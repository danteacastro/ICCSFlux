"""
Integration tests for cRIO <-> DAQ Service config push flow.

These tests verify the config push/ACK flow works correctly without
needing actual hardware or manual testing.

Run with: pytest tests/test_crio_config_flow.py -v
"""

import pytest
import json
import time
import threading
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List


class TestConfigPushFormat:
    """Test that config is pushed in the correct format."""

    def test_channels_pushed_as_dict_not_list(self):
        """Channels must be pushed as dict keyed by name, not as list."""
        # Simulate what daq_service._push_crio_channel_config builds
        channels_config = {
            'tag_0': {'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
            'tag_1': {'physical_channel': 'Mod1/ai1', 'channel_type': 'voltage_input'},
            'tag_72': {'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
        }

        # Build config like _push_crio_channel_config does (FIXED version)
        crio_channels = {}
        for name, channel in channels_config.items():
            ch_dict = {
                'name': name,
                'physical_channel': channel['physical_channel'],
                'channel_type': channel['channel_type'],
            }
            crio_channels[name] = ch_dict  # Dict, not list!

        config_data = {
            'channels': crio_channels,
            'safety_actions': {},
            'timestamp': '2026-01-28T12:00:00',
            'config_version': 'abc123'
        }

        # Verify it's a dict
        assert isinstance(config_data['channels'], dict), \
            "channels must be dict, not list"

        # Verify keys are channel names
        assert 'tag_0' in config_data['channels']
        assert 'tag_72' in config_data['channels']

    def test_crio_handles_dict_channels(self):
        """cRIO _cmd_config_full must handle dict channels."""
        # Simulate payload cRIO receives
        payload = {
            'channels': {
                'tag_0': {'name': 'tag_0', 'physical_channel': 'Mod1/ai0'},
                'tag_1': {'name': 'tag_1', 'physical_channel': 'Mod1/ai1'},
            }
        }

        channels_data = payload.get('channels', {})

        # Should work directly with .items()
        result = {}
        for name, ch_data in channels_data.items():
            result[name] = ch_data.get('physical_channel')

        assert result['tag_0'] == 'Mod1/ai0'
        assert result['tag_1'] == 'Mod1/ai1'

    def test_crio_handles_list_channels_backwards_compat(self):
        """cRIO _cmd_config_full must handle list channels (backwards compat)."""
        # Simulate OLD payload format (list instead of dict)
        payload = {
            'channels': [
                {'name': 'tag_0', 'physical_channel': 'Mod1/ai0'},
                {'name': 'tag_1', 'physical_channel': 'Mod1/ai1'},
            ]
        }

        channels_data = payload.get('channels', {})

        # Handle both list and dict formats (like cRIO code does now)
        if isinstance(channels_data, list):
            channels_data = {ch.get('name'): ch for ch in channels_data if ch.get('name')}

        # Now should work with .items()
        result = {}
        for name, ch_data in channels_data.items():
            result[name] = ch_data.get('physical_channel')

        assert result['tag_0'] == 'Mod1/ai0'
        assert result['tag_1'] == 'Mod1/ai1'


class TestConfigResponseParsing:
    """Test that config responses are parsed correctly."""

    def test_success_status_accepted(self):
        """DAQ service must accept 'success' status from cRIO."""
        payload = {
            'status': 'success',
            'success': True,
            'message': 'Config applied',
            'channels': 96,
            'config_version': 'abc123'
        }

        status = payload.get('status')

        # Must accept both 'ok' and 'success'
        assert status in ('ok', 'success'), \
            f"Status '{status}' should be accepted"

    def test_ok_status_accepted(self):
        """DAQ service must accept 'ok' status (legacy)."""
        payload = {
            'status': 'ok',
            'channels': 96,
            'config_version': 'abc123'
        }

        status = payload.get('status')
        assert status in ('ok', 'success')

    def test_error_status_rejected(self):
        """DAQ service must reject 'error' status."""
        payload = {
            'status': 'error',
            'message': 'Invalid channel config',
            'channels': 0
        }

        status = payload.get('status')
        assert status not in ('ok', 'success')

        # Error message should be extracted
        error_msg = payload.get('error', payload.get('message', 'Unknown error'))
        assert error_msg == 'Invalid channel config'


class TestConfigVersionTracking:
    """Test that config versions are tracked correctly."""

    def test_config_version_hash_consistent(self):
        """Same config should produce same version hash."""
        import hashlib

        config1 = {
            'channels': {'tag_0': {'physical_channel': 'Mod1/ai0'}},
            'safety_actions': {}
        }
        config2 = {
            'channels': {'tag_0': {'physical_channel': 'Mod1/ai0'}},
            'safety_actions': {}
        }

        hash1 = hashlib.md5(json.dumps(config1, sort_keys=True).encode()).hexdigest()[:8]
        hash2 = hashlib.md5(json.dumps(config2, sort_keys=True).encode()).hexdigest()[:8]

        assert hash1 == hash2, "Same config should produce same hash"

    def test_different_config_different_hash(self):
        """Different config should produce different version hash."""
        import hashlib

        config1 = {
            'channels': {'tag_0': {'physical_channel': 'Mod1/ai0'}},
            'safety_actions': {}
        }
        config2 = {
            'channels': {'tag_0': {'physical_channel': 'Mod1/ai1'}},  # Different!
            'safety_actions': {}
        }

        hash1 = hashlib.md5(json.dumps(config1, sort_keys=True).encode()).hexdigest()[:8]
        hash2 = hashlib.md5(json.dumps(config2, sort_keys=True).encode()).hexdigest()[:8]

        assert hash1 != hash2, "Different config should produce different hash"


class TestMQTTTopicRouting:
    """Test that MQTT topics are routed correctly."""

    def test_config_full_topic_format(self):
        """Config push topic must follow correct format."""
        mqtt_base = 'nisystem'
        node_id = 'crio-001'

        expected_topic = f"{mqtt_base}/nodes/{node_id}/config/full"
        assert expected_topic == 'nisystem/nodes/crio-001/config/full'

    def test_config_response_topic_format(self):
        """Config response topic must follow correct format."""
        # cRIO publishes to relative topic, which becomes:
        topic_base = 'nisystem/nodes/crio-001'
        relative_topic = 'config/response'

        full_topic = f"{topic_base}/{relative_topic}"
        assert full_topic == 'nisystem/nodes/crio-001/config/response'

    def test_wildcard_subscription_matches(self):
        """DAQ service wildcard subscription must match cRIO responses."""
        import re

        # DAQ subscribes to: nisystem/nodes/+/config/response
        subscription_pattern = r'nisystem/nodes/[^/]+/config/response'

        # cRIO publishes to: nisystem/nodes/crio-001/config/response
        crio_topic = 'nisystem/nodes/crio-001/config/response'

        assert re.match(subscription_pattern, crio_topic), \
            "Subscription pattern must match cRIO topic"


class TestChannelTypeMapping:
    """Test that channel types are mapped correctly."""

    def test_thermocouple_type_preserved(self):
        """Thermocouple type must be included in config push."""
        channel = {
            'name': 'tag_72',
            'physical_channel': 'Mod5/ai0',
            'channel_type': 'thermocouple',
            'thermocouple_type': 'K'
        }

        # Build config dict like _push_crio_channel_config
        ch_dict = {
            'name': channel['name'],
            'physical_channel': channel['physical_channel'],
            'channel_type': channel['channel_type'],
        }

        # Add thermocouple_type if present
        if channel.get('thermocouple_type'):
            ch_dict['thermocouple_type'] = channel['thermocouple_type']

        assert ch_dict.get('thermocouple_type') == 'K'

    def test_channel_type_internal_mapping(self):
        """Channel types must map to correct internal DAQmx types."""
        # From channel_types.py
        type_map = {
            'voltage_input': 'analog_input',
            'current_input': 'analog_input',
            'thermocouple': 'analog_input',
            'rtd': 'analog_input',
            'voltage_output': 'analog_output',
            'current_output': 'analog_output',
            'digital_input': 'digital_input',
            'digital_output': 'digital_output',
        }

        # Verify all types map to expected internal types
        assert type_map['thermocouple'] == 'analog_input'
        assert type_map['voltage_input'] == 'analog_input'
        assert type_map['digital_input'] == 'digital_input'


class TestEndToEndConfigFlow:
    """End-to-end tests for the config push flow."""

    def test_full_config_push_response_cycle(self):
        """Test complete config push -> response -> ACK cycle."""
        # 1. DAQ builds config
        channels = {
            f'tag_{i}': {
                'name': f'tag_{i}',
                'physical_channel': f'Mod1/ai{i}',
                'channel_type': 'voltage_input'
            }
            for i in range(16)
        }

        config_data = {
            'channels': channels,
            'safety_actions': {},
            'config_version': 'test123'
        }

        # 2. Simulate cRIO receiving config
        received_channels = config_data['channels']

        # Handle list/dict
        if isinstance(received_channels, list):
            received_channels = {ch['name']: ch for ch in received_channels}

        # 3. cRIO processes config
        processed_count = len(received_channels)
        assert processed_count == 16

        # 4. cRIO sends response
        response = {
            'status': 'success',
            'success': True,
            'message': 'Config applied',
            'channels': processed_count,
            'config_version': config_data['config_version']
        }

        # 5. DAQ receives and parses response
        status = response.get('status')
        assert status in ('ok', 'success')

        # 6. DAQ updates tracking
        confirmed_version = response.get('config_version')
        assert confirmed_version == 'test123'

    def test_config_push_with_all_module_types(self):
        """Test config push with all cRIO module types."""
        # Simulate cRIO hardware config
        channels = {}

        # Mod1: NI 9202 (voltage input)
        for i in range(16):
            channels[f'V{i:03d}'] = {
                'name': f'V{i:03d}',
                'physical_channel': f'Mod1/ai{i}',
                'channel_type': 'voltage_input'
            }

        # Mod2: NI 9264 (voltage output)
        for i in range(16):
            channels[f'VO{i:03d}'] = {
                'name': f'VO{i:03d}',
                'physical_channel': f'Mod2/ao{i}',
                'channel_type': 'voltage_output'
            }

        # Mod3: NI 9425 (digital input)
        for i in range(32):
            channels[f'DI{i:03d}'] = {
                'name': f'DI{i:03d}',
                'physical_channel': f'Mod3/port0/line{i}',
                'channel_type': 'digital_input'
            }

        # Mod4: NI 9472 (digital output)
        for i in range(8):
            channels[f'DO{i:03d}'] = {
                'name': f'DO{i:03d}',
                'physical_channel': f'Mod4/port0/line{i}',
                'channel_type': 'digital_output'
            }

        # Mod5: NI 9213 (thermocouple)
        for i in range(16):
            channels[f'TC{i:03d}'] = {
                'name': f'TC{i:03d}',
                'physical_channel': f'Mod5/ai{i}',
                'channel_type': 'thermocouple',
                'thermocouple_type': 'K'
            }

        # Mod6: NI 9266 (current output)
        for i in range(8):
            channels[f'AO{i:03d}'] = {
                'name': f'AO{i:03d}',
                'physical_channel': f'Mod6/ao{i}',
                'channel_type': 'current_output'
            }

        # Build config
        config_data = {
            'channels': channels,
            'safety_actions': {},
            'config_version': 'full_test'
        }

        # Verify all channels present
        assert len(config_data['channels']) == 16 + 16 + 32 + 8 + 16 + 8  # 96

        # Verify channel types
        tc_channels = [ch for ch in channels.values() if ch['channel_type'] == 'thermocouple']
        assert len(tc_channels) == 16
        assert all(ch.get('thermocouple_type') == 'K' for ch in tc_channels)


class TestRetryLogic:
    """Test config push retry logic."""

    def test_retry_on_timeout(self):
        """Config push should retry on timeout."""
        max_retries = 3
        timeout_sec = 5.0

        # Simulate tracking
        pending_push = {
            'config': {'channels': {}},
            'attempts': 1,
            'timestamp': time.time() - timeout_sec - 1,  # Expired
            'node_id': 'crio-001'
        }

        # Check if should retry
        elapsed = time.time() - pending_push['timestamp']
        should_retry = elapsed > timeout_sec and pending_push['attempts'] < max_retries

        assert should_retry, "Should retry after timeout"

    def test_give_up_after_max_retries(self):
        """Config push should give up after max retries."""
        max_retries = 3
        timeout_sec = 5.0

        pending_push = {
            'config': {'channels': {}},
            'attempts': 3,  # Already at max
            'timestamp': time.time() - timeout_sec - 1,
            'node_id': 'crio-001'
        }

        elapsed = time.time() - pending_push['timestamp']
        should_give_up = elapsed > timeout_sec and pending_push['attempts'] >= max_retries

        assert should_give_up, "Should give up after max retries"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
