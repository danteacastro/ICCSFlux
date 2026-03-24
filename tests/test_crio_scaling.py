"""
Scaling Parity Tests — cRIO vs DAQ Service

Validates that the cRIO node applies the same scaling as the DAQ service
for all scaling types: linear, map (voltage), and 4-20mA (current).

Per ISA-95 / IEC 61131-3, scaling belongs at Level 1 (PLC/cRIO).
Both the DAQ service and cRIO must produce identical engineering values.

Also validates:
- Config push includes all scaling params
- Config receive parses all scaling params
- NAMUR NE43 diagnostic ranges for 4-20mA
"""

import json
import math
import sys
import os
import pytest
from dataclasses import dataclass
from typing import Optional

# --- Import DAQ service scaling ---

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))
from scaling import (
    apply_scaling as daq_apply_scaling,
    scale_four_twenty,
    scale_map,
    scale_linear,
    reverse_scaling as daq_reverse_scaling,
)
from config_parser import ChannelConfig as DAQChannelConfig, ChannelType

# --- Import cRIO scaling ---

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))
from crio_node_v2.hardware import apply_scaling as crio_apply_scaling
from crio_node_v2.config import ChannelConfig as CRIOChannelConfig

# ============================================================
# Helper: create matching DAQ + cRIO configs for parity tests
# ============================================================

def make_daq_voltage_map(name="PT_302", raw_min=0.0, raw_max=10.0,
                         scaled_min=0.0, scaled_max=300.0):
    """Create a DAQ ChannelConfig for voltage input with map scaling."""
    cfg = DAQChannelConfig.__new__(DAQChannelConfig)
    cfg.name = name
    cfg.channel_type = ChannelType.VOLTAGE_INPUT
    cfg.scale_type = 'map'
    cfg.scale_slope = 1.0
    cfg.scale_offset = 0.0
    cfg.four_twenty_scaling = False
    cfg.eng_units_min = None
    cfg.eng_units_max = None
    cfg.pre_scaled_min = raw_min
    cfg.pre_scaled_max = raw_max
    cfg.scaled_min = scaled_min
    cfg.scaled_max = scaled_max
    cfg.voltage_range = raw_max
    cfg.current_range_ma = 20.0
    cfg.units = 'psig'
    cfg.pulses_per_unit = 1.0
    cfg.counter_mode = 'frequency'
    return cfg

def make_crio_voltage_map(name="PT_302", raw_min=0.0, raw_max=10.0,
                          scaled_min=0.0, scaled_max=300.0):
    """Create a cRIO ChannelConfig for voltage input with map scaling."""
    return CRIOChannelConfig(
        name=name,
        physical_channel='Mod1/ai0',
        channel_type='voltage_input',
        scale_type='map',
        scale_slope=1.0,
        scale_offset=0.0,
        four_twenty_scaling=False,
        eng_units_min=None,
        eng_units_max=None,
        pre_scaled_min=raw_min,
        pre_scaled_max=raw_max,
        scaled_min=scaled_min,
        scaled_max=scaled_max,
    )

def make_daq_current_420(name="FT_401", eng_min=0.0, eng_max=10000.0):
    """Create a DAQ ChannelConfig for current input with 4-20mA scaling."""
    cfg = DAQChannelConfig.__new__(DAQChannelConfig)
    cfg.name = name
    cfg.channel_type = ChannelType.CURRENT_INPUT
    cfg.scale_type = 'none'
    cfg.scale_slope = 1.0
    cfg.scale_offset = 0.0
    cfg.four_twenty_scaling = True
    cfg.eng_units_min = eng_min
    cfg.eng_units_max = eng_max
    cfg.pre_scaled_min = None
    cfg.pre_scaled_max = None
    cfg.scaled_min = None
    cfg.scaled_max = None
    cfg.voltage_range = 10.0
    cfg.current_range_ma = 20.0
    cfg.units = 'SCFH'
    cfg.pulses_per_unit = 1.0
    cfg.counter_mode = 'frequency'
    return cfg

def make_crio_current_420(name="FT_401", eng_min=0.0, eng_max=10000.0):
    """Create a cRIO ChannelConfig for current input with 4-20mA scaling."""
    return CRIOChannelConfig(
        name=name,
        physical_channel='Mod2/ai0',
        channel_type='current_input',
        four_twenty_scaling=True,
        eng_units_min=eng_min,
        eng_units_max=eng_max,
        scale_type='none',
        scale_slope=1.0,
        scale_offset=0.0,
    )

def make_daq_linear(name="tag_0", slope=2.5, offset=-1.0):
    """Create a DAQ ChannelConfig with linear scaling."""
    cfg = DAQChannelConfig.__new__(DAQChannelConfig)
    cfg.name = name
    cfg.channel_type = ChannelType.VOLTAGE_INPUT
    cfg.scale_type = 'linear'
    cfg.scale_slope = slope
    cfg.scale_offset = offset
    cfg.four_twenty_scaling = False
    cfg.eng_units_min = None
    cfg.eng_units_max = None
    cfg.pre_scaled_min = None
    cfg.pre_scaled_max = None
    cfg.scaled_min = None
    cfg.scaled_max = None
    cfg.voltage_range = 10.0
    cfg.current_range_ma = 20.0
    cfg.units = 'A'
    cfg.pulses_per_unit = 1.0
    cfg.counter_mode = 'frequency'
    return cfg

def make_crio_linear(name="tag_0", slope=2.5, offset=-1.0):
    """Create a cRIO ChannelConfig with linear scaling."""
    return CRIOChannelConfig(
        name=name,
        physical_channel='Mod1/ai0',
        channel_type='voltage_input',
        scale_type='linear',
        scale_slope=slope,
        scale_offset=offset,
    )

# ============================================================
# Test 1: Linear Scaling Parity
# ============================================================

class TestLinearScalingParity:
    """Linear scaling (y = mx + b) must match between cRIO and DAQ."""

    @pytest.mark.parametrize("raw,slope,offset", [
        (0.0, 1.0, 0.0),     # Identity
        (5.0, 2.0, 0.0),     # Slope only
        (5.0, 1.0, -10.0),   # Offset only
        (3.3, 2.5, -1.0),    # Both
        (-5.0, 2.5, -1.0),   # Negative raw
        (10.0, 0.1, 0.0),    # Small slope
    ])
    def test_linear_parity(self, raw, slope, offset):
        daq_cfg = make_daq_linear(slope=slope, offset=offset)
        crio_cfg = make_crio_linear(slope=slope, offset=offset)

        daq_result = daq_apply_scaling(daq_cfg, raw)
        crio_result = crio_apply_scaling(crio_cfg, raw)

        assert daq_result == pytest.approx(crio_result, abs=1e-10), \
            f"Linear mismatch: raw={raw}, slope={slope}, offset={offset}: DAQ={daq_result}, cRIO={crio_result}"

# ============================================================
# Test 2: Map Scaling Parity (Voltage Input)
# ============================================================

class TestMapScalingParity:
    """Map scaling (0-10V → engineering range) must match between cRIO and DAQ."""

    @pytest.mark.parametrize("raw,raw_min,raw_max,scaled_min,scaled_max,expected", [
        (0.0, 0.0, 10.0, 0.0, 300.0, 0.0),       # Min
        (5.0, 0.0, 10.0, 0.0, 300.0, 150.0),      # Midpoint
        (10.0, 0.0, 10.0, 0.0, 300.0, 300.0),      # Max
        (5.0, 0.0, 10.0, -5.0, 5.0, 0.0),          # Bipolar range
        (0.0, 0.0, 10.0, -5.0, 5.0, -5.0),         # Bipolar min
        (10.0, 0.0, 10.0, -5.0, 5.0, 5.0),         # Bipolar max
        (2.5, 0.0, 10.0, 0.0, 100.0, 25.0),        # Quarter range
    ])
    def test_map_parity(self, raw, raw_min, raw_max, scaled_min, scaled_max, expected):
        daq_cfg = make_daq_voltage_map(raw_min=raw_min, raw_max=raw_max,
                                        scaled_min=scaled_min, scaled_max=scaled_max)
        crio_cfg = make_crio_voltage_map(raw_min=raw_min, raw_max=raw_max,
                                          scaled_min=scaled_min, scaled_max=scaled_max)

        daq_result = daq_apply_scaling(daq_cfg, raw)
        crio_result = crio_apply_scaling(crio_cfg, raw)

        assert daq_result == pytest.approx(expected, abs=1e-10)
        assert crio_result == pytest.approx(expected, abs=1e-10)
        assert daq_result == pytest.approx(crio_result, abs=1e-10), \
            f"Map mismatch: raw={raw}: DAQ={daq_result}, cRIO={crio_result}"

# ============================================================
# Test 3: 4-20mA Scaling Parity
# ============================================================

class TestFourTwentyScalingParity:
    """4-20mA scaling must match between cRIO and DAQ."""

    @pytest.mark.parametrize("current_ma,eng_min,eng_max,expected", [
        (4.0, 0.0, 10000.0, 0.0),        # Zero (4mA)
        (12.0, 0.0, 10000.0, 5000.0),     # Midpoint
        (20.0, 0.0, 10000.0, 10000.0),    # Full scale
        (4.0, 0.0, 100.0, 0.0),           # Simple 0-100
        (12.0, 0.0, 100.0, 50.0),         # Simple midpoint
        (20.0, 0.0, 100.0, 100.0),        # Simple full
        (8.0, 0.0, 500.0, 125.0),         # Quarter range
        (16.0, 0.0, 500.0, 375.0),        # Three-quarter
    ])
    def test_420_parity(self, current_ma, eng_min, eng_max, expected):
        daq_cfg = make_daq_current_420(eng_min=eng_min, eng_max=eng_max)
        crio_cfg = make_crio_current_420(eng_min=eng_min, eng_max=eng_max)

        daq_result = daq_apply_scaling(daq_cfg, current_ma)
        crio_result = crio_apply_scaling(crio_cfg, current_ma)

        assert daq_result == pytest.approx(expected, abs=1e-10)
        assert crio_result == pytest.approx(expected, abs=1e-10)
        assert daq_result == pytest.approx(crio_result, abs=1e-10), \
            f"4-20mA mismatch: {current_ma}mA: DAQ={daq_result}, cRIO={crio_result}"

# ============================================================
# Test 4: NAMUR NE43 Edge Cases (4-20mA Diagnostics)
# ============================================================

class TestNamurNE43:
    """NAMUR NE43 diagnostic ranges for 4-20mA signals."""

    def test_under_range_wire_break(self):
        """Below 3.8mA = wire break / sensor error."""
        daq_cfg = make_daq_current_420(eng_min=0.0, eng_max=100.0)
        crio_cfg = make_crio_current_420(eng_min=0.0, eng_max=100.0)

        # 3.5mA — under-range
        daq_result = daq_apply_scaling(daq_cfg, 3.5)
        crio_result = crio_apply_scaling(crio_cfg, 3.5)

        # Both should extrapolate below eng_min
        assert daq_result < 0.0
        assert crio_result < 0.0
        assert daq_result == pytest.approx(crio_result, abs=1e-10)

    def test_over_range(self):
        """Above 20.5mA = over-range condition."""
        daq_cfg = make_daq_current_420(eng_min=0.0, eng_max=100.0)
        crio_cfg = make_crio_current_420(eng_min=0.0, eng_max=100.0)

        # 21mA — over-range
        daq_result = daq_apply_scaling(daq_cfg, 21.0)
        crio_result = crio_apply_scaling(crio_cfg, 21.0)

        # Both should extrapolate above eng_max
        assert daq_result > 100.0
        assert crio_result > 100.0
        assert daq_result == pytest.approx(crio_result, abs=1e-10)

    def test_zero_current(self):
        """0mA = total wire break."""
        daq_cfg = make_daq_current_420(eng_min=0.0, eng_max=100.0)
        crio_cfg = make_crio_current_420(eng_min=0.0, eng_max=100.0)

        daq_result = daq_apply_scaling(daq_cfg, 0.0)
        crio_result = crio_apply_scaling(crio_cfg, 0.0)

        # Both should give same (negative) result
        assert daq_result == pytest.approx(crio_result, abs=1e-10)
        assert daq_result < 0.0  # Well below engineering min

# ============================================================
# Test 5: Config Push Completeness
# ============================================================

class TestConfigPushCompleteness:
    """Verify all scaling params would be included in a config push."""

    def test_scaling_fields_in_crio_config(self):
        """cRIO ChannelConfig must have all scaling fields."""
        cfg = CRIOChannelConfig(
            name='test',
            physical_channel='Mod1/ai0',
            channel_type='voltage_input',
        )
        # All scaling fields must exist
        assert hasattr(cfg, 'scale_slope')
        assert hasattr(cfg, 'scale_offset')
        assert hasattr(cfg, 'scale_type')
        assert hasattr(cfg, 'four_twenty_scaling')
        assert hasattr(cfg, 'eng_units_min')
        assert hasattr(cfg, 'eng_units_max')
        assert hasattr(cfg, 'pre_scaled_min')
        assert hasattr(cfg, 'pre_scaled_max')
        assert hasattr(cfg, 'scaled_min')
        assert hasattr(cfg, 'scaled_max')

    def test_from_dict_parses_scaling(self):
        """from_dict must parse all scaling fields from config push payload."""
        payload = {
            'physical_channel': 'Mod1/ai0',
            'channel_type': 'voltage_input',
            'scale_slope': 2.5,
            'scale_offset': -1.0,
            'scale_type': 'map',
            'four_twenty_scaling': False,
            'eng_units_min': 0.0,
            'eng_units_max': 300.0,
            'pre_scaled_min': 0.0,
            'pre_scaled_max': 10.0,
            'scaled_min': 0.0,
            'scaled_max': 300.0,
        }
        cfg = CRIOChannelConfig.from_dict('PT_302', payload)

        assert cfg.scale_slope == 2.5
        assert cfg.scale_offset == -1.0
        assert cfg.scale_type == 'map'
        assert cfg.four_twenty_scaling is False
        assert cfg.eng_units_min == 0.0
        assert cfg.eng_units_max == 300.0
        assert cfg.pre_scaled_min == 0.0
        assert cfg.pre_scaled_max == 10.0
        assert cfg.scaled_min == 0.0
        assert cfg.scaled_max == 300.0

    def test_from_dict_parses_420(self):
        """from_dict must parse 4-20mA scaling fields."""
        payload = {
            'physical_channel': 'Mod2/ai0',
            'channel_type': 'current_input',
            'four_twenty_scaling': True,
            'eng_units_min': 0.0,
            'eng_units_max': 10000.0,
        }
        cfg = CRIOChannelConfig.from_dict('FT_401', payload)

        assert cfg.four_twenty_scaling is True
        assert cfg.eng_units_min == 0.0
        assert cfg.eng_units_max == 10000.0

    def test_to_dict_includes_scaling(self):
        """to_dict serialization must include scaling fields."""
        from crio_node_v2.config import NodeConfig
        node_cfg = NodeConfig(
            channels={
                'PT_302': CRIOChannelConfig(
                    name='PT_302',
                    physical_channel='Mod1/ai0',
                    channel_type='voltage_input',
                    scale_type='map',
                    pre_scaled_min=0.0,
                    pre_scaled_max=10.0,
                    scaled_min=0.0,
                    scaled_max=300.0,
                    four_twenty_scaling=False,
                )
            }
        )
        d = node_cfg.to_dict()
        ch = d['channels']['PT_302']

        assert ch['scale_type'] == 'map'
        assert ch['pre_scaled_min'] == 0.0
        assert ch['pre_scaled_max'] == 10.0
        assert ch['scaled_min'] == 0.0
        assert ch['scaled_max'] == 300.0
        assert ch['four_twenty_scaling'] is False

# ============================================================
# Test 6: No Scaling (Pass-through)
# ============================================================

class TestNoScaling:
    """Channels with no scaling configured should pass through raw values."""

    def test_passthrough_daq(self):
        cfg = make_daq_linear(slope=1.0, offset=0.0)
        cfg.scale_type = 'none'
        assert daq_apply_scaling(cfg, 5.0) == 5.0

    def test_passthrough_crio(self):
        cfg = CRIOChannelConfig(
            name='test',
            physical_channel='Mod1/ai0',
            channel_type='voltage_input',
            scale_slope=1.0,
            scale_offset=0.0,
            scale_type='none',
        )
        assert crio_apply_scaling(cfg, 5.0) == 5.0

    def test_passthrough_none_config(self):
        """cRIO apply_scaling with None config returns raw."""
        assert crio_apply_scaling(None, 42.0) == 42.0

# ============================================================
# Test 7: Boiler Simulation Scaling (end-to-end)
# ============================================================

class TestBoilerSimulationScaling:
    """Test scaling with the actual Boiler_Simulation_Debug project values."""

    def test_pt302_steam_pressure(self):
        """PT_302: Steam header pressure, 0-10V → 0-300 psig."""
        daq_cfg = make_daq_voltage_map(
            name="PT_302", raw_min=0, raw_max=10,
            scaled_min=0, scaled_max=300
        )
        crio_cfg = make_crio_voltage_map(
            name="PT_302", raw_min=0, raw_max=10,
            scaled_min=0, scaled_max=300
        )

        # At 5V → 150 psig
        assert daq_apply_scaling(daq_cfg, 5.0) == pytest.approx(150.0)
        assert crio_apply_scaling(crio_cfg, 5.0) == pytest.approx(150.0)

    def test_pt301_furnace_draft(self):
        """PT_301: Furnace draft pressure, 0-10V → -5 to +5 inH2O."""
        daq_cfg = make_daq_voltage_map(
            name="PT_301", raw_min=0, raw_max=10,
            scaled_min=-5, scaled_max=5
        )
        crio_cfg = make_crio_voltage_map(
            name="PT_301", raw_min=0, raw_max=10,
            scaled_min=-5, scaled_max=5
        )

        # At 5V → 0 inH2O (neutral draft)
        assert daq_apply_scaling(daq_cfg, 5.0) == pytest.approx(0.0)
        assert crio_apply_scaling(crio_cfg, 5.0) == pytest.approx(0.0)

        # At 0V → -5 inH2O (negative draft)
        assert daq_apply_scaling(daq_cfg, 0.0) == pytest.approx(-5.0)
        assert crio_apply_scaling(crio_cfg, 0.0) == pytest.approx(-5.0)

    def test_ft401_gas_flow(self):
        """FT_401: Natural gas flow, 4-20mA → 0-10000 SCFH."""
        daq_cfg = make_daq_current_420(name="FT_401", eng_min=0, eng_max=10000)
        crio_cfg = make_crio_current_420(name="FT_401", eng_min=0, eng_max=10000)

        # At 12mA → 5000 SCFH
        assert daq_apply_scaling(daq_cfg, 12.0) == pytest.approx(5000.0)
        assert crio_apply_scaling(crio_cfg, 12.0) == pytest.approx(5000.0)

    def test_ft402_feedwater(self):
        """FT_402: Feedwater flow, 4-20mA → 0-500 GPM."""
        daq_cfg = make_daq_current_420(name="FT_402", eng_min=0, eng_max=500)
        crio_cfg = make_crio_current_420(name="FT_402", eng_min=0, eng_max=500)

        # At 8mA → 125 GPM
        assert daq_apply_scaling(daq_cfg, 8.0) == pytest.approx(125.0)
        assert crio_apply_scaling(crio_cfg, 8.0) == pytest.approx(125.0)
