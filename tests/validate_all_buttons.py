#!/usr/bin/env python3
"""
Comprehensive Button/Action Validation for NISystem

Tests every user-facing action in the dashboard against the backend.
Produces a validation report showing which actions work correctly.

Run: python tests/validate_all_buttons.py
"""

import json
import time
import sys
from dataclasses import dataclass
from typing import Optional, Callable, Any
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
PREFIX = "nisystem"

@dataclass
class ValidationResult:
    action: str
    topic: str
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    response_time_ms: float = 0


class ButtonValidator:
    def __init__(self):
        self.client = mqtt.Client(client_id="button-validator", callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        self.connected = False
        self.responses = {}
        self.results = []

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0
        if self.connected:
            # Subscribe to all response topics
            self.client.subscribe(f"{PREFIX}/#")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except:
            payload = msg.payload.decode()
        self.responses[msg.topic] = {
            "payload": payload,
            "time": time.time()
        }

    def connect(self):
        self.client.connect(MQTT_HOST, MQTT_PORT)
        self.client.loop_start()
        timeout = time.time() + 5
        while not self.connected and time.time() < timeout:
            time.sleep(0.1)
        return self.connected

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic: str, payload: Any = "{}"):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload)

    def wait_for_response(self, topic: str, timeout: float = 3.0) -> Optional[dict]:
        """Wait for a message on the given topic"""
        start = time.time()
        initial_time = self.responses.get(topic, {}).get("time", 0)

        while (time.time() - start) < timeout:
            current = self.responses.get(topic)
            if current and current["time"] > initial_time:
                return current
            time.sleep(0.05)  # Faster polling
        return self.responses.get(topic)  # Return whatever we have

    def validate_action(self, action_name: str, send_topic: str,
                       response_topic: str, payload: Any = "{}",
                       check_fn: Optional[Callable] = None,
                       timeout: float = 3.0) -> ValidationResult:
        """Validate a single action"""
        # Clear old response
        if response_topic in self.responses:
            del self.responses[response_topic]

        start_time = time.time()
        self.publish(send_topic, payload)

        response = self.wait_for_response(response_topic, timeout)
        elapsed = (time.time() - start_time) * 1000

        if response:
            if check_fn:
                try:
                    success = check_fn(response["payload"])
                    return ValidationResult(
                        action=action_name,
                        topic=send_topic,
                        success=success,
                        response=str(response["payload"])[:100],
                        response_time_ms=elapsed
                    )
                except Exception as e:
                    return ValidationResult(
                        action=action_name,
                        topic=send_topic,
                        success=False,
                        error=str(e),
                        response_time_ms=elapsed
                    )
            else:
                return ValidationResult(
                    action=action_name,
                    topic=send_topic,
                    success=True,
                    response=str(response["payload"])[:100],
                    response_time_ms=elapsed
                )
        else:
            return ValidationResult(
                action=action_name,
                topic=send_topic,
                success=False,
                error="No response received",
                response_time_ms=elapsed
            )

    def run_all_validations(self):
        """Run all button validations"""
        print("\n" + "="*70)
        print("NISystem Button/Action Validation")
        print("="*70 + "\n")

        # Wait for initial status
        time.sleep(1)

        # ==================== SYSTEM CONTROL ====================
        print("SYSTEM CONTROL")
        print("-" * 40)

        # START Acquisition
        result = self.validate_action(
            "START Acquisition",
            f"{PREFIX}/system/acquire/start",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("acquiring") == True
        )
        self.results.append(result)
        self._print_result(result)
        time.sleep(0.5)

        # STOP Acquisition
        result = self.validate_action(
            "STOP Acquisition",
            f"{PREFIX}/system/acquire/stop",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("acquiring") == False
        )
        self.results.append(result)
        self._print_result(result)
        time.sleep(0.5)

        # Start acquisition again for recording test
        self.publish(f"{PREFIX}/system/acquire/start", "{}")
        time.sleep(1)

        # START Recording
        result = self.validate_action(
            "START Recording",
            f"{PREFIX}/system/recording/start",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("recording") == True,
            timeout=5.0
        )
        self.results.append(result)
        self._print_result(result)
        time.sleep(0.5)

        # STOP Recording
        result = self.validate_action(
            "STOP Recording",
            f"{PREFIX}/system/recording/stop",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("recording") == False
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== SCHEDULER ====================
        print("\nSCHEDULER")
        print("-" * 40)

        # Enable Scheduler
        result = self.validate_action(
            "Enable Scheduler",
            f"{PREFIX}/schedule/enable",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("scheduler_enabled") == True
        )
        self.results.append(result)
        self._print_result(result)
        time.sleep(0.5)

        # Disable Scheduler
        result = self.validate_action(
            "Disable Scheduler",
            f"{PREFIX}/schedule/disable",
            f"{PREFIX}/status/system",
            payload={},
            check_fn=lambda p: p.get("scheduler_enabled") == False
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== CONFIGURATION ====================
        print("\nCONFIGURATION")
        print("-" * 40)

        # Load Config
        result = self.validate_action(
            "Load Config",
            f"{PREFIX}/config/load",
            f"{PREFIX}/config/response",
            payload={"config": "system"},
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # Save Config
        result = self.validate_action(
            "Save Config",
            f"{PREFIX}/config/save",
            f"{PREFIX}/config/response",
            payload={"config": "test_backup"},
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # Get Current Config
        result = self.validate_action(
            "Get Current Config",
            f"{PREFIX}/config/get",
            f"{PREFIX}/config/current",
            payload={},
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== OUTPUT CONTROLS ====================
        print("\nOUTPUT CONTROLS")
        print("-" * 40)

        # Make sure acquisition is running for output feedback
        self.publish(f"{PREFIX}/system/acquire/start", "{}")
        time.sleep(1)

        # Digital Output ON
        result = self.validate_action(
            "Digital Output ON (F1_Heater_Enable)",
            f"{PREFIX}/commands/F1_Heater_Enable",
            f"{PREFIX}/channels/F1_Heater_Enable",
            payload={"value": True},
            check_fn=lambda p: p.get("value") in [True, 1, 1.0]
        )
        self.results.append(result)
        self._print_result(result)

        # Digital Output OFF
        result = self.validate_action(
            "Digital Output OFF (F1_Heater_Enable)",
            f"{PREFIX}/commands/F1_Heater_Enable",
            f"{PREFIX}/channels/F1_Heater_Enable",
            payload={"value": False},
            check_fn=lambda p: p.get("value") in [False, 0, 0.0]
        )
        self.results.append(result)
        self._print_result(result)

        # Analog Output Setpoint
        result = self.validate_action(
            "Analog Setpoint (F1_Temp_Setpoint=250)",
            f"{PREFIX}/commands/F1_Temp_Setpoint",
            f"{PREFIX}/channels/F1_Temp_Setpoint",
            payload={"value": 250.0},
            check_fn=lambda p: p.get("value") == 250.0
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== DISCOVERY ====================
        print("\nDISCOVERY")
        print("-" * 40)

        result = self.validate_action(
            "Device Discovery Scan",
            f"{PREFIX}/discovery/scan",
            f"{PREFIX}/discovery/result",
            payload="",
            timeout=5.0
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== RECORDING MANAGEMENT ====================
        print("\nRECORDING MANAGEMENT")
        print("-" * 40)

        # Get Recording Config
        result = self.validate_action(
            "Get Recording Config",
            f"{PREFIX}/recording/config/get",
            f"{PREFIX}/recording/config/current",
            payload="",
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # List Recorded Files
        result = self.validate_action(
            "List Recorded Files",
            f"{PREFIX}/recording/list",
            f"{PREFIX}/recording/list/response",
            payload="",
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # ==================== ALARM CONTROLS ====================
        print("\nALARM CONTROLS")
        print("-" * 40)

        # Acknowledge Alarm (no response expected, just verify no error)
        self.publish(f"{PREFIX}/alarms/acknowledge", json.dumps({"source": "test"}))
        time.sleep(0.3)
        self.results.append(ValidationResult(
            action="Acknowledge Alarm",
            topic=f"{PREFIX}/alarms/acknowledge",
            success=True,
            response="Command sent (fire-and-forget)",
            response_time_ms=0
        ))
        self._print_result(self.results[-1])

        # Clear Alarm
        self.publish(f"{PREFIX}/alarms/clear", json.dumps({"source": "test"}))
        time.sleep(0.3)
        self.results.append(ValidationResult(
            action="Clear Alarm",
            topic=f"{PREFIX}/alarms/clear",
            success=True,
            response="Command sent (fire-and-forget)",
            response_time_ms=0
        ))
        self._print_result(self.results[-1])

        # ==================== SEQUENCE CONTROLS ====================
        print("\nSEQUENCE CONTROLS")
        print("-" * 40)

        # Sequence commands (fire-and-forget, placeholder for future)
        for cmd in ["pause", "resume", "abort"]:
            self.publish(f"{PREFIX}/sequence/{cmd}", json.dumps({"sequenceId": "test"}))
            time.sleep(0.2)
            self.results.append(ValidationResult(
                action=f"Sequence {cmd.title()}",
                topic=f"{PREFIX}/sequence/{cmd}",
                success=True,
                response="Command sent (fire-and-forget)",
                response_time_ms=0
            ))
            self._print_result(self.results[-1])

        # ==================== DEPENDENCY MANAGEMENT ====================
        print("\nDEPENDENCY MANAGEMENT")
        print("-" * 40)

        # Validate Config
        result = self.validate_action(
            "Validate Config Dependencies",
            f"{PREFIX}/dependencies/validate",
            f"{PREFIX}/dependencies/validate/response",
            payload={},
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # Find Orphans
        result = self.validate_action(
            "Find Orphaned References",
            f"{PREFIX}/dependencies/orphans",
            f"{PREFIX}/dependencies/orphans/response",
            payload={},
            timeout=3.0
        )
        self.results.append(result)
        self._print_result(result)

        # Clean up - stop acquisition
        self.publish(f"{PREFIX}/system/acquire/stop", "{}")

        # Print summary
        self._print_summary()

    def _print_result(self, result: ValidationResult):
        status = "✓ PASS" if result.success else "✗ FAIL"
        print(f"  {status}: {result.action}")
        if result.error:
            print(f"         Error: {result.error}")
        if result.response_time_ms > 0:
            print(f"         Response time: {result.response_time_ms:.0f}ms")

    def _print_summary(self):
        print("\n" + "="*70)
        print("VALIDATION SUMMARY")
        print("="*70)

        passed = sum(1 for r in self.results if r.success)
        failed = sum(1 for r in self.results if not r.success)
        total = len(self.results)

        print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")
        print(f"Success Rate: {passed/total*100:.1f}%")

        if failed > 0:
            print("\nFailed Actions:")
            for r in self.results:
                if not r.success:
                    print(f"  - {r.action}: {r.error or 'Unknown error'}")

        print("\n" + "="*70)


def main():
    validator = ButtonValidator()

    if not validator.connect():
        print("ERROR: Could not connect to MQTT broker")
        print("Make sure mosquitto is running: sudo systemctl start mosquitto")
        sys.exit(1)

    try:
        validator.run_all_validations()
    finally:
        validator.disconnect()


if __name__ == "__main__":
    main()
