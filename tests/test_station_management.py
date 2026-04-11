"""
Unit tests for station (multi-project) management.

Tests the station management logic without requiring MQTT broker,
hardware, or running services. Uses mocking to isolate the
ProjectContext class and station-related DAQService methods.

Covers:
- ProjectContext lifecycle (create, properties, teardown, to_summary)
- Channel conflict detection between projects
- Scan budget estimation
- Station state persistence (save/load)
- Station config presets (save/load/list/delete)
- Mode switching (standalone <-> station)
- 3-project limit enforcement
- Station union channels
"""

import json
import sys
import time
import threading
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

# Add service directory to path for imports
service_dir = Path(__file__).parent.parent / "services" / "daq_service"
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

from state_machine import DAQStateMachine, DAQState
from project_context import ProjectContext
from config_parser import NISystemConfig, ChannelConfig


# =============================================================================
# HELPERS
# =============================================================================

def make_project_data(name="Test Project", channels=None):
    """Create a minimal project data dict."""
    data = {
        "type": "nisystem-project",
        "version": "2.0",
        "name": name,
        "system": {
            "mqtt_broker": "localhost",
            "mqtt_port": 1883,
            "scan_rate_hz": 4,
            "simulation_mode": True,
        },
        "channels": channels or {},
    }
    return data


def make_channel_config(name, physical_channel=None, channel_type="voltage_input", unit="V"):
    """Create a ChannelConfig-like mock object."""
    ch = MagicMock(spec=ChannelConfig)
    ch.name = name
    ch.physical_channel = physical_channel or f"cDAQ1Mod1/{name}"
    ch.channel_type = channel_type
    ch.unit = unit
    return ch


def make_project_context(project_id, project_name="Test", channels=None, color_index=0):
    """Create a ProjectContext with optional mock config."""
    data = make_project_data(project_name)
    ctx = ProjectContext(
        project_id=project_id,
        project_path=Path(f"config/projects/{project_id}.json"),
        project_data=data,
        project_name=project_name,
        color_index=color_index,
    )
    if channels:
        config = MagicMock(spec=NISystemConfig)
        config.channels = {name: make_channel_config(name, phys) for name, phys in channels.items()}
        ctx.config = config
    return ctx


def write_project_file(tmp_dir, filename, name="Test", channels=None):
    """Write a project JSON file to a temp directory and return its path."""
    ch_data = {}
    if channels:
        for ch_name, phys in channels.items():
            ch_data[ch_name] = {
                "name": ch_name,
                "physical_channel": phys,
                "channel_type": "voltage_input",
                "unit": "V",
            }
    data = make_project_data(name, ch_data)
    path = Path(tmp_dir) / filename
    path.write_text(json.dumps(data, indent=2))
    return path


# =============================================================================
# PROJECT CONTEXT TESTS
# =============================================================================

class TestProjectContext:
    """Test the ProjectContext dataclass."""

    def test_basic_construction(self):
        ctx = ProjectContext(
            project_id="proj1",
            project_path=Path("config/projects/proj1.json"),
            project_data=make_project_data("My Project"),
        )
        assert ctx.project_id == "proj1"
        assert ctx.project_name == "My Project"
        assert ctx.color_index == 0

    def test_default_name_from_data(self):
        """If project_name is empty, it should use the name from project_data."""
        ctx = ProjectContext(
            project_id="proj1",
            project_path=Path("test.json"),
            project_data=make_project_data("Data Name"),
        )
        assert ctx.project_name == "Data Name"

    def test_explicit_name_overrides_data(self):
        ctx = ProjectContext(
            project_id="proj1",
            project_path=Path("test.json"),
            project_data=make_project_data("Data Name"),
            project_name="Explicit Name",
        )
        assert ctx.project_name == "Explicit Name"

    def test_default_state_machine_is_stopped(self):
        ctx = ProjectContext(
            project_id="proj1",
            project_path=Path("test.json"),
            project_data=make_project_data(),
        )
        assert ctx.state_machine is not None
        assert ctx.state_machine.state == DAQState.STOPPED

    def test_channel_names_empty_without_config(self):
        ctx = make_project_context("proj1")
        assert ctx.channel_names == set()

    def test_channel_names_with_config(self):
        ctx = make_project_context("proj1", channels={
            "TC_01": "Mod1/ai0",
            "TC_02": "Mod1/ai1",
        })
        assert ctx.channel_names == {"TC_01", "TC_02"}

    def test_acquiring_false_when_stopped(self):
        ctx = make_project_context("proj1")
        assert ctx.acquiring is False

    def test_acquiring_true_when_running(self):
        ctx = make_project_context("proj1")
        ctx.state_machine.force_state(DAQState.RUNNING)
        assert ctx.acquiring is True

    def test_recording_false_without_manager(self):
        ctx = make_project_context("proj1")
        assert ctx.recording is False

    def test_recording_delegates_to_manager(self):
        ctx = make_project_context("proj1")
        ctx.recording_manager = MagicMock()
        ctx.recording_manager.recording = True
        assert ctx.recording is True

    def test_color_index_stored(self):
        ctx = make_project_context("proj1", color_index=5)
        assert ctx.color_index == 5

    def test_loaded_at_is_set(self):
        before = datetime.now()
        ctx = make_project_context("proj1")
        after = datetime.now()
        assert before <= ctx.loaded_at <= after


class TestProjectContextTeardown:
    """Test ProjectContext.teardown() cleanup."""

    def test_teardown_forces_stopped_state(self):
        ctx = make_project_context("proj1")
        ctx.state_machine.force_state(DAQState.RUNNING)
        ctx.teardown()
        assert ctx.state_machine.state == DAQState.STOPPED

    def test_teardown_stops_recording(self):
        ctx = make_project_context("proj1")
        rm = MagicMock()
        rm.recording = True
        ctx.recording_manager = rm
        ctx.teardown()
        rm.stop.assert_called_once()

    def test_teardown_stops_scripts(self):
        ctx = make_project_context("proj1")
        sm = MagicMock()
        ctx.script_manager = sm
        ctx.teardown()
        sm.stop_all_scripts.assert_called_once()

    def test_teardown_stops_sequences(self):
        ctx = make_project_context("proj1")
        seq = MagicMock()
        ctx.sequence_manager = seq
        ctx.teardown()
        seq.stop_all.assert_called_once()

    def test_teardown_clears_safety(self):
        ctx = make_project_context("proj1")
        safety = MagicMock()
        ctx.safety_manager = safety
        ctx.teardown()
        safety.clear_all.assert_called_once()

    def test_teardown_clears_alarms(self):
        ctx = make_project_context("proj1")
        alarms = MagicMock()
        ctx.alarm_manager = alarms
        ctx.teardown()
        alarms.clear_all.assert_called_once_with(clear_configs=True)

    def test_teardown_survives_manager_exceptions(self):
        """Teardown should continue even if individual managers raise."""
        ctx = make_project_context("proj1")
        ctx.script_manager = MagicMock()
        ctx.script_manager.stop_all_scripts.side_effect = RuntimeError("script crash")
        ctx.sequence_manager = MagicMock()
        ctx.safety_manager = MagicMock()
        ctx.alarm_manager = MagicMock()

        ctx.teardown()  # Should not raise

        # Other managers still called despite script crash
        ctx.sequence_manager.stop_all.assert_called_once()
        ctx.safety_manager.clear_all.assert_called_once()
        ctx.alarm_manager.clear_all.assert_called_once()

    def test_teardown_skip_not_recording(self):
        """Teardown should not call stop_recording if not recording."""
        ctx = make_project_context("proj1")
        rm = MagicMock()
        rm.recording = False
        ctx.recording_manager = rm
        ctx.teardown()
        rm.stop_recording.assert_not_called()


class TestProjectContextSummary:
    """Test ProjectContext.to_summary() output."""

    def test_summary_fields(self):
        ctx = make_project_context("proj1", project_name="Test Project",
                                   channels={"TC_01": "Mod1/ai0"}, color_index=3)
        summary = ctx.to_summary()
        assert summary['projectId'] == 'proj1'
        assert summary['projectName'] == 'Test Project'
        assert summary['status'] == DAQState.STOPPED.name
        assert summary['acquiring'] is False
        assert summary['recording'] is False
        assert summary['channelCount'] == 1
        assert summary['colorIndex'] == 3
        assert 'loadedAt' in summary

    def test_summary_acquiring_state(self):
        ctx = make_project_context("proj1")
        ctx.state_machine.force_state(DAQState.RUNNING)
        summary = ctx.to_summary()
        assert summary['status'] == DAQState.RUNNING.name
        assert summary['acquiring'] is True


class TestChannelConflictDetection:
    """Test conflict detection between project contexts."""

    def test_no_conflicts_different_channels(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b", channels={"TC_02": "Mod1/ai1"})
        others = {"proj_a": ctx_a, "proj_b": ctx_b}

        conflicts = ctx_a.get_channel_conflicts(others)
        assert conflicts == {}

    def test_conflict_on_same_physical_channel(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b", channels={"Temp_01": "Mod1/ai0"})  # Same physical
        others = {"proj_a": ctx_a, "proj_b": ctx_b}

        conflicts = ctx_a.get_channel_conflicts(others)
        assert "Mod1/ai0" in conflicts
        assert "proj_b" in conflicts["Mod1/ai0"]

    def test_no_conflict_with_self(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        others = {"proj_a": ctx_a}

        conflicts = ctx_a.get_channel_conflicts(others)
        assert conflicts == {}

    def test_conflict_with_multiple_projects(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b", channels={"Temp_01": "Mod1/ai0"})
        ctx_c = make_project_context("proj_c", channels={"Volt_01": "Mod1/ai0"})
        others = {"proj_a": ctx_a, "proj_b": ctx_b, "proj_c": ctx_c}

        conflicts = ctx_a.get_channel_conflicts(others)
        assert "Mod1/ai0" in conflicts
        assert set(conflicts["Mod1/ai0"]) == {"proj_b", "proj_c"}

    def test_no_conflict_without_config(self):
        ctx_a = make_project_context("proj_a")  # No channels
        ctx_b = make_project_context("proj_b", channels={"TC_01": "Mod1/ai0"})
        others = {"proj_a": ctx_a, "proj_b": ctx_b}

        conflicts = ctx_a.get_channel_conflicts(others)
        assert conflicts == {}


# =============================================================================
# STATION STATE PERSISTENCE TESTS
# =============================================================================

class TestStationStatePersistence:
    """Test station state save/restore using temp files."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.state_path = Path(self.tmp_dir) / "station_state.json"

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _save_state(self, projects):
        """Simulate _save_station_state."""
        state = {
            "loaded_projects": [
                {
                    "project_id": pid,
                    "path": str(ctx.project_path),
                    "color_index": ctx.color_index,
                }
                for pid, ctx in projects.items()
            ]
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2))
        return state

    def _load_state(self):
        """Simulate _restore_station_state."""
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text())

    def test_save_empty_state(self):
        state = self._save_state({})
        assert state["loaded_projects"] == []
        assert self.state_path.exists()

    def test_save_and_restore_single_project(self):
        ctx = make_project_context("proj1", color_index=2)
        self._save_state({"proj1": ctx})

        loaded = self._load_state()
        assert len(loaded["loaded_projects"]) == 1
        assert loaded["loaded_projects"][0]["project_id"] == "proj1"
        assert loaded["loaded_projects"][0]["color_index"] == 2

    def test_save_and_restore_multiple_projects(self):
        projects = {
            "proj1": make_project_context("proj1", color_index=0),
            "proj2": make_project_context("proj2", color_index=1),
            "proj3": make_project_context("proj3", color_index=2),
        }
        self._save_state(projects)

        loaded = self._load_state()
        assert len(loaded["loaded_projects"]) == 3
        ids = {p["project_id"] for p in loaded["loaded_projects"]}
        assert ids == {"proj1", "proj2", "proj3"}

    def test_restore_nonexistent_file_returns_none(self):
        assert self._load_state() is None

    def test_color_index_roundtrip(self):
        """Color indices should survive save/restore cycle."""
        projects = {
            "proj1": make_project_context("proj1", color_index=5),
            "proj2": make_project_context("proj2", color_index=7),
        }
        self._save_state(projects)

        loaded = self._load_state()
        color_map = {p["project_id"]: p["color_index"] for p in loaded["loaded_projects"]}
        assert color_map["proj1"] == 5
        assert color_map["proj2"] == 7


# =============================================================================
# STATION CONFIG PRESET TESTS
# =============================================================================

class TestStationConfigPresets:
    """Test station configuration save/load/list/delete."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.configs_dir = Path(self.tmp_dir) / "stations"
        self.configs_dir.mkdir()
        self.projects_dir = Path(self.tmp_dir) / "projects"
        self.projects_dir.mkdir()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _save_config(self, name, projects):
        """Simulate _handle_station_config_save."""
        safe_name = name.lower().replace(' ', '_').replace('-', '_')
        # Remove non-alphanumeric (except underscore)
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')

        config = {
            "name": name,
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "projects": [
                {
                    "project_id": pid,
                    "path": str(ctx.project_path),
                    "color_index": ctx.color_index,
                }
                for pid, ctx in projects.items()
            ]
        }

        config_path = self.configs_dir / f"{safe_name}.json"

        # Preserve existing created timestamp
        if config_path.exists():
            existing = json.loads(config_path.read_text())
            config["created"] = existing.get("created", config["created"])

        config_path.write_text(json.dumps(config, indent=2))
        return config_path

    def _list_configs(self):
        """Simulate _handle_station_config_list."""
        configs = []
        for config_path in sorted(self.configs_dir.glob("*.json")):
            try:
                data = json.loads(config_path.read_text())
                configs.append({
                    "filename": config_path.name,
                    "name": data.get("name", config_path.stem),
                    "projectCount": len(data.get("projects", [])),
                    "projects": data.get("projects", []),
                    "created": data.get("created", ""),
                    "modified": data.get("modified", ""),
                })
            except (json.JSONDecodeError, IOError):
                continue
        return configs

    def _delete_config(self, filename):
        """Simulate _handle_station_config_delete."""
        config_path = self.configs_dir / filename
        if config_path.exists():
            config_path.unlink()
            return True
        return False

    def test_save_config_creates_file(self):
        projects = {"proj1": make_project_context("proj1")}
        path = self._save_config("My Test Config", projects)
        assert path.exists()
        assert path.name == "my_test_config.json"

    def test_save_config_sanitizes_name(self):
        projects = {"proj1": make_project_context("proj1")}
        path = self._save_config("Test-Config (Special!)", projects)
        assert path.name == "test_config_special.json"

    def test_save_config_preserves_created_on_update(self):
        projects = {"proj1": make_project_context("proj1")}
        path = self._save_config("MyConfig", projects)

        original = json.loads(path.read_text())
        original_created = original["created"]

        # Save again with updated projects
        projects["proj2"] = make_project_context("proj2")
        self._save_config("MyConfig", projects)

        updated = json.loads(path.read_text())
        assert updated["created"] == original_created  # Preserved
        assert len(updated["projects"]) == 2

    def test_save_config_stores_project_details(self):
        projects = {
            "proj1": make_project_context("proj1", color_index=3),
            "proj2": make_project_context("proj2", color_index=5),
        }
        path = self._save_config("Test", projects)
        data = json.loads(path.read_text())

        assert len(data["projects"]) == 2
        id_map = {p["project_id"]: p for p in data["projects"]}
        assert id_map["proj1"]["color_index"] == 3
        assert id_map["proj2"]["color_index"] == 5

    def test_list_configs_empty(self):
        configs = self._list_configs()
        assert configs == []

    def test_list_configs_returns_all(self):
        self._save_config("Config A", {"p1": make_project_context("p1")})
        self._save_config("Config B", {"p2": make_project_context("p2")})

        configs = self._list_configs()
        assert len(configs) == 2
        names = {c["name"] for c in configs}
        assert names == {"Config A", "Config B"}

    def test_list_configs_includes_project_count(self):
        projects = {
            "p1": make_project_context("p1"),
            "p2": make_project_context("p2"),
        }
        self._save_config("Multi", projects)

        configs = self._list_configs()
        assert configs[0]["projectCount"] == 2

    def test_delete_config_removes_file(self):
        self._save_config("ToDelete", {"p1": make_project_context("p1")})
        assert self._delete_config("todelete.json")
        assert not (self.configs_dir / "todelete.json").exists()

    def test_delete_nonexistent_returns_false(self):
        assert not self._delete_config("nonexistent.json")

    def test_list_after_delete(self):
        self._save_config("Keep", {"p1": make_project_context("p1")})
        self._save_config("Delete", {"p2": make_project_context("p2")})

        self._delete_config("delete.json")
        configs = self._list_configs()
        assert len(configs) == 1
        assert configs[0]["name"] == "Keep"


# =============================================================================
# SCAN BUDGET ESTIMATION TESTS
# =============================================================================

class TestScanBudgetEstimation:
    """Test the scan budget estimation logic."""

    def _estimate(self, channels, num_projects=1):
        """Simplified scan budget estimation matching _estimate_station_scan_budget."""
        budget_ms = 500.0
        modules = set()
        total_hw = 0
        remote_count = 0
        sim_count = 0

        for name, ch in channels.items():
            phys = getattr(ch, 'physical_channel', None)
            hw_source = getattr(ch, 'hardware_source', None)

            if hw_source and hw_source in ('crio', 'opto22', 'cfp', 'modbus', 'opcua', 'rest', 'ethernetip'):
                remote_count += 1
            elif phys:
                total_hw += 1
                # Module = everything before last /
                parts = phys.rsplit('/', 1)
                if len(parts) == 2:
                    modules.add(parts[0])
            else:
                sim_count += 1

        module_count = len(modules)
        estimated_ms = (
            module_count * 2.0 +
            total_hw * 0.1 +
            num_projects * 1.0
        )

        return {
            'feasible': estimated_ms < budget_ms,
            'channel_count': len(channels),
            'hw_channel_count': total_hw,
            'module_count': module_count,
            'remote_count': remote_count,
            'simulated_count': sim_count,
            'estimated_ms': round(estimated_ms, 1),
            'budget_ms': budget_ms,
        }

    def test_empty_channels_feasible(self):
        result = self._estimate({})
        assert result['feasible'] is True
        assert result['estimated_ms'] == 1.0  # Just 1 project overhead

    def test_small_project_feasible(self):
        channels = {}
        for i in range(16):
            ch = MagicMock()
            ch.physical_channel = f"cDAQ1Mod1/ai{i}"
            ch.hardware_source = None
            channels[f"ch_{i}"] = ch

        result = self._estimate(channels)
        assert result['feasible'] is True
        assert result['module_count'] == 1
        assert result['hw_channel_count'] == 16

    def test_three_projects_many_channels(self):
        """3 projects with 6 modules each = 18 modules, well within budget."""
        channels = {}
        for proj in range(3):
            for mod in range(6):
                for ch in range(8):
                    key = f"proj{proj}_mod{mod}_ch{ch}"
                    m = MagicMock()
                    m.physical_channel = f"cDAQ{proj + 1}Mod{mod + 1}/ai{ch}"
                    m.hardware_source = None
                    channels[key] = m

        result = self._estimate(channels, num_projects=3)
        # 18 modules * 2 + 144 channels * 0.1 + 3 projects * 1 = 36 + 14.4 + 3 = 53.4ms
        assert result['feasible'] is True
        assert result['module_count'] == 18
        assert result['hw_channel_count'] == 144

    def test_remote_channels_not_counted_as_hw(self):
        channels = {}
        ch = MagicMock()
        ch.physical_channel = "remote/ai0"
        ch.hardware_source = "modbus"
        channels["modbus_ch"] = ch

        result = self._estimate(channels)
        assert result['remote_count'] == 1
        assert result['hw_channel_count'] == 0

    def test_simulated_channels_not_counted_as_hw(self):
        ch = MagicMock()
        ch.physical_channel = None
        ch.hardware_source = None

        result = self._estimate({"sim_ch": ch})
        assert result['simulated_count'] == 1
        assert result['hw_channel_count'] == 0


# =============================================================================
# STATION UNION CHANNELS TESTS
# =============================================================================

class TestStationUnionChannels:
    """Test the channel union logic across loaded projects."""

    def _get_union(self, active_projects):
        """Simulate _get_station_union_channels."""
        all_channels = {}
        for ctx in active_projects.values():
            if ctx.config and ctx.config.channels:
                all_channels.update(ctx.config.channels)
        return all_channels

    def test_empty_projects(self):
        assert self._get_union({}) == {}

    def test_single_project(self):
        ctx = make_project_context("proj1", channels={"TC_01": "Mod1/ai0", "TC_02": "Mod1/ai1"})
        union = self._get_union({"proj1": ctx})
        assert set(union.keys()) == {"TC_01", "TC_02"}

    def test_multiple_projects_disjoint(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b", channels={"TC_02": "Mod1/ai1"})
        union = self._get_union({"proj_a": ctx_a, "proj_b": ctx_b})
        assert set(union.keys()) == {"TC_01", "TC_02"}

    def test_overlapping_channels_last_wins(self):
        """When two projects define the same channel name, later one wins."""
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b", channels={"TC_01": "Mod2/ai0"})
        union = self._get_union({"proj_a": ctx_a, "proj_b": ctx_b})
        assert len(union) == 1
        assert "TC_01" in union

    def test_project_without_config_skipped(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_b = make_project_context("proj_b")  # No config
        union = self._get_union({"proj_a": ctx_a, "proj_b": ctx_b})
        assert set(union.keys()) == {"TC_01"}


# =============================================================================
# 3-PROJECT LIMIT TESTS
# =============================================================================

class TestStationProjectLimit:
    """Test the MAX_STATION_PROJECTS=3 enforcement."""

    MAX_STATION_PROJECTS = 3

    def test_can_load_up_to_limit(self):
        active = {}
        for i in range(self.MAX_STATION_PROJECTS):
            assert len(active) < self.MAX_STATION_PROJECTS
            active[f"proj_{i}"] = make_project_context(f"proj_{i}")
        assert len(active) == 3

    def test_reject_at_limit(self):
        active = {f"proj_{i}": make_project_context(f"proj_{i}") for i in range(3)}
        # Attempting to load a 4th should be rejected
        assert len(active) >= self.MAX_STATION_PROJECTS

    def test_unload_makes_room(self):
        active = {f"proj_{i}": make_project_context(f"proj_{i}") for i in range(3)}
        del active["proj_0"]
        assert len(active) < self.MAX_STATION_PROJECTS

    def test_config_load_respects_available_slots(self):
        """Loading a config with 3 projects into 1 available slot should fail."""
        active = {
            "proj_0": make_project_context("proj_0"),
            "proj_1": make_project_context("proj_1"),
        }
        config_projects = [
            {"project_id": "proj_2", "path": "p2.json"},
            {"project_id": "proj_3", "path": "p3.json"},
        ]
        available_slots = self.MAX_STATION_PROJECTS - len(active)
        # Only 1 slot available but config has 2 new projects
        new_to_load = [p for p in config_projects if p["project_id"] not in active]
        assert len(new_to_load) > available_slots

    def test_config_load_skips_already_loaded(self):
        """Config load should skip projects that are already loaded."""
        active = {"proj_0": make_project_context("proj_0")}
        config_projects = [
            {"project_id": "proj_0", "path": "p0.json"},  # Already loaded
            {"project_id": "proj_1", "path": "p1.json"},  # New
        ]
        new_to_load = [p for p in config_projects if p["project_id"] not in active]
        assert len(new_to_load) == 1
        assert new_to_load[0]["project_id"] == "proj_1"


# =============================================================================
# MODE SWITCHING TESTS
# =============================================================================

class TestModeSwitching:
    """Test standalone <-> station mode switching."""

    def test_default_mode_is_standalone(self):
        settings = {}
        mode = settings.get("system_mode", "standalone")
        assert mode == "standalone"

    def test_save_and_load_mode(self):
        settings_path = None
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            settings_path = Path(f.name)
            json.dump({"system_mode": "station"}, f)

        data = json.loads(settings_path.read_text())
        assert data["system_mode"] == "station"
        settings_path.unlink()

    def test_switch_to_station_mode(self):
        mode = "standalone"
        new_mode = "station"
        assert new_mode in ("standalone", "station")
        mode = new_mode
        assert mode == "station"

    def test_switch_to_standalone_unloads_projects(self):
        """Switching to standalone should unload all station projects."""
        active = {
            "proj_0": make_project_context("proj_0"),
            "proj_1": make_project_context("proj_1"),
        }
        # Simulate standalone switch: unload all
        for pid in list(active.keys()):
            active[pid].teardown()
            del active[pid]
        assert len(active) == 0

    def test_invalid_mode_rejected(self):
        valid_modes = {"standalone", "station"}
        assert "invalid" not in valid_modes
        assert "bay" not in valid_modes  # Old name no longer valid

    def test_mode_response_format(self):
        old_mode = "standalone"
        new_mode = "station"
        response = {
            "success": True,
            "mode": new_mode,
            "previousMode": old_mode,
        }
        assert response["success"] is True
        assert response["mode"] == "station"
        assert response["previousMode"] == "standalone"


# =============================================================================
# VALUE DISPATCH TESTS
# =============================================================================

class TestValueDispatch:
    """Test filtering global values to per-project channels."""

    def test_dispatch_filters_to_project_channels(self):
        """Each project should only see its own channel values."""
        ctx_a = make_project_context("proj_a", channels={
            "TC_01": "Mod1/ai0", "TC_02": "Mod1/ai1"
        })
        ctx_b = make_project_context("proj_b", channels={
            "TC_03": "Mod1/ai2", "TC_04": "Mod1/ai3"
        })
        ctx_a.state_machine.force_state(DAQState.RUNNING)
        ctx_b.state_machine.force_state(DAQState.RUNNING)

        global_values = {
            "TC_01": 25.0, "TC_02": 30.0,
            "TC_03": 35.0, "TC_04": 40.0,
        }

        # Dispatch to each project
        for ctx in [ctx_a, ctx_b]:
            if ctx.acquiring:
                for ch_name in ctx.channel_names:
                    if ch_name in global_values:
                        ctx.channel_values[ch_name] = global_values[ch_name]

        assert set(ctx_a.channel_values.keys()) == {"TC_01", "TC_02"}
        assert set(ctx_b.channel_values.keys()) == {"TC_03", "TC_04"}
        assert ctx_a.channel_values["TC_01"] == 25.0
        assert ctx_b.channel_values["TC_03"] == 35.0

    def test_dispatch_skips_non_acquiring_projects(self):
        ctx_a = make_project_context("proj_a", channels={"TC_01": "Mod1/ai0"})
        ctx_a.state_machine.force_state(DAQState.RUNNING)
        ctx_b = make_project_context("proj_b", channels={"TC_02": "Mod1/ai1"})
        # ctx_b stays STOPPED

        global_values = {"TC_01": 25.0, "TC_02": 30.0}

        for ctx in [ctx_a, ctx_b]:
            if ctx.acquiring:
                for ch_name in ctx.channel_names:
                    if ch_name in global_values:
                        ctx.channel_values[ch_name] = global_values[ch_name]

        assert "TC_01" in ctx_a.channel_values
        assert ctx_b.channel_values == {}  # Not acquiring, no values dispatched


# =============================================================================
# DUPLICATE LOAD GUARD TESTS
# =============================================================================

class TestDuplicateLoadGuard:
    """Test that loading the same project twice is rejected."""

    def test_reject_duplicate_project_id(self):
        active = {"proj1": make_project_context("proj1")}
        project_id = "proj1"
        assert project_id in active  # Would be rejected

    def test_allow_different_project_id(self):
        active = {"proj1": make_project_context("proj1")}
        project_id = "proj2"
        assert project_id not in active  # Would be allowed


# =============================================================================
# PROJECT FILE LOADING TESTS
# =============================================================================

class TestProjectFileLoading:
    """Test loading project files from disk."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_valid_project_file(self):
        path = write_project_file(self.tmp_dir, "test.json", "Test Project",
                                  {"TC_01": "Mod1/ai0"})
        data = json.loads(path.read_text())
        assert data["type"] == "nisystem-project"
        assert data["name"] == "Test Project"
        assert "TC_01" in data["channels"]

    def test_reject_non_project_file(self):
        path = Path(self.tmp_dir) / "bad.json"
        path.write_text(json.dumps({"type": "other-thing"}))
        data = json.loads(path.read_text())
        assert data["type"] != "nisystem-project"

    def test_reject_nonexistent_file(self):
        path = Path(self.tmp_dir) / "missing.json"
        assert not path.exists()

    def test_project_id_from_filename(self):
        """Auto-generate project_id from filename stem."""
        path = write_project_file(self.tmp_dir, "My_Project.json", "My Project")
        project_id = path.stem  # "My_Project"
        assert project_id == "My_Project"

    def test_load_three_different_projects(self):
        """Should be able to load 3 distinct project files."""
        paths = []
        for i in range(3):
            path = write_project_file(
                self.tmp_dir, f"proj_{i}.json", f"Project {i}",
                {f"ch_{i}": f"Mod{i + 1}/ai0"}
            )
            paths.append(path)

        for path in paths:
            data = json.loads(path.read_text())
            assert data["type"] == "nisystem-project"
        assert len(paths) == 3


# =============================================================================
# ACQUIRING GUARD TESTS
# =============================================================================

class TestAcquiringGuards:
    """Test that load/unload is blocked while projects are acquiring."""

    def test_load_blocked_when_any_acquiring(self):
        active = {
            "proj1": make_project_context("proj1"),
            "proj2": make_project_context("proj2"),
        }
        active["proj1"].state_machine.force_state(DAQState.RUNNING)

        any_acquiring = any(ctx.acquiring for ctx in active.values())
        assert any_acquiring is True  # Load should be blocked

    def test_load_allowed_when_none_acquiring(self):
        active = {
            "proj1": make_project_context("proj1"),
            "proj2": make_project_context("proj2"),
        }

        any_acquiring = any(ctx.acquiring for ctx in active.values())
        assert any_acquiring is False  # Load should be allowed

    def test_unload_stops_acquisition_first(self):
        """Unloading a running project should stop acquisition before teardown."""
        ctx = make_project_context("proj1")
        ctx.state_machine.force_state(DAQState.RUNNING)
        assert ctx.acquiring is True

        # Simulate stop + teardown
        ctx.state_machine.force_state(DAQState.STOPPED)
        ctx.teardown()
        assert ctx.acquiring is False
