#!/usr/bin/env python3
"""
NISystem Server
Run from command line, access via browser at http://localhost:5173
Press Ctrl+C to stop.
"""

import os
import sys
import subprocess
import signal
import time
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = Path(__file__).parent
PYTHON = ROOT / "runtime" / "python" / "python.exe"
MOSQUITTO = ROOT / "runtime" / "mosquitto" / "mosquitto.exe"
MOSQUITTO_CONF = ROOT / "runtime" / "mosquitto" / "mosquitto.conf"
DAQ_SERVICE = ROOT / "services" / "daq_service" / "daq_service.py"
CONFIG = ROOT / "config" / "system.ini"
WWW = ROOT / "www"

processes = []
http_server = None


class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def log_message(self, format, *args):
        pass  # Quiet


def start_mosquitto():
    if not MOSQUITTO.exists():
        print("[WARN] Mosquitto not found")
        return None

    proc = subprocess.Popen(
        [str(MOSQUITTO), "-c", str(MOSQUITTO_CONF)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    processes.append(proc)
    return proc


def start_daq():
    log_file = ROOT / "logs" / "daq.log"
    log_file.parent.mkdir(exist_ok=True)

    with open(log_file, "w") as log:
        proc = subprocess.Popen(
            [str(PYTHON), str(DAQ_SERVICE), "-c", str(CONFIG)],
            cwd=str(DAQ_SERVICE.parent),
            stdout=log,
            stderr=subprocess.STDOUT
        )
    processes.append(proc)
    return proc


def start_http(port=5173):
    global http_server
    http_server = HTTPServer(("0.0.0.0", port), QuietHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()


def stop_all(sig=None, frame=None):
    print("\nShutting down...")

    if http_server:
        http_server.shutdown()

    for p in processes:
        p.terminate()

    for p in processes:
        try:
            p.wait(timeout=3)
        except:
            p.kill()

    print("Stopped.")
    sys.exit(0)


def main():
    print("=" * 50)
    print("  NISystem Server")
    print("=" * 50)
    print()

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    print("[*] Starting Mosquitto...")
    start_mosquitto()
    time.sleep(0.5)

    print("[*] Starting DAQ service...")
    start_daq()
    time.sleep(1)

    print("[*] Starting HTTP server...")
    start_http()

    print()
    print("=" * 50)
    print("  Ready: http://localhost:5173")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
