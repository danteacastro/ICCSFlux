#!/usr/bin/env python3
"""
NISystem Service Manager
Unified service lifecycle management for MQTT broker and DAQ service.
Supports single-click start/stop with health monitoring.
"""

import sys
import os
import subprocess
import time
import json
import threading
import signal
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

# Add launcher directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from single_instance import SingleInstance

# Configuration
APP_NAME = "NISystem"
MQTT_BROKER = "localhost"
MQTT_PORT = 1884  # WebSocket-enabled port (matches mosquitto_ws.conf)
MQTT_WS_PORT = 9002  # WebSocket port for browser connections
HEALTH_TIMEOUT_SEC = 10.0
HEARTBEAT_INTERVAL_SEC = 2.0


def get_project_root() -> Path:
    """Get the project root directory"""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        for check_dir in [exe_dir, exe_dir.parent] + list(exe_dir.parents):
            if (check_dir / "config" / "system.ini").exists():
                return check_dir
        return exe_dir
    else:
        return Path(__file__).parent.parent


def get_python_exe() -> str:
    """Get the Python executable path"""
    root = get_project_root()
    if sys.platform == 'win32':
        venv_python = root / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / "venv" / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def find_mosquitto() -> Optional[str]:
    """Find mosquitto executable"""
    # Check common locations
    if sys.platform == 'win32':
        paths = [
            Path(os.environ.get('PROGRAMFILES', '')) / 'mosquitto' / 'mosquitto.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'mosquitto' / 'mosquitto.exe',
            Path(r'C:\mosquitto\mosquitto.exe'),
        ]
    else:
        paths = [
            Path('/usr/sbin/mosquitto'),
            Path('/usr/bin/mosquitto'),
            Path('/usr/local/sbin/mosquitto'),
        ]

    for path in paths:
        if path.exists():
            return str(path)

    # Try to find in PATH
    mosquitto = shutil.which('mosquitto')
    return mosquitto


class ServiceManager:
    """Manages MQTT broker and DAQ service lifecycle"""

    def __init__(self, on_status_change: Optional[Callable[[str], None]] = None):
        self.mqtt_process: Optional[subprocess.Popen] = None
        self.daq_process: Optional[subprocess.Popen] = None
        self.health_thread: Optional[threading.Thread] = None

        self._running = threading.Event()
        self._shutdown_requested = threading.Event()

        self.last_heartbeat: Optional[datetime] = None
        self.service_healthy = False
        self.status = "stopped"  # stopped, starting, running, error

        self._on_status_change = on_status_change
        self._mqtt_client = None

        self.project_root = get_project_root()
        self.config_path = self.project_root / "config" / "system.ini"
        self.daq_service_path = self.project_root / "services" / "daq_service" / "daq_service.py"
        self.log_dir = self.project_root / "logs"

    def _set_status(self, status: str):
        """Update status and notify callback"""
        self.status = status
        if self._on_status_change:
            self._on_status_change(status)

    def start_mosquitto(self) -> bool:
        """Start Mosquitto MQTT broker with WebSocket support"""
        if self.mqtt_process and self.mqtt_process.poll() is None:
            print("Mosquitto already running")
            return True

        mosquitto_path = find_mosquitto()
        if not mosquitto_path:
            print("ERROR: Mosquitto not found. Please install it first.")
            return False

        print(f"Starting Mosquitto from {mosquitto_path}...")

        try:
            # Check if mosquitto is already running on the port
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((MQTT_BROKER, MQTT_PORT))
            sock.close()

            if result == 0:
                print(f"MQTT broker already running on port {MQTT_PORT}")
                return True

            # Start mosquitto with config file for WebSocket support
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / "mosquitto.log"

            # Use config file with WebSocket support
            # Check for secure config first, then fall back to basic config
            secure_config = self.project_root / "config" / "mosquitto_secure.conf"
            basic_config = self.project_root / "mosquitto_ws.conf"
            passwd_file = self.project_root / "config" / "mosquitto_passwd"

            if passwd_file.exists() and secure_config.exists():
                config_file = secure_config
                print(f"  Using SECURE config: {config_file}")
            elif basic_config.exists():
                config_file = basic_config
                print(f"  Using basic config: {config_file}")
            else:
                # No config file, use port directly (no WebSocket support)
                config_file = None
                print(f"  WARNING: No config file found, starting without WebSocket support")

            if config_file:
                cmd = [mosquitto_path, '-v', '-c', str(config_file)]
            else:
                cmd = [mosquitto_path, '-v', '-p', str(MQTT_PORT)]

            if sys.platform == 'win32':
                self.mqtt_process = subprocess.Popen(
                    cmd,
                    stdout=open(log_file, 'w'),
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                self.mqtt_process = subprocess.Popen(
                    cmd,
                    stdout=open(log_file, 'w'),
                    stderr=subprocess.STDOUT
                )

            # Wait for mosquitto to start
            time.sleep(1.0)

            if self.mqtt_process.poll() is not None:
                print(f"ERROR: Mosquitto failed to start. Check {log_file}")
                return False

            print(f"Mosquitto started successfully on port {MQTT_PORT} (TCP) and {MQTT_WS_PORT} (WebSocket)")
            return True

        except Exception as e:
            print(f"ERROR starting Mosquitto: {e}")
            return False

    def start_daq_service(self) -> bool:
        """Start DAQ service"""
        if self.daq_process and self.daq_process.poll() is None:
            print("DAQ service already running")
            return True

        if not self.daq_service_path.exists():
            print(f"ERROR: DAQ service not found at {self.daq_service_path}")
            return False

        if not self.config_path.exists():
            print(f"ERROR: Config not found at {self.config_path}")
            return False

        print("Starting DAQ service...")

        try:
            python_exe = get_python_exe()
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / "daq_service.log"

            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            if sys.platform == 'win32':
                # Start DAQ service in a VISIBLE console window so errors are visible
                # Use 'start' command to open a new window that stays open on error
                cmd = f'start "NISystem DAQ Service" cmd /k "{python_exe}" "{self.daq_service_path}" -c "{self.config_path}"'
                self.daq_process = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    env=env,
                    shell=True
                )
            else:
                self.daq_process = subprocess.Popen(
                    [python_exe, str(self.daq_service_path), '-c', str(self.config_path)],
                    cwd=str(self.project_root),
                    env=env
                )

            # Wait for service to start
            time.sleep(2.0)

            if self.daq_process.poll() is not None:
                print(f"ERROR: DAQ service failed to start. Check {log_file}")
                return False

            print("DAQ service started successfully")
            return True

        except Exception as e:
            print(f"ERROR starting DAQ service: {e}")
            return False

    def start_health_monitor(self):
        """Start health monitoring thread"""
        if self.health_thread and self.health_thread.is_alive():
            return

        self._running.set()
        self.health_thread = threading.Thread(target=self._health_loop, daemon=True, name="health")
        self.health_thread.start()

    def _health_loop(self):
        """Monitor service health via MQTT heartbeat"""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("WARNING: paho-mqtt not available, health monitoring disabled")
            return

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                client.subscribe("nisystem/heartbeat")
                client.subscribe("nisystem/status/system")

        def on_message(client, userdata, msg):
            try:
                if "heartbeat" in msg.topic:
                    self.last_heartbeat = datetime.now()
                    self.service_healthy = True
            except Exception:
                pass

        # Use callback API version 2 to avoid deprecation warning
        self._mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._mqtt_client.on_connect = on_connect
        self._mqtt_client.on_message = on_message

        try:
            self._mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self._mqtt_client.loop_start()
        except Exception as e:
            print(f"WARNING: Could not connect to MQTT for health monitoring: {e}")
            return

        while self._running.is_set() and not self._shutdown_requested.is_set():
            # Check heartbeat timeout
            if self.last_heartbeat:
                elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
                if elapsed > HEALTH_TIMEOUT_SEC:
                    self.service_healthy = False
                    if self.status == "running":
                        self._set_status("error")

            # Check process health
            if self.daq_process and self.daq_process.poll() is not None:
                print("DAQ process died unexpectedly!")
                self.service_healthy = False
                self._set_status("error")

            time.sleep(1.0)

        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()

    def _cleanup_zombie_processes(self):
        """Kill any stale NISystem-related processes before starting new ones.

        Similar to how InfluxDB/Grafana clean up on startup, this ensures
        no orphaned processes from previous runs (e.g., CMD window closed).
        """
        try:
            import psutil
            current_pid = os.getpid()
            killed_count = 0
            project_root_str = str(self.project_root).lower()

            # Patterns to match NISystem-related processes
            daq_patterns = ['daq_service.py', 'daq_service']
            node_patterns = ['vite', 'npm', 'node_modules']

            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'exe']):
                try:
                    if proc.pid == current_pid:
                        continue

                    name = (proc.info.get('name') or '').lower()
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = ' '.join(str(c) for c in cmdline).lower()
                    cwd = (proc.info.get('cwd') or '').lower()
                    exe = (proc.info.get('exe') or '').lower()

                    should_kill = False
                    reason = ""

                    # Check for DAQ service processes
                    if any(p in cmdline_str for p in daq_patterns):
                        should_kill = True
                        reason = "DAQ service"

                    # Check for node processes in our project directory
                    elif name == 'node.exe' or name == 'node':
                        # Only kill node processes related to our project
                        if project_root_str in cmdline_str or project_root_str in cwd:
                            should_kill = True
                            reason = "Node (NISystem)"
                        elif any(p in cmdline_str for p in node_patterns) and 'nisystem' in cmdline_str.lower():
                            should_kill = True
                            reason = "Node (Vite/npm)"

                    if should_kill:
                        print(f"Found orphaned {reason} process (PID: {proc.pid})")
                        if cmdline:
                            # Truncate long command lines
                            cmd_display = cmdline_str[:100] + '...' if len(cmdline_str) > 100 else cmdline_str
                            print(f"  Command: {cmd_display}")
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                            print(f"  [OK] Killed PID {proc.pid}")
                            killed_count += 1
                        except psutil.TimeoutExpired:
                            print(f"  [FAIL] Timeout killing PID {proc.pid}")

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            if killed_count > 0:
                print(f"\nCleaned up {killed_count} orphaned process(es)")
                time.sleep(1)  # Wait for cleanup
            else:
                print("No orphaned processes found")

        except ImportError:
            print("WARNING: psutil not installed - cannot cleanup zombie processes")
            print("         Install with: pip install psutil")

    def start_all(self) -> bool:
        """Start all services with automatic cleanup of zombies"""
        self._set_status("starting")
        self._shutdown_requested.clear()

        # Clean up any zombie processes first
        print("\nChecking for zombie processes...")
        self._cleanup_zombie_processes()

        # Start Mosquitto first
        if not self.start_mosquitto():
            self._set_status("error")
            return False

        # Wait a moment for MQTT to be ready
        time.sleep(0.5)

        # Start DAQ service
        if not self.start_daq_service():
            self._set_status("error")
            return False

        # Start health monitoring
        self.start_health_monitor()

        self._set_status("running")
        return True

    def stop_all(self, timeout: float = 10.0) -> bool:
        """Stop all services gracefully"""
        self._set_status("stopping")
        self._shutdown_requested.set()
        self._running.clear()

        success = True

        # Stop DAQ service first (graceful via signal)
        if self.daq_process and self.daq_process.poll() is None:
            print("Stopping DAQ service...")
            try:
                if sys.platform == 'win32':
                    self.daq_process.terminate()
                else:
                    self.daq_process.send_signal(signal.SIGTERM)

                # Wait for graceful shutdown
                try:
                    self.daq_process.wait(timeout=timeout)
                    print("DAQ service stopped gracefully")
                except subprocess.TimeoutExpired:
                    print("DAQ service did not stop gracefully, forcing...")
                    self.daq_process.kill()
                    self.daq_process.wait()
            except Exception as e:
                print(f"Error stopping DAQ service: {e}")
                success = False

        # Stop Mosquitto
        if self.mqtt_process and self.mqtt_process.poll() is None:
            print("Stopping Mosquitto...")
            try:
                self.mqtt_process.terminate()
                self.mqtt_process.wait(timeout=5.0)
                print("Mosquitto stopped")
            except subprocess.TimeoutExpired:
                self.mqtt_process.kill()
                self.mqtt_process.wait()
            except Exception as e:
                print(f"Error stopping Mosquitto: {e}")
                success = False

        self._set_status("stopped")
        return success

    def is_running(self) -> bool:
        """Check if services are running"""
        daq_running = self.daq_process and self.daq_process.poll() is None
        return daq_running

    def get_status(self) -> dict:
        """Get current service status"""
        return {
            "status": self.status,
            "daq_running": self.daq_process and self.daq_process.poll() is None,
            "mqtt_running": self.mqtt_process and self.mqtt_process.poll() is None,
            "healthy": self.service_healthy,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None
        }


def cleanup_orphaned_processes():
    """Standalone function to clean up orphaned NISystem processes.

    Can be called from batch scripts before starting services:
        python -c "from launcher.service_manager import cleanup_orphaned_processes; cleanup_orphaned_processes()"
    """
    manager = ServiceManager()
    print("=" * 50)
    print("Cleaning up orphaned NISystem processes...")
    print("=" * 50)
    manager._cleanup_zombie_processes()


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='NISystem Service Manager')
    parser.add_argument('command', choices=['start', 'stop', 'status', 'restart', 'cleanup'],
                        help='Command to execute')
    parser.add_argument('--no-mqtt', action='store_true',
                        help='Don\'t start/stop Mosquitto (assume external broker)')

    args = parser.parse_args()

    # Ensure single instance
    instance = SingleInstance("NISystemManager")
    if not instance.acquire():
        print("ERROR: Another instance of Service Manager is already running.")
        sys.exit(1)

    manager = ServiceManager()

    if args.command == 'start':
        print("=" * 50)
        print("Starting NISystem Services...")
        print("=" * 50)

        if manager.start_all():
            print("\nAll services started successfully!")
            print("Press Ctrl+C to stop...")

            # Keep running until interrupted
            def signal_handler(sig, frame):
                print("\nReceived shutdown signal...")
                manager.stop_all()
                sys.exit(0)

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            while manager.is_running():
                time.sleep(1)

        else:
            print("\nFailed to start services!")
            sys.exit(1)

    elif args.command == 'stop':
        print("Stopping NISystem Services...")
        manager.stop_all()
        print("Services stopped.")

    elif args.command == 'status':
        status = manager.get_status()
        print(f"Status: {status['status']}")
        print(f"DAQ Service: {'running' if status['daq_running'] else 'stopped'}")
        print(f"MQTT Broker: {'running' if status['mqtt_running'] else 'stopped'}")
        print(f"Healthy: {status['healthy']}")
        if status['last_heartbeat']:
            print(f"Last Heartbeat: {status['last_heartbeat']}")

    elif args.command == 'restart':
        print("Restarting NISystem Services...")
        manager.stop_all()
        time.sleep(1)
        if manager.start_all():
            print("Services restarted successfully!")
        else:
            print("Failed to restart services!")
            sys.exit(1)

    elif args.command == 'cleanup':
        print("=" * 50)
        print("Cleaning up orphaned NISystem processes...")
        print("=" * 50)
        manager._cleanup_zombie_processes()
        print("\nCleanup complete.")


if __name__ == "__main__":
    main()
