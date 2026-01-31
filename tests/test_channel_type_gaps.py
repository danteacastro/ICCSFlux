"""
Channel Type Gap Tests — Resistance, Pulse Output, Relay

Validates:
1. Resistance input config parsing and field presence in cRIO config
2. Pulse output config parsing, field presence, and counter grouping
3. Relay module metadata (SPST/SPDT/SSR) and momentary pulse config
4. Config push completeness for all new fields
5. Channel type routing (counter_input, counter_output internal types)
"""

import sys
import os
import pytest
from dataclasses import dataclass
from typing import Optional, Dict

# --- Import cRIO modules ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))

from crio_node_v2.config import ChannelConfig as CRIOChannelConfig
from crio_node_v2.channel_types import (
    ChannelType, MODULE_TYPE_MAP, RELAY_MODULES,
    get_relay_type, get_module_channel_type
)

# --- Import DAQ service modules ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))
from config_parser import ChannelConfig as DAQChannelConfig, ChannelType as DAQChannelType


# ============================================================
# Gap 1: Resistance Input
# ============================================================

class TestResistanceConfig:
    """Validate resistance_input config fields exist and parse correctly."""

    def test_crio_config_has_resistance_fields(self):
        """cRIO ChannelConfig has resistance_range and resistance_wiring."""
        ch = CRIOChannelConfig(
            name="R_001",
            physical_channel="Mod1/ai0",
            channel_type="resistance_input"
        )
        assert ch.resistance_range == 1000.0
        assert ch.resistance_wiring == '4-wire'

    def test_crio_config_from_dict_resistance(self):
        """from_dict parses resistance fields."""
        data = {
            'physical_channel': 'Mod1/ai0',
            'channel_type': 'resistance_input',
            'resistance_range': 5000.0,
            'resistance_wiring': '2-wire',
        }
        ch = CRIOChannelConfig.from_dict("R_001", data)
        assert ch.resistance_range == 5000.0
        assert ch.resistance_wiring == '2-wire'

    def test_crio_config_to_dict_resistance(self):
        """to_dict includes resistance fields."""
        from crio_node_v2.config import NodeConfig
        config = NodeConfig()
        config.channels["R_001"] = CRIOChannelConfig(
            name="R_001",
            physical_channel="Mod1/ai0",
            channel_type="resistance_input",
            resistance_range=2200.0,
            resistance_wiring='2-wire',
        )
        d = config.to_dict()
        ch_dict = d['channels']['R_001']
        assert ch_dict['resistance_range'] == 2200.0
        assert ch_dict['resistance_wiring'] == '2-wire'

    def test_daq_config_has_resistance_fields(self):
        """PC DAQ ChannelConfig has resistance_range and resistance_wiring."""
        ch = DAQChannelConfig.__new__(DAQChannelConfig)
        ch.name = "R_001"
        ch.resistance_range = 1000.0
        ch.resistance_wiring = "4-wire"
        assert ch.resistance_range == 1000.0
        assert ch.resistance_wiring == "4-wire"

    def test_resistance_internal_type_is_analog_input(self):
        """resistance_input maps to analog_input internal type."""
        assert ChannelType.get_internal_type('resistance_input') == 'analog_input'

    def test_resistance_is_input(self):
        """resistance_input is classified as input."""
        assert ChannelType.is_input('resistance_input')
        assert not ChannelType.is_output('resistance_input')

    def test_resistance_is_analog(self):
        """resistance_input is classified as analog."""
        assert ChannelType.is_analog('resistance_input')


# ============================================================
# Gap 2: Pulse Output (Counter Output)
# ============================================================

class TestPulseOutputConfig:
    """Validate pulse_output config fields exist and parse correctly."""

    def test_crio_config_has_pulse_fields(self):
        """cRIO ChannelConfig has pulse_frequency, pulse_duty_cycle, pulse_idle_state."""
        ch = CRIOChannelConfig(
            name="PLS_001",
            physical_channel="Mod1/ctr0",
            channel_type="pulse_output"
        )
        assert ch.pulse_frequency == 1000.0
        assert ch.pulse_duty_cycle == 50.0
        assert ch.pulse_idle_state == 'LOW'

    def test_crio_config_from_dict_pulse(self):
        """from_dict parses pulse output fields."""
        data = {
            'physical_channel': 'Mod1/ctr0',
            'channel_type': 'pulse_output',
            'pulse_frequency': 5000.0,
            'pulse_duty_cycle': 25.0,
            'pulse_idle_state': 'HIGH',
        }
        ch = CRIOChannelConfig.from_dict("PLS_001", data)
        assert ch.pulse_frequency == 5000.0
        assert ch.pulse_duty_cycle == 25.0
        assert ch.pulse_idle_state == 'HIGH'

    def test_crio_config_to_dict_pulse(self):
        """to_dict includes pulse output fields."""
        from crio_node_v2.config import NodeConfig
        config = NodeConfig()
        config.channels["PLS_001"] = CRIOChannelConfig(
            name="PLS_001",
            physical_channel="Mod1/ctr0",
            channel_type="pulse_output",
            pulse_frequency=2000.0,
            pulse_duty_cycle=75.0,
            pulse_idle_state='HIGH',
        )
        d = config.to_dict()
        ch_dict = d['channels']['PLS_001']
        assert ch_dict['pulse_frequency'] == 2000.0
        assert ch_dict['pulse_duty_cycle'] == 75.0
        assert ch_dict['pulse_idle_state'] == 'HIGH'

    def test_daq_config_has_pulse_fields(self):
        """PC DAQ ChannelConfig has pulse output fields."""
        ch = DAQChannelConfig.__new__(DAQChannelConfig)
        ch.name = "PLS_001"
        ch.pulse_frequency = 1000.0
        ch.pulse_duty_cycle = 50.0
        ch.pulse_idle_state = "LOW"
        assert ch.pulse_frequency == 1000.0
        assert ch.pulse_duty_cycle == 50.0

    def test_counter_input_has_fields(self):
        """cRIO ChannelConfig has counter input fields."""
        ch = CRIOChannelConfig(
            name="CTR_001",
            physical_channel="Mod1/ctr0",
            channel_type="counter_input",
            counter_mode='frequency',
            counter_edge='rising',
            counter_min_freq=0.5,
            counter_max_freq=5000.0,
        )
        assert ch.counter_mode == 'frequency'
        assert ch.counter_edge == 'rising'
        assert ch.counter_min_freq == 0.5
        assert ch.counter_max_freq == 5000.0


class TestCounterTypeRouting:
    """Validate counter_input and counter_output internal type mapping."""

    def test_counter_input_maps_to_counter_input(self):
        """counter_input -> counter_input internal type."""
        assert ChannelType.get_internal_type('counter_input') == 'counter_input'

    def test_counter_output_maps_to_counter_output(self):
        """counter_output -> counter_output internal type."""
        assert ChannelType.get_internal_type('counter_output') == 'counter_output'

    def test_frequency_input_maps_to_counter_input(self):
        """frequency_input -> counter_input internal type."""
        assert ChannelType.get_internal_type('frequency_input') == 'counter_input'

    def test_pulse_output_maps_to_counter_output(self):
        """pulse_output -> counter_output internal type."""
        assert ChannelType.get_internal_type('pulse_output') == 'counter_output'

    def test_pulse_output_is_output(self):
        """pulse_output is classified as output."""
        assert ChannelType.is_output('pulse_output')
        assert not ChannelType.is_input('pulse_output')

    def test_counter_input_is_input(self):
        """counter_input is classified as input."""
        assert ChannelType.is_input('counter_input')
        assert not ChannelType.is_output('counter_input')

    def test_ni_9361_maps_to_counter_input(self):
        """NI 9361 module maps to COUNTER_INPUT."""
        assert MODULE_TYPE_MAP['9361'] == ChannelType.COUNTER_INPUT
        assert get_module_channel_type('NI 9361') == ChannelType.COUNTER_INPUT


# ============================================================
# Gap 3: Relay Modules
# ============================================================

class TestRelayModules:
    """Validate relay module metadata and momentary pulse config."""

    def test_relay_modules_dict_has_9481(self):
        """9481 is SPST relay."""
        assert RELAY_MODULES['9481'] == 'spst'

    def test_relay_modules_dict_has_9482(self):
        """9482 is SPDT relay."""
        assert RELAY_MODULES['9482'] == 'spdt'

    def test_relay_modules_dict_has_9485(self):
        """9485 is SSR."""
        assert RELAY_MODULES['9485'] == 'ssr'

    def test_get_relay_type_spst(self):
        """get_relay_type returns 'spst' for 9481."""
        assert get_relay_type('9481') == 'spst'
        assert get_relay_type('NI 9481') == 'spst'
        assert get_relay_type('NI-9481') == 'spst'

    def test_get_relay_type_not_relay(self):
        """get_relay_type returns 'none' for non-relay modules."""
        assert get_relay_type('9205') == 'none'
        assert get_relay_type('NI 9213') == 'none'

    def test_relay_modules_map_to_digital_output(self):
        """Relay modules still map to DIGITAL_OUTPUT in MODULE_TYPE_MAP."""
        assert MODULE_TYPE_MAP['9481'] == ChannelType.DIGITAL_OUTPUT
        assert MODULE_TYPE_MAP['9482'] == ChannelType.DIGITAL_OUTPUT
        assert MODULE_TYPE_MAP['9485'] == ChannelType.DIGITAL_OUTPUT

    def test_crio_config_has_relay_fields(self):
        """cRIO ChannelConfig has relay_type and momentary_pulse_ms."""
        ch = CRIOChannelConfig(
            name="RLY_001",
            physical_channel="Mod1/port0/line0",
            channel_type="digital_output",
            relay_type='spst',
            momentary_pulse_ms=500,
        )
        assert ch.relay_type == 'spst'
        assert ch.momentary_pulse_ms == 500

    def test_crio_config_from_dict_relay(self):
        """from_dict parses relay fields."""
        data = {
            'physical_channel': 'Mod1/port0/line0',
            'channel_type': 'digital_output',
            'relay_type': 'spdt',
            'momentary_pulse_ms': 250,
        }
        ch = CRIOChannelConfig.from_dict("RLY_001", data)
        assert ch.relay_type == 'spdt'
        assert ch.momentary_pulse_ms == 250

    def test_crio_config_to_dict_relay(self):
        """to_dict includes relay fields."""
        from crio_node_v2.config import NodeConfig
        config = NodeConfig()
        config.channels["RLY_001"] = CRIOChannelConfig(
            name="RLY_001",
            physical_channel="Mod1/port0/line0",
            channel_type="digital_output",
            relay_type='ssr',
            momentary_pulse_ms=1000,
        )
        d = config.to_dict()
        ch_dict = d['channels']['RLY_001']
        assert ch_dict['relay_type'] == 'ssr'
        assert ch_dict['momentary_pulse_ms'] == 1000

    def test_relay_defaults_to_none(self):
        """Default relay_type is 'none', momentary_pulse_ms is 0."""
        ch = CRIOChannelConfig(
            name="DO_001",
            physical_channel="Mod1/port0/line0",
            channel_type="digital_output",
        )
        assert ch.relay_type == 'none'
        assert ch.momentary_pulse_ms == 0

    def test_daq_config_has_relay_fields(self):
        """PC DAQ ChannelConfig has relay fields."""
        ch = DAQChannelConfig.__new__(DAQChannelConfig)
        ch.name = "RLY_001"
        ch.relay_type = "spst"
        ch.momentary_pulse_ms = 500
        assert ch.relay_type == "spst"
        assert ch.momentary_pulse_ms == 500


# ============================================================
# Config Push Completeness
# ============================================================

class TestConfigPushCompleteness:
    """Validate that all new fields survive a config roundtrip."""

    def test_resistance_roundtrip(self):
        """Resistance fields survive to_dict -> from_dict."""
        original = CRIOChannelConfig(
            name="R_001",
            physical_channel="Mod1/ai0",
            channel_type="resistance_input",
            resistance_range=4700.0,
            resistance_wiring='2-wire',
        )
        data = {
            'physical_channel': original.physical_channel,
            'channel_type': original.channel_type,
            'resistance_range': original.resistance_range,
            'resistance_wiring': original.resistance_wiring,
        }
        restored = CRIOChannelConfig.from_dict("R_001", data)
        assert restored.resistance_range == 4700.0
        assert restored.resistance_wiring == '2-wire'

    def test_pulse_roundtrip(self):
        """Pulse output fields survive to_dict -> from_dict."""
        original = CRIOChannelConfig(
            name="PLS_001",
            physical_channel="Mod1/ctr0",
            channel_type="pulse_output",
            pulse_frequency=8000.0,
            pulse_duty_cycle=33.3,
            pulse_idle_state='HIGH',
        )
        data = {
            'physical_channel': original.physical_channel,
            'channel_type': original.channel_type,
            'pulse_frequency': original.pulse_frequency,
            'pulse_duty_cycle': original.pulse_duty_cycle,
            'pulse_idle_state': original.pulse_idle_state,
        }
        restored = CRIOChannelConfig.from_dict("PLS_001", data)
        assert restored.pulse_frequency == 8000.0
        assert abs(restored.pulse_duty_cycle - 33.3) < 0.01
        assert restored.pulse_idle_state == 'HIGH'

    def test_counter_input_roundtrip(self):
        """Counter input fields survive to_dict -> from_dict."""
        original = CRIOChannelConfig(
            name="CTR_001",
            physical_channel="Mod1/ctr0",
            channel_type="counter_input",
            counter_mode='count',
            counter_edge='falling',
            counter_min_freq=1.0,
            counter_max_freq=10000.0,
        )
        data = {
            'physical_channel': original.physical_channel,
            'channel_type': original.channel_type,
            'counter_mode': original.counter_mode,
            'counter_edge': original.counter_edge,
            'counter_min_freq': original.counter_min_freq,
            'counter_max_freq': original.counter_max_freq,
        }
        restored = CRIOChannelConfig.from_dict("CTR_001", data)
        assert restored.counter_mode == 'count'
        assert restored.counter_edge == 'falling'
        assert restored.counter_min_freq == 1.0
        assert restored.counter_max_freq == 10000.0

    def test_relay_roundtrip(self):
        """Relay fields survive to_dict -> from_dict."""
        original = CRIOChannelConfig(
            name="RLY_001",
            physical_channel="Mod1/port0/line0",
            channel_type="digital_output",
            relay_type='spdt',
            momentary_pulse_ms=750,
        )
        data = {
            'physical_channel': original.physical_channel,
            'channel_type': original.channel_type,
            'relay_type': original.relay_type,
            'momentary_pulse_ms': original.momentary_pulse_ms,
        }
        restored = CRIOChannelConfig.from_dict("RLY_001", data)
        assert restored.relay_type == 'spdt'
        assert restored.momentary_pulse_ms == 750

    def test_full_nodeconfig_roundtrip(self):
        """All new fields survive NodeConfig to_dict -> from_dict roundtrip."""
        from crio_node_v2.config import NodeConfig

        config = NodeConfig()
        config.channels["R_001"] = CRIOChannelConfig(
            name="R_001", physical_channel="Mod1/ai0",
            channel_type="resistance_input",
            resistance_range=3300.0, resistance_wiring='2-wire',
        )
        config.channels["PLS_001"] = CRIOChannelConfig(
            name="PLS_001", physical_channel="Mod2/ctr0",
            channel_type="pulse_output",
            pulse_frequency=10000.0, pulse_duty_cycle=10.0, pulse_idle_state='HIGH',
        )
        config.channels["RLY_001"] = CRIOChannelConfig(
            name="RLY_001", physical_channel="Mod3/port0/line0",
            channel_type="digital_output",
            relay_type='spst', momentary_pulse_ms=200,
        )

        d = config.to_dict()

        # Verify resistance
        r = d['channels']['R_001']
        assert r['resistance_range'] == 3300.0
        assert r['resistance_wiring'] == '2-wire'

        # Verify pulse
        p = d['channels']['PLS_001']
        assert p['pulse_frequency'] == 10000.0
        assert p['pulse_duty_cycle'] == 10.0
        assert p['pulse_idle_state'] == 'HIGH'

        # Verify relay
        rl = d['channels']['RLY_001']
        assert rl['relay_type'] == 'spst'
        assert rl['momentary_pulse_ms'] == 200
