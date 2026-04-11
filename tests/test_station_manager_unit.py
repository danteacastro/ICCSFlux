"""
Unit tests for StationManager (Option B — multi-process station mode).

Tests the shared StationManager module without requiring MQTT broker,
hardware, or running services. Uses mocking for MQTT and subprocess.

Covers:
- StationProcess wrapper (alive, terminate)
- StationManager construction and dependency injection
- Station creation (_handle_create): config generation, process spawn, limits
- Station stop (_handle_stop): process termination, cleanup
- Channel conflict detection
- State persistence (save/restore)
- Health check and auto-restart
- Registry publishing
- MAX_STATIONS enforcement
"""

import json
import sys
import tempfile
import shutil
import time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from station_manager import StationManager, StationProcess


# =============================================================================
# HELPERS
# =============================================================================

def make_project_file(tmp_dir, filename, channels=None):
    """Create a minimal project JSON file and return its path."""
    ch_data = {}
    if channels:
        for name, phys in channels.items():
            ch_data[name] = {
                "name": name,
                "physical_channel": phys,
                "channel_type": "voltage_input",
                "unit": "V",
            }
    data = {
        "type": "nisystem-project",
        "version": "2.0",
        "name": filename.replace(".json", ""),
        "channels": ch_data,
    }
    projects_dir = Path(tmp_dir) / "config" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    path = projects_dir / filename
    path.write_text(json.dumps(data, indent=2))
    return path


def make_manager(tmp_dir, **kwargs):
    """Create a StationManager with test defaults."""
    root = Path(tmp_dir)
    (root / "config" / "projects").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)

    defaults = {
        "root": root,
        "daq_command_fn": lambda config_path: ["python", "daq_service.py", "-c", config_path],
        "credential_fn": lambda: ("testuser", "testpass"),
        "log_fn": lambda tag, msg, level="info": None,  # Silent
        "creation_flags": 0,
        "process_tracker": [],
    }
    defaults.update(kwargs)
    mgr = StationManager(**defaults)
    mgr._mqtt = MagicMock()  # Mock MQTT client so publish works
    return mgr


# =============================================================================
# STATION PROCESS TESTS
# =============================================================================

class TestStationProcess:
    """Test the StationProcess wrapper."""

    def test_alive_when_running(self):
        proc = MagicMock()
        proc.poll.return_value = None  # Still running
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        assert sp.alive is True

    def test_not_alive_when_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0  # Exited
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        assert sp.alive is False

    def test_not_alive_when_no_proc(self):
        sp = StationProcess(None, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        assert sp.alive is False

    def test_pid_property(self):
        proc = MagicMock()
        proc.pid = 12345
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        assert sp.pid == 12345

    def test_pid_none_without_proc(self):
        sp = StationProcess(None, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        assert sp.pid is None

    def test_terminate_calls_terminate(self):
        proc = MagicMock()
        proc.poll.return_value = None
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        sp.terminate()
        proc.terminate.assert_called_once()

    def test_terminate_kills_on_timeout(self):
        import subprocess
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        sp.terminate()
        proc.kill.assert_called_once()

    def test_terminate_with_no_proc(self):
        sp = StationProcess(None, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        sp.terminate()  # Should not raise

    def test_start_time_set(self):
        proc = MagicMock()
        before = time.time()
        sp = StationProcess(proc, "station-001", "Station 1", "test.json", "/tmp/test.ini")
        after = time.time()
        assert before <= sp.start_time <= after


# =============================================================================
# STATION MANAGER CONSTRUCTION TESTS
# =============================================================================

class TestStationManagerConstruction:
    """Test StationManager dependency injection."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_basic_construction(self):
        mgr = make_manager(self.tmp_dir)
        assert mgr.stations == {}
        assert mgr._running is False
        assert mgr.MAX_STATIONS == 3

    def test_custom_daq_command_fn(self):
        cmd_fn = lambda path: ["custom_exe", "-c", path]
        mgr = make_manager(self.tmp_dir, daq_command_fn=cmd_fn)
        assert mgr._daq_command_fn("test.ini") == ["custom_exe", "-c", "test.ini"]

    def test_custom_credential_fn(self):
        cred_fn = lambda: ("admin", "secret")
        mgr = make_manager(self.tmp_dir, credential_fn=cred_fn)
        assert mgr._credential_fn() == ("admin", "secret")

    def test_process_tracker_shared(self):
        tracker = []
        mgr = make_manager(self.tmp_dir, process_tracker=tracker)
        assert mgr._process_tracker is tracker

    def test_paths_derived_from_root(self):
        mgr = make_manager(self.tmp_dir)
        assert mgr._stations_dir == Path(self.tmp_dir) / "config" / "stations"
        assert mgr._state_file == Path(self.tmp_dir) / "config" / "station_state.json"
        assert mgr._data_dir == Path(self.tmp_dir) / "data"


# =============================================================================
# STATION CREATION TESTS
# =============================================================================

class TestStationCreation:
    """Test _handle_create logic."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_station_missing_project(self):
        self.mgr._handle_create({"name": "Station 1"})
        self.mgr._mqtt.publish.assert_called()
        # Should get error response
        calls = self.mgr._mqtt.publish.call_args_list
        response_call = [c for c in calls if "response" in str(c)]
        assert len(response_call) > 0

    def test_create_station_nonexistent_project(self):
        self.mgr._handle_create({"project": "nonexistent.json", "name": "Station 1"})
        calls = self.mgr._mqtt.publish.call_args_list
        response_payloads = [json.loads(c[0][1]) for c in calls if "response" in c[0][0]]
        assert any(not p["success"] for p in response_payloads)

    @patch("subprocess.Popen")
    def test_create_station_success(self, mock_popen):
        proc = MagicMock()
        proc.pid = 99999
        proc.poll.return_value = None
        mock_popen.return_value = proc

        make_project_file(self.tmp_dir, "TestProject.json", {"TC_01": "Mod1/ai0"})
        self.mgr._handle_create({
            "project": "TestProject.json",
            "name": "Station 1",
            "node_id": "station-001",
        })

        assert "station-001" in self.mgr.stations
        assert self.mgr.stations["station-001"].node_name == "Station 1"
        assert self.mgr.stations["station-001"].alive is True

    @patch("subprocess.Popen")
    def test_create_generates_config_file(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json", {"TC_01": "Mod1/ai0"})
        self.mgr._handle_create({
            "project": "Test.json",
            "name": "Station 1",
            "node_id": "station-001",
        })

        config_path = self.mgr._stations_dir / "station-001.ini"
        assert config_path.exists()

    @patch("subprocess.Popen")
    def test_create_generates_data_dirs(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({
            "project": "Test.json",
            "node_id": "station-001",
        })

        data_dir = self.mgr._data_dir / "stations" / "station-001"
        assert (data_dir / "logs").exists()
        assert (data_dir / "recordings").exists()

    @patch("subprocess.Popen")
    def test_create_auto_generates_node_id(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "name": "Auto"})

        assert len(self.mgr.stations) == 1
        node_id = list(self.mgr.stations.keys())[0]
        assert node_id.startswith("station-")

    @patch("subprocess.Popen")
    def test_create_duplicate_rejected(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})
        self.mgr._mqtt.reset_mock()

        # Second create with same ID
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})
        response_calls = [c for c in self.mgr._mqtt.publish.call_args_list
                         if "response" in c[0][0]]
        payloads = [json.loads(c[0][1]) for c in response_calls]
        assert any(not p["success"] for p in payloads)

    @patch("subprocess.Popen")
    def test_create_respects_max_stations(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        for i in range(self.mgr.MAX_STATIONS):
            self.mgr._handle_create({
                "project": "Test.json",
                "node_id": f"station-{i:03d}",
            })

        assert len(self.mgr.stations) == self.mgr.MAX_STATIONS
        self.mgr._mqtt.reset_mock()

        # One more should fail
        self.mgr._handle_create({
            "project": "Test.json",
            "node_id": "station-999",
        })
        assert "station-999" not in self.mgr.stations

    @patch("subprocess.Popen")
    def test_create_passes_credentials_to_env(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        call_kwargs = mock_popen.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env", {})
        assert env.get("MQTT_USERNAME") == "testuser"
        assert env.get("MQTT_PASSWORD") == "testpass"

    @patch("subprocess.Popen")
    def test_create_adds_to_process_tracker(self, mock_popen):
        proc = MagicMock(pid=99999, poll=MagicMock(return_value=None))
        mock_popen.return_value = proc

        tracker = []
        mgr = make_manager(self.tmp_dir, process_tracker=tracker)
        make_project_file(self.tmp_dir, "Test.json")
        mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        assert proc in tracker


# =============================================================================
# CHANNEL CONFLICT TESTS
# =============================================================================

class TestChannelConflicts:
    """Test channel overlap detection during station creation."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("subprocess.Popen")
    def test_conflict_blocks_creation(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        # Create first station with channels
        make_project_file(self.tmp_dir, "ProjA.json", {"TC_01": "Mod1/ai0"})
        self.mgr._handle_create({"project": "ProjA.json", "node_id": "station-001"})

        # Simulate channel claim from first station
        self.mgr._claimed_channels["station-001"] = ["Mod1/ai0"]

        # Try to create second station with overlapping channel
        make_project_file(self.tmp_dir, "ProjB.json", {"Temp_01": "Mod1/ai0"})
        self.mgr._mqtt.reset_mock()
        self.mgr._handle_create({"project": "ProjB.json", "node_id": "station-002"})

        # Should be rejected
        assert "station-002" not in self.mgr.stations

    @patch("subprocess.Popen")
    def test_no_conflict_different_channels(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "ProjA.json", {"TC_01": "Mod1/ai0"})
        self.mgr._handle_create({"project": "ProjA.json", "node_id": "station-001"})
        self.mgr._claimed_channels["station-001"] = ["Mod1/ai0"]

        make_project_file(self.tmp_dir, "ProjB.json", {"TC_02": "Mod1/ai1"})
        self.mgr._handle_create({"project": "ProjB.json", "node_id": "station-002"})

        assert "station-002" in self.mgr.stations


# =============================================================================
# STATION STOP TESTS
# =============================================================================

class TestStationStop:
    """Test _handle_stop logic."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_stop_missing_id(self):
        self.mgr._handle_stop({})
        response_calls = [c for c in self.mgr._mqtt.publish.call_args_list
                         if "response" in c[0][0]]
        payloads = [json.loads(c[0][1]) for c in response_calls]
        assert any(not p["success"] for p in payloads)

    def test_stop_nonexistent_station(self):
        self.mgr._handle_stop({"station_id": "station-999"})
        response_calls = [c for c in self.mgr._mqtt.publish.call_args_list
                         if "response" in c[0][0]]
        payloads = [json.loads(c[0][1]) for c in response_calls]
        assert any(not p["success"] for p in payloads)

    @patch("subprocess.Popen")
    def test_stop_terminates_process(self, mock_popen):
        proc = MagicMock(pid=99999, poll=MagicMock(return_value=None))
        mock_popen.return_value = proc

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})
        assert "station-001" in self.mgr.stations

        self.mgr._handle_stop({"station_id": "station-001"})
        assert "station-001" not in self.mgr.stations
        proc.terminate.assert_called()

    @patch("subprocess.Popen")
    def test_stop_clears_claimed_channels(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json", {"TC_01": "Mod1/ai0"})
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})
        self.mgr._claimed_channels["station-001"] = ["Mod1/ai0"]

        self.mgr._handle_stop({"station_id": "station-001"})
        assert "station-001" not in self.mgr._claimed_channels


# =============================================================================
# STATE PERSISTENCE TESTS
# =============================================================================

class TestStatePersistence:
    """Test _save_state and _restore_stations."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("subprocess.Popen")
    def test_save_state_creates_file(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        assert self.mgr._state_file.exists()
        state = json.loads(self.mgr._state_file.read_text())
        assert "station-001" in state

    @patch("subprocess.Popen")
    def test_save_state_includes_project_info(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({
            "project": "Test.json",
            "name": "My Station",
            "node_id": "station-001",
        })

        state = json.loads(self.mgr._state_file.read_text())
        assert state["station-001"]["node_name"] == "My Station"
        assert state["station-001"]["project"] == "Test.json"

    @patch("subprocess.Popen")
    def test_restore_recreates_stations(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        # Create new manager instance and restore
        mgr2 = make_manager(self.tmp_dir)
        mgr2._restore_stations()

        assert "station-001" in mgr2.stations

    def test_restore_with_no_state_file(self):
        self.mgr._restore_stations()  # Should not raise
        assert len(self.mgr.stations) == 0


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestHealthCheck:
    """Test check_stations auto-restart logic."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("subprocess.Popen")
    def test_healthy_station_not_restarted(self, mock_popen):
        proc = MagicMock(pid=99999, poll=MagicMock(return_value=None))
        mock_popen.return_value = proc

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        initial_call_count = mock_popen.call_count
        self.mgr.check_stations()
        assert mock_popen.call_count == initial_call_count  # No new process

    @patch("subprocess.Popen")
    def test_crashed_station_restarted(self, mock_popen):
        proc1 = MagicMock(pid=99999)
        proc1.poll.return_value = None  # Running during create
        proc2 = MagicMock(pid=88888)
        proc2.poll.return_value = None
        mock_popen.side_effect = [proc1, proc2]

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({"project": "Test.json", "node_id": "station-001"})

        # Simulate crash
        proc1.poll.return_value = 1  # Exited with error
        self.mgr.check_stations()

        # New process spawned
        assert mock_popen.call_count == 2
        assert self.mgr.stations["station-001"].proc is proc2


# =============================================================================
# REGISTRY PUBLISHING TESTS
# =============================================================================

class TestRegistryPublishing:
    """Test _publish_registry output."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_empty_registry(self):
        self.mgr._publish_registry()
        call = self.mgr._mqtt.publish.call_args
        payload = json.loads(call[0][1])
        assert payload["stations"] == {}

    @patch("subprocess.Popen")
    def test_registry_includes_station_info(self, mock_popen):
        proc = MagicMock(pid=99999, poll=MagicMock(return_value=None))
        mock_popen.return_value = proc

        make_project_file(self.tmp_dir, "Test.json")
        self.mgr._handle_create({
            "project": "Test.json",
            "name": "Station 1",
            "node_id": "station-001",
        })

        # Find the registry publish call
        registry_calls = [c for c in self.mgr._mqtt.publish.call_args_list
                         if "registry" in c[0][0]]
        assert len(registry_calls) > 0

        payload = json.loads(registry_calls[-1][0][1])
        station = payload["stations"]["station-001"]
        assert station["nodeId"] == "station-001"
        assert station["nodeName"] == "Station 1"
        assert station["status"] == "running"

    @patch("subprocess.Popen")
    def test_registry_retained(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99999, poll=MagicMock(return_value=None))

        self.mgr._publish_registry()
        call = self.mgr._mqtt.publish.call_args
        assert call[1].get("retain") is True or (len(call[0]) > 2 and call[0][2] is True)

    def test_registry_not_published_without_mqtt(self):
        self.mgr._mqtt = None
        self.mgr._publish_registry()  # Should not raise


# =============================================================================
# MQTT MESSAGE ROUTING TESTS
# =============================================================================

class TestMessageRouting:
    """Test _on_message dispatching."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = make_manager(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_topic_dispatches(self):
        msg = MagicMock()
        msg.topic = "nisystem/station/create"
        msg.payload = json.dumps({"project": "test.json"}).encode()

        with patch.object(self.mgr, '_handle_create') as mock_create:
            self.mgr._on_message(None, None, msg)
            mock_create.assert_called_once()

    def test_stop_topic_dispatches(self):
        msg = MagicMock()
        msg.topic = "nisystem/station/stop"
        msg.payload = json.dumps({"station_id": "station-001"}).encode()

        with patch.object(self.mgr, '_handle_stop') as mock_stop:
            self.mgr._on_message(None, None, msg)
            mock_stop.assert_called_once()

    def test_list_topic_publishes_registry(self):
        msg = MagicMock()
        msg.topic = "nisystem/station/list"
        msg.payload = b'{}'

        with patch.object(self.mgr, '_publish_registry') as mock_pub:
            self.mgr._on_message(None, None, msg)
            mock_pub.assert_called_once()

    def test_channel_claimed_topic_updates_cache(self):
        msg = MagicMock()
        msg.topic = "nisystem/nodes/station-001/channels/claimed"
        msg.payload = json.dumps({"channels": ["Mod1/ai0", "Mod1/ai1"]}).encode()

        self.mgr._on_message(None, None, msg)
        assert self.mgr._claimed_channels["station-001"] == ["Mod1/ai0", "Mod1/ai1"]

    def test_channel_claimed_empty_clears_cache(self):
        self.mgr._claimed_channels["station-001"] = ["Mod1/ai0"]

        msg = MagicMock()
        msg.topic = "nisystem/nodes/station-001/channels/claimed"
        msg.payload = b''

        self.mgr._on_message(None, None, msg)
        assert "station-001" not in self.mgr._claimed_channels

    def test_malformed_payload_does_not_crash(self):
        msg = MagicMock()
        msg.topic = "nisystem/station/create"
        msg.payload = b'not json{'

        self.mgr._on_message(None, None, msg)  # Should not raise
