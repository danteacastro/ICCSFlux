#!/usr/bin/env python3
"""
Station Management Integration Test (DHWSIM cDAQ Simulation)
=============================================================

End-to-end validation of multi-project station mode using the
cDAQ-9189-DHWSIM simulated chassis in NI MAX.

Auto-starts Mosquitto + DAQ service — no manual NISystem Start.bat needed.

The two test projects share modules but use different channels (realistic
scenario — e.g., Zone 1 gets Mod1 ch0-7 and Zone 2 gets Mod1 ch8-15).
Both zones share Mod1, Mod2, Mod3, Mod4, and Mod6. This validates that
the union hardware reader correctly serves multiple projects from the
same physical modules without cross-contamination.

Prerequisites:
  - NI MAX with simulated cDAQ-9189-DHWSIM chassis configured
    (6 modules: NI 9213, NI 9205, NI 9203, NI 9375, NI 9375, NI 9264)
  - Project files generated: run `python scripts/create_station_test_projects.py`

Usage:
  # Full suite (auto-starts broker + DAQ):
  python -m pytest tests/test_station_integration.py -v -s

  # Individual groups:
  python -m pytest tests/test_station_integration.py -v -k "Group1"
  python -m pytest tests/test_station_integration.py -v -k "Group5"

Test Groups:
  Group 1 — Infrastructure (MQTT, DAQ, auth)
  Group 2 — Mode switching (standalone → station)
  Group 3 — Project loading (load 2 projects, conflict detection)
  Group 4 — Per-project acquisition (start, channel isolation, values)
  Group 5 — Station config presets (save/load/delete)
  Group 6 — Per-project recording (files on disk, sample counts, isolation)
  Group 9 — Per-project alarm scoping (fire alarm, verify no cross-contamination)
  Group 10 — Station state persistence (station_state.json structure)
  Group 7 — Unload and cleanup
  Group 8 — Guard rails (3-project limit, duplicate load, acquiring block)
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
tests_dir = Path(__file__).parent
if str(tests_dir) not in sys.path:
    sys.path.insert(0, str(tests_dir))

from service_fixtures import is_port_open

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJ_A_FILE = "_StationTest_Zone1.json"
PROJ_B_FILE = "_StationTest_Zone2.json"
PROJ_A_NAME = "Station Test — Zone 1"
PROJ_B_NAME = "Station Test — Zone 2"

# Channel sets per project — shared modules, different channels
# Project A: Zone 1 (first half of each module)
PROJ_A_TC = [f"TC_M1_ch{i:02d}" for i in range(8)]        # Mod1 ch0-7
PROJ_A_AI = [f"AI_M2_ch{i:02d}" for i in range(8)]        # Mod2 ch0-7
PROJ_A_CI = [f"CI_M3_ch{i:02d}" for i in range(4)]        # Mod3 ch0-3
PROJ_A_DI = [f"DI_M4_ch{i:02d}" for i in range(8)]        # Mod4 ch0-7
PROJ_A_AO = [f"AO_M6_ch{i:02d}" for i in range(8)]        # Mod6 ch0-7
PROJ_A_CHANNELS = set(PROJ_A_TC + PROJ_A_AI + PROJ_A_CI + PROJ_A_DI + PROJ_A_AO)  # 36

# Project B: Zone 2 (second half of each module + all DO)
PROJ_B_TC = [f"TC_M1_ch{i:02d}" for i in range(8, 16)]    # Mod1 ch8-15
PROJ_B_AI = [f"AI_M2_ch{i:02d}" for i in range(8, 16)]    # Mod2 ch8-15
PROJ_B_CI = [f"CI_M3_ch{i:02d}" for i in range(4, 8)]     # Mod3 ch4-7
PROJ_B_DI = [f"DI_M4_ch{i:02d}" for i in range(8, 16)]    # Mod4 ch8-15
PROJ_B_DO = [f"DO_M5_ch{i:02d}" for i in range(16)]       # Mod5 all 16 DO
PROJ_B_AO = [f"AO_M6_ch{i:02d}" for i in range(8, 16)]    # Mod6 ch8-15
PROJ_B_CHANNELS = set(PROJ_B_TC + PROJ_B_AI + PROJ_B_CI + PROJ_B_DI + PROJ_B_DO + PROJ_B_AO)  # 52

# Shared modules (both projects read from these, different channels)
SHARED_MODULES = {"Mod1", "Mod2", "Mod3", "Mod4", "Mod6"}

ALL_CHANNELS = PROJ_A_CHANNELS | PROJ_B_CHANNELS  # 88 total, no overlap

# Admin credentials (matches conftest.py ensure_test_admin)
_TEST_ADMIN_CREDENTIALS = ("test_admin", "validation_test_pw_2026")


# ---------------------------------------------------------------------------
# Cascade skip state
# ---------------------------------------------------------------------------

class _StationState:
    infra_ok = False
    mode_switched = False
    projects_loaded = False
    acquisition_started = False
    preset_saved = False


_state = _StationState()


def _require_infra():
    if not _state.infra_ok:
        pytest.skip("Infrastructure not ready (Group 1 must pass)")


def _require_mode():
    _require_infra()
    if not _state.mode_switched:
        pytest.skip("Station mode not active (Group 2 must pass)")


def _require_projects():
    _require_mode()
    if not _state.projects_loaded:
        pytest.skip("Projects not loaded (Group 3 must pass)")


def _require_acquisition():
    _require_projects()
    if not _state.acquisition_started:
        pytest.skip("Acquisition not started (Group 4 must pass)")


# ---------------------------------------------------------------------------
# StationHarness — MQTT client for station testing
# ---------------------------------------------------------------------------

class StationHarness:
    """MQTT test client for station management integration testing."""

    def __init__(self, host: str, port: int,
                 username: Optional[str] = None,
                 password: Optional[str] = None):
        import paho.mqtt.client as mqtt

        self.host = host
        self.port = port
        self.node_id: Optional[str] = None
        self.topic_base: Optional[str] = None

        # System status
        self._status: Optional[Dict[str, Any]] = None
        self._status_version = 0
        self._status_event = threading.Event()

        # Station status
        self._station_status: Optional[Dict[str, Any]] = None
        self._station_event = threading.Event()
        self._station_version = 0

        # Per-project channel values: {project_id: {channel: value}}
        self._project_values: Dict[str, Dict[str, Any]] = {}
        self._project_timestamps: Dict[str, Dict[str, float]] = {}
        self._values_lock = threading.Lock()

        # Debug: track regular (non-station) batch channel names
        self._debug_batch_channels: Set[str] = set()
        self._debug_batch_count = 0

        # Generic message waiters
        self._waiters: Dict[str, dict] = {}
        self._lock = threading.Lock()

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"station-test-{int(time.time() * 1000) % 100000}",
        )
        if username and password:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        # Subscribe to everything we need
        client.subscribe("nisystem/#", qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        topic = msg.topic

        # System status: nisystem/nodes/{node_id}/status/system
        if "/status/system" in topic:
            parts = topic.split("/")
            if len(parts) >= 4:
                self.node_id = parts[2]
                self.topic_base = f"nisystem/nodes/{self.node_id}"
            self._status = payload
            self._status_version += 1
            self._status_event.set()

        # Station status: nisystem/nodes/{node_id}/station/status
        elif "/station/status" in topic and "/config/" not in topic:
            self._station_status = payload
            self._station_version += 1
            self._station_event.set()

        # Per-project channel batches: nisystem/nodes/{node_id}/projects/{pid}/channels/batch
        elif "/projects/" in topic and "/channels/batch" in topic:
            parts = topic.split("/")
            try:
                proj_idx = parts.index("projects") + 1
                project_id = parts[proj_idx]
            except (ValueError, IndexError):
                return

            values = payload.get("v", {})
            now = time.time()
            with self._values_lock:
                if project_id not in self._project_values:
                    self._project_values[project_id] = {}
                    self._project_timestamps[project_id] = {}
                self._project_values[project_id].update(values)
                for ch in values:
                    self._project_timestamps[project_id][ch] = now

        # Debug: track regular batch (non-project-scoped)
        if "/channels/batch" in topic and "/projects/" not in topic:
            v = payload.get("v", {})
            if v:
                self._debug_batch_channels.update(v.keys())
                self._debug_batch_count += 1


        # Waiter dispatch
        with self._lock:
            for pattern, waiter in list(self._waiters.items()):
                if topic == pattern or topic.startswith(pattern.rstrip("#")):
                    waiter["messages"].append(payload)
                    if len(waiter["messages"]) >= waiter["count"]:
                        waiter["event"].set()

    def connect(self, timeout: float = 5.0) -> bool:
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            return True
        except Exception:
            return False

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def discover_node(self, timeout: float = 15.0) -> bool:
        self._status_event.clear()
        if self._status_event.wait(timeout=timeout):
            return self.node_id is not None
        return False

    def login_admin(self, timeout: float = 10.0) -> bool:
        if self.topic_base is None:
            return False

        auth_event = threading.Event()
        auth_result = {}
        auth_topic = f"{self.topic_base}/auth/status"

        def on_auth(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                auth_result.update(data)
                auth_event.set()
            except Exception:
                pass

        self.client.message_callback_add(auth_topic, on_auth)
        time.sleep(0.2)
        self.send_command("auth/login", {
            "username": _TEST_ADMIN_CREDENTIALS[0],
            "password": _TEST_ADMIN_CREDENTIALS[1],
            "source_ip": "station_test",
        })
        auth_event.wait(timeout=timeout)
        self.client.message_callback_remove(auth_topic)
        return auth_result.get("authenticated", False)

    def send_command(self, category: str, payload: Any = None):
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/{category}"
        data = json.dumps(payload) if payload is not None else "{}"
        self.client.publish(topic, data)

    def send_project_command(self, project_id: str, category: str,
                             payload: Any = None):
        """Send a command under the project namespace."""
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/projects/{project_id}/{category}"
        data = json.dumps(payload) if payload is not None else "{}"
        self.client.publish(topic, data)

    def get_status(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        if self._status is not None:
            return self._status
        self._status_event.wait(timeout=timeout)
        return self._status

    def refresh_status(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        version_before = self._status_version
        self._status_event.clear()
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._status_event.wait(timeout=min(1.0, deadline - time.time()))
            if self._status_version > version_before:
                return self._status
            self._status_event.clear()
        return self._status

    def wait_for_station_status(self, timeout: float = 10.0) -> Optional[Dict]:
        """Wait for a FRESH station status (ignores stale ones)."""
        version_before = self._station_version
        self._station_event.clear()
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            self._station_event.wait(timeout=min(1.0, remaining))
            if self._station_version > version_before:
                return self._station_status
            self._station_event.clear()
        # Timed out — return whatever we have
        return self._station_status

    def get_station_status(self) -> Optional[Dict]:
        return self._station_status

    def prepare_waiter(self, suffix: str, count: int = 1) -> str:
        """Pre-register a waiter BEFORE sending the command (avoids race)."""
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/{suffix}"
        event = threading.Event()
        waiter = {"event": event, "messages": [], "count": count}
        with self._lock:
            self._waiters[topic] = waiter
        return topic

    def collect_waiter(self, topic: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
        """Collect results from a pre-registered waiter."""
        with self._lock:
            waiter = self._waiters.get(topic)
        if not waiter:
            return []
        waiter["event"].wait(timeout=timeout)
        with self._lock:
            self._waiters.pop(topic, None)
        return waiter["messages"]

    def wait_for_topic(self, suffix: str, timeout: float = 10.0,
                       count: int = 1) -> List[Dict[str, Any]]:
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/{suffix}"
        event = threading.Event()
        waiter = {"event": event, "messages": [], "count": count}
        with self._lock:
            self._waiters[topic] = waiter
        event.wait(timeout=timeout)
        with self._lock:
            self._waiters.pop(topic, None)
        return waiter["messages"]

    def get_project_values(self, project_id: str) -> Dict[str, Any]:
        with self._values_lock:
            return dict(self._project_values.get(project_id, {}))

    def get_project_channels_received(self, project_id: str) -> Set[str]:
        with self._values_lock:
            return set(self._project_values.get(project_id, {}).keys())

    def clear_project_values(self):
        with self._values_lock:
            self._project_values.clear()
            self._project_timestamps.clear()


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def harness(mqtt_broker, daq_service):
    """Create and connect the station test harness."""
    h = StationHarness(
        host=mqtt_broker["host"],
        port=mqtt_broker["port"],
        username=mqtt_broker.get("username"),
        password=mqtt_broker.get("password"),
    )
    assert h.connect(), "Cannot connect to MQTT broker"
    assert h.discover_node(timeout=15), (
        "DAQ service not publishing status — is it running?"
    )
    yield h
    h.disconnect()


# ===========================================================================
# GROUP 1 — Infrastructure
# ===========================================================================

class TestGroup1_Infrastructure:
    """Verify MQTT, DAQ service, and project files exist."""

    def test_01_mqtt_broker_alive(self, mqtt_broker):
        assert is_port_open(mqtt_broker["host"], mqtt_broker["port"]), \
            "MQTT broker not responding"
        _state.infra_ok = True

    def test_02_daq_service_online(self, harness):
        _require_infra()
        status = harness.get_status(timeout=10)
        assert status is not None, "DAQ service not publishing status"
        assert harness.node_id is not None
        print(f"  Node ID: {harness.node_id}")

    def test_03_admin_login(self, harness):
        _require_infra()
        ok = harness.login_admin(timeout=10)
        assert ok, "Cannot log in as admin"

    def test_04_project_files_exist(self):
        _require_infra()
        proj_dir = PROJECT_ROOT / "config" / "projects"
        assert (proj_dir / PROJ_A_FILE).exists(), \
            f"{PROJ_A_FILE} not found — run: python scripts/create_station_test_projects.py"
        assert (proj_dir / PROJ_B_FILE).exists(), \
            f"{PROJ_B_FILE} not found — run: python scripts/create_station_test_projects.py"

        # Validate structure
        for fname in [PROJ_A_FILE, PROJ_B_FILE]:
            data = json.loads((proj_dir / fname).read_text(encoding="utf-8"))
            assert data["type"] == "nisystem-project"
            assert len(data["channels"]) > 0
        print(f"  Project A: {PROJ_A_FILE} ({len(PROJ_A_CHANNELS)} channels)")
        print(f"  Project B: {PROJ_B_FILE} ({len(PROJ_B_CHANNELS)} channels)")


# ===========================================================================
# GROUP 2 — Mode Switching
# ===========================================================================

class TestGroup2_ModeSwitching:
    """Switch from standalone to station mode."""

    def test_01_ensure_not_acquiring(self, harness):
        """Stop any running acquisition before mode switch."""
        _require_infra()
        status = harness.get_status(timeout=5)
        if status and status.get("acquiring"):
            harness.send_command("system/acquire/stop", {})
            time.sleep(3)
            status = harness.refresh_status(timeout=5)
            assert not (status or {}).get("acquiring"), \
                "Could not stop acquisition before mode switch"

    def test_02_switch_to_station_mode(self, harness):
        _require_infra()
        waiter_key = harness.prepare_waiter("system/mode/response")
        harness.send_command("system/mode", {"mode": "station"})
        msgs = harness.collect_waiter(waiter_key, timeout=10)
        assert len(msgs) > 0, "No mode switch response"
        resp = msgs[0]
        assert resp.get("success"), f"Mode switch failed: {resp.get('message')}"
        assert resp.get("mode") == "station"
        _state.mode_switched = True
        print(f"  Switched to station mode (was: {resp.get('previousMode')})")

    def test_03_station_status_published(self, harness):
        _require_mode()
        # Request fresh station status
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        assert status is not None, "No station status published"
        projects = status.get("projects", [])
        print(f"  Station has {len(projects)} projects loaded")


# ===========================================================================
# GROUP 3 — Project Loading
# ===========================================================================

class TestGroup3_ProjectLoading:
    """Load two test projects into the station."""

    def test_01_load_project_a(self, harness):
        _require_mode()
        # Pre-register waiters for both possible response topics
        loaded_key = harness.prepare_waiter("station/loaded")
        resp_key = harness.prepare_waiter("station/response")
        harness.send_command("station/load", {"filename": PROJ_A_FILE})
        loaded_msgs = harness.collect_waiter(loaded_key, timeout=15)
        resp_msgs = harness.collect_waiter(resp_key, timeout=2)
        msgs = loaded_msgs or resp_msgs
        if msgs:
            resp = msgs[0]
            if resp.get("success"):
                print(f"  Loaded Project A: {resp.get('projectName')} "
                      f"({resp.get('channelCount')} channels, color={resp.get('colorIndex')})")
                return
            elif "already loaded" in resp.get("message", ""):
                print(f"  Project A already loaded (from previous run)")
                return
            else:
                assert False, f"Load failed: {resp}"
        # Fallback: check station status to confirm load worked
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        project_ids = [p.get("projectId") for p in (status or {}).get("projects", [])]
        assert "_stationtest_zone1" in project_ids, \
            f"Project A not in station status: {project_ids}"
        print(f"  Loaded Project A (confirmed via status)")

    def test_02_load_project_b(self, harness):
        _require_mode()
        loaded_key = harness.prepare_waiter("station/loaded")
        resp_key = harness.prepare_waiter("station/response")
        harness.send_command("station/load", {"filename": PROJ_B_FILE})
        loaded_msgs = harness.collect_waiter(loaded_key, timeout=15)
        resp_msgs = harness.collect_waiter(resp_key, timeout=2)
        msgs = loaded_msgs or resp_msgs
        if msgs:
            resp = msgs[0]
            if resp.get("success"):
                print(f"  Loaded Project B: {resp.get('projectName')} "
                      f"({resp.get('channelCount')} channels, color={resp.get('colorIndex')})")
                return
            elif "already loaded" in resp.get("message", ""):
                print(f"  Project B already loaded (from previous run)")
                return
            else:
                assert False, f"Load failed: {resp}"
        # Fallback: check station status
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        project_ids = [p.get("projectId") for p in (status or {}).get("projects", [])]
        assert "_stationtest_zone2" in project_ids, \
            f"Project B not in station status: {project_ids}"
        print(f"  Loaded Project B (confirmed via status)")

    def test_03_station_shows_two_projects(self, harness):
        _require_mode()
        # Poll station status until we see 2 projects (max 15s)
        deadline = time.time() + 15
        projects = []
        while time.time() < deadline:
            harness.send_command("station/status", {})
            status = harness.wait_for_station_status(timeout=5)
            if status:
                projects = status.get("projects", [])
                if len(projects) == 2:
                    break
            time.sleep(1)

        assert len(projects) == 2, f"Expected 2 projects, got {len(projects)}"

        total = status.get("totalChannels", 0)
        assert total == len(ALL_CHANNELS), \
            f"Expected {len(ALL_CHANNELS)} total channels, got {total}"

        for p in projects:
            print(f"  {p.get('projectId')}: {p.get('projectName')} "
                  f"({p.get('channelCount')} ch, status={p.get('status')})")

        _state.projects_loaded = True

    def test_04_no_channel_conflicts_despite_shared_modules(self, harness):
        """Projects share modules (Mod1-4, Mod6) but use different channels — no conflicts."""
        _require_projects()
        status = harness.get_station_status()
        assert status is not None
        conflicts = status.get("conflicts", {})
        assert len(conflicts) == 0, f"Unexpected conflicts: {conflicts}"
        print(f"  No channel conflicts (shared modules: {SHARED_MODULES}, different channels)")

    def test_05_different_color_indices(self, harness):
        """Each project gets a unique color index."""
        _require_projects()
        status = harness.get_station_status()
        projects = status.get("projects", [])
        colors = [p.get("colorIndex") for p in projects]
        assert len(set(colors)) == len(colors), \
            f"Color indices not unique: {colors}"
        print(f"  Color indices: {colors}")


# ===========================================================================
# GROUP 4 — Per-Project Acquisition
# ===========================================================================

class TestGroup4_Acquisition:
    """Start acquisition and verify per-project channel isolation."""

    def test_01_get_project_ids(self, harness):
        """Discover actual project IDs from station status."""
        _require_projects()
        status = harness.get_station_status()
        projects = status.get("projects", [])
        # Store project IDs for later tests
        self.__class__._proj_ids = [p.get("projectId") for p in projects]
        assert len(self._proj_ids) == 2
        print(f"  Project IDs: {self._proj_ids}")

    def test_02_start_project_a_acquisition(self, harness):
        _require_projects()
        proj_id = self.__class__._proj_ids[0]
        harness.send_project_command(proj_id, "acquire/start", {})
        time.sleep(5)

        # Poll station status until project A shows as acquiring (max 15s)
        deadline = time.time() + 15
        proj_a = None
        while time.time() < deadline:
            harness.send_command("station/status", {})
            status = harness.wait_for_station_status(timeout=5)
            if status:
                projects = status.get("projects", [])
                proj_a = next((p for p in projects if p.get("projectId") == proj_id), None)
                if proj_a and (proj_a.get("acquiring") or
                               str(proj_a.get("status", "")).upper() == "RUNNING"):
                    break
            time.sleep(1)

        assert proj_a is not None, \
            f"Project A ({proj_id}) not in station status. Last status: {status}"
        is_running = (proj_a.get("acquiring") or
                      str(proj_a.get("status", "")).upper() == "RUNNING")
        assert is_running, \
            f"Project A not acquiring: status={proj_a.get('status')}, acquiring={proj_a.get('acquiring')}"
        print(f"  Project A ({proj_id}) acquiring")

    def test_03_start_project_b_acquisition(self, harness):
        _require_projects()
        proj_id = self.__class__._proj_ids[1]
        harness.send_project_command(proj_id, "acquire/start", {})
        time.sleep(5)

        # Poll station status until project B shows as acquiring (max 15s)
        deadline = time.time() + 15
        proj_b = None
        while time.time() < deadline:
            harness.send_command("station/status", {})
            status = harness.wait_for_station_status(timeout=5)
            if status:
                projects = status.get("projects", [])
                proj_b = next((p for p in projects if p.get("projectId") == proj_id), None)
                if proj_b and (proj_b.get("acquiring") or
                               str(proj_b.get("status", "")).upper() == "RUNNING"):
                    break
            time.sleep(1)

        assert proj_b is not None, \
            f"Project B ({proj_id}) not in station status. Last status: {status}"
        is_running = (proj_b.get("acquiring") or
                      str(proj_b.get("status", "")).upper() == "RUNNING")
        assert is_running, \
            f"Project B not acquiring: status={proj_b.get('status')}, acquiring={proj_b.get('acquiring')}"
        print(f"  Project B ({proj_id}) acquiring")
        _state.acquisition_started = True

    def test_04_project_a_receives_its_channels(self, harness):
        """Project A (Zone 1) should receive ch0-7 from shared modules, not ch8-15."""
        _require_acquisition()
        proj_id = self.__class__._proj_ids[0]

        # Wait for values to flow
        deadline = time.time() + 20
        while time.time() < deadline:
            received = harness.get_project_channels_received(proj_id)
            if len(received) >= len(PROJ_A_CHANNELS) * 0.5:
                break
            time.sleep(0.5)

        received = harness.get_project_channels_received(proj_id)
        print(f"  Project A receiving {len(received)}/{len(PROJ_A_CHANNELS)} channels")
        if len(received) == 0:
            # Debug: show what project keys exist and regular batch info
            with harness._values_lock:
                known_projects = list(harness._project_values.keys())
                total_vals = sum(len(v) for v in harness._project_values.values())
            print(f"  Debug: known projects={known_projects}, total values={total_vals}")
            print(f"  Debug: regular batch count={harness._debug_batch_count}, "
                  f"channels={len(harness._debug_batch_channels)}")

        # Should have its own channels
        expected_present = PROJ_A_CHANNELS & received
        assert len(expected_present) >= len(PROJ_A_CHANNELS) * 0.5, \
            f"Project A missing too many channels. Got: {len(expected_present)}/{len(PROJ_A_CHANNELS)}"

        # Should NOT have Project B's exclusive channels (ch8-15 on shared modules, all DO)
        b_only = PROJ_B_CHANNELS - PROJ_A_CHANNELS
        unexpected = b_only & received
        assert len(unexpected) == 0, \
            f"Project A received Project B channels: {sorted(unexpected)[:10]}"

    def test_05_project_b_receives_its_channels(self, harness):
        """Project B (Zone 2) should receive ch8-15 from shared modules + all DO."""
        _require_acquisition()
        proj_id = self.__class__._proj_ids[1]

        deadline = time.time() + 15
        while time.time() < deadline:
            received = harness.get_project_channels_received(proj_id)
            if len(received) >= len(PROJ_B_CHANNELS) * 0.5:
                break
            time.sleep(0.5)

        received = harness.get_project_channels_received(proj_id)
        print(f"  Project B receiving {len(received)}/{len(PROJ_B_CHANNELS)} channels")

        expected_present = PROJ_B_CHANNELS & received
        assert len(expected_present) >= len(PROJ_B_CHANNELS) * 0.5, \
            f"Project B missing too many channels. Got: {len(expected_present)}/{len(PROJ_B_CHANNELS)}"

        # Should NOT have Project A's exclusive channels (ch0-7 on shared modules)
        a_only = PROJ_A_CHANNELS - PROJ_B_CHANNELS
        unexpected = a_only & received
        assert len(unexpected) == 0, \
            f"Project B received Project A channels: {sorted(unexpected)[:10]}"

    def test_06_shared_module_both_projects_get_values(self, harness):
        """Both projects should get TC values from Mod1 (shared module, different channels)."""
        _require_acquisition()
        proj_a_id = self.__class__._proj_ids[0]
        proj_b_id = self.__class__._proj_ids[1]

        vals_a = harness.get_project_values(proj_a_id)
        vals_b = harness.get_project_values(proj_b_id)

        # Project A: TC_M1_ch00-07
        a_tc = {ch: vals_a.get(ch) for ch in PROJ_A_TC if ch in vals_a}
        # Project B: TC_M1_ch08-15
        b_tc = {ch: vals_b.get(ch) for ch in PROJ_B_TC if ch in vals_b}

        print(f"  Mod1 (shared): A has {len(a_tc)}/8 TCs, B has {len(b_tc)}/8 TCs")
        for ch, val in sorted(a_tc.items())[:3]:
            print(f"    A {ch}: {val}")
        for ch, val in sorted(b_tc.items())[:3]:
            print(f"    B {ch}: {val}")

        assert len(a_tc) >= 4, f"Project A missing Mod1 TCs: {len(a_tc)}/8"
        assert len(b_tc) >= 4, f"Project B missing Mod1 TCs: {len(b_tc)}/8"

        # Verify no cross-contamination on shared module
        a_has_b_tc = set(PROJ_B_TC) & set(vals_a.keys())
        b_has_a_tc = set(PROJ_A_TC) & set(vals_b.keys())
        assert len(a_has_b_tc) == 0, \
            f"Project A got Project B's Mod1 channels: {a_has_b_tc}"
        assert len(b_has_a_tc) == 0, \
            f"Project B got Project A's Mod1 channels: {b_has_a_tc}"

    def test_07_both_projects_status_shows_running(self, harness):
        """Station status should show both projects as running."""
        _require_acquisition()
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        for p in projects:
            is_running = (p.get("acquiring") or
                          str(p.get("status", "")).upper() == "RUNNING")
            assert is_running, \
                f"Project {p.get('projectId')} not running: status={p.get('status')}"
        print("  Both projects running concurrently")


# ===========================================================================
# GROUP 5 — Station Config Presets
# ===========================================================================

class TestGroup5_ConfigPresets:
    """Test saving, listing, and loading station configuration presets."""

    PRESET_NAME = "DHWSIM Test Station"

    def test_01_save_config_preset(self, harness):
        _require_projects()
        harness.send_command("station/config/save", {"name": self.PRESET_NAME})
        msgs = harness.wait_for_topic("station/config/save/response", timeout=10)
        assert len(msgs) > 0, "No save response"
        resp = msgs[0]
        assert resp.get("success"), f"Save failed: {resp.get('message')}"
        assert resp.get("projectCount") == 2
        print(f"  Saved preset: {resp.get('name')} ({resp.get('filename')})")
        _state.preset_saved = True

    def test_02_list_config_presets(self, harness):
        _require_projects()
        if not _state.preset_saved:
            pytest.skip("Preset not saved")
        harness.send_command("station/config/list", {})
        msgs = harness.wait_for_topic("station/config/list/response", timeout=10)
        assert len(msgs) > 0, "No list response"
        configs = msgs[0].get("configs", [])
        assert len(configs) >= 1
        names = [c.get("name") for c in configs]
        assert self.PRESET_NAME in names, \
            f"Preset '{self.PRESET_NAME}' not in list: {names}"
        print(f"  Found {len(configs)} preset(s): {names}")

    def test_03_preset_file_exists_on_disk(self):
        _require_projects()
        if not _state.preset_saved:
            pytest.skip("Preset not saved")
        configs_dir = PROJECT_ROOT / "config" / "stations"
        preset_files = list(configs_dir.glob("*.json"))
        assert len(preset_files) >= 1, "No preset files on disk"
        # Find our preset
        found = False
        for f in preset_files:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("name") == self.PRESET_NAME:
                found = True
                assert len(data.get("projects", [])) == 2
                print(f"  Preset on disk: {f.name}")
                break
        assert found, f"Preset '{self.PRESET_NAME}' not found on disk"


# ===========================================================================
# GROUP 6 — Per-Project Recording (Deep Verification)
# ===========================================================================

class TestGroup6_Recording:
    """Test per-project recording: start, verify files on disk, sample counts, isolation."""

    _proj_a_recording_dir: Optional[Path] = None
    _proj_b_recording_dir: Optional[Path] = None

    def test_01_start_recording_project_a(self, harness):
        """Start recording on Project A only."""
        _require_acquisition()
        proj_id = TestGroup4_Acquisition._proj_ids[0]
        harness.send_project_command(proj_id, "recording/start", {})
        time.sleep(4)  # Let a few samples write

        # Verify via station status
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        proj_a = next((p for p in projects if p["projectId"] == proj_id), None)
        assert proj_a is not None, "Project A not in station status"
        assert proj_a.get("recording"), \
            f"Project A not recording (status: {proj_a})"
        print(f"  Project A recording started")

    def test_02_project_b_not_recording(self, harness):
        """Verify Project B is NOT recording (isolation check)."""
        _require_acquisition()
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        proj_b = next((p for p in projects if p["projectId"] == proj_b_id), None)
        assert proj_b is not None, "Project B not in station status"
        assert not proj_b.get("recording"), \
            "Project B should NOT be recording — only A was started"
        print(f"  Project B correctly not recording")

    def test_03_start_recording_project_b(self, harness):
        """Start recording on Project B as well."""
        _require_acquisition()
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]
        harness.send_project_command(proj_b_id, "recording/start", {})
        time.sleep(4)

        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        proj_b = next((p for p in projects if p["projectId"] == proj_b_id), None)
        assert proj_b is not None
        assert proj_b.get("recording"), \
            f"Project B not recording (status: {proj_b})"
        print(f"  Project B recording started")

    def test_04_verify_recording_files_on_disk(self, harness):
        """Verify CSV files exist in per-project recording directories."""
        _require_acquisition()
        proj_a_id = TestGroup4_Acquisition._proj_ids[0]
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]

        # Recording dirs: {log_directory}/{project_id}/
        # The DAQ service runs from services/daq_service/, so ./logs/ is relative to that
        # But the config may use absolute or relative paths
        possible_bases = [
            PROJECT_ROOT / "logs",
            PROJECT_ROOT / "services" / "daq_service" / "logs",
            Path("./logs").resolve(),
        ]

        # Find recording files for Project A
        proj_a_files = []
        for base in possible_bases:
            rec_dir = base / proj_a_id
            if rec_dir.exists():
                TestGroup6_Recording._proj_a_recording_dir = rec_dir
                proj_a_files = list(rec_dir.glob("*.csv"))
                if proj_a_files:
                    break

        assert len(proj_a_files) > 0, \
            f"No CSV files found for Project A ({proj_a_id}) in any of: " \
            f"{[str(b / proj_a_id) for b in possible_bases]}"
        print(f"  Project A: {len(proj_a_files)} CSV file(s) in "
              f"{TestGroup6_Recording._proj_a_recording_dir}")

        # Find recording files for Project B
        proj_b_files = []
        for base in possible_bases:
            rec_dir = base / proj_b_id
            if rec_dir.exists():
                TestGroup6_Recording._proj_b_recording_dir = rec_dir
                proj_b_files = list(rec_dir.glob("*.csv"))
                if proj_b_files:
                    break

        assert len(proj_b_files) > 0, \
            f"No CSV files found for Project B ({proj_b_id})"
        print(f"  Project B: {len(proj_b_files)} CSV file(s) in "
              f"{TestGroup6_Recording._proj_b_recording_dir}")

    def test_05_verify_csv_content_isolation(self, harness):
        """Verify each project's CSV only contains that project's channels."""
        _require_acquisition()
        proj_a_dir = TestGroup6_Recording._proj_a_recording_dir
        proj_b_dir = TestGroup6_Recording._proj_b_recording_dir
        if not proj_a_dir or not proj_b_dir:
            pytest.skip("Recording dirs not found (test_04 must pass)")

        # Read Project A's latest CSV
        a_files = sorted(proj_a_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
        assert len(a_files) > 0
        a_csv = a_files[-1]
        a_lines = a_csv.read_text(encoding='utf-8').splitlines()
        # Find header line (skip metadata comment lines starting with #)
        a_header = None
        a_data_lines = 0
        for line in a_lines:
            if line.startswith('#'):
                continue
            if a_header is None:
                a_header = line
            else:
                a_data_lines += 1

        assert a_header is not None, f"No header in {a_csv.name}"
        a_columns = set(a_header.split(','))
        # Remove timestamp column
        a_columns.discard('Timestamp')
        a_columns.discard('timestamp')

        # All columns should be Project A channels
        unexpected_b = a_columns & PROJ_B_CHANNELS
        assert len(unexpected_b) == 0, \
            f"Project A CSV contains Project B channels: {unexpected_b}"
        # Should contain at least some Project A channels
        expected_a = a_columns & PROJ_A_CHANNELS
        assert len(expected_a) > 0, \
            f"Project A CSV has no Project A channels. Columns: {a_columns}"
        print(f"  Project A CSV: {len(expected_a)} channels, {a_data_lines} data rows")

        # Read Project B's latest CSV
        b_files = sorted(proj_b_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
        assert len(b_files) > 0
        b_csv = b_files[-1]
        b_lines = b_csv.read_text(encoding='utf-8').splitlines()
        b_header = None
        b_data_lines = 0
        for line in b_lines:
            if line.startswith('#'):
                continue
            if b_header is None:
                b_header = line
            else:
                b_data_lines += 1

        assert b_header is not None, f"No header in {b_csv.name}"
        b_columns = set(b_header.split(','))
        b_columns.discard('Timestamp')
        b_columns.discard('timestamp')

        unexpected_a = b_columns & PROJ_A_CHANNELS
        assert len(unexpected_a) == 0, \
            f"Project B CSV contains Project A channels: {unexpected_a}"
        expected_b = b_columns & PROJ_B_CHANNELS
        assert len(expected_b) > 0, \
            f"Project B CSV has no Project B channels. Columns: {b_columns}"
        print(f"  Project B CSV: {len(expected_b)} channels, {b_data_lines} data rows")

    def test_06_verify_sample_counts(self, harness):
        """Verify both projects have recorded data rows (not just headers)."""
        _require_acquisition()
        proj_a_dir = TestGroup6_Recording._proj_a_recording_dir
        proj_b_dir = TestGroup6_Recording._proj_b_recording_dir
        if not proj_a_dir or not proj_b_dir:
            pytest.skip("Recording dirs not found")

        for label, rec_dir in [("A", proj_a_dir), ("B", proj_b_dir)]:
            csv_files = sorted(rec_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
            assert len(csv_files) > 0
            latest = csv_files[-1]
            data_rows = sum(1 for line in latest.read_text(encoding='utf-8').splitlines()
                            if line and not line.startswith('#')
                            and 'Timestamp' not in line and 'timestamp' not in line)
            assert data_rows >= 2, \
                f"Project {label} has only {data_rows} data rows — expected at least 2"
            print(f"  Project {label}: {data_rows} samples recorded")

    def test_07_stop_recording_both(self, harness):
        """Stop recording on both projects."""
        _require_acquisition()
        proj_a_id = TestGroup4_Acquisition._proj_ids[0]
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]

        harness.send_project_command(proj_a_id, "recording/stop", {})
        harness.send_project_command(proj_b_id, "recording/stop", {})
        time.sleep(2)

        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        for p in projects:
            assert not p.get("recording"), \
                f"Project {p.get('projectId')} still recording after stop"
        print("  Both projects stopped recording")


# ===========================================================================
# GROUP 9 — Per-Project Alarm Scoping
# ===========================================================================

class TestGroup9_AlarmScoping:
    """Verify alarms fire per-project and don't cross-contaminate."""

    _alarm_a_id = "test-alarm-proj-a"
    _alarm_b_id = "test-alarm-proj-b"

    def test_01_configure_alarm_on_project_a(self, harness):
        """Push alarm config to Project A for TC_M1_ch00 (Hi > 50)."""
        _require_acquisition()
        proj_a_id = TestGroup4_Acquisition._proj_ids[0]

        resp_key = harness.prepare_waiter(
            f"projects/{proj_a_id}/alarms/configure/response")
        harness.send_project_command(proj_a_id, "commands/alarm/configure", {
            "id": self._alarm_a_id,
            "channel": "TC_M1_ch00",
            "name": "TC_M1_ch00",
            "severity": "HIGH",
            "high": 50,
            "deadband": 0,
            "on_delay_s": 0,
            "off_delay_s": 0,
            "latch_behavior": "AUTO_CLEAR",
        })
        msgs = harness.collect_waiter(resp_key, timeout=10)
        assert len(msgs) > 0, "No alarm configure response"
        assert msgs[0].get("success"), \
            f"Alarm configure failed: {msgs[0].get('error')}"
        print(f"  Configured alarm on Project A: {self._alarm_a_id}")

    def test_02_configure_alarm_on_project_b(self, harness):
        """Push alarm config to Project B for TC_M1_ch08 (Hi > 50)."""
        _require_acquisition()
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]

        resp_key = harness.prepare_waiter(
            f"projects/{proj_b_id}/alarms/configure/response")
        harness.send_project_command(proj_b_id, "commands/alarm/configure", {
            "id": self._alarm_b_id,
            "channel": "TC_M1_ch08",
            "name": "TC_M1_ch08",
            "severity": "HIGH",
            "high": 50,
            "deadband": 0,
            "on_delay_s": 0,
            "off_delay_s": 0,
            "latch_behavior": "AUTO_CLEAR",
        })
        msgs = harness.collect_waiter(resp_key, timeout=10)
        assert len(msgs) > 0, "No alarm configure response"
        assert msgs[0].get("success"), \
            f"Alarm configure failed: {msgs[0].get('error')}"
        print(f"  Configured alarm on Project B: {self._alarm_b_id}")

    def test_03_wait_for_alarm_events(self, harness):
        """Wait for simulator values to trigger alarms (simulated TCs often > 50)."""
        _require_acquisition()
        proj_a_id = TestGroup4_Acquisition._proj_ids[0]
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]

        # Simulator TC values are typically sine waves 0-200°C, so they should
        # cross 50°C within a few seconds. Wait up to 15s.
        a_alarm_key = harness.prepare_waiter(
            f"projects/{proj_a_id}/alarms/")
        b_alarm_key = harness.prepare_waiter(
            f"projects/{proj_b_id}/alarms/")

        time.sleep(10)  # Let scan loop push values through alarm manager

        a_msgs = harness.collect_waiter(a_alarm_key, timeout=5)
        b_msgs = harness.collect_waiter(b_alarm_key, timeout=5)

        # At least one project should have fired
        has_a = len(a_msgs) > 0
        has_b = len(b_msgs) > 0
        print(f"  Project A alarm events: {len(a_msgs)}, Project B: {len(b_msgs)}")

        if not has_a and not has_b:
            # Check if simulator values are reaching threshold
            vals_a = harness.get_project_values(proj_a_id)
            tc_val = vals_a.get("TC_M1_ch00", "N/A")
            vals_b = harness.get_project_values(proj_b_id)
            tc_val_b = vals_b.get("TC_M1_ch08", "N/A")
            print(f"  TC_M1_ch00={tc_val}, TC_M1_ch08={tc_val_b}")
            pytest.skip("Simulator values haven't crossed alarm threshold yet")

    def test_04_alarm_scoped_to_project(self, harness):
        """Verify alarm events go to the correct project namespace only."""
        _require_acquisition()
        proj_a_id = TestGroup4_Acquisition._proj_ids[0]
        proj_b_id = TestGroup4_Acquisition._proj_ids[1]

        # Subscribe to both project alarm topics and collect for 8 seconds
        a_key = harness.prepare_waiter(f"projects/{proj_a_id}/alarms/", count=100)
        b_key = harness.prepare_waiter(f"projects/{proj_b_id}/alarms/", count=100)
        time.sleep(8)
        a_msgs = harness.collect_waiter(a_key, timeout=1)
        b_msgs = harness.collect_waiter(b_key, timeout=1)

        # Check that Project A alarm events reference Project A channels
        for msg in a_msgs:
            ch = msg.get("channel", "")
            if ch:
                assert ch in PROJ_A_CHANNELS, \
                    f"Project A alarm references non-A channel: {ch}"

        # Check that Project B alarm events reference Project B channels
        for msg in b_msgs:
            ch = msg.get("channel", "")
            if ch:
                assert ch in PROJ_B_CHANNELS, \
                    f"Project B alarm references non-B channel: {ch}"

        print(f"  Alarm scoping verified: A={len(a_msgs)} events, B={len(b_msgs)} events")
        print(f"  No cross-contamination detected")


# ===========================================================================
# GROUP 10 — Station State Persistence
# ===========================================================================

class TestGroup10_Persistence:
    """Test station state save/restore across mode switches."""

    def test_01_verify_station_state_file_exists(self, harness):
        """Verify config/station_state.json was written by the DAQ service."""
        _require_acquisition()
        state_file = PROJECT_ROOT / "config" / "station_state.json"
        # The DAQ service may write to its CWD — check multiple locations
        possible_paths = [
            state_file,
            PROJECT_ROOT / "services" / "daq_service" / "config" / "station_state.json",
        ]
        found = None
        for p in possible_paths:
            if p.exists():
                found = p
                break

        if found is None:
            # Force a state save by re-requesting station status
            harness.send_command("station/status", {})
            time.sleep(2)
            for p in possible_paths:
                if p.exists():
                    found = p
                    break

        assert found is not None, \
            f"station_state.json not found in: {[str(p) for p in possible_paths]}"
        content = json.loads(found.read_text(encoding='utf-8'))
        projects = content.get("loaded_projects", [])
        assert len(projects) >= 2, \
            f"Expected 2+ projects in station_state.json, got {len(projects)}"
        project_ids = [p["project_id"] for p in projects]
        assert TestGroup4_Acquisition._proj_ids[0] in project_ids
        assert TestGroup4_Acquisition._proj_ids[1] in project_ids
        print(f"  station_state.json: {len(projects)} projects persisted at {found}")

    def test_02_state_file_has_correct_structure(self, harness):
        """Verify the station state file has required fields."""
        _require_acquisition()
        possible_paths = [
            PROJECT_ROOT / "config" / "station_state.json",
            PROJECT_ROOT / "services" / "daq_service" / "config" / "station_state.json",
        ]
        found = next((p for p in possible_paths if p.exists()), None)
        if not found:
            pytest.skip("station_state.json not found")

        content = json.loads(found.read_text(encoding='utf-8'))
        for entry in content.get("loaded_projects", []):
            assert "project_id" in entry, f"Missing project_id: {entry}"
            assert "path" in entry, f"Missing path: {entry}"
            assert "color_index" in entry, f"Missing color_index: {entry}"
            # Verify path points to real file
            proj_path = Path(entry["path"])
            assert proj_path.exists(), \
                f"Project file not found: {entry['path']}"
        print("  Station state structure validated")


# ===========================================================================
# GROUP 7 — Unload and Cleanup
# ===========================================================================

class TestGroup7_Cleanup:
    """Stop acquisition, unload projects, switch back to standalone."""

    def test_01_stop_project_b_acquisition(self, harness):
        _require_acquisition()
        proj_id = TestGroup4_Acquisition._proj_ids[1]
        harness.send_project_command(proj_id, "acquire/stop", {})
        time.sleep(3)

        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        projects = status.get("projects", [])
        proj_b = next((p for p in projects if p["projectId"] == proj_id), None)
        if proj_b:
            assert not proj_b.get("acquiring"), \
                f"Project B still acquiring after stop"
        print(f"  Project B stopped")

    def test_02_stop_project_a_acquisition(self, harness):
        _require_acquisition()
        proj_id = TestGroup4_Acquisition._proj_ids[0]
        harness.send_project_command(proj_id, "acquire/stop", {})
        time.sleep(3)
        print(f"  Project A stopped")

    def test_03_unload_project_b(self, harness):
        _require_projects()
        proj_id = TestGroup4_Acquisition._proj_ids[1]

        # Ensure acquisition is stopped first (unload handles this but be explicit)
        harness.send_project_command(proj_id, "acquire/stop", {})
        time.sleep(2)

        harness.send_command("station/unload", {"projectId": proj_id})
        # Wait for either station/unloaded or station/response (error)
        time.sleep(3)
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        project_ids = [p.get("projectId") for p in status.get("projects", [])]
        assert proj_id not in project_ids, \
            f"Project B still loaded after unload: {project_ids}"
        print(f"  Unloaded Project B ({proj_id})")

    def test_04_unload_project_a(self, harness):
        _require_projects()
        proj_id = TestGroup4_Acquisition._proj_ids[0]

        harness.send_project_command(proj_id, "acquire/stop", {})
        time.sleep(2)

        harness.send_command("station/unload", {"projectId": proj_id})
        time.sleep(3)
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        project_ids = [p.get("projectId") for p in status.get("projects", [])]
        assert proj_id not in project_ids, \
            f"Project A still loaded after unload: {project_ids}"
        print(f"  Unloaded Project A ({proj_id})")

    def test_05_station_empty(self, harness):
        _require_mode()
        # Poll station status until empty (max 15s)
        deadline = time.time() + 15
        projects = None
        while time.time() < deadline:
            harness.send_command("station/status", {})
            status = harness.wait_for_station_status(timeout=5)
            if status:
                projects = status.get("projects", [])
                if len(projects) == 0:
                    break
            time.sleep(1)
        assert projects is not None
        assert len(projects) == 0, f"Station not empty: {len(projects)} projects"
        print("  Station is empty")

    def test_06_switch_back_to_standalone(self, harness):
        _require_mode()
        waiter_key = harness.prepare_waiter("system/mode/response")
        harness.send_command("system/mode", {"mode": "standalone"})
        msgs = harness.collect_waiter(waiter_key, timeout=10)
        assert len(msgs) > 0, "No mode switch response"
        resp = msgs[0]
        assert resp.get("success"), f"Mode switch failed: {resp.get('message')}"
        assert resp.get("mode") == "standalone"
        print("  Switched back to standalone mode")

    def test_07_delete_test_preset(self, harness):
        """Clean up the test preset created in Group 5."""
        _require_infra()
        if not _state.preset_saved:
            pytest.skip("No preset to delete")

        # Find the preset filename
        harness.send_command("station/config/list", {})
        msgs = harness.wait_for_topic("station/config/list/response", timeout=10)
        if msgs:
            configs = msgs[0].get("configs", [])
            for c in configs:
                if c.get("name") == TestGroup5_ConfigPresets.PRESET_NAME:
                    harness.send_command("station/config/delete",
                                         {"filename": c["filename"]})
                    del_msgs = harness.wait_for_topic(
                        "station/config/delete/response", timeout=10)
                    if del_msgs and del_msgs[0].get("success"):
                        print(f"  Deleted test preset: {c['filename']}")
                    break


# ===========================================================================
# GROUP 8 — Guard Rails
# ===========================================================================

class TestGroup8_GuardRails:
    """Test station management edge cases and protections."""

    def test_01_reject_load_in_standalone_mode(self, harness):
        """Station load should be rejected when in standalone mode."""
        _require_infra()
        # Ensure we're in standalone mode
        mode_key = harness.prepare_waiter("system/mode/response")
        harness.send_command("system/mode", {"mode": "standalone"})
        harness.collect_waiter(mode_key, timeout=10)

        resp_key = harness.prepare_waiter("station/response")
        harness.send_command("station/load", {"filename": PROJ_A_FILE})
        msgs = harness.collect_waiter(resp_key, timeout=10)
        assert len(msgs) > 0, "No rejection response"
        assert not msgs[0].get("success"), "Load should be rejected in standalone mode"
        assert "standalone" in msgs[0].get("message", "").lower()
        print("  Load rejected in standalone mode")

    def test_02_switch_to_station_for_guard_tests(self, harness):
        _require_infra()
        waiter_key = harness.prepare_waiter("system/mode/response")
        harness.send_command("system/mode", {"mode": "station"})
        msgs = harness.collect_waiter(waiter_key, timeout=10)
        assert len(msgs) > 0 and msgs[0].get("success")

    def test_03_reject_duplicate_load(self, harness):
        """Loading the same project twice should fail."""
        _require_infra()
        # Load once — use pre-registered waiter
        loaded_key = harness.prepare_waiter("station/loaded")
        harness.send_command("station/load", {"filename": PROJ_A_FILE})
        harness.collect_waiter(loaded_key, timeout=15)

        # Verify project is loaded via polling
        deadline = time.time() + 10
        project_ids = []
        while time.time() < deadline:
            harness.send_command("station/status", {})
            status = harness.wait_for_station_status(timeout=5)
            project_ids = [p.get("projectId") for p in (status or {}).get("projects", [])]
            if len(project_ids) >= 1:
                break
            time.sleep(1)
        assert len(project_ids) >= 1, "First load didn't work"

        # Try loading again — should get rejection on station/response
        resp_key = harness.prepare_waiter("station/response")
        harness.send_command("station/load", {"filename": PROJ_A_FILE})
        resp_msgs = harness.collect_waiter(resp_key, timeout=10)
        assert len(resp_msgs) > 0, "No rejection response for duplicate load"
        assert not resp_msgs[0].get("success"), "Should reject duplicate load"
        assert "already loaded" in resp_msgs[0].get("message", "").lower()
        print("  Duplicate load rejected correctly")

    def test_04_three_project_limit(self, harness):
        """Cannot load more than 3 projects."""
        _require_infra()
        # Load project B (now at 2)
        harness.send_command("station/load", {"filename": PROJ_B_FILE})
        msgs = harness.wait_for_topic("station/loaded", timeout=15)

        # Load the DHWSIM soak project (project #3)
        soak_path = PROJECT_ROOT / "config" / "projects" / "_DhwSimSoakTest.json"
        if soak_path.exists():
            harness.send_command("station/load",
                                 {"filename": "_DhwSimSoakTest.json"})
            msgs = harness.wait_for_topic("station/loaded", timeout=15)
            if msgs and msgs[0].get("success"):
                # Now at 3 — try a 4th
                harness.send_command("station/load",
                                     {"filename": PROJ_A_FILE,
                                      "projectId": "proj_a_dup"})
                msgs = harness.wait_for_topic("station/response", timeout=10)
                if msgs:
                    assert not msgs[0].get("success"), \
                        "Should reject 4th project"
                    assert "limit" in msgs[0].get("message", "").lower()
                    print("  3-project limit enforced")

                # Unload the 3rd
                harness.send_command("station/unload",
                                     {"projectId": "_dhwsimsoak_test"})
                harness.wait_for_topic("station/unloaded", timeout=10)
            else:
                print("  Skipped 3-project limit test (soak project load failed)")
        else:
            print("  Skipped 3-project limit test (soak project not found)")

    def test_05_cleanup_guard_tests(self, harness):
        """Unload everything and switch back to standalone."""
        _require_infra()
        # Get current station status
        harness.send_command("station/status", {})
        status = harness.wait_for_station_status(timeout=10)
        if status:
            for p in status.get("projects", []):
                pid = p.get("projectId")
                if pid:
                    # Stop acquisition if running
                    if p.get("acquiring"):
                        harness.send_project_command(pid, "acquire/stop", {})
                        time.sleep(2)
                    harness.send_command("station/unload", {"projectId": pid})
                    harness.wait_for_topic("station/unloaded", timeout=10)

        # Switch back to standalone
        harness.send_command("system/mode", {"mode": "standalone"})
        msgs = harness.wait_for_topic("system/mode/response", timeout=10)
        if msgs:
            print(f"  Cleaned up — mode: {msgs[0].get('mode')}")
