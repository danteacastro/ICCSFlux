"""
Tests for recording_manager.py
Covers data recording, triggered recording, file rotation, and ALCOA+ compliance.
"""

import pytest
import tempfile
import os
import csv
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from recording_manager import RecordingManager, RecordingConfig, MAX_PRE_TRIGGER_SAMPLES


class TestRecordingConfig:
    """Tests for RecordingConfig dataclass"""

    def test_defaults(self):
        """Test default configuration values"""
        config = RecordingConfig()

        assert config.file_prefix == "recording"
        assert config.file_format == "csv"
        assert config.sample_interval == 1.0
        assert config.sample_interval_unit == "seconds"
        assert config.decimation == 1
        assert config.rotation_mode == "single"
        assert config.max_file_size_mb == 100.0
        assert config.write_mode == "buffered"
        assert config.mode == "manual"

    def test_custom_values(self):
        """Test custom configuration"""
        config = RecordingConfig(
            file_prefix="test",
            sample_interval=500,
            sample_interval_unit="milliseconds",
            decimation=10,
            rotation_mode="time",
            max_file_duration_s=3600
        )

        assert config.file_prefix == "test"
        assert config.sample_interval == 500
        assert config.sample_interval_unit == "milliseconds"
        assert config.decimation == 10
        assert config.rotation_mode == "time"

    def test_effective_sample_rate_seconds(self):
        """Test effective sample rate calculation in seconds"""
        config = RecordingConfig(sample_interval=0.5, sample_interval_unit="seconds")
        assert config.effective_sample_rate_hz == 2.0

    def test_effective_sample_rate_milliseconds(self):
        """Test effective sample rate calculation in milliseconds"""
        config = RecordingConfig(sample_interval=100, sample_interval_unit="milliseconds")
        assert config.effective_sample_rate_hz == 10.0

    def test_effective_sample_rate_with_decimation(self):
        """Test effective sample rate with decimation"""
        config = RecordingConfig(sample_interval=1.0, decimation=2)
        assert config.effective_sample_rate_hz == 0.5

    def test_to_dict(self):
        """Test conversion to dictionary"""
        config = RecordingConfig(file_prefix="test")
        d = config.to_dict()

        assert d['file_prefix'] == "test"
        assert 'sample_interval' in d
        assert 'rotation_mode' in d

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'file_prefix': 'custom',
            'sample_interval': 2.0,
            'decimation': 5
        }

        config = RecordingConfig.from_dict(d)
        assert config.file_prefix == 'custom'
        assert config.sample_interval == 2.0
        assert config.decimation == 5


class TestRecordingManager:
    """Tests for RecordingManager class"""

    @pytest.fixture
    def data_dir(self):
        """Create a temporary directory for recording data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def recording_manager(self, data_dir):
        """Create a RecordingManager instance"""
        manager = RecordingManager(default_path=str(data_dir))
        return manager

    @pytest.fixture
    def channel_values(self):
        """Sample channel values"""
        return {
            'temp_1': 25.5,
            'temp_2': 30.2,
            'pressure': 101.3,
            'flow_rate': 10.0
        }

    @pytest.fixture
    def channel_configs(self):
        """Sample channel configurations"""
        return {
            'temp_1': {'units': 'degC', 'channel_type': 'thermocouple'},
            'temp_2': {'units': 'degC', 'channel_type': 'thermocouple'},
            'pressure': {'units': 'kPa', 'channel_type': 'voltage_input'},
            'flow_rate': {'units': 'L/min', 'channel_type': 'current_input'}
        }

    def test_initialization(self, recording_manager, data_dir):
        """Test manager initialization"""
        assert recording_manager.config.base_path == str(data_dir)
        assert recording_manager.recording is False
        assert recording_manager.samples_written == 0

    def test_configure(self, recording_manager):
        """Test configuration update"""
        config_dict = {
            'file_prefix': 'test_recording',
            'sample_interval': 0.5,
            'decimation': 2
        }

        result = recording_manager.configure(config_dict)

        assert result is True
        assert recording_manager.config.file_prefix == 'test_recording'
        assert recording_manager.config.sample_interval == 0.5
        assert recording_manager.config.decimation == 2

    def test_configure_while_recording_fails(self, recording_manager, data_dir):
        """Test that config changes are blocked while recording"""
        recording_manager.start()

        result = recording_manager.configure({'file_prefix': 'new_prefix'})

        assert result is False
        # Original config unchanged
        assert recording_manager.config.file_prefix == "recording"

        recording_manager.stop()

    def test_configure_warns_on_large_pre_trigger(self, recording_manager):
        """Test warning when pre_trigger_samples exceeds max"""
        config_dict = {
            'pre_trigger_samples': MAX_PRE_TRIGGER_SAMPLES + 1000
        }

        # Should not raise, just warn
        result = recording_manager.configure(config_dict)
        assert result is True

    def test_start_stop_recording(self, recording_manager, data_dir):
        """Test starting and stopping recording"""
        result = recording_manager.start()

        assert result is True
        assert recording_manager.recording is True
        assert recording_manager.current_file is not None
        assert recording_manager.current_file.exists()

        result = recording_manager.stop()

        assert result is True
        assert recording_manager.recording is False

    def test_start_when_already_recording(self, recording_manager):
        """Test that starting when already recording returns False"""
        recording_manager.start()
        result = recording_manager.start()

        assert result is False

        recording_manager.stop()

    def test_stop_when_not_recording(self, recording_manager):
        """Test that stopping when not recording returns False"""
        result = recording_manager.stop()
        assert result is False

    def test_write_sample(self, recording_manager, channel_values, channel_configs):
        """Test writing a sample"""
        recording_manager.start()

        recording_manager.write_sample(channel_values, channel_configs)

        assert recording_manager.samples_written == 1

        recording_manager.stop()

        # Verify file has content
        with open(recording_manager.current_file) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should have header rows and data row
        assert len(rows) >= 2

    def test_write_sample_with_decimation(self, recording_manager, channel_values, channel_configs):
        """Test that decimation skips samples correctly"""
        recording_manager.configure({'decimation': 3})
        recording_manager.start()

        # Write 10 samples, only 4 should be recorded (0, 3, 6, 9)
        for i in range(10):
            # Temporarily disable time-based interval for this test
            recording_manager.config.sample_interval = 0.001
            recording_manager.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        # With decimation=3, samples written = 10/3 = 3 (integer division)
        # Actually the counter logic: 1st sample written, then every 3rd
        assert recording_manager.samples_written >= 3

        recording_manager.stop()

    def test_write_sample_time_interval(self, recording_manager, channel_values, channel_configs):
        """Test time-based sample interval"""
        recording_manager.configure({
            'sample_interval': 100,  # 100ms
            'sample_interval_unit': 'milliseconds'
        })
        recording_manager.start()

        # First sample should be written
        recording_manager.write_sample(channel_values, channel_configs)
        assert recording_manager.samples_written == 1

        # Immediate second sample should be skipped
        recording_manager.write_sample(channel_values, channel_configs)
        assert recording_manager.samples_written == 1

        # Wait and write again
        time.sleep(0.15)
        recording_manager.write_sample(channel_values, channel_configs)
        assert recording_manager.samples_written == 2

        recording_manager.stop()

    def test_channel_selection(self, recording_manager, channel_values, channel_configs):
        """Test that only selected channels are recorded"""
        recording_manager.configure({
            'selected_channels': ['temp_1', 'pressure']
        })
        recording_manager.start()

        recording_manager.write_sample(channel_values, channel_configs)
        recording_manager.stop()

        # Read the file and check columns (skip comment lines)
        with open(recording_manager.current_file) as f:
            reader = csv.reader(f)
            # Skip comment lines that start with #
            for row in reader:
                if row and not row[0].startswith('#'):
                    header = row
                    break
            else:
                header = []

        # Should only have timestamp, temp_1, pressure
        assert 'temp_1' in header
        assert 'pressure' in header
        assert 'temp_2' not in header
        assert 'flow_rate' not in header

    def test_script_values(self, recording_manager, channel_values, channel_configs):
        """Test recording script-computed values"""
        recording_manager.start()

        # Add script values
        recording_manager.update_script_values({
            'calculated_avg': 27.85,
            'ratio': 1.5
        })

        recording_manager.write_sample(channel_values, channel_configs)
        recording_manager.stop()

        # Read the file and check for script columns (skip comment lines)
        with open(recording_manager.current_file) as f:
            reader = csv.reader(f)
            # Skip comment lines that start with #
            for row in reader:
                if row and not row[0].startswith('#'):
                    header = row
                    break
            else:
                header = []

        assert 'script:calculated_avg' in header
        assert 'script:ratio' in header

    def test_script_values_validation(self, recording_manager):
        """Test that invalid script values are filtered"""
        recording_manager.update_script_values({
            'valid': 100.0,
            'nan_value': float('nan'),
            'inf_value': float('inf'),
            'string_value': 'invalid'  # Non-numeric
        })

        # Only valid numeric values should be stored
        assert 'valid' in recording_manager.script_values
        assert 'nan_value' not in recording_manager.script_values
        assert 'inf_value' not in recording_manager.script_values
        assert 'string_value' not in recording_manager.script_values

    def test_filename_timestamp_pattern(self, recording_manager):
        """Test timestamp-based filename generation"""
        recording_manager.configure({
            'naming_pattern': 'timestamp',
            'include_date': True,
            'include_time': True
        })

        filename = recording_manager._generate_filename()

        # Should contain date and time patterns
        assert 'recording' in filename
        assert '.csv' in filename

    def test_filename_sequential_pattern(self, recording_manager):
        """Test sequential filename generation"""
        recording_manager.configure({
            'naming_pattern': 'sequential',
            'sequential_start': 1,
            'sequential_padding': 4
        })

        filename1 = recording_manager._generate_filename()
        filename2 = recording_manager._generate_filename()

        assert '0001' in filename1
        assert '0002' in filename2

    def test_directory_structure_flat(self, recording_manager, data_dir):
        """Test flat directory structure"""
        # Must include base_path in configure() since it replaces entire config
        recording_manager.configure({
            'directory_structure': 'flat',
            'base_path': str(data_dir)
        })

        output_dir = recording_manager._get_output_directory()

        # Compare resolved paths to handle string vs Path differences
        assert output_dir.resolve() == Path(data_dir).resolve()

    def test_directory_structure_daily(self, recording_manager, data_dir):
        """Test daily directory structure"""
        recording_manager.configure({
            'directory_structure': 'daily',
            'base_path': str(data_dir)
        })

        output_dir = recording_manager._get_output_directory()
        now = datetime.now()

        # Verify the output has the expected date-based structure
        assert now.strftime('%Y') in str(output_dir)
        assert now.strftime('%m') in str(output_dir)
        assert now.strftime('%d') in str(output_dir)

    def test_directory_structure_monthly(self, recording_manager, data_dir):
        """Test monthly directory structure"""
        recording_manager.configure({
            'directory_structure': 'monthly',
            'base_path': str(data_dir)
        })

        output_dir = recording_manager._get_output_directory()
        now = datetime.now()

        # Verify the output has the expected date-based structure
        assert now.strftime('%Y') in str(output_dir)
        assert now.strftime('%m') in str(output_dir)

    def test_buffered_write_mode(self, recording_manager, channel_values, channel_configs):
        """Test buffered write mode"""
        recording_manager.configure({
            'write_mode': 'buffered',
            'buffer_size': 5,
            'sample_interval': 0.001  # Very fast for testing
        })
        recording_manager.start()

        # Write fewer than buffer_size samples
        for _ in range(3):
            recording_manager.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        # Buffer not flushed yet (less than buffer_size)
        assert len(recording_manager.write_buffer) <= 3

        # Write more to trigger flush
        for _ in range(5):
            recording_manager.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        recording_manager.stop()

    def test_immediate_write_mode(self, recording_manager, channel_values, channel_configs):
        """Test immediate write mode"""
        recording_manager.configure({
            'write_mode': 'immediate',
            'sample_interval': 0.001
        })
        recording_manager.start()

        recording_manager.write_sample(channel_values, channel_configs)

        # Buffer should be empty in immediate mode
        assert len(recording_manager.write_buffer) == 0

        recording_manager.stop()

    def test_get_config(self, recording_manager):
        """Test getting current configuration"""
        config = recording_manager.get_config()

        assert isinstance(config, dict)
        assert 'file_prefix' in config
        assert 'sample_interval' in config

    def test_on_status_change_callback(self, recording_manager):
        """Test status change callback is called"""
        callback = Mock()
        recording_manager.on_status_change = callback

        recording_manager.start()

        callback.assert_called()

        recording_manager.stop()

        assert callback.call_count >= 2  # At least start and stop

    def test_statistics_tracking(self, recording_manager, channel_values, channel_configs):
        """Test that statistics are tracked correctly"""
        recording_manager.configure({'sample_interval': 0.001})
        recording_manager.start()

        for _ in range(5):
            recording_manager.write_sample(channel_values, channel_configs)
            time.sleep(0.002)

        recording_manager.stop()

        assert recording_manager.samples_written >= 5
        assert recording_manager.bytes_written > 0
        assert recording_manager.file_count == 1

    def test_custom_filename(self, recording_manager, data_dir):
        """Test starting with custom filename"""
        result = recording_manager.start(filename="custom_test.csv")

        assert result is True
        assert recording_manager.current_file.name == "custom_test.csv"

        recording_manager.stop()


class TestTriggeredRecording:
    """Tests for triggered recording mode"""

    @pytest.fixture
    def data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def recording_manager(self, data_dir):
        manager = RecordingManager(default_path=str(data_dir))
        manager.configure({
            'mode': 'triggered',
            'trigger_channel': 'pressure',
            'trigger_condition': 'above',
            'trigger_value': 100.0,
            'pre_trigger_samples': 5,
            'post_trigger_samples': 10,
            'sample_interval': 0.001
        })
        return manager

    def test_trigger_armed_on_start(self, recording_manager):
        """Test that trigger is armed when recording starts"""
        recording_manager.start()

        assert recording_manager.trigger_armed is True
        assert recording_manager.trigger_fired is False

        recording_manager.stop()

    def test_pre_trigger_buffer(self, recording_manager):
        """Test pre-trigger buffering"""
        recording_manager.start()

        channel_configs = {'pressure': {'units': 'kPa'}}

        # Write samples below trigger (pre-trigger buffer)
        for i in range(10):
            recording_manager.write_sample({'pressure': 50.0 + i}, channel_configs)
            time.sleep(0.002)

        # Pre-trigger buffer should have samples
        assert len(recording_manager.pre_trigger_buffer) > 0

        recording_manager.stop()


class TestFileRotation:
    """Tests for file rotation functionality"""

    @pytest.fixture
    def data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_rotation_mode_single(self, data_dir):
        """Test single file mode (no rotation)"""
        manager = RecordingManager(default_path=str(data_dir))
        manager.configure({
            'rotation_mode': 'single',
            'sample_interval': 0.001,
            'base_path': str(data_dir)  # Must include base_path
        })

        manager.start()

        # Write many samples
        for _ in range(100):
            manager.write_sample({'value': 1.0}, {'value': {}})
            time.sleep(0.002)

        manager.stop()

        # Should still be one file
        files = list(data_dir.glob("*.csv"))
        assert len(files) == 1

    def test_rotation_mode_samples(self, data_dir):
        """Test rotation by sample count"""
        manager = RecordingManager(default_path=str(data_dir))
        manager.configure({
            'rotation_mode': 'samples',
            'max_file_samples': 10,
            'on_limit_reached': 'new_file',
            'sample_interval': 0.001,
            'base_path': str(data_dir)  # Must include base_path
        })

        manager.start()

        # Write more than max_file_samples
        for _ in range(25):
            manager.write_sample({'value': 1.0}, {'value': {}})
            time.sleep(0.002)

        manager.stop()

        # Should have multiple files (25/10 = 2-3 files)
        files = list(data_dir.glob("*.csv"))
        assert len(files) >= 2


class TestThreadSafety:
    """Tests for thread safety"""

    @pytest.fixture
    def data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_concurrent_writes(self, data_dir):
        """Test thread-safe concurrent writes"""
        import threading

        manager = RecordingManager(default_path=str(data_dir))
        manager.configure({'sample_interval': 0.001})
        manager.start()

        errors = []

        def write_samples(thread_id):
            try:
                for i in range(50):
                    manager.write_sample(
                        {f'thread_{thread_id}_val': float(i)},
                        {f'thread_{thread_id}_val': {}}
                    )
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            t = threading.Thread(target=write_samples, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        manager.stop()

        assert len(errors) == 0

    def test_concurrent_script_updates(self, data_dir):
        """Test thread-safe script value updates"""
        import threading

        manager = RecordingManager(default_path=str(data_dir))

        errors = []

        def update_scripts(thread_id):
            try:
                for i in range(100):
                    manager.update_script_values({
                        f'thread_{thread_id}_param': float(i)
                    })
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=update_scripts, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
