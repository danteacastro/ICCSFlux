"""
Unit tests for DAQ Watchdog
Tests service health monitoring and fail-safe actions
"""

import pytest
import json
import time
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import tempfile

import sys
sys.path.insert(0, 'services/daq_service')

# Mock paho.mqtt before importing
@pytest.fixture(autouse=True)
def mock_paho():
    """Mock paho.mqtt"""
    mock_mqtt = MagicMock()
    mock_client = MagicMock()
    mock_mqtt.Client.return_value = mock_client
    mock_mqtt.CallbackAPIVersion = MagicMock()
    mock_mqtt.CallbackAPIVersion.VERSION2 = 2

    with patch.dict('sys.modules', {
        'paho': MagicMock(),
        'paho.mqtt': mock_mqtt,
        'paho.mqtt.client': mock_mqtt,
    }):
        yield mock_mqtt


from watchdog import WatchdogConfig, DAQWatchdog, load_config_from_ini


class TestWatchdogConfig:
    """Test WatchdogConfig dataclass"""

    def test_default_values(self):
        """Test default configuration values"""
        config = WatchdogConfig()

        assert config.mqtt_broker == "localhost"
        assert config.mqtt_port == 1883
        assert config.mqtt_base_topic == "nisystem"
        assert config.heartbeat_timeout_sec == 10.0
        assert config.check_interval_sec == 2.0
        assert config.failsafe_outputs == {}
        assert config.restart_service is False
        assert config.service_name == "daq_service"

    def test_custom_values(self):
        """Test custom configuration"""
        config = WatchdogConfig(
            mqtt_broker="192.168.1.100",
            mqtt_port=1884,
            heartbeat_timeout_sec=5.0,
            failsafe_outputs={"heater": False},
            restart_service=True
        )

        assert config.mqtt_broker == "192.168.1.100"
        assert config.mqtt_port == 1884
        assert config.heartbeat_timeout_sec == 5.0
        assert config.failsafe_outputs == {"heater": False}
        assert config.restart_service is True


class TestDAQWatchdog:
    """Test DAQWatchdog class"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog instance"""
        config = WatchdogConfig(
            heartbeat_timeout_sec=5.0,
            check_interval_sec=1.0
        )
        return DAQWatchdog(config)

    def test_initialization(self, watchdog):
        """Test watchdog initialization"""
        assert watchdog.running is False
        assert watchdog.last_heartbeat is None
        assert watchdog.daq_online is False
        assert watchdog.failsafe_triggered is False

    def test_no_failsafe_outputs_configured(self):
        """Test initialization without failsafe outputs"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)

        # Should not raise, just logs info
        assert watchdog.config.failsafe_outputs == {}


class TestHeartbeatHandling:
    """Test heartbeat message handling"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog with mock client"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_handle_heartbeat_sets_online(self, watchdog):
        """Test that heartbeat sets DAQ online"""
        payload = {
            'sequence': 1,
            'timestamp': datetime.now().isoformat(),
            'acquiring': True,
            'recording': False,
            'thread_health': {'reader_healthy': True, 'reader_died': False}
        }

        watchdog._handle_heartbeat(payload)

        assert watchdog.daq_online is True
        assert watchdog.last_heartbeat is not None

    def test_handle_heartbeat_recovery(self, watchdog):
        """Test recovery after failsafe"""
        watchdog.failsafe_triggered = True

        payload = {
            'sequence': 1,
            'thread_health': {'reader_healthy': True}
        }

        watchdog._handle_heartbeat(payload)

        # Should log recovery event
        watchdog.mqtt_client.publish.assert_called()

    def test_handle_heartbeat_reader_unhealthy(self, watchdog):
        """Test unhealthy reader detection"""
        payload = {
            'sequence': 1,
            'thread_health': {'reader_healthy': False, 'reader_died': True}
        }

        watchdog._handle_heartbeat(payload)

        # Should publish unhealthy event and trigger failsafe
        assert watchdog.failsafe_triggered is True

    def test_handle_heartbeat_acquisition_stopped(self, watchdog):
        """Test acquisition stop detection"""
        # First heartbeat - acquiring
        watchdog._handle_heartbeat({
            'sequence': 1,
            'acquiring': True
        })

        # Second heartbeat - not acquiring
        watchdog._handle_heartbeat({
            'sequence': 2,
            'acquiring': False
        })

        # Should publish acquisition stopped event (only once)
        assert watchdog._warned_acquisition_stop is True


class TestStatusHandling:
    """Test status message handling"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig()
        return DAQWatchdog(config)

    def test_handle_status_offline(self, watchdog):
        """Test handling offline status"""
        watchdog.daq_online = True

        watchdog._handle_status({'status': 'offline'})

        assert watchdog.daq_online is False


class TestHealthCheck:
    """Test health checking"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig(heartbeat_timeout_sec=5.0)
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_check_health_no_heartbeat_yet(self, watchdog):
        """Test health check when no heartbeat received yet"""
        # Should not trigger failsafe
        watchdog._check_health()

        assert watchdog.failsafe_triggered is False

    def test_check_health_timeout(self, watchdog):
        """Test health check triggers failsafe on timeout"""
        watchdog.last_heartbeat = time.time() - 10  # 10 seconds ago

        watchdog._check_health()

        assert watchdog.failsafe_triggered is True

    def test_check_health_within_timeout(self, watchdog):
        """Test health check passes within timeout"""
        watchdog.last_heartbeat = time.time()  # Just now

        watchdog._check_health()

        assert watchdog.failsafe_triggered is False

    def test_check_health_recovery(self, watchdog):
        """Test failsafe reset on recovery"""
        watchdog.failsafe_triggered = True
        watchdog.daq_online = True
        watchdog.last_heartbeat = time.time()

        watchdog._check_health()

        assert watchdog.failsafe_triggered is False


class TestFailsafe:
    """Test failsafe functionality"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog with failsafe outputs"""
        config = WatchdogConfig(
            failsafe_outputs={
                'heater1': False,
                'heater2': False,
                'pump': 0
            }
        )
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_trigger_failsafe(self, watchdog):
        """Test triggering failsafe"""
        watchdog._trigger_failsafe(15.0)

        assert watchdog.failsafe_triggered is True
        assert watchdog.failsafe_trigger_time is not None
        assert watchdog.daq_online is False

    def test_trigger_failsafe_with_reason(self, watchdog):
        """Test triggering failsafe with custom reason"""
        watchdog._trigger_failsafe(0, reason="Reader thread died")

        assert watchdog.failsafe_triggered is True

    def test_set_failsafe_outputs(self, watchdog):
        """Test setting failsafe outputs"""
        watchdog._set_failsafe_outputs()

        # Should publish to all failsafe channels
        calls = watchdog.mqtt_client.publish.call_args_list
        assert len(calls) >= 3  # heater1, heater2, pump

    def test_set_failsafe_outputs_none_configured(self):
        """Test setting failsafe with no outputs configured"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()

        # Should not raise
        watchdog._set_failsafe_outputs()


class TestServiceRestart:
    """Test service restart functionality"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog with restart enabled"""
        config = WatchdogConfig(
            restart_service=True,
            service_name="test_service"
        )
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    @patch('watchdog.subprocess.run')
    def test_attempt_restart_success(self, mock_run, watchdog):
        """Test successful service restart"""
        mock_run.return_value = MagicMock(returncode=0)

        watchdog._attempt_restart()

        assert mock_run.called
        # On Linux: single systemctl restart call
        # On Windows: sc stop + sc start (two calls)
        import platform
        if platform.system() == "Windows":
            assert mock_run.call_count == 2
            stop_args = mock_run.call_args_list[0][0][0]
            start_args = mock_run.call_args_list[1][0][0]
            assert 'sc' in stop_args
            assert 'test_service' in stop_args[2]
            assert 'sc' in start_args
            assert 'test_service' in start_args[2]
        else:
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert 'systemctl' in call_args
            assert 'restart' in call_args
            assert 'test_service' in call_args

    @patch('watchdog.subprocess.run')
    def test_attempt_restart_failure(self, mock_run, watchdog):
        """Test failed service restart"""
        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied")

        # Should not raise
        watchdog._attempt_restart()


class TestMQTTCallbacks:
    """Test MQTT callback handling"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_on_mqtt_connect_success(self, watchdog):
        """Test MQTT connection success callback"""
        mock_client = MagicMock()
        watchdog._on_mqtt_connect(
            client=mock_client,
            userdata=None,
            flags=None,
            reason_code=0,
            properties=None
        )

        # Should subscribe to topics using the passed client
        mock_client.subscribe.assert_called()
        mock_client.publish.assert_called()

    def test_on_mqtt_connect_failure(self, watchdog):
        """Test MQTT connection failure callback"""
        watchdog._on_mqtt_connect(
            client=MagicMock(),
            userdata=None,
            flags=None,
            reason_code=1,  # Connection refused
            properties=None
        )

        # Should not subscribe
        watchdog.mqtt_client.subscribe.assert_not_called()

    def test_on_mqtt_message_heartbeat(self, watchdog):
        """Test handling heartbeat message"""
        msg = MagicMock()
        msg.topic = "nisystem/nodes/node1/heartbeat"
        msg.payload = json.dumps({
            'sequence': 1,
            'acquiring': True,
            'thread_health': {}
        }).encode()

        watchdog._on_mqtt_message(MagicMock(), None, msg)

        assert watchdog.daq_online is True

    def test_on_mqtt_message_status(self, watchdog):
        """Test handling status message"""
        msg = MagicMock()
        msg.topic = "nisystem/nodes/node1/status/system"
        msg.payload = json.dumps({'status': 'offline'}).encode()

        watchdog.daq_online = True
        watchdog._on_mqtt_message(MagicMock(), None, msg)

        assert watchdog.daq_online is False


class TestPublishing:
    """Test MQTT publishing"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_publish_alarm(self, watchdog):
        """Test publishing alarm"""
        watchdog._publish_alarm("test_alarm", "Test message")

        call_args = watchdog.mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert "alarms/test_alarm" in topic
        assert payload['severity'] == 'critical'
        assert payload['message'] == "Test message"

    def test_publish_watchdog_event(self, watchdog):
        """Test publishing watchdog event"""
        watchdog._publish_watchdog_event("test_event", "Test message")

        call_args = watchdog.mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert "watchdog/event" in topic
        assert payload['event'] == 'test_event'

    def test_publish_status(self, watchdog):
        """Test publishing status"""
        watchdog.daq_online = True
        watchdog.failsafe_triggered = False

        watchdog._publish_status()

        call_args = watchdog.mqtt_client.publish.call_args
        payload = json.loads(call_args[0][1])

        assert payload['status'] == 'online'
        assert payload['daq_online'] is True
        assert payload['failsafe_triggered'] is False


class TestStartStop:
    """Test start/stop functionality"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        return watchdog

    @patch.object(DAQWatchdog, '_setup_mqtt')
    @patch.object(DAQWatchdog, '_run_loop')
    def test_start(self, mock_run, mock_setup, watchdog):
        """Test starting watchdog"""
        watchdog.start()

        assert watchdog.running is True
        mock_setup.assert_called_once()
        mock_run.assert_called_once()

    def test_stop(self, watchdog):
        """Test stopping watchdog"""
        watchdog.running = True
        watchdog.mqtt_client = MagicMock()

        watchdog.stop()

        assert watchdog.running is False
        watchdog.mqtt_client.loop_stop.assert_called_once()
        watchdog.mqtt_client.disconnect.assert_called_once()


class TestConfigLoading:
    """Test configuration loading from INI file"""

    def test_load_default_config(self):
        """Test loading with non-existent file returns defaults"""
        config = load_config_from_ini("/nonexistent/path.ini")

        assert config.mqtt_broker == "localhost"
        assert config.heartbeat_timeout_sec == 10.0

    def test_load_from_ini(self):
        """Test loading from actual INI file"""
        ini_content = """
[system]
mqtt_broker = 192.168.1.100
mqtt_port = 1884

[watchdog]
heartbeat_timeout_sec = 15.0
check_interval_sec = 3.0
restart_service = true
service_name = my_daq_service

[safety_action:Emergency_Stop]
actions = heater1:false, heater2:false, pump:0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(ini_content)
            f.flush()

            config = load_config_from_ini(f.name)

        assert config.mqtt_broker == "192.168.1.100"
        assert config.heartbeat_timeout_sec == 15.0
        assert config.check_interval_sec == 3.0
        assert config.restart_service is True
        assert config.service_name == "my_daq_service"

    def test_load_failsafe_outputs(self):
        """Test loading failsafe outputs from emergency safety action"""
        ini_content = """
[safety_action:Emergency_Shutdown]
actions = heater:false, valve:true, setpoint:0.5
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(ini_content)
            f.flush()

            config = load_config_from_ini(f.name)

        assert config.failsafe_outputs['heater'] is False
        assert config.failsafe_outputs['valve'] is True
        assert config.failsafe_outputs['setpoint'] == 0.5


class TestAcquisitionTracking:
    """Test acquisition state tracking"""

    @pytest.fixture
    def watchdog(self):
        """Create watchdog"""
        config = WatchdogConfig()
        watchdog = DAQWatchdog(config)
        watchdog.mqtt_client = MagicMock()
        return watchdog

    def test_acquisition_start_resets_warning(self, watchdog):
        """Test that acquisition start resets warning flag"""
        watchdog._warned_acquisition_stop = True

        watchdog._handle_heartbeat({'sequence': 1, 'acquiring': True})

        assert watchdog._warned_acquisition_stop is False

    def test_acquisition_stop_warns_once(self, watchdog):
        """Test that acquisition stop only warns once"""
        watchdog._expected_acquiring = True
        watchdog._warned_acquisition_stop = False

        # First stop
        watchdog._handle_heartbeat({'sequence': 1, 'acquiring': False})
        first_call_count = watchdog.mqtt_client.publish.call_count

        # Second stop (same heartbeat)
        watchdog._handle_heartbeat({'sequence': 2, 'acquiring': False})
        second_call_count = watchdog.mqtt_client.publish.call_count

        # Should not warn again
        assert watchdog._warned_acquisition_stop is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
