#!/usr/bin/env python3
"""
Script Control Loop Tests for NISystem

Tests the complete control loop where Python scripts:
1. Subscribe to hardware input tags (sensors)
2. Compute derived values and make control decisions
3. Write to digital outputs (solenoid valves, relays)
4. Write to analog outputs (motor speed, heater power)
5. Verify outputs change hardware state

This simulates real lab experiments with:
- Loop schedules (continuous control loops)
- Draw schedules (timed sequences)
- Solenoid valve control
- PID-like control algorithms

Run with: python -m pytest tests/test_script_control_loop.py -v
"""

import json
import math
import time
import unittest
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import paho.mqtt.client as mqtt

# Test configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
SYSTEM_PREFIX = "nisystem"

# =============================================================================
# HARDWARE I/O SIMULATION
# =============================================================================

class OutputType(Enum):
    DIGITAL = "digital"
    ANALOG = "analog"

@dataclass
class DigitalOutput:
    """Simulates a digital output (relay, solenoid valve)"""
    name: str
    state: bool = False  # False = OFF/CLOSED, True = ON/OPEN
    last_changed: float = 0.0
    change_count: int = 0

    def set_state(self, state: bool):
        if self.state != state:
            self.state = state
            self.last_changed = time.time()
            self.change_count += 1

@dataclass
class AnalogOutput:
    """Simulates an analog output (0-10V, 4-20mA, etc.)"""
    name: str
    value: float = 0.0
    min_value: float = 0.0
    max_value: float = 100.0
    last_changed: float = 0.0

    def set_value(self, value: float):
        # Clamp to range
        self.value = max(self.min_value, min(self.max_value, value))
        self.last_changed = time.time()

class HardwareIOSimulator:
    """
    Simulates the NI hardware I/O system.

    In real system:
    - Digital outputs control solenoid valves, relays
    - Analog outputs control motor speed, heater power, etc.
    - Scripts write to these via MQTT commands
    """

    def __init__(self):
        # Digital outputs (solenoid valves, relays)
        self.digital_outputs: Dict[str, DigitalOutput] = {
            "Valve_Inlet": DigitalOutput("Valve_Inlet"),
            "Valve_Outlet": DigitalOutput("Valve_Outlet"),
            "Valve_Bypass": DigitalOutput("Valve_Bypass"),
            "Heater_Enable": DigitalOutput("Heater_Enable"),
            "Pump_Enable": DigitalOutput("Pump_Enable"),
            "Alarm_Horn": DigitalOutput("Alarm_Horn"),
        }

        # Analog outputs (0-100% scaled)
        self.analog_outputs: Dict[str, AnalogOutput] = {
            "Motor_Speed_Setpoint": AnalogOutput("Motor_Speed_Setpoint", max_value=100.0),
            "Heater_Power": AnalogOutput("Heater_Power", max_value=100.0),
            "Flow_Setpoint": AnalogOutput("Flow_Setpoint", max_value=50.0),
            "Pressure_Setpoint": AnalogOutput("Pressure_Setpoint", max_value=150.0),
        }

        # Track all output commands received
        self.command_history: List[Dict] = []

    def write_digital(self, name: str, state: bool) -> bool:
        """Write to a digital output"""
        if name in self.digital_outputs:
            self.digital_outputs[name].set_state(state)
            self.command_history.append({
                "type": "digital",
                "name": name,
                "value": state,
                "timestamp": time.time()
            })
            return True
        return False

    def write_analog(self, name: str, value: float) -> bool:
        """Write to an analog output"""
        if name in self.analog_outputs:
            self.analog_outputs[name].set_value(value)
            self.command_history.append({
                "type": "analog",
                "name": name,
                "value": value,
                "timestamp": time.time()
            })
            return True
        return False

    def get_digital_state(self, name: str) -> Optional[bool]:
        """Read current digital output state"""
        if name in self.digital_outputs:
            return self.digital_outputs[name].state
        return None

    def get_analog_value(self, name: str) -> Optional[float]:
        """Read current analog output value"""
        if name in self.analog_outputs:
            return self.analog_outputs[name].value
        return None

    def reset_all(self):
        """Reset all outputs to default state"""
        for do in self.digital_outputs.values():
            do.state = False
            do.change_count = 0
        for ao in self.analog_outputs.values():
            ao.value = 0.0
        self.command_history.clear()

# =============================================================================
# CONTROL SCRIPT SIMULATOR
# =============================================================================

class ControlScriptSimulator:
    """
    Simulates Python scripts that control hardware outputs.

    In real system, scripts run in browser (Pyodide/Skulpt) and:
    1. Subscribe to input sensor tags via MQTT
    2. Compute control decisions
    3. Publish output commands to MQTT
    4. DAQ service receives commands and writes to NI hardware
    """

    def __init__(self, hardware: HardwareIOSimulator):
        self.hardware = hardware
        self.input_values: Dict[str, float] = {}
        self.setpoints: Dict[str, float] = {}
        self.control_mode: str = "manual"  # manual, auto, sequence

        # PID state for analog control
        self.pid_integral: Dict[str, float] = {}
        self.pid_last_error: Dict[str, float] = {}

        # Sequence state
        self.sequence_step: Optional[int] = None  # None = sequence not started
        self.sequence_start_time: float = 0.0

        # Published script outputs (py.* tags)
        self.published_values: Dict[str, float] = {}

        # Output commands generated
        self.output_commands: List[Dict] = []

    def update_inputs(self, sensor_values: Dict[str, float]):
        """Update input sensor values (received via MQTT subscription)"""
        self.input_values.update(sensor_values)

    def set_setpoint(self, name: str, value: float):
        """Set a control setpoint"""
        self.setpoints[name] = value

    # -------------------------------------------------------------------------
    # Control Algorithms
    # -------------------------------------------------------------------------

    def on_off_control(self, sensor_tag: str, output_tag: str,
                       setpoint: float, hysteresis: float = 1.0) -> bool:
        """
        Simple on/off (bang-bang) control with hysteresis.
        Like a thermostat controlling a heater.

        Returns the output state (True = ON, False = OFF)
        """
        current = self.input_values.get(sensor_tag, 0.0)

        # Get current output state
        current_state = self.hardware.get_digital_state(output_tag) or False

        # Apply hysteresis
        if current_state:
            # Currently ON - turn OFF if above setpoint + hysteresis
            new_state = current < (setpoint + hysteresis)
        else:
            # Currently OFF - turn ON if below setpoint - hysteresis
            new_state = current < (setpoint - hysteresis)

        # Write to output
        self.hardware.write_digital(output_tag, new_state)
        self._record_output("digital", output_tag, new_state)

        return new_state

    def pid_control(self, sensor_tag: str, output_tag: str,
                    setpoint: float, kp: float = 1.0,
                    ki: float = 0.1, kd: float = 0.05,
                    dt: float = 0.1) -> float:
        """
        PID control for analog outputs.
        Like controlling motor speed or heater power.

        Returns the output value (0-100%)
        """
        current = self.input_values.get(sensor_tag, 0.0)
        error = setpoint - current

        # Get previous state
        integral = self.pid_integral.get(output_tag, 0.0)
        last_error = self.pid_last_error.get(output_tag, error)

        # PID calculation
        integral += error * dt
        derivative = (error - last_error) / dt if dt > 0 else 0

        output = kp * error + ki * integral + kd * derivative

        # Clamp to 0-100%
        output = max(0.0, min(100.0, output))

        # Store state
        self.pid_integral[output_tag] = integral
        self.pid_last_error[output_tag] = error

        # Write to output
        self.hardware.write_analog(output_tag, output)
        self._record_output("analog", output_tag, output)

        # Publish as script value
        self.published_values[f"py.PID_{output_tag}"] = output
        self.published_values[f"py.Error_{output_tag}"] = error

        return output

    def threshold_control(self, sensor_tag: str, output_tag: str,
                          threshold: float, above_action: bool = True) -> bool:
        """
        Threshold-based digital control.
        Example: Open bypass valve if pressure exceeds threshold.

        Returns the output state
        """
        current = self.input_values.get(sensor_tag, 0.0)

        if above_action:
            # Activate when above threshold
            new_state = current > threshold
        else:
            # Activate when below threshold
            new_state = current < threshold

        self.hardware.write_digital(output_tag, new_state)
        self._record_output("digital", output_tag, new_state)

        return new_state

    # -------------------------------------------------------------------------
    # Sequence Control (Draw Schedules)
    # -------------------------------------------------------------------------

    def run_sequence_step(self, sequence: List[Dict], elapsed_time: float) -> Optional[int]:
        """
        Execute a timed sequence (draw schedule).

        Sequence format:
        [
            {"duration": 5.0, "actions": [("Valve_Inlet", True), ("Pump_Enable", True)]},
            {"duration": 10.0, "actions": [("Heater_Enable", True)]},
            {"duration": 5.0, "actions": [("Valve_Inlet", False), ("Pump_Enable", False)]},
        ]

        Returns current step index, or None if sequence complete.
        """
        if not sequence:
            return None

        # Find current step based on elapsed time
        cumulative_time = 0.0
        current_step = None

        for i, step in enumerate(sequence):
            cumulative_time += step["duration"]
            if elapsed_time < cumulative_time:
                current_step = i
                break

        if current_step is None:
            # Sequence complete
            return None

        # Execute actions for current step if step changed
        if self.sequence_step is None or current_step != self.sequence_step:
            self.sequence_step = current_step
            step = sequence[current_step]

            for action in step.get("actions", []):
                output_tag, value = action
                if isinstance(value, bool):
                    self.hardware.write_digital(output_tag, value)
                    self._record_output("digital", output_tag, value)
                else:
                    self.hardware.write_analog(output_tag, value)
                    self._record_output("analog", output_tag, value)

        return current_step

    # -------------------------------------------------------------------------
    # Loop Schedule (Continuous Control)
    # -------------------------------------------------------------------------

    def run_control_loop(self, config: Dict) -> Dict[str, Any]:
        """
        Execute one iteration of a control loop.

        Config format:
        {
            "temperature_control": {
                "sensor": "Temperature_1",
                "output": "Heater_Enable",
                "setpoint": 50.0,
                "type": "on_off",
                "hysteresis": 2.0
            },
            "pressure_control": {
                "sensor": "Pressure_In",
                "output": "Valve_Bypass",
                "threshold": 120.0,
                "type": "threshold"
            },
            "motor_control": {
                "sensor": "Motor_RPM",
                "output": "Motor_Speed_Setpoint",
                "setpoint": 1500.0,
                "type": "pid",
                "kp": 0.1, "ki": 0.01, "kd": 0.005
            }
        }

        Returns dict of control outputs.
        """
        results = {}

        for name, ctrl in config.items():
            ctrl_type = ctrl.get("type", "on_off")

            if ctrl_type == "on_off":
                result = self.on_off_control(
                    ctrl["sensor"], ctrl["output"],
                    ctrl["setpoint"], ctrl.get("hysteresis", 1.0)
                )
                results[name] = result

            elif ctrl_type == "threshold":
                result = self.threshold_control(
                    ctrl["sensor"], ctrl["output"],
                    ctrl["threshold"], ctrl.get("above_action", True)
                )
                results[name] = result

            elif ctrl_type == "pid":
                result = self.pid_control(
                    ctrl["sensor"], ctrl["output"],
                    ctrl["setpoint"],
                    ctrl.get("kp", 1.0),
                    ctrl.get("ki", 0.1),
                    ctrl.get("kd", 0.05)
                )
                results[name] = result

        return results

    def _record_output(self, output_type: str, name: str, value: Any):
        """Record an output command for verification"""
        self.output_commands.append({
            "type": output_type,
            "name": name,
            "value": value,
            "timestamp": time.time()
        })

    def get_output_commands(self) -> List[Dict]:
        """Return list of output commands generated"""
        return self.output_commands.copy()

    def clear_commands(self):
        """Clear command history"""
        self.output_commands.clear()

# =============================================================================
# MQTT OUTPUT PUBLISHER
# =============================================================================

class MQTTOutputPublisher:
    """
    Simulates the MQTT message flow for output control.

    In real system:
    - Script publishes to nisystem/output/digital/{name} or nisystem/output/analog/{name}
    - DAQ service subscribes and writes to NI hardware
    - DAQ service publishes confirmation to nisystem/status/output/{name}
    """

    def __init__(self, hardware: HardwareIOSimulator):
        self.hardware = hardware
        self.published_messages: List[Dict] = []
        self.received_confirmations: List[Dict] = []

    def publish_digital_output(self, name: str, state: bool) -> Dict:
        """Publish a digital output command via MQTT"""
        topic = f"{SYSTEM_PREFIX}/output/digital/{name}"
        payload = {
            "value": state,
            "timestamp": time.time()
        }

        self.published_messages.append({
            "topic": topic,
            "payload": payload
        })

        # Simulate hardware receiving and executing
        success = self.hardware.write_digital(name, state)

        # Simulate confirmation
        if success:
            confirmation = {
                "topic": f"{SYSTEM_PREFIX}/status/output/{name}",
                "payload": {
                    "name": name,
                    "type": "digital",
                    "value": state,
                    "success": True,
                    "timestamp": time.time()
                }
            }
            self.received_confirmations.append(confirmation)

        return {"success": success, "topic": topic}

    def publish_analog_output(self, name: str, value: float) -> Dict:
        """Publish an analog output command via MQTT"""
        topic = f"{SYSTEM_PREFIX}/output/analog/{name}"
        payload = {
            "value": value,
            "timestamp": time.time()
        }

        self.published_messages.append({
            "topic": topic,
            "payload": payload
        })

        # Simulate hardware receiving and executing
        success = self.hardware.write_analog(name, value)

        # Simulate confirmation
        if success:
            confirmation = {
                "topic": f"{SYSTEM_PREFIX}/status/output/{name}",
                "payload": {
                    "name": name,
                    "type": "analog",
                    "value": value,
                    "success": True,
                    "timestamp": time.time()
                }
            }
            self.received_confirmations.append(confirmation)

        return {"success": success, "topic": topic}

    def get_confirmation(self, name: str) -> Optional[Dict]:
        """Get the latest confirmation for an output"""
        for conf in reversed(self.received_confirmations):
            if conf["payload"]["name"] == name:
                return conf
        return None

# =============================================================================
# TEST CLASSES
# =============================================================================

class TestDigitalOutputControl(unittest.TestCase):
    """Tests for digital output (valve, relay) control"""

    def setUp(self):
        self.hardware = HardwareIOSimulator()
        self.script = ControlScriptSimulator(self.hardware)
        self.mqtt_pub = MQTTOutputPublisher(self.hardware)

    def test_01_valve_on_off_via_script(self):
        """Test script directly controlling a valve"""
        # Valve should start closed
        self.assertFalse(self.hardware.get_digital_state("Valve_Inlet"))

        # Script opens valve
        self.hardware.write_digital("Valve_Inlet", True)
        self.assertTrue(self.hardware.get_digital_state("Valve_Inlet"))

        # Script closes valve
        self.hardware.write_digital("Valve_Inlet", False)
        self.assertFalse(self.hardware.get_digital_state("Valve_Inlet"))

    def test_02_valve_control_via_mqtt(self):
        """Test script controlling valve via MQTT publish"""
        # Publish open command
        result = self.mqtt_pub.publish_digital_output("Valve_Inlet", True)
        self.assertTrue(result["success"])

        # Verify valve state changed
        self.assertTrue(self.hardware.get_digital_state("Valve_Inlet"))

        # Verify confirmation received
        conf = self.mqtt_pub.get_confirmation("Valve_Inlet")
        self.assertIsNotNone(conf)
        self.assertTrue(conf["payload"]["value"])

    def test_03_on_off_temperature_control(self):
        """Test on/off control for temperature (like a thermostat)"""
        setpoint = 50.0
        hysteresis = 2.0

        # Simulate temperature rising above setpoint
        self.script.update_inputs({"Temperature_1": 53.0})
        state = self.script.on_off_control(
            "Temperature_1", "Heater_Enable", setpoint, hysteresis
        )
        self.assertFalse(state)  # Should turn OFF when above setpoint+hysteresis

        # Temperature drops below setpoint
        self.script.update_inputs({"Temperature_1": 47.0})
        state = self.script.on_off_control(
            "Temperature_1", "Heater_Enable", setpoint, hysteresis
        )
        self.assertTrue(state)  # Should turn ON when below setpoint-hysteresis

    def test_04_threshold_pressure_relief(self):
        """Test threshold control (e.g., pressure relief valve)"""
        threshold = 120.0

        # Normal pressure - valve closed
        self.script.update_inputs({"Pressure_In": 100.0})
        state = self.script.threshold_control(
            "Pressure_In", "Valve_Bypass", threshold
        )
        self.assertFalse(state)
        self.assertFalse(self.hardware.get_digital_state("Valve_Bypass"))

        # High pressure - valve opens
        self.script.update_inputs({"Pressure_In": 130.0})
        state = self.script.threshold_control(
            "Pressure_In", "Valve_Bypass", threshold
        )
        self.assertTrue(state)
        self.assertTrue(self.hardware.get_digital_state("Valve_Bypass"))

    def test_05_multiple_valves_coordinated(self):
        """Test controlling multiple valves in coordination"""
        # Open inlet, close outlet (filling mode)
        self.hardware.write_digital("Valve_Inlet", True)
        self.hardware.write_digital("Valve_Outlet", False)

        self.assertTrue(self.hardware.get_digital_state("Valve_Inlet"))
        self.assertFalse(self.hardware.get_digital_state("Valve_Outlet"))

        # Switch to draining mode
        self.hardware.write_digital("Valve_Inlet", False)
        self.hardware.write_digital("Valve_Outlet", True)

        self.assertFalse(self.hardware.get_digital_state("Valve_Inlet"))
        self.assertTrue(self.hardware.get_digital_state("Valve_Outlet"))

class TestAnalogOutputControl(unittest.TestCase):
    """Tests for analog output (motor speed, heater power) control"""

    def setUp(self):
        self.hardware = HardwareIOSimulator()
        self.script = ControlScriptSimulator(self.hardware)
        self.mqtt_pub = MQTTOutputPublisher(self.hardware)

    def test_01_set_motor_speed(self):
        """Test setting motor speed via analog output"""
        # Set motor to 50%
        self.hardware.write_analog("Motor_Speed_Setpoint", 50.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 50.0)

        # Set to 100%
        self.hardware.write_analog("Motor_Speed_Setpoint", 100.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 100.0)

    def test_02_analog_output_via_mqtt(self):
        """Test analog output via MQTT publish"""
        result = self.mqtt_pub.publish_analog_output("Heater_Power", 75.0)
        self.assertTrue(result["success"])

        # Verify value changed
        self.assertEqual(self.hardware.get_analog_value("Heater_Power"), 75.0)

        # Verify confirmation
        conf = self.mqtt_pub.get_confirmation("Heater_Power")
        self.assertIsNotNone(conf)
        self.assertEqual(conf["payload"]["value"], 75.0)

    def test_03_analog_clamping(self):
        """Test analog output value clamping"""
        # Try to set above max
        self.hardware.write_analog("Motor_Speed_Setpoint", 150.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 100.0)

        # Try to set below min
        self.hardware.write_analog("Motor_Speed_Setpoint", -10.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 0.0)

    def test_04_pid_motor_control(self):
        """Test PID control for motor speed"""
        setpoint = 1500.0  # Target RPM

        # Initial state - motor slow
        self.script.update_inputs({"Motor_RPM": 1000.0})
        output = self.script.pid_control(
            "Motor_RPM", "Motor_Speed_Setpoint", setpoint,
            kp=0.05, ki=0.01, kd=0.005
        )

        # Output should be positive (need to speed up)
        self.assertGreater(output, 0)

        # Run a few iterations to see output change
        outputs = [output]
        for rpm in [1200, 1350, 1450, 1500, 1500]:
            self.script.update_inputs({"Motor_RPM": float(rpm)})
            output = self.script.pid_control(
                "Motor_RPM", "Motor_Speed_Setpoint", setpoint,
                kp=0.05, ki=0.01, kd=0.005
            )
            outputs.append(output)

        # As we approach setpoint, output should stabilize
        # (This is a simplified test - real PID would need tuning)
        self.assertLess(abs(outputs[-1] - outputs[-2]), abs(outputs[0] - outputs[1]))

    def test_05_heater_power_ramp(self):
        """Test ramping heater power gradually"""
        # Ramp from 0 to 100% in 10 steps
        for i in range(11):
            power = i * 10.0
            self.hardware.write_analog("Heater_Power", power)
            self.assertEqual(self.hardware.get_analog_value("Heater_Power"), power)

class TestSequenceControl(unittest.TestCase):
    """Tests for sequence/draw schedule control"""

    def setUp(self):
        self.hardware = HardwareIOSimulator()
        self.script = ControlScriptSimulator(self.hardware)

    def test_01_simple_sequence(self):
        """Test a simple valve sequence"""
        sequence = [
            {"duration": 2.0, "actions": [("Valve_Inlet", True), ("Pump_Enable", True)]},
            {"duration": 5.0, "actions": [("Heater_Enable", True)]},
            {"duration": 2.0, "actions": [("Valve_Inlet", False), ("Pump_Enable", False), ("Heater_Enable", False)]},
        ]

        # At t=0, step 0 should execute
        step = self.script.run_sequence_step(sequence, elapsed_time=0.5)
        self.assertEqual(step, 0)
        self.assertTrue(self.hardware.get_digital_state("Valve_Inlet"))
        self.assertTrue(self.hardware.get_digital_state("Pump_Enable"))

        # At t=3, step 1 should execute
        step = self.script.run_sequence_step(sequence, elapsed_time=3.0)
        self.assertEqual(step, 1)
        self.assertTrue(self.hardware.get_digital_state("Heater_Enable"))

        # At t=8, step 2 should execute (shutdown)
        step = self.script.run_sequence_step(sequence, elapsed_time=8.0)
        self.assertEqual(step, 2)
        self.assertFalse(self.hardware.get_digital_state("Valve_Inlet"))
        self.assertFalse(self.hardware.get_digital_state("Pump_Enable"))
        self.assertFalse(self.hardware.get_digital_state("Heater_Enable"))

        # At t=10, sequence complete
        step = self.script.run_sequence_step(sequence, elapsed_time=10.0)
        self.assertIsNone(step)

    def test_02_sequence_with_analog(self):
        """Test sequence with analog output changes"""
        sequence = [
            {"duration": 3.0, "actions": [("Motor_Speed_Setpoint", 25.0), ("Pump_Enable", True)]},
            {"duration": 5.0, "actions": [("Motor_Speed_Setpoint", 75.0)]},
            {"duration": 2.0, "actions": [("Motor_Speed_Setpoint", 0.0), ("Pump_Enable", False)]},
        ]

        # Step 0: Motor at 25%
        self.script.run_sequence_step(sequence, elapsed_time=1.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 25.0)
        self.assertTrue(self.hardware.get_digital_state("Pump_Enable"))

        # Step 1: Motor at 75%
        self.script.run_sequence_step(sequence, elapsed_time=4.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 75.0)

        # Step 2: Motor off
        self.script.run_sequence_step(sequence, elapsed_time=9.0)
        self.assertEqual(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 0.0)
        self.assertFalse(self.hardware.get_digital_state("Pump_Enable"))

class TestLoopSchedule(unittest.TestCase):
    """Tests for continuous control loop (loop schedule)"""

    def setUp(self):
        self.hardware = HardwareIOSimulator()
        self.script = ControlScriptSimulator(self.hardware)

    def test_01_basic_control_loop(self):
        """Test running a basic control loop iteration"""
        loop_config = {
            "temperature_control": {
                "sensor": "Temperature_1",
                "output": "Heater_Enable",
                "setpoint": 50.0,
                "type": "on_off",
                "hysteresis": 2.0
            },
            "pressure_safety": {
                "sensor": "Pressure_In",
                "output": "Valve_Bypass",
                "threshold": 120.0,
                "type": "threshold"
            }
        }

        # Set sensor values
        self.script.update_inputs({
            "Temperature_1": 45.0,  # Below setpoint
            "Pressure_In": 100.0     # Normal
        })

        # Run one loop iteration
        results = self.script.run_control_loop(loop_config)

        # Heater should be ON (temp below setpoint)
        self.assertTrue(results["temperature_control"])
        self.assertTrue(self.hardware.get_digital_state("Heater_Enable"))

        # Bypass valve should be OFF (pressure normal)
        self.assertFalse(results["pressure_safety"])
        self.assertFalse(self.hardware.get_digital_state("Valve_Bypass"))

    def test_02_continuous_loop_simulation(self):
        """Test running control loop continuously"""
        loop_config = {
            "heater": {
                "sensor": "Temperature_1",
                "output": "Heater_Enable",
                "setpoint": 50.0,
                "type": "on_off",
                "hysteresis": 2.0
            }
        }

        # Simulate temperature rising over time with heater control
        temperature = 25.0  # Start cold
        heater_cycles = 0
        last_heater_state = False

        for i in range(100):  # 100 loop iterations
            self.script.update_inputs({"Temperature_1": temperature})
            results = self.script.run_control_loop(loop_config)

            heater_on = results["heater"]

            # Count heater cycles
            if heater_on != last_heater_state:
                heater_cycles += 1
                last_heater_state = heater_on

            # Simulate temperature change based on heater
            if heater_on:
                temperature += 0.5  # Heating
            else:
                temperature -= 0.3  # Cooling

        # Temperature should stabilize around setpoint
        self.assertGreater(temperature, 45.0)
        self.assertLess(temperature, 55.0)

        # There should have been some heater cycling
        self.assertGreater(heater_cycles, 0)

    def test_03_multi_loop_with_pid(self):
        """Test control loop with PID for analog output"""
        loop_config = {
            "motor_speed": {
                "sensor": "Motor_RPM",
                "output": "Motor_Speed_Setpoint",
                "setpoint": 1500.0,
                "type": "pid",
                "kp": 0.02,
                "ki": 0.005,
                "kd": 0.001
            }
        }

        # Simulate motor responding to setpoint changes
        rpm = 0.0
        motor_output = 0.0

        for i in range(50):
            self.script.update_inputs({"Motor_RPM": rpm})
            results = self.script.run_control_loop(loop_config)
            motor_output = results["motor_speed"]

            # Simulate motor responding to output (simplified)
            rpm = rpm + (motor_output - rpm * 0.05) * 0.5
            rpm = max(0, rpm)

        # Motor should be approaching target
        self.assertGreater(rpm, 500)  # Making progress toward 1500

class TestFullControlDataFlow(unittest.TestCase):
    """
    Integration tests for the complete control data flow:
    Input sensors -> MQTT -> Script -> Compute -> Output commands -> MQTT -> Hardware
    """

    def setUp(self):
        self.hardware = HardwareIOSimulator()
        self.script = ControlScriptSimulator(self.hardware)
        self.mqtt_pub = MQTTOutputPublisher(self.hardware)

    def test_01_complete_control_cycle(self):
        """Test complete control cycle with all components"""
        # Step 1: Simulate sensor data arriving via MQTT
        sensor_data = {
            "Temperature_1": 45.0,
            "Temperature_2": 48.0,
            "Pressure_In": 105.0,
            "Pressure_Out": 100.0,
            "Flow_Rate": 10.5,
            "Motor_RPM": 1450.0
        }
        self.script.update_inputs(sensor_data)

        # Step 2: Script computes control actions
        loop_config = {
            "temp_control": {
                "sensor": "Temperature_1",
                "output": "Heater_Enable",
                "setpoint": 50.0,
                "type": "on_off"
            },
            "motor_control": {
                "sensor": "Motor_RPM",
                "output": "Motor_Speed_Setpoint",
                "setpoint": 1500.0,
                "type": "pid",
                "kp": 0.05
            }
        }
        results = self.script.run_control_loop(loop_config)

        # Step 3: Verify output commands were generated
        commands = self.script.get_output_commands()
        self.assertGreater(len(commands), 0)

        # Step 4: Script publishes computed values (py.* tags)
        self.assertIn("py.PID_Motor_Speed_Setpoint", self.script.published_values)
        self.assertIn("py.Error_Motor_Speed_Setpoint", self.script.published_values)

        # Step 5: Verify hardware state changed
        self.assertTrue(self.hardware.get_digital_state("Heater_Enable"))
        self.assertGreater(self.hardware.get_analog_value("Motor_Speed_Setpoint"), 0)

    def test_02_script_published_values_available(self):
        """Test that script-computed control values are published as py.* tags"""
        self.script.update_inputs({"Temperature_1": 45.0})
        self.script.on_off_control("Temperature_1", "Heater_Enable", 50.0)

        self.script.update_inputs({"Motor_RPM": 1400.0})
        self.script.pid_control("Motor_RPM", "Motor_Speed_Setpoint", 1500.0)

        # These py.* values would be available in DataTab for recording
        published = self.script.published_values
        self.assertIn("py.PID_Motor_Speed_Setpoint", published)
        self.assertIn("py.Error_Motor_Speed_Setpoint", published)

    def test_03_output_command_history_for_recording(self):
        """Test that output commands are recorded for data logging"""
        # Run some control actions
        self.hardware.write_digital("Valve_Inlet", True)
        self.hardware.write_analog("Motor_Speed_Setpoint", 50.0)
        self.hardware.write_digital("Valve_Inlet", False)
        self.hardware.write_analog("Motor_Speed_Setpoint", 75.0)

        # Command history should be available for recording
        history = self.hardware.command_history
        self.assertEqual(len(history), 4)

        # Verify command details
        self.assertEqual(history[0]["type"], "digital")
        self.assertEqual(history[0]["name"], "Valve_Inlet")
        self.assertEqual(history[0]["value"], True)

    def test_04_verify_full_mqtt_flow(self):
        """Test complete MQTT message flow for outputs"""
        # Publish digital command via MQTT
        self.mqtt_pub.publish_digital_output("Pump_Enable", True)

        # Verify message was published
        self.assertEqual(len(self.mqtt_pub.published_messages), 1)
        msg = self.mqtt_pub.published_messages[0]
        self.assertIn("output/digital/Pump_Enable", msg["topic"])

        # Verify hardware received command
        self.assertTrue(self.hardware.get_digital_state("Pump_Enable"))

        # Verify confirmation was received
        self.assertEqual(len(self.mqtt_pub.received_confirmations), 1)
        conf = self.mqtt_pub.received_confirmations[0]
        self.assertTrue(conf["payload"]["success"])

# =============================================================================
# STANDALONE RUNNER
# =============================================================================

def run_all_tests():
    """Run all test classes"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestDigitalOutputControl,
        TestAnalogOutputControl,
        TestSequenceControl,
        TestLoopSchedule,
        TestFullControlDataFlow,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Script Control Loop Tests")
    parser.add_argument("--test", help="Run specific test class")
    parser.add_argument("--list", action="store_true", help="List test classes")

    args = parser.parse_args()

    if args.list:
        print("Available test classes:")
        print("  - TestDigitalOutputControl")
        print("  - TestAnalogOutputControl")
        print("  - TestSequenceControl")
        print("  - TestLoopSchedule")
        print("  - TestFullControlDataFlow")
    elif args.test:
        test_classes = {
            "TestDigitalOutputControl": TestDigitalOutputControl,
            "TestAnalogOutputControl": TestAnalogOutputControl,
            "TestSequenceControl": TestSequenceControl,
            "TestLoopSchedule": TestLoopSchedule,
            "TestFullControlDataFlow": TestFullControlDataFlow,
        }
        if args.test in test_classes:
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromTestCase(test_classes[args.test])
            runner = unittest.TextTestRunner(verbosity=2)
            runner.run(suite)
        else:
            print(f"Unknown test class: {args.test}")
    else:
        import sys
        success = run_all_tests()
        sys.exit(0 if success else 1)

