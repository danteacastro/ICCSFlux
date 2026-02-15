#!/usr/bin/env python3
"""
ICCSFlux Portable Launcher (Executable Edition)
Starts all compiled services and opens the dashboard in browser.

When compiled with PyInstaller --noconsole, runs in service/background mode.
"""

import base64
import hashlib
import json
import os
import secrets
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
MOSQUITTO_CONF = ROOT / "config" / "mosquitto.conf"
DAQ_SERVICE = ROOT / "DAQService.exe"
AZURE_UPLOADER = ROOT / "AzureUploader.exe"
CONFIG = ROOT / "config" / "system.ini"
CRED_FILE = ROOT / "config" / "mqtt_credentials.json"
PASSWD_FILE = ROOT / "config" / "mosquitto_passwd"
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


def _hash_mosquitto_password(password, iterations=101):
    """Generate mosquitto-compatible PBKDF2-SHA512 password hash."""
    salt = os.urandom(12)
    dk = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, iterations, dklen=64)
    salt_b64 = base64.b64encode(salt).decode('ascii')
    hash_b64 = base64.b64encode(dk).decode('ascii')
    return f"$7${iterations}${salt_b64}${hash_b64}"


def setup_mqtt_credentials():
    """Auto-generate MQTT credentials on first run. Idempotent."""
    if CRED_FILE.exists():
        return True

    print("[SETUP] Generating MQTT credentials (first-run)...")

    backend_pass = secrets.token_urlsafe(24)
    dashboard_pass = secrets.token_urlsafe(24)

    creds = {
        'backend': {'username': 'backend', 'password': backend_pass},
        'dashboard': {'username': 'dashboard', 'password': dashboard_pass},
    }

    # Write credential store
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CRED_FILE, 'w') as f:
        json.dump(creds, f, indent=2)

    # Write mosquitto password file (PBKDF2-SHA512)
    lines = []
    for username, password in [('backend', backend_pass), ('dashboard', dashboard_pass)]:
        hashed = _hash_mosquitto_password(password)
        lines.append(f"{username}:{hashed}")
    with open(PASSWD_FILE, 'w', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

    print("[  OK ] MQTT credentials generated")
    return True


def load_mqtt_credentials():
    """Load MQTT credentials from the auto-generated file. Returns (username, password) or (None, None)."""
    if not CRED_FILE.exists():
        return None, None
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds['backend']['username'], creds['backend']['password']
    except Exception:
        return None, None


class QuietHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler for Vue SPA with proper MIME types and SPA fallback"""

    # Ensure .js files get the correct MIME type (Windows registry can override)
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.js': 'application/javascript',
        '.mjs': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.svg': 'image/svg+xml',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
    }

    def do_GET(self):
        """Serve files with SPA fallback — unknown paths serve index.html"""
        # Try to serve the file normally first
        path = self.translate_path(self.path)
        if os.path.exists(path) and not os.path.isdir(path):
            return super().do_GET()
        # For directories, check for index.html
        if os.path.isdir(path):
            index = os.path.join(path, 'index.html')
            if os.path.exists(index):
                return super().do_GET()
        # SPA fallback: serve index.html for any unmatched route
        self.path = '/index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        pass  # Suppress routine request logging

    def log_error(self, format, *args):
        """Log errors so we can debug 404s and serving issues"""
        print(f"[HTTP] ERROR: {format % args}")


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

    # Start Mosquitto (CWD=ROOT so relative paths in config resolve correctly)
    proc = subprocess.Popen(
        [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF)],
        cwd=str(ROOT),
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

    # Start DAQ service with MQTT credentials
    env = os.environ.copy()
    env["ICCSFLUX_DATA_DIR"] = str(DATA)

    mqtt_user, mqtt_pass = load_mqtt_credentials()
    if mqtt_user and mqtt_pass:
        env["MQTT_USERNAME"] = mqtt_user
        env["MQTT_PASSWORD"] = mqtt_pass

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
    if not AZURE_UPLOADER.exists():
        # Azure uploader not available (normal if not installed)
        return None

    print("[START] Azure IoT Hub uploader (idle)...")

    # Pass MQTT credentials via environment variables
    env = os.environ.copy()
    mqtt_user, mqtt_pass = load_mqtt_credentials()
    if mqtt_user and mqtt_pass:
        env["MQTT_USERNAME"] = mqtt_user
        env["MQTT_PASSWORD"] = mqtt_pass

    # Start Azure uploader - it connects to MQTT and waits for commands
    proc = subprocess.Popen(
        [str(AZURE_UPLOADER), "--host", "localhost", "--port", "1883"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL if SERVICE_MODE else None,
        stderr=subprocess.DEVNULL if SERVICE_MODE else None,
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


_cleanup_done = False

def cleanup(signum=None, frame=None):
    """Clean shutdown of all services"""
    global httpd, _cleanup_done

    # Guard against double cleanup (atexit + signal can both fire)
    if _cleanup_done:
        return
    _cleanup_done = True

    try:
        print()
        print("[STOP] Shutting down ICCSFlux...")
    except Exception:
        pass

    # Stop HTTP server
    if httpd:
        try:
            httpd.shutdown()
        except Exception:
            pass

    # Stop all subprocesses
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

    # Release single instance lock
    release_single_instance()

    try:
        print("[  OK ] Shutdown complete")
    except Exception:
        pass

    # Only call sys.exit when invoked from signal handler, not from atexit
    if signum is not None:
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
    parser.add_argument("--setup", action="store_true",
                        help="Generate MQTT credentials and exit (for service installation)")
    parser.add_argument("-v", "--version", action="version",
                        version="ICCSFlux Portable 1.0")
    args = parser.parse_args()

    # --setup mode: generate credentials and exit
    if args.setup:
        setup_mqtt_credentials()
        return 0

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

    # Register atexit so cleanup runs even if the console window is closed
    atexit.register(cleanup)

    # On Windows, handle console close/logoff events (clicking X on console window)
    if sys.platform == 'win32':
        try:
            kernel32 = ctypes.windll.kernel32
            _CTRL_CLOSE_EVENT = 2
            _CTRL_LOGOFF_EVENT = 5
            _CTRL_SHUTDOWN_EVENT = 6

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
            def _console_handler(event):
                if event in (_CTRL_CLOSE_EVENT, _CTRL_LOGOFF_EVENT, _CTRL_SHUTDOWN_EVENT):
                    cleanup()
                    return True
                return False

            kernel32.SetConsoleCtrlHandler(_console_handler, True)
        except Exception:
            pass  # Non-critical — Ctrl+C still works

    # Generate MQTT credentials on first run (before starting mosquitto)
    setup_mqtt_credentials()

    # Generate TLS certificates on first run (before starting mosquitto)
    tls_dir = ROOT / "config" / "tls"
    if not (tls_dir / "ca.crt").exists():
        print("[SETUP] Generating TLS certificates (first-run)...")
        try:
            # PyInstaller bundles generate_tls_certs.py into _MEIPASS/scripts/
            # Dev mode has it at ROOT/scripts/
            bundle_dir = getattr(sys, '_MEIPASS', None)
            if bundle_dir:
                scripts_path = str(Path(bundle_dir) / "scripts")
            else:
                scripts_path = str(ROOT / "scripts")
            sys.path.insert(0, scripts_path)
            from generate_tls_certs import generate_certificates
            if generate_certificates(tls_dir):
                print("[  OK ] TLS certificates generated")
            else:
                print("[WARN] TLS certificate generation failed — TLS listener will be unavailable")
        except Exception as e:
            print(f"[WARN] TLS certificate generation failed: {e}")
        finally:
            sys.path.pop(0)

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
