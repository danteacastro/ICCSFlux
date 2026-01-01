"""
Build NISystem as a portable Windows application.

This creates a self-contained folder that can run on any Windows PC
without installing Python, Node.js, or Mosquitto.

Usage: python build_portable.py

Output: dist/NISystem-Portable/
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import tempfile
from pathlib import Path

# Configuration
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.11.7/python-3.11.7-embed-amd64.zip"
MOSQUITTO_URL = "https://mosquitto.org/files/binary/win64/mosquitto-2.0.18-install-windows-x64.exe"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

PROJECT_ROOT = Path(__file__).parent
BUILD_DIR = PROJECT_ROOT / "dist" / "NISystem-Portable"


def log(msg):
    print(f"[BUILD] {msg}")


def download_file(url, dest):
    """Download a file with progress"""
    log(f"Downloading {url.split('/')[-1]}...")
    urllib.request.urlretrieve(url, dest)


def build_dashboard():
    """Build the Vue dashboard to static files"""
    log("Building dashboard...")
    dashboard_dir = PROJECT_ROOT / "dashboard"

    # Check if node_modules exists
    if not (dashboard_dir / "node_modules").exists():
        log("Installing npm dependencies...")
        subprocess.run(["npm", "install"], cwd=dashboard_dir, check=True)

    # Build
    subprocess.run(["npm", "run", "build"], cwd=dashboard_dir, check=True)

    return dashboard_dir / "dist"


def setup_embedded_python():
    """Download and setup embedded Python"""
    python_dir = BUILD_DIR / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    # Download embedded Python
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        download_file(PYTHON_EMBED_URL, tmp.name)

        log("Extracting Python...")
        with zipfile.ZipFile(tmp.name, 'r') as zf:
            zf.extractall(python_dir)

        os.unlink(tmp.name)

    # Enable pip by modifying python311._pth
    pth_file = python_dir / "python311._pth"
    if pth_file.exists():
        content = pth_file.read_text()
        # Uncomment import site
        content = content.replace("#import site", "import site")
        # Add Lib\site-packages
        if "Lib\\site-packages" not in content:
            content += "\nLib\\site-packages\n"
        pth_file.write_text(content)

    # Download and run get-pip
    log("Installing pip...")
    get_pip = python_dir / "get-pip.py"
    download_file(GET_PIP_URL, str(get_pip))

    python_exe = python_dir / "python.exe"
    subprocess.run([str(python_exe), str(get_pip), "--no-warn-script-location"],
                   cwd=python_dir, check=True)
    get_pip.unlink()

    # Install required packages
    log("Installing Python packages...")
    subprocess.run([
        str(python_exe), "-m", "pip", "install",
        "paho-mqtt", "--no-warn-script-location"
    ], check=True)

    return python_dir


def setup_mosquitto():
    """Setup portable Mosquitto"""
    mosquitto_dir = BUILD_DIR / "mosquitto"
    mosquitto_dir.mkdir(parents=True, exist_ok=True)

    # For portable, we just need mosquitto.exe and its DLLs
    # Download from a simpler source or bundle pre-extracted files
    log("Setting up Mosquitto...")

    # Create a simple mosquitto config
    config = mosquitto_dir / "mosquitto.conf"
    config.write_text("""# Portable Mosquitto config
listener 1883 127.0.0.1
listener 9001 127.0.0.1
protocol websockets
allow_anonymous true
""")

    # Note: User needs to copy mosquitto.exe manually or we download portable version
    log("NOTE: Copy mosquitto.exe and required DLLs to: " + str(mosquitto_dir))

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
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache')
    )

    # Copy config
    config_dest = BUILD_DIR / "config"
    if config_dest.exists():
        shutil.rmtree(config_dest)
    shutil.copytree(PROJECT_ROOT / "config", config_dest)

    # Copy launcher
    launcher_dest = BUILD_DIR / "launcher"
    launcher_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        PROJECT_ROOT / "launcher" / "nisystem_launcher.py",
        launcher_dest / "nisystem_launcher.py"
    )


def copy_dashboard_build(dashboard_dist):
    """Copy built dashboard files"""
    log("Copying dashboard build...")

    www_dest = BUILD_DIR / "www"
    if www_dest.exists():
        shutil.rmtree(www_dest)
    shutil.copytree(dashboard_dist, www_dest)


def create_launcher():
    """Create the main launcher script"""
    log("Creating launcher...")

    launcher = BUILD_DIR / "NISystem.py"
    launcher.write_text('''#!/usr/bin/env python3
"""
NISystem Portable Launcher
Starts all services and opens the dashboard.
"""

import os
import sys
import subprocess
import time
import webbrowser
import signal
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

ROOT = Path(__file__).parent
PYTHON = ROOT / "python" / "python.exe"
MOSQUITTO = ROOT / "mosquitto" / "mosquitto.exe"
MOSQUITTO_CONF = ROOT / "mosquitto" / "mosquitto.conf"
DAQ_SERVICE = ROOT / "services" / "daq_service" / "daq_service.py"
CONFIG = ROOT / "config" / "system.ini"
WWW = ROOT / "www"

processes = []


def start_mosquitto():
    """Start Mosquitto broker"""
    if not MOSQUITTO.exists():
        print("[WARN] Mosquitto not found - MQTT will not work")
        print(f"       Please copy mosquitto.exe to: {MOSQUITTO.parent}")
        return None

    print("[START] Mosquitto MQTT broker...")

    args = [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF)]
    proc = subprocess.Popen(args, cwd=str(MOSQUITTO.parent))
    processes.append(proc)
    return proc


def start_daq_service():
    """Start DAQ service"""
    print("[START] DAQ Service...")

    proc = subprocess.Popen(
        [str(PYTHON), str(DAQ_SERVICE), "-c", str(CONFIG)],
        cwd=str(DAQ_SERVICE.parent)
    )
    processes.append(proc)
    return proc


def start_web_server(port=5173):
    """Start web server for dashboard"""
    print(f"[START] Web server on port {port}...")

    os.chdir(WWW)

    handler = SimpleHTTPRequestHandler
    httpd = HTTPServer(("127.0.0.1", port), handler)

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    return httpd


def cleanup(signum=None, frame=None):
    """Clean up all processes"""
    print("\\n[STOP] Shutting down...")

    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            proc.kill()

    sys.exit(0)


def main():
    print("=" * 50)
    print("  NISystem Portable")
    print("=" * 50)
    print()

    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Start services
    start_mosquitto()
    time.sleep(1)

    start_daq_service()
    time.sleep(2)

    httpd = start_web_server()

    print()
    print("=" * 50)
    print("  NISystem Ready!")
    print("  Dashboard: http://localhost:5173")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print()

    # Open browser
    webbrowser.open("http://localhost:5173")

    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
''')

    # Create batch launcher
    bat = BUILD_DIR / "NISystem.bat"
    bat.write_text('''@echo off
cd /d "%~dp0"
python\\python.exe NISystem.py
pause
''')


def main():
    print("=" * 50)
    print("  NISystem Portable Builder")
    print("=" * 50)
    print()

    # Clean build dir
    if BUILD_DIR.exists():
        log("Cleaning previous build...")
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # Build dashboard
    dashboard_dist = build_dashboard()

    # Setup components
    setup_embedded_python()
    setup_mosquitto()
    copy_project_files()
    copy_dashboard_build(dashboard_dist)
    create_launcher()

    print()
    print("=" * 50)
    log("Build complete!")
    print(f"  Output: {BUILD_DIR}")
    print()
    print("  To complete portable setup:")
    print("  1. Download Mosquitto from https://mosquitto.org/files/binary/win64/")
    print("  2. Extract mosquitto.exe and DLLs to: dist/NISystem-Portable/mosquitto/")
    print()
    print("  To run: Double-click NISystem.bat")
    print("=" * 50)


if __name__ == "__main__":
    main()
