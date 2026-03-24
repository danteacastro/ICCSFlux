#!/usr/bin/env python3
"""
ICCSFlux Fleet Monitor — Portable Launcher

Serves the built monitor SPA and opens the browser.
Compile with PyInstaller for a standalone .exe.
"""

import os
import sys
import signal
import socket
import argparse
import webbrowser
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Detect if running as windowed app (no console)
SERVICE_MODE = not sys.stdout or not sys.stdout.isatty()

# Root directory (exe location or script parent)
if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).parent.resolve()
else:
    ROOT = Path(__file__).parent.parent.resolve()  # project root when run as script

WWW = ROOT / "monitor" / "dist" if not getattr(sys, 'frozen', False) else ROOT / "www"

DEFAULT_PORT = 5174

class MonitorHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler for Vue SPA with proper MIME types and SPA fallback."""

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
        """Serve files with SPA fallback — unknown paths serve index.html."""
        path = self.translate_path(self.path)
        if os.path.exists(path) and not os.path.isdir(path):
            return super().do_GET()
        if os.path.isdir(path):
            index = os.path.join(path, 'index.html')
            if os.path.exists(index):
                return super().do_GET()
        # SPA fallback
        self.path = '/index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        pass  # Suppress routine request logging

    def log_error(self, format, *args):
        if not SERVICE_MODE:
            print(f"[HTTP] ERROR: {format % args}")

def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0

def find_available_port(start: int) -> int:
    """Find an available port starting from `start`."""
    for port in range(start, start + 20):
        if is_port_available(port):
            return port
    return start

def main():
    parser = argparse.ArgumentParser(
        description="ICCSFlux Fleet Monitor — Portable Launcher",
    )
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser automatically")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Web server port (default: {DEFAULT_PORT})")
    parser.add_argument("-v", "--version", action="version",
                        version="ICCSFlux Fleet Monitor 0.1.0-alpha")
    args = parser.parse_args()

    if not WWW.exists():
        print(f"[ERROR] Monitor web files not found at {WWW}")
        print("        Run 'npm run build' in the monitor/ directory first.")
        if not SERVICE_MODE:
            input("Press Enter to exit...")
        return 1

    port = find_available_port(args.port)

    print()
    print("=" * 50)
    print("    ICCSFlux Fleet Monitor")
    print("=" * 50)
    print()
    print(f"  Serving from:  {WWW}")
    print(f"  URL:           http://localhost:{port}")
    print()
    print("  Press Ctrl+C to stop")
    print()

    # Change to www directory so HTTPServer serves from there
    os.chdir(WWW)

    server = HTTPServer(('127.0.0.1', port), MonitorHTTPHandler)

    # Run server in a thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Open browser
    if not args.no_browser:
        webbrowser.open(f'http://localhost:{port}')

    # Wait for shutdown signal
    def shutdown(*_):
        print("\n[SHUTDOWN] Stopping Fleet Monitor...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep main thread alive
    try:
        server_thread.join()
    except KeyboardInterrupt:
        shutdown()

    return 0

if __name__ == '__main__':
    sys.exit(main())
