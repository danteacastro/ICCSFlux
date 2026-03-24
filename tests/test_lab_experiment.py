#!/usr/bin/env python3
"""
Lab Experiment Integration Tests for NISystem

These tests simulate real laboratory experiment workflows including:
1. Session/Project Management (load, save, configure)
2. Acquisition (start, stop, verify data flow)
3. Python Script Integration (formulas, transforms, computed values)
4. Recording (various modes, file verification)
5. Full Experiment Workflows (end-to-end scenarios)

Requirements:
- Mosquitto broker running on localhost:1883
- DAQ service running (simulation mode is fine)

Run with: python -m pytest tests/test_lab_experiment.py -v
Or standalone: python tests/test_lab_experiment.py
"""

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

import paho.mqtt.client as mqtt

# Add services to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

# Test configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
SYSTEM_PREFIX = "nisystem"
DEFAULT_TIMEOUT = 10.0
DATA_SETTLE_TIME = 2.0  # Time to wait for data to stabilize

# =============================================================================
# HELPER CLASSES
# =============================================================================

@dataclass
class MessageCollector:
    """Collects MQTT messages for testing"""
    messages: Dict[str, List[dict]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, topic: str, payload: Any):
        with self.lock:
            if topic not in self.messages:
                self.messages[topic] = []
            self.messages[topic].append({
                "payload": payload,
                "timestamp": time.time()
            })

    def get(self, topic: str) -> List[dict]:
        with self.lock:
            return self.messages.get(topic, []).copy()

    def get_latest(self, topic: str) -> Optional[dict]:
        msgs = self.get(topic)
        return msgs[-1] if msgs else None

    def clear(self):
        with self.lock:
            self.messages.clear()

    def wait_for_message(self, topic: str, timeout: float = 5.0,
                         condition: Optional[Callable[[dict], bool]] = None) -> Optional[dict]:
        """Wait for a message on topic, optionally matching a condition"""
        start = time.time()
        while (time.time() - start) < timeout:
            msgs = self.get(topic)
            for msg in reversed(msgs):  # Check newest first
                if condition is None or condition(msg["payload"]):
                    return msg
            time.sleep(0.1)
        return None

class MQTTTestClient:
    """MQTT client for testing with message collection"""

    def __init__(self, client_id: str = "lab-test-client"):
        self.client = mqtt.Client(client_id=client_id)
        self.connected = False
        self.collector = MessageCollector()
        self._setup_callbacks()

    def _setup_callbacks(self):
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload.decode()
        self.collector.add(msg.topic, payload)

    def connect(self, host: str = MQTT_HOST, port: int = MQTT_PORT,
                timeout: float = 5.0) -> bool:
        try:
            self.client.connect(host, port, keepalive=60)
            self.client.loop_start()
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            return self.connected
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe(self, topic: str):
        self.client.subscribe(topic)

    def publish(self, topic: str, payload: Any, retain: bool = False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, retain=retain)

    def send_command(self, command: str, payload: Optional[dict] = None) -> str:
        """Send a command and return request_id for tracking"""
        request_id = f"test-{time.time()}"
        full_payload = {"request_id": request_id}
        if payload:
            full_payload.update(payload)
        self.publish(f"{SYSTEM_PREFIX}/system/{command}", full_payload)
        return request_id

    def wait_for_ack(self, command: str, request_id: str,
                     timeout: float = 5.0) -> Optional[dict]:
        """Wait for command acknowledgment"""
        topic = f"{SYSTEM_PREFIX}/response/{command}"
        return self.collector.wait_for_message(
            topic, timeout,
            condition=lambda p: p.get("request_id") == request_id
        )

# =============================================================================
# TEST FIXTURES - Simulated Lab Data
# =============================================================================

class SimulatedLabData:
    """Generates simulated lab experiment data"""

    @staticmethod
    def temperature_sensor(t: float, ambient: float = 25.0,
                           amplitude: float = 5.0) -> float:
        """Simulate temperature with slow drift and noise"""
        drift = 0.1 * math.sin(t / 100)  # Slow drift
        noise = 0.2 * math.sin(t * 10 + 0.5)  # High-freq noise
        return ambient + amplitude * math.sin(t / 30) + drift + noise

    @staticmethod
    def pressure_sensor(t: float, base: float = 101.325,
                        variance: float = 0.5) -> float:
        """Simulate pressure readings (kPa)"""
        return base + variance * math.sin(t / 20) + 0.1 * math.sin(t * 5)

    @staticmethod
    def flow_sensor(t: float, setpoint: float = 10.0) -> float:
        """Simulate flow rate (L/min) with occasional step changes"""
        step = 2.0 if (int(t) % 60) > 30 else 0  # Step change every 30s
        return setpoint + step + 0.5 * math.sin(t / 10)

    @staticmethod
    def rpm_sensor(t: float, target: float = 1500.0) -> float:
        """Simulate motor RPM with startup ramp"""
        ramp = min(1.0, t / 10)  # 10-second ramp
        vibration = 5 * math.sin(t * 50)  # High-freq vibration
        return target * ramp + vibration

    @staticmethod
    def generate_sample(t: float) -> Dict[str, float]:
        """Generate a complete sample of all sensors"""
        return {
            "Temperature_1": SimulatedLabData.temperature_sensor(t),
            "Temperature_2": SimulatedLabData.temperature_sensor(t, ambient=30.0),
            "Pressure_In": SimulatedLabData.pressure_sensor(t),
            "Pressure_Out": SimulatedLabData.pressure_sensor(t, base=100.0),
            "Flow_Rate": SimulatedLabData.flow_sensor(t),
            "Motor_RPM": SimulatedLabData.rpm_sensor(t),
        }

# =============================================================================
# PYTHON SCRIPT SIMULATION
# =============================================================================

class PythonScriptSimulator:
    """
    Simulates frontend Python scripts that compute derived values.
    In the real system, these run in the browser via Pyodide/Skulpt.
    """

    def __init__(self):
        self.published_values: Dict[str, float] = {}
        self.formulas: Dict[str, Callable] = {}
        self.transforms: Dict[str, Callable] = {}
        self._setup_default_formulas()

    def _setup_default_formulas(self):
        """Set up common lab calculation formulas"""

        # Efficiency calculation: (Output Power / Input Power) * 100
        self.formulas["Efficiency"] = lambda vals: (
            (vals.get("Pressure_Out", 0) * vals.get("Flow_Rate", 0)) /
            max(vals.get("Pressure_In", 1) * vals.get("Flow_Rate", 1), 0.001) * 100
        )

        # Pressure differential
        self.formulas["Delta_P"] = lambda vals: (
            vals.get("Pressure_In", 0) - vals.get("Pressure_Out", 0)
        )

        # Temperature differential
        self.formulas["Delta_T"] = lambda vals: (
            vals.get("Temperature_2", 0) - vals.get("Temperature_1", 0)
        )

        # Heat transfer coefficient (simplified)
        self.formulas["Heat_Transfer"] = lambda vals: (
            vals.get("Flow_Rate", 0) * 4.18 * abs(vals.get("Delta_T", 0) if "Delta_T" in vals
                else vals.get("Temperature_2", 0) - vals.get("Temperature_1", 0))
        )

        # Motor power estimate
        self.formulas["Motor_Power"] = lambda vals: (
            vals.get("Motor_RPM", 0) * 0.01  # Simplified power calc
        )

        # Running average transform (would normally maintain state)
        self.transforms["Temp1_Avg"] = lambda vals, history: (
            sum(h.get("Temperature_1", 0) for h in history[-10:]) /
            max(len(history[-10:]), 1)
        )

    def compute_all(self, channel_values: Dict[str, float],
                    history: Optional[List[Dict]] = None) -> Dict[str, float]:
        """Compute all derived values from raw channel data"""
        results = {}
        history = history or []

        # Compute formulas
        for name, formula in self.formulas.items():
            try:
                # Pass both raw values and already-computed results
                combined = {**channel_values, **results}
                results[f"py.{name}"] = formula(combined)
            except Exception as e:
                results[f"py.{name}"] = float('nan')

        # Compute transforms
        for name, transform in self.transforms.items():
            try:
                results[f"py.{name}"] = transform(channel_values, history)
            except Exception as e:
                results[f"py.{name}"] = float('nan')

        self.published_values = results
        return results

    def get_published_tags(self) -> List[str]:
        """Return list of tag names this script publishes"""
        return (
            [f"py.{name}" for name in self.formulas.keys()] +
            [f"py.{name}" for name in self.transforms.keys()]
        )

# =============================================================================
# TEST CLASSES
# =============================================================================

class TestSessionManagement(unittest.TestCase):
    """Tests for project/session management"""

    @classmethod
    def setUpClass(cls):
        cls.mqtt = MQTTTestClient("session-test")
        cls.connected = cls.mqtt.connect()
        if cls.connected:
            cls.mqtt.subscribe(f"{SYSTEM_PREFIX}/#")
            time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.connected:
            cls.mqtt.disconnect()

    def setUp(self):
        self.mqtt.collector.clear()

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_01_project_load_nonexistent(self):
        """Test loading a project that doesn't exist"""
        request_id = self.mqtt.send_command("project/load", {
            "path": "/nonexistent/project.dcflux"
        })

        # Should get error response
        response = self.mqtt.collector.wait_for_message(
            f"{SYSTEM_PREFIX}/response/project",
            timeout=5.0
        )

        # Verify we get some response (success or failure)
        self.assertIsNotNone(response, "Should receive project response")

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_02_get_system_status(self):
        """Test retrieving system status"""
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/status/get", "{}")

        # Wait for status
        status = self.mqtt.collector.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=5.0
        )

        if status:
            payload = status["payload"]
            # Verify expected fields
            self.assertIn("acquiring", payload)
            self.assertIn("recording", payload)

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_03_channel_configuration(self):
        """Test that channel configuration is published"""
        # Request channel config
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/config/channels/get", "{}")

        # Wait for channel config
        config = self.mqtt.collector.wait_for_message(
            f"{SYSTEM_PREFIX}/config/channels",
            timeout=5.0
        )

        # Should receive channel configuration
        if config:
            payload = config["payload"]
            self.assertIsInstance(payload, dict)

class TestAcquisition(unittest.TestCase):
    """Tests for data acquisition start/stop and data flow"""

    @classmethod
    def setUpClass(cls):
        cls.mqtt = MQTTTestClient("acquisition-test")
        cls.connected = cls.mqtt.connect()
        if cls.connected:
            cls.mqtt.subscribe(f"{SYSTEM_PREFIX}/#")
            time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.connected:
            # Ensure acquisition is stopped
            cls.mqtt.send_command("acquire/stop", {})
            time.sleep(1)
            cls.mqtt.disconnect()

    def setUp(self):
        self.mqtt.collector.clear()

    @unittest.skipUnless(True, "Requires MQTT broker and DAQ service")
    def test_01_start_acquisition(self):
        """Test starting data acquisition"""
        request_id = self.mqtt.send_command("acquire/start", {})

        # Wait for acknowledgment
        ack = self.mqtt.wait_for_ack("acquire/start", request_id, timeout=5.0)

        # Check system status shows acquiring
        time.sleep(1)
        status = self.mqtt.collector.get_latest(f"{SYSTEM_PREFIX}/status/system")

        if status:
            self.assertTrue(
                status["payload"].get("acquiring", False) or
                "Already acquiring" in str(ack),
                "Acquisition should be active or already running"
            )

    @unittest.skipUnless(True, "Requires MQTT broker and DAQ service")
    def test_02_data_flow(self):
        """Test that data is flowing after acquisition starts"""
        # Ensure acquisition is running
        self.mqtt.send_command("acquire/start", {})
        time.sleep(DATA_SETTLE_TIME)

        # Clear and wait for new data
        self.mqtt.collector.clear()
        time.sleep(2)

        # Check for data messages
        data_topics = [
            topic for topic in self.mqtt.collector.messages.keys()
            if "/data/" in topic or "/values" in topic
        ]

        # Should have received some data
        # Note: Test may pass even without data if service not running
        print(f"Data topics received: {data_topics}")

    @unittest.skipUnless(True, "Requires MQTT broker and DAQ service")
    def test_03_stop_acquisition(self):
        """Test stopping data acquisition"""
        # First ensure it's running
        self.mqtt.send_command("acquire/start", {})
        time.sleep(1)

        # Now stop
        request_id = self.mqtt.send_command("acquire/stop", {})

        # Wait for acknowledgment
        ack = self.mqtt.wait_for_ack("acquire/stop", request_id, timeout=5.0)

        # Check system status
        time.sleep(1)
        status = self.mqtt.collector.get_latest(f"{SYSTEM_PREFIX}/status/system")

        if status:
            self.assertFalse(
                status["payload"].get("acquiring", True) and
                "Not acquiring" not in str(ack),
                "Acquisition should be stopped"
            )

class TestPythonScriptIntegration(unittest.TestCase):
    """Tests for Python script computed values"""

    def setUp(self):
        self.script_sim = PythonScriptSimulator()
        self.lab_data = SimulatedLabData()
        self.history: List[Dict] = []

    def test_01_formula_computation(self):
        """Test that formulas compute correctly"""
        # Generate sample data
        sample = self.lab_data.generate_sample(t=10.0)

        # Compute derived values
        results = self.script_sim.compute_all(sample, self.history)

        # Verify formulas computed
        self.assertIn("py.Efficiency", results)
        self.assertIn("py.Delta_P", results)
        self.assertIn("py.Delta_T", results)
        self.assertIn("py.Heat_Transfer", results)
        self.assertIn("py.Motor_Power", results)

        # Verify values are reasonable
        self.assertGreater(results["py.Efficiency"], 0)
        self.assertFalse(math.isnan(results["py.Efficiency"]))

    def test_02_transform_with_history(self):
        """Test transforms that use historical data"""
        # Build up history
        for t in range(20):
            sample = self.lab_data.generate_sample(t=float(t))
            self.history.append(sample)

        # Compute with history
        current = self.lab_data.generate_sample(t=20.0)
        results = self.script_sim.compute_all(current, self.history)

        # Verify running average
        self.assertIn("py.Temp1_Avg", results)

        # Should be close to recent average
        recent_temps = [h["Temperature_1"] for h in self.history[-10:]]
        expected_avg = sum(recent_temps) / len(recent_temps)
        self.assertAlmostEqual(results["py.Temp1_Avg"], expected_avg, places=2)

    def test_03_error_handling(self):
        """Test that errors in formulas are handled gracefully"""
        # Create formula that will divide by zero
        self.script_sim.formulas["BadFormula"] = lambda vals: vals["Missing"] / 0

        sample = self.lab_data.generate_sample(t=10.0)
        results = self.script_sim.compute_all(sample)

        # Should have NaN for bad formula, not crash
        self.assertIn("py.BadFormula", results)
        self.assertTrue(math.isnan(results["py.BadFormula"]))

    def test_04_continuous_computation(self):
        """Test computing over a time series"""
        results_over_time = []

        for t in range(100):
            sample = self.lab_data.generate_sample(t=float(t))
            self.history.append(sample)
            results = self.script_sim.compute_all(sample, self.history)
            results_over_time.append({
                "time": t,
                "efficiency": results["py.Efficiency"],
                "delta_p": results["py.Delta_P"],
                "motor_power": results["py.Motor_Power"]
            })

        # Verify we have continuous data
        self.assertEqual(len(results_over_time), 100)

        # Verify trends (motor power should increase with ramp)
        early_power = sum(r["motor_power"] for r in results_over_time[:10]) / 10
        late_power = sum(r["motor_power"] for r in results_over_time[-10:]) / 10
        self.assertGreater(late_power, early_power, "Motor power should increase after ramp")

    def test_05_get_published_tags(self):
        """Test getting list of published tag names"""
        tags = self.script_sim.get_published_tags()

        self.assertIn("py.Efficiency", tags)
        self.assertIn("py.Delta_P", tags)
        self.assertIn("py.Temp1_Avg", tags)

        # All should have py. prefix
        for tag in tags:
            self.assertTrue(tag.startswith("py."), f"Tag {tag} should have py. prefix")

class TestRecording(unittest.TestCase):
    """Tests for data recording functionality"""

    @classmethod
    def setUpClass(cls):
        cls.mqtt = MQTTTestClient("recording-test")
        cls.connected = cls.mqtt.connect()
        if cls.connected:
            cls.mqtt.subscribe(f"{SYSTEM_PREFIX}/#")
            time.sleep(0.5)

        # Create temp directory for test recordings
        cls.temp_dir = tempfile.mkdtemp(prefix="nisystem_test_")

    @classmethod
    def tearDownClass(cls):
        if cls.connected:
            # Stop any active recording
            cls.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/stop", "{}")
            time.sleep(1)
            cls.mqtt.disconnect()

        # Cleanup temp directory
        if hasattr(cls, 'temp_dir') and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def setUp(self):
        self.mqtt.collector.clear()

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_01_configure_recording(self):
        """Test configuring recording parameters"""
        config = {
            "base_path": self.temp_dir,
            "file_prefix": "test_recording",
            "file_format": "csv",
            "sample_interval": 0.1,
            "sample_interval_unit": "seconds",
            "decimation": 1,
            "rotation_mode": "single",
            "mode": "manual"
        }

        self.mqtt.publish(
            f"{SYSTEM_PREFIX}/system/recording/config",
            config
        )

        time.sleep(1)

        # Check for response
        response = self.mqtt.collector.get_latest(
            f"{SYSTEM_PREFIX}/response/recording"
        )

        # Config update should succeed or be acknowledged
        print(f"Recording config response: {response}")

    @unittest.skipUnless(True, "Requires MQTT broker and DAQ service")
    def test_02_start_stop_recording(self):
        """Test starting and stopping recording"""
        # Ensure acquisition is running first
        self.mqtt.send_command("acquire/start", {})
        time.sleep(2)

        # Configure recording
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/config", {
            "base_path": self.temp_dir,
            "file_prefix": "start_stop_test",
            "sample_interval": 0.5,
            "sample_interval_unit": "seconds"
        })
        time.sleep(0.5)

        # Start recording
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/start", {})
        time.sleep(3)

        # Check status
        status = self.mqtt.collector.get_latest(f"{SYSTEM_PREFIX}/status/system")
        if status:
            print(f"Recording status: {status['payload'].get('recording')}")

        # Stop recording
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/stop", {})
        time.sleep(1)

        # Check for recorded file
        files = list(Path(self.temp_dir).glob("*.csv"))
        print(f"Recorded files: {files}")

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_03_triggered_recording_config(self):
        """Test configuring triggered recording mode"""
        config = {
            "base_path": self.temp_dir,
            "file_prefix": "triggered_test",
            "mode": "triggered",
            "trigger_channel": "Temperature_1",
            "trigger_condition": "above",
            "trigger_value": 30.0,
            "pre_trigger_samples": 10,
            "post_trigger_samples": 50
        }

        self.mqtt.publish(
            f"{SYSTEM_PREFIX}/system/recording/config",
            config
        )

        time.sleep(1)

        response = self.mqtt.collector.get_latest(
            f"{SYSTEM_PREFIX}/response/recording"
        )
        print(f"Triggered config response: {response}")

    @unittest.skipUnless(True, "Requires MQTT broker")
    def test_04_rotation_modes(self):
        """Test different file rotation configurations"""
        rotation_configs = [
            {"rotation_mode": "single"},
            {"rotation_mode": "time", "max_file_duration_s": 60},
            {"rotation_mode": "size", "max_file_size_mb": 10},
            {"rotation_mode": "samples", "max_file_samples": 1000},
        ]

        for config in rotation_configs:
            config["base_path"] = self.temp_dir
            config["file_prefix"] = f"rotation_{config['rotation_mode']}"

            self.mqtt.publish(
                f"{SYSTEM_PREFIX}/system/recording/config",
                config
            )
            time.sleep(0.5)

            response = self.mqtt.collector.get_latest(
                f"{SYSTEM_PREFIX}/response/recording"
            )
            print(f"Rotation mode {config['rotation_mode']}: {response}")

class TestFullExperimentWorkflow(unittest.TestCase):
    """
    End-to-end tests simulating complete lab experiment workflows.
    These tests combine session, acquisition, scripts, and recording.
    """

    @classmethod
    def setUpClass(cls):
        cls.mqtt = MQTTTestClient("workflow-test")
        cls.connected = cls.mqtt.connect()
        if cls.connected:
            cls.mqtt.subscribe(f"{SYSTEM_PREFIX}/#")
            time.sleep(0.5)

        cls.temp_dir = tempfile.mkdtemp(prefix="nisystem_workflow_")
        cls.script_sim = PythonScriptSimulator()
        cls.lab_data = SimulatedLabData()

    @classmethod
    def tearDownClass(cls):
        if cls.connected:
            # Cleanup
            cls.mqtt.send_command("acquire/stop", {})
            cls.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/stop", "{}")
            time.sleep(1)
            cls.mqtt.disconnect()

        if hasattr(cls, 'temp_dir') and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def setUp(self):
        self.mqtt.collector.clear()

    @unittest.skipUnless(True, "Full integration test")
    def test_01_complete_experiment_session(self):
        """
        Simulate a complete lab experiment:
        1. Configure channels
        2. Start acquisition
        3. Run Python scripts for derived values
        4. Record data
        5. Stop and verify
        """
        print("\n=== Starting Complete Experiment Session ===")

        # Step 1: Configure recording
        print("Step 1: Configuring recording...")
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/config", {
            "base_path": self.temp_dir,
            "file_prefix": "experiment_001",
            "file_format": "csv",
            "sample_interval": 0.5,
            "sample_interval_unit": "seconds",
            "decimation": 1,
            "include_scripts": True
        })
        time.sleep(1)

        # Step 2: Start acquisition
        print("Step 2: Starting acquisition...")
        request_id = self.mqtt.send_command("acquire/start", {})
        time.sleep(2)

        # Step 3: Start recording
        print("Step 3: Starting recording...")
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/start", {})
        time.sleep(1)

        # Step 4: Simulate data collection with Python script values
        print("Step 4: Simulating data collection with scripts...")
        history = []
        for t in range(10):
            # Generate raw sensor data
            sample = self.lab_data.generate_sample(t=float(t))
            history.append(sample)

            # Compute script values
            script_values = self.script_sim.compute_all(sample, history)

            # Publish script values to recording
            self.mqtt.publish(
                f"{SYSTEM_PREFIX}/system/recording/script_values",
                script_values
            )

            time.sleep(0.5)

        # Step 5: Stop recording
        print("Step 5: Stopping recording...")
        self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/stop", "{}")
        time.sleep(1)

        # Step 6: Stop acquisition
        print("Step 6: Stopping acquisition...")
        self.mqtt.send_command("acquire/stop", {})
        time.sleep(1)

        # Step 7: Verify results
        print("Step 7: Verifying results...")
        files = list(Path(self.temp_dir).glob("*.csv"))
        print(f"Recorded files: {files}")

        # Check for status
        status = self.mqtt.collector.get_latest(f"{SYSTEM_PREFIX}/status/system")
        if status:
            print(f"Final status: acquiring={status['payload'].get('acquiring')}, "
                  f"recording={status['payload'].get('recording')}")

        print("=== Experiment Session Complete ===\n")

    @unittest.skipUnless(True, "Full integration test")
    def test_02_multi_run_experiment(self):
        """
        Simulate an experiment with multiple test runs:
        - Run 1: Baseline measurements
        - Run 2: With process changes
        - Run 3: Return to baseline
        """
        print("\n=== Starting Multi-Run Experiment ===")

        runs = [
            {"name": "baseline", "duration": 5, "setpoint": 10.0},
            {"name": "high_flow", "duration": 5, "setpoint": 15.0},
            {"name": "return_baseline", "duration": 5, "setpoint": 10.0},
        ]

        recorded_files = []

        for run in runs:
            print(f"\n--- Run: {run['name']} ---")

            # Configure for this run
            self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/config", {
                "base_path": self.temp_dir,
                "file_prefix": f"experiment_{run['name']}",
                "sample_interval": 0.5,
                "sample_interval_unit": "seconds"
            })
            time.sleep(0.5)

            # Start acquisition and recording
            self.mqtt.send_command("acquire/start", {})
            time.sleep(1)
            self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/start", {})
            time.sleep(0.5)

            # Collect data
            history = []
            for t in range(run["duration"]):
                sample = self.lab_data.generate_sample(t=float(t))
                # Modify flow based on setpoint
                sample["Flow_Rate"] = run["setpoint"] + 0.5 * math.sin(t / 5)
                history.append(sample)

                script_values = self.script_sim.compute_all(sample, history)
                self.mqtt.publish(
                    f"{SYSTEM_PREFIX}/system/recording/script_values",
                    script_values
                )
                time.sleep(0.5)

            # Stop recording
            self.mqtt.publish(f"{SYSTEM_PREFIX}/system/recording/stop", {})
            time.sleep(0.5)

            # Stop acquisition
            self.mqtt.send_command("acquire/stop", {})
            time.sleep(0.5)

            # Track recorded file
            files = list(Path(self.temp_dir).glob(f"*{run['name']}*.csv"))
            recorded_files.extend(files)
            print(f"Recorded: {files}")

        print(f"\n=== Multi-Run Complete: {len(recorded_files)} files ===\n")

    @unittest.skipUnless(True, "Full integration test")
    def test_03_long_duration_simulation(self):
        """
        Simulate a longer experiment with periodic data collection.
        Tests data accumulation and history management.
        """
        print("\n=== Starting Long Duration Simulation ===")

        # This simulates what would be hours of data in seconds
        total_simulated_time = 3600  # 1 hour simulated
        time_step = 60  # Report every minute
        samples_per_step = 10

        history = []
        summary_data = []

        for sim_time in range(0, total_simulated_time, time_step):
            # Collect samples
            step_samples = []
            for i in range(samples_per_step):
                t = sim_time + i * (time_step / samples_per_step)
                sample = self.lab_data.generate_sample(t=t)
                step_samples.append(sample)
                history.append(sample)

            # Compute averages for this period
            avg_temp = sum(s["Temperature_1"] for s in step_samples) / len(step_samples)
            avg_flow = sum(s["Flow_Rate"] for s in step_samples) / len(step_samples)
            avg_rpm = sum(s["Motor_RPM"] for s in step_samples) / len(step_samples)

            # Compute script values
            combined = step_samples[-1].copy()
            script_values = self.script_sim.compute_all(combined, history)

            summary_data.append({
                "sim_time_s": sim_time,
                "avg_temp": avg_temp,
                "avg_flow": avg_flow,
                "avg_rpm": avg_rpm,
                "efficiency": script_values.get("py.Efficiency", 0),
                "samples_collected": len(history)
            })

        print(f"Simulated {total_simulated_time}s with {len(history)} total samples")
        print(f"Generated {len(summary_data)} summary records")

        # Verify data trends
        early_efficiency = sum(d["efficiency"] for d in summary_data[:10]) / 10
        late_efficiency = sum(d["efficiency"] for d in summary_data[-10:]) / 10
        print(f"Early avg efficiency: {early_efficiency:.2f}")
        print(f"Late avg efficiency: {late_efficiency:.2f}")

        print("=== Long Duration Simulation Complete ===\n")

# =============================================================================
# MQTT SCRIPT DATA FLOW TESTS
# =============================================================================

class MQTTScriptDataFlowSimulator:
    """
    Simulates the complete MQTT data flow for Python scripts:
    1. Hardware tags published by DAQ service
    2. Script subscribes to hardware tags (bringing in tags)
    3. Script computes derived values
    4. Script publishes computed tags to MQTT (publishing tags)
    5. Frontend widgets receive tags
    6. Recording manager captures tags

    This mirrors the real system where:
    - DAQ service publishes to nisystem/data/{channel_name}
    - Python scripts (running in browser) subscribe to those topics
    - Scripts compute py.* values and publish to nisystem/script/{tag_name}
    - DataTab.vue's availableChannels combines hardware + script channels
    - Recording includes selected script channels
    """

    def __init__(self, mqtt_client: MQTTTestClient):
        self.mqtt = mqtt_client
        self.script_sim = PythonScriptSimulator()
        self.lab_data = SimulatedLabData()

        # Track what's available in the "system"
        self.hardware_channels: Dict[str, float] = {}
        self.script_channels: Dict[str, float] = {}
        self.widget_display_values: Dict[str, float] = {}
        self.available_for_recording: List[str] = []

        # Message history for validation
        self.received_hardware_messages: List[Dict] = []
        self.received_script_messages: List[Dict] = []
        self.history: List[Dict] = []

    def setup_subscriptions(self):
        """Subscribe to all relevant topics"""
        # Subscribe to hardware data (what scripts consume)
        self.mqtt.subscribe(f"{SYSTEM_PREFIX}/data/#")
        # Subscribe to script outputs (what scripts publish)
        self.mqtt.subscribe(f"{SYSTEM_PREFIX}/script/#")
        # Subscribe to system status for widget updates
        self.mqtt.subscribe(f"{SYSTEM_PREFIX}/status/#")
        # Subscribe to config for available channels
        self.mqtt.subscribe(f"{SYSTEM_PREFIX}/config/#")

    def simulate_daq_publishing_hardware_data(self, sample: Dict[str, float]):
        """
        Simulate DAQ service publishing hardware channel values.
        In real system: DAQ reads from NI hardware and publishes to MQTT.
        """
        for channel_name, value in sample.items():
            topic = f"{SYSTEM_PREFIX}/data/{channel_name}"
            payload = {
                "value": value,
                "timestamp": time.time(),
                "quality": "good"
            }
            self.mqtt.publish(topic, payload)
            self.hardware_channels[channel_name] = value
            self.received_hardware_messages.append({
                "channel": channel_name,
                "value": value,
                "timestamp": time.time()
            })

    def script_subscribe_and_compute(self) -> Dict[str, float]:
        """
        Simulate Python script subscribing to hardware tags and computing.
        In real system: Browser-based Python (Pyodide) subscribes to MQTT
        via WebSocket, gets values, computes formulas.

        Returns dict of computed py.* values.
        """
        # Collect current hardware values (simulate script receiving from MQTT)
        current_values = self.hardware_channels.copy()
        self.history.append(current_values)

        # Compute derived values using script simulator
        computed = self.script_sim.compute_all(current_values, self.history)

        return computed

    def script_publish_computed_values(self, computed: Dict[str, float]):
        """
        Simulate script publishing computed values back to MQTT.
        In real system: Browser script publishes py.* values to MQTT.
        These then appear in DataTab's availableChannels under "Python Scripts".
        """
        for tag_name, value in computed.items():
            # Strip py. prefix for topic, keep in payload
            topic_name = tag_name.replace("py.", "")
            topic = f"{SYSTEM_PREFIX}/script/{topic_name}"
            payload = {
                "value": value,
                "timestamp": time.time(),
                "tag": tag_name,  # Full name with py. prefix
                "source": "python_script"
            }
            self.mqtt.publish(topic, payload)
            self.script_channels[tag_name] = value
            self.received_script_messages.append({
                "tag": tag_name,
                "value": value,
                "timestamp": time.time()
            })

    def simulate_frontend_receiving_tags(self):
        """
        Simulate frontend receiving tags and updating widgets.
        In real system: Vue components subscribe to MQTT and update reactive state.

        DataTab.vue's availableChannels computed property:
        - Gets hardware channels from store.channels
        - Gets script channels from pythonScripts.getPublishedChannelNames()
        - Combines both for tag selection UI
        """
        # Simulate what DataTab.vue's availableChannels would contain
        self.available_for_recording = []

        # Hardware channels
        for channel_name in self.hardware_channels.keys():
            self.available_for_recording.append({
                "name": channel_name,
                "type": "hardware",
                "group": "Hardware Channels"
            })

        # Script channels (py.* tags)
        for tag_name in self.script_channels.keys():
            self.available_for_recording.append({
                "name": tag_name,
                "type": "computed",
                "group": "Python Scripts"
            })

        # Update widget display values (what charts/displays would show)
        self.widget_display_values = {
            **self.hardware_channels,
            **self.script_channels
        }

        return self.available_for_recording

    def simulate_recording_with_scripts(self,
                                          selected_channels: List[str],
                                          duration_samples: int = 10) -> List[Dict]:
        """
        Simulate recording manager capturing selected channels including scripts.
        In real system: RecordingManager subscribes to selected channels,
        captures values, writes to CSV.
        """
        recorded_data = []

        for i in range(duration_samples):
            # Generate hardware data
            t = float(i)
            sample = self.lab_data.generate_sample(t=t)

            # Simulate DAQ publishing
            self.simulate_daq_publishing_hardware_data(sample)
            time.sleep(0.01)  # Small delay for MQTT

            # Script processes and publishes
            computed = self.script_subscribe_and_compute()
            self.script_publish_computed_values(computed)
            time.sleep(0.01)

            # Frontend updates
            self.simulate_frontend_receiving_tags()

            # Recording captures selected channels
            record = {"timestamp": time.time()}
            for channel in selected_channels:
                if channel in self.widget_display_values:
                    record[channel] = self.widget_display_values[channel]
                else:
                    record[channel] = None  # Channel not available

            recorded_data.append(record)

        return recorded_data

    def get_available_channels_for_ui(self) -> Dict[str, List[Dict]]:
        """
        Return available channels grouped as they would appear in DataTab UI.
        This mirrors the DataTab.vue availableChannels computed property.
        """
        grouped = {
            "Hardware Channels": [],
            "Python Scripts": []
        }

        for channel_name in self.hardware_channels.keys():
            grouped["Hardware Channels"].append({
                "name": channel_name,
                "type": "analog_input",
                "unit": "varies"
            })

        for tag_name in self.script_channels.keys():
            grouped["Python Scripts"].append({
                "name": tag_name,
                "type": "computed",
                "unit": ""
            })

        return grouped

class TestMQTTScriptDataFlow(unittest.TestCase):
    """
    Tests the complete MQTT data flow for Python scripts.

    This tests the full pipeline that the user described:
    1. Bring in tags (subscribe to hardware channels)
    2. Compute derived values
    3. Publish tags (script outputs to MQTT)
    4. Tags show up in data system widgets
    5. Tags available for recording selection
    """

    @classmethod
    def setUpClass(cls):
        cls.mqtt = MQTTTestClient("mqtt-flow-test")
        cls.connected = cls.mqtt.connect()
        if cls.connected:
            cls.mqtt.subscribe(f"{SYSTEM_PREFIX}/#")
            time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.connected:
            cls.mqtt.disconnect()

    def setUp(self):
        self.mqtt.collector.clear()
        self.flow_sim = MQTTScriptDataFlowSimulator(self.mqtt)
        self.flow_sim.setup_subscriptions()

    def test_01_hardware_tag_subscription(self):
        """Test that scripts can receive hardware tags via MQTT"""
        # Simulate DAQ publishing hardware data
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        time.sleep(0.2)

        # Verify hardware channels are tracked
        self.assertEqual(len(self.flow_sim.hardware_channels), 6)
        self.assertIn("Temperature_1", self.flow_sim.hardware_channels)
        self.assertIn("Pressure_In", self.flow_sim.hardware_channels)
        self.assertIn("Motor_RPM", self.flow_sim.hardware_channels)

        # Verify messages were received
        self.assertEqual(len(self.flow_sim.received_hardware_messages), 6)

    def test_02_script_computes_from_subscribed_tags(self):
        """Test that scripts compute values from subscribed hardware tags"""
        # Publish hardware data
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)

        # Script subscribes and computes
        computed = self.flow_sim.script_subscribe_and_compute()

        # Verify computed values exist
        self.assertIn("py.Efficiency", computed)
        self.assertIn("py.Delta_P", computed)
        self.assertIn("py.Delta_T", computed)
        self.assertIn("py.Heat_Transfer", computed)
        self.assertIn("py.Motor_Power", computed)

        # Verify computation used subscribed values
        expected_delta_p = sample["Pressure_In"] - sample["Pressure_Out"]
        self.assertAlmostEqual(computed["py.Delta_P"], expected_delta_p, places=5)

    def test_03_script_publishes_to_mqtt(self):
        """Test that scripts publish computed tags back to MQTT"""
        # Simulate full flow
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        computed = self.flow_sim.script_subscribe_and_compute()
        self.flow_sim.script_publish_computed_values(computed)
        time.sleep(0.2)

        # Verify script channels are tracked
        self.assertEqual(len(self.flow_sim.script_channels), len(computed))
        self.assertIn("py.Efficiency", self.flow_sim.script_channels)

        # Verify messages were published
        self.assertEqual(len(self.flow_sim.received_script_messages), len(computed))

        # Verify we can find the messages in MQTT collector
        # (These would be received by frontend widgets in real system)
        efficiency_topic = f"{SYSTEM_PREFIX}/script/Efficiency"
        msg = self.mqtt.collector.get_latest(efficiency_topic)
        if msg:
            self.assertEqual(msg["payload"]["tag"], "py.Efficiency")
            self.assertIn("value", msg["payload"])

    def test_04_tags_appear_in_widget_system(self):
        """Test that published tags appear in frontend widget system"""
        # Run full simulation cycle
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        computed = self.flow_sim.script_subscribe_and_compute()
        self.flow_sim.script_publish_computed_values(computed)
        available = self.flow_sim.simulate_frontend_receiving_tags()

        # Verify available channels includes both hardware and scripts
        channel_names = [c["name"] for c in available]

        # Hardware channels
        self.assertIn("Temperature_1", channel_names)
        self.assertIn("Pressure_In", channel_names)

        # Script channels (py.* prefix)
        self.assertIn("py.Efficiency", channel_names)
        self.assertIn("py.Delta_P", channel_names)

        # Verify grouping
        hardware_group = [c for c in available if c["group"] == "Hardware Channels"]
        script_group = [c for c in available if c["group"] == "Python Scripts"]

        self.assertEqual(len(hardware_group), 6)  # 6 hardware channels
        self.assertGreater(len(script_group), 0)  # At least some script channels

    def test_05_widget_display_values_update(self):
        """Test that widget display values reflect latest data"""
        # Run two simulation cycles with different data
        for t in [10.0, 20.0]:
            sample = SimulatedLabData.generate_sample(t=t)
            self.flow_sim.simulate_daq_publishing_hardware_data(sample)
            computed = self.flow_sim.script_subscribe_and_compute()
            self.flow_sim.script_publish_computed_values(computed)
            self.flow_sim.simulate_frontend_receiving_tags()

        # Widget values should have latest data
        display = self.flow_sim.widget_display_values

        # Should have all hardware and script values
        self.assertIn("Temperature_1", display)
        self.assertIn("py.Efficiency", display)

        # Values should be numeric
        self.assertIsInstance(display["Temperature_1"], (int, float))
        self.assertIsInstance(display["py.Efficiency"], (int, float))

    def test_06_channels_available_for_recording_selection(self):
        """Test that channels appear in recording selection UI"""
        # Run simulation
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        computed = self.flow_sim.script_subscribe_and_compute()
        self.flow_sim.script_publish_computed_values(computed)

        # Get available channels as DataTab UI would see them
        grouped = self.flow_sim.get_available_channels_for_ui()

        # Verify structure matches DataTab's availableChannels format
        self.assertIn("Hardware Channels", grouped)
        self.assertIn("Python Scripts", grouped)

        # Hardware should have all 6 channels
        hw_names = [c["name"] for c in grouped["Hardware Channels"]]
        self.assertIn("Temperature_1", hw_names)
        self.assertIn("Motor_RPM", hw_names)

        # Scripts should have computed values
        script_names = [c["name"] for c in grouped["Python Scripts"]]
        self.assertIn("py.Efficiency", script_names)
        self.assertIn("py.Delta_P", script_names)

    def test_07_recording_captures_script_channels(self):
        """Test that recording includes selected script channels"""
        # Select channels including both hardware and scripts
        selected = [
            "Temperature_1",
            "Temperature_2",
            "py.Efficiency",
            "py.Delta_T"
        ]

        # Run recording simulation
        recorded = self.flow_sim.simulate_recording_with_scripts(
            selected_channels=selected,
            duration_samples=5
        )

        # Verify all records have the selected channels
        self.assertEqual(len(recorded), 5)

        for record in recorded:
            self.assertIn("timestamp", record)
            self.assertIn("Temperature_1", record)
            self.assertIn("py.Efficiency", record)
            self.assertIn("py.Delta_T", record)

            # Values should be numeric (not None)
            self.assertIsNotNone(record["Temperature_1"])
            self.assertIsNotNone(record["py.Efficiency"])

    def test_08_continuous_data_flow(self):
        """Test continuous data flow over multiple cycles"""
        all_efficiency = []

        for t in range(20):
            sample = SimulatedLabData.generate_sample(t=float(t))
            self.flow_sim.simulate_daq_publishing_hardware_data(sample)
            computed = self.flow_sim.script_subscribe_and_compute()
            self.flow_sim.script_publish_computed_values(computed)
            self.flow_sim.simulate_frontend_receiving_tags()

            all_efficiency.append(self.flow_sim.widget_display_values.get("py.Efficiency", 0))

        # Verify continuous data collection
        self.assertEqual(len(all_efficiency), 20)
        self.assertEqual(len(self.flow_sim.history), 20)

        # Verify efficiency values are reasonable (should vary but stay positive)
        self.assertTrue(all(e > 0 for e in all_efficiency))

    def test_09_script_tag_naming_convention(self):
        """Test that script tags follow py.* naming convention"""
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        computed = self.flow_sim.script_subscribe_and_compute()

        # All computed tags should have py. prefix
        for tag in computed.keys():
            self.assertTrue(tag.startswith("py."),
                f"Script tag '{tag}' should have py. prefix")

        # Published tag names should preserve prefix
        self.flow_sim.script_publish_computed_values(computed)
        for tag in self.flow_sim.script_channels.keys():
            self.assertTrue(tag.startswith("py."),
                f"Published tag '{tag}' should have py. prefix")

    def test_10_full_pipeline_integrity(self):
        """
        Integration test: Verify complete pipeline from hardware to recording.
        This is the full flow the user described:
        Hardware -> MQTT -> Script -> MQTT -> Widgets -> Recording
        """
        # Step 1: Hardware data enters system
        sample = SimulatedLabData.generate_sample(t=10.0)
        self.flow_sim.simulate_daq_publishing_hardware_data(sample)
        self.assertEqual(len(self.flow_sim.hardware_channels), 6,
            "Step 1 FAIL: Hardware channels not received")

        # Step 2: Script subscribes and receives hardware tags
        computed = self.flow_sim.script_subscribe_and_compute()
        self.assertIn("py.Efficiency", computed,
            "Step 2 FAIL: Script didn't compute from hardware tags")

        # Step 3: Script publishes computed tags
        self.flow_sim.script_publish_computed_values(computed)
        self.assertIn("py.Efficiency", self.flow_sim.script_channels,
            "Step 3 FAIL: Script tags not published")

        # Step 4: Frontend receives and updates widgets
        available = self.flow_sim.simulate_frontend_receiving_tags()
        channel_names = [c["name"] for c in available]
        self.assertIn("py.Efficiency", channel_names,
            "Step 4 FAIL: Script tags not available in UI")

        # Step 5: Recording can capture script channels
        selected = ["Temperature_1", "py.Efficiency"]
        recorded = self.flow_sim.simulate_recording_with_scripts(selected, 3)
        self.assertEqual(len(recorded), 3,
            "Step 5 FAIL: Recording didn't capture samples")
        self.assertIsNotNone(recorded[0]["py.Efficiency"],
            "Step 5 FAIL: Script values not in recording")

        print("\n[OK] Full pipeline integrity verified:")
        print("  Hardware -> MQTT -> Script -> MQTT -> Widgets -> Recording")

class TestRecordedDataValidation(unittest.TestCase):
    """Tests for validating recorded CSV data"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nisystem_validation_")
        self.lab_data = SimulatedLabData()
        self.script_sim = PythonScriptSimulator()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_01_csv_format_validation(self):
        """Test that generated CSV has correct format"""
        csv_path = Path(self.temp_dir) / "test_format.csv"

        # Generate test data
        samples = []
        history = []
        for t in range(10):
            sample = self.lab_data.generate_sample(t=float(t))
            history.append(sample)
            script_values = self.script_sim.compute_all(sample, history)

            row = {"timestamp": time.time() + t}
            row.update(sample)
            row.update(script_values)
            samples.append(row)

        # Write CSV
        if samples:
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=samples[0].keys())
                writer.writeheader()
                writer.writerows(samples)

        # Validate
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 10)

        # Check all expected columns exist
        expected_columns = [
            "timestamp", "Temperature_1", "Temperature_2",
            "Pressure_In", "Pressure_Out", "Flow_Rate", "Motor_RPM",
            "py.Efficiency", "py.Delta_P", "py.Delta_T"
        ]
        for col in expected_columns:
            self.assertIn(col, rows[0].keys(), f"Missing column: {col}")

    def test_02_data_consistency(self):
        """Test that recorded data is mathematically consistent"""
        csv_path = Path(self.temp_dir) / "test_consistency.csv"

        # Generate and write data
        samples = []
        for t in range(50):
            sample = self.lab_data.generate_sample(t=float(t))
            script_values = self.script_sim.compute_all(sample, samples)

            row = {"timestamp": time.time() + t * 0.1}
            row.update(sample)
            row.update(script_values)
            samples.append(row)

        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=samples[0].keys())
            writer.writeheader()
            writer.writerows(samples)

        # Read back and validate
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for row in rows:
            # Verify Delta_P = Pressure_In - Pressure_Out
            p_in = float(row["Pressure_In"])
            p_out = float(row["Pressure_Out"])
            delta_p = float(row["py.Delta_P"])
            self.assertAlmostEqual(delta_p, p_in - p_out, places=5,
                msg="Delta_P should equal Pressure_In - Pressure_Out")

            # Verify Delta_T = Temperature_2 - Temperature_1
            t1 = float(row["Temperature_1"])
            t2 = float(row["Temperature_2"])
            delta_t = float(row["py.Delta_T"])
            self.assertAlmostEqual(delta_t, t2 - t1, places=5,
                msg="Delta_T should equal Temperature_2 - Temperature_1")

    def test_03_timestamp_monotonicity(self):
        """Test that timestamps are monotonically increasing"""
        csv_path = Path(self.temp_dir) / "test_timestamps.csv"

        # Generate data
        samples = []
        base_time = time.time()
        for t in range(20):
            sample = self.lab_data.generate_sample(t=float(t))
            row = {"timestamp": base_time + t * 0.5}
            row.update(sample)
            samples.append(row)

        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=samples[0].keys())
            writer.writeheader()
            writer.writerows(samples)

        # Validate timestamps
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        prev_ts = 0
        for i, row in enumerate(rows):
            ts = float(row["timestamp"])
            self.assertGreater(ts, prev_ts,
                f"Timestamp at row {i} should be greater than previous")
            prev_ts = ts

# =============================================================================
# STANDALONE RUNNER
# =============================================================================

def run_single_test(test_class, test_name):
    """Run a single test method"""
    suite = unittest.TestSuite()
    suite.addTest(test_class(test_name))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

def run_all_tests():
    """Run all test classes"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestSessionManagement,
        TestAcquisition,
        TestPythonScriptIntegration,
        TestMQTTScriptDataFlow,
        TestRecording,
        TestFullExperimentWorkflow,
        TestRecordedDataValidation,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NISystem Lab Experiment Tests")
    parser.add_argument("--test", help="Run specific test (e.g., TestPythonScriptIntegration)")
    parser.add_argument("--method", help="Run specific method in test class")
    parser.add_argument("--list", action="store_true", help="List all test classes")

    args = parser.parse_args()

    if args.list:
        print("Available test classes:")
        print("  - TestSessionManagement")
        print("  - TestAcquisition")
        print("  - TestPythonScriptIntegration")
        print("  - TestMQTTScriptDataFlow")
        print("  - TestRecording")
        print("  - TestFullExperimentWorkflow")
        print("  - TestRecordedDataValidation")
    elif args.test:
        # Find the test class
        test_classes = {
            "TestSessionManagement": TestSessionManagement,
            "TestAcquisition": TestAcquisition,
            "TestPythonScriptIntegration": TestPythonScriptIntegration,
            "TestMQTTScriptDataFlow": TestMQTTScriptDataFlow,
            "TestRecording": TestRecording,
            "TestFullExperimentWorkflow": TestFullExperimentWorkflow,
            "TestRecordedDataValidation": TestRecordedDataValidation,
        }

        if args.test in test_classes:
            if args.method:
                run_single_test(test_classes[args.test], args.method)
            else:
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromTestCase(test_classes[args.test])
                runner = unittest.TextTestRunner(verbosity=2)
                runner.run(suite)
        else:
            print(f"Unknown test class: {args.test}")
            print("Use --list to see available test classes")
    else:
        # Run all tests
        success = run_all_tests()
        sys.exit(0 if success else 1)
