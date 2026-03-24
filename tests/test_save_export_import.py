"""
Tests for save/export/import round-trip integrity.

Validates that project data survives:
1. Save → Load cycle (ProjectManager)
2. Export → Import round-trip (simulating DAQ service handlers)
3. Schema migration during load
4. Edge cases: empty channels, special characters, large projects
5. All real project files in config/projects/
"""

import pytest
import tempfile
import json
import copy
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from project_manager import ProjectManager, ProjectStatus, PROJECT_SCHEMA
from schema_migrations import migrate_project, SCHEMA_VERSIONS

# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def temp_dirs():
    """Create temporary directories for projects and backups"""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        backup_dir = Path(tmpdir) / "backups"
        projects_dir.mkdir()
        backup_dir.mkdir()
        yield projects_dir, backup_dir

@pytest.fixture
def manager(temp_dirs):
    """Create a ProjectManager instance"""
    projects_dir, backup_dir = temp_dirs
    return ProjectManager(
        projects_dir=projects_dir,
        backup_dir=backup_dir,
        max_backups=5
    )

@pytest.fixture
def full_project():
    """A comprehensive project with all sections populated."""
    return {
        "type": "nisystem-project",
        "version": "2.0",
        "name": "Round Trip Test",
        "created": "2025-06-01T10:00:00",
        "system": {
            "mqtt_broker": "localhost",
            "mqtt_port": 1883,
            "mqtt_base_topic": "nisystem",
            "scan_rate_hz": 10,
            "publish_rate_hz": 4,
            "simulation_mode": False,
            "log_directory": "./logs",
            "system_name": "Round Trip Test",
            "system_id": "RT-TEST-001"
        },
        "channels": {
            "TT_101": {
                "name": "TT_101",
                "physical_channel": "cDAQ-9189-DHWSIMMod1/ai0",
                "channel_type": "thermocouple",
                "unit": "degC",
                "group": "Combustion",
                "description": "Furnace temperature",
                "visible": True,
                "low_limit": None,
                "high_limit": 950,
                "low_warning": None,
                "high_warning": 800,
                "chartable": True,
                "scale_slope": 1,
                "scale_offset": 0,
                "scale_type": "none",
                "four_twenty_scaling": False,
                "eng_units_min": None,
                "eng_units_max": None,
                "thermocouple_type": "K",
                "cjc_source": "internal",
                "voltage_range": 10,
                "current_range_ma": 20,
                "invert": False,
                "default_state": False,
                "default_value": 0,
                "safety_action": None,
                "safety_interlock": None,
                "log": True,
                "log_interval_ms": 1000,
                "source_type": "cdaq",
                "node_id": ""
            },
            "PT_201": {
                "name": "PT_201",
                "physical_channel": "cDAQ-9189-DHWSIMMod2/ai0",
                "channel_type": "current_input",
                "unit": "psig",
                "group": "Steam",
                "description": "Steam header pressure",
                "visible": True,
                "low_limit": None,
                "high_limit": 280,
                "low_warning": None,
                "high_warning": 250,
                "chartable": True,
                "scale_slope": 1,
                "scale_offset": 0,
                "scale_type": "none",
                "four_twenty_scaling": True,
                "eng_units_min": 0,
                "eng_units_max": 300,
                "thermocouple_type": None,
                "cjc_source": None,
                "voltage_range": 10,
                "current_range_ma": 20,
                "invert": False,
                "default_state": False,
                "default_value": 0,
                "safety_action": None,
                "safety_interlock": None,
                "log": True,
                "log_interval_ms": 1000,
                "source_type": "cdaq",
                "node_id": ""
            },
            "XS_301": {
                "name": "XS_301",
                "physical_channel": "cDAQ-9189-DHWSIMMod3/port0/line0",
                "channel_type": "digital_input",
                "unit": "",
                "group": "Safety",
                "description": "E-Stop status",
                "visible": True,
                "low_limit": None,
                "high_limit": None,
                "chartable": False,
                "source_type": "cdaq",
                "node_id": ""
            },
            "XY_401": {
                "name": "XY_401",
                "physical_channel": "cDAQ-9189-DHWSIMMod4/port0/line0",
                "channel_type": "digital_output",
                "unit": "",
                "group": "Control",
                "description": "Gas shutoff valve",
                "visible": True,
                "low_limit": None,
                "high_limit": None,
                "chartable": False,
                "default_state": False,
                "default_value": 0,
                "source_type": "cdaq",
                "node_id": ""
            },
            "FCV_501": {
                "name": "FCV_501",
                "physical_channel": "cDAQ-9189-DHWSIMMod5/ao0",
                "channel_type": "voltage_output",
                "unit": "%",
                "group": "Control",
                "description": "Gas control valve",
                "visible": True,
                "low_limit": None,
                "high_limit": None,
                "chartable": True,
                "scale_type": "map",
                "pre_scaled_min": 0,
                "pre_scaled_max": 10,
                "scaled_min": 0,
                "scaled_max": 100,
                "source_type": "cdaq",
                "node_id": ""
            }
        },
        "layout": {
            "gridColumns": 24,
            "rowHeight": 30,
            "pages": [
                {
                    "id": "page-1",
                    "name": "Overview",
                    "order": 0,
                    "widgets": [
                        {
                            "id": "w1",
                            "type": "NumericDisplay",
                            "x": 0, "y": 0, "w": 4, "h": 2,
                            "channel": "TT_101",
                            "label": "Furnace Temp"
                        },
                        {
                            "id": "w2",
                            "type": "GaugeWidget",
                            "x": 4, "y": 0, "w": 4, "h": 4,
                            "channel": "PT_201",
                            "label": "Steam Pressure",
                            "min": 0, "max": 300
                        }
                    ]
                },
                {
                    "id": "page-2",
                    "name": "Safety",
                    "order": 1,
                    "widgets": [
                        {
                            "id": "w3",
                            "type": "LedIndicator",
                            "x": 0, "y": 0, "w": 3, "h": 2,
                            "channel": "XS_301",
                            "label": "E-Stop"
                        }
                    ]
                }
            ],
            "currentPageId": "page-1"
        },
        "scripts": {
            "calculatedParams": [
                {
                    "id": "cp1",
                    "name": "Efficiency",
                    "formula": "(TT_101 - TT_102) / TT_101 * 100",
                    "unit": "%",
                    "enabled": True
                }
            ],
            "sequences": [],
            "schedules": [],
            "alarms": [],
            "transformations": [],
            "triggers": [
                {
                    "id": "trg1",
                    "name": "High Temp",
                    "condition": "TT_101 > 900",
                    "action": "alarm",
                    "enabled": True
                }
            ],
            "pythonScripts": [],
            "functionBlocks": [],
            "drawPatterns": [],
            "watchdogs": [],
            "stateMachines": [],
            "reportTemplates": [],
            "scheduledReports": []
        },
        "recording": {
            "config": {
                "interval_ms": 1000,
                "format": "csv"
            },
            "selectedChannels": ["TT_101", "PT_201"]
        },
        "safety": {
            "alarmConfigs": {},
            "interlocks": [
                {
                    "id": "int1",
                    "name": "High Temp Shutdown",
                    "condition": "TT_101 > 950",
                    "outputs": [
                        {"channel": "XY_401", "value": 0}
                    ],
                    "enabled": True
                }
            ],
            "safetyActions": {}
        }
    }

# ===========================================================================
# SAVE -> LOAD ROUND-TRIP TESTS
# ===========================================================================

class TestSaveLoadRoundTrip:
    """Verify project data integrity through save → load cycles."""

    def test_basic_save_load(self, manager, temp_dirs, full_project):
        """Save and reload a project, verify all data is preserved."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "test_project.json"

        # Save
        status, msg = manager.save_project(path, full_project)
        assert status == ProjectStatus.SUCCESS, f"Save failed: {msg}"

        # Load
        status, loaded, msg = manager.load_project(path)
        assert status == ProjectStatus.SUCCESS, f"Load failed: {msg}"

        # Verify core structure preserved
        assert loaded["type"] == "nisystem-project"
        assert loaded["version"] == "2.0"
        assert loaded["name"] == "Round Trip Test"

    def test_channels_preserved(self, manager, temp_dirs, full_project):
        """All channel fields survive save → load."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "channels_test.json"

        original_channels = copy.deepcopy(full_project["channels"])

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        for ch_name, orig_ch in original_channels.items():
            assert ch_name in loaded["channels"], f"Channel {ch_name} missing after load"
            loaded_ch = loaded["channels"][ch_name]
            for field, value in orig_ch.items():
                assert field in loaded_ch, f"Channel {ch_name} missing field: {field}"
                assert loaded_ch[field] == value, \
                    f"Channel {ch_name}.{field}: expected {value!r}, got {loaded_ch[field]!r}"

    def test_thermocouple_fields_preserved(self, manager, temp_dirs, full_project):
        """Thermocouple-specific fields survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "tc_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        tc = loaded["channels"]["TT_101"]
        assert tc["channel_type"] == "thermocouple"
        assert tc["thermocouple_type"] == "K"
        assert tc["cjc_source"] == "internal"

    def test_four_twenty_scaling_preserved(self, manager, temp_dirs, full_project):
        """4-20mA scaling parameters survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "420_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        ch = loaded["channels"]["PT_201"]
        assert ch["four_twenty_scaling"] is True
        assert ch["eng_units_min"] == 0
        assert ch["eng_units_max"] == 300
        assert ch["current_range_ma"] == 20

    def test_voltage_output_scaling_preserved(self, manager, temp_dirs, full_project):
        """Voltage output map scaling survives round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "ao_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        ch = loaded["channels"]["FCV_501"]
        assert ch["scale_type"] == "map"
        assert ch["pre_scaled_min"] == 0
        assert ch["pre_scaled_max"] == 10
        assert ch["scaled_min"] == 0
        assert ch["scaled_max"] == 100

    def test_layout_pages_preserved(self, manager, temp_dirs, full_project):
        """Multi-page layout with widgets survives round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "layout_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        assert len(loaded["layout"]["pages"]) == 2
        assert loaded["layout"]["pages"][0]["name"] == "Overview"
        assert loaded["layout"]["pages"][1]["name"] == "Safety"
        assert len(loaded["layout"]["pages"][0]["widgets"]) == 2
        assert loaded["layout"]["gridColumns"] == 24
        assert loaded["layout"]["rowHeight"] == 30

    def test_widget_props_preserved(self, manager, temp_dirs, full_project):
        """Widget properties survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "widget_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        w = loaded["layout"]["pages"][0]["widgets"][1]
        assert w["type"] == "GaugeWidget"
        assert w["channel"] == "PT_201"
        assert w["min"] == 0
        assert w["max"] == 300

    def test_scripts_preserved(self, manager, temp_dirs, full_project):
        """Scripts section (formulas, triggers, etc.) survives round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "scripts_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        assert len(loaded["scripts"]["calculatedParams"]) == 1
        assert loaded["scripts"]["calculatedParams"][0]["name"] == "Efficiency"
        assert loaded["scripts"]["calculatedParams"][0]["formula"] == \
            "(TT_101 - TT_102) / TT_101 * 100"

        assert len(loaded["scripts"]["triggers"]) == 1
        assert loaded["scripts"]["triggers"][0]["condition"] == "TT_101 > 900"

    def test_recording_preserved(self, manager, temp_dirs, full_project):
        """Recording config and selectedChannels survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "recording_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        assert loaded["recording"]["selectedChannels"] == ["TT_101", "PT_201"]
        assert loaded["recording"]["config"]["interval_ms"] == 1000

    def test_safety_interlocks_preserved(self, manager, temp_dirs, full_project):
        """Safety interlocks survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "safety_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        assert len(loaded["safety"]["interlocks"]) == 1
        interlock = loaded["safety"]["interlocks"][0]
        assert interlock["name"] == "High Temp Shutdown"
        assert interlock["condition"] == "TT_101 > 950"
        assert interlock["outputs"][0]["channel"] == "XY_401"

    def test_metadata_injected(self, manager, temp_dirs, full_project):
        """Save injects 'modified' timestamp and preserves 'created'."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "meta_test.json"

        original_created = full_project["created"]

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        assert loaded["created"] == original_created
        assert "modified" in loaded
        # Modified should be an ISO timestamp
        datetime.fromisoformat(loaded["modified"])

    def test_null_values_preserved(self, manager, temp_dirs, full_project):
        """Null/None values in channel configs survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "null_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        tc = loaded["channels"]["TT_101"]
        assert tc["low_limit"] is None
        assert tc["low_warning"] is None
        assert tc["eng_units_min"] is None
        assert tc["safety_action"] is None

    def test_boolean_values_preserved(self, manager, temp_dirs, full_project):
        """Boolean values don't get coerced to int."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "bool_test.json"

        manager.save_project(path, full_project)
        _, loaded, _ = manager.load_project(path)

        tc = loaded["channels"]["TT_101"]
        assert tc["visible"] is True
        assert isinstance(tc["visible"], bool)
        assert tc["invert"] is False
        assert isinstance(tc["invert"], bool)
        assert tc["four_twenty_scaling"] is False
        assert isinstance(tc["four_twenty_scaling"], bool)

        pt = loaded["channels"]["PT_201"]
        assert pt["four_twenty_scaling"] is True
        assert isinstance(pt["four_twenty_scaling"], bool)

# ===========================================================================
# EXPORT → IMPORT ROUND-TRIP TESTS
# ===========================================================================

class TestExportImportRoundTrip:
    """Simulate the export → import pipeline that goes through DAQ service."""

    @staticmethod
    def simulate_export(project_data):
        """Simulate frontend export (collectCurrentState → JSON string)."""
        return json.dumps(project_data, indent=2)

    @staticmethod
    def simulate_import_json(payload, projects_dir):
        """
        Simulate _handle_project_import_json logic.
        Returns (saved_path, saved_data) or raises.
        """
        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")
        if payload.get("type") != "nisystem-project":
            raise ValueError("Invalid project type")

        project_name = payload.get("name", "Imported Project")
        safe_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in project_name)
        safe_name = safe_name.strip().replace(' ', '_')
        filename = f"{safe_name}.json"
        project_path = projects_dir / filename

        payload["type"] = "nisystem-project"
        payload["version"] = payload.get("version", "1.0")
        payload["modified"] = datetime.now().isoformat()
        if not payload.get("created"):
            payload["created"] = datetime.now().isoformat()

        with open(project_path, 'w') as f:
            json.dump(payload, f, indent=2)

        return project_path, payload

    def test_export_import_round_trip(self, temp_dirs, full_project):
        """Full export → import cycle preserves data."""
        projects_dir, _ = temp_dirs

        # Export: serialize to JSON string
        exported_json = self.simulate_export(full_project)

        # Import: parse JSON, save to file
        imported_data = json.loads(exported_json)
        save_path, saved_data = self.simulate_import_json(imported_data, projects_dir)

        # Verify file was saved
        assert save_path.exists()

        # Re-read from disk
        with open(save_path) as f:
            on_disk = json.load(f)

        # All channels preserved
        for ch_name in full_project["channels"]:
            assert ch_name in on_disk["channels"]

        # Layout preserved
        assert len(on_disk["layout"]["pages"]) == len(full_project["layout"]["pages"])

        # Scripts preserved
        assert len(on_disk["scripts"]["calculatedParams"]) == \
            len(full_project["scripts"]["calculatedParams"])

    def test_import_filename_sanitization(self, temp_dirs, full_project):
        """Import sanitizes project name for filename."""
        projects_dir, _ = temp_dirs

        full_project["name"] = "My Test Project! (v2.0) [draft]"
        _, saved = self.simulate_import_json(copy.deepcopy(full_project), projects_dir)

        expected_name = "My_Test_Project___v2_0___draft_"
        expected_file = projects_dir / f"{expected_name}.json"
        assert expected_file.exists()

    def test_import_preserves_version(self, temp_dirs, full_project):
        """Import preserves existing version, doesn't force overwrite."""
        projects_dir, _ = temp_dirs

        full_project["version"] = "2.0"
        _, saved = self.simulate_import_json(copy.deepcopy(full_project), projects_dir)
        assert saved["version"] == "2.0"

    def test_import_defaults_version_if_missing(self, temp_dirs, full_project):
        """Import defaults version to 1.0 if missing."""
        projects_dir, _ = temp_dirs

        del full_project["version"]
        _, saved = self.simulate_import_json(copy.deepcopy(full_project), projects_dir)
        assert saved["version"] == "1.0"

    def test_import_sets_created_if_missing(self, temp_dirs, full_project):
        """Import sets created timestamp if not present."""
        projects_dir, _ = temp_dirs

        del full_project["created"]
        _, saved = self.simulate_import_json(copy.deepcopy(full_project), projects_dir)
        assert "created" in saved
        datetime.fromisoformat(saved["created"])

    def test_import_preserves_created_if_present(self, temp_dirs, full_project):
        """Import preserves existing created timestamp."""
        projects_dir, _ = temp_dirs

        original_created = full_project["created"]
        _, saved = self.simulate_import_json(copy.deepcopy(full_project), projects_dir)
        assert saved["created"] == original_created

    def test_import_rejects_non_project(self, temp_dirs):
        """Import rejects data without nisystem-project type."""
        projects_dir, _ = temp_dirs

        with pytest.raises(ValueError, match="Invalid project type"):
            self.simulate_import_json({"type": "other"}, projects_dir)

    def test_import_rejects_non_dict(self, temp_dirs):
        """Import rejects non-dict payloads."""
        projects_dir, _ = temp_dirs

        with pytest.raises(ValueError, match="Invalid payload"):
            self.simulate_import_json("not a dict", projects_dir)

# ===========================================================================
# SAVE → EXPORT → IMPORT → LOAD FULL CYCLE
# ===========================================================================

class TestFullCycle:
    """End-to-end: save → read file → parse → import → load."""

    def test_full_cycle(self, manager, temp_dirs, full_project):
        """Complete round-trip through all stages."""
        projects_dir, _ = temp_dirs

        # Stage 1: Save via ProjectManager
        save_path = projects_dir / "original.json"
        status, _ = manager.save_project(save_path, copy.deepcopy(full_project))
        assert status == ProjectStatus.SUCCESS

        # Stage 2: Read file (simulating export/download)
        with open(save_path) as f:
            exported = json.load(f)

        # Stage 3: Import (simulating import handler)
        exported["name"] = "Re-imported Project"
        import_dir = projects_dir / "imports"
        import_dir.mkdir()

        safe_name = exported["name"].replace(' ', '_')
        import_path = import_dir / f"{safe_name}.json"
        exported["modified"] = datetime.now().isoformat()
        with open(import_path, 'w') as f:
            json.dump(exported, f, indent=2)

        # Stage 4: Load via ProjectManager
        status, loaded, _ = manager.load_project(import_path)
        assert status == ProjectStatus.SUCCESS

        # Verify data integrity
        assert loaded["name"] == "Re-imported Project"
        assert set(loaded["channels"].keys()) == set(full_project["channels"].keys())

        # Verify deep channel data
        for ch_name in full_project["channels"]:
            orig = full_project["channels"][ch_name]
            reimported = loaded["channels"][ch_name]
            for field in orig:
                assert field in reimported, \
                    f"Missing field {ch_name}.{field} after full cycle"
                assert reimported[field] == orig[field], \
                    f"Changed field {ch_name}.{field}: {orig[field]!r} -> {reimported[field]!r}"

    def test_double_save(self, manager, temp_dirs, full_project):
        """Two consecutive saves produce identical file content (idempotent)."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "double_save.json"

        # Save twice
        manager.save_project(path, copy.deepcopy(full_project))
        with open(path) as f:
            first_save = json.load(f)

        # The modified timestamp will differ, but channel data should be identical
        manager.save_project(path, copy.deepcopy(full_project))
        with open(path) as f:
            second_save = json.load(f)

        # Compare everything except timestamps
        for key in ["channels", "layout", "scripts", "recording", "safety"]:
            if key in first_save:
                assert first_save[key] == second_save[key], \
                    f"Section '{key}' differs between saves"

# ===========================================================================
# SCHEMA MIGRATION TESTS
# ===========================================================================

class TestSchemaMigration:
    """Test that older project formats can be loaded correctly."""

    def test_v1_0_migrates_to_2_0(self):
        """V1.0 project auto-migrates to 2.0 on load."""
        v1_project = {
            "type": "nisystem-project",
            "version": "1.0",
            "channels": {
                "temp_1": {
                    "type": "thermocouple",
                    "physical_channel": "cDAQ1Mod1/ai0"
                }
            }
        }

        migrated, migrations = migrate_project(v1_project, "2.0")

        assert migrated["version"] == "2.0"
        assert len(migrations) == 2  # 1.0->1.1, 1.1->2.0
        # channel_type should be normalized
        assert migrated["channels"]["temp_1"]["channel_type"] == "thermocouple"
        # alarm defaults added
        assert migrated["channels"]["temp_1"]["alarm_deadband"] == 0.0

    def test_v1_1_migrates_to_2_0(self):
        """V1.1 project auto-migrates to 2.0."""
        v1_1_project = {
            "type": "nisystem-project",
            "version": "1.1",
            "channels": {
                "temp_1": {
                    "channel_type": "thermocouple",
                    "physical_channel": "cDAQ1Mod1/ai0"
                }
            }
        }

        migrated, migrations = migrate_project(v1_1_project, "2.0")

        assert migrated["version"] == "2.0"
        assert len(migrations) == 1  # 1.1->2.0
        assert "metadata" in migrated

    def test_v2_0_no_migration(self):
        """V2.0 project needs no migration."""
        v2_project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {}
        }

        migrated, migrations = migrate_project(v2_project, "2.0")
        assert len(migrations) == 0

    def test_list_channels_converted_to_dict(self):
        """Legacy list-format channels are converted to dict format in 2.0 migration."""
        v1_project = {
            "type": "nisystem-project",
            "version": "1.0",
            "channels": [
                {"name": "temp_1", "type": "thermocouple"},
                {"name": "press_1", "type": "voltage_input"}
            ]
        }

        migrated, _ = migrate_project(v1_project, "2.0")

        assert isinstance(migrated["channels"], dict)
        assert "temp_1" in migrated["channels"]
        assert "press_1" in migrated["channels"]

    def test_save_load_with_migration(self, manager, temp_dirs):
        """Saving a v1.0 project and loading it triggers migration."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "v1_project.json"

        # Write a v1.0 project directly to disk (bypass manager save validation)
        v1_project = {
            "type": "nisystem-project",
            "version": "1.0",
            "channels": {
                "temp_1": {
                    "type": "thermocouple",
                    "physical_channel": "cDAQ1Mod1/ai0"
                }
            }
        }
        with open(path, 'w') as f:
            json.dump(v1_project, f)

        # Load triggers migration
        status, loaded, msg = manager.load_project(path)
        assert status == ProjectStatus.SUCCESS
        assert loaded["version"] == "2.0"

# ===========================================================================
# EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Test edge cases that could cause data loss or corruption."""

    def test_empty_channels(self, manager, temp_dirs):
        """Project with no channels saves and loads correctly."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "empty_channels.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {}
        }

        status, _ = manager.save_project(path, project)
        assert status == ProjectStatus.SUCCESS

        status, loaded, _ = manager.load_project(path)
        assert status == ProjectStatus.SUCCESS
        assert loaded["channels"] == {}

    def test_special_characters_in_channel_name(self, manager, temp_dirs):
        """Channel names with dots/underscores survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "special_chars.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "py.my_calc": {
                    "channel_type": "calculated",
                    "name": "py.my_calc",
                    "unit": "V"
                },
                "crio_1.TT_101": {
                    "channel_type": "thermocouple",
                    "name": "crio_1.TT_101",
                    "unit": "degC"
                }
            }
        }

        manager.save_project(path, project)
        _, loaded, _ = manager.load_project(path)

        assert "py.my_calc" in loaded["channels"]
        assert "crio_1.TT_101" in loaded["channels"]

    def test_large_project(self, manager, temp_dirs):
        """Project with many channels (100+) saves and loads correctly."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "large_project.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {}
        }

        for i in range(200):
            project["channels"][f"CH_{i:04d}"] = {
                "channel_type": "voltage_input",
                "name": f"CH_{i:04d}",
                "physical_channel": f"Mod{(i // 16) + 1}/ai{i % 16}",
                "unit": "V",
                "group": f"Group_{i // 20}",
                "description": f"Channel {i}",
                "visible": True,
                "chartable": True,
                "source_type": "cdaq"
            }

        status, _ = manager.save_project(path, project)
        assert status == ProjectStatus.SUCCESS

        status, loaded, _ = manager.load_project(path)
        assert status == ProjectStatus.SUCCESS
        assert len(loaded["channels"]) == 200

    def test_unicode_in_descriptions(self, manager, temp_dirs):
        """Unicode characters in descriptions survive round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "unicode_test.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "TT_101": {
                    "channel_type": "thermocouple",
                    "name": "TT_101",
                    "unit": "\u00b0C",
                    "description": "Temperatur F\u00fchler - Ofen \u00dcberwachung"
                }
            }
        }

        manager.save_project(path, project)
        _, loaded, _ = manager.load_project(path)

        ch = loaded["channels"]["TT_101"]
        assert ch["unit"] == "\u00b0C"
        assert "F\u00fchler" in ch["description"]
        assert "\u00dc" in ch["description"]

    def test_numeric_precision(self, manager, temp_dirs):
        """Float values maintain precision through round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "precision_test.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "PT_101": {
                    "channel_type": "current_input",
                    "name": "PT_101",
                    "scale_slope": 0.0012345678,
                    "scale_offset": -0.0001,
                    "eng_units_min": 0.0,
                    "eng_units_max": 1013.25,
                    "low_limit": 0.001,
                    "high_limit": 999.999
                }
            }
        }

        manager.save_project(path, project)
        _, loaded, _ = manager.load_project(path)

        ch = loaded["channels"]["PT_101"]
        assert ch["scale_slope"] == 0.0012345678
        assert ch["scale_offset"] == -0.0001
        assert ch["eng_units_max"] == 1013.25
        assert ch["low_limit"] == 0.001
        assert ch["high_limit"] == 999.999

    def test_empty_string_fields(self, manager, temp_dirs):
        """Empty string fields are preserved (not converted to null)."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "empty_strings.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "CH_1": {
                    "channel_type": "voltage_input",
                    "name": "CH_1",
                    "unit": "",
                    "group": "",
                    "description": "",
                    "node_id": ""
                }
            }
        }

        manager.save_project(path, project)
        _, loaded, _ = manager.load_project(path)

        ch = loaded["channels"]["CH_1"]
        assert ch["unit"] == ""
        assert ch["group"] == ""
        assert ch["description"] == ""
        assert ch["node_id"] == ""

    def test_nested_widget_props(self, manager, temp_dirs):
        """Deeply nested widget configuration survives round-trip."""
        projects_dir, _ = temp_dirs
        path = projects_dir / "nested_widgets.json"

        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {},
            "layout": {
                "gridColumns": 24,
                "rowHeight": 30,
                "pages": [{
                    "id": "p1",
                    "name": "Test",
                    "order": 0,
                    "widgets": [{
                        "id": "w1",
                        "type": "TrendChart",
                        "x": 0, "y": 0, "w": 12, "h": 6,
                        "channels": ["TT_101", "TT_102", "TT_103"],
                        "timeWindow": 300,
                        "style": {
                            "colors": ["#ff0000", "#00ff00", "#0000ff"],
                            "lineWidth": 2,
                            "showGrid": True
                        },
                        "yAxis": {
                            "min": 0,
                            "max": 1000,
                            "label": "Temperature (\u00b0C)"
                        }
                    }]
                }]
            }
        }

        manager.save_project(path, project)
        _, loaded, _ = manager.load_project(path)

        w = loaded["layout"]["pages"][0]["widgets"][0]
        assert w["channels"] == ["TT_101", "TT_102", "TT_103"]
        assert w["style"]["colors"] == ["#ff0000", "#00ff00", "#0000ff"]
        assert w["yAxis"]["max"] == 1000

# ===========================================================================
# REAL PROJECT FILES VALIDATION
# ===========================================================================

class TestRealProjectFiles:
    """Validate all project files in config/projects/ can be loaded."""

    PROJECTS_DIR = Path(__file__).parent.parent / "config" / "projects"

    def _get_project_files(self):
        """Get all JSON files in the projects directory."""
        if not self.PROJECTS_DIR.exists():
            return []
        return sorted(
            f for f in self.PROJECTS_DIR.glob("*.json")
            if f.name != "manifest.json" and not f.is_dir()
        )

    def test_all_projects_parse_as_json(self):
        """Every project file is valid JSON."""
        for path in self._get_project_files():
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            assert isinstance(data, dict), f"{path.name}: root is not an object"

    def test_all_projects_have_required_fields(self):
        """Every project has type and version fields."""
        for path in self._get_project_files():
            with open(path, encoding='utf-8') as f:
                data = json.load(f)

            assert data.get("type") == "nisystem-project", \
                f"{path.name}: missing or wrong type"
            assert "version" in data, \
                f"{path.name}: missing version"
            assert data["version"] in ["1.0", "1.1", "2.0"], \
                f"{path.name}: invalid version {data['version']}"

    def test_all_projects_validate(self):
        """Every project passes ProjectManager validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProjectManager(
                projects_dir=Path(tmpdir) / "p",
                backup_dir=Path(tmpdir) / "b"
            )

            for path in self._get_project_files():
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)

                result = manager.validate_project(data)
                assert result.valid, \
                    f"{path.name}: validation failed: {result.errors}"

    def test_all_projects_save_load_round_trip(self):
        """Every project survives a save → load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            backup_dir = Path(tmpdir) / "backups"
            projects_dir.mkdir()
            backup_dir.mkdir()
            manager = ProjectManager(
                projects_dir=projects_dir,
                backup_dir=backup_dir,
                max_backups=5
            )

            for path in self._get_project_files():
                with open(path, encoding='utf-8') as f:
                    original = json.load(f)

                save_path = projects_dir / path.name
                status, msg = manager.save_project(save_path, copy.deepcopy(original))
                assert status == ProjectStatus.SUCCESS, \
                    f"{path.name}: save failed: {msg}"

                status, loaded, msg = manager.load_project(save_path)
                assert status == ProjectStatus.SUCCESS, \
                    f"{path.name}: load failed: {msg}"

                # Verify channels preserved
                orig_channels = original.get("channels", {})
                loaded_channels = loaded.get("channels", {})
                assert set(orig_channels.keys()) == set(loaded_channels.keys()), \
                    f"{path.name}: channel set changed"

    def test_all_projects_channels_have_types(self):
        """Every channel in every project has a channel_type or type field."""
        for path in self._get_project_files():
            with open(path, encoding='utf-8') as f:
                data = json.load(f)

            channels = data.get("channels", {})
            if isinstance(channels, dict):
                for ch_name, ch_config in channels.items():
                    ch_type = ch_config.get("channel_type") or ch_config.get("type", "")
                    # Allow empty for test projects designed to have errors
                    if "Validation_Error" not in path.name:
                        assert ch_type, \
                            f"{path.name}: channel {ch_name} has no type"

    def test_all_projects_have_layout(self):
        """Every project has a layout section with at least one page."""
        for path in self._get_project_files():
            with open(path, encoding='utf-8') as f:
                data = json.load(f)

            assert "layout" in data, f"{path.name}: missing layout"
            layout = data["layout"]
            assert "pages" in layout, f"{path.name}: layout missing pages"
            assert len(layout["pages"]) > 0, f"{path.name}: no pages"
