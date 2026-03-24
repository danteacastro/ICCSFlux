#!/usr/bin/env python3
"""
NISystem Dev Launcher — starts all services in separate console windows.

Replaces the bat file startup. Credentials pass through subprocess.Popen(env=...),
never through CMD string parsing. Matches the portable exe's credential flow exactly.

Usage:
    python scripts/start_services.py          # Start all services
    python scripts/start_services.py --no-browser  # Skip opening browser
"""

import json
import logging
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
MOSQUITTO_CONF = ROOT / "config" / "mosquitto.conf"
CRED_FILE = ROOT / "config" / "mqtt_credentials.json"
TLS_CA = ROOT / "config" / "tls" / "ca.crt"

CREATE_NEW_CONSOLE = 0x00000010

# Track all launched processes for cleanup
_processes: list[subprocess.Popen] = []
_shutting_down = False
_station_manager = None

# Station manager (shared module)
try:
    from station_manager import StationManager
    HAS_STATION_MANAGER = True
except ImportError:
    HAS_STATION_MANAGER = False

# ── Utilities ──────────────────────────────────────────────────────────────────

def log(tag: str, msg: str):
    print(f"  [{tag}] {msg}")

def is_port_open(port: int) -> bool:
    """Check if a TCP port is accepting connections on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False

def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(port):
            return True
        time.sleep(0.3)
    return False

def load_mqtt_credentials() -> dict:
    """Load MQTT credentials from JSON. Returns env dict to merge."""
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

def load_mqtt_credentials_tuple():
    """Load MQTT credentials as (user, pass) tuple for station manager."""
    if not CRED_FILE.exists():
        return None, None
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds['backend']['username'], creds['backend']['password']
    except Exception:
        return None, None

# ── Process Management ─────────────────────────────────────────────────────────

def kill_previous():
    """Kill previous NISystem processes to allow clean restart."""
    log("CLEANUP", "Killing previous NISystem processes...")

    # Stop Mosquitto Windows Service if running
    subprocess.run(["net", "stop", "mosquitto"],
                   capture_output=True, creationflags=0x08000000)

    # Kill mosquitto by name
    subprocess.run(["taskkill", "/F", "/IM", "mosquitto.exe"],
                   capture_output=True, creationflags=0x08000000)

    # Kill Python processes running our services
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if any(s in cmdline for s in ["daq_service", "watchdog.py"]):
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass

    # Kill Vite on port 5173
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            creationflags=0x08000000)
        for line in result.stdout.splitlines():
            if ":5173" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, creationflags=0x08000000)
    except Exception:
        pass

    # Kill named windows
    for title in ["MQTT Broker", "DAQ Service", "Watchdog",
                   "Azure Uploader", "Frontend (Vite)"]:
        subprocess.run(
            ["taskkill", "/FI", f"WINDOWTITLE eq {title}*", "/F"],
            capture_output=True, creationflags=0x08000000)

    time.sleep(2)
    log("CLEANUP", "Done.")

def start_in_console(title: str, command: list[str], env: dict = None,
                     cwd: str = None) -> subprocess.Popen:
    """Start a process in its own visible console window.

    Credentials are passed via the env dict — CMD never touches them.
    No CMD wrapper — the process runs directly with CREATE_NEW_CONSOLE.
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    proc = subprocess.Popen(
        command,
        env=full_env,
        cwd=cwd or str(ROOT),
        creationflags=CREATE_NEW_CONSOLE,
    )
    _processes.append(proc)
    return proc

# ── Setup ──────────────────────────────────────────────────────────────────────

def setup_credentials():
    """Ensure MQTT credentials exist (idempotent)."""
    log("SETUP", "Checking MQTT credentials...")
    result = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "mqtt_credentials.py")],
        cwd=str(ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: Failed to generate MQTT credentials!")
        print(result.stderr)
        sys.exit(1)
    for line in result.stdout.strip().splitlines():
        log("MQTT", line)

def setup_tls():
    """Generate TLS certificates if missing."""
    if TLS_CA.exists():
        log("SETUP", "TLS certificates OK")
        return
    log("SETUP", "Generating TLS certificates...")
    result = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "generate_tls_certs.py")],
        cwd=str(ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: TLS certificate generation failed!")
        print(result.stderr)
        sys.exit(1)
    log("SETUP", "TLS certificates generated")

# ── Service Starters ───────────────────────────────────────────────────────────

def start_mosquitto() -> subprocess.Popen:
    """Start Mosquitto MQTT broker."""
    log("MOSQUITTO", "Starting MQTT broker...")
    if not MOSQUITTO.exists():
        log("MOSQUITTO", f"ERROR: Not found at {MOSQUITTO}")
        sys.exit(1)

    proc = start_in_console("MQTT Broker", [
        str(MOSQUITTO), "-v", "-c", str(MOSQUITTO_CONF),
    ])

    if wait_for_port(1883, timeout=5):
        log("MOSQUITTO", "Ready on port 1883")
    else:
        log("MOSQUITTO", "WARNING: Port 1883 not responding after 5s")

    return proc

def start_daq_service(mqtt_env: dict) -> subprocess.Popen:
    """Start DAQ Service with MQTT credentials in environment."""
    log("DAQ", "Starting DAQ Service...")
    proc = start_in_console("DAQ Service", [
        PYTHON, "services\\daq_service\\daq_service.py", "-c", "config\\system.ini",
    ], env=mqtt_env)
    time.sleep(2)
    if proc.poll() is not None:
        log("DAQ", f"ERROR: Exited immediately (code {proc.returncode})")
    else:
        log("DAQ", f"Started (PID {proc.pid})")
    return proc

def start_watchdog(mqtt_env: dict) -> subprocess.Popen:
    """Start Watchdog with MQTT credentials in environment."""
    log("WATCHDOG", "Starting Watchdog...")
    proc = start_in_console("Watchdog", [
        PYTHON, "services\\daq_service\\watchdog.py", "-c", "config\\system.ini",
    ], env=mqtt_env)
    log("WATCHDOG", f"Started (PID {proc.pid})")
    return proc

def start_azure_uploader(mqtt_env: dict) -> subprocess.Popen | None:
    """Start Azure IoT Uploader if available."""
    azure_python = ROOT / "azure-venv" / "Scripts" / "python.exe"
    if not azure_python.exists():
        log("AZURE", "Azure venv not found — skipping uploader")
        return None

    # Check if azure SDK is importable
    check = subprocess.run(
        [str(azure_python), "-c", "import azure.iot.device"],
        capture_output=True, creationflags=0x08000000)
    if check.returncode != 0:
        log("AZURE", "Azure IoT SDK not installed — skipping uploader")
        return None

    log("AZURE", "Starting Azure IoT Uploader...")
    proc = start_in_console("Azure Uploader", [
        str(azure_python),
        "services\\azure_uploader\\azure_uploader_service.py",
        "--host", "localhost", "--port", "1883",
    ], env=mqtt_env)
    log("AZURE", f"Started (PID {proc.pid})")
    return proc

def start_frontend() -> subprocess.Popen:
    """Start Vite dev server. npm is a .cmd file so needs CMD to run."""
    log("FRONTEND", "Starting Vite dev server...")
    proc = start_in_console("Frontend (Vite)", [
        "cmd", "/k", "npm run dev",
    ], cwd=str(ROOT / "dashboard"))
    log("FRONTEND", f"Started (PID {proc.pid})")
    return proc

# ── Monitor & Shutdown ─────────────────────────────────────────────────────────

def shutdown():
    """Gracefully stop all services in reverse order."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True

    print()
    log("SHUTDOWN", "Stopping all services...")

    # Stop station manager first (stops all station DAQ processes)
    if _station_manager:
        _station_manager.stop()

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

    # Final cleanup: kill mosquitto by name (in case the console wrapper survived)
    subprocess.run(["taskkill", "/F", "/IM", "mosquitto.exe"],
                   capture_output=True, creationflags=0x08000000)

    log("SHUTDOWN", "All services stopped.")

def monitor():
    """Wait for Ctrl+C, then shut down all services."""
    log("MONITOR", "All services running. Press Ctrl+C to stop all.")
    print()
    counter = 0
    try:
        while not _shutting_down:
            time.sleep(3)
            counter += 1
            # Check station health every ~30s
            if _station_manager and counter % 10 == 0:
                _station_manager.check_stations()
    except KeyboardInterrupt:
        shutdown()

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    os.chdir(str(ROOT))

    no_browser = "--no-browser" in sys.argv

    print()
    print("=" * 72)
    print("  NISystem — Starting Services")
    print("=" * 72)
    print()

    # Preflight checks
    if not Path(PYTHON).exists():
        print("ERROR: Python virtual environment not found!")
        print(f"  Expected: {PYTHON}")
        sys.exit(1)

    # Step 1: Clean slate
    kill_previous()
    print()

    # Step 2: Setup
    setup_credentials()
    setup_tls()
    mqtt_env = load_mqtt_credentials()
    if mqtt_env:
        log("CREDS", f"Loaded credentials for user: {mqtt_env.get('MQTT_USERNAME')}")
    else:
        log("CREDS", "WARNING: No MQTT credentials found")
    print()

    # Step 3: Start services
    services = {}

    services["mosquitto"] = start_mosquitto()
    services["daq"] = start_daq_service(mqtt_env)
    services["watchdog"] = start_watchdog(mqtt_env)
    services["azure"] = start_azure_uploader(mqtt_env)
    services["frontend"] = start_frontend()

    # Step 3b: Start station manager (multi-instance support)
    global _station_manager
    if HAS_STATION_MANAGER:
        _station_manager = StationManager(
            root=ROOT,
            daq_command_fn=lambda config_path: [
                PYTHON, "services\\daq_service\\daq_service.py", "-c", config_path
            ],
            credential_fn=load_mqtt_credentials_tuple,
            creation_flags=CREATE_NEW_CONSOLE,
            process_tracker=_processes,
        )
        _station_manager.start()
        log("STATION", "Station manager ready (multi-instance support)")
    else:
        log("STATION", "Station manager not available (missing paho-mqtt)")

    print()
    print("=" * 72)
    print("  All services started!")
    print("=" * 72)
    print()
    print("  MQTT Broker:     Window titled 'MQTT Broker'")
    print("  DAQ Service:     Window titled 'DAQ Service'")
    print("  Watchdog:        Window titled 'Watchdog'")
    if services.get("azure"):
        print("  Azure Uploader:  Window titled 'Azure Uploader'")
    print("  Frontend:        Window titled 'Frontend (Vite)'")
    if _station_manager:
        print("  Station Manager: Active (create stations via Admin tab)")
    print()
    print("  Dashboard: http://localhost:5173")
    print()

    # Step 4: Open browser
    if not no_browser:
        time.sleep(5)
        os.startfile("http://localhost:5173")

    # Step 5: Wait for Ctrl+C
    monitor()

if __name__ == "__main__":
    main()
