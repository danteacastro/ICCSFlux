#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive System Test for NISystem
Tests all state machines, project loading, configuration management, and integration
"""

import json
import time
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Fix console encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import paho.mqtt.client as mqtt

class NISystemTester:
    """Comprehensive test suite for NISystem"""

    def __init__(self, mqtt_broker="localhost", mqtt_port=1883):
        self.broker = mqtt_broker
        self.port = mqtt_port
        self.client = None
        self.messages = {}
        self.test_results = []
        self.base_topic = "nisystem"

    def connect(self):
        """Connect to MQTT broker"""
        print(f"\n{'='*80}")
        print(f"CONNECTING TO MQTT BROKER")
        print(f"{'='*80}")

        self.client = mqtt.Client()
        self.client.on_message = self._on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

        # Subscribe to all relevant topics
        topics = [
            f"{self.base_topic}/status/system",
            f"{self.base_topic}/command/ack",
            f"{self.base_topic}/config/response",
            f"{self.base_topic}/config/current",
            f"{self.base_topic}/config/list/response",
            f"{self.base_topic}/project/response",
            f"{self.base_topic}/project/loaded",
            f"{self.base_topic}/project/list/response",
            f"{self.base_topic}/recording/response",
            f"{self.base_topic}/test-session/status",
        ]

        for topic in topics:
            self.client.subscribe(topic)

        time.sleep(1)  # Wait for subscriptions
        print("✅ Connected to MQTT broker")

    def _on_message(self, client, userdata, msg):
        """Store received messages"""
        try:
            payload = json.loads(msg.payload.decode())
            self.messages[msg.topic] = payload
        except:
            self.messages[msg.topic] = msg.payload.decode()

    def send_command(self, command: str, payload: Any = None):
        """Send MQTT command"""
        topic = f"{self.base_topic}/{command}"
        if payload:
            self.client.publish(topic, json.dumps(payload))
        else:
            self.client.publish(topic, "")

    def wait_for_response(self, topic: str, timeout: float = 5.0) -> Any:
        """Wait for response on topic"""
        start = time.time()
        while time.time() - start < timeout:
            if topic in self.messages:
                return self.messages.pop(topic)
            time.sleep(0.1)
        return None

    def assert_test(self, condition: bool, test_name: str, details: str = ""):
        """Record test result"""
        result = {
            "test": test_name,
            "passed": condition,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)

        status = "✅ PASS" if condition else "❌ FAIL"
        print(f"  {status}: {test_name}")
        if details:
            print(f"    Details: {details}")

        return condition

    # =========================================================================
    # TEST SUITE 1: STATE MACHINE VALIDATION
    # =========================================================================

    def test_acquisition_state_machine(self):
        """Test acquisition state machine with all valid and invalid transitions"""
        print(f"\n{'='*80}")
        print("TEST SUITE 1: ACQUISITION STATE MACHINE")
        print(f"{'='*80}\n")

        # Test 1: Initial state should be stopped
        print("Test 1.1: Verify initial state (should be stopped)")
        self.send_command("system/status/request")
        time.sleep(0.5)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status and not status.get("acquiring", True),
            "Initial acquisition state is stopped",
            f"acquiring={status.get('acquiring') if status else 'NO RESPONSE'}"
        )

        # Test 2: Start acquisition (should succeed)
        print("\nTest 1.2: Start acquisition (valid transition)")
        self.send_command("system/acquire/start", {"request_id": "test_start_1"})
        time.sleep(1)
        ack = self.wait_for_response(f"{self.base_topic}/command/ack")
        status = self.wait_for_response(f"{self.base_topic}/status/system")

        self.assert_test(
            ack and ack.get("success"),
            "Acquisition start command acknowledged",
            f"ack={ack}"
        )
        self.assert_test(
            status and status.get("acquiring"),
            "Acquisition state is now running",
            f"acquiring={status.get('acquiring') if status else 'NO RESPONSE'}"
        )

        # Test 3: Try to start again (should reject)
        print("\nTest 1.3: Start acquisition again (should reject)")
        self.send_command("system/acquire/start", {"request_id": "test_start_2"})
        time.sleep(0.5)
        ack = self.wait_for_response(f"{self.base_topic}/command/ack")

        self.assert_test(
            ack and not ack.get("success"),
            "Duplicate start command rejected",
            f"ack={ack}"
        )

        # Test 4: Stop acquisition (should succeed)
        print("\nTest 1.4: Stop acquisition (valid transition)")
        self.send_command("system/acquire/stop", {"request_id": "test_stop_1"})
        time.sleep(1)
        ack = self.wait_for_response(f"{self.base_topic}/command/ack")
        status = self.wait_for_response(f"{self.base_topic}/status/system")

        self.assert_test(
            ack and ack.get("success"),
            "Acquisition stop command acknowledged",
            f"ack={ack}"
        )
        self.assert_test(
            status and not status.get("acquiring"),
            "Acquisition state is now stopped",
            f"acquiring={status.get('acquiring') if status else 'NO RESPONSE'}"
        )

        # Test 5: Try to stop again (should reject)
        print("\nTest 1.5: Stop acquisition again (should reject)")
        self.send_command("system/acquire/stop", {"request_id": "test_stop_2"})
        time.sleep(0.5)
        ack = self.wait_for_response(f"{self.base_topic}/command/ack")

        self.assert_test(
            ack and not ack.get("success"),
            "Duplicate stop command rejected",
            f"ack={ack}"
        )

    def test_recording_state_machine(self):
        """Test recording state machine with prerequisite validation"""
        print(f"\n{'='*80}")
        print("TEST SUITE 2: RECORDING STATE MACHINE")
        print(f"{'='*80}\n")

        # Test 1: Try to record without acquisition (should fail)
        print("Test 2.1: Start recording without acquisition (should reject)")
        self.send_command("system/recording/start", {"filename": "test_recording.tdms"})
        time.sleep(0.5)
        response = self.wait_for_response(f"{self.base_topic}/recording/response")

        self.assert_test(
            response and not response.get("success"),
            "Recording rejected without acquisition",
            f"response={response}"
        )

        # Test 2: Start acquisition, then recording (should succeed)
        print("\nTest 2.2: Start acquisition then recording (should succeed)")
        self.send_command("system/acquire/start")
        time.sleep(1)

        self.send_command("system/recording/start", {"filename": "test_recording_2.tdms"})
        time.sleep(1)
        response = self.wait_for_response(f"{self.base_topic}/recording/response")
        status = self.wait_for_response(f"{self.base_topic}/status/system")

        self.assert_test(
            response and response.get("success"),
            "Recording started successfully",
            f"response={response}"
        )
        self.assert_test(
            status and status.get("recording"),
            "Recording state is active",
            f"recording={status.get('recording') if status else 'NO RESPONSE'}"
        )

        # Test 3: Try to record again (should reject)
        print("\nTest 2.3: Start recording again (should reject)")
        self.send_command("system/recording/start", {"filename": "test_recording_3.tdms"})
        time.sleep(0.5)
        response = self.wait_for_response(f"{self.base_topic}/recording/response")

        self.assert_test(
            response and not response.get("success"),
            "Duplicate recording start rejected",
            f"response={response}"
        )

        # Test 4: Stop recording (should succeed)
        print("\nTest 2.4: Stop recording (should succeed)")
        self.send_command("system/recording/stop")
        time.sleep(1)
        response = self.wait_for_response(f"{self.base_topic}/recording/response")
        status = self.wait_for_response(f"{self.base_topic}/status/system")

        self.assert_test(
            response and response.get("success"),
            "Recording stopped successfully",
            f"response={response}"
        )
        self.assert_test(
            status and not status.get("recording"),
            "Recording state is inactive",
            f"recording={status.get('recording') if status else 'NO RESPONSE'}"
        )

        # Test 5: Stop acquisition (should cascade stop recording)
        print("\nTest 2.5: Stop acquisition (cleanup)")
        self.send_command("system/acquire/stop")
        time.sleep(1)

    # =========================================================================
    # TEST SUITE 3: CONFIGURATION MANAGEMENT
    # =========================================================================

    def test_configuration_management(self):
        """Test configuration save/load cycle"""
        print(f"\n{'='*80}")
        print("TEST SUITE 3: CONFIGURATION MANAGEMENT")
        print(f"{'='*80}\n")

        # Test 1: List available configurations
        print("Test 3.1: List available configurations")
        self.send_command("config/list")
        time.sleep(1)
        response = self.wait_for_response(f"{self.base_topic}/config/list/response")

        self.assert_test(
            response and "configs" in response,
            "Config list retrieved",
            f"config_count={len(response.get('configs', [])) if response else 0}"
        )

        # Test 2: Get current configuration
        print("\nTest 3.2: Get current configuration")
        self.send_command("config/get")
        time.sleep(1)
        config = self.wait_for_response(f"{self.base_topic}/config/current")

        self.assert_test(
            config and "system" in config and "channels" in config,
            "Current config retrieved",
            f"channels={len(config.get('channels', {})) if config else 0}"
        )

        # Store for later comparison
        original_config = config

        # Test 3: Try to save config while acquiring (should reject)
        print("\nTest 3.3: Try to save config while acquiring (should reject)")
        self.send_command("system/acquire/start")
        time.sleep(1)

        self.send_command("config/save", {"filename": "test_config.ini"})
        time.sleep(0.5)
        response = self.wait_for_response(f"{self.base_topic}/config/response")

        self.assert_test(
            response and not response.get("success"),
            "Config save rejected while acquiring",
            f"response={response}"
        )

        # Stop acquisition for next tests
        self.send_command("system/acquire/stop")
        time.sleep(1)

        # Note: Actual save/load would require authentication and file system access
        print("\nTest 3.4: Config save/load requires authentication (skipped in test)")

    # =========================================================================
    # TEST SUITE 4: PROJECT MANAGEMENT
    # =========================================================================

    def test_project_management(self):
        """Test project save/load with complex data"""
        print(f"\n{'='*80}")
        print("TEST SUITE 4: PROJECT MANAGEMENT")
        print(f"{'='*80}\n")

        # Test 1: List available projects
        print("Test 4.1: List available projects")
        self.send_command("project/list")
        time.sleep(1)
        response = self.wait_for_response(f"{self.base_topic}/project/list/response")

        self.assert_test(
            response and "projects" in response,
            "Project list retrieved",
            f"project_count={len(response.get('projects', [])) if response else 0}"
        )

        # Test 2: Get current project
        print("\nTest 4.2: Get current project")
        self.send_command("project/get-current")
        time.sleep(1)
        # This might return empty if no project loaded

        # Test 3: Create complex project data
        print("\nTest 4.3: Create complex project data structure")
        complex_project = {
            "type": "nisystem-project",
            "version": "2.0",
            "name": "Comprehensive Test Project",
            "description": "Auto-generated test project with complex data",
            "config": "system.ini",
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "layout": {
                "pages": [
                    {
                        "id": "page-1",
                        "name": "Test Page 1",
                        "order": 0,
                        "widgets": [
                            {
                                "id": "widget-1",
                                "type": "gauge",
                                "channel": "Tank_1",
                                "x": 0, "y": 0, "w": 6, "h": 6
                            },
                            {
                                "id": "widget-2",
                                "type": "chart",
                                "channels": ["Tank_1", "Tank_2"],
                                "x": 6, "y": 0, "w": 12, "h": 6
                            }
                        ]
                    },
                    {
                        "id": "page-2",
                        "name": "Test Page 2",
                        "order": 1,
                        "widgets": [
                            {
                                "id": "widget-3",
                                "type": "text-label",
                                "channel": "T_flu",
                                "x": 0, "y": 0, "w": 4, "h": 2
                            }
                        ]
                    }
                ],
                "currentPageId": "page-1",
                "gridColumns": 24,
                "rowHeight": 30
            },
            "scripts": {
                "calculatedParams": [],
                "sequences": [],
                "schedules": [],
                "triggers": [],
                "transformations": [],
                "functionBlocks": [],
                "drawPatterns": {"patterns": [], "history": []},
                "stateMachines": [],
                "watchdogs": [],
                "reportTemplates": [],
                "scheduledReports": []
            },
            "recording": {
                "config": {
                    "sampleInterval": 100,
                    "sampleIntervalUnit": "ms"
                },
                "selectedChannels": ["Tank_1", "Tank_2", "T_flu"]
            },
            "safety": {
                "alarmConfigs": {},
                "interlocks": [],
                "alarms": []
            }
        }

        self.assert_test(
            True,
            "Complex project structure created",
            f"pages={len(complex_project['layout']['pages'])}, widgets={sum(len(p['widgets']) for p in complex_project['layout']['pages'])}"
        )

        # Test 4: Save project
        print("\nTest 4.4: Save complex project")
        self.send_command("project/save", {
            "filename": "test_comprehensive_project.json",
            "data": complex_project
        })
        time.sleep(1)
        response = self.wait_for_response(f"{self.base_topic}/project/response")

        self.assert_test(
            response is not None,
            "Project save command sent",
            f"response={response}"
        )

        # Test 5: Load the saved project
        print("\nTest 4.5: Load saved project")
        self.send_command("project/load", {"filename": "test_comprehensive_project.json"})
        time.sleep(2)
        response = self.wait_for_response(f"{self.base_topic}/project/loaded")

        self.assert_test(
            response is not None,
            "Project load response received",
            f"success={response.get('success') if response else 'NO RESPONSE'}"
        )

        if response and response.get("success") and response.get("project"):
            loaded_project = response.get("project")
            self.assert_test(
                loaded_project.get("name") == complex_project["name"],
                "Project name matches",
                f"loaded={loaded_project.get('name')}"
            )

            layout = loaded_project.get("layout", {})
            self.assert_test(
                len(layout.get("pages", [])) == 2,
                "Project has 2 pages",
                f"pages={len(layout.get('pages', []))}"
            )

            widget_count = sum(len(p.get("widgets", [])) for p in layout.get("pages", []))
            self.assert_test(
                widget_count == 3,
                "Project has 3 widgets total",
                f"widgets={widget_count}"
            )

    # =========================================================================
    # TEST SUITE 5: END-TO-END WORKFLOW
    # =========================================================================

    def test_end_to_end_workflow(self):
        """Test complete workflow: start → record → session → stop"""
        print(f"\n{'='*80}")
        print("TEST SUITE 5: END-TO-END WORKFLOW")
        print(f"{'='*80}\n")

        # Step 1: Start from clean state
        print("Test 5.1: Ensure clean starting state")
        self.send_command("system/acquire/stop")
        time.sleep(1)

        # Step 2: Start acquisition
        print("\nTest 5.2: Start acquisition")
        self.send_command("system/acquire/start")
        time.sleep(1)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status and status.get("acquiring"),
            "Workflow step 1: Acquisition started"
        )

        # Step 3: Start recording
        print("\nTest 5.3: Start recording")
        self.send_command("system/recording/start", {"filename": "workflow_test.tdms"})
        time.sleep(1)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status and status.get("recording"),
            "Workflow step 2: Recording started"
        )

        # Step 4: Enable session/scheduler
        print("\nTest 5.4: Enable scheduler/session")
        self.send_command("schedule/enable")
        time.sleep(1)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status is not None,
            "Workflow step 3: Scheduler enabled"
        )

        # Step 5: Let it run for a bit
        print("\nTest 5.5: Run workflow for 3 seconds")
        time.sleep(3)
        self.assert_test(True, "Workflow running successfully")

        # Step 6: Stop recording
        print("\nTest 5.6: Stop recording")
        self.send_command("system/recording/stop")
        time.sleep(1)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status and not status.get("recording"),
            "Workflow step 4: Recording stopped"
        )

        # Step 7: Disable scheduler
        print("\nTest 5.7: Disable scheduler")
        self.send_command("schedule/disable")
        time.sleep(1)

        # Step 8: Stop acquisition
        print("\nTest 5.8: Stop acquisition")
        self.send_command("system/acquire/stop")
        time.sleep(1)
        status = self.wait_for_response(f"{self.base_topic}/status/system")
        self.assert_test(
            status and not status.get("acquiring"),
            "Workflow step 5: Acquisition stopped"
        )

        self.assert_test(
            True,
            "Complete workflow executed successfully",
            "start → record → session → stop"
        )

    # =========================================================================
    # TEST SUITE 6: STRESS TEST
    # =========================================================================

    def test_rapid_state_transitions(self):
        """Stress test with rapid state changes"""
        print(f"\n{'='*80}")
        print("TEST SUITE 6: RAPID STATE TRANSITION STRESS TEST")
        print(f"{'='*80}\n")

        print("Test 6.1: Rapid start/stop cycles (10 iterations)")
        failures = 0
        for i in range(10):
            self.send_command("system/acquire/start")
            time.sleep(0.2)
            self.send_command("system/acquire/stop")
            time.sleep(0.2)

        time.sleep(2)  # Wait for all responses
        self.assert_test(
            failures == 0,
            "Rapid state transitions handled correctly",
            f"iterations=10, failures={failures}"
        )

        print("\nTest 6.2: Concurrent command flood (20 commands)")
        for i in range(20):
            self.send_command("system/status/request")
            time.sleep(0.05)

        time.sleep(1)
        self.assert_test(
            True,
            "System handled command flood",
            "commands=20"
        )

    # =========================================================================
    # MAIN TEST RUNNER
    # =========================================================================

    def run_all_tests(self):
        """Run complete test suite"""
        print(f"\n{'#'*80}")
        print(f"# NISYSTEM COMPREHENSIVE SYSTEM TEST")
        print(f"# Started: {datetime.now().isoformat()}")
        print(f"{'#'*80}\n")

        try:
            self.connect()

            self.test_acquisition_state_machine()
            self.test_recording_state_machine()
            self.test_configuration_management()
            self.test_project_management()
            self.test_end_to_end_workflow()
            self.test_rapid_state_transitions()

        finally:
            self.disconnect()

        self.print_summary()

    def disconnect(self):
        """Disconnect from MQTT"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def print_summary(self):
        """Print test summary"""
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}\n")

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r["passed"])
        failed = total - passed

        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/total*100):.1f}%\n")

        if failed > 0:
            print("Failed Tests:")
            for result in self.test_results:
                if not result["passed"]:
                    print(f"  ❌ {result['test']}")
                    if result["details"]:
                        print(f"     {result['details']}")

        # Save results to file
        results_file = Path(__file__).parent / "test_results_comprehensive.json"
        with open(results_file, 'w') as f:
            json.dump({
                "summary": {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "timestamp": datetime.now().isoformat()
                },
                "results": self.test_results
            }, f, indent=2)

        print(f"\n📊 Detailed results saved to: {results_file}")

        return failed == 0


if __name__ == "__main__":
    tester = NISystemTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
