#!/usr/bin/env python3
"""
cRIO Acquisition Test Runner

Mirrors start_services.py: kill previous → setup → start Mosquitto + DAQ →
run pytest against real cRIO hardware → cleanup.

Usage:
    python scripts/run_acquisition_tests.py              # Run all tests
    python scripts/run_acquisition_tests.py -k "Group1"  # Run specific group
    python scripts/run_acquisition_tests.py --deploy-first  # Deploy before test
    python scripts/run_acquisition_tests.py --tb=short   # Pass pytest args
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Project root is parent of scripts/
ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / "venv" / "Scripts" / "python.exe")
MOSQUITTO = Path(r"C:\Program Files\mosquitto\mosquitto.exe")
VENDOR_MOSQUITTO = ROOT / "vendor" / "mosquitto" / "mosquitto.exe"
MOSQUITTO_CONF = ROOT / "config" / "mosquitto.conf"
CRED_FILE = ROOT / "config" / "mqtt_credentials.json"
TLS_CA = ROOT / "config" / "tls" / "ca.crt"
TEST_FILE = ROOT / "tests" / "test_crio_acquisition.py"

CREATE_NO_WINDOW = 0x08000000

# Track processes we started
_processes: list = []

# ── Utilities ─────────────────────────────────────────────────────────────────

def log(tag: str, msg: str):
    print(f"  [{tag}] {msg}")

def is_port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False

def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(port):
            return True
        time.sleep(0.3)
    return False

def load_mqtt_credentials() -> dict:
    if not CRED_FILE.exists():
        return {}
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return {
            "MQTT_USERNAME": creds["backend"]["username"],
            "MQTT_PASSWORD": creds["backend"]["password"],
        }
    except Exception as e:
        log("CREDS", f"Warning: could not read credentials: {e}")
        return {}

# ── Process Management (mirrors start_services.py kill_previous) ─────────────

def kill_previous():
    """Kill previous DAQ service processes. Keep Mosquitto alive so cRIO stays connected."""
    log("CLEANUP", "Killing stale DAQ processes...")

    # Kill Python processes running our services (NOT Mosquitto — cRIO is connected to it)
    killed = 0
    try:
        import psutil
        my_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["pid"] == my_pid:
                continue
            try:
                name = (proc.info["name"] or "").lower()
                if name not in ("python.exe", "python3.exe", "python"):
                    continue
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if any(s in cmdline for s in [
                    "daq_service.py", "daq_service\\daq_service",
                    "watchdog.py",
                ]):
                    log("CLEANUP", f"  Killing PID {proc.info['pid']}: {cmdline[:80]}")
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass

    if killed:
        log("CLEANUP", f"  Killed {killed} stale process(es)")
        time.sleep(2)

    log("CLEANUP", "Done.")

# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_credentials():
    """Ensure MQTT credentials exist (idempotent)."""
    log("SETUP", "Checking MQTT credentials...")
    result = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "mqtt_credentials.py")],
        cwd=str(ROOT), capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to generate MQTT credentials!")
        print(result.stderr)
        sys.exit(1)
    log("SETUP", "MQTT credentials OK")

def setup_tls():
    """Generate TLS certificates if missing."""
    if TLS_CA.exists():
        log("SETUP", "TLS certificates OK")
        return
    log("SETUP", "Generating TLS certificates...")
    result = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "generate_tls_certs.py")],
        cwd=str(ROOT), capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: TLS certificate generation failed!")
        print(result.stderr)
        sys.exit(1)
    log("SETUP", "TLS certificates generated")

# ── Service Starters (mirrors start_services.py but headless) ────────────────

def start_mosquitto():
    """Start Mosquitto MQTT broker if not already running (headless).

    Reuses existing Mosquitto so the cRIO stays connected — avoids
    the 60-120s reconnect backoff penalty from paho-mqtt.
    """
    if is_port_open(1883):
        log("MOSQUITTO", "Already running on port 1883 (cRIO stays connected)")
        if is_port_open(8883):
            log("MOSQUITTO", "TLS on port 8883 OK")
        return

    mosquitto_exe = None
    if VENDOR_MOSQUITTO.exists():
        mosquitto_exe = str(VENDOR_MOSQUITTO)
    elif MOSQUITTO.exists():
        mosquitto_exe = str(MOSQUITTO)
    else:
        print("ERROR: Mosquitto not found!")
        print(f"  Checked: {VENDOR_MOSQUITTO}")
        print(f"  Checked: {MOSQUITTO}")
        sys.exit(1)

    log("MOSQUITTO", "Starting MQTT broker...")
    proc = subprocess.Popen(
        [mosquitto_exe, "-v", "-c", str(MOSQUITTO_CONF)],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _processes.append(proc)

    if wait_for_port(1883, timeout=5):
        log("MOSQUITTO", "Ready on port 1883")
    else:
        log("MOSQUITTO", "WARNING: Port 1883 not responding after 5s")

    if wait_for_port(8883, timeout=3):
        log("MOSQUITTO", "TLS ready on port 8883")
    else:
        log("MOSQUITTO", "WARNING: TLS port 8883 not responding")

def start_daq_service(mqtt_env: dict):
    """Start DAQ service (headless)."""
    log("DAQ", "Starting DAQ Service...")
    full_env = os.environ.copy()
    full_env.update(mqtt_env)

    import tempfile
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = tempfile.NamedTemporaryFile(
        prefix="daq_acq_test_", suffix=".log", delete=False, mode="w",
        dir=str(log_dir),
    )

    proc = subprocess.Popen(
        [PYTHON, "services\\daq_service\\daq_service.py", "-c", "config\\system.ini"],
        env=full_env,
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    _processes.append(proc)

    # Wait for DAQ to start publishing status.
    # IMPORTANT: Skip retained messages (retain=True) — they may be stale from
    # a previous DAQ instance that is no longer running. Wait for a FRESH
    # (non-retained) status message to confirm the DAQ is actually alive.
    log("DAQ", "Waiting for DAQ service to come online...")
    import threading
    try:
        import paho.mqtt.client as mqtt

        ready = threading.Event()
        probe = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"daq-startup-probe-{int(time.time())}",
        )
        creds = load_mqtt_credentials()
        if creds:
            probe.username_pw_set(creds["MQTT_USERNAME"], creds["MQTT_PASSWORD"])

        def on_message(client, userdata, msg):
            # Skip retained messages — they may be stale
            if msg.retain:
                return
            try:
                payload = json.loads(msg.payload.decode())
                if payload.get("node_type") == "daq":
                    ready.set()
            except Exception:
                pass

        probe.on_message = on_message
        probe.connect("127.0.0.1", 1883, keepalive=10)
        probe.loop_start()
        probe.subscribe("nisystem/+/+/status/system", qos=1)

        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                probe.loop_stop()
                probe.disconnect()
                output = ""
                try:
                    with open(log_file.name) as f:
                        output = f.read()[-2000:]
                except Exception:
                    pass
                print(f"ERROR: DAQ service exited (code {proc.returncode})")
                print(output)
                sys.exit(1)
            if ready.wait(timeout=1.0):
                break

        probe.loop_stop()
        probe.disconnect()

        if ready.is_set():
            log("DAQ", f"Online (PID {proc.pid})")
        else:
            log("DAQ", "WARNING: DAQ service not responding after 30s")
    except Exception as e:
        log("DAQ", f"Probe error: {e} — waiting 10s fallback")
        time.sleep(10)
        if proc.poll() is not None:
            print(f"ERROR: DAQ service exited (code {proc.returncode})")
            sys.exit(1)
        log("DAQ", f"Started (PID {proc.pid})")

# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup():
    """Stop services we started (reverse order). Leave Mosquitto for cRIO."""
    log("CLEANUP", "Stopping services...")

    for proc in reversed(_processes):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except OSError:
            pass

    # Kill any orphaned DAQ processes
    try:
        import psutil
        my_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["pid"] == my_pid:
                continue
            try:
                name = (proc.info["name"] or "").lower()
                if name not in ("python.exe", "python3.exe", "python"):
                    continue
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if "daq_service.py" in cmdline or "daq_service\\daq_service" in cmdline:
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass

    log("CLEANUP", "Done.")

# ── Deploy (optional) ─────────────────────────────────────────────────────────

def deploy_crio():
    """Run deploy_crio.py before testing."""
    log("DEPLOY", "Deploying to cRIO...")
    result = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "deploy_crio.py")],
        cwd=str(ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        print("ERROR: cRIO deploy failed!")
        sys.exit(1)
    log("DEPLOY", "Deploy complete. Waiting for cRIO to restart...")
    time.sleep(10)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.chdir(str(ROOT))

    # Parse our flags (pass rest to pytest)
    deploy_first = "--deploy-first" in sys.argv
    pytest_args = [a for a in sys.argv[1:] if a != "--deploy-first"]

    print()
    print("=" * 72)
    print("  NISystem — cRIO Acquisition Tests")
    print("=" * 72)
    print()

    # Preflight
    if not Path(PYTHON).exists():
        print("ERROR: Python virtual environment not found!")
        print(f"  Expected: {PYTHON}")
        sys.exit(1)

    if not TEST_FILE.exists():
        print(f"ERROR: Test file not found: {TEST_FILE}")
        sys.exit(1)

    try:
        # Step 1: Clean slate (same as start_services.py)
        kill_previous()
        print()

        # Step 2: Setup credentials and TLS (idempotent)
        setup_credentials()
        setup_tls()
        mqtt_env = load_mqtt_credentials()
        print()

        # Step 3: Optional deploy
        if deploy_first:
            deploy_crio()
            print()

        # Step 4: Start services (reuse Mosquitto if running, start DAQ fresh)
        start_mosquitto()
        start_daq_service(mqtt_env)
        print()

        # Step 5: Run pytest
        log("TESTS", "Running cRIO acquisition tests...")
        print()

        cmd = [PYTHON, "-m", "pytest", str(TEST_FILE), "-v"] + pytest_args
        result = subprocess.run(cmd, cwd=str(ROOT))

        print()
        print("=" * 72)
        if result.returncode == 0:
            print("  ALL TESTS PASSED")
        else:
            print(f"  TESTS FAILED (exit code {result.returncode})")
        print("=" * 72)
        print()

        return result.returncode

    finally:
        cleanup()

if __name__ == "__main__":
    sys.exit(main())
