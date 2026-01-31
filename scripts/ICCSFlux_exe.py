#!/usr/bin/env python3
"""
ICCSFlux Portable Launcher (Executable Edition)
Starts all compiled services and opens the dashboard in browser.

When compiled with PyInstaller --noconsole, runs in service/background mode.
"""

import os
import sys
import subprocess
import time
import webbrowser
import signal
import socket
import argparse
import atexit
import ctypes
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

# Detect if running as windowed app (no console = service mode)
SERVICE_MODE = not sys.stdout or not sys.stdout.isatty()

# Get the directory where this executable/script is located
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    ROOT = Path(sys.executable).parent.resolve()
else:
    # Running as script
    ROOT = Path(__file__).parent.resolve()

# Paths relative to root
MOSQUITTO = ROOT / "mosquitto" / "mosquitto.exe"
MOSQUITTO_CONF = ROOT / "mosquitto" / "mosquitto.conf"
DAQ_SERVICE = ROOT / "DAQService.exe"
AZURE_PYTHON = ROOT / "azure_uploader" / "python" / "python.exe"
AZURE_SERVICE = ROOT / "azure_uploader" / "azure_uploader_service.py"
CONFIG = ROOT / "config" / "system.ini"
WWW = ROOT / "www"
DATA = ROOT / "data"
LOCKFILE = ROOT / "data" / ".iccsflux.lock"

# Global process list for cleanup
processes = []
httpd = None
_lockfile_handle = None


def is_process_running(pid):
    """Check if a process with given PID is still running (Windows)"""
    try:
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def acquire_single_instance():
    """Acquire single instance lock. Returns True if this is the only instance."""
    global _lockfile_handle

    # Ensure data directory exists
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)

    # Check if lock file exists with a running process
    if LOCKFILE.exists():
        try:
            with open(LOCKFILE, 'r') as f:
                old_pid = int(f.read().strip())
            if is_process_running(old_pid):
                return False  # Another instance is running
        except (ValueError, OSError, IOError):
            pass  # Stale or corrupt lock file, continue

    # Write our PID to lock file
    try:
        with open(LOCKFILE, 'w') as f:
            f.write(str(os.getpid()))
        _lockfile_handle = LOCKFILE
        atexit.register(release_single_instance)
        return True
    except Exception:
        return False


def release_single_instance():
    """Release single instance lock"""
    global _lockfile_handle
    if _lockfile_handle and _lockfile_handle.exists():
        try:
            _lockfile_handle.unlink()
        except Exception:
            pass
        _lockfile_handle = None


class QuietHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler that doesn't log every request"""
    def log_message(self, format, *args):
        pass  # Suppress logging


def is_port_available(port):
    """Check if a port is available"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def wait_for_port(port, timeout=10):
    """Wait for a port to become available (service started)"""
    start = time.time()
    while time.time() - start < timeout:
        if not is_port_available(port):
            return True
        time.sleep(0.2)
    return False


def start_mosquitto():
    """Start Mosquitto MQTT broker"""
    if not MOSQUITTO.exists():
        print("[WARN] Mosquitto not found at:", MOSQUITTO)
        print("       MQTT will not work. Copy mosquitto.exe to the mosquitto folder.")
        return None

    if not is_port_available(1883):
        print("[INFO] MQTT broker already running on port 1883")
        return None

    print("[START] Mosquitto MQTT broker...")

    # Start Mosquitto
    proc = subprocess.Popen(
        [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF)],
        cwd=str(MOSQUITTO.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    processes.append(proc)

    # Wait for MQTT to be ready
    if wait_for_port(1883, timeout=5):
        print("[  OK ] MQTT broker ready (port 1883)")
    else:
        print("[WARN] MQTT broker may not have started properly")

    return proc


def is_process_running_by_name(name):
    """Check if a process with given name is running"""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def start_daq_service():
    """Start the DAQ backend service"""
    if not DAQ_SERVICE.exists():
        print("[ERROR] DAQService.exe not found at:", DAQ_SERVICE)
        return None

    # Check if DAQ service is already running (by process name)
    if is_process_running_by_name("DAQService.exe"):
        print("[INFO] DAQ Service already running")
        return None

    print("[START] ICCSFlux DAQ Service...")

    # Ensure data directories exist
    DATA.mkdir(exist_ok=True)
    (DATA / "recordings").mkdir(exist_ok=True)
    (DATA / "logs").mkdir(exist_ok=True)

    # Start DAQ service
    env = os.environ.copy()
    env["ICCSFLUX_DATA_DIR"] = str(DATA)

    proc = subprocess.Popen(
        [str(DAQ_SERVICE), "-c", str(CONFIG)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL if SERVICE_MODE else None,
        stderr=subprocess.DEVNULL if SERVICE_MODE else None,
    )
    processes.append(proc)

    # Wait for service to publish status
    time.sleep(2)

    if proc.poll() is None:
        print("[  OK ] DAQ Service started")
    else:
        print("[ERROR] DAQ Service failed to start")

    return proc


def start_azure_uploader():
    """Start Azure IoT Hub uploader service (runs idle, waiting for commands)"""
    if not AZURE_PYTHON.exists() or not AZURE_SERVICE.exists():
        # Azure uploader not available (normal if not installed)
        return None

    print("[START] Azure IoT Hub uploader (idle)...")

    # Start Azure uploader - it connects to MQTT and waits for commands
    proc = subprocess.Popen(
        [str(AZURE_PYTHON), str(AZURE_SERVICE), "--host", "localhost", "--port", "1883"],
        cwd=str(AZURE_SERVICE.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    processes.append(proc)

    time.sleep(1)
    if proc.poll() is None:
        print("[  OK ] Azure uploader ready (waiting for commands)")
    else:
        print("[WARN] Azure uploader failed to start")

    return proc


def start_web_server(port=5173):
    """Start HTTP server for the dashboard"""
    global httpd

    if not WWW.exists():
        print("[ERROR] Dashboard files not found at:", WWW)
        return None

    # Find available port
    if not is_port_available(port):
        for p in range(5174, 5180):
            if is_port_available(p):
                port = p
                break

    print(f"[START] Web server on port {port}...")

    # Change to www directory
    os.chdir(WWW)

    try:
        httpd = HTTPServer(("127.0.0.1", port), QuietHTTPHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"[  OK ] Dashboard available at http://localhost:{port}")
        return port
    except Exception as e:
        print(f"[ERROR] Failed to start web server: {e}")
        return None


def cleanup(signum=None, frame=None):
    """Clean shutdown of all services"""
    global httpd

    print()
    print("[STOP] Shutting down ICCSFlux...")

    # Stop HTTP server
    if httpd:
        httpd.shutdown()

    # Stop all subprocesses
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            try:
                proc.kill()
            except:
                pass

    # Release single instance lock
    release_single_instance()

    print("[  OK ] Shutdown complete")
    sys.exit(0)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="ICCSFlux - Industrial Data Acquisition Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Services started:
  - Mosquitto MQTT broker (port 1883)
  - DAQ Service (data acquisition, port 9002)
  - Azure IoT Hub uploader (if available)
  - Web server (dashboard, port 5173)

Example:
  ICCSFlux.exe              Start all services and open dashboard
  ICCSFlux.exe --no-browser Start without opening browser
"""
    )
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser automatically")
    parser.add_argument("--port", type=int, default=5173,
                        help="Web server port (default: 5173)")
    parser.add_argument("-v", "--version", action="version",
                        version="ICCSFlux Portable 1.0")
    args = parser.parse_args()

    # Check for single instance
    if not acquire_single_instance():
        print("[ERROR] ICCSFlux is already running!")
        print("        Only one instance can run at a time.")
        if not SERVICE_MODE:
            input("Press Enter to exit...")
        return 1

    print()
    print("=" * 55)
    print("       ICCSFlux - Industrial Data Acquisition")
    print("=" * 55)
    print()

    # Verify required files exist
    if not DAQ_SERVICE.exists():
        if not SERVICE_MODE:
            print("[ERROR] DAQService.exe not found!")
            print("        Run build_exe.py to create the portable package.")
            input("Press Enter to exit...")
        return 1

    if not WWW.exists():
        if not SERVICE_MODE:
            print("[ERROR] Dashboard files not found!")
            print("        Run build_exe.py to create the portable package.")
            input("Press Enter to exit...")
        return 1

    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Start services
    start_mosquitto()
    time.sleep(1)

    start_daq_service()
    time.sleep(1)

    # Start Azure uploader if available
    start_azure_uploader()

    port = start_web_server(args.port)

    if port:
        if not SERVICE_MODE:
            print()
            print("=" * 55)
            print(f"  ICCSFlux is ready!")
            print(f"  Dashboard: http://localhost:{port}")
            print()
            print("  Press Ctrl+C to stop")
            print("=" * 55)
            print()

            # Open browser (only in interactive mode, unless --no-browser)
            if not args.no_browser:
                time.sleep(0.5)
                webbrowser.open(f"http://localhost:{port}")

        # Keep running
        try:
            while True:
                # Check if processes are still running
                for proc in processes:
                    if proc.poll() is not None:
                        print("[WARN] A service has stopped unexpectedly")
                time.sleep(5)
        except KeyboardInterrupt:
            cleanup()
    else:
        print("[ERROR] Failed to start dashboard server")
        cleanup()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
