"""
Pytest configuration and shared fixtures for NISystem tests

Provides robust test harness with:
- Automatic MQTT broker startup (no manual NISystem Start.bat needed)
- Proper MQTT connection management with authentication
- Acquisition state management
- Reliable message waiting with subscription confirmation
- System status checking
"""


def pytest_configure(config):
    """Register custom markers for layer-based test selection."""
    for i in range(1, 18):
        config.addinivalue_line(
            "markers", f"layer{i}: System validation layer {i}"
        )

import json
import os
import pytest
import time
import sys
from pathlib import Path

# Add tests directory to path for imports
tests_dir = Path(__file__).parent
if str(tests_dir) not in sys.path:
    sys.path.insert(0, str(tests_dir))

# Import shared utilities from test_helpers
from test_helpers import (
    MQTTTestHarness,
    MQTTTestFixture,
    MQTT_HOST,
    MQTT_PORT,
    SYSTEM_PREFIX,
)

from service_fixtures import (
    start_mosquitto,
    stop_mosquitto,
    start_daq_service,
    stop_daq_service,
    is_port_open,
    load_mqtt_credentials,
)

# Re-export for backwards compatibility
__all__ = ['MQTTTestHarness', 'MQTTTestFixture', 'MQTT_HOST', 'MQTT_PORT', 'SYSTEM_PREFIX']


# =============================================================================
# Session-Scoped Service Fixtures (auto-start/stop)
# =============================================================================

@pytest.fixture(scope="session")
def mqtt_broker():
    """
    Session-scoped: ensure MQTT broker is running for the test session.

    - If Mosquitto is already running on port 1883, uses it (no teardown).
    - If not, starts it silently and tears it down after the session.
    - If Mosquitto executable is not found, skips the test.

    Yields connection info dict:
        {"host": str, "port": int, "username": str|None, "password": str|None}
    """
    proc, we_started, conn_info = start_mosquitto(port=1883)

    if not is_port_open('127.0.0.1', conn_info['port']):
        pytest.skip(
            "MQTT broker not available and could not auto-start "
            "(mosquitto.exe not found in vendor/ or Program Files)"
        )

    yield conn_info

    if we_started:
        stop_mosquitto(proc)


# Known test password for the test_admin user (created by ensure_test_admin)
_TEST_ADMIN_PASSWORD = "validation_test_pw_2026"


@pytest.fixture(scope="session")
def ensure_test_admin():
    """Create a 'test_admin' user in data/users.json before DAQ service starts.

    The DAQ service loads users.json on startup. If the admin password has been
    changed (common in production), tests can't log in. This fixture creates a
    dedicated test_admin user with a known password so the validation suite can
    always authenticate.

    Must run BEFORE daq_service fixture (enforced by fixture dependency).
    """
    project_root = Path(__file__).parent.parent
    users_file = project_root / "data" / "users.json"

    created = False
    if users_file.exists():
        try:
            import bcrypt
            users = json.loads(users_file.read_text(encoding="utf-8"))

            if "test_admin" not in users:
                salt = bcrypt.gensalt()
                pw_hash = bcrypt.hashpw(
                    _TEST_ADMIN_PASSWORD.encode("utf-8"), salt
                ).decode("utf-8")

                users["test_admin"] = {
                    "username": "test_admin",
                    "password_hash": pw_hash,
                    "role": "admin",
                    "display_name": "Test Admin (validation suite)",
                    "email": "",
                    "enabled": True,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "last_login": "",
                    "failed_attempts": 0,
                    "locked_until": None,
                    "must_change_password": False,
                    "custom_permissions": [],
                }
                users_file.write_text(
                    json.dumps(users, indent=2), encoding="utf-8"
                )
                created = True
        except Exception:
            pass

    yield {"username": "test_admin", "password": _TEST_ADMIN_PASSWORD}

    # Don't remove the user on teardown — it's harmless and avoids
    # issues if the DAQ service is still using it


@pytest.fixture(scope="session")
def daq_service(mqtt_broker, ensure_test_admin):
    """
    Session-scoped: ensure DAQ service is running.
    Depends on mqtt_broker fixture (broker must be up first).
    Depends on ensure_test_admin (test user must exist before DAQ starts).

    - If DAQ service is already publishing status, uses it (no teardown).
    - If not, starts it and tears it down after the session.
    """
    proc, we_started = start_daq_service(
        mqtt_host=mqtt_broker['host'],
        mqtt_port=mqtt_broker['port'],
        username=mqtt_broker.get('username'),
        password=mqtt_broker.get('password'),
    )

    yield {
        "already_running": not we_started,
        "host": mqtt_broker['host'],
        "port": mqtt_broker['port'],
    }

    if we_started:
        stop_daq_service(proc)


# =============================================================================
# Per-Test MQTT Client Fixtures
# =============================================================================

@pytest.fixture
def mqtt_client(mqtt_broker):
    """Provide a connected MQTT test client with auto-started broker."""
    client = MQTTTestHarness(
        f"pytest-{time.time()}",
        username=mqtt_broker.get('username'),
        password=mqtt_broker.get('password'),
    )
    assert client.connect(), "Failed to connect to MQTT broker"
    # Wait for initial status
    client.wait_for_status(timeout=2.0)
    yield client
    client.disconnect()


@pytest.fixture
def mqtt_client_acquiring(mqtt_client):
    """
    Provide MQTT client with acquisition guaranteed to be running.
    Cleans up by stopping acquisition after test.
    """
    assert mqtt_client.ensure_acquiring(), "Failed to start acquisition"
    # Give the system a moment to stabilize
    time.sleep(0.5)
    yield mqtt_client
    mqtt_client.ensure_not_acquiring()


@pytest.fixture
def mqtt_client_clean(mqtt_client):
    """
    Provide MQTT client with clean state (no acquisition, no recording).
    """
    mqtt_client.ensure_not_recording()
    mqtt_client.ensure_not_acquiring()
    time.sleep(0.3)
    yield mqtt_client


@pytest.fixture(scope="session")
def check_services(mqtt_broker):
    """Check that required services are running (uses auto-started broker)."""
    client = MQTTTestHarness(
        "service-check",
        username=mqtt_broker.get('username'),
        password=mqtt_broker.get('password'),
    )
    if not client.connect(timeout=3.0):
        pytest.skip("MQTT broker not available")

    # Check for DAQ service by waiting for status
    client.wait_for_status(timeout=3.0)
    status = client.get_system_status()
    if not status:
        client.disconnect()
        pytest.skip("DAQ service not responding")

    client.disconnect()
