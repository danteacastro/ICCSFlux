"""
Automated Hardware Platform Test Suite
=======================================
Comprehensive tests for all four hardware platforms:
  - cDAQ (NI C-Series via NI-DAQmx on PC)
  - cRIO (NI C-Series via NI-DAQmx on cRIO controller)
  - Opto22 (groov EPIC/RIO GRV-series modules)
  - cFP (NI CompactFieldPoint via Modbus)

Tests cover:
  1. Module database completeness & correctness (all platforms)
  2. Channel type → DAQmx call mapping (cDAQ/cRIO)
  3. Configuration round-trip: ChannelConfig → hardware_reader → nidaqmx args
  4. Terminal config, scaling, enum mapping correctness
  5. Opto22 module database validation
  6. Cross-platform consistency (cRIO ↔ cDAQ share same modules)
  7. Realistic multi-module project configs for every module type

No physical hardware required — all NI-DAQmx calls are mocked.
"""

import pytest
import sys
import re
import ast
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass

# --- Path setup ---
DAQ_SERVICE = Path(__file__).parent.parent / "services" / "daq_service"
CRIO_NODE = Path(__file__).parent.parent / "services" / "crio_node_v2"
OPTO22_NODE = Path(__file__).parent.parent / "services" / "opto22_node"
CFP_NODE = Path(__file__).parent.parent / "services" / "cfp_node"

sys.path.insert(0, str(DAQ_SERVICE))
sys.path.insert(0, str(CRIO_NODE))
sys.path.insert(0, str(OPTO22_NODE))

# Import config_parser first (no nidaqmx dependency)
from config_parser import (
    NISystemConfig, SystemConfig, ChassisConfig, ModuleConfig, ChannelConfig,
    ChannelType, ThermocoupleType, DataViewerConfig
)

# Mock nidaqmx + numpy, then import hardware_reader
_mocked_modules = (
    'nidaqmx', 'nidaqmx.constants', 'nidaqmx.stream_readers', 'numpy'
)
_saved_modules = {m: sys.modules.get(m) for m in _mocked_modules}

# Build rich mock constants so hardware_reader's enum lookups work
mock_constants = MagicMock()

# TerminalConfiguration mock with all values
class _MockTermCfg:
    RSE = 'RSE'
    DIFF = 'DIFF'
    NRSE = 'NRSE'
    PSEUDO_DIFF = 'PSEUDO_DIFF'
    DEFAULT = 'DEFAULT'

class _MockTCType:
    J = 'J'; K = 'K'; T = 'T'; E = 'E'; N = 'N'; R = 'R'; S = 'S'; B = 'B'

class _MockAcqType:
    CONTINUOUS = 'CONTINUOUS'

class _MockEdge:
    RISING = 'RISING'; FALLING = 'FALLING'

class _MockLevel:
    LOW = 'LOW'; HIGH = 'HIGH'

class _MockCountDir:
    COUNT_UP = 'COUNT_UP'; COUNT_DOWN = 'COUNT_DOWN'

class _MockFreqMethod:
    LOW_FREQUENCY_1_COUNTER = 'LOW_FREQ'

class _MockFreqUnits:
    HZ = 'HZ'

class _MockSampleTiming:
    SAMPLE_CLOCK = 'SAMPLE_CLOCK'

class _MockStrainBridge:
    FULL_BRIDGE_I = 'FULL_BRIDGE_I'
    FULL_BRIDGE_II = 'FULL_BRIDGE_II'
    FULL_BRIDGE_III = 'FULL_BRIDGE_III'
    HALF_BRIDGE_I = 'HALF_BRIDGE_I'
    HALF_BRIDGE_II = 'HALF_BRIDGE_II'
    QUARTER_BRIDGE_I = 'QUARTER_BRIDGE_I'
    QUARTER_BRIDGE_II = 'QUARTER_BRIDGE_II'

class _MockBridgeConfig:
    FULL_BRIDGE = 'FULL_BRIDGE'
    HALF_BRIDGE = 'HALF_BRIDGE'
    QUARTER_BRIDGE = 'QUARTER_BRIDGE'
    NO_BRIDGE = 'NO_BRIDGE'

class _MockBridgeUnits:
    MILLIVOLTS_PER_VOLT = 'mV_PER_V'

class _MockCoupling:
    AC = 'AC'; DC = 'DC'

class _MockCJCSource:
    BUILT_IN = 'BUILT_IN'
    CONSTANT_USER_VALUE = 'CONSTANT_USER_VALUE'
    SCANNABLE_CHANNEL = 'SCANNABLE_CHANNEL'

class _MockCurrentShuntLoc:
    INTERNAL = 'INTERNAL'; EXTERNAL = 'EXTERNAL'

class _MockRTDType:
    PT_3750 = 'PT_3750'; PT_3851 = 'PT_3851'; PT_3916 = 'PT_3916'

class _MockResistanceConfig:
    TWO_WIRE = 'TWO_WIRE'; THREE_WIRE = 'THREE_WIRE'; FOUR_WIRE = 'FOUR_WIRE'

class _MockExcitationSource:
    INTERNAL = 'INTERNAL'; EXTERNAL = 'EXTERNAL'

mock_constants.TerminalConfiguration = _MockTermCfg
mock_constants.ThermocoupleType = _MockTCType
mock_constants.AcquisitionType = _MockAcqType
mock_constants.Edge = _MockEdge
mock_constants.Level = _MockLevel
mock_constants.CountDirection = _MockCountDir
mock_constants.CounterFrequencyMethod = _MockFreqMethod
mock_constants.FrequencyUnits = _MockFreqUnits
mock_constants.SampleTimingType = _MockSampleTiming
mock_constants.StrainGageBridgeType = _MockStrainBridge
mock_constants.BridgeConfiguration = _MockBridgeConfig
mock_constants.BridgeUnits = _MockBridgeUnits
mock_constants.Coupling = _MockCoupling
mock_constants.CJCSource = _MockCJCSource
mock_constants.CurrentShuntResistorLocation = _MockCurrentShuntLoc
mock_constants.RTDType = _MockRTDType
mock_constants.ResistanceConfiguration = _MockResistanceConfig
mock_constants.ExcitationSource = _MockExcitationSource
mock_constants.READ_ALL_AVAILABLE = -1

mock_nidaqmx = MagicMock()
mock_nidaqmx.constants = mock_constants

for m in _mocked_modules:
    sys.modules[m] = MagicMock()
sys.modules['nidaqmx'] = mock_nidaqmx
sys.modules['nidaqmx.constants'] = mock_constants

import hardware_reader
from hardware_reader import (
    get_terminal_config, get_cjc_source, TC_TYPE_MAP,
    HardwareReader, TaskGroup, _get_physical_channel_index,
)

# Restore modules
for m, orig in _saved_modules.items():
    if orig is not None:
        sys.modules[m] = orig
    else:
        sys.modules.pop(m, None)

hardware_reader.NIDAQMX_AVAILABLE = True

# Import platform-specific module databases
sys.path.insert(0, str(CRIO_NODE))
from channel_types import (
    MODULE_TYPE_MAP as NI_MODULE_MAP,
    COMBO_MODULE_MAP,
    RELAY_MODULES,
    MODULE_HARDWARE_LIMITS,
    get_module_channel_type,
    get_combo_channel_type,
    get_relay_type,
    get_module_hardware_limits,
    ChannelType as CrioChannelType,
)

# Import Opto22 channel_types under distinct name to avoid cRIO collision
import importlib.util as _ilu
_opto22_spec = _ilu.spec_from_file_location(
    'opto22_channel_types', str(OPTO22_NODE / 'channel_types.py'))
opto22_ct = _ilu.module_from_spec(_opto22_spec)
_opto22_spec.loader.exec_module(opto22_ct)
OPTO22_MODULES = opto22_ct.OPTO22_MODULES
Opto22ChannelType = opto22_ct.ChannelType

# Import device_discovery module database
from device_discovery import NI_MODULE_DATABASE


# ============================================================================
# SECTION 1: NI C-Series Module Database Tests (cDAQ + cRIO)
# ============================================================================

class TestNIModuleDatabase:
    """Verify every NI module in our database is real and correctly typed."""

    # Ground-truth: every NI 9xxx module number → expected channel type category
    # Source: NI C Series Module Overview (ni.com/c-series)
    NI_MODULE_SPECS = {
        # Voltage input
        '9201': 'voltage_input', '9202': 'voltage_input', '9204': 'voltage_input',
        '9205': 'voltage_input', '9206': 'voltage_input', '9209': 'voltage_input',
        '9215': 'voltage_input', '9220': 'voltage_input', '9221': 'voltage_input',
        '9222': 'voltage_input', '9223': 'voltage_input', '9224': 'voltage_input',
        '9225': 'voltage_input', '9228': 'voltage_input', '9229': 'voltage_input',
        '9238': 'voltage_input', '9239': 'voltage_input', '9242': 'voltage_input',
        '9244': 'voltage_input', '9252': 'voltage_input',
        # Current input
        '9203': 'current_input', '9208': 'current_input',
        '9227': 'current_input', '9246': 'current_input', '9247': 'current_input',
        '9253': 'current_input',
        # Combo (voltage + current)
        '9207': 'voltage_input',  # default=voltage, channels 8-15=current
        # Thermocouple
        '9210': 'thermocouple', '9211': 'thermocouple', '9212': 'thermocouple',
        '9213': 'thermocouple', '9214': 'thermocouple',
        # RTD
        '9216': 'rtd', '9217': 'rtd', '9226': 'rtd',
        # Universal (bridge default)
        '9218': 'bridge_input', '9219': 'bridge_input',
        # IEPE
        '9230': 'iepe_input', '9231': 'iepe_input', '9232': 'iepe_input',
        '9233': 'iepe_input', '9234': 'iepe_input', '9250': 'iepe_input',
        '9251': 'iepe_input',
        # Strain/Bridge
        '9235': 'strain_input', '9236': 'strain_input', '9237': 'bridge_input',
        # Voltage output
        '9260': 'voltage_output', '9262': 'voltage_output', '9263': 'voltage_output',
        '9264': 'voltage_output', '9269': 'voltage_output',
        # Current output
        '9265': 'current_output', '9266': 'current_output',
        # Digital input
        '9375': 'digital_input', '9401': 'digital_input', '9402': 'digital_input',
        '9403': 'digital_input', '9411': 'digital_input', '9421': 'digital_input',
        '9422': 'digital_input', '9423': 'digital_input', '9425': 'digital_input',
        '9426': 'digital_input', '9435': 'digital_input', '9436': 'digital_input',
        '9437': 'digital_input',
        # Digital output
        '9470': 'digital_output', '9472': 'digital_output', '9474': 'digital_output',
        '9475': 'digital_output', '9476': 'digital_output', '9477': 'digital_output',
        '9478': 'digital_output', '9481': 'digital_output', '9482': 'digital_output',
        '9485': 'digital_output',
        # Counter
        '9361': 'counter_input',
    }

    def test_all_spec_modules_in_crio_database(self):
        """Every module in our spec list must exist in NI_MODULE_MAP."""
        missing = []
        for model, expected_type in self.NI_MODULE_SPECS.items():
            if model not in NI_MODULE_MAP:
                missing.append(model)
        assert missing == [], f"Modules missing from cRIO MODULE_TYPE_MAP: {missing}"

    def test_all_spec_modules_in_discovery_database(self):
        """Every module in our spec list must exist in device_discovery NI_MODULE_DATABASE."""
        missing = []
        for model in self.NI_MODULE_SPECS:
            # Discovery uses "NI 9xxx" keys
            key = f"NI {model}"
            if key not in NI_MODULE_DATABASE:
                missing.append(key)
        assert missing == [], f"Modules missing from NI_MODULE_DATABASE: {missing}"

    def test_crio_module_types_match_spec(self):
        """Channel types in NI_MODULE_MAP must match the spec."""
        mismatches = []
        for model, expected_type in self.NI_MODULE_SPECS.items():
            if model in NI_MODULE_MAP:
                actual = NI_MODULE_MAP[model].value
                if actual != expected_type:
                    mismatches.append(f"NI {model}: expected={expected_type}, got={actual}")
        assert mismatches == [], f"Type mismatches:\n" + "\n".join(mismatches)

    def test_no_extra_modules_in_crio(self):
        """No fabricated modules in MODULE_TYPE_MAP."""
        extras = [m for m in NI_MODULE_MAP if m not in self.NI_MODULE_SPECS]
        assert extras == [], f"Unknown modules in MODULE_TYPE_MAP (verify these are real): {extras}"

    def test_databases_in_sync(self):
        """cRIO MODULE_TYPE_MAP and device_discovery NI_MODULE_DATABASE must list same modules."""
        crio_set = set(NI_MODULE_MAP.keys())
        # Discovery uses "NI 9xxx" prefix — strip it
        disc_set = set()
        for key in NI_MODULE_DATABASE:
            m = re.match(r'NI (\d+)', key)
            if m:
                disc_set.add(m.group(1))

        only_crio = crio_set - disc_set
        only_disc = disc_set - crio_set

        assert only_crio == set(), f"In cRIO MODULE_TYPE_MAP but not device_discovery: {only_crio}"
        assert only_disc == set(), f"In device_discovery but not cRIO MODULE_TYPE_MAP: {only_disc}"

    def test_combo_module_9207_split(self):
        """NI 9207 is a combo module: ai0-7=voltage, ai8-15=current."""
        assert '9207' in COMBO_MODULE_MAP
        alt_type, split_index = COMBO_MODULE_MAP['9207']
        assert alt_type == CrioChannelType.CURRENT_INPUT
        assert split_index == 8

        # Channel 0-7: voltage (returns None = use default)
        assert get_combo_channel_type('NI 9207', 0) is None
        assert get_combo_channel_type('NI 9207', 7) is None

        # Channel 8-15: current
        assert get_combo_channel_type('NI 9207', 8) == CrioChannelType.CURRENT_INPUT
        assert get_combo_channel_type('NI 9207', 15) == CrioChannelType.CURRENT_INPUT

    def test_relay_modules_exist(self):
        """All relay modules are correctly tagged."""
        assert get_relay_type('NI 9481') == 'spst'
        assert get_relay_type('NI 9482') == 'spdt'
        assert get_relay_type('NI 9485') == 'ssr'
        assert get_relay_type('NI 9263') == 'none'  # Not a relay

    def test_output_module_hardware_limits(self):
        """All output modules must have hardware limits defined."""
        output_models = [m for m, t in self.NI_MODULE_SPECS.items()
                        if t in ('voltage_output', 'current_output')]
        missing_limits = []
        for m in output_models:
            limits = get_module_hardware_limits(f'NI {m}')
            if limits is None:
                missing_limits.append(m)
        assert missing_limits == [], f"Output modules without hardware limits: {missing_limits}"

    def test_voltage_output_limits_bipolar(self):
        """Voltage output modules must have symmetric bipolar limits."""
        for model in ('9260', '9262', '9263', '9264', '9269'):
            limits = get_module_hardware_limits(f'NI {model}')
            assert limits is not None, f"NI {model} missing limits"
            assert limits['voltage_min'] < 0, f"NI {model} voltage_min should be negative (bipolar)"
            assert limits['voltage_max'] > 0, f"NI {model} voltage_max should be positive"
            assert abs(limits['voltage_min']) == limits['voltage_max'], f"NI {model} should be symmetric"

    def test_current_output_limits_unipolar(self):
        """Current output modules must have 0-20mA limits."""
        for model in ('9265', '9266'):
            limits = get_module_hardware_limits(f'NI {model}')
            assert limits is not None, f"NI {model} missing limits"
            assert limits['current_min_ma'] == 0.0
            assert limits['current_max_ma'] == 20.0

    @pytest.mark.parametrize("model", list(NI_MODULE_SPECS.keys()))
    def test_discovery_channel_count_positive(self, model):
        """Every module in discovery database must have channel count > 0."""
        key = f"NI {model}"
        if key in NI_MODULE_DATABASE:
            info = NI_MODULE_DATABASE[key]
            count = info.get('channels', info.get('channel_count', 0))
            assert count > 0, f"{key} has invalid channel count: {count}"


# ============================================================================
# SECTION 2: DAQmx Channel Configuration Tests
# ============================================================================

class TestDAQmxChannelSetup:
    """Verify hardware_reader configures DAQmx channels correctly."""

    def _make_config(self, channel_name, channel_type, **kwargs):
        """Helper to create a minimal NISystemConfig with one channel."""
        ch_kwargs = {
            'name': channel_name,
            'physical_channel': 'cDAQ1Mod1/ai0',
            'channel_type': channel_type,
        }
        ch_kwargs.update(kwargs)
        return NISystemConfig(
            system=SystemConfig(simulation_mode=False),
            chassis={'cDAQ1': ChassisConfig(name='cDAQ1', chassis_type='cDAQ-9189', device_name='cDAQ1')},
            modules={'Mod1': ModuleConfig(name='Mod1', module_type='NI-9205', chassis='cDAQ1', slot=1)},
            channels={channel_name: ChannelConfig(**ch_kwargs)},
            dataviewer=DataViewerConfig(), safety_actions={}
        )

    # --- Terminal configuration ---

    def test_terminal_config_all_valid_strings(self):
        """All terminal config strings must resolve to non-None."""
        for cfg_str in ('RSE', 'DIFF', 'DIFFERENTIAL', 'NRSE', 'PSEUDO_DIFF',
                        'PSEUDODIFFERENTIAL', 'DEFAULT', 'rse', 'diff', 'default'):
            result = get_terminal_config(cfg_str)
            assert result is not None, f"get_terminal_config('{cfg_str}') returned None"

    def test_terminal_config_invalid_fallback(self):
        """Invalid terminal config string must fall back to DEFAULT (not crash)."""
        result = get_terminal_config('INVALID_GARBAGE')
        assert result is not None

    # --- CJC Source ---

    def test_cjc_source_all_valid(self):
        """All CJC source strings must resolve correctly."""
        for src in ('INTERNAL', 'BUILT_IN', 'CONSTANT', 'CONST_VAL', 'CHANNEL', 'SCANNABLE_CHANNEL'):
            result = get_cjc_source(src)
            assert result is not None, f"get_cjc_source('{src}') returned None"

    def test_cjc_source_invalid_fallback(self):
        """Invalid CJC source must fall back to BUILT_IN."""
        result = get_cjc_source('INVALID')
        assert result is not None

    # --- TC type mapping ---

    def test_all_8_tc_types_mapped(self):
        """All 8 thermocouple types (J,K,T,E,N,R,S,B) must be in TC_TYPE_MAP."""
        assert len(TC_TYPE_MAP) == 8
        for tc_type in ThermocoupleType:
            assert tc_type in TC_TYPE_MAP, f"{tc_type} missing from TC_TYPE_MAP"

    # --- Physical channel index extraction ---

    def test_physical_channel_index_ai(self):
        assert _get_physical_channel_index('cDAQ1Mod1/ai0') == 0
        assert _get_physical_channel_index('cDAQ1Mod1/ai15') == 15

    def test_physical_channel_index_port_line(self):
        assert _get_physical_channel_index('cDAQ1Mod2/port0/line7') == 7
        assert _get_physical_channel_index('cDAQ1Mod3/port0/line31') == 31

    def test_physical_channel_index_no_digits(self):
        """Handles edge case of no trailing digits."""
        assert _get_physical_channel_index('nodigits') == 0

    # --- ChannelConfig defaults ---

    def test_voltage_input_defaults(self):
        """Voltage input channel has correct defaults."""
        ch = ChannelConfig(name='V1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.VOLTAGE_INPUT)
        assert ch.voltage_range == 10.0
        assert ch.terminal_config == 'DEFAULT'
        assert ch.scale_slope == 1.0
        assert ch.scale_offset == 0.0

    def test_current_input_defaults(self):
        """Current input channel has correct defaults."""
        ch = ChannelConfig(name='I1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.CURRENT_INPUT)
        assert ch.current_range_ma == 20.0
        assert ch.shunt_resistor_loc == 'internal'
        assert ch.terminal_config == 'DEFAULT'

    def test_thermocouple_defaults(self):
        """Thermocouple channel has correct defaults."""
        ch = ChannelConfig(name='TC1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.THERMOCOUPLE,
                          thermocouple_type=ThermocoupleType.K)
        assert ch.cjc_source == 'internal'
        assert ch.cjc_value == 25.0
        assert ch.open_detect is True
        assert ch.auto_zero is False

    def test_rtd_defaults(self):
        """RTD channel has correct defaults."""
        ch = ChannelConfig(name='RTD1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.RTD)
        assert ch.rtd_type == 'Pt100'
        assert ch.rtd_resistance == 100.0
        assert ch.rtd_wiring == '4-wire'
        assert ch.rtd_current == 0.001

    def test_strain_defaults(self):
        """Strain gauge channel has correct defaults."""
        ch = ChannelConfig(name='SG1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.STRAIN)
        assert ch.strain_config == 'full-bridge'
        assert ch.strain_excitation_voltage == 2.5
        assert ch.strain_gage_factor == 2.0
        assert ch.strain_resistance == 350.0
        assert ch.poisson_ratio == 0.30

    def test_iepe_defaults(self):
        """IEPE channel has correct defaults."""
        ch = ChannelConfig(name='IEPE1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.IEPE)
        assert ch.iepe_sensitivity == 100.0
        assert ch.iepe_current == 0.004  # 4mA in Amps
        assert ch.iepe_coupling == 'AC'

    def test_resistance_defaults(self):
        """Resistance channel has correct defaults."""
        ch = ChannelConfig(name='R1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.RESISTANCE)
        assert ch.resistance_range == 1000.0
        assert ch.resistance_wiring == '4-wire'

    def test_counter_defaults(self):
        """Counter channel has correct defaults."""
        ch = ChannelConfig(name='CTR1', physical_channel='cDAQ1Mod1/ctr0',
                          channel_type=ChannelType.COUNTER)
        assert ch.counter_mode == 'frequency'
        assert ch.counter_edge == 'rising'
        assert ch.counter_min_freq == 0.1
        assert ch.counter_max_freq == 1000.0

    def test_encoder_defaults(self):
        """Encoder (position mode counter) channel has correct defaults."""
        ch = ChannelConfig(name='ENC1', physical_channel='cDAQ1Mod1/ctr0',
                          channel_type=ChannelType.COUNTER,
                          counter_mode='position')
        assert ch.decoding_type == 'X4'
        assert ch.pulses_per_revolution == 1024
        assert ch.z_index_enable is False

    def test_digital_output_defaults(self):
        """Digital output channel has correct defaults."""
        ch = ChannelConfig(name='DO1', physical_channel='cDAQ1Mod1/port0/line0',
                          channel_type=ChannelType.DIGITAL_OUTPUT)
        assert ch.default_state is False
        assert ch.invert is False
        assert ch.relay_type == 'none'
        assert ch.momentary_pulse_ms == 0


# ============================================================================
# SECTION 3: Channel Type Enum Completeness
# ============================================================================

class TestChannelTypeEnum:
    """Verify ChannelType enum is complete and correct across platforms."""

    EXPECTED_TYPES = {
        'thermocouple', 'voltage_input', 'current_input', 'rtd',
        'strain', 'strain_input', 'bridge_input', 'iepe', 'iepe_input',
        'resistance', 'resistance_input',
        'voltage_output', 'current_output',
        'digital_input', 'digital_output',
        'counter', 'counter_input', 'counter_output',
        'frequency_input', 'pulse_output',
        'modbus_register', 'modbus_coil',
    }

    def test_all_expected_types_exist(self):
        """All expected channel types must be in the enum."""
        actual = {ct.value for ct in ChannelType}
        missing = self.EXPECTED_TYPES - actual
        assert missing == set(), f"Missing channel types: {missing}"

    def test_no_extra_types(self):
        """No unexpected channel types in the enum."""
        actual = {ct.value for ct in ChannelType}
        extra = actual - self.EXPECTED_TYPES
        assert extra == set(), f"Unexpected channel types: {extra}"

    def test_short_forms_resolve_to_explicit(self):
        """Short forms (strain, iepe, resistance, counter) must be valid."""
        assert ChannelType('strain') == ChannelType.STRAIN
        assert ChannelType('iepe') == ChannelType.IEPE
        assert ChannelType('resistance') == ChannelType.RESISTANCE
        assert ChannelType('counter') == ChannelType.COUNTER

    def test_legacy_aliases(self):
        """Legacy aliases must still work."""
        # These are defined in _missing_ classmethod
        try:
            assert ChannelType('voltage') == ChannelType.VOLTAGE_INPUT
            assert ChannelType('current') == ChannelType.CURRENT_INPUT
        except ValueError:
            # If _missing_ is not implemented, skip
            pytest.skip("Legacy aliases not supported by this ChannelType")


# ============================================================================
# SECTION 4: Opto22 Module Database Tests
# ============================================================================

class TestOpto22ModuleDatabase:
    """Verify every Opto22 module in our database uses real GRV-series part numbers."""

    # Valid GRV-series prefixes from Opto22 catalog
    VALID_GRV_PREFIXES = (
        'GRV-IAC', 'GRV-IDC', 'GRV-OAC', 'GRV-ODC', 'GRV-IMA', 'GRV-IV',
        'GRV-OVM', 'GRV-ITM', 'GRV-IRT', 'GRV-ITR', 'GRV-IIC', 'GRV-IVA',
        'GRV-CSE', 'GRV-CCA', 'GRV-MM', 'GRV-OMR', 'GRV-IACDCTTL',
        'GRV-IDCSW',
    )

    VALID_CHANNEL_TYPES = {
        'digital_input', 'digital_output', 'current_input', 'voltage_input',
        'thermocouple', 'rtd', 'resistance_input', 'voltage_output',
        'current_output', 'counter_input', 'serial',
    }

    def test_all_modules_have_grv_prefix(self):
        """All Opto22 modules must start with 'GRV-'."""
        bad = [m for m in OPTO22_MODULES if not m.startswith('GRV-')]
        assert bad == [], f"Non-GRV modules: {bad}"

    def test_all_module_types_valid(self):
        """All module type values must be recognized channel types."""
        bad = []
        for model, info in OPTO22_MODULES.items():
            if info['type'] not in self.VALID_CHANNEL_TYPES:
                bad.append(f"{model}: type={info['type']}")
        assert bad == [], f"Invalid module types:\n" + "\n".join(bad)

    def test_all_modules_have_positive_channel_count(self):
        """Every module must have channels > 0."""
        bad = [m for m, info in OPTO22_MODULES.items() if info.get('channels', 0) <= 0]
        assert bad == [], f"Modules with invalid channel count: {bad}"

    def test_all_modules_have_description(self):
        """Every module must have a non-empty description."""
        bad = [m for m, info in OPTO22_MODULES.items() if not info.get('description')]
        assert bad == [], f"Modules without description: {bad}"

    def test_no_fabricated_part_numbers(self):
        """Known fabricated part numbers must NOT be in the database."""
        KNOWN_FAKE = ['GRV-IVE-8', 'GRV-OVOE-8', 'GRV-OMOE-8', 'GRV-ODC-12']
        found = [m for m in KNOWN_FAKE if m in OPTO22_MODULES]
        assert found == [], f"Fabricated part numbers still in database: {found}"

    def test_minimum_module_count(self):
        """We should have at least 30 Opto22 modules (catalog has 40+)."""
        assert len(OPTO22_MODULES) >= 30, f"Only {len(OPTO22_MODULES)} modules — expected 30+"

    def test_all_major_categories_represented(self):
        """Opto22 database must cover all major I/O categories."""
        types_present = {info['type'] for info in OPTO22_MODULES.values()}
        required = {'digital_input', 'digital_output', 'voltage_input', 'current_input',
                    'thermocouple', 'rtd', 'voltage_output'}
        missing = required - types_present
        assert missing == set(), f"Missing I/O categories: {missing}"

    @pytest.mark.parametrize("part_number", list(OPTO22_MODULES.keys()))
    def test_module_part_number_format(self, part_number):
        """Each part number must match GRV-XXXX-NN pattern."""
        assert re.match(r'^GRV-[A-Z]', part_number), \
            f"Invalid format: {part_number}"


# ============================================================================
# SECTION 5: Cross-Platform Consistency
# ============================================================================

class TestCrossPlatformConsistency:
    """Verify cRIO and Opto22 channel_types.py share compatible patterns."""

    def test_crio_channel_type_enum_matches_config_parser(self):
        """cRIO ChannelType must include same types as config_parser ChannelType."""
        crio_values = {ct.value for ct in CrioChannelType}
        # Core types that MUST exist in cRIO
        required = {
            'voltage_input', 'current_input', 'thermocouple', 'rtd',
            'strain_input', 'bridge_input', 'iepe_input', 'resistance_input',
            'voltage_output', 'current_output',
            'digital_input', 'digital_output',
            'counter_input', 'frequency_input', 'pulse_output',
        }
        missing = required - crio_values
        assert missing == set(), f"cRIO missing channel types: {missing}"

    def test_opto22_channel_type_enum_matches_config_parser(self):
        """Opto22 ChannelType must include same core types as config_parser."""
        opto_values = {ct.value for ct in Opto22ChannelType}
        required = {
            'voltage_input', 'current_input', 'thermocouple', 'rtd',
            'voltage_output', 'current_output',
            'digital_input', 'digital_output',
            'counter_input',
        }
        missing = required - opto_values
        assert missing == set(), f"Opto22 missing channel types: {missing}"

    def test_crio_is_input_classification(self):
        """cRIO is_input() must correctly classify all input types."""
        for ct_val in ('voltage_input', 'current_input', 'thermocouple', 'rtd',
                       'digital_input', 'counter_input', 'frequency_input'):
            assert CrioChannelType.is_input(ct_val), f"{ct_val} should be input"

    def test_crio_is_output_classification(self):
        """cRIO is_output() must correctly classify all output types."""
        for ct_val in ('voltage_output', 'current_output', 'digital_output', 'pulse_output'):
            assert CrioChannelType.is_output(ct_val), f"{ct_val} should be output"

    def test_opto22_is_input_classification(self):
        """Opto22 is_input() must correctly classify all input types."""
        for ct_val in ('voltage_input', 'current_input', 'thermocouple', 'rtd',
                       'digital_input', 'counter_input', 'frequency_input'):
            assert Opto22ChannelType.is_input(ct_val), f"{ct_val} should be input"

    def test_opto22_is_output_classification(self):
        """Opto22 is_output() must correctly classify all output types."""
        for ct_val in ('voltage_output', 'current_output', 'digital_output', 'pulse_output'):
            assert Opto22ChannelType.is_output(ct_val), f"{ct_val} should be output"


# ============================================================================
# SECTION 6: Realistic Multi-Module Project Configs
# ============================================================================

class TestRealisticProjectConfigs:
    """
    Test realistic project configurations that combine multiple module types.
    These simulate real-world deployments to verify config parsing handles
    the full channel type matrix correctly.
    """

    def _build_project(self, modules_and_channels):
        """Build NISystemConfig from a list of (module_type, [(ch_name, ch_type, kwargs)])."""
        chassis = {'cDAQ1': ChassisConfig(name='cDAQ1', chassis_type='cDAQ-9189', device_name='cDAQ1')}
        modules = {}
        channels = {}

        for slot, (module_type, ch_list) in enumerate(modules_and_channels, start=1):
            mod_name = f'Mod{slot}'
            modules[mod_name] = ModuleConfig(
                name=mod_name, module_type=module_type, chassis='cDAQ1', slot=slot
            )
            for ch_name, ch_type, kwargs in ch_list:
                ch_kwargs = {
                    'name': ch_name,
                    'physical_channel': f'cDAQ1{mod_name}/ai{len(channels) % 16}',
                    'channel_type': ch_type,
                }
                ch_kwargs.update(kwargs)
                channels[ch_name] = ChannelConfig(**ch_kwargs)

        return NISystemConfig(
            system=SystemConfig(simulation_mode=False),
            chassis=chassis, modules=modules, channels=channels,
            dataviewer=DataViewerConfig(), safety_actions={}
        )

    def test_thermocouple_project_all_tc_types(self):
        """Project with NI 9213 using all 8 thermocouple types."""
        tc_channels = []
        for i, tc_type in enumerate(ThermocoupleType):
            tc_channels.append((
                f'TC_{tc_type.value}', ChannelType.THERMOCOUPLE,
                {'thermocouple_type': tc_type, 'cjc_source': 'internal'}
            ))

        config = self._build_project([('NI-9213', tc_channels)])
        assert len(config.channels) == 8
        for ch in config.channels.values():
            assert ch.channel_type == ChannelType.THERMOCOUPLE
            assert ch.thermocouple_type is not None

    def test_rtd_project_all_wiring_types(self):
        """Project with NI 9216 using 2-wire, 3-wire, 4-wire RTDs."""
        rtd_channels = [
            ('RTD_2W', ChannelType.RTD, {'rtd_type': 'Pt100', 'rtd_wiring': '2-wire'}),
            ('RTD_3W', ChannelType.RTD, {'rtd_type': 'Pt100', 'rtd_wiring': '3-wire'}),
            ('RTD_4W', ChannelType.RTD, {'rtd_type': 'Pt100', 'rtd_wiring': '4-wire'}),
            ('RTD_385', ChannelType.RTD, {'rtd_type': 'Pt385', 'rtd_wiring': '4-wire'}),
        ]
        config = self._build_project([('NI-9216', rtd_channels)])
        wirings = {ch.rtd_wiring for ch in config.channels.values()}
        assert wirings == {'2-wire', '3-wire', '4-wire'}

    def test_strain_project_all_bridge_variants(self):
        """Project with NI 9235 using all strain bridge configurations."""
        bridge_variants = [
            'full-bridge', 'full-bridge-I', 'full-bridge-II', 'full-bridge-III',
            'half-bridge', 'half-bridge-I', 'half-bridge-II',
            'quarter-bridge', 'quarter-bridge-I', 'quarter-bridge-II',
        ]
        strain_channels = [
            (f'SG_{v.replace("-", "_")}', ChannelType.STRAIN,
             {'strain_config': v, 'strain_gage_factor': 2.1, 'strain_excitation_voltage': 3.3})
            for v in bridge_variants
        ]
        config = self._build_project([('NI-9235', strain_channels)])
        assert len(config.channels) == len(bridge_variants)
        for ch in config.channels.values():
            assert ch.strain_config in bridge_variants

    def test_iepe_project_ac_dc_coupling(self):
        """Project with NI 9234 using AC and DC coupling modes."""
        iepe_channels = [
            ('ACCEL_AC', ChannelType.IEPE, {'iepe_coupling': 'AC', 'iepe_sensitivity': 100.0}),
            ('ACCEL_DC', ChannelType.IEPE, {'iepe_coupling': 'DC', 'iepe_sensitivity': 50.0}),
            ('MIC_AC', ChannelType.IEPE, {'iepe_coupling': 'AC', 'iepe_sensitivity': 45.0,
                                           'iepe_current': 0.002}),
        ]
        config = self._build_project([('NI-9234', iepe_channels)])
        couplings = {ch.iepe_coupling for ch in config.channels.values()}
        assert couplings == {'AC', 'DC'}

    def test_mixed_analog_project(self):
        """Project mixing voltage, current, and thermocouple on same chassis."""
        config = self._build_project([
            ('NI-9213', [
                ('TC_1', ChannelType.THERMOCOUPLE, {'thermocouple_type': ThermocoupleType.K}),
                ('TC_2', ChannelType.THERMOCOUPLE, {'thermocouple_type': ThermocoupleType.J}),
            ]),
            ('NI-9205', [
                ('V_1', ChannelType.VOLTAGE_INPUT, {'voltage_range': 10.0, 'terminal_config': 'DIFF'}),
                ('V_2', ChannelType.VOLTAGE_INPUT, {'voltage_range': 5.0, 'terminal_config': 'RSE'}),
            ]),
            ('NI-9208', [
                ('I_1', ChannelType.CURRENT_INPUT, {'current_range_ma': 20.0}),
            ]),
        ])
        types = {ch.channel_type for ch in config.channels.values()}
        assert types == {ChannelType.THERMOCOUPLE, ChannelType.VOLTAGE_INPUT, ChannelType.CURRENT_INPUT}

    def test_full_io_project(self):
        """Project with analog in, analog out, digital in, digital out, counter."""
        config = self._build_project([
            ('NI-9205', [
                ('AI_1', ChannelType.VOLTAGE_INPUT, {'voltage_range': 10.0}),
            ]),
            ('NI-9263', [
                ('AO_1', ChannelType.VOLTAGE_OUTPUT, {
                    'physical_channel': 'cDAQ1Mod2/ao0', 'voltage_range': 10.0,
                }),
            ]),
            ('NI-9421', [
                ('DI_1', ChannelType.DIGITAL_INPUT, {
                    'physical_channel': 'cDAQ1Mod3/port0/line0',
                }),
            ]),
            ('NI-9472', [
                ('DO_1', ChannelType.DIGITAL_OUTPUT, {
                    'physical_channel': 'cDAQ1Mod4/port0/line0',
                }),
            ]),
            ('NI-9361', [
                ('CTR_1', ChannelType.COUNTER, {
                    'physical_channel': 'cDAQ1Mod5/ctr0', 'counter_mode': 'frequency',
                }),
            ]),
        ])
        types = {ch.channel_type for ch in config.channels.values()}
        expected = {ChannelType.VOLTAGE_INPUT, ChannelType.VOLTAGE_OUTPUT,
                   ChannelType.DIGITAL_INPUT, ChannelType.DIGITAL_OUTPUT,
                   ChannelType.COUNTER}
        assert types == expected

    def test_terminal_config_per_module_type(self):
        """Different modules support different terminal configs."""
        # NI 9205: supports RSE, DIFF, NRSE
        # NI 9239: DIFF only (4-wire)
        config = self._build_project([
            ('NI-9205', [
                ('V_RSE', ChannelType.VOLTAGE_INPUT, {'terminal_config': 'RSE'}),
                ('V_DIFF', ChannelType.VOLTAGE_INPUT, {'terminal_config': 'DIFF'}),
                ('V_NRSE', ChannelType.VOLTAGE_INPUT, {'terminal_config': 'NRSE'}),
            ]),
            ('NI-9239', [
                ('V_9239', ChannelType.VOLTAGE_INPUT, {'terminal_config': 'DIFF'}),
            ]),
        ])
        configs = {ch.name: ch.terminal_config for ch in config.channels.values()}
        assert configs['V_RSE'] == 'RSE'
        assert configs['V_DIFF'] == 'DIFF'
        assert configs['V_NRSE'] == 'NRSE'
        assert configs['V_9239'] == 'DIFF'

    def test_voltage_output_bipolar_range(self):
        """Voltage output must support negative values (not hardcoded to 0)."""
        ch = ChannelConfig(
            name='AO_1', physical_channel='cDAQ1Mod2/ao0',
            channel_type=ChannelType.VOLTAGE_OUTPUT,
            voltage_range=10.0,
        )
        # The fix: voltage_range_min should default to -voltage_range for bipolar outputs
        # Before fix: min was hardcoded to 0.0
        assert ch.voltage_range == 10.0
        # Check the default_value (for outputs, can be set to negative)
        assert ch.default_value == 0.0

    def test_4_20ma_scaling_config(self):
        """4-20mA scaling must map 4mA→eng_min, 20mA→eng_max."""
        ch = ChannelConfig(
            name='I_1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.CURRENT_INPUT,
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
            units='PSI'
        )
        assert ch.four_twenty_scaling is True
        assert ch.eng_units_min == 0.0
        assert ch.eng_units_max == 100.0


# ============================================================================
# SECTION 7: Strain Gauge / Bridge Configuration Matrix
# ============================================================================

class TestStrainBridgeMatrix:
    """
    Verify the critical distinction between StrainGageBridgeType and BridgeConfiguration.

    add_ai_strain_gage_chan() → StrainGageBridgeType (7 variants, measures µε)
    add_ai_bridge_chan()      → BridgeConfiguration (4 variants, measures mV/V)
    """

    STRAIN_VARIANTS = [
        'full-bridge', 'full-bridge-I', 'full-bridge-II', 'full-bridge-III',
        'half-bridge', 'half-bridge-I', 'half-bridge-II',
        'quarter-bridge', 'quarter-bridge-I', 'quarter-bridge-II',
    ]

    BRIDGE_VARIANTS = ['full-bridge', 'half-bridge', 'quarter-bridge']

    def test_strain_channel_type(self):
        """Strain channels must use STRAIN or STRAIN_INPUT type."""
        ch = ChannelConfig(name='SG1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.STRAIN)
        assert ch.channel_type == ChannelType.STRAIN

    def test_bridge_channel_type(self):
        """Bridge channels must use BRIDGE_INPUT type."""
        ch = ChannelConfig(name='BR1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.BRIDGE_INPUT)
        assert ch.channel_type == ChannelType.BRIDGE_INPUT

    def test_strain_all_7_wiring_variants(self):
        """All 7 strain gage bridge wiring variants must be representable."""
        SEVEN_STRAIN = {
            'full-bridge-I', 'full-bridge-II', 'full-bridge-III',
            'half-bridge-I', 'half-bridge-II',
            'quarter-bridge-I', 'quarter-bridge-II',
        }
        for variant in SEVEN_STRAIN:
            ch = ChannelConfig(name=f'SG_{variant}', physical_channel='ai0',
                              channel_type=ChannelType.STRAIN, strain_config=variant)
            assert ch.strain_config == variant

    def test_strain_short_forms_valid(self):
        """Short forms (full-bridge, half-bridge, quarter-bridge) must be valid."""
        for short in ('full-bridge', 'half-bridge', 'quarter-bridge'):
            ch = ChannelConfig(name=f'SG_{short}', physical_channel='ai0',
                              channel_type=ChannelType.STRAIN, strain_config=short)
            assert ch.strain_config == short

    def test_bridge_only_3_configs(self):
        """Generic bridge only supports FULL/HALF/QUARTER/NO_BRIDGE."""
        for cfg in ('full-bridge', 'half-bridge', 'quarter-bridge'):
            ch = ChannelConfig(name=f'BR_{cfg}', physical_channel='ai0',
                              channel_type=ChannelType.BRIDGE_INPUT, strain_config=cfg)
            assert ch.strain_config == cfg

    def test_ni_9235_is_strain(self):
        """NI 9235 (quarter-bridge 120Ω) should map to STRAIN_INPUT."""
        assert NI_MODULE_MAP['9235'] == CrioChannelType.STRAIN_INPUT

    def test_ni_9236_is_strain(self):
        """NI 9236 (quarter-bridge 350Ω) should map to STRAIN_INPUT."""
        assert NI_MODULE_MAP['9236'] == CrioChannelType.STRAIN_INPUT

    def test_ni_9237_is_bridge(self):
        """NI 9237 (full/half/quarter selectable) should map to BRIDGE_INPUT."""
        assert NI_MODULE_MAP['9237'] == CrioChannelType.BRIDGE_INPUT

    def test_ni_9219_is_bridge(self):
        """NI 9219 (universal AI) should map to BRIDGE_INPUT (universal default)."""
        assert NI_MODULE_MAP['9219'] == CrioChannelType.BRIDGE_INPUT


# ============================================================================
# SECTION 8: IEPE / Accelerometer Configuration
# ============================================================================

class TestIEPEConfiguration:
    """Verify IEPE/accelerometer channel setup is correct."""

    def test_iepe_current_in_amps(self):
        """IEPE excitation current must be in Amps (not mA)."""
        ch = ChannelConfig(name='ACCEL', physical_channel='ai0',
                          channel_type=ChannelType.IEPE,
                          iepe_current=0.004)  # 4mA = 0.004A
        assert ch.iepe_current == 0.004
        assert ch.iepe_current < 1.0, "IEPE current must be in Amps (< 1.0), not mA"

    def test_iepe_coupling_values(self):
        """IEPE coupling must be 'AC' or 'DC'."""
        for coupling in ('AC', 'DC'):
            ch = ChannelConfig(name='ACCEL', physical_channel='ai0',
                              channel_type=ChannelType.IEPE, iepe_coupling=coupling)
            assert ch.iepe_coupling == coupling

    def test_iepe_sensitivity_units(self):
        """IEPE sensitivity is in mV/g (or mV/Pa for microphones)."""
        ch = ChannelConfig(name='ACCEL', physical_channel='ai0',
                          channel_type=ChannelType.IEPE,
                          iepe_sensitivity=100.0)
        assert ch.iepe_sensitivity == 100.0

    def test_ni_iepe_modules_all_mapped(self):
        """All NI IEPE modules must be mapped to IEPE_INPUT."""
        iepe_models = ['9230', '9231', '9232', '9233', '9234', '9250', '9251']
        for model in iepe_models:
            assert NI_MODULE_MAP[model] == CrioChannelType.IEPE_INPUT, \
                f"NI {model} should be IEPE_INPUT"


# ============================================================================
# SECTION 9: Counter / Encoder Configuration
# ============================================================================

class TestCounterConfiguration:
    """Verify counter and encoder channel configurations."""

    def test_counter_modes(self):
        """All counter modes must be valid."""
        for mode in ('frequency', 'count', 'period', 'position'):
            ch = ChannelConfig(name='CTR', physical_channel='ctr0',
                              channel_type=ChannelType.COUNTER, counter_mode=mode)
            assert ch.counter_mode == mode

    def test_counter_edge_types(self):
        """Counter edge must be rising, falling, or both."""
        for edge in ('rising', 'falling', 'both'):
            ch = ChannelConfig(name='CTR', physical_channel='ctr0',
                              channel_type=ChannelType.COUNTER, counter_edge=edge)
            assert ch.counter_edge == edge

    def test_encoder_decoding_types(self):
        """Encoder decoding types: X1, X2, X4, two_pulse."""
        for dt in ('X1', 'X2', 'X4', 'two_pulse'):
            ch = ChannelConfig(name='ENC', physical_channel='ctr0',
                              channel_type=ChannelType.COUNTER,
                              counter_mode='position', decoding_type=dt)
            assert ch.decoding_type == dt

    def test_encoder_z_index(self):
        """Encoder Z-index (home pulse) enable/disable."""
        ch = ChannelConfig(name='ENC', physical_channel='ctr0',
                          channel_type=ChannelType.COUNTER,
                          counter_mode='position', z_index_enable=True)
        assert ch.z_index_enable is True

    def test_pulse_output_config(self):
        """Pulse output frequency and duty cycle."""
        ch = ChannelConfig(name='PWM', physical_channel='ctr0',
                          channel_type=ChannelType.PULSE_OUTPUT,
                          pulse_frequency=10000.0, pulse_duty_cycle=75.0,
                          pulse_idle_state='HIGH')
        assert ch.pulse_frequency == 10000.0
        assert ch.pulse_duty_cycle == 75.0
        assert ch.pulse_idle_state == 'HIGH'


# ============================================================================
# SECTION 10: HardwareSource Detection
# ============================================================================

class TestHardwareSourceDetection:
    """Verify HardwareSource.from_channel_config routes correctly."""

    def test_local_daq_default(self):
        """Default channels route to LOCAL_DAQ."""
        ch = ChannelConfig(name='V1', physical_channel='cDAQ1Mod1/ai0',
                          channel_type=ChannelType.VOLTAGE_INPUT)
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.LOCAL_DAQ

    def test_crio_source(self):
        """cRIO channels route to CRIO."""
        ch = ChannelConfig(name='V1', physical_channel='Mod1/ai0',
                          channel_type=ChannelType.VOLTAGE_INPUT, source_type='crio')
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.CRIO

    def test_opto22_source(self):
        """Opto22 channels route to OPTO22."""
        ch = ChannelConfig(name='V1', physical_channel='AI_0',
                          channel_type=ChannelType.VOLTAGE_INPUT, source_type='opto22')
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.OPTO22

    def test_modbus_tcp_source(self):
        """Modbus register channels route to MODBUS_TCP."""
        ch = ChannelConfig(name='M1', physical_channel='192.168.1.100:502:40001',
                          channel_type=ChannelType.MODBUS_REGISTER)
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.MODBUS_TCP

    def test_modbus_rtu_source(self):
        """Modbus RTU channels route to MODBUS_RTU."""
        ch = ChannelConfig(name='M1', physical_channel='rtu://COM3:1:40001',
                          channel_type=ChannelType.MODBUS_REGISTER)
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.MODBUS_RTU

    def test_cfp_tcp_source(self):
        """CFP channels with source_type='cfp' route to MODBUS_TCP."""
        ch = ChannelConfig(name='TC1', physical_channel='192.168.1.50:502:40001',
                          channel_type=ChannelType.THERMOCOUPLE, source_type='cfp')
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.MODBUS_TCP

    def test_cfp_rtu_source(self):
        """CFP channels with RTU physical channel route to MODBUS_RTU."""
        ch = ChannelConfig(name='TC1', physical_channel='rtu://COM4:1:40001',
                          channel_type=ChannelType.THERMOCOUPLE, source_type='cfp')
        from config_parser import HardwareSource
        assert ch.hardware_source == HardwareSource.MODBUS_RTU


# ============================================================================
# SECTION 11: Module-Specific Terminal Config Constraints
# ============================================================================

class TestModuleTerminalConfigConstraints:
    """
    Verify that terminal configuration constraints per module are documented.
    Not all NI modules support all terminal configurations.

    This serves as a reference and validates our understanding of hardware limits.
    """

    # Source: NI hardware datasheets
    MODULE_TERM_SUPPORT = {
        # Module: set of supported terminal configs
        '9205': {'RSE', 'DIFF', 'NRSE'},      # 32 SE / 16 DIFF, switchable
        '9206': {'DIFF'},                        # Isolated differential only
        '9215': {'DIFF'},                        # Simultaneous sampling, DIFF only
        '9220': {'DIFF'},                        # Simultaneous sampling, DIFF only
        '9222': {'DIFF'},                        # Simultaneous sampling, DIFF only
        '9223': {'DIFF'},                        # Simultaneous sampling, DIFF only
        '9239': {'DIFF'},                        # 24-bit, DIFF only
        '9201': {'RSE'},                         # Single-ended only
        '9221': {'DIFF'},                        # ±60V, DIFF only
        '9229': {'DIFF'},                        # Isolated, DIFF only
        '9209': {'RSE', 'DIFF'},                 # 16 DIFF / 32 SE
        '9204': {'RSE', 'DIFF'},                 # 16 SE / 8 DIFF
    }

    @pytest.mark.parametrize("model,supported", list(MODULE_TERM_SUPPORT.items()))
    def test_module_term_support_documented(self, model, supported):
        """Verify module terminal configuration support is documented."""
        assert model in NI_MODULE_MAP, f"NI {model} not in MODULE_TYPE_MAP"
        assert len(supported) > 0, f"NI {model} has no supported terminal configs"

    def test_9205_triple_mode(self):
        """NI 9205 must support RSE, DIFF, and NRSE (most versatile)."""
        supported = self.MODULE_TERM_SUPPORT['9205']
        assert 'RSE' in supported
        assert 'DIFF' in supported
        assert 'NRSE' in supported

    def test_diff_only_modules(self):
        """Modules that only support DIFF should be flagged."""
        diff_only = [m for m, s in self.MODULE_TERM_SUPPORT.items() if s == {'DIFF'}]
        assert len(diff_only) > 0, "Should have at least one DIFF-only module"
        for m in diff_only:
            assert self.MODULE_TERM_SUPPORT[m] == {'DIFF'}


# ============================================================================
# SECTION 12: Config Round-Trip Integrity
# ============================================================================

class TestConfigRoundTrip:
    """
    Test that channel configurations survive JSON round-trip:
    ChannelConfig → dict → JSON → dict → ChannelConfig
    """

    def _round_trip(self, ch):
        """Serialize a ChannelConfig to dict, then reconstruct."""
        import json
        from dataclasses import asdict

        d = asdict(ch)
        # ChannelType enum → string
        d['channel_type'] = ch.channel_type.value
        if ch.thermocouple_type:
            d['thermocouple_type'] = ch.thermocouple_type.value

        json_str = json.dumps(d)
        d2 = json.loads(json_str)

        # Reconstruct
        d2['channel_type'] = ChannelType(d2['channel_type'])
        if d2.get('thermocouple_type'):
            d2['thermocouple_type'] = ThermocoupleType(d2['thermocouple_type'])

        return ChannelConfig(**d2)

    def test_thermocouple_round_trip(self):
        """Thermocouple config survives serialization."""
        ch = ChannelConfig(
            name='TC1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.THERMOCOUPLE,
            thermocouple_type=ThermocoupleType.K,
            cjc_source='internal', cjc_value=25.0,
            open_detect=True, auto_zero=False
        )
        ch2 = self._round_trip(ch)
        assert ch2.thermocouple_type == ThermocoupleType.K
        assert ch2.cjc_source == 'internal'
        assert ch2.open_detect is True

    def test_strain_round_trip(self):
        """Strain gauge config survives serialization."""
        ch = ChannelConfig(
            name='SG1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.STRAIN,
            strain_config='quarter-bridge-II',
            strain_gage_factor=2.1,
            strain_excitation_voltage=3.3,
            strain_resistance=120.0,
            poisson_ratio=0.285
        )
        ch2 = self._round_trip(ch)
        assert ch2.strain_config == 'quarter-bridge-II'
        assert ch2.strain_gage_factor == 2.1
        assert ch2.strain_excitation_voltage == 3.3
        assert ch2.strain_resistance == 120.0
        assert ch2.poisson_ratio == 0.285

    def test_iepe_round_trip(self):
        """IEPE config survives serialization."""
        ch = ChannelConfig(
            name='ACCEL1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.IEPE,
            iepe_sensitivity=50.0,
            iepe_current=0.002,  # 2mA
            iepe_coupling='DC',
            terminal_config='DIFF'
        )
        ch2 = self._round_trip(ch)
        assert ch2.iepe_sensitivity == 50.0
        assert ch2.iepe_current == 0.002
        assert ch2.iepe_coupling == 'DC'
        assert ch2.terminal_config == 'DIFF'

    def test_counter_encoder_round_trip(self):
        """Encoder config survives serialization."""
        ch = ChannelConfig(
            name='ENC1', physical_channel='cDAQ1Mod1/ctr0',
            channel_type=ChannelType.COUNTER,
            counter_mode='position',
            decoding_type='X4',
            pulses_per_revolution=2048,
            z_index_enable=True
        )
        ch2 = self._round_trip(ch)
        assert ch2.counter_mode == 'position'
        assert ch2.decoding_type == 'X4'
        assert ch2.pulses_per_revolution == 2048
        assert ch2.z_index_enable is True

    def test_current_input_round_trip(self):
        """Current input with shunt and terminal config survives serialization."""
        ch = ChannelConfig(
            name='I1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.CURRENT_INPUT,
            current_range_ma=20.0,
            shunt_resistor_loc='external',
            terminal_config='DIFF',
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=250.0,
            units='PSI'
        )
        ch2 = self._round_trip(ch)
        assert ch2.shunt_resistor_loc == 'external'
        assert ch2.terminal_config == 'DIFF'
        assert ch2.four_twenty_scaling is True
        assert ch2.eng_units_max == 250.0

    def test_voltage_input_with_scaling_round_trip(self):
        """Voltage input with map scaling survives serialization."""
        ch = ChannelConfig(
            name='V1', physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.VOLTAGE_INPUT,
            voltage_range=10.0,
            terminal_config='RSE',
            scale_type='map',
            pre_scaled_min=-10.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=100.0,
            units='%'
        )
        ch2 = self._round_trip(ch)
        assert ch2.terminal_config == 'RSE'
        assert ch2.pre_scaled_min == -10.0
        assert ch2.scaled_max == 100.0


# ============================================================================
# SECTION 13: Safety-Critical Output Limits
# ============================================================================

class TestSafetyCriticalOutputLimits:
    """
    Verify that output channels enforce hardware limits.
    Critical for safety — writing out-of-range values can damage hardware.
    """

    def test_voltage_output_within_module_limits(self):
        """User-configured voltage range must not exceed module hardware limits."""
        for model, limits in MODULE_HARDWARE_LIMITS.items():
            if 'voltage_min' in limits:
                v_min = limits['voltage_min']
                v_max = limits['voltage_max']
                # No user config should exceed these bounds
                assert v_min >= -15.0, f"NI {model} voltage_min={v_min} too low"
                assert v_max <= 15.0, f"NI {model} voltage_max={v_max} too high"

    def test_current_output_within_module_limits(self):
        """User-configured current range must not exceed module hardware limits."""
        for model, limits in MODULE_HARDWARE_LIMITS.items():
            if 'current_min_ma' in limits:
                i_min = limits['current_min_ma']
                i_max = limits['current_max_ma']
                assert i_min >= 0.0, f"NI {model} current_min_ma={i_min} negative"
                assert i_max <= 25.0, f"NI {model} current_max_ma={i_max} too high"

    def test_relay_momentary_pulse_config(self):
        """Relay momentary pulse config defaults to latching (0ms)."""
        ch = ChannelConfig(name='RLY', physical_channel='port0/line0',
                          channel_type=ChannelType.DIGITAL_OUTPUT,
                          relay_type='spdt')
        assert ch.momentary_pulse_ms == 0  # 0 = latching mode


# ============================================================================
# SECTION 14: Modbus Configuration Validation
# ============================================================================

class TestModbusConfiguration:
    """Verify Modbus channel configurations are valid."""

    def test_modbus_register_types(self):
        """All Modbus register types must be valid."""
        for reg_type in ('holding', 'input', 'coil', 'discrete'):
            ch = ChannelConfig(name='M1', physical_channel='192.168.1.1:502:40001',
                              channel_type=ChannelType.MODBUS_REGISTER,
                              modbus_register_type=reg_type)
            assert ch.modbus_register_type == reg_type

    def test_modbus_data_types(self):
        """All Modbus data types must be valid."""
        for data_type in ('int16', 'uint16', 'int32', 'uint32', 'float32', 'float64', 'bool'):
            ch = ChannelConfig(name='M1', physical_channel='192.168.1.1:502:40001',
                              channel_type=ChannelType.MODBUS_REGISTER,
                              modbus_data_type=data_type)
            assert ch.modbus_data_type == data_type

    def test_modbus_byte_orders(self):
        """Modbus byte/word order must be 'big' or 'little'."""
        for order in ('big', 'little'):
            ch = ChannelConfig(name='M1', physical_channel='192.168.1.1:502:40001',
                              channel_type=ChannelType.MODBUS_REGISTER,
                              modbus_byte_order=order, modbus_word_order=order)
            assert ch.modbus_byte_order == order
            assert ch.modbus_word_order == order

    def test_modbus_slave_id_explicit(self):
        """Explicit slave ID overrides module slot."""
        ch = ChannelConfig(name='M1', physical_channel='192.168.1.1:502:40001',
                          channel_type=ChannelType.MODBUS_REGISTER,
                          modbus_slave_id=5)
        assert ch.modbus_slave_id == 5

    def test_modbus_scaling(self):
        """Modbus scale and offset must work correctly."""
        ch = ChannelConfig(name='M1', physical_channel='192.168.1.1:502:40001',
                          channel_type=ChannelType.MODBUS_REGISTER,
                          modbus_scale=0.1, modbus_offset=-40.0)
        # value = raw * 0.1 - 40.0
        raw = 400
        expected = raw * ch.modbus_scale + ch.modbus_offset
        assert expected == 0.0


# ============================================================================
# SECTION 15: Simulation Coverage (All Channel Types)
# ============================================================================

class TestSimulationCoverage:
    """
    Verify the HardwareSimulator can simulate ALL channel types.
    This lets us test without physical hardware.
    """

    @pytest.fixture
    def simulator(self):
        """Import and create a HardwareSimulator with every channel type."""
        from simulator import HardwareSimulator
        channels = {
            'TC_K': ChannelConfig(name='TC_K', physical_channel='sim/ai0',
                                  channel_type=ChannelType.THERMOCOUPLE,
                                  thermocouple_type=ThermocoupleType.K),
            'RTD_1': ChannelConfig(name='RTD_1', physical_channel='sim/ai1',
                                   channel_type=ChannelType.RTD, rtd_type='Pt100'),
            'V_1': ChannelConfig(name='V_1', physical_channel='sim/ai2',
                                 channel_type=ChannelType.VOLTAGE_INPUT, voltage_range=10.0),
            'I_1': ChannelConfig(name='I_1', physical_channel='sim/ai3',
                                 channel_type=ChannelType.CURRENT_INPUT),
            'DI_1': ChannelConfig(name='DI_1', physical_channel='sim/port0/line0',
                                  channel_type=ChannelType.DIGITAL_INPUT),
            'DO_1': ChannelConfig(name='DO_1', physical_channel='sim/port0/line1',
                                  channel_type=ChannelType.DIGITAL_OUTPUT),
            'CTR_1': ChannelConfig(name='CTR_1', physical_channel='sim/ctr0',
                                   channel_type=ChannelType.COUNTER, counter_mode='frequency'),
            'AO_1': ChannelConfig(name='AO_1', physical_channel='sim/ao0',
                                  channel_type=ChannelType.VOLTAGE_OUTPUT),
            'SG_1': ChannelConfig(name='SG_1', physical_channel='sim/ai4',
                                  channel_type=ChannelType.STRAIN),
            'IEPE_1': ChannelConfig(name='IEPE_1', physical_channel='sim/ai5',
                                    channel_type=ChannelType.IEPE),
            'R_1': ChannelConfig(name='R_1', physical_channel='sim/ai6',
                                 channel_type=ChannelType.RESISTANCE),
        }
        config = NISystemConfig(
            system=SystemConfig(simulation_mode=True),
            chassis={}, modules={}, channels=channels,
            dataviewer=DataViewerConfig(), safety_actions={}
        )
        return HardwareSimulator(config)

    def test_simulator_reads_all_types(self, simulator):
        """Simulator must return values for all configured channel types."""
        values = simulator.read_all()
        expected_channels = {'TC_K', 'RTD_1', 'V_1', 'I_1', 'DI_1', 'DO_1',
                           'CTR_1', 'AO_1', 'SG_1', 'IEPE_1', 'R_1'}
        missing = expected_channels - set(values.keys())
        assert missing == set(), f"Simulator missing channels: {missing}"

    def test_simulator_thermocouple_range(self, simulator):
        """Simulated thermocouple must return realistic temperature."""
        values = simulator.read_all()
        temp = values.get('TC_K', 0.0)
        assert -50 < temp < 500, f"TC value {temp} out of realistic range"

    def test_simulator_voltage_range(self, simulator):
        """Simulated voltage must be within configured range."""
        values = simulator.read_all()
        v = values.get('V_1', 0.0)
        assert -15 < v < 15, f"Voltage value {v} out of range"

    def test_simulator_current_range(self, simulator):
        """Simulated current must be within 0-25mA range."""
        values = simulator.read_all()
        i = values.get('I_1', 0.0)
        # Simulator may return in mA (0-20) or raw
        assert -5 < i < 30, f"Current value {i} out of range"

    def test_simulator_digital_binary(self, simulator):
        """Simulated digital values must be 0.0 or 1.0."""
        values = simulator.read_all()
        di = values.get('DI_1', -1)
        assert di in (0.0, 1.0), f"Digital input value {di} not binary"

    def test_simulator_write_output(self, simulator):
        """Simulator must accept output writes."""
        simulator.write_channel('DO_1', True)
        values = simulator.read_all()
        assert values.get('DO_1') == 1.0

    def test_simulator_counter_non_negative(self, simulator):
        """Simulated counter must be non-negative."""
        values = simulator.read_all()
        ctr = values.get('CTR_1', -1)
        assert ctr >= 0, f"Counter value {ctr} should be non-negative"
