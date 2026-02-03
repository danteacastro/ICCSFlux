#!/usr/bin/env python3
"""
Dashboard Static File Server

Serves the built Vue dashboard as static files.
This allows the dashboard to run without needing a separate dev server.

Usage:
    python dashboard_server.py                    # Serve on port 8080
    python dashboard_server.py --port 80          # Serve on port 80
    python dashboard_server.py --dist /path/to/dist  # Custom dist path
"""

import argparse
import http.server
import json
import logging
import mimetypes
import os
import socketserver
import sys
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DashboardServer')


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler for Vue SPA with API proxy support"""

    # Custom MIME types
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.js': 'application/javascript',
        '.mjs': 'application/javascript',
        '.json': 'application/json',
        '.wasm': 'application/wasm',
        '.vue': 'text/html',
        '.svg': 'image/svg+xml',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
    }

    def __init__(self, *args, dist_path: Path = None, **kwargs):
        self.dist_path = dist_path or Path(__file__).parent.parent.parent / 'dashboard' / 'dist'
        super().__init__(*args, directory=str(self.dist_path), **kwargs)

    def do_GET(self):
        """Handle GET requests with SPA fallback"""
        # Parse path
        parsed = urlparse(self.path)
        path = parsed.path

        # API requests should go to backend (return 404 for now)
        if path.startswith('/api/'):
            self.send_error(404, 'API not available through static server')
            return

        # Health check
        if path == '/health':
            health_data = {'status': 'ok', 'server': 'dashboard'}
            if hasattr(self, 'metrics_provider') and self.metrics_provider:
                try:
                    metrics = self.metrics_provider()
                    health_data['acquiring'] = metrics.get('acquiring', False)
                    health_data['uptime_seconds'] = metrics.get('uptime_seconds', 0)
                    health_data['channel_count'] = metrics.get('channel_count', 0)
                except Exception:
                    pass
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_data).encode())
            return

        # Metrics endpoint
        if path == '/metrics':
            if hasattr(self, 'metrics_provider') and self.metrics_provider:
                try:
                    metrics_data = self.metrics_provider()
                except Exception as e:
                    metrics_data = {'error': str(e)}
            else:
                metrics_data = {'status': 'no metrics provider configured'}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(metrics_data).encode())
            return

        # Try to serve the file
        file_path = self.dist_path / path.lstrip('/')

        if file_path.is_file():
            # Serve the actual file
            super().do_GET()
        elif file_path.is_dir() and (file_path / 'index.html').exists():
            # Serve directory index
            self.path = path.rstrip('/') + '/index.html'
            super().do_GET()
        else:
            # SPA fallback: serve index.html for all unmatched routes
            index_path = self.dist_path / 'index.html'
            if index_path.exists():
                self.path = '/index.html'
                super().do_GET()
            else:
                self.send_error(404, f'File not found and no index.html for SPA fallback')

    def log_message(self, format, *args):
        """Override to use Python logging"""
        logger.info("%s - %s", self.address_string(), format % args)

    def log_error(self, format, *args):
        """Override to use Python logging"""
        logger.error("%s - %s", self.address_string(), format % args)


class DashboardServer:
    """Threaded HTTP server for dashboard"""

    def __init__(self, port: int = 8080, dist_path: Optional[Path] = None, metrics_provider=None):
        self.port = port
        self.dist_path = dist_path or Path(__file__).parent.parent.parent / 'dashboard' / 'dist'
        self.metrics_provider = metrics_provider
        self.server: Optional[socketserver.TCPServer] = None
        self.thread: Optional[threading.Thread] = None

    def _make_handler(self):
        """Create handler class with custom dist_path and metrics_provider"""
        dist_path = self.dist_path
        metrics_provider = self.metrics_provider

        class CustomHandler(DashboardHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, dist_path=dist_path, **kwargs)
                self.metrics_provider = metrics_provider

        return CustomHandler

    def start(self) -> bool:
        """Start the server in a background thread"""
        if not self.dist_path.exists():
            logger.error(f"Dashboard dist not found: {self.dist_path}")
            logger.info("Build the dashboard first: cd dashboard && npm run build")
            return False

        index_file = self.dist_path / 'index.html'
        if not index_file.exists():
            logger.error(f"index.html not found in {self.dist_path}")
            return False

        try:
            # Allow address reuse
            socketserver.TCPServer.allow_reuse_address = True

            handler = self._make_handler()
            self.server = socketserver.TCPServer(('', self.port), handler)

            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

            logger.info(f"Dashboard server started on http://localhost:{self.port}")
            return True

        except OSError as e:
            if 'Address already in use' in str(e) or e.errno == 10048:  # Windows
                logger.error(f"Port {self.port} is already in use")
            else:
                logger.error(f"Failed to start server: {e}")
            return False

    def stop(self):
        """Stop the server"""
        if self.server:
            logger.info("Stopping dashboard server...")
            self.server.shutdown()
            self.server = None
            self.thread = None

    def is_running(self) -> bool:
        """Check if server is running"""
        return self.server is not None and self.thread is not None and self.thread.is_alive()


def main():
    parser = argparse.ArgumentParser(description='NISystem Dashboard Server')
    parser.add_argument('--port', '-p', type=int, default=8080, help='Port to serve on')
    parser.add_argument('--dist', '-d', type=str, help='Path to dashboard dist directory')

    args = parser.parse_args()

    dist_path = Path(args.dist) if args.dist else None

    server = DashboardServer(port=args.port, dist_path=dist_path)

    if not server.start():
        sys.exit(1)

    print(f"\nDashboard available at: http://localhost:{args.port}")
    print("Press Ctrl+C to stop\n")

    try:
        # Keep main thread alive
        while server.is_running():
            server.thread.join(timeout=1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()


if __name__ == '__main__':
    main()
