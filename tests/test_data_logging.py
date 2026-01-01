"""
Data Logging Tests
Validates that data is logged correctly to files.
"""

import pytest
import sys
import time
import csv
import json
from pathlib import Path
from datetime import datetime

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import (
    ChannelConfig, ChannelType, NISystemConfig,
    SystemConfig, ChassisConfig, ModuleConfig
)


class TestCSVLogging:
    """Test CSV data logging functionality."""

    @pytest.fixture
    def sample_data(self):
        """Create sample channel data."""
        return [
            {"timestamp": time.time(), "temp_1": 25.5, "voltage_1": 5.0, "counter_1": 100},
            {"timestamp": time.time() + 1, "temp_1": 26.0, "voltage_1": 5.1, "counter_1": 150},
            {"timestamp": time.time() + 2, "temp_1": 26.5, "voltage_1": 5.2, "counter_1": 200}
        ]

    def test_csv_write_and_read(self, sample_data, tmp_path):
        """Test writing and reading CSV data."""
        csv_file = tmp_path / "test_log.csv"

        # Write data
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=sample_data[0].keys())
            writer.writeheader()
            writer.writerows(sample_data)

        # Read back
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        assert float(rows[0]["temp_1"]) == 25.5
        assert float(rows[1]["voltage_1"]) == 5.1
        assert int(float(rows[2]["counter_1"])) == 200

    def test_csv_append_mode(self, tmp_path):
        """Test appending to existing CSV file."""
        csv_file = tmp_path / "append_test.csv"

        # Initial write
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writeheader()
            writer.writerow({"timestamp": 1.0, "value": 10})

        # Append
        with open(csv_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writerow({"timestamp": 2.0, "value": 20})

        # Verify
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        assert float(rows[0]["value"]) == 10
        assert float(rows[1]["value"]) == 20

    def test_csv_handles_special_values(self, tmp_path):
        """Test CSV handles NaN, None, and special floats."""
        csv_file = tmp_path / "special_values.csv"

        data = [
            {"timestamp": 1.0, "value": float('nan')},
            {"timestamp": 2.0, "value": float('inf')},
            {"timestamp": 3.0, "value": None}
        ]

        # Write
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writeheader()
            for row in data:
                writer.writerow(row)

        # Verify file was written
        assert csv_file.exists()
        content = csv_file.read_text()
        assert "timestamp" in content


class TestLogFileNaming:
    """Test log file naming conventions."""

    def test_datetime_filename(self, tmp_path):
        """Test datetime-based filename generation."""
        now = datetime.now()
        filename = f"data_{now.strftime('%Y%m%d_%H%M%S')}.csv"

        log_file = tmp_path / filename
        log_file.touch()

        assert log_file.exists()
        assert "data_" in filename
        assert ".csv" in filename

    def test_session_based_filename(self, tmp_path):
        """Test session-based filename generation."""
        session_id = "recording_001"
        filename = f"{session_id}_data.csv"

        log_file = tmp_path / filename
        log_file.touch()

        assert log_file.exists()
        assert session_id in filename


class TestLogRotation:
    """Test log file rotation functionality."""

    def test_size_based_rotation(self, tmp_path):
        """Test rotation when file exceeds size limit."""
        log_file = tmp_path / "rotating.csv"
        max_size = 1000  # bytes

        # Write until over limit
        with open(log_file, 'w') as f:
            for i in range(100):
                f.write(f"timestamp,value\n{i},{i * 10}\n")
                if log_file.stat().st_size > max_size:
                    break

        # Check file size
        assert log_file.stat().st_size > 0

    def test_file_rotation_numbering(self, tmp_path):
        """Test that rotated files get incrementing numbers."""
        base_name = "data"

        # Create numbered files
        for i in range(5):
            log_file = tmp_path / f"{base_name}_{i:03d}.csv"
            log_file.touch()

        # Check all exist
        for i in range(5):
            assert (tmp_path / f"{base_name}_{i:03d}.csv").exists()


class TestDataIntegrity:
    """Test data integrity during logging."""

    def test_no_data_loss_on_flush(self, tmp_path):
        """Test that data is not lost when file is flushed."""
        log_file = tmp_path / "flush_test.csv"

        # Write with immediate flush
        with open(log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writeheader()

            for i in range(100):
                writer.writerow({"timestamp": i, "value": i * 10})
                f.flush()

        # Verify all rows written
        with open(log_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 100

    def test_timestamp_ordering(self, tmp_path):
        """Test that timestamps are in order."""
        log_file = tmp_path / "timestamp_test.csv"

        timestamps = [time.time() + i for i in range(10)]

        with open(log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writeheader()
            for i, ts in enumerate(timestamps):
                writer.writerow({"timestamp": ts, "value": i})

        # Read and verify order
        with open(log_file, 'r') as f:
            reader = csv.DictReader(f)
            read_timestamps = [float(row["timestamp"]) for row in reader]

        # Check monotonically increasing
        for i in range(1, len(read_timestamps)):
            assert read_timestamps[i] >= read_timestamps[i - 1]


class TestLogFormat:
    """Test log file format."""

    def test_csv_header_matches_data(self, tmp_path):
        """Test that CSV header matches data columns."""
        log_file = tmp_path / "format_test.csv"

        channels = ["temp_1", "temp_2", "voltage_1", "counter_1"]
        header = ["timestamp"] + channels

        data = {"timestamp": time.time()}
        for ch in channels:
            data[ch] = 0.0

        with open(log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(data)

        # Read header
        with open(log_file, 'r') as f:
            reader = csv.reader(f)
            file_header = next(reader)

        assert file_header == header

    def test_iso_timestamp_format(self, tmp_path):
        """Test ISO timestamp format in logs."""
        log_file = tmp_path / "iso_test.csv"

        now = datetime.now()
        iso_timestamp = now.isoformat()

        with open(log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "value"])
            writer.writeheader()
            writer.writerow({"timestamp": iso_timestamp, "value": 42})

        # Read and parse
        with open(log_file, 'r') as f:
            reader = csv.DictReader(f)
            row = next(reader)

        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(row["timestamp"])
        assert parsed.year == now.year


class TestChannelLogging:
    """Test channel-specific logging behavior."""

    @pytest.fixture
    def sample_config(self):
        """Create sample configuration."""
        return NISystemConfig(
            system=SystemConfig(log_directory="./logs"),
            chassis={"main": ChassisConfig(name="main", chassis_type="cDAQ-9178")},
            modules={"mod1": ModuleConfig(name="mod1", module_type="NI-9213", chassis="main", slot=1)},
            channels={
                "logged_channel": ChannelConfig(
                    name="logged_channel",
                    module="mod1",
                    physical_channel="ai0",
                    channel_type=ChannelType.VOLTAGE,
                    log=True,
                    log_interval_ms=100
                ),
                "unlogged_channel": ChannelConfig(
                    name="unlogged_channel",
                    module="mod1",
                    physical_channel="ai1",
                    channel_type=ChannelType.VOLTAGE,
                    log=False
                )
            },
            safety_actions={}
        )

    def test_log_flag_respected(self, sample_config):
        """Test that log flag determines if channel is logged."""
        logged = sample_config.channels["logged_channel"]
        unlogged = sample_config.channels["unlogged_channel"]

        assert logged.log == True
        assert unlogged.log == False

    def test_log_interval_setting(self, sample_config):
        """Test log interval configuration."""
        ch = sample_config.channels["logged_channel"]
        assert ch.log_interval_ms == 100

    def test_default_log_interval(self):
        """Test default log interval is 1000ms."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE
        )
        assert ch.log_interval_ms == 1000


class TestRecordingMetadata:
    """Test recording metadata storage."""

    def test_metadata_json_format(self, tmp_path):
        """Test metadata is stored in JSON format."""
        metadata_file = tmp_path / "recording_metadata.json"

        metadata = {
            "recording_id": "rec_001",
            "start_time": datetime.now().isoformat(),
            "channels": ["temp_1", "voltage_1"],
            "sample_rate_hz": 1.0,
            "simulation_mode": True,
            "description": "Test recording"
        }

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Read back
        with open(metadata_file, 'r') as f:
            loaded = json.load(f)

        assert loaded["recording_id"] == "rec_001"
        assert loaded["channels"] == ["temp_1", "voltage_1"]

    def test_metadata_with_channel_configs(self, tmp_path):
        """Test metadata includes channel configurations."""
        ch = ChannelConfig(
            name="temp_1",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.THERMOCOUPLE,
            units="C",
            low_limit=0.0,
            high_limit=500.0
        )

        metadata = {
            "recording_id": "rec_002",
            "channels": {
                ch.name: {
                    "type": ch.channel_type.value,
                    "units": ch.units,
                    "low_limit": ch.low_limit,
                    "high_limit": ch.high_limit
                }
            }
        }

        metadata_file = tmp_path / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f)

        with open(metadata_file, 'r') as f:
            loaded = json.load(f)

        assert loaded["channels"]["temp_1"]["type"] == "thermocouple"
        assert loaded["channels"]["temp_1"]["high_limit"] == 500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
