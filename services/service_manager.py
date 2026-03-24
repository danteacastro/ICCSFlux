#!/usr/bin/env python3
"""
NISystem Service Manager

Unified service management for Windows deployment:
- Install/uninstall Windows services (using NSSM)
- Start/stop/restart services
- View service status and logs
- Manage MQTT broker (Mosquitto)
- Build and deploy dashboard

Usage:
    python service_manager.py install      # Install all services
    python service_manager.py uninstall    # Remove all services
    python service_manager.py start        # Start all services
    python service_manager.py stop         # Stop all services
    python service_manager.py status       # Show service status
    python service_manager.py logs         # View recent logs
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# ANSI colors
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def colored(text: str, color: str) -> str:
    if sys.platform == 'win32':
        os.system('')  # Enable ANSI on Windows
    return f"{color}{text}{Colors.END}"

def success(msg: str): print(colored(f"[OK] {msg}", Colors.GREEN))
def error(msg: str): print(colored(f"[ERROR] {msg}", Colors.RED))
def warning(msg: str): print(colored(f"[WARN] {msg}", Colors.YELLOW))
def info(msg: str): print(colored(f"[INFO] {msg}", Colors.CYAN))
def header(msg: str):
    print(colored(f"\n{'='*60}", Colors.BLUE))
    print(colored(f"  {msg}", Colors.BOLD))
    print(colored(f"{'='*60}", Colors.BLUE))

class ServiceConfig:
    """Service configuration paths"""
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.services_dir = self.project_root / 'services'
        self.config_dir = self.project_root / 'config'
        self.dashboard_dir = self.project_root / 'dashboard'
        self.logs_dir = self.project_root / 'logs'
        self.tools_dir = self.project_root / 'tools'

        # Python paths
        self.venv_python = self.project_root / 'venv' / 'Scripts' / 'python.exe'
        if not self.venv_python.exists():
            self.venv_python = Path(sys.executable)

        # Service definitions
        self.daq_service = self.services_dir / 'daq_service' / 'daq_service.py'
        self.config_file = self.config_dir / 'system.ini'

        # NSSM (Non-Sucking Service Manager)
        self.nssm_dir = self.tools_dir / 'nssm'
        self.nssm_exe = self.nssm_dir / 'nssm.exe'
        self.nssm_url = 'https://nssm.cc/release/nssm-2.24.zip'

        # Mosquitto
        self.mosquitto_dir = Path(os.environ.get('PROGRAMFILES', 'C:\\Program Files')) / 'mosquitto'
        self.mosquitto_exe = self.mosquitto_dir / 'mosquitto.exe'
        self.mosquitto_conf = self.mosquitto_dir / 'mosquitto.conf'

        # Service names
        self.daq_service_name = 'NISystemDAQ'
        self.mosquitto_service_name = 'Mosquitto'

        # Ensure directories exist
        self.logs_dir.mkdir(exist_ok=True)
        self.tools_dir.mkdir(exist_ok=True)

class ServiceManager:
    """Manages Windows services for NISystem"""

    def __init__(self):
        self.config = ServiceConfig()

    def _run_cmd(self, cmd: List[str], check: bool = True, capture: bool = True) -> Tuple[int, str]:
        """Run a command and return (returncode, output)"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                timeout=60
            )
            output = (result.stdout or '') + (result.stderr or '')
            if check and result.returncode != 0:
                return result.returncode, output
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, "Command timed out"
        except Exception as e:
            return -1, str(e)

    def _run_elevated(self, cmd: List[str]) -> Tuple[int, str]:
        """Run command with elevation (admin) if needed"""
        # Try running normally first
        code, output = self._run_cmd(cmd, check=False)
        if code == 0:
            return code, output

        # If access denied, suggest running as admin
        if 'Access is denied' in output or code == 5:
            error("Administrator privileges required. Please run as Administrator.")
            return code, output

        return code, output

    # ==================== NSSM Management ====================

    def ensure_nssm(self) -> bool:
        """Download and extract NSSM if not present"""
        if self.config.nssm_exe.exists():
            return True

        info("Downloading NSSM (Non-Sucking Service Manager)...")

        try:
            zip_path = self.config.tools_dir / 'nssm.zip'

            # Download
            urllib.request.urlretrieve(self.config.nssm_url, zip_path)

            # Extract
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(self.config.tools_dir)

            # Find the exe (it's in a versioned subdirectory)
            for item in self.config.tools_dir.iterdir():
                if item.is_dir() and item.name.startswith('nssm'):
                    # Copy 64-bit version
                    src = item / 'win64' / 'nssm.exe'
                    if src.exists():
                        self.config.nssm_dir.mkdir(exist_ok=True)
                        shutil.copy(src, self.config.nssm_exe)
                        success(f"NSSM installed to {self.config.nssm_exe}")

                        # Cleanup
                        zip_path.unlink()
                        shutil.rmtree(item)
                        return True

            error("Could not find nssm.exe in downloaded archive")
            return False

        except Exception as e:
            error(f"Failed to download NSSM: {e}")
            return False

    def _nssm(self, *args) -> Tuple[int, str]:
        """Run NSSM command"""
        if not self.config.nssm_exe.exists():
            if not self.ensure_nssm():
                return -1, "NSSM not available"

        cmd = [str(self.config.nssm_exe)] + list(args)
        return self._run_elevated(cmd)

    # ==================== Mosquitto Management ====================

    def check_mosquitto_installed(self) -> bool:
        """Check if Mosquitto is installed"""
        return self.config.mosquitto_exe.exists()

    def configure_mosquitto(self) -> bool:
        """Configure Mosquitto for network access"""
        if not self.check_mosquitto_installed():
            warning("Mosquitto not installed")
            print("  Download from: https://mosquitto.org/download/")
            print("  Or use: winget install EclipseFoundation.Mosquitto")
            return False

        info("Configuring Mosquitto...")

        # Create config that allows network connections
        config_content = """# NISystem Mosquitto Configuration
# Generated by service_manager.py

# Listen on all interfaces
listener 1883 0.0.0.0

# Allow anonymous connections (for local network)
allow_anonymous true

# Logging
log_dest file C:/ProgramData/mosquitto/mosquitto.log
log_type error
log_type warning
log_type notice
log_type information

# Persistence
persistence true
persistence_location C:/ProgramData/mosquitto/

# Connection settings
max_connections -1
"""

        try:
            # Backup existing config
            if self.config.mosquitto_conf.exists():
                backup = self.config.mosquitto_conf.with_suffix('.conf.backup')
                if not backup.exists():
                    shutil.copy(self.config.mosquitto_conf, backup)

            # Write new config
            with open(self.config.mosquitto_conf, 'w') as f:
                f.write(config_content)

            success("Mosquitto configured for network access")
            return True

        except PermissionError:
            error("Permission denied. Run as Administrator to configure Mosquitto.")
            return False
        except Exception as e:
            error(f"Failed to configure Mosquitto: {e}")
            return False

    def install_mosquitto_service(self) -> bool:
        """Ensure Mosquitto is running as a service"""
        if not self.check_mosquitto_installed():
            return False

        info("Checking Mosquitto service...")

        # Check if service exists
        code, output = self._run_cmd(['sc', 'query', self.config.mosquitto_service_name], check=False)

        if code == 0:
            success("Mosquitto service already installed")
            return True

        # Install as service using mosquitto's built-in capability
        info("Installing Mosquitto service...")
        code, output = self._run_elevated([
            str(self.config.mosquitto_exe),
            'install'
        ])

        if code == 0:
            success("Mosquitto service installed")
            return True
        else:
            warning(f"Mosquitto service install returned: {output}")
            return True  # May already be installed

    def start_mosquitto(self) -> bool:
        """Start Mosquitto service"""
        info("Starting Mosquitto...")
        code, output = self._run_elevated(['net', 'start', self.config.mosquitto_service_name])

        if code == 0 or 'already been started' in output:
            success("Mosquitto running")
            return True
        else:
            error(f"Failed to start Mosquitto: {output}")
            return False

    def stop_mosquitto(self) -> bool:
        """Stop Mosquitto service"""
        info("Stopping Mosquitto...")
        code, output = self._run_elevated(['net', 'stop', self.config.mosquitto_service_name])

        if code == 0 or 'is not started' in output:
            success("Mosquitto stopped")
            return True
        return False

    # ==================== DAQ Service Management ====================

    def install_daq_service(self) -> bool:
        """Install DAQ service as Windows service using NSSM"""
        header("Installing NISystem DAQ Service")

        if not self.ensure_nssm():
            return False

        # Check if already installed
        code, output = self._nssm('status', self.config.daq_service_name)
        if code == 0 and 'SERVICE_' in output:
            warning(f"Service {self.config.daq_service_name} already exists")
            return True

        # Install the service
        info(f"Installing service: {self.config.daq_service_name}")

        code, output = self._nssm(
            'install',
            self.config.daq_service_name,
            str(self.config.venv_python),
            f'"{self.config.daq_service}"',
            '-c', f'"{self.config.config_file}"'
        )

        if code != 0:
            error(f"Failed to install service: {output}")
            return False

        # Configure service parameters
        self._nssm('set', self.config.daq_service_name, 'AppDirectory',
                   str(self.config.services_dir / 'daq_service'))

        self._nssm('set', self.config.daq_service_name, 'DisplayName',
                   'NISystem Data Acquisition Service')

        self._nssm('set', self.config.daq_service_name, 'Description',
                   'NISystem DAQ service - handles data acquisition, MQTT communication, and script execution')

        # Logging
        log_file = self.config.logs_dir / 'daq_service.log'
        err_file = self.config.logs_dir / 'daq_service_error.log'
        self._nssm('set', self.config.daq_service_name, 'AppStdout', str(log_file))
        self._nssm('set', self.config.daq_service_name, 'AppStderr', str(err_file))
        self._nssm('set', self.config.daq_service_name, 'AppStdoutCreationDisposition', '4')  # Append
        self._nssm('set', self.config.daq_service_name, 'AppStderrCreationDisposition', '4')

        # Auto-restart on failure
        self._nssm('set', self.config.daq_service_name, 'AppExit', 'Default', 'Restart')
        self._nssm('set', self.config.daq_service_name, 'AppRestartDelay', '5000')  # 5 seconds

        # Start type: automatic
        self._nssm('set', self.config.daq_service_name, 'Start', 'SERVICE_AUTO_START')

        # Dependencies
        self._nssm('set', self.config.daq_service_name, 'DependOnService', self.config.mosquitto_service_name)

        success(f"Service {self.config.daq_service_name} installed")
        return True

    def uninstall_daq_service(self) -> bool:
        """Remove DAQ service"""
        header("Uninstalling NISystem DAQ Service")

        if not self.config.nssm_exe.exists():
            warning("NSSM not found, trying sc.exe")
            code, output = self._run_elevated(['sc', 'delete', self.config.daq_service_name])
            return code == 0

        # Stop first
        self._nssm('stop', self.config.daq_service_name)
        time.sleep(2)

        # Remove
        code, output = self._nssm('remove', self.config.daq_service_name, 'confirm')

        if code == 0:
            success(f"Service {self.config.daq_service_name} removed")
            return True
        else:
            warning(f"Service removal: {output}")
            return True  # May not exist

    def start_daq_service(self) -> bool:
        """Start DAQ service"""
        info(f"Starting {self.config.daq_service_name}...")

        code, output = self._run_elevated(['net', 'start', self.config.daq_service_name])

        if code == 0:
            success("DAQ service started")
            return True
        elif 'already been started' in output:
            success("DAQ service already running")
            return True
        else:
            error(f"Failed to start DAQ service: {output}")
            return False

    def stop_daq_service(self) -> bool:
        """Stop DAQ service"""
        info(f"Stopping {self.config.daq_service_name}...")

        code, output = self._run_elevated(['net', 'stop', self.config.daq_service_name])

        if code == 0 or 'is not started' in output:
            success("DAQ service stopped")
            return True
        else:
            error(f"Failed to stop DAQ service: {output}")
            return False

    def restart_daq_service(self) -> bool:
        """Restart DAQ service"""
        self.stop_daq_service()
        time.sleep(2)
        return self.start_daq_service()

    # ==================== Dashboard Management ====================

    def build_dashboard(self) -> bool:
        """Build Vue dashboard for production"""
        header("Building Dashboard")

        if not self.config.dashboard_dir.exists():
            error(f"Dashboard directory not found: {self.config.dashboard_dir}")
            return False

        # Check for node_modules
        node_modules = self.config.dashboard_dir / 'node_modules'
        if not node_modules.exists():
            info("Installing npm dependencies...")
            code, output = self._run_cmd(
                ['npm', 'install'],
                check=False
            )
            if code != 0:
                error(f"npm install failed: {output}")
                return False

        # Build
        info("Building production bundle...")

        # Change to dashboard directory for the build
        original_dir = os.getcwd()
        os.chdir(self.config.dashboard_dir)

        try:
            code, output = self._run_cmd(['npm', 'run', 'build'], check=False)

            if code != 0:
                error(f"Build failed: {output}")
                return False

            dist_dir = self.config.dashboard_dir / 'dist'
            if dist_dir.exists():
                success(f"Dashboard built: {dist_dir}")

                # Show size
                total_size = sum(f.stat().st_size for f in dist_dir.rglob('*') if f.is_file())
                print(f"  Total size: {total_size / 1024:.1f} KB")
                return True
            else:
                error("Build completed but dist directory not found")
                return False

        finally:
            os.chdir(original_dir)

    # ==================== Firewall Management ====================

    def configure_firewall(self) -> bool:
        """Configure Windows Firewall rules"""
        header("Configuring Firewall")

        rules = [
            ('NISystem-MQTT', '1883', 'MQTT Broker'),
            ('NISystem-Dashboard', '5173', 'Dashboard (dev)'),
            ('NISystem-Dashboard-Prod', '8080', 'Dashboard (prod)'),
        ]

        for name, port, desc in rules:
            # Check if rule exists
            code, _ = self._run_cmd(
                ['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={name}'],
                check=False
            )

            if code == 0:
                info(f"Firewall rule '{name}' already exists")
                continue

            # Add rule
            code, output = self._run_elevated([
                'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                f'name={name}',
                'dir=in',
                'action=allow',
                'protocol=tcp',
                f'localport={port}',
                f'description={desc}'
            ])

            if code == 0:
                success(f"Added firewall rule: {name} (port {port})")
            else:
                warning(f"Failed to add firewall rule {name}: {output}")

        return True

    # ==================== Status ====================

    def get_service_status(self, service_name: str) -> Dict:
        """Get status of a Windows service"""
        status = {
            'name': service_name,
            'installed': False,
            'running': False,
            'state': 'Unknown'
        }

        code, output = self._run_cmd(['sc', 'query', service_name], check=False)

        if code == 0:
            status['installed'] = True
            if 'RUNNING' in output:
                status['running'] = True
                status['state'] = 'Running'
            elif 'STOPPED' in output:
                status['state'] = 'Stopped'
            elif 'PENDING' in output:
                status['state'] = 'Pending'
        else:
            status['state'] = 'Not Installed'

        return status

    def show_status(self):
        """Display status of all services"""
        header("NISystem Service Status")

        # Mosquitto
        mqtt_status = self.get_service_status(self.config.mosquitto_service_name)
        print(f"\n  MQTT Broker (Mosquitto):")
        print(f"    Installed: {'Yes' if mqtt_status['installed'] else 'No'}")
        print(f"    Status:    {mqtt_status['state']}")

        # Test MQTT connectivity
        if mqtt_status['running']:
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                result = s.connect_ex(('localhost', 1883))
                s.close()
                print(f"    Port 1883: {'Open' if result == 0 else 'Closed'}")
            except OSError as e:
                print(f"    Port 1883: Check failed ({e})")

        # DAQ Service
        daq_status = self.get_service_status(self.config.daq_service_name)
        print(f"\n  DAQ Service ({self.config.daq_service_name}):")
        print(f"    Installed: {'Yes' if daq_status['installed'] else 'No'}")
        print(f"    Status:    {daq_status['state']}")

        # Log files
        print(f"\n  Log Files:")
        log_file = self.config.logs_dir / 'daq_service.log'
        if log_file.exists():
            size = log_file.stat().st_size
            print(f"    DAQ Log: {log_file} ({size / 1024:.1f} KB)")

        # Dashboard
        print(f"\n  Dashboard:")
        dist_dir = self.config.dashboard_dir / 'dist'
        if dist_dir.exists():
            print(f"    Built: Yes ({dist_dir})")
        else:
            print(f"    Built: No (run 'build-dashboard' to build)")

    def show_logs(self, lines: int = 50):
        """Show recent log entries"""
        header("Recent Logs")

        log_file = self.config.logs_dir / 'daq_service.log'

        if not log_file.exists():
            warning(f"Log file not found: {log_file}")
            return

        info(f"Last {lines} lines from {log_file}:")
        print()

        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            for line in all_lines[-lines:]:
                print(line.rstrip())

    # ==================== Full Installation ====================

    def install_all(self) -> bool:
        """Full installation of all services"""
        header("NISystem Full Installation")

        results = []

        # 1. Mosquitto
        print("\n[1/5] MQTT Broker Setup")
        if self.check_mosquitto_installed():
            results.append(('Mosquitto Config', self.configure_mosquitto()))
            results.append(('Mosquitto Service', self.install_mosquitto_service()))
        else:
            warning("Mosquitto not installed - please install manually")
            print("  Download: https://mosquitto.org/download/")
            print("  Or run: winget install EclipseFoundation.Mosquitto")
            results.append(('Mosquitto', False))

        # 2. Firewall
        print("\n[2/5] Firewall Configuration")
        results.append(('Firewall', self.configure_firewall()))

        # 3. NSSM
        print("\n[3/5] Service Manager (NSSM)")
        results.append(('NSSM', self.ensure_nssm()))

        # 4. DAQ Service
        print("\n[4/5] DAQ Service Installation")
        results.append(('DAQ Service', self.install_daq_service()))

        # 5. Dashboard
        print("\n[5/5] Dashboard Build")
        results.append(('Dashboard', self.build_dashboard()))

        # Summary
        header("Installation Summary")
        all_ok = True
        for name, ok in results:
            status = colored("[OK]", Colors.GREEN) if ok else colored("[FAIL]", Colors.RED)
            print(f"  {status} {name}")
            if not ok:
                all_ok = False

        if all_ok:
            print(colored("\nInstallation complete!", Colors.GREEN))
            print("\nNext steps:")
            print("  1. Start services: python service_manager.py start")
            print("  2. Open dashboard:  http://localhost:5173")
        else:
            print(colored("\nSome components failed to install.", Colors.YELLOW))
            print("Check the errors above and re-run installation.")

        return all_ok

    def uninstall_all(self) -> bool:
        """Remove all services"""
        header("NISystem Uninstallation")

        self.stop_daq_service()
        self.uninstall_daq_service()

        success("NISystem services removed")
        print("\nNote: Mosquitto service was not removed (may be used by other applications)")

        return True

    def start_all(self) -> bool:
        """Start all services"""
        header("Starting NISystem Services")

        # Start Mosquitto first
        if self.check_mosquitto_installed():
            self.start_mosquitto()
            time.sleep(2)

        # Start DAQ service
        return self.start_daq_service()

    def stop_all(self) -> bool:
        """Stop all services"""
        header("Stopping NISystem Services")

        self.stop_daq_service()
        # Don't stop Mosquitto - other apps might use it

        return True

def main():
    parser = argparse.ArgumentParser(
        description='NISystem Service Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  install         Install all services (Mosquitto, DAQ, Dashboard)
  uninstall       Remove NISystem services
  start           Start all services
  stop            Stop all services
  restart         Restart DAQ service
  status          Show service status
  logs            View DAQ service logs
  build-dashboard Build Vue dashboard for production
  configure-mqtt  Configure Mosquitto for network access

Examples:
  %(prog)s install              # Full installation
  %(prog)s start                # Start services
  %(prog)s status               # Check status
  %(prog)s logs -n 100          # View last 100 log lines
        """
    )

    parser.add_argument('command', choices=[
        'install', 'uninstall', 'start', 'stop', 'restart',
        'status', 'logs', 'build-dashboard', 'configure-mqtt'
    ], help='Command to run')

    parser.add_argument('-n', '--lines', type=int, default=50,
                        help='Number of log lines to show')

    args = parser.parse_args()

    manager = ServiceManager()

    if args.command == 'install':
        sys.exit(0 if manager.install_all() else 1)

    elif args.command == 'uninstall':
        sys.exit(0 if manager.uninstall_all() else 1)

    elif args.command == 'start':
        sys.exit(0 if manager.start_all() else 1)

    elif args.command == 'stop':
        sys.exit(0 if manager.stop_all() else 1)

    elif args.command == 'restart':
        sys.exit(0 if manager.restart_daq_service() else 1)

    elif args.command == 'status':
        manager.show_status()

    elif args.command == 'logs':
        manager.show_logs(args.lines)

    elif args.command == 'build-dashboard':
        sys.exit(0 if manager.build_dashboard() else 1)

    elif args.command == 'configure-mqtt':
        sys.exit(0 if manager.configure_mosquitto() else 1)

if __name__ == '__main__':
    main()
