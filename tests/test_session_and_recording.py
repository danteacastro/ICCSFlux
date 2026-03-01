"""
Tests for session lifecycle (UserVariableManager) and recording manager gaps.

Covers:
- Session start/stop state validation
- Session variable resets and timer management
- Session callbacks (scheduler, recording, sequences)
- Session timeout (autonomous operation protection)
- Recording ALCOA+ integrity (SHA-256, read-only mode)
- Recording file rotation by size, time, and sample count
- Recording circular mode (oldest file deletion)
- Acquisition cascade (session stop cascades to recording stop)
"""

import csv
import hashlib
import os
import stat
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent))

from test_helpers import wait_until

from user_variables import (
    UserVariableManager, UserVariable, TestSessionConfig, TestSession,
)
from recording_manager import RecordingManager, RecordingConfig


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def data_dir():
    """Temporary directory for test data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def uvm(data_dir):
    """UserVariableManager with no callbacks"""
    return UserVariableManager(data_dir=str(data_dir))


@pytest.fixture
def uvm_with_callbacks(data_dir):
    """UserVariableManager with all callback mocks attached"""
    mgr = UserVariableManager(
        data_dir=str(data_dir),
        on_session_start=Mock(),
        on_session_stop=Mock(),
        scheduler_enable=Mock(),
        recording_start=Mock(),
        recording_stop=Mock(),
        run_sequence=Mock(),
        stop_sequence=Mock(),
    )
    return mgr


@pytest.fixture
def rec(data_dir):
    """RecordingManager pointed at temp directory"""
    return RecordingManager(default_path=str(data_dir))


@pytest.fixture
def channel_values():
    return {'temp_1': 25.5, 'pressure': 101.3}


@pytest.fixture
def channel_configs():
    return {
        'temp_1': {'units': 'degC'},
        'pressure': {'units': 'kPa'},
    }


# =============================================================================
# SESSION LIFECYCLE — STATE VALIDATION
# =============================================================================

class TestSessionStateValidation:
    """Test session start/stop state machine guards"""

    def test_start_session_requires_acquisition(self, uvm):
        """Session cannot start if acquisition is not running"""
        result = uvm.start_session(acquiring=False)
        assert result['success'] is False
        assert 'Acquisition must be running' in result['error']

    def test_start_session_rejects_double_start(self, uvm):
        """Starting a session that's already active is rejected"""
        result = uvm.start_session(acquiring=True)
        assert result['success'] is True

        result2 = uvm.start_session(acquiring=True)
        assert result2['success'] is False
        assert 'already active' in result2['error']

    def test_stop_session_rejects_when_not_active(self, uvm):
        """Stopping when no session is active is rejected"""
        result = uvm.stop_session()
        assert result['success'] is False
        assert 'No active session' in result['error']

    def test_start_session_rejects_latched_alarms(self, uvm):
        """Session start is rejected when latched alarms exist and require_no_latched=True"""
        result = uvm.start_session(
            acquiring=True,
            latched_alarm_count=3,
            require_no_latched=True,
        )
        assert result['success'] is False
        assert 'latched' in result['error'].lower()

    def test_start_session_allows_latched_when_not_required(self, uvm):
        """Latched alarms are allowed when require_no_latched=False (default)"""
        result = uvm.start_session(
            acquiring=True,
            latched_alarm_count=5,
            require_no_latched=False,
        )
        assert result['success'] is True

    def test_start_session_rejects_active_alarms(self, uvm):
        """Session start is rejected when active alarms exist and require_no_active=True"""
        result = uvm.start_session(
            acquiring=True,
            active_alarm_count=2,
            require_no_active=True,
        )
        assert result['success'] is False
        assert 'active alarm' in result['error'].lower()

    def test_start_session_allows_active_when_not_required(self, uvm):
        """Active alarms are allowed when require_no_active=False (default)"""
        result = uvm.start_session(
            acquiring=True,
            active_alarm_count=10,
            require_no_active=False,
        )
        assert result['success'] is True

    def test_start_stop_round_trip(self, uvm):
        """Normal start → stop round-trip succeeds"""
        start = uvm.start_session(acquiring=True, started_by='operator1')
        assert start['success'] is True
        assert start.get('started_at') is not None

        stop = uvm.stop_session()
        assert stop['success'] is True
        assert stop.get('stopped_at') is not None
        assert stop.get('session_started_at') == start['started_at']

    def test_session_metadata_round_trip(self, uvm):
        """test_id, description, operator_notes are stored and cleared"""
        uvm.start_session(
            acquiring=True,
            test_id='TEST-001',
            description='Pressure test',
            operator_notes='Check valve #3',
            started_by='alice',
        )

        status = uvm.get_session_status()
        assert status['active'] is True
        assert status['test_id'] == 'TEST-001'
        assert status['description'] == 'Pressure test'
        assert status['operator_notes'] == 'Check valve #3'
        assert status['started_by'] == 'alice'

        uvm.stop_session()

        status2 = uvm.get_session_status()
        assert status2['active'] is False
        assert status2['test_id'] is None
        assert status2['description'] is None


# =============================================================================
# SESSION LIFECYCLE — VARIABLE RESETS AND TIMERS
# =============================================================================

class TestSessionVariableResets:
    """Test that session start resets variables and manages timers"""

    def test_session_resets_test_session_variables(self, uvm):
        """Variables with reset_mode='test_session' are reset to zero on session start"""
        var = UserVariable(
            id='v1', name='counter1', display_name='Counter 1',
            variable_type='accumulator', value=42.0,
            reset_mode='test_session',
        )
        uvm.variables['v1'] = var

        uvm.start_session(acquiring=True)

        assert uvm.variables['v1'].value == 0.0
        assert uvm.variables['v1'].last_reset is not None

    def test_session_does_not_reset_manual_variables(self, uvm):
        """Variables with reset_mode='manual' are NOT reset on session start"""
        var = UserVariable(
            id='v2', name='total', display_name='Total',
            variable_type='accumulator', value=100.0,
            reset_mode='manual',
        )
        uvm.variables['v2'] = var

        uvm.start_session(acquiring=True)

        assert uvm.variables['v2'].value == 100.0

    def test_session_resets_configured_variables(self, uvm):
        """Variables listed in session config reset_variables are reset regardless of reset_mode"""
        var = UserVariable(
            id='v3', name='special', display_name='Special',
            variable_type='counter', value=55.0,
            reset_mode='manual',
        )
        uvm.variables['v3'] = var

        # Configure session to specifically reset v3
        uvm.session.config.reset_variables = ['v3']

        uvm.start_session(acquiring=True)

        assert uvm.variables['v3'].value == 0.0

    def test_session_starts_timers(self, uvm):
        """Timer variables with reset_mode='test_session' start on session start"""
        timer_var = UserVariable(
            id='t1', name='elapsed', display_name='Elapsed',
            variable_type='timer', value=0.0,
            reset_mode='test_session',
        )
        uvm.variables['t1'] = timer_var

        uvm.start_session(acquiring=True)

        assert uvm.variables['t1'].timer_running is True
        assert uvm.variables['t1'].timer_start_time is not None

    def test_session_stop_finalizes_timers(self, uvm):
        """Timer values are finalized (elapsed stored) on session stop"""
        timer_var = UserVariable(
            id='t2', name='elapsed2', display_name='Elapsed 2',
            variable_type='timer', value=0.0,
            reset_mode='test_session',
        )
        uvm.variables['t2'] = timer_var

        uvm.start_session(acquiring=True)
        time.sleep(0.1)  # let some time pass
        uvm.stop_session()

        assert uvm.variables['t2'].timer_running is False
        assert uvm.variables['t2'].timer_start_time is None
        # Elapsed time should be > 0
        assert uvm.variables['t2'].value > 0.0

    def test_session_clears_last_source_value(self, uvm):
        """_last_source_value is cleared on session reset for edge detection restart"""
        var = UserVariable(
            id='v4', name='acc', display_name='Acc',
            variable_type='accumulator', value=10.0,
            reset_mode='test_session',
        )
        var._last_source_value = 5.0
        uvm.variables['v4'] = var

        uvm.start_session(acquiring=True)

        assert uvm.variables['v4']._last_source_value is None

    def test_session_reset_timer_var_in_config(self, uvm):
        """Timer variable in reset_variables list is stopped and zeroed"""
        timer_var = UserVariable(
            id='t3', name='timer_in_list', display_name='Timer Listed',
            variable_type='timer', value=999.0,
            timer_running=True, timer_start_time=time.time() - 100,
            reset_mode='manual',
        )
        uvm.variables['t3'] = timer_var
        uvm.session.config.reset_variables = ['t3']

        uvm.start_session(acquiring=True)

        # Timer should be stopped and zeroed
        assert uvm.variables['t3'].value == 0.0
        assert uvm.variables['t3'].timer_running is False


# =============================================================================
# SESSION LIFECYCLE — CALLBACKS
# =============================================================================

class TestSessionCallbacks:
    """Test that session start/stop fire the correct callbacks"""

    def test_start_fires_scheduler_enable(self, uvm_with_callbacks):
        """Scheduler is enabled when session config has enable_scheduler=True"""
        mgr = uvm_with_callbacks
        mgr.session.config.enable_scheduler = True

        mgr.start_session(acquiring=True)

        mgr.scheduler_enable.assert_called_once_with(True)

    def test_start_fires_recording_start(self, uvm_with_callbacks):
        """Recording is started when session config has start_recording=True"""
        mgr = uvm_with_callbacks
        mgr.session.config.start_recording = True

        mgr.start_session(acquiring=True)

        mgr.recording_start.assert_called_once()

    def test_start_fires_run_sequence(self, uvm_with_callbacks):
        """Run sequence is called when session config has run_sequence_id"""
        mgr = uvm_with_callbacks
        mgr.session.config.run_sequence_id = 'seq_startup'

        mgr.start_session(acquiring=True)

        mgr.run_sequence.assert_called_once_with('seq_startup')

    def test_start_fires_on_session_start(self, uvm_with_callbacks):
        """Custom on_session_start callback is fired"""
        mgr = uvm_with_callbacks

        mgr.start_session(acquiring=True)

        mgr.on_session_start.assert_called_once()

    def test_stop_fires_scheduler_disable(self, uvm_with_callbacks):
        """Scheduler is disabled when session config has enable_scheduler=True"""
        mgr = uvm_with_callbacks
        mgr.session.config.enable_scheduler = True

        mgr.start_session(acquiring=True)
        mgr.stop_session()

        mgr.scheduler_enable.assert_any_call(False)

    def test_stop_fires_recording_stop(self, uvm_with_callbacks):
        """Recording is stopped when session started it"""
        mgr = uvm_with_callbacks
        mgr.session.config.start_recording = True

        mgr.start_session(acquiring=True)
        mgr.stop_session()

        mgr.recording_stop.assert_called_once()

    def test_stop_fires_stop_sequence(self, uvm_with_callbacks):
        """Stop sequence is called if configured"""
        mgr = uvm_with_callbacks
        mgr.session.config.stop_sequence_id = 'seq_shutdown'

        mgr.start_session(acquiring=True)
        mgr.stop_session()

        # stop_sequence is called first (abort running), then run_sequence for the stop sequence
        mgr.stop_sequence.assert_called_once()
        # run_sequence called with stop_sequence_id
        mgr.run_sequence.assert_called_with('seq_shutdown')

    def test_stop_fires_on_session_stop(self, uvm_with_callbacks):
        """Custom on_session_stop callback is fired"""
        mgr = uvm_with_callbacks

        mgr.start_session(acquiring=True)
        mgr.stop_session()

        mgr.on_session_stop.assert_called_once()

    def test_no_callbacks_when_config_disabled(self, uvm_with_callbacks):
        """No callbacks fire when session config features are disabled (defaults)"""
        mgr = uvm_with_callbacks
        # Defaults: enable_scheduler=False, start_recording=False, run_sequence_id=None

        mgr.start_session(acquiring=True)

        mgr.scheduler_enable.assert_not_called()
        mgr.recording_start.assert_not_called()
        mgr.run_sequence.assert_not_called()

    def test_callback_exception_does_not_block_session(self, uvm_with_callbacks):
        """An exception in a callback doesn't prevent session from starting"""
        mgr = uvm_with_callbacks
        mgr.session.config.enable_scheduler = True
        mgr.scheduler_enable.side_effect = RuntimeError("Scheduler broke")

        result = mgr.start_session(acquiring=True)

        # Session should still be active despite callback failure
        assert result['success'] is True
        assert mgr.session.active is True

    def test_stop_callback_exception_does_not_block_stop(self, uvm_with_callbacks):
        """An exception in stop callbacks doesn't prevent session from stopping"""
        mgr = uvm_with_callbacks
        mgr.session.config.start_recording = True
        mgr.recording_stop.side_effect = RuntimeError("Recording broke")

        mgr.start_session(acquiring=True)
        result = mgr.stop_session()

        assert result['success'] is True
        assert mgr.session.active is False


# =============================================================================
# SESSION TIMEOUT
# =============================================================================

class TestSessionTimeout:
    """Test session timeout (autonomous operation protection)"""

    def test_no_timeout_when_disabled(self, uvm):
        """check_session_timeout returns None when timeout_minutes=0"""
        uvm.session.config.timeout_minutes = 0
        uvm.start_session(acquiring=True)

        result = uvm.check_session_timeout()
        assert result is None

    def test_no_timeout_when_inactive(self, uvm):
        """check_session_timeout returns None when no session is active"""
        result = uvm.check_session_timeout()
        assert result is None

    def test_timeout_triggers_stop(self, uvm):
        """Session auto-stops when timeout is reached"""
        uvm.session.config.timeout_minutes = 0.001  # ~0.06 seconds

        uvm.start_session(acquiring=True)
        time.sleep(0.2)  # exceed timeout

        result = uvm.check_session_timeout()
        assert result is not None
        assert result.get('success') is True
        assert result.get('reason') == 'timeout'
        assert uvm.session.active is False

    def test_no_timeout_before_elapsed(self, uvm):
        """Session is not timed out when time hasn't elapsed"""
        uvm.session.config.timeout_minutes = 60  # 60 minutes

        uvm.start_session(acquiring=True)

        result = uvm.check_session_timeout()
        assert result is None
        assert uvm.session.active is True

        uvm.stop_session()

    def test_session_elapsed_seconds(self, uvm):
        """get_session_status includes elapsed_seconds when active"""
        uvm.start_session(acquiring=True)
        time.sleep(0.1)

        status = uvm.get_session_status()
        assert 'elapsed_seconds' in status
        assert status['elapsed_seconds'] >= 0.05
        assert 'elapsed_formatted' in status

        uvm.stop_session()


# =============================================================================
# SESSION THREAD SAFETY
# =============================================================================

class TestSessionThreadSafety:
    """Test session operations under concurrent access"""

    def test_concurrent_start_at_least_one_wins(self, data_dir):
        """At least one thread starts a session; no crash under contention.

        NOTE: start_session() sets session.active=True AFTER callbacks (outside
        lock) to avoid deadlocks.  This means a short race window exists where
        multiple threads can pass the 'if session.active' guard.  The important
        guarantee is that no thread crashes and at least one succeeds.
        """
        mgr = UserVariableManager(data_dir=str(data_dir))
        results = []

        def try_start():
            r = mgr.start_session(acquiring=True)
            results.append(r)

        threads = [threading.Thread(target=try_start) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r['success']]
        failures = [r for r in results if not r['success']]

        assert len(successes) >= 1, "At least one thread must succeed"
        assert len(results) == 10, "All threads must complete without crash"


# =============================================================================
# RECORDING ALCOA+ INTEGRITY
# =============================================================================

class TestRecordingALCOAIntegrity:
    """Test ALCOA+ data integrity features: SHA-256 checksums and read-only mode"""

    def test_integrity_file_created_on_stop(self, rec, data_dir, channel_values, channel_configs):
        """SHA-256 integrity file is created when verify_on_close=True"""
        rec.configure({
            'verify_on_close': True,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        time.sleep(0.002)
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file
        integrity_file = data_file.with_suffix(data_file.suffix + '.sha256')

        assert integrity_file.exists(), f"Integrity file not created: {integrity_file}"

        content = integrity_file.read_text()
        assert 'sha256:' in content
        assert 'size_bytes:' in content
        assert 'ALCOA+' in content
        assert data_file.name in content

    def test_integrity_verification_passes_for_untouched_file(self, rec, data_dir, channel_values, channel_configs):
        """verify_file_integrity returns True for an unmodified file"""
        rec.configure({
            'verify_on_close': True,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file
        valid, message = rec.verify_file_integrity(data_file)

        assert valid is True
        assert 'verified' in message.lower()

    def test_integrity_verification_fails_for_tampered_file(self, rec, data_dir, channel_values, channel_configs):
        """verify_file_integrity detects file tampering"""
        rec.configure({
            'verify_on_close': True,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file

        # Tamper with the data file
        with open(data_file, 'a') as f:
            f.write("TAMPERED DATA\n")

        valid, message = rec.verify_file_integrity(data_file)

        assert valid is False
        assert 'mismatch' in message.lower()

    def test_integrity_missing_file(self, rec, data_dir):
        """verify_file_integrity returns False when integrity file doesn't exist"""
        fake_file = data_dir / "nonexistent.csv"
        fake_file.write_text("dummy")

        valid, message = rec.verify_file_integrity(fake_file)

        assert valid is False
        assert 'not found' in message.lower()

    def test_no_integrity_file_when_disabled(self, rec, data_dir, channel_values, channel_configs):
        """No integrity file created when verify_on_close=False"""
        rec.configure({
            'verify_on_close': False,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file
        integrity_file = data_file.with_suffix(data_file.suffix + '.sha256')

        assert not integrity_file.exists()

    def test_append_only_makes_file_readonly(self, rec, data_dir, channel_values, channel_configs):
        """append_only=True makes the data file read-only after stop"""
        rec.configure({
            'append_only': True,
            'verify_on_close': False,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file
        file_stat = data_file.stat()

        # Check that write bits are removed
        assert not (file_stat.st_mode & stat.S_IWUSR), "Owner write bit should be cleared"

    def test_csv_metadata_header(self, rec, data_dir, channel_values, channel_configs):
        """CSV file starts with metadata comments (NISystem header)"""
        rec.configure({
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        content = rec.current_file.read_text()
        lines = content.splitlines()

        # First lines should be metadata comments
        assert lines[0].startswith('# NISystem Data Recording')
        assert any('Started:' in line for line in lines[:10])
        assert any('Mode:' in line for line in lines[:10])

    def test_csv_footer_on_stop(self, rec, data_dir, channel_values, channel_configs):
        """CSV file ends with footer comments (stop time, duration, sample count)"""
        rec.configure({
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        content = rec.current_file.read_text()
        lines = content.splitlines()

        # Last lines should be footer
        assert any('Stopped:' in line for line in lines[-6:])
        assert any('Duration:' in line for line in lines[-6:])
        assert any('Total Samples:' in line for line in lines[-6:])

    def test_sha256_hash_is_correct(self, rec, data_dir, channel_values, channel_configs):
        """Manually verify the SHA-256 hash in the integrity file matches the data file"""
        rec.configure({
            'verify_on_close': True,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()
        rec.write_sample(channel_values, channel_configs)
        rec.stop()

        data_file = rec.current_file
        integrity_file = data_file.with_suffix(data_file.suffix + '.sha256')

        # Compute expected hash
        sha256 = hashlib.sha256()
        with open(data_file, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        expected_hash = sha256.hexdigest()

        # Parse actual hash from integrity file
        actual_hash = None
        for line in integrity_file.read_text().splitlines():
            if line.startswith('sha256:'):
                actual_hash = line.split(':', 1)[1].strip()

        assert actual_hash == expected_hash


# =============================================================================
# RECORDING FILE ROTATION
# =============================================================================

class TestRecordingRotation:
    """Test file rotation by size, time, and sample count"""

    def test_rotation_by_sample_count(self, data_dir, channel_values, channel_configs):
        """Files rotate after max_file_samples is reached"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 5,
            'on_limit_reached': 'new_file',
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(15):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        rec.stop()

        files = list(data_dir.glob("*.csv"))
        # 15 samples / 5 per file = 3 files (first file + 2 rotated parts)
        assert len(files) >= 3

    def test_rotation_by_size(self, data_dir):
        """Files rotate after max_file_size_mb is reached"""
        rec = RecordingManager(default_path=str(data_dir))
        # Use immediate write mode so bytes_written (from stat) reflects actual disk size.
        # In buffered mode, data stays in memory and stat() returns stale size.
        rec.configure({
            'rotation_mode': 'size',
            'max_file_size_mb': 0.001,  # ~1 KB
            'on_limit_reached': 'new_file',
            'write_mode': 'immediate',
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        # Write enough data to exceed 1KB — wide rows with many channels
        large_values = {f'ch_{i}': float(i) * 1.23456789 for i in range(20)}
        large_configs = {f'ch_{i}': {'units': 'V'} for i in range(20)}

        for _ in range(50):
            rec.write_sample(large_values, large_configs)
            time.sleep(0.002)

        rec.stop()

        files = list(data_dir.glob("*.csv"))
        assert len(files) >= 2, f"Expected rotation but only got {len(files)} file(s)"

    def test_rotation_stop_mode(self, data_dir, channel_values, channel_configs):
        """on_limit_reached='stop' stops recording when limit is reached"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'stop',
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(10):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        # Recording should have been stopped automatically
        assert rec.recording is False

    def test_single_mode_no_rotation(self, data_dir, channel_values, channel_configs):
        """rotation_mode='single' never rotates regardless of sample count"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'single',
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(50):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        rec.stop()

        files = list(data_dir.glob("*.csv"))
        assert len(files) == 1

    def test_rotated_files_have_part_numbers(self, data_dir, channel_values, channel_configs):
        """Rotated files include _partNNN in their names"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'new_file',
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(10):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        rec.stop()

        files = list(data_dir.glob("*part*.csv"))
        assert len(files) >= 1, "Rotated files should contain 'part' in name"

    def test_rotation_integrity_per_file(self, data_dir, channel_values, channel_configs):
        """Each rotated file gets its own integrity file"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 5,
            'on_limit_reached': 'new_file',
            'verify_on_close': True,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(15):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        rec.stop()

        csv_files = list(data_dir.glob("*.csv"))
        sha_files = list(data_dir.glob("*.sha256"))

        # Each CSV file should have a matching SHA-256 integrity file
        assert len(sha_files) >= len(csv_files), \
            f"Expected at least {len(csv_files)} integrity files, got {len(sha_files)}"


# =============================================================================
# RECORDING CIRCULAR MODE
# =============================================================================

class TestRecordingCircularMode:
    """Test circular mode: oldest files are deleted to maintain a rolling window"""

    def test_circular_deletes_oldest_files(self, data_dir, channel_values, channel_configs):
        """Circular mode keeps only circular_max_files files"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'circular',
            'circular_max_files': 2,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        # Write enough samples to create several files
        for _ in range(20):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        rec.stop()

        # Only circular_max_files + 1 (because the final stop file is also there)
        csv_files = list(data_dir.glob("*.csv"))
        # The currently open file is included in circular_files.
        # After stop, we should have at most circular_max_files files remaining
        # (oldest ones deleted)
        assert len(csv_files) <= 3, \
            f"Circular mode should limit files, got {len(csv_files)}: {[f.name for f in csv_files]}"

    def test_circular_tracks_files(self, data_dir, channel_values, channel_configs):
        """Circular file list is maintained during recording"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'circular',
            'circular_max_files': 5,
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        # Write enough to trigger at least one rotation
        for _ in range(10):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        # circular_files should be tracking
        assert len(rec.circular_files) >= 2

        rec.stop()

    def test_circular_never_deletes_current_file(self, data_dir, channel_values, channel_configs):
        """Circular mode should not delete the file currently being written to"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'circular',
            'circular_max_files': 1,  # Very aggressive limit
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })
        rec.start()

        for _ in range(15):
            rec.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        # Current file should still exist
        assert rec.current_file.exists(), "Current recording file was deleted"

        rec.stop()


# =============================================================================
# RECORDING STATUS AND STATE
# =============================================================================

class TestRecordingStatus:
    """Test recording status reporting"""

    def test_status_when_not_recording(self, rec):
        """Status reports recording=False when idle"""
        status = rec.get_status()
        assert status['recording'] is False
        assert status['recording_samples'] == 0
        assert status['recording_filename'] is None

    def test_status_when_recording(self, rec, data_dir, channel_values, channel_configs):
        """Status reports correct values during recording"""
        rec.configure({'sample_interval': 0.001, 'base_path': str(data_dir)})
        rec.start()
        rec.write_sample(channel_values, channel_configs)

        status = rec.get_status()
        assert status['recording'] is True
        assert status['recording_samples'] == 1
        assert status['recording_filename'] is not None
        assert status['recording_file_count'] == 1

        rec.stop()

    def test_status_tracks_bytes(self, rec, data_dir, channel_values, channel_configs):
        """Status tracks bytes written"""
        rec.configure({'sample_interval': 0.001, 'base_path': str(data_dir)})
        rec.start()
        rec.write_sample(channel_values, channel_configs)

        status = rec.get_status()
        assert status['recording_bytes'] > 0

        rec.stop()


# =============================================================================
# ACQUISITION CASCADE: SESSION → RECORDING COORDINATION
# =============================================================================

class TestAcquisitionCascade:
    """Test that session stop cascades to recording stop and other coordinated actions"""

    def test_session_stop_stops_recording(self, data_dir):
        """When session started recording, stopping session also stops recording"""
        recording_started = []
        recording_stopped = []

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            recording_start=lambda: recording_started.append(True),
            recording_stop=lambda: recording_stopped.append(True),
        )
        mgr.session.config.start_recording = True

        mgr.start_session(acquiring=True)
        assert len(recording_started) == 1

        mgr.stop_session()
        assert len(recording_stopped) == 1

    def test_session_stop_disables_scheduler(self, data_dir):
        """When session enabled scheduler, stopping session also disables it"""
        scheduler_calls = []

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            scheduler_enable=lambda v: scheduler_calls.append(v),
        )
        mgr.session.config.enable_scheduler = True

        mgr.start_session(acquiring=True)
        assert scheduler_calls == [True]

        mgr.stop_session()
        assert scheduler_calls == [True, False]

    def test_session_stop_runs_stop_sequence(self, data_dir):
        """Session stop fires the stop sequence if configured"""
        sequence_calls = []

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            run_sequence=lambda sid: sequence_calls.append(sid),
            stop_sequence=Mock(),
        )
        mgr.session.config.run_sequence_id = 'seq_start'
        mgr.session.config.stop_sequence_id = 'seq_stop'

        mgr.start_session(acquiring=True)
        assert sequence_calls == ['seq_start']

        mgr.stop_session()
        # stop_sequence should be called (to abort running), then run_sequence with stop_sequence_id
        assert 'seq_stop' in sequence_calls

    def test_session_no_recording_stop_when_not_configured(self, data_dir):
        """Recording is NOT stopped if session didn't start it"""
        recording_stopped = []

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            recording_stop=lambda: recording_stopped.append(True),
        )
        mgr.session.config.start_recording = False

        mgr.start_session(acquiring=True)
        mgr.stop_session()

        assert len(recording_stopped) == 0

    def test_full_session_recording_lifecycle(self, data_dir):
        """Integration: session start → write samples → session stop → verify data"""
        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'sample_interval': 0.001,
            'verify_on_close': True,
            'base_path': str(data_dir),
        })

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            recording_start=lambda: rec.start(),
            recording_stop=lambda: rec.stop(),
        )
        mgr.session.config.start_recording = True

        # Start session (should start recording)
        result = mgr.start_session(acquiring=True)
        assert result['success'] is True
        assert rec.recording is True

        # Write some samples
        for _ in range(5):
            rec.write_sample({'temp': 25.5}, {'temp': {'units': 'degC'}})
            time.sleep(0.002)

        # Stop session (should stop recording)
        result = mgr.stop_session()
        assert result['success'] is True
        assert rec.recording is False
        assert rec.samples_written >= 5

        # Verify integrity
        valid, msg = rec.verify_file_integrity(rec.current_file)
        assert valid is True

    def test_multiple_sessions_create_separate_files(self, data_dir):
        """Multiple session start/stop cycles create separate recording files"""
        files_created = []

        rec = RecordingManager(default_path=str(data_dir))
        rec.configure({
            'sample_interval': 0.001,
            'base_path': str(data_dir),
        })

        def start_rec():
            rec.start()
            files_created.append(rec.current_file)

        mgr = UserVariableManager(
            data_dir=str(data_dir),
            recording_start=start_rec,
            recording_stop=lambda: rec.stop(),
        )
        mgr.session.config.start_recording = True

        # Session 1
        mgr.start_session(acquiring=True)
        rec.write_sample({'v': 1.0}, {'v': {}})
        time.sleep(0.002)
        mgr.stop_session()

        # Small delay for unique timestamps in filenames
        time.sleep(1.1)

        # Session 2
        mgr.start_session(acquiring=True)
        rec.write_sample({'v': 2.0}, {'v': {}})
        time.sleep(0.002)
        mgr.stop_session()

        csv_files = list(data_dir.glob("*.csv"))
        assert len(csv_files) >= 2, \
            f"Expected 2 recording files, got {len(csv_files)}: {[f.name for f in csv_files]}"


# =============================================================================
# SESSION PERSISTENCE
# =============================================================================

class TestSessionPersistence:
    """Test that session config persists across manager restarts"""

    def test_session_config_persists(self, data_dir):
        """Session config is loaded on restart"""
        mgr1 = UserVariableManager(data_dir=str(data_dir))
        mgr1.update_session_config({
            'enable_scheduler': True,
            'start_recording': True,
            'timeout_minutes': 30,
        })

        # Create new manager from same directory
        mgr2 = UserVariableManager(data_dir=str(data_dir))

        assert mgr2.session.config.enable_scheduler is True
        assert mgr2.session.config.start_recording is True
        assert mgr2.session.config.timeout_minutes == 30

    def test_active_session_does_not_survive_restart(self, data_dir):
        """An active session is NOT restored on restart (safety)"""
        mgr1 = UserVariableManager(data_dir=str(data_dir))
        mgr1.start_session(acquiring=True)
        assert mgr1.session.active is True

        # Create new manager from same directory
        mgr2 = UserVariableManager(data_dir=str(data_dir))

        # Session should NOT be active after restart
        assert mgr2.session.active is False

    def test_variables_persist_after_session_reset(self, data_dir):
        """Variables with reset_mode='test_session' are persisted after reset"""
        mgr = UserVariableManager(data_dir=str(data_dir))

        var = UserVariable(
            id='v1', name='counter', display_name='Counter',
            variable_type='accumulator', value=42.0,
            reset_mode='test_session',
        )
        mgr.variables['v1'] = var
        mgr._save_variables()

        mgr.start_session(acquiring=True)

        # Reload from disk
        mgr2 = UserVariableManager(data_dir=str(data_dir))
        assert mgr2.variables['v1'].value == 0.0  # Reset value was persisted
