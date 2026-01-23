"""
Pytest configuration and shared fixtures for NISystem tests

Provides robust test harness with:
- Proper MQTT connection management
- Acquisition state management
- Reliable message waiting with subscription confirmation
- System status checking
"""

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

# Re-export for backwards compatibility
__all__ = ['MQTTTestHarness', 'MQTTTestFixture', 'MQTT_HOST', 'MQTT_PORT', 'SYSTEM_PREFIX']


@pytest.fixture
def mqtt_client():
    """Provide a connected MQTT test client"""
    client = MQTTTestHarness(f"pytest-{time.time()}")
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
def check_services():
    """Check that required services are running"""
    client = MQTTTestHarness("service-check")
    if not client.connect(timeout=3.0):
        pytest.skip("MQTT broker not available")

    # Check for DAQ service by waiting for status
    client.wait_for_status(timeout=3.0)
    status = client.get_system_status()
    if not status:
        client.disconnect()
        pytest.skip("DAQ service not responding")

    client.disconnect()
