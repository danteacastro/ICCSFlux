"""
Tests for dashboard_server.py
Covers the static file server for the Vue dashboard.
"""

import pytest
import tempfile
import threading
import time
import json
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import socket

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent))

from dashboard_server import DashboardServer, DashboardHandler
from test_helpers import wait_until


def _wait_for_server(server, port, timeout=3.0):
    """Wait until the dashboard server is accepting connections."""
    wait_until(lambda: server.is_running(), timeout=timeout)
    # Also verify the port is actually accepting TCP connections
    def _port_open():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except Exception:
            return False
    wait_until(_port_open, timeout=timeout)


class TestDashboardHandler:
    """Tests for DashboardHandler class"""

    def test_extensions_map(self):
        """Test that custom MIME types are defined"""
        assert DashboardHandler.extensions_map['.js'] == 'application/javascript'
        assert DashboardHandler.extensions_map['.mjs'] == 'application/javascript'
        assert DashboardHandler.extensions_map['.json'] == 'application/json'
        assert DashboardHandler.extensions_map['.wasm'] == 'application/wasm'
        assert DashboardHandler.extensions_map['.svg'] == 'image/svg+xml'
        assert DashboardHandler.extensions_map['.woff'] == 'font/woff'
        assert DashboardHandler.extensions_map['.woff2'] == 'font/woff2'


class TestDashboardServer:
    """Tests for DashboardServer class"""

    @pytest.fixture
    def dashboard_dir(self):
        """Create a temporary dashboard dist directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_path = Path(tmpdir)

            # Create minimal dashboard structure
            (dist_path / 'index.html').write_text('''
<!DOCTYPE html>
<html>
<head><title>Test Dashboard</title></head>
<body><h1>Dashboard</h1></body>
</html>
''')
            (dist_path / 'assets').mkdir()
            (dist_path / 'assets' / 'main.js').write_text('console.log("test");')
            (dist_path / 'assets' / 'style.css').write_text('body { margin: 0; }')

            yield dist_path

    @pytest.fixture
    def free_port(self):
        """Find a free port for testing"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
        return port

    def test_initialization_default(self):
        """Test default initialization"""
        server = DashboardServer()
        assert server.port == 8080
        assert server.dist_path is not None
        assert server.server is None
        assert server.thread is None

    def test_initialization_custom_port(self):
        """Test initialization with custom port"""
        server = DashboardServer(port=9000)
        assert server.port == 9000

    def test_initialization_custom_dist_path(self, dashboard_dir):
        """Test initialization with custom dist path"""
        server = DashboardServer(dist_path=dashboard_dir)
        assert server.dist_path == dashboard_dir

    def test_start_missing_dist(self):
        """Test that start fails if dist directory is missing"""
        server = DashboardServer(dist_path=Path('/nonexistent/path'))
        result = server.start()
        assert result is False

    def test_start_missing_index(self):
        """Test that start fails if index.html is missing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = DashboardServer(dist_path=Path(tmpdir))
            result = server.start()
            assert result is False

    def test_start_and_stop(self, dashboard_dir, free_port):
        """Test starting and stopping the server"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)

        result = server.start()
        assert result is True
        assert server.is_running() is True

        _wait_for_server(server, free_port)

        server.stop()
        assert server.is_running() is False

    def test_is_running(self, dashboard_dir, free_port):
        """Test is_running method"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)

        assert server.is_running() is False

        server.start()
        _wait_for_server(server, free_port)
        assert server.is_running() is True

        server.stop()
        assert wait_until(lambda: not server.is_running(), timeout=3.0), \
            "Server did not stop"

    def test_serve_index_html(self, dashboard_dir, free_port):
        """Test serving index.html"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            response = urlopen(f'http://localhost:{free_port}/')
            content = response.read().decode()

            assert response.status == 200
            assert 'Test Dashboard' in content
        except URLError:
            pytest.fail("Could not connect to server")
        finally:
            server.stop()

    def test_serve_static_asset(self, dashboard_dir, free_port):
        """Test serving static assets"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            response = urlopen(f'http://localhost:{free_port}/assets/main.js')
            content = response.read().decode()

            assert response.status == 200
            assert 'console.log' in content
        except URLError:
            pytest.fail("Could not connect to server")
        finally:
            server.stop()

    def test_health_endpoint(self, dashboard_dir, free_port):
        """Test /health endpoint"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            response = urlopen(f'http://localhost:{free_port}/health')
            content = json.loads(response.read().decode())

            assert response.status == 200
            assert content['status'] == 'ok'
            assert content['server'] == 'dashboard'
        except URLError:
            pytest.fail("Could not connect to server")
        finally:
            server.stop()

    def test_spa_fallback(self, dashboard_dir, free_port):
        """Test SPA fallback for unmatched routes"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            # Request a path that doesn't exist should fallback to index.html
            response = urlopen(f'http://localhost:{free_port}/some/app/route')
            content = response.read().decode()

            assert response.status == 200
            assert 'Test Dashboard' in content  # Should serve index.html
        except URLError:
            pytest.fail("Could not connect to server")
        finally:
            server.stop()

    def test_api_route_returns_404(self, dashboard_dir, free_port):
        """Test that /api/ routes return 404"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            urlopen(f'http://localhost:{free_port}/api/test')
            pytest.fail("Expected 404 error")
        except URLError as e:
            # Should get 404
            assert '404' in str(e)
        finally:
            server.stop()

    def test_concurrent_requests(self, dashboard_dir, free_port):
        """Test handling concurrent requests"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        errors = []
        results = []

        def make_request(path):
            try:
                response = urlopen(f'http://localhost:{free_port}{path}')
                results.append(response.status)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(10):
            t = threading.Thread(target=make_request, args=('/health',))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        server.stop()

        assert len(errors) == 0
        assert all(status == 200 for status in results)

    def test_port_already_in_use(self, dashboard_dir, free_port):
        """Test behavior when port is already in use"""
        import sys

        # Start first server
        server1 = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server1.start()
        _wait_for_server(server1, free_port)

        # Try to start second server on same port
        server2 = DashboardServer(port=free_port, dist_path=dashboard_dir)
        result = server2.start()

        # On Windows with SO_REUSEADDR, the second bind may succeed
        # The important behavior is that we don't crash
        if sys.platform == 'win32':
            # On Windows, result may be True or False depending on timing
            # Just verify no exception was raised
            if result:
                server2.stop()
        else:
            assert result is False

        server1.stop()

    def test_server_runs_in_daemon_thread(self, dashboard_dir, free_port):
        """Test that server thread is a daemon"""
        server = DashboardServer(port=free_port, dist_path=dashboard_dir)
        server.start()
        _wait_for_server(server, free_port)

        assert server.thread is not None
        assert server.thread.daemon is True

        server.stop()


class TestMakeHandler:
    """Tests for _make_handler method"""

    def test_handler_creation(self, ):
        """Test that custom handler is created with correct dist_path"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_path = Path(tmpdir)
            (dist_path / 'index.html').write_text('<html></html>')

            server = DashboardServer(dist_path=dist_path)
            handler_class = server._make_handler()

            # Verify it's a class
            assert isinstance(handler_class, type)

            # Verify it's a subclass of DashboardHandler
            assert issubclass(handler_class, DashboardHandler)


class TestDirectoryIndex:
    """Tests for directory index handling"""

    @pytest.fixture
    def dashboard_with_subdir(self):
        """Create dashboard with subdirectory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_path = Path(tmpdir)

            # Create main index
            (dist_path / 'index.html').write_text('<html>Main</html>')

            # Create subdirectory with index
            subdir = dist_path / 'docs'
            subdir.mkdir()
            (subdir / 'index.html').write_text('<html>Docs</html>')

            yield dist_path

    @pytest.fixture
    def free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
        return port

    def test_serve_directory_index(self, dashboard_with_subdir, free_port):
        """Test serving index.html from subdirectory"""
        server = DashboardServer(port=free_port, dist_path=dashboard_with_subdir)
        server.start()
        _wait_for_server(server, free_port)

        try:
            response = urlopen(f'http://localhost:{free_port}/docs/')
            content = response.read().decode()

            assert response.status == 200
            assert 'Docs' in content
        except URLError:
            pytest.fail("Could not connect to server")
        finally:
            server.stop()
