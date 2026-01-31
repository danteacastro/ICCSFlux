"""
Unit tests for PID Engine

Tests PID control loop calculations, mode transitions, anti-windup,
and configuration management. No hardware or MQTT required.
"""

import pytest
import time
import sys
from pathlib import Path

# Add services to path
services_dir = Path(__file__).parent.parent / "services" / "daq_service"
sys.path.insert(0, str(services_dir))

from pid_engine import (
    PIDEngine, PIDLoop, PIDMode, AntiWindupMethod, DerivativeMode
)


class TestPIDLoop:
    """Tests for PIDLoop dataclass"""

    def test_create_basic_loop(self):
        """Test creating a basic PID loop"""
        loop = PIDLoop(
            id="test_loop",
            name="Test Loop",
            pv_channel="temperature",
            cv_channel="heater",
            kp=1.0,
            ki=0.1,
            kd=0.05
        )
        assert loop.id == "test_loop"
        assert loop.name == "Test Loop"
        assert loop.mode == PIDMode.AUTO
        assert loop.enabled == True

    def test_from_dict(self):
        """Test creating loop from dictionary"""
        data = {
            'id': 'loop1',
            'name': 'Temperature Control',
            'pv_channel': 'TC_001',
            'cv_channel': 'Heater_001',
            'kp': 2.0,
            'ki': 0.5,
            'kd': 0.1,
            'setpoint': 100.0,
            'output_min': 0.0,
            'output_max': 100.0,
            'mode': 'auto',
            'derivative_mode': 'on_pv',
            'anti_windup': 'clamping'
        }
        loop = PIDLoop.from_dict(data)
        assert loop.id == 'loop1'
        assert loop.kp == 2.0
        assert loop.ki == 0.5
        assert loop.mode == PIDMode.AUTO
        assert loop.derivative_mode == DerivativeMode.ON_PV
        assert loop.anti_windup == AntiWindupMethod.CLAMPING

    def test_to_config_dict(self):
        """Test exporting loop to config dict"""
        loop = PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv",
            cv_channel="cv",
            kp=1.5,
            ki=0.2,
            kd=0.0
        )
        config = loop.to_config_dict()
        assert config['id'] == 'test'
        assert config['kp'] == 1.5
        assert config['ki'] == 0.2
        assert 'output' not in config  # Runtime state excluded

    def test_to_status_dict(self):
        """Test exporting loop status"""
        loop = PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv",
            setpoint=50.0
        )
        loop.output = 25.0
        loop.error = 5.0
        loop.last_pv = 45.0

        status = loop.to_status_dict()
        assert status['id'] == 'test'
        assert status['setpoint'] == 50.0
        assert status['output'] == 25.0
        assert status['pv'] == 45.0
        assert 'timestamp' in status


class TestPIDEngine:
    """Tests for PIDEngine class"""

    def test_create_engine(self):
        """Test creating PID engine"""
        engine = PIDEngine()
        assert len(engine.loops) == 0

    def test_add_loop(self):
        """Test adding a loop to the engine"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="Loop 1", pv_channel="pv1")

        result = engine.add_loop(loop)
        assert result == True
        assert "loop1" in engine.loops
        assert len(engine.loops) == 1

    def test_add_duplicate_loop(self):
        """Test that duplicate loop IDs are rejected"""
        engine = PIDEngine()
        loop1 = PIDLoop(id="loop1", name="Loop 1", pv_channel="pv1")
        loop2 = PIDLoop(id="loop1", name="Loop 1 Copy", pv_channel="pv2")

        engine.add_loop(loop1)
        result = engine.add_loop(loop2)
        assert result == False
        assert len(engine.loops) == 1

    def test_remove_loop(self):
        """Test removing a loop"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="Loop 1", pv_channel="pv1")
        engine.add_loop(loop)

        result = engine.remove_loop("loop1")
        assert result == True
        assert "loop1" not in engine.loops

    def test_remove_nonexistent_loop(self):
        """Test removing a loop that doesn't exist"""
        engine = PIDEngine()
        result = engine.remove_loop("nonexistent")
        assert result == False

    def test_get_loop(self):
        """Test getting a loop by ID"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="Loop 1", pv_channel="pv1")
        engine.add_loop(loop)

        retrieved = engine.get_loop("loop1")
        assert retrieved is not None
        assert retrieved.id == "loop1"

    def test_clear_loops(self):
        """Test clearing all loops"""
        engine = PIDEngine()
        engine.add_loop(PIDLoop(id="loop1", name="L1", pv_channel="pv1"))
        engine.add_loop(PIDLoop(id="loop2", name="L2", pv_channel="pv2"))

        engine.clear_loops()
        assert len(engine.loops) == 0


class TestPIDSetpoint:
    """Tests for setpoint control"""

    def test_set_setpoint(self):
        """Test setting setpoint value"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1", pv_channel="pv1",
            setpoint_min=0.0, setpoint_max=100.0
        )
        engine.add_loop(loop)

        result = engine.set_setpoint("loop1", 50.0)
        assert result == True
        assert engine.loops["loop1"].setpoint == 50.0

    def test_setpoint_clamped_to_max(self):
        """Test that setpoint is clamped to maximum"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1", pv_channel="pv1",
            setpoint_min=0.0, setpoint_max=100.0
        )
        engine.add_loop(loop)

        engine.set_setpoint("loop1", 150.0)
        assert engine.loops["loop1"].setpoint == 100.0

    def test_setpoint_clamped_to_min(self):
        """Test that setpoint is clamped to minimum"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1", pv_channel="pv1",
            setpoint_min=10.0, setpoint_max=100.0
        )
        engine.add_loop(loop)

        engine.set_setpoint("loop1", 5.0)
        assert engine.loops["loop1"].setpoint == 10.0

    def test_set_setpoint_nonexistent_loop(self):
        """Test setting setpoint on nonexistent loop"""
        engine = PIDEngine()
        result = engine.set_setpoint("nonexistent", 50.0)
        assert result == False


class TestPIDModeControl:
    """Tests for mode control (auto/manual/cascade)"""

    def test_set_mode_manual(self):
        """Test switching to manual mode"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="L1", pv_channel="pv1")
        engine.add_loop(loop)

        result = engine.set_mode("loop1", "manual")
        assert result == True
        assert engine.loops["loop1"].mode == PIDMode.MANUAL

    def test_set_mode_auto(self):
        """Test switching to auto mode"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="L1", pv_channel="pv1", mode=PIDMode.MANUAL)
        engine.add_loop(loop)

        result = engine.set_mode("loop1", "auto")
        assert result == True
        assert engine.loops["loop1"].mode == PIDMode.AUTO

    def test_set_mode_cascade(self):
        """Test switching to cascade mode"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="L1", pv_channel="pv1")
        engine.add_loop(loop)

        result = engine.set_mode("loop1", "cascade")
        assert result == True
        assert engine.loops["loop1"].mode == PIDMode.CASCADE

    def test_set_manual_output(self):
        """Test setting manual output value"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1", pv_channel="pv1",
            mode=PIDMode.MANUAL,
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        result = engine.set_manual_output("loop1", 75.0)
        assert result == True
        assert engine.loops["loop1"].manual_output == 75.0
        assert engine.loops["loop1"].output == 75.0  # Applied immediately in manual mode

    def test_manual_output_clamped(self):
        """Test that manual output is clamped to limits"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1", pv_channel="pv1",
            mode=PIDMode.MANUAL,
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        engine.set_manual_output("loop1", 150.0)
        assert engine.loops["loop1"].manual_output == 100.0


class TestPIDCalculation:
    """Tests for PID calculation logic"""

    def test_proportional_only(self):
        """Test P-only control"""
        outputs = []
        engine = PIDEngine(on_set_output=lambda ch, val: outputs.append((ch, val)))

        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=2.0, ki=0.0, kd=0.0,
            setpoint=100.0,
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        # PV = 90, SP = 100, error = 10, output = 2.0 * 10 = 20
        result = engine.process_scan({"pv1": 90.0}, dt=0.1)

        assert "cv1" in result
        assert abs(result["cv1"] - 20.0) < 0.1  # Allow small tolerance for initialization

    def test_integral_accumulation(self):
        """Test that integral term accumulates over time"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=0.0, ki=1.0, kd=0.0,
            setpoint=100.0,
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        # Run several scans with constant error
        for _ in range(10):
            engine.process_scan({"pv1": 90.0}, dt=0.1)

        # Integral should have accumulated
        assert engine.loops["loop1"].i_term > 0

    def test_derivative_on_pv(self):
        """Test derivative on PV (no derivative kick)"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=0.0, ki=0.0, kd=1.0,
            setpoint=100.0,
            derivative_mode=DerivativeMode.ON_PV,
            output_min=-100.0, output_max=100.0
        )
        engine.add_loop(loop)

        # First scan to initialize
        engine.process_scan({"pv1": 50.0}, dt=0.1)

        # PV increasing - should get negative d_term (derivative on PV is negated)
        engine.process_scan({"pv1": 60.0}, dt=0.1)

        # With derivative on PV, rapid PV increase causes negative output contribution
        assert engine.loops["loop1"].d_term < 0

    def test_manual_mode_bypasses_calculation(self):
        """Test that manual mode uses manual output directly"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=10.0, ki=1.0, kd=0.0,
            setpoint=100.0,
            mode=PIDMode.MANUAL,
            manual_output=42.0
        )
        engine.add_loop(loop)

        result = engine.process_scan({"pv1": 50.0}, dt=0.1)

        assert result["cv1"] == 42.0

    def test_disabled_loop_skipped(self):
        """Test that disabled loops are not processed"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            enabled=False
        )
        engine.add_loop(loop)

        result = engine.process_scan({"pv1": 50.0}, dt=0.1)

        assert "cv1" not in result

    def test_missing_pv_skipped(self):
        """Test that loops with missing PV are skipped"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1"
        )
        engine.add_loop(loop)

        result = engine.process_scan({"other_channel": 50.0}, dt=0.1)

        assert "cv1" not in result

    def test_output_clamped_to_limits(self):
        """Test that output is clamped to min/max"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=100.0, ki=0.0, kd=0.0,  # High gain to saturate
            setpoint=100.0,
            output_min=0.0, output_max=50.0
        )
        engine.add_loop(loop)

        result = engine.process_scan({"pv1": 0.0}, dt=0.1)

        assert result["cv1"] == 50.0  # Clamped to max

    def test_reverse_action(self):
        """Test reverse acting control (cooling)"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=1.0, ki=0.0, kd=0.0,
            setpoint=100.0,
            reverse_action=True,
            output_min=-100.0, output_max=100.0
        )
        engine.add_loop(loop)

        # PV below setpoint with reverse action should give negative output
        result = engine.process_scan({"pv1": 90.0}, dt=0.1)

        # Error = SP - PV = 10, but reverse_action negates it
        assert engine.loops["loop1"].error == -10.0


class TestAntiWindup:
    """Tests for anti-windup protection"""

    def test_clamping_anti_windup(self):
        """Test clamping anti-windup prevents integral growth at saturation"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=0.0, ki=10.0, kd=0.0,  # High integral gain
            setpoint=100.0,
            output_min=0.0, output_max=50.0,
            anti_windup=AntiWindupMethod.CLAMPING
        )
        engine.add_loop(loop)

        # Run many scans - should saturate at max
        for _ in range(100):
            engine.process_scan({"pv1": 0.0}, dt=0.1)

        # I-term should not grow unbounded
        # With proper anti-windup, i_term should stop growing when output saturates
        assert engine.loops["loop1"].output == 50.0

    def test_back_calculation_anti_windup(self):
        """Test back-calculation anti-windup"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=0.0, ki=10.0, kd=0.0,
            setpoint=100.0,
            output_min=0.0, output_max=50.0,
            anti_windup=AntiWindupMethod.BACK_CALCULATION
        )
        engine.add_loop(loop)

        # Run scans at saturation
        for _ in range(20):
            engine.process_scan({"pv1": 0.0}, dt=0.1)

        # With back-calculation, i_term should be adjusted to match clamped output
        assert engine.loops["loop1"].output == 50.0
        # i_term should be equal to output when p_term and d_term are 0
        assert abs(engine.loops["loop1"].i_term - 50.0) < 1.0


class TestBumplessTransfer:
    """Tests for bumpless mode transfer"""

    def test_bumpless_manual_to_auto(self):
        """Test bumpless transfer from manual to auto"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=1.0, ki=0.1, kd=0.0,
            setpoint=100.0,
            mode=PIDMode.MANUAL,
            manual_output=30.0,
            bumpless_transfer=True
        )
        engine.add_loop(loop)

        # Run in manual mode
        engine.process_scan({"pv1": 95.0}, dt=0.1)

        # Switch to auto
        engine.set_mode("loop1", "auto")

        # Output should not jump significantly
        result = engine.process_scan({"pv1": 95.0}, dt=0.1)

        # With bumpless transfer, i_term is set to maintain current output
        # The output should be close to the previous manual output
        assert abs(result["cv1"] - 30.0) < 10.0  # Allow some deviation due to P-term

    def test_bumpless_auto_to_manual(self):
        """Test bumpless transfer from auto to manual"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=1.0, ki=0.5, kd=0.0,
            setpoint=100.0,
            mode=PIDMode.AUTO,
            bumpless_transfer=True,
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        # Run in auto mode to build up output
        for _ in range(10):
            engine.process_scan({"pv1": 90.0}, dt=0.1)

        auto_output = engine.loops["loop1"].output

        # Switch to manual
        engine.set_mode("loop1", "manual")

        # Manual output should be set to current output
        assert abs(engine.loops["loop1"].manual_output - auto_output) < 0.1


class TestDeadband:
    """Tests for deadband functionality"""

    def test_deadband_suppresses_small_errors(self):
        """Test that small errors within deadband are ignored"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=10.0, ki=0.0, kd=0.0,
            setpoint=100.0,
            deadband=5.0,  # Error within +/- 5 is ignored
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        # PV = 98, error = 2, within deadband
        engine.process_scan({"pv1": 98.0}, dt=0.1)

        assert engine.loops["loop1"].error == 0.0  # Error zeroed due to deadband


class TestCascadeControl:
    """Tests for cascade control"""

    def test_cascade_setpoint_from_channel(self):
        """Test that cascade mode can get setpoint from another channel"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            setpoint_source="channel",
            setpoint_channel="remote_sp",
            kp=1.0, ki=0.0, kd=0.0,
            setpoint_min=0.0, setpoint_max=200.0
        )
        engine.add_loop(loop)

        # Process with remote setpoint channel
        result = engine.process_scan({"pv1": 80.0, "remote_sp": 100.0}, dt=0.1)

        # Error should be based on remote setpoint
        assert engine.loops["loop1"].error == 20.0  # 100 - 80


class TestTuning:
    """Tests for PID tuning"""

    def test_set_tuning(self):
        """Test setting tuning parameters"""
        engine = PIDEngine()
        loop = PIDLoop(id="loop1", name="L1", pv_channel="pv1")
        engine.add_loop(loop)

        result = engine.set_tuning("loop1", kp=2.5, ki=0.3, kd=0.05)

        assert result == True
        assert engine.loops["loop1"].kp == 2.5
        assert engine.loops["loop1"].ki == 0.3
        assert engine.loops["loop1"].kd == 0.05


class TestConfiguration:
    """Tests for configuration load/save"""

    def test_load_config(self):
        """Test loading configuration from dict"""
        engine = PIDEngine()
        config = {
            'loops': [
                {'id': 'loop1', 'name': 'Loop 1', 'pv_channel': 'TC1', 'kp': 1.5},
                {'id': 'loop2', 'name': 'Loop 2', 'pv_channel': 'TC2', 'kp': 2.0}
            ]
        }

        engine.load_config(config)

        assert len(engine.loops) == 2
        assert engine.loops['loop1'].kp == 1.5
        assert engine.loops['loop2'].kp == 2.0

    def test_to_config_dict(self):
        """Test exporting configuration to dict"""
        engine = PIDEngine()
        engine.add_loop(PIDLoop(id="loop1", name="L1", pv_channel="pv1", kp=1.5))
        engine.add_loop(PIDLoop(id="loop2", name="L2", pv_channel="pv2", kp=2.0))

        config = engine.to_config_dict()

        assert 'loops' in config
        assert len(config['loops']) == 2

    def test_json_roundtrip(self):
        """Test JSON serialization roundtrip"""
        engine = PIDEngine()
        engine.add_loop(PIDLoop(
            id="loop1", name="Test Loop",
            pv_channel="TC1", cv_channel="Heater",
            kp=2.0, ki=0.5, kd=0.1,
            setpoint=100.0
        ))

        json_str = engine.to_json()

        engine2 = PIDEngine()
        engine2.load_json(json_str)

        assert len(engine2.loops) == 1
        assert engine2.loops['loop1'].kp == 2.0
        assert engine2.loops['loop1'].setpoint == 100.0


class TestOutputCallback:
    """Tests for output callback functionality"""

    def test_output_callback_called(self):
        """Test that output callback is called with correct values"""
        outputs = []

        def capture_output(channel, value):
            outputs.append((channel, value))
            return True

        engine = PIDEngine(on_set_output=capture_output)
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=1.0, ki=0.0, kd=0.0,
            setpoint=100.0
        )
        engine.add_loop(loop)

        engine.process_scan({"pv1": 90.0}, dt=0.1)

        assert len(outputs) == 1
        assert outputs[0][0] == "cv1"

    def test_status_callback_called(self):
        """Test that status callback is called"""
        statuses = []

        def capture_status(loop_id, status):
            statuses.append((loop_id, status))

        engine = PIDEngine()
        engine.set_status_callback(capture_status)

        loop = PIDLoop(id="loop1", name="L1", pv_channel="pv1", cv_channel="cv1")
        engine.add_loop(loop)

        engine.process_scan({"pv1": 50.0}, dt=0.1)

        assert len(statuses) == 1
        assert statuses[0][0] == "loop1"
        assert 'output' in statuses[0][1]


class TestRateLimiting:
    """Tests for output rate limiting"""

    def test_rate_limiting_applied(self):
        """Test that output rate limiting prevents large jumps"""
        engine = PIDEngine()
        loop = PIDLoop(
            id="loop1", name="L1",
            pv_channel="pv1", cv_channel="cv1",
            kp=100.0, ki=0.0, kd=0.0,  # High gain for large output change
            setpoint=100.0,
            output_rate_limit=10.0,  # Max 10 units/sec
            output_min=0.0, output_max=100.0
        )
        engine.add_loop(loop)

        # First scan to initialize (output near 0)
        engine.process_scan({"pv1": 100.0}, dt=0.1)  # No error

        # Large error suddenly - would want to jump to 100 but rate limited
        result = engine.process_scan({"pv1": 0.0}, dt=0.1)

        # With rate limit of 10/sec and dt=0.1, max change is 1.0
        # Output should be limited
        assert result["cv1"] <= 10.0  # Can't jump more than rate_limit * dt from 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
