#!/usr/bin/env python3
"""
Topic Alignment Tests

These tests verify that the MQTT topics used by the frontend
match what the backend publishes/subscribes to.

This prevents the common issue of frontend/backend topic mismatches.
"""

import pytest
import time
import json

SYSTEM_PREFIX = "nisystem"


class TestTopicAlignment:
    """Verify frontend and backend use matching topic patterns"""

    def test_status_topic(self, mqtt_client):
        """Frontend expects status on nisystem/status/system"""
        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/status/system")
        msgs = mqtt_client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0
        )
        assert len(msgs) > 0, "Backend not publishing to nisystem/status/system"

    def test_channel_data_topic_pattern(self, mqtt_client_with_acquisition):
        """Frontend expects channel data on nisystem/channels/<name>"""
        mqtt_client_with_acquisition.subscribe(f"{SYSTEM_PREFIX}/channels/#")

        time.sleep(1.0)

        # Check for channel messages
        found_channels = []
        with mqtt_client_with_acquisition.message_lock:
            for topic in mqtt_client_with_acquisition.messages:
                if "/channels/" in topic:
                    found_channels.append(topic)

        assert len(found_channels) > 0, \
            "Backend not publishing to nisystem/channels/<channel_name> pattern"

    def test_config_channels_topic(self, mqtt_client):
        """Frontend expects config on nisystem/config/channels"""
        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/config/channels")
        msgs = mqtt_client.wait_for_message(
            f"{SYSTEM_PREFIX}/config/channels",
            timeout=3.0
        )
        assert len(msgs) > 0, "Backend not publishing to nisystem/config/channels"

    def test_system_command_topics(self, mqtt_client):
        """Backend listens on nisystem/system/acquire/start|stop"""
        # First stop any existing acquisition
        mqtt_client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(1.0)

        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/status/system")
        mqtt_client.clear_messages()

        # Send start command to correct topic
        mqtt_client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
        time.sleep(2.0)

        msgs = mqtt_client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0,
            count=3
        )

        assert len(msgs) > 0, "No status response after acquire/start"
        assert any(m["payload"].get("acquiring") for m in msgs), \
            "Backend didn't respond to nisystem/system/acquire/start"

        # Clean up
        mqtt_client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")

    def test_output_command_topic(self, mqtt_client_with_acquisition):
        """Backend listens on nisystem/commands/<channel_name>"""
        channel = "F1_Heater_Enable"

        mqtt_client_with_acquisition.subscribe(f"{SYSTEM_PREFIX}/channels/{channel}")
        mqtt_client_with_acquisition.clear_messages()

        # Send command to correct topic
        mqtt_client_with_acquisition.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            json.dumps({"value": True})
        )

        time.sleep(1.0)
        msgs = mqtt_client_with_acquisition.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/{channel}",
            timeout=3.0
        )

        # Backend should respond with channel value feedback
        assert len(msgs) > 0, \
            f"Backend didn't respond to command on nisystem/commands/{channel}"

    def test_alarm_topic_pattern(self, mqtt_client):
        """Backend publishes alarms on nisystem/alarms/<source>"""
        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/alarms/#")

        # Note: Alarms may or may not be present depending on simulation state
        # Just verify subscription works
        time.sleep(2.0)

        # Check the topic pattern if any alarms received
        with mqtt_client.message_lock:
            for topic in mqtt_client.messages:
                if "/alarms/" in topic:
                    # Verify topic structure
                    parts = topic.split("/")
                    assert len(parts) >= 3, f"Invalid alarm topic: {topic}"
                    assert parts[1] == "alarms", f"Wrong topic pattern: {topic}"


class TestChannelDataFormat:
    """Verify channel data has expected format"""

    def test_thermocouple_data_format(self, mqtt_client_with_acquisition):
        """Thermocouple data should have value, timestamp, units, quality"""
        mqtt_client_with_acquisition.subscribe(f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp")

        msgs = mqtt_client_with_acquisition.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp",
            timeout=3.0
        )

        assert len(msgs) > 0, "No thermocouple data received"

        data = msgs[0]["payload"]
        assert "value" in data, "Missing 'value' field"
        assert "timestamp" in data, "Missing 'timestamp' field"
        assert "units" in data, "Missing 'units' field"
        assert "quality" in data, "Missing 'quality' field"
        assert "status" in data, "Missing 'status' field"

    def test_digital_input_data_format(self, mqtt_client_with_acquisition):
        """Digital input data should have value field"""
        mqtt_client_with_acquisition.subscribe(f"{SYSTEM_PREFIX}/channels/E_Stop")

        msgs = mqtt_client_with_acquisition.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/E_Stop",
            timeout=3.0
        )

        assert len(msgs) > 0, "No digital input data received"

        data = msgs[0]["payload"]
        assert "value" in data, "Missing 'value' field"

    def test_config_channels_format(self, mqtt_client):
        """Channel config should have channels dict with expected fields"""
        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/config/channels")

        msgs = mqtt_client.wait_for_message(
            f"{SYSTEM_PREFIX}/config/channels",
            timeout=3.0
        )

        assert len(msgs) > 0, "No config received"

        config = msgs[0]["payload"]
        assert "channels" in config, "Missing 'channels' in config"

        # Check first channel has expected fields
        channels = config["channels"]
        assert len(channels) > 0, "No channels in config"

        first_channel = list(channels.values())[0]
        expected_fields = ["name", "type", "units", "description"]
        for field in expected_fields:
            assert field in first_channel, f"Missing '{field}' in channel config"


class TestSystemStatusFormat:
    """Verify system status has expected format"""

    def test_status_has_required_fields(self, mqtt_client):
        """System status should have all required fields"""
        mqtt_client.subscribe(f"{SYSTEM_PREFIX}/status/system")

        msgs = mqtt_client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0
        )

        assert len(msgs) > 0, "No status received"

        status = msgs[0]["payload"]
        required_fields = [
            "status",
            "simulation_mode",
            "acquiring",
            "recording",
            "channel_count",
            "scan_rate_hz",
            "publish_rate_hz"
        ]

        for field in required_fields:
            assert field in status, f"Missing '{field}' in system status"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
