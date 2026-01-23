"""
Build ICCSFlux as a portable Windows application.

This creates a self-contained folder that can run on any Windows PC
without installing Python, Node.js, or Mosquitto system-wide.

Usage:
    python build_portable.py           # Online build (downloads dependencies)
    python build_portable.py --offline # Offline build (uses vendor/ folder)

Output: dist/ICCSFlux-Portable/

Requirements:
- Python 3.8+ (to run this build script)
- Node.js + npm (to build the dashboard, unless using pre-built)
- Internet connection (unless using --offline with populated vendor/)

For offline builds, first run: python download_dependencies.py
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import argparse
from pathlib import Path

# Configuration
PYTHON_VERSION = "3.11.7"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Mosquitto portable from Eclipse releases
MOSQUITTO_VERSION = "2.0.18"
MOSQUITTO_URL = f"https://mosquitto.org/files/binary/win64/mosquitto-{MOSQUITTO_VERSION}-install-windows-x64.exe"

# Paths
PROJECT_ROOT = Path(__file__).parent.parent  # Go up from scripts/ to project root
BUILD_DIR = PROJECT_ROOT / "dist" / "ICCSFlux-Portable"
VENDOR_DIR = PROJECT_ROOT / "vendor"

# Python packages to install (from requirements.txt files)
PYTHON_PACKAGES = [
    "paho-mqtt>=1.6.0",
    "pymodbus>=3.0.0",
    "pyserial>=3.5",
    "numpy>=1.21.0",
    "scipy>=1.7.0",
    "python-dateutil>=2.8.0",
    "psutil>=5.9.0",
    "requests>=2.28.0",  # For Opto22 node
    "opcua>=0.98.0",     # OPC-UA server/client
    "pycomm3>=1.2.0",    # Allen Bradley EtherNet/IP
]

# Global offline mode flag
OFFLINE_MODE = False


def log(msg, level="INFO"):
    prefix = {"INFO": "[BUILD]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")


def download_file(url, dest, desc=None):
    """Download a file with progress indication"""
    if OFFLINE_MODE:
        log(f"Cannot download in offline mode: {desc or url}", "ERROR")
        return False

    filename = desc or url.split('/')[-1]
    log(f"Downloading {filename}...")
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        log(f"Failed to download {filename}: {e}", "ERROR")
        return False


def check_vendor_files():
    """Check what vendor files are available for offline build."""
    available = {
        'python_embed': False,
        'get_pip': False,
        'python_packages': False,
        'mosquitto': False,
        'dashboard': False,
    }

    if not VENDOR_DIR.exists():
        return available

    # Check Python embed
    python_zip = VENDOR_DIR / "python" / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    available['python_embed'] = python_zip.exists()

    # Check get-pip.py
    get_pip = VENDOR_DIR / "python" / "get-pip.py"
    available['get_pip'] = get_pip.exists()

    # Check Python packages
    packages_dir = VENDOR_DIR / "python-packages"
    if packages_dir.exists():
        wheels = list(packages_dir.glob("*.whl"))
        tarballs = list(packages_dir.glob("*.tar.gz"))
        available['python_packages'] = len(wheels) + len(tarballs) > 0

    # Check Mosquitto
    mosquitto_exe = VENDOR_DIR / "mosquitto" / "mosquitto.exe"
    available['mosquitto'] = mosquitto_exe.exists()

    # Check pre-built dashboard
    dashboard_dist = VENDOR_DIR / "dashboard-dist" / "index.html"
    available['dashboard'] = dashboard_dist.exists()

    return available


def build_dashboard():
    """Build the Vue dashboard to static files"""
    vendor_available = check_vendor_files()

    # Use pre-built dashboard if available in offline mode
    if OFFLINE_MODE and vendor_available['dashboard']:
        log("Using pre-built dashboard from vendor/")
        return VENDOR_DIR / "dashboard-dist"

    # Also use pre-built if available and no npm
    if vendor_available['dashboard']:
        try:
            subprocess.run("npm --version", shell=True, capture_output=True, check=True)
        except:
            log("npm not found, using pre-built dashboard from vendor/")
            return VENDOR_DIR / "dashboard-dist"

    if OFFLINE_MODE:
        log("Cannot build dashboard offline without pre-built version!", "ERROR")
        log("Run download_dependencies.py first to pre-build dashboard", "ERROR")
        return None

    log("Building Vue dashboard...")
    dashboard_dir = PROJECT_ROOT / "dashboard"

    if not dashboard_dir.exists():
        log("Dashboard directory not found!", "ERROR")
        return None

    # Check if node_modules exists
    if not (dashboard_dir / "node_modules").exists():
        log("Installing npm dependencies...")
        result = subprocess.run("npm install", shell=True, cwd=dashboard_dir, capture_output=True)
        if result.returncode != 0:
            log("npm install failed!", "ERROR")
            print(result.stderr.decode())
            return None

    # Build production
    log("Running npm build...")
    result = subprocess.run("npm run build", shell=True, cwd=dashboard_dir, capture_output=True)
    if result.returncode != 0:
        log("npm build failed!", "ERROR")
        print(result.stderr.decode())
        return None

    dist_dir = dashboard_dir / "dist"
    if not dist_dir.exists():
        log("Dashboard build output not found!", "ERROR")
        return None

    log("Dashboard built successfully", "OK")
    return dist_dir


def setup_embedded_python():
    """Download and setup embedded Python with all dependencies"""
    log("Setting up embedded Python...")
    python_dir = BUILD_DIR / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    vendor_available = check_vendor_files()

    # Get Python embed zip
    tmp_path = python_dir / "python_embed.zip"

    if vendor_available['python_embed']:
        log("  Using Python from vendor/")
        vendor_zip = VENDOR_DIR / "python" / f"python-{PYTHON_VERSION}-embed-amd64.zip"
        shutil.copy(vendor_zip, tmp_path)
    else:
        if OFFLINE_MODE:
            log("Python embed not in vendor/ - cannot continue offline!", "ERROR")
            return None
        if not download_file(PYTHON_EMBED_URL, str(tmp_path), f"Python {PYTHON_VERSION} embed"):
            return None

    log("Extracting Python...")
    with zipfile.ZipFile(tmp_path, 'r') as zf:
        zf.extractall(python_dir)
    tmp_path.unlink()

    # Enable pip by modifying python311._pth
    pth_files = list(python_dir.glob("python*._pth"))
    if pth_files:
        pth_file = pth_files[0]
        content = pth_file.read_text()
        # Uncomment import site
        content = content.replace("#import site", "import site")
        # Add Lib\site-packages
        if "Lib\\site-packages" not in content:
            content += "\nLib\\site-packages\n"
        pth_file.write_text(content)

    # Create site-packages directory
    site_packages = python_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    # Get get-pip.py
    get_pip = python_dir / "get-pip.py"

    if vendor_available['get_pip']:
        log("  Using get-pip.py from vendor/")
        shutil.copy(VENDOR_DIR / "python" / "get-pip.py", get_pip)
    else:
        if OFFLINE_MODE:
            log("get-pip.py not in vendor/ - cannot continue offline!", "ERROR")
            return None
        log("Installing pip...")
        if not download_file(GET_PIP_URL, str(get_pip)):
            return None

    # Install pip
    log("Installing pip...")
    python_exe = python_dir / "python.exe"
    result = subprocess.run(
        [str(python_exe), str(get_pip), "--no-warn-script-location"],
        cwd=python_dir,
        capture_output=True
    )
    if result.returncode != 0:
        log("pip installation failed!", "ERROR")
        print(result.stderr.decode())
        return None
    get_pip.unlink()

    # Install required packages
    log("Installing Python packages...")
    packages_dir = VENDOR_DIR / "python-packages"

    if vendor_available['python_packages']:
        # Install from local wheels
        log("  Installing from vendor/python-packages/")
        result = subprocess.run(
            [
                str(python_exe), "-m", "pip", "install",
                "--no-index",
                "--find-links", str(packages_dir),
                "--no-warn-script-location",
                "-q"
            ] + PYTHON_PACKAGES,
            capture_output=True
        )
        if result.returncode != 0:
            log("  Some packages failed, trying individually...", "WARN")
            for package in PYTHON_PACKAGES:
                pkg_name = package.split(">=")[0].split("==")[0]
                log(f"    Installing {pkg_name}...")
                subprocess.run(
                    [
                        str(python_exe), "-m", "pip", "install",
                        "--no-index",
                        "--find-links", str(packages_dir),
                        "--no-warn-script-location",
                        "-q",
                        package
                    ],
                    capture_output=True
                )
    else:
        if OFFLINE_MODE:
            log("Python packages not in vendor/ - cannot continue offline!", "ERROR")
            return None

        # Install from PyPI
        log("  Installing from PyPI (this may take a few minutes)...")
        for package in PYTHON_PACKAGES:
            pkg_name = package.split(">=")[0].split("==")[0]
            log(f"    Installing {pkg_name}...")
            result = subprocess.run(
                [str(python_exe), "-m", "pip", "install", package, "--no-warn-script-location", "-q"],
                capture_output=True
            )
            if result.returncode != 0:
                log(f"    Warning: Failed to install {pkg_name}", "WARN")

    log("Python environment ready", "OK")
    return python_dir


def setup_mosquitto():
    """Setup Mosquitto MQTT broker"""
    log("Setting up Mosquitto MQTT broker...")
    mosquitto_dir = BUILD_DIR / "mosquitto"
    mosquitto_dir.mkdir(parents=True, exist_ok=True)

    vendor_available = check_vendor_files()
    mosquitto_exe = None

    # Check vendor first
    if vendor_available['mosquitto']:
        log("  Using Mosquitto from vendor/")
        vendor_mosquitto = VENDOR_DIR / "mosquitto"
        for f in vendor_mosquitto.iterdir():
            if f.is_file():
                shutil.copy(f, mosquitto_dir / f.name)
        mosquitto_exe = mosquitto_dir / "mosquitto.exe"

    # Check system installation
    elif not OFFLINE_MODE:
        system_mosquitto = Path("C:/Program Files/mosquitto")

        if system_mosquitto.exists() and (system_mosquitto / "mosquitto.exe").exists():
            log("  Found system Mosquitto installation, copying...")

            files_to_copy = [
                "mosquitto.exe",
                "mosquitto.dll",
                "mosquitto_dynamic_security.dll",
                "libcrypto-3-x64.dll",
                "libssl-3-x64.dll",
                "mosquitto_passwd.exe",
            ]

            for filename in files_to_copy:
                src = system_mosquitto / filename
                if src.exists():
                    shutil.copy(src, mosquitto_dir / filename)

            mosquitto_exe = mosquitto_dir / "mosquitto.exe"
        else:
            log("System Mosquitto not found", "WARN")
            log("You will need to manually copy Mosquitto files to:", "WARN")
            log(f"  {mosquitto_dir}", "WARN")
            log("Download from: https://mosquitto.org/download/", "WARN")
    else:
        log("Mosquitto not in vendor/ - must be added manually", "WARN")

    # Create portable mosquitto config
    config_content = """# ICCSFlux Portable Mosquitto Configuration
# Localhost only for security

# TCP listener for backend services
listener 1883 127.0.0.1

# WebSocket listener for browser dashboard
listener 9001 127.0.0.1
protocol websockets

# Allow anonymous connections (localhost only)
allow_anonymous true

# Logging
log_dest stderr
log_type error
log_type warning

# Performance
max_queued_messages 10000
"""

    (mosquitto_dir / "mosquitto.conf").write_text(config_content)

    if mosquitto_exe and mosquitto_exe.exists():
        log("Mosquitto ready", "OK")
    else:
        log("Mosquitto config created (executable needed)", "WARN")

    return mosquitto_dir


def copy_project_files():
    """Copy necessary project files"""
    log("Copying project files...")

    # Copy services
    services_dest = BUILD_DIR / "services"
    if services_dest.exists():
        shutil.rmtree(services_dest)

    shutil.copytree(
        PROJECT_ROOT / "services",
        services_dest,
        ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '.pytest_cache',
            '*.log', '*.tmp', 'test_*.py'
        )
    )
    log("  Copied services/")

    # Copy config
    config_dest = BUILD_DIR / "config"
    if config_dest.exists():
        shutil.rmtree(config_dest)
    shutil.copytree(
        PROJECT_ROOT / "config",
        config_dest,
        ignore=shutil.ignore_patterns('*.log', '*.tmp')
    )
    log("  Copied config/")

    # Create data directories
    data_dir = BUILD_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "recordings").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    (data_dir / "audit").mkdir(exist_ok=True)
    log("  Created data directories")

    # Copy docs
    docs_dest = BUILD_DIR / "docs"
    if (PROJECT_ROOT / "docs").exists():
        if docs_dest.exists():
            shutil.rmtree(docs_dest)
        shutil.copytree(PROJECT_ROOT / "docs", docs_dest)
        log("  Copied docs/")

    log("Project files copied", "OK")


def copy_dashboard_build(dashboard_dist):
    """Copy built dashboard files"""
    log("Copying dashboard build...")

    www_dest = BUILD_DIR / "www"
    if www_dest.exists():
        shutil.rmtree(www_dest)
    shutil.copytree(dashboard_dist, www_dest)

    log("Dashboard copied", "OK")


def create_launcher():
    """Create the main launcher script and batch file"""
    log("Creating launcher...")

    # Main Python launcher
    launcher_py = BUILD_DIR / "ICCSFlux.py"
    launcher_py.write_text('''#!/usr/bin/env python3
"""
ICCSFlux Portable Launcher
Starts all services and opens the dashboard in browser.
"""

import os
import sys
import subprocess
import time
import webbrowser
import signal
import socket
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

# Paths relative to this script
ROOT = Path(__file__).parent.resolve()
PYTHON = ROOT / "python" / "python.exe"
MOSQUITTO = ROOT / "mosquitto" / "mosquitto.exe"
MOSQUITTO_CONF = ROOT / "mosquitto" / "mosquitto.conf"
DAQ_SERVICE = ROOT / "services" / "daq_service" / "daq_service.py"
CONFIG = ROOT / "config" / "system.ini"
WWW = ROOT / "www"
DATA = ROOT / "data"

# Global process list for cleanup
processes = []
httpd = None


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


def start_daq_service():
    """Start the DAQ backend service"""
    print("[START] ICCSFlux DAQ Service...")

    # Ensure data directories exist
    DATA.mkdir(exist_ok=True)
    (DATA / "recordings").mkdir(exist_ok=True)
    (DATA / "logs").mkdir(exist_ok=True)

    # Start DAQ service
    env = os.environ.copy()
    env["ICCSFLUX_DATA_DIR"] = str(DATA)

    proc = subprocess.Popen(
        [str(PYTHON), str(DAQ_SERVICE), "-c", str(CONFIG)],
        cwd=str(DAQ_SERVICE.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    processes.append(proc)

    # Wait for service to publish status
    time.sleep(2)

    if proc.poll() is None:
        print("[  OK ] DAQ Service started")
    else:
        print("[ERROR] DAQ Service failed to start")

    return proc


def start_web_server(port=5173):
    """Start HTTP server for the dashboard"""
    global httpd

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

    print("[  OK ] Shutdown complete")
    sys.exit(0)


def main():
    print()
    print("=" * 55)
    print("       ICCSFlux - Industrial Data Acquisition")
    print("=" * 55)
    print()

    # Verify required files exist
    if not PYTHON.exists():
        print("[ERROR] Embedded Python not found!")
        print("        Run build_portable.py to create the portable package.")
        input("Press Enter to exit...")
        return 1

    if not WWW.exists():
        print("[ERROR] Dashboard files not found!")
        print("        Run build_portable.py to create the portable package.")
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

    port = start_web_server()

    if port:
        print()
        print("=" * 55)
        print(f"  ICCSFlux is ready!")
        print(f"  Dashboard: http://localhost:{port}")
        print()
        print("  Press Ctrl+C to stop")
        print("=" * 55)
        print()

        # Open browser
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
''')

    # Batch launcher for double-click
    bat = BUILD_DIR / "ICCSFlux.bat"
    bat.write_text('''@echo off
title ICCSFlux
cd /d "%~dp0"
python\\python.exe ICCSFlux.py
if errorlevel 1 pause
''')

    # Create README
    readme = BUILD_DIR / "README.txt"
    readme.write_text(f'''ICCSFlux Portable
================

Industrial Data Acquisition & Control System

QUICK START
-----------
Double-click ICCSFlux.bat to start.

The dashboard will open automatically in your browser at:
http://localhost:5173

Press Ctrl+C in the console window to stop.


REQUIREMENTS
------------
- Windows 10/11 (64-bit)
- For real hardware: NI-DAQmx drivers from ni.com


FOLDER STRUCTURE
----------------
ICCSFlux.bat      - Main launcher (double-click this)
ICCSFlux.py       - Python launcher script
python/         - Embedded Python {PYTHON_VERSION}
mosquitto/      - MQTT broker
services/       - Backend services
www/            - Dashboard (browser UI)
config/         - Configuration files
data/           - Recordings and logs
docs/           - Documentation


SIMULATION MODE
---------------
ICCSFlux runs in simulation mode by default if no NI hardware
is detected. This is useful for testing and demos.


DOCUMENTATION
-------------
See the docs/ folder for:
- ICCSFlux_User_Manual.md
- ICCSFlux_Remote_Nodes_Guide.md
- ICCSFlux_Python_Scripting_Guide.md


SUPPORT
-------
Contact your system administrator for support.
''')

    log("Launcher created", "OK")


def main():
    global OFFLINE_MODE

    # Parse arguments
    parser = argparse.ArgumentParser(description="Build ICCSFlux portable package")
    parser.add_argument('--offline', action='store_true',
                        help='Build using only vendor/ files (no downloads)')
    args = parser.parse_args()

    OFFLINE_MODE = args.offline

    print()
    print("=" * 60)
    print("       ICCSFlux Portable Builder")
    if OFFLINE_MODE:
        print("       (OFFLINE MODE - using vendor/ files)")
    print("=" * 60)
    print()

    # Check vendor files if offline
    if OFFLINE_MODE:
        log("Checking vendor/ files...")
        vendor = check_vendor_files()
        print(f"  Python embed:    {'[OK]' if vendor['python_embed'] else '[MISSING]'}")
        print(f"  get-pip.py:      {'[OK]' if vendor['get_pip'] else '[MISSING]'}")
        print(f"  Python packages: {'[OK]' if vendor['python_packages'] else '[MISSING]'}")
        print(f"  Mosquitto:       {'[OK]' if vendor['mosquitto'] else '[MISSING]'}")
        print(f"  Dashboard:       {'[OK]' if vendor['dashboard'] else '[MISSING]'}")
        print()

        if not vendor['python_embed'] or not vendor['get_pip'] or not vendor['python_packages']:
            log("Missing required vendor files for offline build!", "ERROR")
            log("Run: python download_dependencies.py", "ERROR")
            return 1

    # Check prerequisites
    log("Checking prerequisites...")

    # Check npm (only required if not using pre-built dashboard)
    vendor = check_vendor_files()
    if not OFFLINE_MODE or not vendor['dashboard']:
        try:
            result = subprocess.run("npm --version", shell=True, capture_output=True, check=True)
            log(f"  npm: v{result.stdout.decode().strip()}")
        except:
            if vendor['dashboard']:
                log("  npm: not found (using pre-built dashboard)")
            else:
                log("npm not found! Install Node.js from nodejs.org", "ERROR")
                log("Or run download_dependencies.py to pre-build dashboard", "ERROR")
                return 1
    else:
        log("  npm: not required (using pre-built dashboard)")

    # Clean build dir
    if BUILD_DIR.exists():
        log("Cleaning previous build...")
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    print()

    # Build dashboard first (can fail early)
    dashboard_dist = build_dashboard()
    if not dashboard_dist:
        log("Dashboard build failed!", "ERROR")
        return 1

    print()

    # Setup components
    python_dir = setup_embedded_python()
    if not python_dir:
        log("Python setup failed!", "ERROR")
        return 1

    print()

    setup_mosquitto()

    print()

    copy_project_files()
    copy_dashboard_build(dashboard_dist)

    print()

    create_launcher()

    # Calculate size
    total_size = sum(f.stat().st_size for f in BUILD_DIR.rglob('*') if f.is_file())
    size_mb = total_size / (1024 * 1024)

    print()
    print("=" * 60)
    log("Build complete!", "OK")
    print()
    print(f"  Output: {BUILD_DIR}")
    print(f"  Size:   {size_mb:.1f} MB")
    if OFFLINE_MODE:
        print(f"  Mode:   Offline (no internet required)")
    print()

    # Check if Mosquitto was bundled
    if not (BUILD_DIR / "mosquitto" / "mosquitto.exe").exists():
        print("  NOTE: Mosquitto not found.")
        print("        Copy mosquitto.exe and DLLs to:")
        print(f"        {BUILD_DIR / 'mosquitto'}")
        print()
        print("  Download from: https://mosquitto.org/download/")
        print()

    print("  To run: Double-click ICCSFlux.bat")
    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
