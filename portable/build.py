"""
NISystem Portable Builder

Builds a complete, self-contained portable application.
Target PC needs NOTHING installed.

Run on dev machine: python portable/build.py

Output: portable/dist/NISystem/
  - nisystem-server.exe  <- Run this from command line
  - config/              <- INI files (hardware config)
  - projects/            <- JSON project files (frontend state)
  - www/                 <- Dashboard frontend
  - runtime/             <- Python + Mosquitto
  - logs/                <- Runtime logs
  - data/                <- Recorded data

Usage on target PC:
  > nisystem-server.exe
  Then open http://localhost:5173 in browser
  Ctrl+C to stop
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import stat
from pathlib import Path

PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
MOSQUITTO_VERSION = "2.0.18"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
BUILD_DIR = SCRIPT_DIR / "build"
DIST_DIR = SCRIPT_DIR / "dist" / "NISystem"


def log(msg):
    print(f"[*] {msg}")


def run_cmd(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"Command failed: {cmd}")
    return result


def download(url, dest):
    log(f"Downloading {Path(url).name}...")
    urllib.request.urlretrieve(url, dest)


def rmtree(path):
    if path.exists():
        shutil.rmtree(path, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))


def clean():
    log("Cleaning...")
    rmtree(BUILD_DIR)
    rmtree(DIST_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def build_dashboard():
    log("Building dashboard...")
    src = PROJECT_ROOT / "dashboard"

    if not (src / "node_modules").exists():
        run_cmd(["npm", "install"], cwd=src)

    run_cmd(["npm", "run", "build"], cwd=src)
    shutil.copytree(src / "dist", DIST_DIR / "www")


def setup_python():
    log("Setting up Python...")

    python_dir = DIST_DIR / "runtime" / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    # Download embedded Python
    zip_path = BUILD_DIR / "python.zip"
    download(PYTHON_EMBED_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(python_dir)

    # Enable imports
    for pth in python_dir.glob("python*._pth"):
        pth.write_text(pth.read_text().replace("#import site", "import site"))

    # Install pip
    get_pip = BUILD_DIR / "get-pip.py"
    download(GET_PIP_URL, get_pip)
    python_exe = python_dir / "python.exe"
    run_cmd([str(python_exe), str(get_pip), "--no-warn-script-location"])

    # Install packages
    run_cmd([str(python_exe), "-m", "pip", "install", "paho-mqtt", "pyinstaller", "--no-warn-script-location"])


def setup_mosquitto():
    log("Setting up Mosquitto...")

    mq_dir = DIST_DIR / "runtime" / "mosquitto"
    mq_dir.mkdir(parents=True, exist_ok=True)

    (mq_dir / "mosquitto.conf").write_text(
        "listener 1883 127.0.0.1\n\nlistener 9001 127.0.0.1\nprotocol websockets\n\nallow_anonymous true\n"
    )

    # Download mosquitto
    try:
        zip_url = f"https://mosquitto.org/files/binary/win64/mosquitto-{MOSQUITTO_VERSION}-install-windows-x64.zip"
        zip_path = BUILD_DIR / "mosquitto.zip"
        download(zip_url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith(('.exe', '.dll')):
                    (mq_dir / Path(name).name).write_bytes(zf.read(name))
    except Exception as e:
        log(f"WARN: Could not download Mosquitto: {e}")


def copy_services():
    log("Copying services...")

    shutil.copytree(
        PROJECT_ROOT / "services", DIST_DIR / "services",
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.log')
    )
    shutil.copytree(PROJECT_ROOT / "config", DIST_DIR / "config")
    (DIST_DIR / "logs").mkdir(exist_ok=True)
    (DIST_DIR / "data").mkdir(exist_ok=True)
    (DIST_DIR / "projects").mkdir(exist_ok=True)  # Project files (JSON)

    # Set simulation_mode = false for production
    config_file = DIST_DIR / "config" / "system.ini"
    if config_file.exists():
        content = config_file.read_text()
        content = content.replace("simulation_mode = true", "simulation_mode = false")
        content = content.replace("simulation_mode=true", "simulation_mode=false")
        config_file.write_text(content)
        log("Set simulation_mode = false for production")


def create_server_exe():
    log("Creating nisystem-server.exe...")

    server_py = BUILD_DIR / "nisystem_server.py"
    server_py.write_text('''#!/usr/bin/env python3
"""NISystem Server - Run from command line, Ctrl+C to stop"""

import os
import sys
import subprocess
import signal
import time
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent.parent / "dist" / "NISystem"

processes = []
server = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "www"), **kw)
    def log_message(self, *a):
        pass


def stop(sig=None, frame=None):
    print("\\nStopping...")
    if server:
        server.shutdown()
    for p in processes:
        p.terminate()
    for p in processes:
        try:
            p.wait(timeout=2)
        except:
            p.kill()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print("=" * 50)
    print("  NISystem Server")
    print("=" * 50)
    print()

    # Start Mosquitto
    mq = ROOT / "runtime" / "mosquitto" / "mosquitto.exe"
    mq_conf = ROOT / "runtime" / "mosquitto" / "mosquitto.conf"
    if mq.exists():
        print("[*] Starting MQTT broker...")
        p = subprocess.Popen([str(mq), "-c", str(mq_conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(p)
        time.sleep(0.5)

    # Start DAQ service
    print("[*] Starting DAQ service...")
    py = ROOT / "runtime" / "python" / "python.exe"
    daq = ROOT / "services" / "daq_service" / "daq_service.py"
    cfg = ROOT / "config" / "system.ini"
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    with open(log_dir / "daq.log", "w") as log:
        p = subprocess.Popen([str(py), str(daq), "-c", str(cfg)], stdout=log, stderr=subprocess.STDOUT, cwd=str(daq.parent))
        processes.append(p)
    time.sleep(1)

    # Start HTTP server
    print("[*] Starting web server...")
    global server
    server = HTTPServer(("0.0.0.0", 5173), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print()
    print("=" * 50)
    print("  Ready: http://localhost:5173")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
''')

    # Build with PyInstaller using the embedded Python
    python_exe = DIST_DIR / "runtime" / "python" / "python.exe"
    run_cmd([
        str(python_exe), "-m", "PyInstaller",
        "--onefile",
        "--console",  # Console app like Grafana
        "--name", "nisystem-server",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "pyinstaller"),
        "--specpath", str(BUILD_DIR),
        "--clean",
        str(server_py)
    ])


def main():
    print("=" * 60)
    print("  NISystem Portable Builder")
    print("=" * 60)
    print()

    clean()
    build_dashboard()
    setup_python()
    setup_mosquitto()
    copy_services()
    create_server_exe()

    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print()
    print(f"  Output: {DIST_DIR}")
    print()
    print("  Copy the NISystem folder to any Windows PC.")
    print("  Run: nisystem-server.exe")
    print("  Open: http://localhost:5173")
    print("=" * 60)


if __name__ == "__main__":
    main()
