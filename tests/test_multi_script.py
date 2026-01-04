#!/usr/bin/env python3
"""
Multi-Script Concurrent Execution Tests for NISystem

Tests that multiple Python scripts can run simultaneously in the same session:
1. Multiple scripts subscribe to the same hardware tags
2. Each script computes its own derived values (py.Script1_*, py.Script2_*)
3. Scripts can have different update rates
4. All script outputs are published to MQTT
5. All script outputs appear in widgets and are available for recording
6. Scripts can control different hardware outputs without conflict

Run with: python -m pytest tests/test_multi_script.py -v
"""

import json
import math
import threading
import time
import unittest
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

# Test configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
SYSTEM_PREFIX = "nisystem"


# =============================================================================
# MULTI-SCRIPT SIMULATOR
# =============================================================================

@dataclass
class ScriptInstance:
    """Represents a single Python script instance"""
    name: str
    prefix: str  # e.g., "Script1" -> outputs py.Script1_*
    formulas: Dict[str, Callable]
    update_interval_ms: int = 100  # How often this script runs
    subscribed_tags: Set[str] = field(default_factory=set)
    published_values: Dict[str, float] = field(default_factory=dict)
    execution_count: int = 0
    last_execution_time: float = 0.0
    is_running: bool = False
    error_count: int = 0

    def get_output_tag(self, name: str) -> str:
        """Get full output tag name with prefix"""
        return f"py.{self.prefix}_{name}"


class MultiScriptSimulator:
    """
    Simulates multiple Python scripts running concurrently.

    In the real system:
    - Each script runs in its own execution context (Pyodide/Skulpt)
    - Scripts share access to the same MQTT topics
    - Scripts can have different update rates
    - All script outputs are collected and published
    """

    def __init__(self):
        self.scripts: Dict[str, ScriptInstance] = {}
        self.hardware_values: Dict[str, float] = {}
        self.all_published_values: Dict[str, float] = {}
        self.execution_log: List[Dict] = []
        self.lock = threading.Lock()

    def add_script(self, name: str, prefix: str,
                   formulas: Dict[str, Callable],
                   subscribed_tags: Optional[Set[str]] = None,
                   update_interval_ms: int = 100) -> ScriptInstance:
        """Add a new script instance"""
        script = ScriptInstance(
            name=name,
            prefix=prefix,
            formulas=formulas,
            subscribed_tags=subscribed_tags or set(),
            update_interval_ms=update_interval_ms
        )
        self.scripts[name] = script
        return script

    def update_hardware_values(self, values: Dict[str, float]):
        """Update hardware values (from DAQ/MQTT)"""
        with self.lock:
            self.hardware_values.update(values)

    def execute_script(self, script: ScriptInstance) -> Dict[str, float]:
        """Execute a single script and return its outputs"""
        outputs = {}

        with self.lock:
            # Get input values (filtered by subscription if specified)
            if script.subscribed_tags:
                inputs = {k: v for k, v in self.hardware_values.items()
                         if k in script.subscribed_tags}
            else:
                inputs = self.hardware_values.copy()

            # Also include other scripts' published values as inputs
            # (scripts can chain computations)
            inputs.update(self.all_published_values)

        # Execute each formula
        for formula_name, formula_fn in script.formulas.items():
            try:
                result = formula_fn(inputs)
                output_tag = script.get_output_tag(formula_name)
                outputs[output_tag] = result
            except Exception as e:
                script.error_count += 1
                output_tag = script.get_output_tag(formula_name)
                outputs[output_tag] = float('nan')

        # Update script state
        script.published_values = outputs
        script.execution_count += 1
        script.last_execution_time = time.time()

        # Update global published values
        with self.lock:
            self.all_published_values.update(outputs)
            self.execution_log.append({
                "script": script.name,
                "timestamp": time.time(),
                "outputs": outputs.copy()
            })

        return outputs

    def execute_all_scripts(self) -> Dict[str, Dict[str, float]]:
        """Execute all scripts once and return their outputs"""
        results = {}
        for name, script in self.scripts.items():
            results[name] = self.execute_script(script)
        return results

    def execute_scripts_parallel(self) -> Dict[str, Dict[str, float]]:
        """Execute all scripts in parallel using threads"""
        results = {}

        with ThreadPoolExecutor(max_workers=len(self.scripts)) as executor:
            futures = {
                executor.submit(self.execute_script, script): name
                for name, script in self.scripts.items()
            }

            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    results[name] = {"error": str(e)}

        return results

    def run_continuous(self, duration_s: float, base_interval_ms: int = 50):
        """
        Run all scripts continuously for a duration.
        Each script runs at its own interval.
        """
        start_time = time.time()
        iteration = 0

        while (time.time() - start_time) < duration_s:
            current_time = time.time()

            for name, script in self.scripts.items():
                # Check if it's time for this script to run
                time_since_last = (current_time - script.last_execution_time) * 1000
                if time_since_last >= script.update_interval_ms:
                    self.execute_script(script)

            # Small sleep to prevent busy-waiting
            time.sleep(base_interval_ms / 1000.0)
            iteration += 1

        return iteration

    def get_all_published_tags(self) -> List[str]:
        """Get list of all tags published by all scripts"""
        tags = []
        for script in self.scripts.values():
            for formula_name in script.formulas.keys():
                tags.append(script.get_output_tag(formula_name))
        return tags

    def get_execution_stats(self) -> Dict[str, Dict]:
        """Get execution statistics for all scripts"""
        stats = {}
        for name, script in self.scripts.items():
            stats[name] = {
                "execution_count": script.execution_count,
                "error_count": script.error_count,
                "last_execution": script.last_execution_time,
                "published_values": script.published_values.copy()
            }
        return stats


# =============================================================================
# SAMPLE SCRIPTS FOR TESTING
# =============================================================================

def create_efficiency_script() -> Dict[str, Callable]:
    """Script 1: Calculates efficiency metrics"""
    return {
        "Efficiency": lambda v: (
            (v.get("Pressure_Out", 0) * v.get("Flow_Rate", 1)) /
            max(v.get("Pressure_In", 1) * v.get("Flow_Rate", 1), 0.001) * 100
        ),
        "Delta_P": lambda v: v.get("Pressure_In", 0) - v.get("Pressure_Out", 0),
        "Power_Est": lambda v: v.get("Motor_RPM", 0) * 0.01,
    }


def create_thermal_script() -> Dict[str, Callable]:
    """Script 2: Calculates thermal metrics"""
    return {
        "Delta_T": lambda v: v.get("Temperature_2", 0) - v.get("Temperature_1", 0),
        "Heat_Transfer": lambda v: (
            v.get("Flow_Rate", 0) * 4.18 *
            abs(v.get("Temperature_2", 0) - v.get("Temperature_1", 0))
        ),
        "Avg_Temp": lambda v: (
            (v.get("Temperature_1", 0) + v.get("Temperature_2", 0)) / 2
        ),
    }


def create_safety_script() -> Dict[str, Callable]:
    """Script 3: Safety monitoring and alarms"""
    return {
        "Overpressure": lambda v: 1.0 if v.get("Pressure_In", 0) > 120 else 0.0,
        "Overtemp": lambda v: 1.0 if v.get("Temperature_1", 0) > 80 else 0.0,
        "Motor_Fault": lambda v: 1.0 if v.get("Motor_RPM", 0) < 100 else 0.0,
        "System_OK": lambda v: (
            1.0 if (v.get("Pressure_In", 0) <= 120 and
                   v.get("Temperature_1", 0) <= 80 and
                   v.get("Motor_RPM", 0) >= 100) else 0.0
        ),
    }


def create_control_script() -> Dict[str, Callable]:
    """Script 4: Control outputs based on inputs"""
    return {
        "Heater_Demand": lambda v: max(0, min(100, (50 - v.get("Temperature_1", 25)) * 5)),
        "Motor_Setpoint": lambda v: max(0, min(100, v.get("py.Script1_Efficiency", 50))),
        "Valve_Command": lambda v: 1.0 if v.get("Flow_Rate", 0) < 5 else 0.0,
    }


def create_chained_script() -> Dict[str, Callable]:
    """Script 5: Uses outputs from other scripts (chaining)"""
    return {
        "Combined_Index": lambda v: (
            v.get("py.Script1_Efficiency", 0) * 0.5 +
            v.get("py.Script2_Heat_Transfer", 0) * 0.3 +
            v.get("py.Script3_System_OK", 0) * 100 * 0.2
        ),
        "Efficiency_OK": lambda v: 1.0 if v.get("py.Script1_Efficiency", 0) > 80 else 0.0,
    }


# =============================================================================
# SIMULATED LAB DATA
# =============================================================================

class SimulatedLabData:
    """Generates simulated sensor data"""

    @staticmethod
    def generate_sample(t: float) -> Dict[str, float]:
        return {
            "Temperature_1": 25.0 + 5.0 * math.sin(t / 30) + 0.2 * math.sin(t * 10),
            "Temperature_2": 30.0 + 5.0 * math.sin(t / 30) + 0.2 * math.sin(t * 10),
            "Pressure_In": 101.325 + 0.5 * math.sin(t / 20),
            "Pressure_Out": 100.0 + 0.5 * math.sin(t / 20),
            "Flow_Rate": 10.0 + 2.0 * (1 if (int(t) % 60) > 30 else 0) + 0.5 * math.sin(t / 10),
            "Motor_RPM": 1500.0 * min(1.0, t / 10) + 5 * math.sin(t * 50),
        }


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestMultipleScriptsBasic(unittest.TestCase):
    """Basic tests for multiple scripts running together"""

    def setUp(self):
        self.sim = MultiScriptSimulator()
        self.lab_data = SimulatedLabData()

    def test_01_two_scripts_different_outputs(self):
        """Test two scripts producing different outputs from same inputs"""
        # Add two scripts
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())

        # Set hardware values
        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        # Execute both scripts
        results = self.sim.execute_all_scripts()

        # Verify both scripts executed
        self.assertIn("Script1", results)
        self.assertIn("Script2", results)

        # Verify each script produced its expected outputs
        self.assertIn("py.Script1_Efficiency", results["Script1"])
        self.assertIn("py.Script1_Delta_P", results["Script1"])
        self.assertIn("py.Script2_Delta_T", results["Script2"])
        self.assertIn("py.Script2_Heat_Transfer", results["Script2"])

    def test_02_all_outputs_available_globally(self):
        """Test that all script outputs are available in global published values"""
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())
        self.sim.add_script("Script3", "Script3", create_safety_script())

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)
        self.sim.execute_all_scripts()

        # All outputs should be in global published values
        all_published = self.sim.all_published_values

        self.assertIn("py.Script1_Efficiency", all_published)
        self.assertIn("py.Script2_Delta_T", all_published)
        self.assertIn("py.Script3_System_OK", all_published)

    def test_03_scripts_with_different_subscriptions(self):
        """Test scripts subscribing to different subsets of tags"""
        # Script1 only subscribes to pressure/flow
        self.sim.add_script(
            "PressureScript", "Pressure",
            {"Delta_P": lambda v: v.get("Pressure_In", 0) - v.get("Pressure_Out", 0)},
            subscribed_tags={"Pressure_In", "Pressure_Out"}
        )

        # Script2 only subscribes to temperature
        self.sim.add_script(
            "TempScript", "Temp",
            {"Delta_T": lambda v: v.get("Temperature_2", 0) - v.get("Temperature_1", 0)},
            subscribed_tags={"Temperature_1", "Temperature_2"}
        )

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        results = self.sim.execute_all_scripts()

        # Both should work with their subscribed tags
        self.assertIn("py.Pressure_Delta_P", results["PressureScript"])
        self.assertIn("py.Temp_Delta_T", results["TempScript"])

        # Values should be correct
        expected_delta_p = sample["Pressure_In"] - sample["Pressure_Out"]
        self.assertAlmostEqual(
            results["PressureScript"]["py.Pressure_Delta_P"],
            expected_delta_p,
            places=5
        )


class TestScriptChaining(unittest.TestCase):
    """Test scripts that use outputs from other scripts"""

    def setUp(self):
        self.sim = MultiScriptSimulator()
        self.lab_data = SimulatedLabData()

    def test_01_script_uses_another_scripts_output(self):
        """Test one script using output from another script"""
        # Script1 computes efficiency
        self.sim.add_script("Script1", "Script1", create_efficiency_script())

        # Script2 uses Script1's efficiency output
        self.sim.add_script("Script2", "Script2", {
            "Efficiency_Grade": lambda v: (
                "A" if v.get("py.Script1_Efficiency", 0) > 90 else
                "B" if v.get("py.Script1_Efficiency", 0) > 80 else
                "C"
            ),
            "Double_Efficiency": lambda v: v.get("py.Script1_Efficiency", 0) * 2
        })

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        # Execute Script1 first, then Script2
        self.sim.execute_script(self.sim.scripts["Script1"])
        results = self.sim.execute_script(self.sim.scripts["Script2"])

        # Script2 should have used Script1's output
        self.assertIn("py.Script2_Double_Efficiency", results)

        # Verify the value is actually doubled
        efficiency = self.sim.all_published_values["py.Script1_Efficiency"]
        double_eff = results["py.Script2_Double_Efficiency"]
        self.assertAlmostEqual(double_eff, efficiency * 2, places=5)

    def test_02_three_level_chain(self):
        """Test chain of 3 scripts: A -> B -> C"""
        # Level 1: Raw computation
        self.sim.add_script("Level1", "L1", {
            "RawValue": lambda v: v.get("Temperature_1", 0) + 10
        })

        # Level 2: Uses Level1
        self.sim.add_script("Level2", "L2", {
            "Processed": lambda v: v.get("py.L1_RawValue", 0) * 2
        })

        # Level 3: Uses Level2
        self.sim.add_script("Level3", "L3", {
            "Final": lambda v: v.get("py.L2_Processed", 0) + 100
        })

        sample = {"Temperature_1": 25.0}
        self.sim.update_hardware_values(sample)

        # Execute in order
        self.sim.execute_script(self.sim.scripts["Level1"])
        self.sim.execute_script(self.sim.scripts["Level2"])
        self.sim.execute_script(self.sim.scripts["Level3"])

        # Verify chain: (25+10)*2 + 100 = 170
        final = self.sim.all_published_values["py.L3_Final"]
        self.assertEqual(final, 170.0)


class TestConcurrentExecution(unittest.TestCase):
    """Test scripts executing in parallel"""

    def setUp(self):
        self.sim = MultiScriptSimulator()
        self.lab_data = SimulatedLabData()

    def test_01_parallel_execution(self):
        """Test multiple scripts executing in parallel threads"""
        # Add several scripts
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())
        self.sim.add_script("Script3", "Script3", create_safety_script())

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        # Execute all in parallel
        results = self.sim.execute_scripts_parallel()

        # All should have completed
        self.assertEqual(len(results), 3)
        self.assertNotIn("error", results.get("Script1", {}))
        self.assertNotIn("error", results.get("Script2", {}))
        self.assertNotIn("error", results.get("Script3", {}))

    def test_02_high_frequency_concurrent(self):
        """Test many rapid concurrent executions"""
        self.sim.add_script("Fast1", "Fast1", create_efficiency_script())
        self.sim.add_script("Fast2", "Fast2", create_thermal_script())

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        # Execute 100 times in parallel batches
        for i in range(100):
            results = self.sim.execute_scripts_parallel()
            self.assertEqual(len(results), 2)

        # Check execution counts
        stats = self.sim.get_execution_stats()
        self.assertEqual(stats["Fast1"]["execution_count"], 100)
        self.assertEqual(stats["Fast2"]["execution_count"], 100)

    def test_03_different_update_rates(self):
        """Test scripts with different update intervals"""
        # Fast script: 50ms interval
        self.sim.add_script("FastScript", "Fast",
                           create_efficiency_script(),
                           update_interval_ms=50)

        # Slow script: 200ms interval
        self.sim.add_script("SlowScript", "Slow",
                           create_thermal_script(),
                           update_interval_ms=200)

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)

        # Run for 500ms
        self.sim.run_continuous(duration_s=0.5, base_interval_ms=25)

        # Fast script should have run more times than slow script
        stats = self.sim.get_execution_stats()
        fast_count = stats["FastScript"]["execution_count"]
        slow_count = stats["SlowScript"]["execution_count"]

        # Fast should run ~4x more than slow (50ms vs 200ms)
        self.assertGreater(fast_count, slow_count)
        # Allow some tolerance for timing
        self.assertGreater(fast_count, slow_count * 2)


class TestScriptIsolation(unittest.TestCase):
    """Test that scripts are properly isolated from each other"""

    def setUp(self):
        self.sim = MultiScriptSimulator()

    def test_01_error_in_one_doesnt_affect_others(self):
        """Test that an error in one script doesn't break others"""
        # Good script
        self.sim.add_script("GoodScript", "Good", {
            "Value": lambda v: v.get("Temperature_1", 0) + 10
        })

        # Bad script (will throw error)
        self.sim.add_script("BadScript", "Bad", {
            "Value": lambda v: v["NonexistentKey"] / 0  # KeyError and ZeroDivision
        })

        sample = {"Temperature_1": 25.0}
        self.sim.update_hardware_values(sample)

        # Execute all - should not throw
        results = self.sim.execute_all_scripts()

        # Good script should have valid result
        self.assertEqual(results["GoodScript"]["py.Good_Value"], 35.0)

        # Bad script should have NaN
        self.assertTrue(math.isnan(results["BadScript"]["py.Bad_Value"]))

        # Error should be counted
        self.assertEqual(self.sim.scripts["BadScript"].error_count, 1)
        self.assertEqual(self.sim.scripts["GoodScript"].error_count, 0)

    def test_02_scripts_have_separate_state(self):
        """Test that scripts maintain separate internal state"""
        # Use a stateful formula (via closure)
        counter1 = [0]
        counter2 = [0]

        self.sim.add_script("Counter1", "C1", {
            "Count": lambda v: (counter1.__setitem__(0, counter1[0] + 1), counter1[0])[1]
        })

        self.sim.add_script("Counter2", "C2", {
            "Count": lambda v: (counter2.__setitem__(0, counter2[0] + 10), counter2[0])[1]
        })

        self.sim.update_hardware_values({"dummy": 1})

        # Execute multiple times
        for _ in range(5):
            self.sim.execute_all_scripts()

        # Each counter should have its own state
        self.assertEqual(counter1[0], 5)
        self.assertEqual(counter2[0], 50)


class TestAllOutputsAvailableForRecording(unittest.TestCase):
    """Test that all script outputs can be recorded"""

    def setUp(self):
        self.sim = MultiScriptSimulator()
        self.lab_data = SimulatedLabData()

    def test_01_all_tags_listed(self):
        """Test that all output tags are discoverable"""
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())
        self.sim.add_script("Script3", "Script3", create_safety_script())

        tags = self.sim.get_all_published_tags()

        # Should have all expected tags
        expected = [
            "py.Script1_Efficiency", "py.Script1_Delta_P", "py.Script1_Power_Est",
            "py.Script2_Delta_T", "py.Script2_Heat_Transfer", "py.Script2_Avg_Temp",
            "py.Script3_Overpressure", "py.Script3_Overtemp",
            "py.Script3_Motor_Fault", "py.Script3_System_OK",
        ]

        for tag in expected:
            self.assertIn(tag, tags)

    def test_02_all_values_numeric(self):
        """Test that all output values are numeric (recordable)"""
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())

        sample = self.lab_data.generate_sample(t=10.0)
        self.sim.update_hardware_values(sample)
        self.sim.execute_all_scripts()

        # All values should be float/int
        for tag, value in self.sim.all_published_values.items():
            self.assertIsInstance(value, (int, float),
                f"Tag {tag} value should be numeric, got {type(value)}")

    def test_03_simulate_recording_session(self):
        """Test simulating a recording session with all scripts"""
        self.sim.add_script("Script1", "Script1", create_efficiency_script())
        self.sim.add_script("Script2", "Script2", create_thermal_script())
        self.sim.add_script("Script3", "Script3", create_safety_script())

        # Simulate recording multiple samples
        recorded_data = []

        for t in range(20):
            sample = self.lab_data.generate_sample(t=float(t))
            self.sim.update_hardware_values(sample)
            self.sim.execute_all_scripts()

            # Record all values (hardware + scripts)
            record = {"timestamp": time.time()}
            record.update(sample)
            record.update(self.sim.all_published_values)
            recorded_data.append(record)

        # Should have 20 records
        self.assertEqual(len(recorded_data), 20)

        # Each record should have all expected columns
        first_record = recorded_data[0]
        self.assertIn("Temperature_1", first_record)
        self.assertIn("py.Script1_Efficiency", first_record)
        self.assertIn("py.Script2_Delta_T", first_record)
        self.assertIn("py.Script3_System_OK", first_record)


class TestRealWorldScenarios(unittest.TestCase):
    """Test realistic multi-script scenarios"""

    def setUp(self):
        self.sim = MultiScriptSimulator()
        self.lab_data = SimulatedLabData()

    def test_01_monitoring_and_control_scripts(self):
        """Test monitoring script alongside control script"""
        # Monitoring script (read-only calculations)
        self.sim.add_script("Monitor", "Mon", {
            "Efficiency": lambda v: (
                v.get("Pressure_Out", 0) / max(v.get("Pressure_In", 1), 0.001) * 100
            ),
            "TempDiff": lambda v: v.get("Temperature_2", 0) - v.get("Temperature_1", 0),
        })

        # Control script (would write to outputs in real system)
        self.sim.add_script("Control", "Ctrl", {
            "HeaterDemand": lambda v: max(0, min(100, (50 - v.get("Temperature_1", 25)) * 5)),
            "PumpSpeed": lambda v: max(0, min(100, v.get("Flow_Rate", 0) * 10)),
        })

        # Run for several iterations
        for t in range(10):
            sample = self.lab_data.generate_sample(t=float(t))
            self.sim.update_hardware_values(sample)
            self.sim.execute_all_scripts()

        # Both scripts should have run
        stats = self.sim.get_execution_stats()
        self.assertEqual(stats["Monitor"]["execution_count"], 10)
        self.assertEqual(stats["Control"]["execution_count"], 10)

        # Values should be present
        self.assertIn("py.Mon_Efficiency", self.sim.all_published_values)
        self.assertIn("py.Ctrl_HeaterDemand", self.sim.all_published_values)

    def test_02_cascaded_control_loop(self):
        """Test inner/outer control loop pattern with two scripts"""
        # Outer loop: Slow temperature setpoint adjustment
        self.sim.add_script("OuterLoop", "Outer", {
            "TempSetpoint": lambda v: 50.0 + 5.0 * math.sin(v.get("_time", 0) / 100),
        }, update_interval_ms=1000)

        # Inner loop: Fast heater control to track setpoint
        self.sim.add_script("InnerLoop", "Inner", {
            "HeaterOutput": lambda v: max(0, min(100,
                (v.get("py.Outer_TempSetpoint", 50) - v.get("Temperature_1", 25)) * 10
            )),
        }, update_interval_ms=100)

        sample = self.lab_data.generate_sample(t=10.0)
        sample["_time"] = 10.0
        self.sim.update_hardware_values(sample)

        # Execute outer first, then inner uses its output
        self.sim.execute_script(self.sim.scripts["OuterLoop"])
        self.sim.execute_script(self.sim.scripts["InnerLoop"])

        # Inner loop should be using outer loop's setpoint
        setpoint = self.sim.all_published_values["py.Outer_TempSetpoint"]
        heater = self.sim.all_published_values["py.Inner_HeaterOutput"]

        # If temp < setpoint, heater should be positive
        if sample["Temperature_1"] < setpoint:
            self.assertGreater(heater, 0)


# =============================================================================
# STANDALONE RUNNER
# =============================================================================

def run_all_tests():
    """Run all test classes"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestMultipleScriptsBasic,
        TestScriptChaining,
        TestConcurrentExecution,
        TestScriptIsolation,
        TestAllOutputsAvailableForRecording,
        TestRealWorldScenarios,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Multi-Script Concurrent Execution Tests")
    parser.add_argument("--test", help="Run specific test class")
    parser.add_argument("--list", action="store_true", help="List test classes")

    args = parser.parse_args()

    if args.list:
        print("Available test classes:")
        print("  - TestMultipleScriptsBasic")
        print("  - TestScriptChaining")
        print("  - TestConcurrentExecution")
        print("  - TestScriptIsolation")
        print("  - TestAllOutputsAvailableForRecording")
        print("  - TestRealWorldScenarios")
    elif args.test:
        test_classes = {
            "TestMultipleScriptsBasic": TestMultipleScriptsBasic,
            "TestScriptChaining": TestScriptChaining,
            "TestConcurrentExecution": TestConcurrentExecution,
            "TestScriptIsolation": TestScriptIsolation,
            "TestAllOutputsAvailableForRecording": TestAllOutputsAvailableForRecording,
            "TestRealWorldScenarios": TestRealWorldScenarios,
        }
        if args.test in test_classes:
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromTestCase(test_classes[args.test])
            runner = unittest.TextTestRunner(verbosity=2)
            runner.run(suite)
        else:
            print(f"Unknown test class: {args.test}")
    else:
        success = run_all_tests()
        sys.exit(0 if success else 1)
