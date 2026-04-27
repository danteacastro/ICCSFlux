"""
Scenario Test Runner — JSON-driven integration tests for NISystem.

Defines test scenarios as JSON files with steps (inject values, assert alarms,
check channel values, etc.) and runs them against a live DAQ service via MQTT.

Usage:
    python tools/run_scenario.py scenarios/heater_alarm.json --host localhost
    python tools/run_scenario.py scenarios/ --junit-xml results.xml
    python tools/run_scenario.py scenarios/heater_alarm.json --timeout 60
"""

import argparse
import json
import math
import os
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    if __name__ == "__main__":
        print("Error: paho-mqtt is required. Install with: pip install paho-mqtt", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# Scenario Data Model
# ---------------------------------------------------------------------------

@dataclass
class ScenarioStep:
    """A single step in a scenario."""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ScenarioStep':
        action = d.get('action', '')
        params = {k: v for k, v in d.items() if k != 'action'}
        return cls(action=action, params=params)

@dataclass
class Scenario:
    """A complete test scenario."""
    name: str
    description: str = ''
    project: str = ''
    setup: Dict[str, Any] = field(default_factory=dict)
    steps: List[ScenarioStep] = field(default_factory=list)
    timeout: float = 30.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Scenario':
        steps = [ScenarioStep.from_dict(s) for s in d.get('steps', [])]
        return cls(
            name=d.get('name', 'Unnamed'),
            description=d.get('description', ''),
            project=d.get('project', ''),
            setup=d.get('setup', {}),
            steps=steps,
            timeout=d.get('timeout', 30.0),
        )

    @classmethod
    def from_file(cls, path: str) -> 'Scenario':
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_dict(json.load(f))

@dataclass
class StepResult:
    """Result of executing a single step."""
    step_index: int
    action: str
    success: bool
    message: str = ''
    duration: float = 0.0

@dataclass
class ScenarioResult:
    """Result of running a complete scenario."""
    scenario_name: str
    success: bool
    step_results: List[StepResult] = field(default_factory=list)
    error: str = ''
    duration: float = 0.0

    @property
    def failed_steps(self) -> List[StepResult]:
        return [s for s in self.step_results if not s.success]

# ---------------------------------------------------------------------------
# MQTT Client Wrapper
# ---------------------------------------------------------------------------

class ScenarioMQTTClient:
    """MQTT client for scenario execution with message caching."""

    def __init__(self, host: str, port: int, base_topic: str = 'nisystem',
                 username: Optional[str] = None, password: Optional[str] = None):
        self.host = host
        self.port = port
        self.base_topic = base_topic
        self.username = username
        self.password = password

        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._channel_values: Dict[str, float] = {}
        self._alarm_states: Dict[str, str] = {}
        self._system_state: str = 'unknown'
        self._recording_state: str = 'stopped'
        self._received_messages: List[Dict] = []

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to MQTT broker and subscribe to status topics."""
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f'scenario-runner-{os.getpid()}',
        )
        if self.username:
            self._client.username_pw_set(self.username, self.password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        try:
            self._client.connect(self.host, self.port, keepalive=60)
        except Exception as e:
            print(f"  Connection failed: {e}", file=sys.stderr)
            return False

        self._client.loop_start()

        deadline = time.time() + timeout
        while not self._connected and time.time() < deadline:
            time.sleep(0.05)

        return self._connected

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False

    def publish(self, topic: str, payload: Any, qos: int = 1):
        """Publish to a topic (relative to base_topic)."""
        full_topic = f"{self.base_topic}/{topic}" if not topic.startswith(self.base_topic) else topic
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(full_topic, payload, qos=qos)

    def get_channel_value(self, channel: str) -> Optional[float]:
        return self._channel_values.get(channel)

    def get_alarm_state(self, alarm: str) -> Optional[str]:
        return self._alarm_states.get(alarm)

    def get_system_state(self) -> str:
        return self._system_state

    def get_recording_state(self) -> str:
        return self._recording_state

    def wait_for_condition(self, condition: Callable[[], bool],
                           timeout: float = 10.0, poll_interval: float = 0.1) -> bool:
        """Wait until condition returns True or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(poll_interval)
        return False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            # Subscribe to key status topics
            client.subscribe(f"{self.base_topic}/#")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload
            self._received_messages.append({'topic': topic, 'payload': payload, 'ts': time.time()})
            return

        self._received_messages.append({'topic': topic, 'payload': payload, 'ts': time.time()})

        # Parse channel batch updates
        if '/channels/batch' in topic:
            if isinstance(payload, dict):
                values = payload.get('values', payload)
                for ch_name, val in values.items():
                    if isinstance(val, dict):
                        self._channel_values[ch_name] = val.get('value', val.get('v', 0))
                    else:
                        try:
                            self._channel_values[ch_name] = float(val)
                        except (TypeError, ValueError):
                            pass

        # Parse alarm updates
        elif '/alarms' in topic:
            if isinstance(payload, dict):
                for alarm_id, alarm_data in payload.items():
                    if isinstance(alarm_data, dict):
                        self._alarm_states[alarm_id] = alarm_data.get('state', 'unknown')
                    else:
                        self._alarm_states[alarm_id] = str(alarm_data)
            elif isinstance(payload, list):
                for alarm_data in payload:
                    if isinstance(alarm_data, dict):
                        aid = alarm_data.get('id', alarm_data.get('channel', ''))
                        self._alarm_states[aid] = alarm_data.get('state', 'unknown')

        # Parse system state
        elif '/status/system' in topic:
            if isinstance(payload, dict):
                self._system_state = payload.get('acquisitionState', payload.get('state', 'unknown'))
            elif isinstance(payload, str):
                self._system_state = payload

        # Parse recording state
        elif '/recording/status' in topic or '/status/recording' in topic:
            if isinstance(payload, dict):
                self._recording_state = payload.get('state', 'unknown')

# ---------------------------------------------------------------------------
# Step Executors
# ---------------------------------------------------------------------------

COMPARE_OPS = {
    '>': lambda a, b: a > b,
    '<': lambda a, b: a < b,
    '>=': lambda a, b: a >= b,
    '<=': lambda a, b: a <= b,
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '~=': lambda a, b: math.isclose(a, b, rel_tol=0.05, abs_tol=0.5),
}

def _execute_step(client: ScenarioMQTTClient, step: ScenarioStep) -> StepResult:
    """Execute a single scenario step."""
    start = time.time()
    action = step.action
    p = step.params

    try:
        if action == 'wait':
            seconds = float(p.get('seconds', 1.0))
            time.sleep(seconds)
            return StepResult(0, action, True, f"Waited {seconds}s", time.time() - start)

        elif action == 'start_acquisition':
            client.publish('commands/acquire', {'action': 'start'})
            ok = client.wait_for_condition(
                lambda: client.get_system_state() in ('RUNNING', 'running'),
                timeout=p.get('timeout', 10.0),
            )
            return StepResult(0, action, ok,
                              'Acquisition started' if ok else f'Acquisition did not start (state: {client.get_system_state()})',
                              time.time() - start)

        elif action == 'stop_acquisition':
            client.publish('commands/acquire', {'action': 'stop'})
            ok = client.wait_for_condition(
                lambda: client.get_system_state() in ('STOPPED', 'stopped', 'IDLE', 'idle'),
                timeout=p.get('timeout', 10.0),
            )
            return StepResult(0, action, ok,
                              'Acquisition stopped' if ok else f'Acquisition did not stop (state: {client.get_system_state()})',
                              time.time() - start)

        elif action == 'inject_value':
            channel = p.get('channel', '')
            value = p.get('value', 0)
            client._channel_values[channel] = float(value)
            # Also publish so the DAQ service can pick it up
            client.publish(f'inject/{channel}', {'value': value})
            return StepResult(0, action, True, f"Injected {channel}={value}", time.time() - start)

        elif action == 'set_output':
            channel = p.get('channel', '')
            value = p.get('value', 0)
            client.publish('commands/output', {'channel': channel, 'value': value})
            return StepResult(0, action, True, f"Set output {channel}={value}", time.time() - start)

        elif action == 'assert_value':
            channel = p.get('channel', '')
            op_str = p.get('operator', '==')
            expected = float(p.get('value', 0))
            timeout = float(p.get('timeout', 5.0))
            op_fn = COMPARE_OPS.get(op_str)

            if op_fn is None:
                return StepResult(0, action, False, f"Unknown operator: {op_str}", time.time() - start)

            actual = None

            def _check():
                nonlocal actual
                actual = client.get_channel_value(channel)
                return actual is not None and op_fn(actual, expected)

            ok = client.wait_for_condition(_check, timeout=timeout)
            if actual is None:
                return StepResult(0, action, False,
                                  f"Channel {channel!r} not found", time.time() - start)
            return StepResult(0, action, ok,
                              f"{channel}={actual} {op_str} {expected}: {'PASS' if ok else 'FAIL'}",
                              time.time() - start)

        elif action == 'assert_alarm':
            alarm = p.get('alarm', '')
            expected_state = p.get('state', 'active')
            timeout = float(p.get('timeout', 5.0))
            actual = None

            def _check():
                nonlocal actual
                actual = client.get_alarm_state(alarm)
                return actual == expected_state

            ok = client.wait_for_condition(_check, timeout=timeout)
            return StepResult(0, action, ok,
                              f"Alarm {alarm!r} state={actual} (expected {expected_state}): {'PASS' if ok else 'FAIL'}",
                              time.time() - start)

        elif action == 'assert_recording':
            expected_state = p.get('state', 'running')
            timeout = float(p.get('timeout', 5.0))

            def _check():
                return client.get_recording_state() == expected_state

            ok = client.wait_for_condition(_check, timeout=timeout)
            return StepResult(0, action, ok,
                              f"Recording state={client.get_recording_state()} (expected {expected_state}): {'PASS' if ok else 'FAIL'}",
                              time.time() - start)

        elif action == 'start_recording':
            client.publish('commands/recording', {'action': 'start'})
            return StepResult(0, action, True, "Start recording command sent", time.time() - start)

        elif action == 'stop_recording':
            client.publish('commands/recording', {'action': 'stop'})
            return StepResult(0, action, True, "Stop recording command sent", time.time() - start)

        elif action == 'run_script':
            script_id = p.get('script', p.get('id', ''))
            client.publish('commands/script', {'action': 'run', 'scriptId': script_id})
            return StepResult(0, action, True, f"Script {script_id!r} triggered", time.time() - start)

        elif action == 'assert_mqtt':
            topic_pattern = p.get('topic', '')
            timeout = float(p.get('timeout', 5.0))
            payload_contains = p.get('contains', None)
            start_check = time.time()

            def _check():
                for msg in client._received_messages:
                    if msg['ts'] < start_check:
                        continue
                    if _topic_matches(msg['topic'], topic_pattern):
                        if payload_contains is None:
                            return True
                        payload_str = json.dumps(msg['payload']) if not isinstance(msg['payload'], str) else msg['payload']
                        if payload_contains in payload_str:
                            return True
                return False

            ok = client.wait_for_condition(_check, timeout=timeout)
            return StepResult(0, action, ok,
                              f"MQTT assertion on {topic_pattern!r}: {'PASS' if ok else 'TIMEOUT'}",
                              time.time() - start)

        elif action == 'publish':
            topic = p.get('topic', '')
            payload = p.get('payload', '')
            client.publish(topic, payload)
            return StepResult(0, action, True, f"Published to {topic}", time.time() - start)

        else:
            return StepResult(0, action, False, f"Unknown action: {action!r}", time.time() - start)

    except Exception as e:
        return StepResult(0, action, False, f"Exception: {e}", time.time() - start)

def _topic_matches(topic: str, pattern: str) -> bool:
    """Simple MQTT topic pattern matching (supports + and #)."""
    if pattern == '#':
        return True

    t_parts = topic.split('/')
    p_parts = pattern.split('/')

    ti, pi = 0, 0
    while pi < len(p_parts):
        if p_parts[pi] == '#':
            return True
        if ti >= len(t_parts):
            return False
        if p_parts[pi] != '+' and p_parts[pi] != t_parts[ti]:
            return False
        ti += 1
        pi += 1

    return ti == len(t_parts)

# ---------------------------------------------------------------------------
# Scenario Runner
# ---------------------------------------------------------------------------

def run_scenario(scenario: Scenario, host: str = 'localhost', port: int = 1883,
                 base_topic: str = 'nisystem',
                 username: Optional[str] = None, password: Optional[str] = None) -> ScenarioResult:
    """Run a single scenario against a live DAQ service."""
    result = ScenarioResult(scenario_name=scenario.name, success=True)
    start_time = time.time()

    print(f"  Running: {scenario.name}")
    if scenario.description:
        print(f"    {scenario.description}")

    client = ScenarioMQTTClient(host, port, base_topic, username, password)
    if not client.connect():
        result.success = False
        result.error = "Failed to connect to MQTT broker"
        result.duration = time.time() - start_time
        return result

    try:
        for i, step in enumerate(scenario.steps):
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > scenario.timeout:
                result.success = False
                result.error = f"Scenario timeout after {elapsed:.1f}s (limit: {scenario.timeout}s)"
                break

            step_result = _execute_step(client, step)
            step_result.step_index = i
            result.step_results.append(step_result)

            status = "PASS" if step_result.success else "FAIL"
            print(f"    [{status}] Step {i + 1}: {step.action} — {step_result.message}")

            if not step_result.success:
                result.success = False
                if step.params.get('abort_on_fail', True):
                    result.error = f"Step {i + 1} failed: {step_result.message}"
                    break

    except Exception as e:
        result.success = False
        result.error = f"Unexpected error: {e}\n{traceback.format_exc()}"
    finally:
        client.disconnect()

    result.duration = time.time() - start_time
    status = "PASSED" if result.success else "FAILED"
    print(f"  Result: {status} ({result.duration:.1f}s)")
    return result

def run_scenarios_from_path(path: str, **kwargs) -> List[ScenarioResult]:
    """Run scenarios from a file or directory."""
    target = Path(path)
    results = []

    if target.is_file():
        scenario = Scenario.from_file(str(target))
        results.append(run_scenario(scenario, **kwargs))
    elif target.is_dir():
        for entry in sorted(target.iterdir()):
            if entry.suffix == '.json' and entry.is_file():
                try:
                    scenario = Scenario.from_file(str(entry))
                    results.append(run_scenario(scenario, **kwargs))
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"  Skipping {entry.name}: {e}", file=sys.stderr)
    else:
        print(f"Error: {path} not found", file=sys.stderr)

    return results

# ---------------------------------------------------------------------------
# JUnit XML Output
# ---------------------------------------------------------------------------

def results_to_junit_xml(results: List[ScenarioResult]) -> str:
    """Convert scenario results to JUnit XML format."""
    testsuites = ET.Element('testsuites')
    testsuite = ET.SubElement(testsuites, 'testsuite',
                              name='NISystem Scenarios',
                              tests=str(len(results)),
                              failures=str(sum(1 for r in results if not r.success)),
                              time=str(sum(r.duration for r in results)))

    for result in results:
        testcase = ET.SubElement(testsuite, 'testcase',
                                  name=result.scenario_name,
                                  time=str(result.duration))
        if not result.success:
            failure = ET.SubElement(testcase, 'failure',
                                     message=result.error or 'Scenario failed')
            details = []
            for sr in result.step_results:
                status = 'PASS' if sr.success else 'FAIL'
                details.append(f"[{status}] Step {sr.step_index + 1}: {sr.action} — {sr.message}")
            failure.text = '\n'.join(details)

    return ET.tostring(testsuites, encoding='unicode', xml_declaration=True)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Run NISystem test scenarios',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/run_scenario.py scenarios/heater_alarm.json
  python tools/run_scenario.py scenarios/ --junit-xml results.xml
  python tools/run_scenario.py scenarios/test.json --host 192.168.1.1 --timeout 60
        """,
    )
    parser.add_argument('path', help='Scenario JSON file or directory')
    parser.add_argument('--host', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--base-topic', default='nisystem', help='Base MQTT topic')
    parser.add_argument('--username', '-u', help='MQTT username')
    parser.add_argument('--password', '-p', help='MQTT password')
    parser.add_argument('--timeout', type=float, default=0,
                        help='Override scenario timeout (0 = use scenario default)')
    parser.add_argument('--junit-xml', default=None,
                        help='Write JUnit XML results to file')
    args = parser.parse_args()

    print("=" * 60)
    print("NISystem Scenario Test Runner")
    print("=" * 60)

    results = run_scenarios_from_path(
        args.path,
        host=args.host,
        port=args.port,
        base_topic=args.base_topic,
        username=args.username,
        password=args.password,
    )

    if not results:
        print("No scenarios found or run.")
        sys.exit(2)

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    print(f"Results: {passed} passed, {failed} failed out of {len(results)} scenarios")
    total_time = sum(r.duration for r in results)
    print(f"Total time: {total_time:.1f}s")

    # Write JUnit XML if requested
    if args.junit_xml:
        xml_content = results_to_junit_xml(results)
        with open(args.junit_xml, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print(f"JUnit XML written to: {args.junit_xml}")

    sys.exit(1 if failed > 0 else 0)

if __name__ == '__main__':
    main()
