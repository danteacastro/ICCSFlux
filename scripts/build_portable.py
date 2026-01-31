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

# Python packages to install - ALL features included
# Note: azure-iot-device is in separate venv (azure_uploader/) due to paho-mqtt version conflict
PYTHON_PACKAGES = [
    # Core (paho-mqtt 2.x for our MQTT code)
    "paho-mqtt>=2.0.0",
    "numpy>=1.21.0",
    "scipy>=1.7.0",
    "python-dateutil>=2.8.0",
    "psutil>=5.9.0",
    "bcrypt>=4.0.0",
    # Industrial protocols
    "pymodbus>=3.0.0",
    "pyserial>=3.5",
    "opcua>=0.98.0",
    "pycomm3>=1.2.0",
    # HTTP/REST
    "requests>=2.28.0",
    "httpx>=0.24.0",
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
        'azure_packages': False,
        'mosquitto': False,
        'nssm': False,
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

    # Check Azure packages (separate dir for paho-mqtt 1.x compatibility)
    azure_packages_dir = VENDOR_DIR / "azure-packages"
    if azure_packages_dir.exists():
        azure_wheels = list(azure_packages_dir.glob("*.whl"))
        available['azure_packages'] = len(azure_wheels) > 0

    # Check NSSM
    nssm_exe = VENDOR_DIR / "nssm" / "nssm.exe"
    available['nssm'] = nssm_exe.exists()

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


def setup_nssm():
    """Setup NSSM (Non-Sucking Service Manager) for Windows service support"""
    log("Setting up NSSM service manager...")
    nssm_dir = BUILD_DIR / "nssm"
    nssm_dir.mkdir(parents=True, exist_ok=True)

    vendor_available = check_vendor_files()
    nssm_exe = None

    # Check vendor first
    if vendor_available['nssm']:
        log("  Using NSSM from vendor/")
        src = VENDOR_DIR / "nssm" / "nssm.exe"
        dst = nssm_dir / "nssm.exe"
        shutil.copy(src, dst)
        nssm_exe = dst
    else:
        log("NSSM not in vendor/ - must be added manually", "WARN")
        log("Download from: https://nssm.cc/download", "WARN")

        # Create placeholder README
        readme = nssm_dir / "README.txt"
        readme.write_text("""NSSM - Non-Sucking Service Manager

Download from: https://nssm.cc/download

Extract and copy nssm.exe (from the win64 folder) here.
""")

    if nssm_exe and nssm_exe.exists():
        log("NSSM ready", "OK")
    else:
        log("NSSM placeholder created (executable needed)", "WARN")

    return nssm_dir


def setup_azure_uploader():
    """Setup Azure IoT Hub Uploader with separate Python environment (paho-mqtt 1.x)"""
    log("Setting up Azure IoT Hub Uploader...")
    azure_dir = BUILD_DIR / "azure_uploader"
    azure_dir.mkdir(parents=True, exist_ok=True)

    vendor_available = check_vendor_files()

    # Check if Azure packages are available in vendor
    azure_packages_dir = VENDOR_DIR / "azure-packages"
    has_azure_packages = azure_packages_dir.exists() and any(azure_packages_dir.glob("*.whl"))

    if not has_azure_packages:
        log("  Azure packages not in vendor/azure-packages/", "WARN")
        log("  Run: pip download paho-mqtt<2 azure-iot-device --dest vendor/azure-packages", "WARN")
        # Still create the directory structure for manual setup
        readme = azure_dir / "README.txt"
        readme.write_text("""Azure IoT Hub Uploader

This is a separate service that forwards channel data to Azure IoT Hub.
It requires its own Python environment due to package conflicts.

SETUP:
1. Create a virtual environment:
   python -m venv venv

2. Activate it:
   venv\\Scripts\\activate

3. Install dependencies:
   pip install paho-mqtt<2 azure-iot-device

4. Copy config:
   copy azure_uploader.ini.example azure_uploader.ini

5. Edit azure_uploader.ini with your Azure IoT Hub connection string

6. Run:
   python azure_uploader_service.py
""")
        # Copy the service files
        src_dir = PROJECT_ROOT / "services" / "azure_uploader"
        if src_dir.exists():
            for f in src_dir.iterdir():
                if f.is_file():
                    shutil.copy(f, azure_dir / f.name)
        log("Azure uploader placeholder created (needs manual setup)", "WARN")
        return azure_dir

    # Create embedded Python for Azure uploader
    log("  Creating Azure uploader Python environment...")
    azure_python_dir = azure_dir / "python"
    azure_python_dir.mkdir(exist_ok=True)

    # Copy base Python from main embed
    if vendor_available['python_embed']:
        embed_zip = VENDOR_DIR / "python" / f"python-{PYTHON_VERSION}-embed-amd64.zip"
        if embed_zip.exists():
            import zipfile
            with zipfile.ZipFile(embed_zip, 'r') as z:
                z.extractall(azure_python_dir)

    # Install pip
    if vendor_available['get_pip']:
        get_pip = VENDOR_DIR / "python" / "get-pip.py"
        python_exe = azure_python_dir / "python.exe"

        # Fix _pth file
        pth_files = list(azure_python_dir.glob("*._pth"))
        for pth_file in pth_files:
            content = pth_file.read_text()
            if "#import site" in content:
                content = content.replace("#import site", "import site")
                pth_file.write_text(content)

        # Install pip
        subprocess.run(
            [str(python_exe), str(get_pip), "--no-warn-script-location", "-q"],
            capture_output=True
        )

        # Install Azure packages
        log("  Installing Azure-compatible packages...")
        result = subprocess.run(
            [
                str(python_exe), "-m", "pip", "install",
                "--no-index",
                "--find-links", str(azure_packages_dir),
                "--no-warn-script-location",
                "-q",
                "paho-mqtt<2",
                "azure-iot-device"
            ],
            capture_output=True
        )
        if result.returncode != 0:
            log("  Warning: Some Azure packages failed to install", "WARN")

    # Copy the service files (no manual batch needed - starts automatically with ICCSFlux)
    src_dir = PROJECT_ROOT / "services" / "azure_uploader"
    if src_dir.exists():
        for f in src_dir.iterdir():
            if f.is_file() and f.name != 'Start-AzureUploader.bat':
                shutil.copy(f, azure_dir / f.name)

    log("Azure uploader ready", "OK")
    return azure_dir


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

    # Copy launcher utilities (single_instance.py for service management)
    launcher_dest = BUILD_DIR / "launcher"
    launcher_dest.mkdir(exist_ok=True)
    launcher_src = PROJECT_ROOT / "launcher" / "single_instance.py"
    if launcher_src.exists():
        shutil.copy2(launcher_src, launcher_dest / "single_instance.py")
        log("  Copied launcher/")

    # Create data directories
    data_dir = BUILD_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "recordings").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    (data_dir / "audit").mkdir(exist_ok=True)
    log("  Created data directories")

    # Copy user documentation (filtered and renamed for clarity)
    docs_dest = BUILD_DIR / "docs"
    docs_dest.mkdir(exist_ok=True)

    # Map source files to numbered destination names (user-facing docs only)
    user_docs = [
        ("USER_GUIDE.md", "01_Getting_Started.md"),
        ("ICCSFlux_Quick_Reference.md", "02_Quick_Reference.md"),
        ("ICCSFlux_User_Manual.md", "03_User_Manual.md"),
        ("ICCSFlux_Python_Scripting_Guide.md", "04_Python_Scripting.md"),
        ("ICCSFlux_Remote_Nodes_Guide.md", "05_Remote_Nodes.md"),
        ("ICCSFlux_Administrator_Guide.md", "06_Administrator_Guide.md"),
    ]

    docs_src = PROJECT_ROOT / "docs"
    copied = 0
    for src_name, dest_name in user_docs:
        src_path = docs_src / src_name
        if src_path.exists():
            shutil.copy(src_path, docs_dest / dest_name)
            copied += 1

    log(f"  Copied {copied} user docs")

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

When run via pythonw.exe (no console), runs in service/background mode.
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

# Detect service mode (running under pythonw.exe = no console)
SERVICE_MODE = 'pythonw' in sys.executable.lower()

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


def start_azure_uploader():
    """Start Azure IoT Hub uploader service (runs idle, waiting for commands)"""
    AZURE_DIR = ROOT / "azure_uploader"
    AZURE_PYTHON = AZURE_DIR / "python" / "python.exe"
    AZURE_SERVICE = AZURE_DIR / "azure_uploader_service.py"

    if not AZURE_PYTHON.exists() or not AZURE_SERVICE.exists():
        # Azure uploader not available (normal if not installed)
        return None

    print("[START] Azure IoT Hub uploader (idle)...")

    # Start Azure uploader - it connects to MQTT and waits for commands
    # Config comes dynamically via MQTT when recording starts
    proc = subprocess.Popen(
        [str(AZURE_PYTHON), str(AZURE_SERVICE), "--host", "localhost", "--port", "1883"],
        cwd=str(AZURE_DIR),
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
        if not SERVICE_MODE:
            print("[ERROR] Embedded Python not found!")
            print("        Run build_portable.py to create the portable package.")
            input("Press Enter to exit...")
        return 1

    if not WWW.exists():
        if not SERVICE_MODE:
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

    # Start Azure uploader if configured (uses separate Python env)
    start_azure_uploader()

    port = start_web_server()

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

            # Open browser (only in interactive mode)
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

    # Service manager batch file
    service_bat = BUILD_DIR / "ICCSFlux-Service.bat"
    service_bat.write_text('''@echo off
cd /d "%~dp0"

if "%1"=="install" goto install
if "%1"=="uninstall" goto uninstall
if "%1"=="start" goto start
if "%1"=="stop" goto stop
if "%1"=="status" goto status
goto usage

:install
echo Installing ICCSFlux as startup service...
schtasks /create /tn "ICCSFlux" /tr "wscript.exe \\"%~dp0ICCSFlux-Hidden.vbs\\"" /sc onlogon /rl highest /f
if errorlevel 1 (
    echo Failed to install. Try running as Administrator.
) else (
    echo.
    echo ICCSFlux will start automatically when you log in.
    echo Run "ICCSFlux-Service.bat start" to start now.
)
goto end

:uninstall
echo Removing ICCSFlux from startup...
schtasks /delete /tn "ICCSFlux" /f
echo Done.
goto end

:start
echo Starting ICCSFlux in background...
wscript.exe "%~dp0ICCSFlux-Hidden.vbs"
timeout /t 3 /nobreak >nul
echo.
echo ICCSFlux is running in background.
echo Dashboard: http://localhost:5173
goto end

:stop
echo Stopping ICCSFlux...
taskkill /f /im mosquitto.exe 2>nul
for /f "tokens=2" %%%%i in ('tasklist /fi "WINDOWTITLE eq ICCSFlux*" /fo list ^| find "PID:"') do taskkill /f /pid %%%%i 2>nul
wmic process where "commandline like '%%%%ICCSFlux.py%%%%'" call terminate >nul 2>&1
echo Stopped.
goto end

:status
echo.
echo Checking ICCSFlux status...
echo.
netstat -an | find ":1883" >nul && echo MQTT Broker (1883): RUNNING || echo MQTT Broker (1883): STOPPED
netstat -an | find ":5173" >nul && echo Dashboard   (5173): RUNNING || echo Dashboard   (5173): STOPPED
echo.
schtasks /query /tn "ICCSFlux" >nul 2>&1 && echo Startup: INSTALLED || echo Startup: NOT INSTALLED
goto end

:usage
echo.
echo ICCSFlux Service Manager
echo ========================
echo.
echo Usage: ICCSFlux-Service.bat [command]
echo.
echo Commands:
echo   install   - Install as startup service (runs on login)
echo   uninstall - Remove from startup
echo   start     - Start ICCSFlux in background
echo   stop      - Stop ICCSFlux
echo   status    - Check if running
echo.
echo For interactive mode with console, use ICCSFlux.bat instead.
echo.
goto end

:end
''')

    # Hidden launcher VBScript (runs without console window)
    vbs = BUILD_DIR / "ICCSFlux-Hidden.vbs"
    vbs.write_text('''' ICCSFlux Hidden Launcher
' Runs ICCSFlux.py without a visible console window

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Get script directory
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Build paths
PythonExe = ScriptDir & "\\python\\pythonw.exe"
LauncherPy = ScriptDir & "\\ICCSFlux.py"

' Run hidden (0 = hidden window)
WshShell.Run """" & PythonExe & """ """ & LauncherPy & """", 0, False
''')

    # Simple double-click batch files
    start_bg = BUILD_DIR / "Start-Background.bat"
    start_bg.write_text('''@echo off
cd /d "%~dp0"
echo Starting ICCSFlux in background...
wscript.exe "%~dp0ICCSFlux-Hidden.vbs"
timeout /t 2 /nobreak >nul
echo.
echo ICCSFlux is running.
echo.
echo Open your browser to: http://localhost:5173
echo.
echo To stop: double-click Stop-ICCSFlux.bat
echo.
pause
''')

    stop_bat = BUILD_DIR / "Stop-ICCSFlux.bat"
    stop_bat.write_text('''@echo off
cd /d "%~dp0"
echo Stopping ICCSFlux...
echo.
taskkill /f /im mosquitto.exe 2>nul
wmic process where "commandline like '%%ICCSFlux.py%%'" call terminate >nul 2>&1
wmic process where "commandline like '%%daq_service.py%%'" call terminate >nul 2>&1
echo.
echo ICCSFlux stopped.
echo.
pause
''')

    # Task Scheduler based auto-start (runs on login)
    install_auto = BUILD_DIR / "Install-AutoStart.bat"
    install_auto.write_text('''@echo off
cd /d "%~dp0"
echo.
echo This will make ICCSFlux start automatically when you log in.
echo.
schtasks /create /tn "ICCSFlux" /tr "wscript.exe \\"%~dp0ICCSFlux-Hidden.vbs\\"" /sc onlogon /rl highest /f
if errorlevel 1 (
    echo.
    echo Failed. Try right-clicking this file and selecting "Run as administrator"
) else (
    echo.
    echo Done! ICCSFlux will now start automatically when you log in.
)
echo.
pause
''')

    uninstall_auto = BUILD_DIR / "Uninstall-AutoStart.bat"
    uninstall_auto.write_text('''@echo off
cd /d "%~dp0"
echo.
echo Removing ICCSFlux from automatic startup...
echo.
schtasks /delete /tn "ICCSFlux" /f 2>nul
echo.
echo Done. ICCSFlux will no longer start automatically.
echo.
pause
''')

    # NSSM-based Windows Service (runs even when logged out)
    install_svc = BUILD_DIR / "Install-Service.bat"
    install_svc.write_text('''@echo off
cd /d "%~dp0"
echo.
echo Installing ICCSFlux as a Windows Service...
echo (This will run even when logged out)
echo.

if not exist "nssm\\nssm.exe" (
    echo ERROR: nssm.exe not found in nssm folder.
    echo Download from https://nssm.cc/download and copy nssm.exe to the nssm folder.
    echo.
    pause
    exit /b 1
)

nssm\\nssm.exe install ICCSFlux "%~dp0python\\pythonw.exe" "%~dp0ICCSFlux.py"
nssm\\nssm.exe set ICCSFlux AppDirectory "%~dp0"
nssm\\nssm.exe set ICCSFlux DisplayName "ICCSFlux Data Acquisition"
nssm\\nssm.exe set ICCSFlux Description "Industrial data acquisition and control service"
nssm\\nssm.exe set ICCSFlux Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux AppStdout "%~dp0data\\logs\\service.log"
nssm\\nssm.exe set ICCSFlux AppStderr "%~dp0data\\logs\\service.log"
nssm\\nssm.exe set ICCSFlux AppRotateFiles 1
nssm\\nssm.exe set ICCSFlux AppRotateBytes 10485760

echo.
echo Service installed. Starting...
net start ICCSFlux

echo.
echo Done! ICCSFlux is now running as a Windows service.
echo.
echo You can manage it via:
echo   - Services (services.msc)
echo   - net start/stop ICCSFlux
echo   - Uninstall-Service.bat to remove
echo.
pause
''')

    uninstall_svc = BUILD_DIR / "Uninstall-Service.bat"
    uninstall_svc.write_text('''@echo off
cd /d "%~dp0"
echo.
echo Removing ICCSFlux Windows Service...
echo.

if not exist "nssm\\nssm.exe" (
    echo ERROR: nssm.exe not found. Trying net stop...
    net stop ICCSFlux 2>nul
    sc delete ICCSFlux 2>nul
) else (
    nssm\\nssm.exe stop ICCSFlux 2>nul
    nssm\\nssm.exe remove ICCSFlux confirm
)

echo.
echo Done. ICCSFlux service removed.
echo.
pause
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


RUNNING IN BACKGROUND
---------------------
Double-click these files:

  Start-Background.bat    - Run without console window
  Stop-ICCSFlux.bat       - Stop ICCSFlux

AUTO-START ON LOGIN
-------------------
Double-click these files:

  Install-AutoStart.bat   - Start when you log in
  Uninstall-AutoStart.bat - Remove auto-start

WINDOWS SERVICE (runs even when logged out)
-------------------------------------------
Double-click these files:

  Install-Service.bat     - Install as Windows service
  Uninstall-Service.bat   - Remove Windows service


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
See the docs/ folder (read in order):

  01_Getting_Started.md     - Start here! Quick setup guide
  02_Quick_Reference.md     - Cheat sheet for common tasks
  03_User_Manual.md         - Complete reference manual
  04_Python_Scripting.md    - Writing automation scripts
  05_Remote_Nodes.md        - Multi-node/distributed setup
  06_Administrator_Guide.md - IT/Admin configuration


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
    setup_nssm()
    setup_azure_uploader()

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
