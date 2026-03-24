"""
Service auto-start utilities for pytest fixtures.

Provides functions to silently start/stop Mosquitto and DAQ service
so tests can run without manual NISystem Start.bat.

Safety:
- If a service is already running, it is reused (not restarted)
- Only services we started are terminated on teardown
- TLS listener (8883) is added when certs exist so edge nodes can connect
"""

import atexit
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

PROJECT_ROOT = Path(__file__).parent.parent

# Track temp log files for cleanup on unexpected exit
_temp_log_files: list = []

def _cleanup_temp_logs():
    """Remove temp log files on exit (atexit handler)."""
    for p in _temp_log_files:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass
    _temp_log_files.clear()

def cleanup_stale_test_logs(max_age_hours: float = 24.0):
    """Remove stale daq_test_*.log files from previous crashed runs."""
    logs_dir = PROJECT_ROOT / 'logs'
    if not logs_dir.exists():
        return
    cutoff = time.time() - (max_age_hours * 3600)
    for f in logs_dir.glob('daq_test_*.log'):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        except Exception:
            pass

atexit.register(_cleanup_temp_logs)
# Clean up stale logs from previous crashed runs on import
cleanup_stale_test_logs()

# Windows CREATE_NO_WINDOW flag (suppress console windows)
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

# Paths
_CRED_FILE = PROJECT_ROOT / 'config' / 'mqtt_credentials.json'
_PASSWD_FILE = PROJECT_ROOT / 'config' / 'mosquitto_passwd'
_TEST_CONF = PROJECT_ROOT / 'config' / 'mosquitto_test.conf'
_TLS_CA = PROJECT_ROOT / 'config' / 'tls' / 'ca.crt'
_TLS_CERT = PROJECT_ROOT / 'config' / 'tls' / 'server.crt'
_TLS_KEY = PROJECT_ROOT / 'config' / 'tls' / 'server.key'

def find_mosquitto() -> Optional[Path]:
    """Find Mosquitto executable, preferring project-local vendor copy."""
    candidates = [
        PROJECT_ROOT / 'vendor' / 'mosquitto' / 'mosquitto.exe',
        Path(r'C:\Program Files\mosquitto\mosquitto.exe'),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def is_port_open(host: str = '127.0.0.1', port: int = 1883) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Poll until port is open or timeout expires."""
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(host, port):
            return True
        time.sleep(0.2)
    return False

def load_mqtt_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Load backend MQTT credentials from config/mqtt_credentials.json.

    Returns (username, password) or (None, None) if unavailable.
    """
    if _CRED_FILE.exists():
        try:
            creds = json.loads(_CRED_FILE.read_text())
            return creds['backend']['username'], creds['backend']['password']
        except (KeyError, json.JSONDecodeError, FileNotFoundError):
            pass
    return None, None

def _has_auth_config() -> bool:
    """Check if both credential file and password file exist."""
    return _CRED_FILE.exists() and _PASSWD_FILE.exists()

def _has_tls_certs() -> bool:
    """Check if TLS certificates exist for the 8883 listener."""
    return _TLS_CA.exists() and _TLS_CERT.exists() and _TLS_KEY.exists()

def _write_test_mosquitto_conf(port: int = 1883) -> Path:
    """Write a Mosquitto config for testing.

    Listeners:
      - port 1883 (127.0.0.1): local services — auth if credentials exist
      - port 8883 (0.0.0.0):   edge nodes (cRIO/Opto22/CFP) — TLS + auth
        Only added when TLS certs AND auth credentials both exist.
      - port 9002 (127.0.0.1): WebSocket — anonymous, for dashboard
        Matches production config so the dashboard can connect during tests.

    Written to config/mosquitto_test.conf so relative password_file
    paths resolve correctly (Mosquitto resolves relative paths from CWD).
    """
    has_auth = _has_auth_config()
    has_tls = _has_tls_certs()

    # per_listener_settings required when mixing auth/anon across listeners
    lines = ["per_listener_settings true"]

    # Listener 1: local TCP (1883)
    lines.append(f"listener {port} 127.0.0.1")

    if has_auth:
        lines += [
            "allow_anonymous false",
            "password_file config/mosquitto_passwd",
        ]
    else:
        lines.append("allow_anonymous true")

    # Listener 2: TLS for edge nodes (8883)
    if has_auth and has_tls:
        lines += [
            "",
            "listener 8883 0.0.0.0",
            "cafile config/tls/ca.crt",
            "certfile config/tls/server.crt",
            "keyfile config/tls/server.key",
            "allow_anonymous false",
            "password_file config/mosquitto_passwd",
        ]

    # Listener 3: WebSocket for dashboard (9002)
    lines += [
        "",
        "listener 9002 127.0.0.1",
        "protocol websockets",
        "allow_anonymous true",
    ]

    lines += [
        "",
        "log_dest stderr",
        "log_type error",
        "log_type warning",
        "max_keepalive 120",
        "message_size_limit 2097152",
    ]

    _TEST_CONF.write_text('\n'.join(lines) + '\n')
    return _TEST_CONF

def _kill_stale_mosquitto() -> None:
    """Kill any stale Mosquitto processes from previous test runs."""
    if sys.platform != 'win32':
        return
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', 'mosquitto.exe'],
            capture_output=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        time.sleep(0.5)
    except Exception:
        pass

def start_mosquitto(port: int = 1883) -> Tuple[Optional[subprocess.Popen], bool, Dict[str, Any]]:
    """Start Mosquitto broker if not already running.

    Returns:
        (process, we_started_it, connection_info)
        connection_info = {"host": str, "port": int,
                          "username": str|None, "password": str|None}
    """
    username, password = load_mqtt_credentials() if _has_auth_config() else (None, None)
    conn_info = {
        "host": "127.0.0.1",
        "port": port,
        "username": username,
        "password": password,
    }

    # Already running and healthy?
    if is_port_open('127.0.0.1', port):
        return None, False, conn_info

    # Port not open — kill any stale broker + DAQ processes from previous runs
    _kill_stale_mosquitto()
    _kill_stale_daq_processes()

    # Find executable
    exe = find_mosquitto()
    if exe is None:
        return None, False, conn_info

    # Write test config
    conf = _write_test_mosquitto_conf(port)

    # Start subprocess (no console window)
    creationflags = _NO_WINDOW if sys.platform == 'win32' else 0
    proc = subprocess.Popen(
        [str(exe), "-c", str(conf)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )

    # Wait for port to open
    if not wait_for_port('127.0.0.1', port, timeout=5.0):
        # Check if process died immediately
        if proc.poll() is not None:
            output = proc.stdout.read().decode(errors='replace') if proc.stdout else ''
            raise RuntimeError(
                f"Mosquitto failed to start (exit code {proc.returncode}):\n{output[:500]}"
            )
        raise RuntimeError(f"Mosquitto started but port {port} not open after 5s")

    return proc, True, conn_info

def stop_mosquitto(proc: Optional[subprocess.Popen]) -> None:
    """Terminate Mosquitto process gracefully."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)
    except Exception:
        pass

    # Clean up test config
    try:
        _TEST_CONF.unlink(missing_ok=True)
    except Exception:
        pass

def _kill_stale_daq_processes() -> None:
    """Kill any stale DAQ service processes from previous test runs.

    On Windows, finds python.exe processes whose command line includes
    'daq_service.py' and terminates them. This prevents stale processes
    from blocking port or resource access on subsequent test runs.
    """
    if sys.platform != 'win32':
        return
    try:
        # Use tasklist + findstr to find DAQ service processes
        result = subprocess.run(
            ['wmic', 'process', 'where',
             "name='python.exe' and commandline like '%daq_service.py%'",
             'get', 'processid'],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                # Don't kill ourselves
                if pid == os.getpid():
                    continue
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=_NO_WINDOW,
                    )
                except Exception:
                    pass
        # Give OS a moment to release resources
        time.sleep(0.5)
    except Exception:
        pass

def start_daq_service(
    mqtt_host: str = '127.0.0.1',
    mqtt_port: int = 1883,
    username: Optional[str] = None,
    password: Optional[str] = None,
    startup_timeout: float = 60.0,
) -> Tuple[Optional[subprocess.Popen], bool]:
    """Start DAQ service if not already running.

    Returns (process, we_started_it).
    Detects running service by checking for status messages on MQTT.
    Verifies startup by waiting for the first status publication.

    IMPORTANT: stdout is redirected to a temp file (not PIPE) to avoid
    the classic subprocess pipe-buffer deadlock. The DAQ service logs
    heavily; a 64 KB pipe buffer fills in seconds, blocking the process.
    """
    # Check if DAQ service is already publishing
    if _is_daq_service_running(mqtt_host, mqtt_port, username, password):
        return None, False

    # Kill any stale DAQ processes from previous interrupted test runs
    _kill_stale_daq_processes()

    # Find Python interpreter
    venv_python = PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe'
    if not venv_python.exists():
        return None, False

    # Build environment
    env = os.environ.copy()
    if username and password:
        env['MQTT_USERNAME'] = username
        env['MQTT_PASSWORD'] = password

    # Start subprocess — run as script (not module) so Python adds
    # services/daq_service/ to sys.path for relative imports.
    # This matches how start.bat launches it.
    daq_script = PROJECT_ROOT / 'services' / 'daq_service' / 'daq_service.py'
    config_ini = PROJECT_ROOT / 'config' / 'system.ini'
    cmd = [str(venv_python), str(daq_script)]
    if config_ini.exists():
        cmd += ['-c', str(config_ini)]

    # Redirect stdout to a temp file to avoid pipe-buffer deadlock.
    # The DAQ service writes thousands of log lines; a PIPE would fill
    # its 64 KB buffer and block the process before it reaches MQTT connect.
    log_file = tempfile.NamedTemporaryFile(
        mode='w', prefix='daq_test_', suffix='.log',
        dir=str(PROJECT_ROOT / 'logs'), delete=False,
    )
    log_path = Path(log_file.name)
    _temp_log_files.append(log_path)

    creationflags = _NO_WINDOW if sys.platform == 'win32' else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    # Attach log path to process for cleanup
    proc._daq_log_path = log_path

    # Wait for the service to initialize and start publishing status.
    # Subscribe and wait for a LIVE (non-retained) status message to confirm
    # the new process is actually running — retained messages may be stale.
    import threading
    try:
        import paho.mqtt.client as mqtt

        ready = threading.Event()
        probe = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f'daq-startup-probe-{int(time.time())}',
        )
        if username and password:
            probe.username_pw_set(username, password)

        def on_message(client, userdata, msg):
            # Skip retained messages — they may be stale from a previous
            # DAQ session that is no longer running.  Only a fresh
            # (non-retained) publish with node_type="daq" proves the new
            # process is alive (cRIO nodes publish to the same topic pattern).
            if msg.retain:
                return
            try:
                import json as _json
                payload = _json.loads(msg.payload.decode())
                if payload.get('node_type') == 'daq':
                    ready.set()
            except Exception:
                pass  # Malformed payload — ignore

        probe.on_message = on_message
        probe.connect(mqtt_host, mqtt_port, keepalive=10)
        probe.loop_start()
        probe.subscribe(_DAQ_STATUS_TOPIC, qos=1)

        deadline = time.time() + startup_timeout
        while time.time() < deadline:
            # Process died?
            if proc.poll() is not None:
                probe.loop_stop()
                probe.disconnect()
                log_file.close()
                output = log_path.read_text(errors='replace')[:500]
                raise RuntimeError(
                    f"DAQ service failed to start (exit code {proc.returncode}):\n{output}"
                )
            if ready.wait(timeout=1.0):
                break

        probe.loop_stop()
        probe.disconnect()
    except RuntimeError:
        raise  # Re-raise our own errors
    except Exception:
        # If probe setup fails, fall back to a simple sleep
        time.sleep(min(10, startup_timeout))
        if proc.poll() is not None:
            log_file.close()
            output = log_path.read_text(errors='replace')[:500]
            raise RuntimeError(
                f"DAQ service failed to start (exit code {proc.returncode}):\n{output}"
            )

    return proc, True

def stop_daq_service(proc: Optional[subprocess.Popen]) -> None:
    """Terminate DAQ service process gracefully."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)
    except Exception:
        pass

    # Clean up temp log file
    log_path = getattr(proc, '_daq_log_path', None)
    if log_path:
        try:
            Path(log_path).unlink(missing_ok=True)
        except Exception:
            pass

# Topic pattern matching any DAQ service status publication.
# The DAQ service publishes to: {base}/nodes/{node_id}/status/system
# e.g. nisystem/nodes/node-001/status/system
_DAQ_STATUS_TOPIC = 'nisystem/+/+/status/system'

def _is_daq_service_running(
    host: str, port: int,
    username: Optional[str], password: Optional[str],
) -> bool:
    """Check if DAQ service is actively publishing status via MQTT.

    Ignores retained messages (stale from previous sessions) and waits
    for a live status publish to confirm the service is actually running.
    """
    try:
        import paho.mqtt.client as mqtt
        import threading

        received = threading.Event()
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f'daq-service-probe-{int(time.time())}',
        )
        if username and password:
            client.username_pw_set(username, password)

        def on_message(client, userdata, msg):
            # Skip retained messages — they may be stale from a previous
            # session that has since exited.  Only a live (non-retained)
            # publish proves the service is actually running right now.
            # Also require node_type="daq" — cRIO nodes publish to the same
            # topic pattern and would otherwise cause a false positive.
            if msg.retain:
                return
            try:
                import json as _json
                payload = _json.loads(msg.payload.decode())
                if payload.get('node_type') == 'daq':
                    received.set()
            except Exception:
                pass  # Malformed payload — ignore

        client.on_message = on_message
        client.connect(host, port, keepalive=5)
        client.loop_start()
        client.subscribe(_DAQ_STATUS_TOPIC)

        # DAQ publishes status every ~1s, so 5s is plenty
        found = received.wait(timeout=5.0)

        client.loop_stop()
        client.disconnect()
        return found
    except Exception:
        return False
