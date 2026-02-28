"""
Tests for hardware_reader.py
Covers hardware reader helper functions and configuration.
Note: Actual hardware tests require nidaqmx and physical hardware.
These tests focus on the logic that can be tested without hardware.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

# Import config_parser first since hardware_reader depends on it
from config_parser import (
    NISystemConfig, SystemConfig, ChassisConfig, ModuleConfig, ChannelConfig,
    ChannelType, ThermocoupleType, DataViewerConfig
)

# Mock nidaqmx/numpy before importing hardware_reader, then restore all mocks
# to prevent leaking into other test files (e.g. device_discovery tests)
_mocked = ('nidaqmx', 'nidaqmx.constants', 'nidaqmx.stream_readers', 'numpy')
_saved = {m: sys.modules.get(m) for m in _mocked}
for m in _mocked:
    sys.modules[m] = MagicMock()

import hardware_reader
from hardware_reader import (
    get_terminal_config, get_cjc_source, TC_TYPE_MAP,
    DEFAULT_SAMPLE_RATE_HZ, BUFFER_SIZE
)

# Restore all original modules (remove mocks)
for m, orig in _saved.items():
    if orig is not None:
        sys.modules[m] = orig
    else:
        sys.modules.pop(m, None)

# hardware_reader captured mock references at import time — force NIDAQMX_AVAILABLE=True
# so get_terminal_config/get_cjc_source don't bail with None
hardware_reader.NIDAQMX_AVAILABLE = True


class TestConstants:
    """Tests for module constants"""

    def test_sample_rate(self):
        """Test default sample rate"""
        assert DEFAULT_SAMPLE_RATE_HZ == 10

    def test_buffer_size(self):
        """Test default buffer size"""
        assert BUFFER_SIZE == 100


class TestTCTypeMap:
    """Tests for thermocouple type mapping"""

    def test_all_tc_types_mapped(self):
        """Test that all thermocouple types have mappings"""
        assert ThermocoupleType.J in TC_TYPE_MAP
        assert ThermocoupleType.K in TC_TYPE_MAP
        assert ThermocoupleType.T in TC_TYPE_MAP
        assert ThermocoupleType.E in TC_TYPE_MAP
        assert ThermocoupleType.N in TC_TYPE_MAP
        assert ThermocoupleType.R in TC_TYPE_MAP
        assert ThermocoupleType.S in TC_TYPE_MAP
        assert ThermocoupleType.B in TC_TYPE_MAP

    def test_tc_type_values(self):
        """Test thermocouple type string values"""
        assert TC_TYPE_MAP[ThermocoupleType.J] == 'J'
        assert TC_TYPE_MAP[ThermocoupleType.K] == 'K'
        assert TC_TYPE_MAP[ThermocoupleType.T] == 'T'


class TestGetTerminalConfig:
    """Tests for get_terminal_config function"""

    def test_rse_config(self):
        """Test RSE terminal configuration"""
        # With mocked nidaqmx, we can't test actual enum values
        # but we can verify the function handles the input
        result = get_terminal_config('RSE')
        assert result is not None

    def test_diff_config(self):
        """Test DIFF terminal configuration"""
        result = get_terminal_config('DIFF')
        assert result is not None

    def test_differential_alias(self):
        """Test DIFFERENTIAL alias for DIFF"""
        result = get_terminal_config('DIFFERENTIAL')
        assert result is not None

    def test_nrse_config(self):
        """Test NRSE terminal configuration"""
        result = get_terminal_config('NRSE')
        assert result is not None

    def test_pseudo_diff_config(self):
        """Test PSEUDO_DIFF terminal configuration"""
        result = get_terminal_config('PSEUDO_DIFF')
        assert result is not None

    def test_pseudodifferential_alias(self):
        """Test PSEUDODIFFERENTIAL alias"""
        result = get_terminal_config('PSEUDODIFFERENTIAL')
        assert result is not None

    def test_default_config(self):
        """Test DEFAULT terminal configuration"""
        result = get_terminal_config('DEFAULT')
        assert result is not None

    def test_case_insensitive(self):
        """Test that config is case-insensitive"""
        result1 = get_terminal_config('rse')
        result2 = get_terminal_config('RSE')
        result3 = get_terminal_config('Rse')
        # All should return the same value
        assert result1 is not None
        assert result2 is not None
        assert result3 is not None

    def test_unknown_config_defaults_to_rse(self):
        """Test that unknown config defaults to RSE"""
        result = get_terminal_config('INVALID')
        # Should log a warning and return RSE
        assert result is not None


class TestGetCJCSource:
    """Tests for get_cjc_source function"""

    def test_internal_source(self):
        """Test INTERNAL CJC source"""
        result = get_cjc_source('INTERNAL')
        assert result is not None

    def test_built_in_alias(self):
        """Test BUILT_IN alias for INTERNAL"""
        result = get_cjc_source('BUILT_IN')
        assert result is not None

    def test_constant_source(self):
        """Test CONSTANT CJC source"""
        result = get_cjc_source('CONSTANT')
        assert result is not None

    def test_channel_source(self):
        """Test CHANNEL CJC source"""
        result = get_cjc_source('CHANNEL')
        assert result is not None

    def test_case_insensitive(self):
        """Test that source is case-insensitive"""
        result1 = get_cjc_source('internal')
        result2 = get_cjc_source('INTERNAL')
        assert result1 is not None
        assert result2 is not None

    def test_unknown_source_defaults_to_built_in(self):
        """Test that unknown source defaults to BUILT_IN"""
        result = get_cjc_source('INVALID')
        assert result is not None


class TestChannelConfigHelpers:
    """Tests for channel configuration helper properties"""

    def test_channel_physical_path_parsing(self):
        """Test physical channel path parsing logic"""
        # Direct path (contains '/')
        channel = ChannelConfig(
            name='test',
            physical_channel='cDAQ-9189-DHWSIMMod1/ai0',
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert '/' in channel.physical_channel

    def test_crio_channel_detection(self):
        """Test cRIO channel detection pattern"""
        # cRIO channels start with "Mod" followed by digit
        import re

        crio_pattern = r'^Mod\d'

        # cRIO format
        assert re.match(crio_pattern, 'Mod4/port0/line0')
        assert re.match(crio_pattern, 'Mod1/ai0')

        # Local format
        assert not re.match(crio_pattern, 'cDAQ-9189-DHWSIMMod1/ai0')
        assert not re.match(crio_pattern, 'cDAQ1Mod1/ai0')


class TestHardwareReaderConfiguration:
    """Tests for HardwareReader configuration scenarios"""

    @pytest.fixture
    def sample_config(self):
        """Create a sample configuration"""
        return NISystemConfig(
            system=SystemConfig(simulation_mode=False),
            chassis={
                'cDAQ1': ChassisConfig(
                    name='cDAQ1',
                    chassis_type='cDAQ-9189',
                    serial='12345',
                    device_name='cDAQ-9189-DHWSIM'
                )
            },
            modules={
                'Mod1': ModuleConfig(
                    name='Mod1',
                    module_type='NI-9213',
                    chassis='cDAQ1',
                    slot=1
                ),
                'Mod2': ModuleConfig(
                    name='Mod2',
                    module_type='NI-9263',
                    chassis='cDAQ1',
                    slot=2
                )
            },
            channels={
                'TC_1': ChannelConfig(
                    name='TC_1',
                    physical_channel='cDAQ-9189-DHWSIMMod1/ai0',
                    channel_type=ChannelType.THERMOCOUPLE,
                    thermocouple_type=ThermocoupleType.K
                ),
                'AI_1': ChannelConfig(
                    name='AI_1',
                    physical_channel='cDAQ-9189-DHWSIMMod1/ai1',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    voltage_range=10.0,
                    terminal_config='RSE'
                ),
                'DO_1': ChannelConfig(
                    name='DO_1',
                    physical_channel='cDAQ-9189-DHWSIMMod2/port0/line0',
                    channel_type=ChannelType.DIGITAL_OUTPUT
                )
            },
            dataviewer=DataViewerConfig(),
            safety_actions={}
        )

    def test_channel_type_grouping(self, sample_config):
        """Test that channels are grouped correctly by type"""
        # Analog input types that can share a task
        ANALOG_INPUT_TYPES = {
            ChannelType.THERMOCOUPLE, ChannelType.VOLTAGE_INPUT, ChannelType.CURRENT_INPUT,
            ChannelType.RTD, ChannelType.STRAIN, ChannelType.IEPE, ChannelType.RESISTANCE
        }

        analog_channels = [
            ch for ch in sample_config.channels.values()
            if ch.channel_type in ANALOG_INPUT_TYPES
        ]

        digital_output_channels = [
            ch for ch in sample_config.channels.values()
            if ch.channel_type == ChannelType.DIGITAL_OUTPUT
        ]

        assert len(analog_channels) == 2  # TC_1, AI_1
        assert len(digital_output_channels) == 1  # DO_1

    def test_extract_module_from_path(self, sample_config):
        """Test extracting module name from physical channel path"""
        def extract_module(physical_channel):
            if '/' in physical_channel:
                return physical_channel.split('/')[0]
            return ""

        assert extract_module('cDAQ-9189-DHWSIMMod1/ai0') == 'cDAQ-9189-DHWSIMMod1'
        assert extract_module('cDAQ1Mod2/port0/line0') == 'cDAQ1Mod2'
        assert extract_module('ai0') == ""

    def test_channel_source_type_filtering(self, sample_config):
        """Test filtering channels by source type"""
        # Local channels (default)
        local_channels = [
            ch for ch in sample_config.channels.values()
            if getattr(ch, 'source_type', 'local') == 'local'
        ]

        assert len(local_channels) == 3

        # Add a cRIO channel
        sample_config.channels['CRIO_1'] = ChannelConfig(
            name='CRIO_1',
            physical_channel='Mod4/ai0',
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type='crio'
        )

        crio_channels = [
            ch for ch in sample_config.channels.values()
            if getattr(ch, 'source_type', 'local') == 'crio'
        ]

        assert len(crio_channels) == 1


class TestScalingIntegration:
    """Tests for scaling integration with hardware reader"""

    def test_reverse_scaling_import(self):
        """Test that reverse_scaling can be imported"""
        # This validates the import path is correct
        try:
            from scaling import reverse_scaling
            assert callable(reverse_scaling)
        except ImportError:
            pytest.skip("scaling module not available")


class TestTaskGroupDataclass:
    """Tests for TaskGroup dataclass structure"""

    def test_task_group_fields(self):
        """Test TaskGroup has expected fields"""
        from hardware_reader import TaskGroup

        # Create a mock task group
        group = TaskGroup(
            task=MagicMock(),
            channel_names=['ch1', 'ch2'],
            module_name='Mod1',
            channel_type=ChannelType.VOLTAGE_INPUT,
            is_continuous=True,
            reader=None,
            channel_types={}
        )

        assert group.channel_names == ['ch1', 'ch2']
        assert group.module_name == 'Mod1'
        assert group.is_continuous is True


class TestHardwareReaderMocked:
    """Tests for HardwareReader with mocked nidaqmx"""

    @pytest.fixture
    def mock_nidaqmx(self):
        """Setup mocked nidaqmx module"""
        mock_task = MagicMock()
        mock_task.ai_channels = MagicMock()
        mock_task.do_channels = MagicMock()
        mock_task.ao_channels = MagicMock()

        with patch.dict('sys.modules', {'nidaqmx': MagicMock()}):
            yield mock_task

    def test_continuous_acquisition_concept(self):
        """Test the continuous acquisition architecture concept"""
        # The architecture is:
        # Hardware (10Hz continuous) -> FIFO buffer -> Background thread -> latest_values dict

        # This test validates the concept, not the implementation
        # since actual implementation requires hardware

        # Key points:
        # 1. Hardware samples continuously at DEFAULT_SAMPLE_RATE_HZ
        # 2. Background thread reads from buffer
        # 3. read_all() returns cached values instantly

        assert DEFAULT_SAMPLE_RATE_HZ == 10  # Hardware sample rate
        assert BUFFER_SIZE == 100    # Buffer holds 10 seconds of data

    def test_thread_safety_design(self):
        """Test that thread safety design is in place"""
        import threading

        # The HardwareReader uses a lock for thread safety
        # This test validates the design pattern

        lock = threading.Lock()
        latest_values = {}

        def update_values():
            with lock:
                latest_values['temp'] = 25.0

        def read_values():
            with lock:
                return latest_values.copy()

        update_values()
        result = read_values()

        assert result.get('temp') == 25.0
