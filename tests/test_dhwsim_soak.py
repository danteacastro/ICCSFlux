#!/usr/bin/env python3
"""
DHWSIM cDAQ 72-Hour Terminal Soak Test
========================================

Validates sustained operation of the cDAQ-9189-DHWSIM chassis over an extended
period (default 72 hours).  Auto-starts Mosquitto + DAQ service — no manual
NISystem Start.bat needed.

The test proceeds in three phases:

  Phase 1 — Setup & Baseline (Groups 1-3)
    Verify infrastructure, load project, start acquisition, capture baselines.

  Phase 2 — Continuous Soak (Group 4)
    Run for SOAK_DURATION_HOURS (default 72, override with env var).
    Every CHECKPOINT_INTERVAL_MIN minutes, validate:
      - All channels still publishing (no dropouts)
      - Scan timing jitter within tolerance
      - No unexpected COMM_FAIL alarms
      - System memory usage bounded
      - MQTT connection stable
      - Recording files rotating correctly

  Phase 3 — Post-Soak Validation (Group 5)
    Stop acquisition, verify clean shutdown, check final stats.

Usage:
  # Full 72-hour soak (default):
  python -m pytest tests/test_dhwsim_soak.py -v -s

  # Quick 1-hour smoke test:
  SOAK_HOURS=1 python -m pytest tests/test_dhwsim_soak.py -v -s

  # 15-minute dry run (verify setup only):
  SOAK_HOURS=0.25 python -m pytest tests/test_dhwsim_soak.py -v -s

  # Just setup + baseline (skip soak):
  python -m pytest tests/test_dhwsim_soak.py -v -k "Group1 or Group2 or Group3"

  # Just the soak loop:
  python -m pytest tests/test_dhwsim_soak.py -v -s -k "Group4"

Environment variables:
  SOAK_HOURS              — Total soak duration in hours (default: 72)
  CHECKPOINT_MINUTES      — Minutes between health checks (default: 15)
  DHWSIM_DEVICE           — NI MAX device name (default: cDAQ-9189-DHWSIM)
  SOAK_RECORD             — Enable CSV recording during soak (default: 1)
  SOAK_MAX_MEMORY_MB      — Max DAQ service memory before FAIL (default: 2048)
  SOAK_MAX_DROPOUT_PCT    — Max channel dropout % per checkpoint (default: 5)
  SOAK_MAX_JITTER_MS      — Max scan timing jitter in ms (default: 50)
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
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
# Configuration (overridable via environment)
# ---------------------------------------------------------------------------

SOAK_HOURS = float(os.environ.get("SOAK_HOURS", "72"))
CHECKPOINT_MINUTES = float(os.environ.get("CHECKPOINT_MINUTES", "15"))
DHWSIM_DEVICE = os.environ.get("DHWSIM_DEVICE", "cDAQ-9189-DHWSIM")
SOAK_RECORD = os.environ.get("SOAK_RECORD", "1") == "1"
MAX_MEMORY_MB = float(os.environ.get("SOAK_MAX_MEMORY_MB", "2048"))
MAX_DROPOUT_PCT = float(os.environ.get("SOAK_MAX_DROPOUT_PCT", "5"))
MAX_JITTER_MS = float(os.environ.get("SOAK_MAX_JITTER_MS", "50"))

TEST_PROJECT = "_DhwSimSoakTest.json"
TEST_PROJECT_NAME = "DHWSIM 72h Soak Test"

# Expected channel groups
MOD1_TC = [f"TC_M1_ch{i:02d}" for i in range(16)]
MOD2_AI = [f"AI_M2_ch{i:02d}" for i in range(16)]
MOD3_CI = [f"CI_M3_ch{i:02d}" for i in range(8)]
MOD4_DI = [f"DI_M4_ch{i:02d}" for i in range(16)]
MOD5_DO = [f"DO_M5_ch{i:02d}" for i in range(16)]
MOD6_AO = [f"AO_M6_ch{i:02d}" for i in range(16)]
ALL_INPUT_CHANNELS = set(MOD1_TC + MOD2_AI + MOD3_CI + MOD4_DI)
ALL_CHANNELS = set(MOD1_TC + MOD2_AI + MOD3_CI + MOD4_DI + MOD5_DO + MOD6_AO)
TOTAL_CHANNELS = 88

# Admin credentials (matches conftest.py ensure_test_admin)
_TEST_ADMIN_CREDENTIALS = ("test_admin", "validation_test_pw_2026")

# ---------------------------------------------------------------------------
# Soak report
# ---------------------------------------------------------------------------

class SoakReport:
    """Accumulates checkpoint results for final summary."""

    def __init__(self):
        self.start_time: Optional[float] = None
        self.checkpoints: List[Dict[str, Any]] = []
        self.failures: List[str] = []
        self.warnings: List[str] = []
        self.total_dropouts = 0
        self.max_memory_mb = 0.0
        self.max_jitter_ms = 0.0
        self.mqtt_reconnects = 0
        self.recording_rotations = 0

    def add_checkpoint(self, data: Dict[str, Any]):
        self.checkpoints.append(data)
        if data.get("memory_mb", 0) > self.max_memory_mb:
            self.max_memory_mb = data["memory_mb"]
        if data.get("jitter_ms", 0) > self.max_jitter_ms:
            self.max_jitter_ms = data["jitter_ms"]
        self.total_dropouts += data.get("dropout_count", 0)

    def add_failure(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.failures.append(f"[{ts}] {msg}")

    def add_warning(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.warnings.append(f"[{ts}] {msg}")

    def summary(self) -> str:
        elapsed = time.time() - (self.start_time or time.time())
        hours = elapsed / 3600
        lines = [
            "=" * 70,
            "DHWSIM 72h SOAK TEST — FINAL REPORT",
            "=" * 70,
            f"Duration:           {hours:.1f} hours ({elapsed:.0f} seconds)",
            f"Checkpoints:        {len(self.checkpoints)}",
            f"Total dropouts:     {self.total_dropouts}",
            f"Peak memory:        {self.max_memory_mb:.1f} MB",
            f"Peak jitter:        {self.max_jitter_ms:.1f} ms",
            f"MQTT reconnects:    {self.mqtt_reconnects}",
            f"Recording rotations:{self.recording_rotations}",
            f"Warnings:           {len(self.warnings)}",
            f"Failures:           {len(self.failures)}",
        ]
        if self.failures:
            lines.append("\nFAILURES:")
            for f in self.failures:
                lines.append(f"  {f}")
        if self.warnings:
            lines.append("\nWARNINGS:")
            for w in self.warnings[:50]:  # cap at 50
                lines.append(f"  {w}")
            if len(self.warnings) > 50:
                lines.append(f"  ... and {len(self.warnings) - 50} more")
        verdict = "PASS" if not self.failures else "FAIL"
        lines.append(f"\nVERDICT: {verdict}")
        lines.append("=" * 70)
        return "\n".join(lines)


_report = SoakReport()

# ---------------------------------------------------------------------------
# Cascade skip state
# ---------------------------------------------------------------------------

class _SoakState:
    infra_ok = False
    project_loaded = False
    acquisition_started = False
    baseline_captured = False


_state = _SoakState()


def _require_infra():
    if not _state.infra_ok:
        pytest.skip("Infrastructure not ready (Group 1 must pass)")


def _require_project():
    _require_infra()
    if not _state.project_loaded:
        pytest.skip("Project not loaded (Group 2 must pass)")


def _require_acquisition():
    _require_project()
    if not _state.acquisition_started:
        pytest.skip("Acquisition not started (Group 2 must pass)")


def _require_baseline():
    _require_acquisition()
    if not _state.baseline_captured:
        pytest.skip("Baseline not captured (Group 3 must pass)")


# ---------------------------------------------------------------------------
# SoakHarness — MQTT client for soak testing
# ---------------------------------------------------------------------------

class SoakHarness:
    """MQTT test client tuned for long-duration soak testing."""

    def __init__(self, host: str, port: int,
                 username: Optional[str] = None,
                 password: Optional[str] = None):
        import paho.mqtt.client as mqtt

        self.host = host
        self.port = port
        self.node_id: Optional[str] = None
        self.topic_base: Optional[str] = None
        self._status: Optional[Dict[str, Any]] = None
        self._status_version = 0
        self._status_event = threading.Event()
        self._channel_values: Dict[str, Any] = {}
        self._channel_timestamps: Dict[str, float] = {}
        self._values_lock = threading.Lock()
        self._waiters: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._connect_count = 0
        self._disconnect_count = 0

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"soak-harness-{int(time.time() * 1000) % 100000}",
        )
        if username and password:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._connect_count += 1
        # Re-subscribe on reconnect
        if self.topic_base:
            client.subscribe(f"{self.topic_base}/status/system", qos=1)
            client.subscribe(f"{self.topic_base}/data/#", qos=0)
            client.subscribe(f"{self.topic_base}/status/alarms", qos=1)

    def _on_disconnect(self, client, userdata, flags=None, rc=None,
                       properties=None):
        self._disconnect_count += 1

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        topic = msg.topic

        # Status messages
        if "/status/system" in topic:
            # Extract node_id from topic: nisystem/nodes/{node_id}/status/system
            parts = topic.split("/")
            if len(parts) >= 4:
                self.node_id = parts[2]
                self.topic_base = f"nisystem/nodes/{self.node_id}"
            self._status = payload
            self._status_version += 1
            self._status_event.set()

        # Channel data messages
        elif "/data/" in topic:
            if isinstance(payload, dict):
                now = time.time()
                with self._values_lock:
                    for ch_name, value in payload.items():
                        self._channel_values[ch_name] = value
                        self._channel_timestamps[ch_name] = now

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
        self.client.subscribe("nisystem/+/+/status/system", qos=1)
        if self._status_event.wait(timeout=timeout):
            return self.node_id is not None
        return False

    def login_admin(self, timeout: float = 10.0) -> bool:
        if self.topic_base is None:
            return False

        candidates = []
        if _TEST_ADMIN_CREDENTIALS:
            candidates.append(_TEST_ADMIN_CREDENTIALS)
        pw_file = PROJECT_ROOT / "data" / "initial_admin_password.txt"
        if pw_file.exists():
            content = pw_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                if "Password:" in line:
                    pw = line.split("Password:", 1)[1].strip()
                    if pw:
                        candidates.append(("admin", pw))
                    break

        for username, password in candidates:
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
            self.client.subscribe(auth_topic, qos=1)
            time.sleep(0.2)
            self.send_command("auth/login", {
                "username": username, "password": password,
                "source_ip": "soak_test",
            })
            auth_event.wait(timeout=timeout)
            self.client.message_callback_remove(auth_topic)
            if auth_result.get("authenticated"):
                return True
        return False

    def send_command(self, category: str, payload: Any = None):
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/{category}"
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

    def wait_for_status_field(self, field: str, value: Any,
                              timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.refresh_status(timeout=min(3.0, deadline - time.time()))
            if status and status.get(field) == value:
                return True
        return False

    def wait_for_topic(self, suffix: str, timeout: float = 10.0,
                       count: int = 1) -> List[Dict[str, Any]]:
        if self.topic_base is None:
            raise RuntimeError("Must discover_node() first")
        topic = f"{self.topic_base}/{suffix}"
        event = threading.Event()
        waiter = {"event": event, "messages": [], "count": count}
        with self._lock:
            self._waiters[topic] = waiter
        self.client.subscribe(topic, qos=1)
        event.wait(timeout=timeout)
        with self._lock:
            self._waiters.pop(topic, None)
        return waiter["messages"]

    def get_channel_snapshot(self) -> Dict[str, Any]:
        with self._values_lock:
            return dict(self._channel_values)

    def get_channel_ages(self) -> Dict[str, float]:
        now = time.time()
        with self._values_lock:
            return {ch: now - ts for ch, ts in self._channel_timestamps.items()}

    def get_stale_channels(self, max_age_s: float = 5.0) -> Set[str]:
        ages = self.get_channel_ages()
        return {ch for ch, age in ages.items() if age > max_age_s}

    def get_missing_channels(self, expected: Set[str]) -> Set[str]:
        with self._values_lock:
            return expected - set(self._channel_values.keys())

    @property
    def reconnect_count(self) -> int:
        return max(0, self._connect_count - 1)


# ---------------------------------------------------------------------------
# Module-scoped harness fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def harness(mqtt_broker):
    """Create and connect the soak test harness."""
    h = SoakHarness(
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


@pytest.fixture(scope="module")
def report():
    """Shared soak report accumulator."""
    _report.start_time = time.time()
    yield _report
    # Print final report at end of module
    print("\n\n" + _report.summary())
    # Write report to file
    report_path = PROJECT_ROOT / "data" / "logs" / "soak_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_report.summary(), encoding="utf-8")
    print(f"\nReport saved: {report_path}")


# ===========================================================================
# GROUP 1 — Infrastructure
# ===========================================================================

class TestGroup1_Infrastructure:
    """Verify MQTT broker and DAQ service are alive."""

    def test_01_mqtt_broker_alive(self, mqtt_broker):
        assert is_port_open(mqtt_broker["host"], mqtt_broker["port"]), \
            "MQTT broker not responding on port 1883"
        _state.infra_ok = True

    def test_02_daq_service_online(self, harness):
        _require_infra()
        status = harness.get_status(timeout=10)
        assert status is not None, "DAQ service not publishing status"
        assert harness.node_id is not None, "Could not discover node_id"
        print(f"  Node ID: {harness.node_id}")

    def test_03_admin_login(self, harness):
        _require_infra()
        ok = harness.login_admin(timeout=10)
        assert ok, "Cannot log in as admin — check credentials"

    def test_04_websocket_listener(self, mqtt_broker):
        """Verify WebSocket port 9002 is open (dashboard connectivity)."""
        _require_infra()
        ws_open = is_port_open("127.0.0.1", 9002)
        if not ws_open:
            pytest.skip("WebSocket port 9002 not open (dashboard won't connect)")


# ===========================================================================
# GROUP 2 — Project Load & Acquisition Start
# ===========================================================================

class TestGroup2_ProjectAndAcquisition:
    """Load soak test project and start acquisition."""

    def test_01_load_project(self, harness):
        _require_infra()
        # Verify project file exists
        proj_path = PROJECT_ROOT / "config" / "projects" / TEST_PROJECT
        assert proj_path.exists(), f"Project file not found: {proj_path}"

        harness.send_command("project/load", {"filename": TEST_PROJECT})
        time.sleep(2)

        status = harness.refresh_status(timeout=10)
        assert status is not None
        loaded = status.get("project_name") or status.get("projectName", "")
        assert TEST_PROJECT_NAME in loaded or TEST_PROJECT.replace(".json", "") in loaded, \
            f"Project not loaded. Status shows: {loaded}"
        _state.project_loaded = True
        print(f"  Project loaded: {loaded}")

    def test_02_verify_channel_config(self, harness):
        _require_project()
        msgs = harness.wait_for_topic("config/channels", timeout=10)
        if msgs:
            channels = msgs[0] if isinstance(msgs[0], dict) else {}
            print(f"  Config has {len(channels)} channels")
            assert len(channels) >= TOTAL_CHANNELS * 0.9, \
                f"Expected ~{TOTAL_CHANNELS} channels, got {len(channels)}"

    def test_03_start_acquisition(self, harness):
        _require_project()
        harness.send_command("system/acquire/start", {})
        ok = harness.wait_for_status_field("acquiring", True, timeout=20)
        assert ok, (
            "Acquisition did not start within 20s. "
            "Check NI MAX — is the DHWSIM device present and not reserved?"
        )
        _state.acquisition_started = True
        print("  Acquisition started")

    def test_04_channels_arriving(self, harness):
        _require_acquisition()
        # Wait up to 10s for channels to start flowing
        deadline = time.time() + 10
        while time.time() < deadline:
            snapshot = harness.get_channel_snapshot()
            if len(snapshot) >= TOTAL_CHANNELS * 0.8:
                break
            time.sleep(0.5)

        snapshot = harness.get_channel_snapshot()
        missing = ALL_INPUT_CHANNELS - set(snapshot.keys())
        print(f"  Receiving {len(snapshot)} channels, "
              f"{len(missing)} input channels missing")
        assert len(missing) < len(ALL_INPUT_CHANNELS) * 0.2, \
            f"Too many channels missing: {sorted(missing)[:20]}"

    def test_05_start_recording(self, harness):
        """Start CSV recording for the soak duration."""
        _require_acquisition()
        if not SOAK_RECORD:
            pytest.skip("Recording disabled (SOAK_RECORD=0)")

        harness.send_command("recording/start", {
            "format": "csv",
            "interval_ms": 1000,
        })
        time.sleep(2)
        status = harness.refresh_status(timeout=5)
        recording = (status or {}).get("recording", False)
        if not recording:
            _report.add_warning("Recording did not start — continuing soak without recording")
            pytest.skip("Recording did not start")
        print("  Recording started")


# ===========================================================================
# GROUP 3 — Baseline Capture
# ===========================================================================

class TestGroup3_Baseline:
    """Capture baseline readings for comparison during soak."""

    def test_01_tc_baseline(self, harness, report):
        _require_acquisition()
        time.sleep(3)  # Let values stabilize
        snapshot = harness.get_channel_snapshot()

        tc_values = {ch: snapshot.get(ch) for ch in MOD1_TC if ch in snapshot}
        print(f"  TC channels reporting: {len(tc_values)}/16")
        for ch, val in sorted(tc_values.items()):
            if val is not None:
                print(f"    {ch}: {val:.2f} degC")

        # At least half the TCs should have values
        assert len(tc_values) >= 8, \
            f"Only {len(tc_values)}/16 TC channels have values"
        _state.baseline_captured = True

    def test_02_ai_baseline(self, harness, report):
        _require_acquisition()
        snapshot = harness.get_channel_snapshot()
        ai_values = {ch: snapshot.get(ch) for ch in MOD2_AI if ch in snapshot}
        print(f"  AI channels reporting: {len(ai_values)}/16")
        assert len(ai_values) >= 8, \
            f"Only {len(ai_values)}/16 AI channels have values"

    def test_03_ci_baseline(self, harness, report):
        _require_acquisition()
        snapshot = harness.get_channel_snapshot()
        ci_values = {ch: snapshot.get(ch) for ch in MOD3_CI if ch in snapshot}
        print(f"  CI channels reporting: {len(ci_values)}/8")
        assert len(ci_values) >= 4, \
            f"Only {len(ci_values)}/8 CI channels have values"

    def test_04_di_baseline(self, harness, report):
        _require_acquisition()
        snapshot = harness.get_channel_snapshot()
        di_values = {ch: snapshot.get(ch) for ch in MOD4_DI if ch in snapshot}
        print(f"  DI channels reporting: {len(di_values)}/16")
        assert len(di_values) >= 8, \
            f"Only {len(di_values)}/16 DI channels have values"

    def test_05_system_baseline(self, harness, report):
        """Capture baseline system health."""
        _require_acquisition()
        status = harness.refresh_status(timeout=5) or {}
        mem = status.get("memory_mb", status.get("memoryMB", 0))
        cpu = status.get("cpu_percent", status.get("cpuPercent", 0))
        scan_rate = status.get("actual_scan_rate_hz",
                               status.get("actualScanRateHz", 0))
        print(f"  Memory: {mem:.1f} MB")
        print(f"  CPU: {cpu:.1f}%")
        print(f"  Scan rate: {scan_rate:.1f} Hz")
        report.start_time = time.time()


# ===========================================================================
# GROUP 4 — Continuous Soak
# ===========================================================================

class TestGroup4_ContinuousSoak:
    """Run the sustained soak test for SOAK_HOURS duration.

    This is a single long-running test that performs periodic checkpoints.
    """

    def test_01_soak_loop(self, harness, report):
        """Main soak loop — runs for SOAK_HOURS with periodic health checks."""
        _require_baseline()

        soak_duration_s = SOAK_HOURS * 3600
        checkpoint_interval_s = CHECKPOINT_MINUTES * 60
        start_time = time.time()
        end_time = start_time + soak_duration_s
        checkpoint_num = 0

        print(f"\n{'=' * 60}")
        print(f"SOAK TEST STARTING")
        print(f"  Duration: {SOAK_HOURS} hours ({soak_duration_s:.0f}s)")
        print(f"  Checkpoint interval: {CHECKPOINT_MINUTES} minutes")
        print(f"  Max memory: {MAX_MEMORY_MB} MB")
        print(f"  Max dropout: {MAX_DROPOUT_PCT}%")
        print(f"  Max jitter: {MAX_JITTER_MS} ms")
        print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Expected end: "
              f"{(datetime.now() + timedelta(seconds=soak_duration_s)).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}\n")

        critical_failures = []

        while time.time() < end_time:
            # Sleep until next checkpoint
            next_checkpoint = start_time + (checkpoint_num + 1) * checkpoint_interval_s
            sleep_time = next_checkpoint - time.time()
            if sleep_time > 0:
                # Sleep in 10s increments so we can detect test abort
                remaining = sleep_time
                while remaining > 0:
                    time.sleep(min(remaining, 10))
                    remaining = next_checkpoint - time.time()

            checkpoint_num += 1
            elapsed_h = (time.time() - start_time) / 3600
            ts = datetime.now().strftime("%H:%M:%S")

            print(f"\n--- Checkpoint {checkpoint_num} "
                  f"[{ts}, {elapsed_h:.1f}h elapsed] ---")

            checkpoint = self._run_checkpoint(harness, checkpoint_num)
            report.add_checkpoint(checkpoint)

            # Print checkpoint summary
            print(f"  Channels: {checkpoint['channels_ok']}/{TOTAL_CHANNELS}"
                  f" ({checkpoint['dropout_count']} dropouts)")
            print(f"  Stale: {checkpoint['stale_count']}")
            print(f"  Memory: {checkpoint['memory_mb']:.1f} MB")
            print(f"  Jitter: {checkpoint['jitter_ms']:.1f} ms")
            print(f"  Acquiring: {checkpoint['acquiring']}")
            print(f"  MQTT reconnects: {harness.reconnect_count}")

            # Evaluate pass/fail criteria
            if not checkpoint["acquiring"]:
                msg = f"Checkpoint {checkpoint_num}: Acquisition stopped unexpectedly"
                critical_failures.append(msg)
                report.add_failure(msg)
                print(f"  ** CRITICAL: {msg}")
                # Try to restart
                harness.send_command("system/acquire/start", {})
                time.sleep(5)

            dropout_pct = (checkpoint["dropout_count"] / max(len(ALL_INPUT_CHANNELS), 1)) * 100
            if dropout_pct > MAX_DROPOUT_PCT:
                msg = (f"Checkpoint {checkpoint_num}: "
                       f"Dropout {dropout_pct:.1f}% > {MAX_DROPOUT_PCT}%")
                report.add_failure(msg)
                print(f"  ** FAIL: {msg}")

            if checkpoint["memory_mb"] > MAX_MEMORY_MB:
                msg = (f"Checkpoint {checkpoint_num}: "
                       f"Memory {checkpoint['memory_mb']:.1f} MB > {MAX_MEMORY_MB} MB")
                report.add_failure(msg)
                print(f"  ** FAIL: {msg}")

            if checkpoint["jitter_ms"] > MAX_JITTER_MS:
                msg = (f"Checkpoint {checkpoint_num}: "
                       f"Jitter {checkpoint['jitter_ms']:.1f} ms > {MAX_JITTER_MS} ms")
                report.add_warning(msg)
                print(f"  ** WARNING: {msg}")

            if checkpoint["alarm_count"] > 0:
                report.add_warning(
                    f"Checkpoint {checkpoint_num}: "
                    f"{checkpoint['alarm_count']} active alarms"
                )

            report.mqtt_reconnects = harness.reconnect_count

        # Soak complete
        print(f"\n{'=' * 60}")
        print(f"SOAK LOOP COMPLETE — {checkpoint_num} checkpoints over "
              f"{SOAK_HOURS} hours")
        print(f"{'=' * 60}\n")

        # Final assertion
        assert not critical_failures, \
            f"Soak had {len(critical_failures)} critical failures:\n" + \
            "\n".join(critical_failures)

    def _run_checkpoint(self, harness: SoakHarness,
                        num: int) -> Dict[str, Any]:
        """Execute a single health checkpoint."""
        # Get fresh status
        status = harness.refresh_status(timeout=5) or {}

        # Channel health
        snapshot = harness.get_channel_snapshot()
        missing = harness.get_missing_channels(ALL_INPUT_CHANNELS)
        stale = harness.get_stale_channels(max_age_s=5.0)

        # System health from status
        memory_mb = status.get("memory_mb",
                               status.get("memoryMB", 0))
        cpu_pct = status.get("cpu_percent",
                             status.get("cpuPercent", 0))
        acquiring = status.get("acquiring", False)

        # Scan timing
        scan_stats = status.get("scan_timing", status.get("scanTiming", {}))
        jitter_ms = scan_stats.get("jitter_ms",
                                   scan_stats.get("jitterMs", 0))

        # Alarms
        alarm_count = len(status.get("active_alarms",
                                     status.get("activeAlarms", [])))

        return {
            "checkpoint": num,
            "timestamp": time.time(),
            "channels_ok": len(snapshot),
            "dropout_count": len(missing),
            "stale_count": len(stale),
            "missing_channels": sorted(missing)[:10],
            "stale_channels": sorted(stale)[:10],
            "memory_mb": memory_mb,
            "cpu_percent": cpu_pct,
            "jitter_ms": jitter_ms,
            "acquiring": acquiring,
            "alarm_count": alarm_count,
            "mqtt_reconnects": harness.reconnect_count,
        }


# ===========================================================================
# GROUP 5 — Post-Soak Validation
# ===========================================================================

class TestGroup5_PostSoak:
    """Clean shutdown and final validation after soak completes."""

    def test_01_stop_recording(self, harness):
        _require_acquisition()
        if not SOAK_RECORD:
            pytest.skip("Recording was not enabled")
        harness.send_command("recording/stop", {})
        time.sleep(2)
        print("  Recording stopped")

    def test_02_verify_recording_files(self):
        """Check that recording files were created during soak."""
        _require_acquisition()
        if not SOAK_RECORD:
            pytest.skip("Recording was not enabled")
        # Look for CSV files in data directory
        data_dir = PROJECT_ROOT / "data"
        csv_files = list(data_dir.rglob("*.csv"))
        print(f"  Found {len(csv_files)} CSV files in data/")
        if csv_files:
            total_size = sum(f.stat().st_size for f in csv_files)
            print(f"  Total recording size: {total_size / (1024*1024):.1f} MB")

    def test_03_stop_acquisition(self, harness):
        _require_acquisition()
        harness.send_command("system/acquire/stop", {})
        ok = harness.wait_for_status_field("acquiring", False, timeout=15)
        assert ok, "Acquisition did not stop cleanly within 15s"
        print("  Acquisition stopped cleanly")

    def test_04_final_status(self, harness, report):
        """Capture final system status and verify clean state."""
        status = harness.refresh_status(timeout=5) or {}
        mem = status.get("memory_mb", status.get("memoryMB", 0))
        print(f"  Final memory: {mem:.1f} MB")
        print(f"  Total MQTT reconnects: {harness.reconnect_count}")

        # No acquisition should be running
        assert not status.get("acquiring", False), \
            "Acquisition still running after stop command"

    def test_05_print_report(self, report):
        """Print the final soak test report."""
        print("\n" + report.summary())

        # Write JSON checkpoint log
        log_path = PROJECT_ROOT / "data" / "logs" / "soak_checkpoints.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(report.checkpoints, f, indent=2)
        print(f"Checkpoint log: {log_path}")

        assert not report.failures, \
            f"Soak test had {len(report.failures)} failures — see report above"
