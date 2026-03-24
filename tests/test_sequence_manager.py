"""
Unit tests for Sequence Manager

Tests sequence execution, step types, pause/resume, abort,
loops, and condition handling. No hardware or MQTT required.
"""

import pytest
import time
import threading
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add services and tests to path
services_dir = Path(__file__).parent.parent / "services" / "daq_service"
sys.path.insert(0, str(services_dir))
sys.path.insert(0, str(Path(__file__).parent))

from test_helpers import wait_until

from sequence_manager import (
    SequenceManager, Sequence, SequenceStep, SequenceState, StepType
)

class TestSequenceStep:
    """Tests for SequenceStep dataclass"""

    def test_create_set_output_step(self):
        """Test creating a setOutput step"""
        step = SequenceStep(
            type=StepType.SET_OUTPUT.value,
            channel="valve1",
            value=1.0
        )
        assert step.type == "setOutput"
        assert step.channel == "valve1"
        assert step.value == 1.0

    def test_create_wait_duration_step(self):
        """Test creating a waitDuration step"""
        step = SequenceStep(
            type=StepType.WAIT_DURATION.value,
            duration_ms=5000
        )
        assert step.type == "waitDuration"
        assert step.duration_ms == 5000

    def test_create_wait_condition_step(self):
        """Test creating a waitCondition step"""
        step = SequenceStep(
            type=StepType.WAIT_CONDITION.value,
            condition_channel="temperature",
            condition_operator=">=",
            condition_value=100.0,
            condition_timeout_ms=30000
        )
        assert step.condition_channel == "temperature"
        assert step.condition_operator == ">="

    def test_from_dict(self):
        """Test creating step from dictionary"""
        data = {
            'type': 'setOutput',
            'channel': 'pump',
            'value': 1,
            'label': 'Turn on pump'
        }
        step = SequenceStep.from_dict(data)
        assert step.type == 'setOutput'
        assert step.channel == 'pump'
        assert step.label == 'Turn on pump'

    def test_to_dict(self):
        """Test exporting step to dictionary"""
        step = SequenceStep(
            type=StepType.SET_OUTPUT.value,
            channel="valve1",
            value=1.0,
            label="Open valve"
        )
        data = step.to_dict()
        assert data['type'] == 'setOutput'
        assert data['channel'] == 'valve1'
        assert 'duration_ms' not in data  # None values excluded

class TestSequence:
    """Tests for Sequence dataclass"""

    def test_create_sequence(self):
        """Test creating a sequence"""
        seq = Sequence(
            id="test_seq",
            name="Test Sequence",
            description="A test sequence",
            steps=[
                SequenceStep(type=StepType.SET_OUTPUT.value, channel="v1", value=1),
                SequenceStep(type=StepType.WAIT_DURATION.value, duration_ms=1000),
            ]
        )
        assert seq.id == "test_seq"
        assert len(seq.steps) == 2
        assert seq.state == SequenceState.IDLE

    def test_from_dict(self):
        """Test creating sequence from dictionary"""
        data = {
            'id': 'seq1',
            'name': 'Startup Sequence',
            'description': 'System startup procedure',
            'enabled': True,
            'steps': [
                {'type': 'setOutput', 'channel': 'pump', 'value': 1},
                {'type': 'waitDuration', 'duration_ms': 2000}
            ]
        }
        seq = Sequence.from_dict(data)
        assert seq.id == 'seq1'
        assert seq.name == 'Startup Sequence'
        assert len(seq.steps) == 2

    def test_to_dict(self):
        """Test exporting sequence to dictionary"""
        seq = Sequence(
            id="test",
            name="Test",
            steps=[SequenceStep(type="setOutput", channel="v1", value=1)]
        )
        data = seq.to_dict()
        assert data['id'] == 'test'
        assert len(data['steps']) == 1

class TestSequenceManager:
    """Tests for SequenceManager class"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a sequence manager with temp file"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        return manager

    def test_create_manager(self, manager):
        """Test creating sequence manager"""
        assert len(manager.sequences) == 0

    def test_add_sequence(self, manager):
        """Test adding a sequence"""
        seq = Sequence(id="seq1", name="Test", steps=[])
        result = manager.add_sequence(seq)
        assert result == True
        assert "seq1" in manager.sequences

    def test_remove_sequence(self, manager):
        """Test removing a sequence"""
        seq = Sequence(id="seq1", name="Test", steps=[])
        manager.add_sequence(seq)

        result = manager.remove_sequence("seq1")
        assert result == True
        assert "seq1" not in manager.sequences

    def test_remove_nonexistent_sequence(self, manager):
        """Test removing nonexistent sequence"""
        result = manager.remove_sequence("nonexistent")
        assert result == False

    def test_get_sequence(self, manager):
        """Test getting a sequence by ID"""
        seq = Sequence(id="seq1", name="Test", steps=[])
        manager.add_sequence(seq)

        retrieved = manager.get_sequence("seq1")
        assert retrieved is not None
        assert retrieved.id == "seq1"

    def test_get_all_sequences(self, manager):
        """Test getting all sequences"""
        manager.add_sequence(Sequence(id="seq1", name="S1", steps=[]))
        manager.add_sequence(Sequence(id="seq2", name="S2", steps=[]))

        all_seqs = manager.get_all_sequences()
        assert len(all_seqs) == 2

class TestSequenceExecution:
    """Tests for sequence execution"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a sequence manager with mocked callbacks"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))

        # Mock callbacks
        manager.outputs_set = []
        manager.on_set_output = lambda ch, val: manager.outputs_set.append((ch, val))
        manager.channel_values = {}
        manager.on_get_channel_value = lambda ch: manager.channel_values.get(ch)
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))

        return manager

    def test_start_sequence(self, manager):
        """Test starting a sequence"""
        seq = Sequence(
            id="test",
            name="Test",
            steps=[SequenceStep(type="setOutput", channel="v1", value=1)]
        )
        manager.add_sequence(seq)

        result = manager.start_sequence("test")
        assert result == True

        assert wait_until(lambda: ("started", "test") in manager.events,
                          timeout=3.0), "Sequence did not start"

    def test_start_disabled_sequence(self, manager):
        """Test that disabled sequences cannot be started"""
        seq = Sequence(id="test", name="Test", enabled=False, steps=[])
        manager.add_sequence(seq)

        result = manager.start_sequence("test")
        assert result == False

    def test_cannot_start_second_sequence(self, manager):
        """Test that only one sequence can run at a time"""
        seq1 = Sequence(
            id="seq1", name="S1",
            steps=[SequenceStep(type="waitDuration", duration_ms=1000)]
        )
        seq2 = Sequence(id="seq2", name="S2", steps=[])

        manager.add_sequence(seq1)
        manager.add_sequence(seq2)

        manager.start_sequence("seq1")
        assert wait_until(
            lambda: manager.sequences["seq1"].state == SequenceState.RUNNING,
            timeout=3.0), "seq1 did not start"

        result = manager.start_sequence("seq2")
        assert result == False

        manager.abort_sequence("seq1")

    def test_set_output_step_execution(self, manager):
        """Test that setOutput steps execute correctly"""
        seq = Sequence(
            id="test", name="Test",
            steps=[
                SequenceStep(type="setOutput", channel="valve1", value=1),
                SequenceStep(type="setOutput", channel="pump", value=1)
            ]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")

        assert wait_until(
            lambda: ("valve1", 1) in manager.outputs_set and ("pump", 1) in manager.outputs_set,
            timeout=3.0), "setOutput steps did not execute"

    def test_sequence_completion(self, manager):
        """Test sequence completion"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="setOutput", channel="v1", value=1)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")

        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=3.0), "Sequence did not complete"
        assert manager.sequences["test"].state == SequenceState.COMPLETED

class TestSequencePauseResume:
    """Tests for pause/resume functionality"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager with long-running sequence"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_pause_sequence(self, manager):
        """Test pausing a running sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=5000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        result = manager.pause_sequence("test")
        assert result == True
        assert manager.sequences["test"].state == SequenceState.PAUSED

        manager.abort_sequence("test")

    def test_resume_sequence(self, manager):
        """Test resuming a paused sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=500)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        manager.pause_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.PAUSED,
            timeout=3.0), "Sequence did not pause"

        result = manager.resume_sequence("test")
        assert result == True
        assert manager.sequences["test"].state == SequenceState.RUNNING

        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=5.0), "Sequence did not complete after resume"

    def test_cannot_pause_non_running_sequence(self, manager):
        """Test that non-running sequences cannot be paused"""
        seq = Sequence(id="test", name="Test", steps=[])
        manager.add_sequence(seq)

        result = manager.pause_sequence("test")
        assert result == False

class TestSequenceAbort:
    """Tests for sequence abort functionality"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_abort_running_sequence(self, manager):
        """Test aborting a running sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=5000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        result = manager.abort_sequence("test")
        assert result == True

        assert wait_until(
            lambda: ("aborted", "test") in manager.events,
            timeout=3.0), "Sequence did not abort"
        assert manager.sequences["test"].state == SequenceState.ABORTED

    def test_abort_paused_sequence(self, manager):
        """Test aborting a paused sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=5000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        manager.pause_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.PAUSED,
            timeout=3.0), "Sequence did not pause"

        result = manager.abort_sequence("test")
        assert result == True

    def test_cannot_remove_running_sequence(self, manager):
        """Test that running sequences cannot be removed"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=2000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        result = manager.remove_sequence("test")
        assert result == False

        manager.abort_sequence("test")

class TestWaitDuration:
    """Tests for wait duration steps"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_wait_duration_timing(self, manager):
        """Test that wait duration is approximately correct"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=300)]
        )
        manager.add_sequence(seq)

        start = time.time()
        manager.start_sequence("test")

        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=5.0), "Sequence did not complete"

        elapsed = time.time() - start
        assert elapsed >= 0.3  # Should have waited at least 300ms

class TestWaitCondition:
    """Tests for wait condition steps"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager with channel value callback"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.channel_values = {}
        manager.on_get_channel_value = lambda ch: manager.channel_values.get(ch)
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_wait_condition_met_immediately(self, manager):
        """Test condition that is already met"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(
                type="waitCondition",
                condition_channel="temp",
                condition_operator=">=",
                condition_value=100,
                condition_timeout_ms=5000
            )]
        )
        manager.add_sequence(seq)

        # Set channel value before starting
        manager.channel_values["temp"] = 150

        manager.start_sequence("test")

        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=3.0), "Sequence did not complete"

    def test_wait_condition_met_during_wait(self, manager):
        """Test condition that becomes true during wait"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(
                type="waitCondition",
                condition_channel="temp",
                condition_operator=">=",
                condition_value=100,
                condition_timeout_ms=5000
            )]
        )
        manager.add_sequence(seq)
        manager.channel_values["temp"] = 50  # Not met initially

        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        # Now set value to meet condition
        manager.channel_values["temp"] = 150

        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=5.0), "Sequence did not complete after condition met"

    def test_wait_condition_timeout(self, manager):
        """Test condition timeout"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(
                type="waitCondition",
                condition_channel="temp",
                condition_operator=">=",
                condition_value=100,
                condition_timeout_ms=300  # Short timeout
            )]
        )
        manager.add_sequence(seq)
        manager.channel_values["temp"] = 50  # Never met

        manager.start_sequence("test")

        # Should complete (with timeout) rather than hang
        assert wait_until(
            lambda: ("completed", "test") in manager.events,
            timeout=5.0), "Sequence did not complete on timeout"

    def test_condition_operators(self, manager):
        """Test different condition operators"""
        operators_and_values = [
            ("==", 100, 100, True),
            ("==", 100, 99, False),
            ("!=", 100, 99, True),
            ("<", 100, 50, True),
            (">", 100, 150, True),
            ("<=", 100, 100, True),
            (">=", 100, 100, True),
        ]

        for op, target, actual, should_pass in operators_and_values:
            # Test the internal condition evaluation
            step = SequenceStep(
                type="waitCondition",
                condition_channel="ch",
                condition_operator=op,
                condition_value=target
            )
            manager.channel_values["ch"] = actual

            result = manager._evaluate_condition(step)
            assert result == should_pass, f"Failed for {op} with target={target}, actual={actual}"

class TestLoops:
    """Tests for loop functionality"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.outputs_set = []
        manager.on_set_output = lambda ch, val: manager.outputs_set.append((ch, val))
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_loop_executes_multiple_times(self, manager):
        """Test that loops execute the correct number of times"""
        seq = Sequence(
            id="test", name="Test",
            steps=[
                SequenceStep(type="loopStart", loop_id="main"),
                SequenceStep(type="setOutput", channel="counter", value=1),
                SequenceStep(type="loopEnd", loop_id="main", loop_count=3),
            ]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")

        # Should have executed setOutput 3 times
        assert wait_until(
            lambda: len([o for o in manager.outputs_set if o[0] == "counter"]) == 3,
            timeout=3.0), "Loop did not execute 3 times"

class TestStatus:
    """Tests for status reporting"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager"""
        seq_file = tmp_path / "sequences.json"
        return SequenceManager(sequences_file=str(seq_file))

    def test_get_status(self, manager):
        """Test getting manager status"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=1000)]
        )
        manager.add_sequence(seq)

        status = manager.get_status()
        assert status["sequence_count"] == 1
        assert status["running_sequence_id"] is None

    def test_status_while_running(self, manager):
        """Test status while sequence is running"""
        seq = Sequence(
            id="test", name="Test Sequence",
            steps=[SequenceStep(type="waitDuration", duration_ms=2000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        status = manager.get_status()
        assert status["running_sequence_id"] == "test"
        assert status["running_sequence_name"] == "Test Sequence"
        assert status["running_sequence_state"] == "running"

        manager.abort_sequence("test")

    def test_get_running_sequence(self, manager):
        """Test getting the running sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=2000)]
        )
        manager.add_sequence(seq)

        # No running sequence initially
        assert manager.get_running_sequence() is None

        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.get_running_sequence() is not None,
            timeout=3.0), "No running sequence found"

        running = manager.get_running_sequence()
        assert running.id == "test"

        manager.abort_sequence("test")

class TestShutdown:
    """Tests for shutdown behavior"""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager"""
        seq_file = tmp_path / "sequences.json"
        manager = SequenceManager(sequences_file=str(seq_file))
        manager.events = []
        manager.on_sequence_event = lambda evt, seq: manager.events.append((evt, seq.id))
        return manager

    def test_shutdown_aborts_running_sequence(self, manager):
        """Test that shutdown aborts any running sequence"""
        seq = Sequence(
            id="test", name="Test",
            steps=[SequenceStep(type="waitDuration", duration_ms=5000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")
        assert wait_until(
            lambda: manager.sequences["test"].state == SequenceState.RUNNING,
            timeout=3.0), "Sequence did not start running"

        manager.shutdown()

        assert wait_until(
            lambda: ("aborted", "test") in manager.events,
            timeout=3.0), "Sequence was not aborted on shutdown"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
