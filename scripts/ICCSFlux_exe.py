#!/usr/bin/env python3
"""
ICCSFlux — Native Desktop Launcher + Service Manager

Uses tkinter (Python stdlib) for the native window. No external UI
frameworks, no JS bridges, no web views. Just works.

TODO (1.0): Windows Service integration via NSSM
  - Register Mosquitto, DAQService, AzureUploader as Windows Services
  - Launcher becomes a management UI that talks to SCM, not the process parent
  - Services auto-start on boot, survive user logout
  - NSSM is already bundled in the portable build (nssm/ directory)
  - This requires the launcher to use `nssm install/start/stop` instead of
    subprocess.Popen for service lifecycle

TODO (1.0): MQTT-based graceful shutdown
  - Launcher publishes a shutdown command to DAQ service via MQTT
  - DAQ service shuts down cleanly (flushes recordings, closes hardware)
  - Currently uses TerminateProcess on Windows (no cleanup opportunity)
"""

import base64
import configparser
import hashlib
import json
import os
import secrets
import sys
import subprocess
import time
import webbrowser
import socket
import argparse
import atexit
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
from collections import deque
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Get the directory where this executable/script is located
if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).parent.resolve()
else:
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
VERSION_FILE = ROOT / "VERSION.txt"

# Icon path (bundled by PyInstaller or in assets/)
if getattr(sys, 'frozen', False):
    ICO_PATH = Path(sys._MEIPASS) / 'iccsflux.ico'
else:
    ICO_PATH = ROOT.parent / 'assets' / 'icons' / 'iccsflux.ico'

# Prevent child processes from spawning console windows
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

# ─── Service Dependency Graph ───────────────────────────────────────────────
# Explicit dependency declarations. A service won't start until all its
# dependencies are running/external. Shutdown runs in reverse order.

SERVICE_DEPS = {
    "MOSQUITTO": [],
    "DAQ":       ["MOSQUITTO"],
    "AZURE":     ["MOSQUITTO"],
    "HTTP":      [],
}

# Ports used for health probing (None = alive-only check)
SERVICE_HEALTH_PORTS = {
    "MOSQUITTO": 1883,
    "DAQ":       None,
    "AZURE":     None,
    "HTTP":      None,  # set dynamically after web server starts
}

# Global process list for cleanup
processes = []
httpd = None
_lockfile_handle = None
_dashboard_port = None

# ─── Log Buffer (shared between Python threads and UI) ──────────────────────

_log_lock = threading.Lock()
_log_buffer = deque(maxlen=2000)
_log_cursor = 0

_status_lock = threading.Lock()
_service_statuses = {}
_managed_services = []

_error_count = 0
_version_info = "dev"
_project_name = None

# ─── File Logger (always works) ─────────────────────────────────────────────

_file_logger = None

def _setup_file_logging():
    global _file_logger
    log_dir = DATA / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _file_logger = logging.getLogger("iccsflux-launcher")
    _file_logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(
        str(log_dir / "launcher.log"),
        maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)-5s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S',
    ))
    _file_logger.addHandler(handler)

_LEVEL_MAP = {
    "error": logging.ERROR, "warn": logging.WARNING,
    "ok": logging.INFO, "start": logging.INFO, "info": logging.INFO,
}

# Words that cause false-positive "error" classification
_ERROR_FALSE_POSITIVES = (
    'mqtterrorcode', 'err_success', 'error=none', 'error=0',
    'error_count=0', 'no error', 'without error',
)

def log_entry(tag, message, level="info"):
    global _log_cursor, _error_count
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"id": 0, "ts": ts, "tag": tag, "msg": message, "level": level}
    with _log_lock:
        _log_cursor += 1
        entry["id"] = _log_cursor
        _log_buffer.append(entry)
        if level == "error":
            _error_count += 1
    if _file_logger:
        _file_logger.log(_LEVEL_MAP.get(level, logging.INFO), "[%-10s] %s", tag, message)


def update_service_status(tag, name, status, pid=None, restarts=0,
                          max_restarts=5, cpu=0.0, mem=0.0, healthy=None):
    with _status_lock:
        _service_statuses[tag] = {
            "tag": tag, "name": name, "status": status, "pid": pid,
            "restarts": restarts, "maxRestarts": max_restarts,
            "cpu": round(cpu, 1), "mem": round(mem, 1),
            "healthy": healthy,
        }


def _classify_line(line):
    lower = line.lower()
    if any(k in lower for k in ('error', 'exception', 'traceback', 'failed', 'fatal', 'critical')):
        if not any(fp in lower for fp in _ERROR_FALSE_POSITIVES):
            return "error"
    if any(k in lower for k in ('warning', 'warn', 'timeout', 'retry')):
        return "warn"
    return "info"


# ─── Health Check ────────────────────────────────────────────────────────────

def check_port_health(port):
    """Try to connect to a TCP port. Returns True if accepting connections."""
    if port is None:
        return None  # No health check configured
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


# ─── Process Output Reader ───────────────────────────────────────────────────

class ProcessOutputReader:
    def __init__(self, proc, tag):
        self.proc = proc
        self.tag = tag

    def start(self):
        if self.proc.stdout:
            threading.Thread(
                target=self._read_loop, daemon=True, name=f"reader-{self.tag}",
            ).start()

    def _read_loop(self):
        try:
            for raw_line in iter(self.proc.stdout.readline, b''):
                try:
                    line = raw_line.decode('utf-8', errors='replace').rstrip()
                except Exception:
                    line = str(raw_line).rstrip()
                if line:
                    log_entry(self.tag, line, _classify_line(line))
        except Exception:
            pass


# ─── Managed Service ─────────────────────────────────────────────────────────

class ManagedService:
    def __init__(self, name, tag, max_restarts=5):
        self.name = name
        self.tag = tag
        self.proc = None
        self.reader = None
        self.restart_count = 0
        self.max_restarts = max_restarts
        self.start_time = 0.0
        self.status = "stopped"
        self._restarting = False
        self._psutil_proc = None
        self.health_port = SERVICE_HEALTH_PORTS.get(tag)
        self._healthy = None  # None=unknown, True=healthy, False=unhealthy

    def attach(self, proc):
        self.proc = proc
        self.start_time = time.time()
        self.status = "running"
        self.reader = ProcessOutputReader(proc, self.tag)
        self.reader.start()
        self._psutil_proc = None
        if HAS_PSUTIL and proc:
            try:
                self._psutil_proc = psutil.Process(proc.pid)
                self._psutil_proc.cpu_percent()
            except Exception:
                self._psutil_proc = None
        pid = proc.pid if proc else None
        update_service_status(self.tag, self.name, "running", pid,
                              self.restart_count, self.max_restarts)

    def attach_external(self, pid):
        """Attach to an already-running process we didn't start."""
        self.proc = None
        self.start_time = time.time()
        self.status = "external"
        self._psutil_proc = None
        if HAS_PSUTIL and pid:
            try:
                self._psutil_proc = psutil.Process(pid)
                self._psutil_proc.cpu_percent()
            except Exception:
                self._psutil_proc = None
        update_service_status(self.tag, self.name, "external", pid,
                              self.restart_count, self.max_restarts)

    @property
    def alive(self):
        if self.status == "external":
            if self._psutil_proc:
                try:
                    return self._psutil_proc.is_running()
                except Exception:
                    return False
            return True
        return self.proc is not None and self.proc.poll() is None

    def check(self):
        if self.proc is None or self.status in ("stopped", "failed", "external"):
            return None
        if self._restarting:
            return None
        retcode = self.proc.poll()
        if retcode is not None:
            self.status = "crashed"
            self._psutil_proc = None
            self._healthy = None
            update_service_status(self.tag, self.name, "crashed", None,
                                  self.restart_count, self.max_restarts)
            return f"exited with code {retcode}"
        return None

    def check_health(self):
        """Run health probe if configured. Updates self._healthy."""
        if self.health_port is None:
            self._healthy = None
            return
        if self.status not in ("running", "external"):
            self._healthy = None
            return
        self._healthy = check_port_health(self.health_port)

    def get_resource_stats(self):
        if not HAS_PSUTIL or not self._psutil_proc:
            return 0.0, 0.0
        try:
            if not self._psutil_proc.is_running():
                self._psutil_proc = None
                return 0.0, 0.0
            cpu = self._psutil_proc.cpu_percent(interval=0)
            mem = self._psutil_proc.memory_info().rss / (1024 * 1024)
            return cpu, mem
        except Exception:
            self._psutil_proc = None
            return 0.0, 0.0

    def update_status_display(self):
        pid = None
        if self.proc and self.status != "external":
            pid = self.proc.pid if self.alive else None
        elif self._psutil_proc:
            try:
                pid = self._psutil_proc.pid
            except Exception:
                pass
        cpu, mem = self.get_resource_stats()
        update_service_status(self.tag, self.name, self.status, pid,
                              self.restart_count, self.max_restarts,
                              cpu, mem, self._healthy)

    def stop(self):
        """Stop this service. Works on both managed and external processes."""
        if self.status == "external":
            # Kill the external process via psutil or taskkill
            log_entry(self.tag, f"Stopping external {self.name}...", "info")
            killed = False
            if self._psutil_proc:
                try:
                    self._psutil_proc.terminate()
                    self._psutil_proc.wait(timeout=5)
                    killed = True
                except Exception:
                    try:
                        self._psutil_proc.kill()
                        killed = True
                    except Exception:
                        pass
            if not killed:
                # Fallback: taskkill by name
                exe_names = {
                    "MOSQUITTO": "mosquitto.exe",
                    "DAQ": "DAQService.exe",
                    "AZURE": "AzureUploader.exe",
                }
                exe = exe_names.get(self.tag)
                if exe:
                    try:
                        subprocess.run(["taskkill", "/IM", exe, "/F"],
                                       capture_output=True, creationflags=_NO_WINDOW)
                    except Exception:
                        pass
        elif self.proc and self.alive:
            log_entry(self.tag, f"Stopping {self.name}...", "info")
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                except OSError:
                    pass
        self.proc = None
        self.status = "stopped"
        self._healthy = None
        self._psutil_proc = None
        self.update_status_display()
        log_entry(self.tag, f"{self.name} stopped", "info")
        return True


# ─── Utility Functions ───────────────────────────────────────────────────────

def is_process_running(pid):
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def find_pid_by_name(name):
    """Find PID of a running process by executable name."""
    if HAS_PSUTIL:
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == name.lower():
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return None


def acquire_single_instance():
    global _lockfile_handle
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCKFILE.exists():
        try:
            with open(LOCKFILE, 'r') as f:
                old_pid = int(f.read().strip())
            if is_process_running(old_pid):
                return False
        except (ValueError, OSError, IOError):
            pass
    try:
        with open(LOCKFILE, 'w') as f:
            f.write(str(os.getpid()))
        _lockfile_handle = LOCKFILE
        atexit.register(release_single_instance)
        return True
    except Exception:
        return False


def release_single_instance():
    global _lockfile_handle
    if _lockfile_handle and _lockfile_handle.exists():
        try:
            _lockfile_handle.unlink()
        except Exception:
            pass
        _lockfile_handle = None


def _hash_mosquitto_password(password, iterations=101):
    salt = os.urandom(12)
    dk = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, iterations, dklen=64)
    salt_b64 = base64.b64encode(salt).decode('ascii')
    hash_b64 = base64.b64encode(dk).decode('ascii')
    return f"$7${iterations}${salt_b64}${hash_b64}"


def setup_mqtt_credentials():
    if CRED_FILE.exists():
        return True
    log_entry("LAUNCHER", "Generating MQTT credentials (first-run)...", "start")
    backend_pass = secrets.token_urlsafe(24)
    dashboard_pass = secrets.token_urlsafe(24)
    creds = {
        'backend': {'username': 'backend', 'password': backend_pass},
        'dashboard': {'username': 'dashboard', 'password': dashboard_pass},
    }
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CRED_FILE, 'w') as f:
        json.dump(creds, f, indent=2)
    lines = []
    for username, password in [('backend', backend_pass), ('dashboard', dashboard_pass)]:
        hashed = _hash_mosquitto_password(password)
        lines.append(f"{username}:{hashed}")
    with open(PASSWD_FILE, 'w', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    log_entry("LAUNCHER", "MQTT credentials generated", "ok")
    return True


def load_mqtt_credentials():
    if not CRED_FILE.exists():
        return None, None
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds['backend']['username'], creds['backend']['password']
    except Exception:
        return None, None


def read_version():
    """Read build version from VERSION.txt."""
    if VERSION_FILE.exists():
        try:
            text = VERSION_FILE.read_text().strip()
            for line in text.split('\n'):
                line = line.strip()
                if line and not line.startswith('SHA') and not line.startswith('Built'):
                    return line
        except Exception:
            pass
    return "dev"


def read_project_name():
    try:
        if CONFIG.exists():
            cfg = configparser.ConfigParser()
            cfg.read(str(CONFIG))
            project_path = cfg.get('daq', 'project', fallback='')
            if project_path:
                p = Path(project_path)
                if not p.is_absolute():
                    p = ROOT / p
                if p.exists():
                    with open(p) as f:
                        data = json.load(f)
                    return data.get('name', p.stem)
                return p.stem
    except Exception:
        pass
    projects_dir = ROOT / "config" / "projects"
    if projects_dir.exists():
        jsons = list(projects_dir.glob("*.json"))
        if len(jsons) == 1:
            try:
                with open(jsons[0]) as f:
                    data = json.load(f)
                return data.get('name', jsons[0].stem)
            except Exception:
                return jsons[0].stem
        elif len(jsons) > 1:
            return f"{len(jsons)} projects"
    return None


class QuietHTTPHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.js': 'application/javascript', '.mjs': 'application/javascript',
        '.css': 'text/css', '.json': 'application/json',
        '.svg': 'image/svg+xml', '.woff': 'font/woff',
        '.woff2': 'font/woff2', '.ttf': 'font/ttf',
    }

    def do_GET(self):
        path = self.translate_path(self.path)
        if os.path.exists(path) and not os.path.isdir(path):
            return super().do_GET()
        if os.path.isdir(path):
            index = os.path.join(path, 'index.html')
            if os.path.exists(index):
                return super().do_GET()
        self.path = '/index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        pass

    def log_error(self, format, *args):
        log_entry("HTTP", format % args, "error")


def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def wait_for_port(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        if not is_port_available(port):
            return True
        time.sleep(0.2)
    return False


def is_process_running_by_name(name):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True,
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def _get_dep_services(tag):
    """Return list of service tags that depend on the given tag."""
    return [t for t, deps in SERVICE_DEPS.items() if tag in deps]


def _check_deps_running(tag):
    """Check if all dependencies for a service are running. Returns (ok, missing)."""
    missing = []
    for dep_tag in SERVICE_DEPS.get(tag, []):
        with _status_lock:
            dep = _service_statuses.get(dep_tag)
        if not dep or dep["status"] not in ("running", "external"):
            missing.append(dep_tag)
    return len(missing) == 0, missing


# ─── Service Startup ─────────────────────────────────────────────────────────

def start_mosquitto():
    svc = ManagedService("Mosquitto", "MOSQUITTO")
    update_service_status("MOSQUITTO", "Mosquitto", "stopped")
    if not MOSQUITTO.exists():
        log_entry("MOSQUITTO", "Not found", "warn")
        return svc
    if not is_port_available(1883):
        pid = find_pid_by_name("mosquitto.exe")
        log_entry("MOSQUITTO", f"Already running on port 1883 (PID {pid or '?'})", "info")
        svc.attach_external(pid)
        return svc
    log_entry("MOSQUITTO", "Starting MQTT broker...", "start")
    proc = subprocess.Popen(
        [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF), "-v"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW,
    )
    processes.append(proc)
    svc.attach(proc)
    if wait_for_port(1883, timeout=5):
        log_entry("MOSQUITTO", "Ready on port 1883", "ok")
    else:
        log_entry("MOSQUITTO", "May not have started properly", "warn")
    return svc


def start_daq_service():
    svc = ManagedService("DAQ Service", "DAQ")
    update_service_status("DAQ", "DAQ Service", "stopped")
    if not DAQ_SERVICE.exists():
        log_entry("DAQ", "DAQService.exe not found", "error")
        svc.status = "failed"
        update_service_status("DAQ", "DAQ Service", "failed")
        return svc
    if is_process_running_by_name("DAQService.exe"):
        pid = find_pid_by_name("DAQService.exe")
        log_entry("DAQ", f"Already running (PID {pid or '?'})", "info")
        svc.attach_external(pid)
        return svc
    log_entry("DAQ", "Starting DAQ Service...", "start")
    DATA.mkdir(exist_ok=True)
    (DATA / "recordings").mkdir(exist_ok=True)
    (DATA / "logs").mkdir(exist_ok=True)
    env = os.environ.copy()
    env["ICCSFLUX_DATA_DIR"] = str(DATA)
    mqtt_user, mqtt_pass = load_mqtt_credentials()
    if mqtt_user and mqtt_pass:
        env["MQTT_USERNAME"] = mqtt_user
        env["MQTT_PASSWORD"] = mqtt_pass
    proc = subprocess.Popen(
        [str(DAQ_SERVICE), "-c", str(CONFIG)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW,
    )
    processes.append(proc)
    svc.attach(proc)
    time.sleep(2)
    if proc.poll() is None:
        log_entry("DAQ", f"Started (PID {proc.pid})", "ok")
    else:
        log_entry("DAQ", f"Failed to start (exit code {proc.returncode})", "error")
        svc.status = "failed"
        update_service_status("DAQ", "DAQ Service", "failed")
    return svc


def start_azure_uploader():
    svc = ManagedService("Azure Uploader", "AZURE", max_restarts=3)
    if not AZURE_UPLOADER.exists():
        return svc
    update_service_status("AZURE", "Azure Uploader", "stopped")
    if is_process_running_by_name("AzureUploader.exe"):
        pid = find_pid_by_name("AzureUploader.exe")
        log_entry("AZURE", f"Already running (PID {pid or '?'})", "info")
        svc.attach_external(pid)
        return svc
    log_entry("AZURE", "Starting Azure IoT Hub uploader...", "start")
    # Resolve historian.db path (same as DAQ service uses)
    log_dir = ROOT / "logs"
    db_path = log_dir / "historian" / "historian.db"
    env = os.environ.copy()
    proc = subprocess.Popen(
        [str(AZURE_UPLOADER), "--db-path", str(db_path)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW,
    )
    processes.append(proc)
    svc.attach(proc)
    time.sleep(1)
    if proc.poll() is None:
        log_entry("AZURE", f"Ready (PID {proc.pid})", "ok")
    else:
        log_entry("AZURE", "Failed to start", "warn")
        svc.status = "failed"
        update_service_status("AZURE", "Azure Uploader", "failed")
    return svc


def start_web_server(port=5173):
    global httpd
    if not WWW.exists():
        log_entry("HTTP", "Dashboard files not found at: " + str(WWW), "error")
        return None
    if not is_port_available(port):
        for p in range(5174, 5180):
            if is_port_available(p):
                port = p
                break
    log_entry("HTTP", f"Starting web server on port {port}...", "start")
    os.chdir(WWW)
    try:
        httpd = HTTPServer(("127.0.0.1", port), QuietHTTPHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        log_entry("HTTP", f"Dashboard available at http://localhost:{port}", "ok")
        # Update health port for HTTP now that we know it
        SERVICE_HEALTH_PORTS["HTTP"] = port
        update_service_status("HTTP", "Web Server", "running", pid=None)
        return port
    except Exception as e:
        log_entry("HTTP", f"Failed to start web server: {e}", "error")
        return None


# ─── Service Start (by tag) ─────────────────────────────────────────────────

def start_service_by_tag(tag):
    """Start a single service by tag. Checks dependencies first.
    Returns the ManagedService (updates the global list in place)."""
    # Check deps
    ok, missing = _check_deps_running(tag)
    if not ok:
        for dep in missing:
            log_entry(tag, f"Dependency '{dep}' not running — starting it first", "info")
            start_service_by_tag(dep)
        time.sleep(0.5)

    # Find existing ManagedService or create one
    svc = None
    for s in _managed_services:
        if s.tag == tag:
            svc = s
            break

    if tag == "MOSQUITTO":
        new_svc = start_mosquitto()
    elif tag == "DAQ":
        new_svc = start_daq_service()
    elif tag == "AZURE":
        new_svc = start_azure_uploader()
    else:
        return svc

    if svc:
        # Update in place
        svc.proc = new_svc.proc
        svc.reader = new_svc.reader
        svc.start_time = new_svc.start_time
        svc.status = new_svc.status
        svc._psutil_proc = new_svc._psutil_proc
        svc.restart_count = 0
        svc.update_status_display()
        return svc
    else:
        _managed_services.append(new_svc)
        return new_svc


# ─── Cleanup ─────────────────────────────────────────────────────────────────

_cleanup_done = False

def _shutdown_httpd():
    """Shut down HTTP server in a thread so it can't block forever."""
    global httpd
    if httpd:
        try:
            httpd.shutdown()
        except Exception:
            pass
        httpd = None

def cleanup(kill_services=True):
    global httpd, _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    # Shut down HTTP server with a timeout (can hang if stuck mid-request)
    t = threading.Thread(target=_shutdown_httpd, daemon=True)
    t.start()
    t.join(timeout=3)

    if kill_services:
        log_entry("LAUNCHER", "Shutting down ICCSFlux services...", "start")
        # Stop in reverse dependency order — includes external services
        stop_order = ["AZURE", "DAQ", "MOSQUITTO"]
        for tag in stop_order:
            for svc in _managed_services:
                if svc.tag == tag and svc.status not in ("stopped", "failed"):
                    svc.stop()
        # Kill any remaining processes we started
        for proc in processes:
            try:
                if proc.poll() is None:
                    proc.kill()
            except OSError:
                pass
        log_entry("LAUNCHER", "All services stopped", "ok")
    else:
        log_entry("LAUNCHER", "Closing launcher (services still running)", "info")

    release_single_instance()


# ─── Service Monitor & Restart ───────────────────────────────────────────────

def restart_service(svc):
    """Restart a service by launching a new process.
    Always checks for existing instances first to prevent duplicates."""
    # Guard: don't start if already running
    if svc.tag == "MOSQUITTO" and not is_port_available(1883):
        pid = find_pid_by_name("mosquitto.exe")
        log_entry("MOSQUITTO", f"Already running (PID {pid or '?'}) — skipping start", "warn")
        svc.attach_external(pid)
        return
    if svc.tag == "DAQ" and is_process_running_by_name("DAQService.exe"):
        pid = find_pid_by_name("DAQService.exe")
        log_entry("DAQ", f"Already running (PID {pid or '?'}) — skipping start", "warn")
        svc.attach_external(pid)
        return
    if svc.tag == "AZURE" and is_process_running_by_name("AzureUploader.exe"):
        pid = find_pid_by_name("AzureUploader.exe")
        log_entry("AZURE", f"Already running (PID {pid or '?'}) — skipping start", "warn")
        svc.attach_external(pid)
        return

    if svc.tag == "MOSQUITTO" and MOSQUITTO.exists():
        proc = subprocess.Popen(
            [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF), "-v"],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
        processes.append(proc)
        svc.attach(proc)
    elif svc.tag == "DAQ":
        env = os.environ.copy()
        env["ICCSFLUX_DATA_DIR"] = str(DATA)
        mqtt_user, mqtt_pass = load_mqtt_credentials()
        if mqtt_user and mqtt_pass:
            env["MQTT_USERNAME"] = mqtt_user
            env["MQTT_PASSWORD"] = mqtt_pass
        proc = subprocess.Popen(
            [str(DAQ_SERVICE), "-c", str(CONFIG)],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
        processes.append(proc)
        svc.attach(proc)
    elif svc.tag == "AZURE" and AZURE_UPLOADER.exists():
        env = os.environ.copy()
        mqtt_user, mqtt_pass = load_mqtt_credentials()
        if mqtt_user and mqtt_pass:
            env["MQTT_USERNAME"] = mqtt_user
            env["MQTT_PASSWORD"] = mqtt_pass
        proc = subprocess.Popen(
            [str(AZURE_UPLOADER), "--host", "localhost", "--port", "1883"],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
        processes.append(proc)
        svc.attach(proc)


def monitor_loop(managed_services, stop_event):
    health_counter = 0
    while not stop_event.is_set():
        health_counter += 1
        for svc in managed_services:
            if svc.alive:
                svc.update_status_display()
            # Health check every ~10s (3s poll * 3 cycles)
            if health_counter % 3 == 0:
                svc.check_health()
                svc.update_status_display()
            err = svc.check()
            if err:
                log_entry(svc.tag, f"{svc.name} {err}", "error")
                if svc.restart_count < svc.max_restarts:
                    uptime = time.time() - svc.start_time
                    if uptime > 300:
                        svc.restart_count = 0
                    delay = min(2 * (2 ** svc.restart_count), 30)
                    svc.restart_count += 1
                    log_entry(svc.tag,
                              f"Restarting in {delay}s (attempt {svc.restart_count}/{svc.max_restarts})...",
                              "warn")
                    svc.update_status_display()
                    time.sleep(delay)
                    if stop_event.is_set():
                        break
                    restart_service(svc)
                    if svc.alive:
                        log_entry(svc.tag, f"Restarted (PID {svc.proc.pid})", "ok")
                else:
                    log_entry(svc.tag, "Max restarts exceeded — giving up", "error")
                    svc.status = "failed"
                    svc.update_status_display()
        stop_event.wait(3)


# ─── Tkinter UI ──────────────────────────────────────────────────────────────

DOT_COLORS = {
    "running": "#16a34a", "external": "#0891b2", "stopped": "#a3a3a3",
    "crashed": "#dc2626", "failed": "#dc2626", "starting": "#ca8a04",
}

class LauncherUI:
    def __init__(self, root, stop_event):
        self.root = root
        self.stop_event = stop_event
        self.root.title("ICCSFlux Service Manager")
        self.root.geometry("900x620")
        self.root.minsize(700, 400)
        try:
            if ICO_PATH.exists():
                self.root.iconbitmap(default=str(ICO_PATH))
        except Exception:
            pass

        self._last_log_id = 0
        self._all_entries = []
        self._total_lines = 0
        self._start_time = time.time()
        self._dashboard_opened = False
        self.svc_widgets = {}

        self._build_header()
        self._build_services()
        self._build_log()
        self._build_statusbar()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_header(self):
        fr = ttk.Frame(self.root)
        fr.pack(fill=tk.X, padx=10, pady=(8, 0))

        left = ttk.Frame(fr)
        left.pack(side=tk.LEFT)
        ttk.Label(left, text="ICCSFlux Service Manager",
                  font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)
        self.subtitle_label = ttk.Label(left, text="Starting...",
                                        font=("Segoe UI", 9), foreground="#666")
        self.subtitle_label.pack(anchor=tk.W)

        right = ttk.Frame(fr)
        right.pack(side=tk.RIGHT)
        ttk.Button(right, text="Logs Folder", command=self._open_logs).pack(side=tk.LEFT, padx=2)
        ttk.Button(right, text="Export", command=self._export_logs).pack(side=tk.LEFT, padx=2)
        self.btn_dashboard = ttk.Button(right, text="Open Dashboard",
                                        command=self._open_dashboard, state=tk.DISABLED)
        self.btn_dashboard.pack(side=tk.LEFT, padx=2)
        ttk.Button(right, text="Restart All",
                   command=self._restart_all).pack(side=tk.LEFT, padx=2)

    def _build_services(self):
        self.svc_frame = ttk.LabelFrame(self.root, text="Services", padding=5)
        self.svc_frame.pack(fill=tk.X, padx=10, pady=5)

    def _build_log(self):
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        # Filter bar
        bar = ttk.Frame(container)
        bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(bar, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar(value="all")
        combo = ttk.Combobox(bar, textvariable=self.filter_var, width=12, state="readonly",
                             values=["all", "error", "warn", "MOSQUITTO", "DAQ", "AZURE", "HTTP", "LAUNCHER"])
        combo.pack(side=tk.LEFT, padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self._refilter())

        ttk.Label(bar, text="Search:").pack(side=tk.LEFT, padx=(8, 0))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refilter())
        ttk.Entry(bar, textvariable=self.search_var, width=18).pack(side=tk.LEFT, padx=4)

        self.line_label = ttk.Label(bar, text="0 lines")
        self.line_label.pack(side=tk.RIGHT)
        self.auto_scroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Auto-scroll", variable=self.auto_scroll).pack(side=tk.RIGHT, padx=8)

        # Log text
        log_fr = ttk.Frame(container)
        log_fr.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_fr, wrap=tk.WORD, font=("Consolas", 10),
                                state=tk.DISABLED, bg="white", relief=tk.SUNKEN, bd=1)
        sb = ttk.Scrollbar(log_fr, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Keyboard shortcuts
        self.log_text.bind("<Control-a>", self._select_all)
        self.log_text.bind("<Control-A>", self._select_all)
        self.log_text.bind("<Control-c>", self._copy_selection)
        self.log_text.bind("<Control-C>", self._copy_selection)

        # Right-click context menu
        self._log_menu = tk.Menu(self.log_text, tearoff=0)
        self._log_menu.add_command(label="Copy", accelerator="Ctrl+C",
                                   command=self._copy_selection)
        self._log_menu.add_command(label="Select All", accelerator="Ctrl+A",
                                   command=self._select_all)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="Clear Log", command=self._clear_log)
        self.log_text.bind("<Button-3>", self._show_log_menu)

        # Color tags
        for tag, color in [("MOSQUITTO", "#7c3aed"), ("DAQ", "#0369a1"),
                           ("AZURE", "#1d4ed8"), ("HTTP", "#15803d"), ("LAUNCHER", "#525252")]:
            self.log_text.tag_configure(f"t_{tag}", foreground=color, font=("Consolas", 10, "bold"))
        self.log_text.tag_configure("ts", foreground="#888")
        for lvl, color, bold in [("error", "#c42b1c", True), ("warn", "#9a6700", False),
                                  ("ok", "#15803d", False), ("start", "#0369a1", False),
                                  ("info", "#555", False)]:
            f = ("Consolas", 10, "bold") if bold else ("Consolas", 10)
            self.log_text.tag_configure(f"m_{lvl}", foreground=color, font=f)

    def _build_statusbar(self):
        fr = ttk.Frame(self.root)
        fr.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.status_label = ttk.Label(fr, text="Starting...", foreground="#666")
        self.status_label.pack(side=tk.LEFT)
        self.uptime_label = ttk.Label(fr, text="", foreground="#666")
        self.uptime_label.pack(side=tk.RIGHT)

    # ── Polling ──────────────────────────────────────────────────────────

    def _poll(self):
        # New log entries
        with _log_lock:
            new = [e for e in _log_buffer if e["id"] > self._last_log_id]
        if new:
            self._all_entries.extend(new)
            self._last_log_id = new[-1]["id"]
            self._total_lines += len(new)
            self.log_text.configure(state=tk.NORMAL)
            for e in new:
                if self._matches(e):
                    self._insert_entry(e)
            self.log_text.configure(state=tk.DISABLED)
            if self.auto_scroll.get():
                self.log_text.see(tk.END)
            self.line_label.configure(text=f"{self._total_lines} lines")
            while len(self._all_entries) > 2000:
                self._all_entries.pop(0)

        # Services
        with _status_lock:
            svcs = list(_service_statuses.values())
        for s in svcs:
            self._update_svc_card(s)

        # Dashboard button + auto-open
        if _dashboard_port:
            self.btn_dashboard.configure(state=tk.NORMAL)
            self.status_label.configure(
                text=f"Ready — http://localhost:{_dashboard_port}", foreground="#15803d")
            if not self._dashboard_opened:
                self._dashboard_opened = True
                webbrowser.open(f"http://localhost:{_dashboard_port}")

        # Subtitle
        parts = []
        if _version_info and _version_info != "dev":
            v = _version_info
            if len(v) < 30 and not v.startswith("ICCSFlux"):
                v = f"v{v}"
            parts.append(v)
        if _project_name:
            parts.append(_project_name)
        self.subtitle_label.configure(text=" \u00b7 ".join(parts) if parts else "Industrial Data Acquisition")

        # Uptime
        secs = int(time.time() - self._start_time)
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        self.uptime_label.configure(text=f"Uptime: {h:02d}:{m:02d}:{s:02d}")

        self.root.after(500, self._poll)

    # ── Service cards ─────────────────────────────────────────────────────

    def _update_svc_card(self, svc):
        tag = svc["tag"]
        if tag not in self.svc_widgets:
            card = ttk.Frame(self.svc_frame)
            card.pack(side=tk.LEFT, padx=6, pady=2)

            dot = tk.Label(card, text="\u25cf", font=("Segoe UI", 14), fg="#a3a3a3")
            dot.pack(side=tk.LEFT, padx=(0, 4))

            info = ttk.Frame(card)
            info.pack(side=tk.LEFT)
            name_lbl = ttk.Label(info, text=svc["name"], font=("Segoe UI", 9, "bold"))
            name_lbl.pack(anchor=tk.W)
            detail_lbl = ttk.Label(info, text="", font=("Segoe UI", 8), foreground="#666")
            detail_lbl.pack(anchor=tk.W)
            res_lbl = ttk.Label(info, text="", font=("Segoe UI", 8), foreground="#888")
            res_lbl.pack(anchor=tk.W)

            # Buttons: Start/Stop toggle + Restart
            btn_frame = ttk.Frame(card)
            btn_frame.pack(side=tk.LEFT, padx=(6, 0))

            start_stop_btn = None
            restart_btn = None
            if tag != "HTTP":
                start_stop_btn = ttk.Button(btn_frame, text="\u25b6", width=3,
                                            command=lambda t=tag: self._start_stop_svc(t))
                start_stop_btn.pack(side=tk.LEFT, padx=1)
                restart_btn = ttk.Button(btn_frame, text="\u21bb", width=3,
                                         command=lambda t=tag: self._restart_svc(t))
                restart_btn.pack(side=tk.LEFT, padx=1)

            self.svc_widgets[tag] = {
                "dot": dot, "detail": detail_lbl, "res": res_lbl,
                "start_stop": start_stop_btn, "restart": restart_btn,
            }

        w = self.svc_widgets[tag]
        w["dot"].configure(fg=DOT_COLORS.get(svc["status"], "#a3a3a3"))

        # Detail text
        detail = svc["status"]
        if svc["status"] in ("running", "external") and svc.get("pid"):
            detail = f"PID {svc['pid']}"
            if svc["status"] == "external":
                detail += " (ext)"
        elif svc["status"] == "crashed":
            detail = f"restarts: {svc['restarts']}/{svc['maxRestarts']}"

        # Health indicator
        healthy = svc.get("healthy")
        if healthy is False and svc["status"] in ("running", "external"):
            detail += " \u2022 unresponsive"
        elif healthy is True:
            detail += " \u2022 healthy"

        w["detail"].configure(text=detail)

        # Resource stats
        if svc["status"] in ("running", "external") and (svc.get("cpu", 0) > 0 or svc.get("mem", 0) > 0):
            w["res"].configure(text=f"{svc['cpu']:.1f}% CPU \u00b7 {svc['mem']:.0f} MB")
        else:
            w["res"].configure(text="")

        # Button states
        if w["start_stop"]:
            if svc["status"] in ("running", "external"):
                w["start_stop"].configure(text="\u25a0", state=tk.NORMAL)  # Stop ■
                w["restart"].configure(state=tk.NORMAL)  # Restart ↻
            elif svc["status"] in ("stopped", "crashed", "failed"):
                w["start_stop"].configure(text="\u25b6", state=tk.NORMAL)  # Start ▶
                w["restart"].configure(state=tk.DISABLED)
            else:
                w["start_stop"].configure(state=tk.DISABLED)
                w["restart"].configure(state=tk.DISABLED)

    # ── Log helpers ───────────────────────────────────────────────────────

    def _matches(self, e):
        f = self.filter_var.get()
        if f == "error" and e["level"] != "error":
            return False
        if f == "warn" and e["level"] not in ("error", "warn"):
            return False
        if f not in ("all", "error", "warn") and e["tag"] != f:
            return False
        search = self.search_var.get().lower()
        if search and search not in e["msg"].lower() and search not in e["tag"].lower():
            return False
        return True

    def _insert_entry(self, e):
        self.log_text.insert(tk.END, e["ts"] + " ", "ts")
        self.log_text.insert(tk.END, f"{e['tag']:10s} ", f"t_{e['tag']}")
        self.log_text.insert(tk.END, e["msg"] + "\n", f"m_{e['level']}")

    def _refilter(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        for e in self._all_entries:
            if self._matches(e):
                self._insert_entry(e)
        self.log_text.configure(state=tk.DISABLED)
        if self.auto_scroll.get():
            self.log_text.see(tk.END)

    # ── Copy / Select All ────────────────────────────────────────────────

    def _select_all(self, event=None):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.tag_add(tk.SEL, "1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.mark_set(tk.INSERT, "1.0")
        self.log_text.see(tk.INSERT)
        return "break"

    def _copy_selection(self, event=None):
        try:
            text = self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            text = self.log_text.get("1.0", tk.END).rstrip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
        return "break"

    def _show_log_menu(self, event):
        self._log_menu.tk_popup(event.x_root, event.y_root)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self._all_entries.clear()
        self._total_lines = 0
        self.line_label.configure(text="0 lines")

    # ── Actions ───────────────────────────────────────────────────────────

    def _open_dashboard(self):
        if _dashboard_port:
            webbrowser.open(f"http://localhost:{_dashboard_port}")

    def _open_logs(self):
        logs_dir = DATA / "logs"
        logs_dir.mkdir(exist_ok=True)
        os.startfile(str(logs_dir))

    def _export_logs(self):
        logs_dir = DATA / "logs"
        logs_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"launcher_export_{ts}.log"
        with _log_lock:
            entries = list(_log_buffer)
        with open(path, 'w', encoding='utf-8') as f:
            for e in entries:
                f.write(f"{e['ts']} [{e['tag']:10s}] [{e['level']:5s}] {e['msg']}\n")
        os.startfile(str(path))
        log_entry("LAUNCHER", f"Logs exported to {path.name}", "ok")

    # ── Start / Stop / Restart per service ───────────────────────────────

    def _start_stop_svc(self, tag):
        """Toggle: if running → stop, if stopped → start."""
        with _status_lock:
            svc_status = _service_statuses.get(tag, {})
        status = svc_status.get("status", "stopped")
        if status in ("running", "external"):
            # Warn about dependents
            dependents = _get_dep_services(tag)
            running_deps = []
            for dep_tag in dependents:
                with _status_lock:
                    ds = _service_statuses.get(dep_tag, {})
                if ds.get("status") in ("running",):
                    running_deps.append(ds.get("name", dep_tag))
            if running_deps:
                names = ", ".join(running_deps)
                ok = messagebox.askyesno(
                    f"Stop {svc_status.get('name', tag)}",
                    f"The following services depend on {svc_status.get('name', tag)}:\n\n"
                    f"  {names}\n\n"
                    f"They may crash or malfunction. Stop anyway?",
                    parent=self.root,
                )
                if not ok:
                    return
            threading.Thread(target=self._do_stop, args=(tag,), daemon=True).start()
        elif status in ("stopped", "crashed", "failed"):
            threading.Thread(target=self._do_start, args=(tag,), daemon=True).start()

    def _do_stop(self, tag):
        for svc in _managed_services:
            if svc.tag == tag:
                svc.stop()
                break

    def _do_start(self, tag):
        log_entry(tag, f"Starting service...", "start")
        start_service_by_tag(tag)

    def _restart_svc(self, tag):
        threading.Thread(target=self._do_restart, args=(tag,), daemon=True).start()

    def _do_restart(self, tag):
        for svc in _managed_services:
            if svc.tag == tag:
                svc._restarting = True
                log_entry(svc.tag, f"Manually restarting {svc.name}...", "start")
                svc.stop()  # Works for both managed and external
                time.sleep(1)
                restart_service(svc)
                svc._restarting = False
                if svc.alive:
                    log_entry(svc.tag, f"Restarted (PID {svc.proc.pid})", "ok")
                else:
                    log_entry(svc.tag, "Failed to restart", "error")
                    svc.status = "failed"
                    svc.update_status_display()

    # ── Restart All ──────────────────────────────────────────────────────

    def _restart_all(self):
        ok = messagebox.askyesno(
            "Restart All Services",
            "This will stop and restart all services.\n\n"
            "The dashboard will briefly disconnect.\n\n"
            "Continue?",
            parent=self.root,
        )
        if not ok:
            return
        threading.Thread(target=self._do_restart_all, daemon=True).start()

    def _do_restart_all(self):
        log_entry("LAUNCHER", "Restarting all services...", "start")

        # Stop in reverse dependency order
        for svc in reversed(_managed_services):
            if svc.status == "external":
                continue
            if svc.tag == "HTTP":
                continue
            svc.stop()

        time.sleep(1)

        # Start in dependency order
        for svc in _managed_services:
            if svc.status == "external":
                log_entry(svc.tag, f"{svc.name} is external — skipping", "info")
                continue
            if svc.tag == "HTTP":
                continue
            log_entry(svc.tag, f"Starting {svc.name}...", "start")
            svc._restarting = True
            restart_service(svc)
            svc._restarting = False
            if svc.alive:
                log_entry(svc.tag, f"Restarted (PID {svc.proc.pid})", "ok")
            else:
                log_entry(svc.tag, f"Failed to restart {svc.name}", "error")
                svc.status = "failed"
                svc.update_status_display()
            time.sleep(1)

        log_entry("LAUNCHER", "All services restarted", "ok")

    # ── Close Dialog ─────────────────────────────────────────────────────

    def _on_close(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Exit ICCSFlux")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg.update_idletasks()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        px = self.root.winfo_x()
        py = self.root.winfo_y()
        dw, dh = 380, 150
        dlg.geometry(f"{dw}x{dh}+{px + (pw - dw)//2}+{py + (ph - dh)//2}")

        try:
            if ICO_PATH.exists():
                dlg.iconbitmap(default=str(ICO_PATH))
        except Exception:
            pass

        result = {"action": None}

        ttk.Label(dlg, text="How do you want to exit?",
                  font=("Segoe UI", 11)).pack(pady=(16, 8))
        ttk.Label(dlg, text="Services started by this launcher can be stopped or left running.",
                  font=("Segoe UI", 9), foreground="#666").pack(pady=(0, 12))

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 12))

        def _stop_exit():
            result["action"] = "stop"
            dlg.destroy()

        def _keep_exit():
            result["action"] = "keep"
            dlg.destroy()

        def _cancel():
            result["action"] = None
            dlg.destroy()

        ttk.Button(btn_frame, text="Stop All & Exit",
                   command=_stop_exit).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Keep Running & Exit",
                   command=_keep_exit).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel",
                   command=_cancel).pack(side=tk.LEFT, padx=4)

        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        dlg.bind("<Escape>", lambda e: _cancel())

        self.root.wait_window(dlg)

        if result["action"] == "stop":
            self.stop_event.set()
            cleanup(kill_services=True)
            self.root.destroy()
        elif result["action"] == "keep":
            self.stop_event.set()
            cleanup(kill_services=False)
            self.root.destroy()


# ─── Main ────────────────────────────────────────────────────────────────────

def start_services_thread(port_requested, stop_event):
    global _dashboard_port, _version_info, _project_name

    _version_info = read_version()
    _project_name = read_project_name()

    if _version_info != "dev":
        log_entry("LAUNCHER", f"Version: {_version_info}", "info")
    if _project_name:
        log_entry("LAUNCHER", f"Project: {_project_name}", "info")

    setup_mqtt_credentials()

    tls_dir = ROOT / "config" / "tls"
    if not (tls_dir / "ca.crt").exists():
        log_entry("LAUNCHER", "Generating TLS certificates (first-run)...", "start")
        try:
            bundle_dir = getattr(sys, '_MEIPASS', None)
            if bundle_dir:
                scripts_path = str(Path(bundle_dir) / "scripts")
            else:
                scripts_path = str(ROOT / "scripts")
            sys.path.insert(0, scripts_path)
            from generate_tls_certs import generate_certificates
            if generate_certificates(tls_dir):
                log_entry("LAUNCHER", "TLS certificates generated", "ok")
            else:
                log_entry("LAUNCHER", "TLS generation failed", "warn")
        except Exception as e:
            log_entry("LAUNCHER", f"TLS generation failed: {e}", "warn")
        finally:
            sys.path.pop(0)

    managed_services = []

    svc_mqtt = start_mosquitto()
    managed_services.append(svc_mqtt)
    time.sleep(1)

    svc_daq = start_daq_service()
    managed_services.append(svc_daq)
    time.sleep(1)

    svc_azure = start_azure_uploader()
    managed_services.append(svc_azure)

    _dashboard_port = start_web_server(port_requested)

    _managed_services.clear()
    _managed_services.extend(managed_services)

    if _dashboard_port:
        log_entry("LAUNCHER", f"ICCSFlux is ready — Dashboard: http://localhost:{_dashboard_port}", "ok")
    else:
        log_entry("LAUNCHER", "Failed to start dashboard server", "error")

    monitor_loop(managed_services, stop_event)


def main():
    parser = argparse.ArgumentParser(description="ICCSFlux Launcher")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("-v", "--version", action="version", version="ICCSFlux Portable 1.0")
    args = parser.parse_args()

    if args.setup:
        setup_mqtt_credentials()
        return 0

    if not acquire_single_instance():
        try:
            root = tk.Tk()
            root.title("ICCSFlux")
            root.geometry("350x100")
            ttk.Label(root, text="ICCSFlux is already running.",
                      font=("Segoe UI", 11)).pack(expand=True)
            root.mainloop()
        except Exception:
            pass
        return 1

    atexit.register(cleanup)
    _setup_file_logging()
    log_entry("LAUNCHER", "ICCSFlux starting...", "start")
    log_entry("LAUNCHER", f"ROOT: {ROOT}", "info")

    stop_event = threading.Event()
    threading.Thread(
        target=start_services_thread, args=(args.port, stop_event),
        daemon=True, name="service-manager",
    ).start()

    root = tk.Tk()
    ui = LauncherUI(root, stop_event)
    root.mainloop()

    stop_event.set()
    cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
