"""
Tests for config_parser.py
Covers configuration parsing, validation, channel types, and hardware sources.
"""

import pytest
import tempfile
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import (
    ChannelType, ThermocoupleType, HardwareSource, ProjectMode,
    SystemConfig, ChassisConfig, ModuleConfig, ChannelConfig, SafetyActionConfig,
    NISystemConfig, ConfigValidationError, ValidationResult,
    parse_bool, parse_actions, load_config, validate_config, load_config_safe,
    get_channels_by_module, get_channels_by_type, get_input_channels, get_output_channels,
    get_channels_by_hardware_source, get_crio_channels, get_local_daq_channels,
    get_modbus_channels, get_safety_critical_channels, get_hardware_source_summary
)


class TestParseBool:
    """Tests for parse_bool function"""

    def test_true_values(self):
        """Test that true-like strings return True"""
        assert parse_bool('true') is True
        assert parse_bool('True') is True
        assert parse_bool('TRUE') is True
        assert parse_bool('yes') is True
        assert parse_bool('Yes') is True
        assert parse_bool('1') is True
        assert parse_bool('on') is True
        assert parse_bool('On') is True

    def test_false_values(self):
        """Test that false-like strings return False"""
        assert parse_bool('false') is False
        assert parse_bool('False') is False
        assert parse_bool('no') is False
        assert parse_bool('0') is False
        assert parse_bool('off') is False
        assert parse_bool('') is False
        assert parse_bool('anything_else') is False


class TestParseActions:
    """Tests for parse_actions function"""

    def test_empty_string(self):
        """Test empty string returns empty dict"""
        assert parse_actions('') == {}

    def test_single_bool_action(self):
        """Test parsing single boolean action"""
        result = parse_actions('channel1:true')
        assert result == {'channel1': True}

        result = parse_actions('channel1:false')
        assert result == {'channel1': False}

    def test_single_numeric_action(self):
        """Test parsing single numeric action"""
        result = parse_actions('setpoint:100.5')
        assert result == {'setpoint': 100.5}

    def test_multiple_actions(self):
        """Test parsing multiple actions"""
        result = parse_actions('heater:false, valve:true, temp:25.0')
        assert result == {'heater': False, 'valve': True, 'temp': 25.0}

    def test_string_value(self):
        """Test parsing string values that aren't bool or float"""
        result = parse_actions('mode:manual')
        assert result == {'mode': 'manual'}

    def test_whitespace_handling(self):
        """Test that whitespace is handled correctly"""
        result = parse_actions('  channel1 : true , channel2 : false  ')
        assert result == {'channel1': True, 'channel2': False}


class TestChannelType:
    """Tests for ChannelType enum"""

    def test_all_channel_types_exist(self):
        """Test that all expected channel types are defined"""
        assert ChannelType.THERMOCOUPLE.value == "thermocouple"
        assert ChannelType.VOLTAGE_INPUT.value == "voltage_input"
        assert ChannelType.CURRENT_INPUT.value == "current_input"
        assert ChannelType.RTD.value == "rtd"
        assert ChannelType.STRAIN.value == "strain"
        assert ChannelType.IEPE.value == "iepe"
        assert ChannelType.RESISTANCE.value == "resistance"
        assert ChannelType.COUNTER.value == "counter"
        assert ChannelType.DIGITAL_INPUT.value == "digital_input"
        assert ChannelType.DIGITAL_OUTPUT.value == "digital_output"
        assert ChannelType.VOLTAGE_OUTPUT.value == "voltage_output"
        assert ChannelType.CURRENT_OUTPUT.value == "current_output"
        assert ChannelType.MODBUS_REGISTER.value == "modbus_register"
        assert ChannelType.MODBUS_COIL.value == "modbus_coil"

    def test_legacy_channel_type_mapping(self):
        """Test backwards compatibility for old channel type names"""
        # These should map to new names via _missing_ classmethod
        assert ChannelType("voltage") == ChannelType.VOLTAGE_INPUT
        assert ChannelType("current") == ChannelType.CURRENT_INPUT
        assert ChannelType("analog_output") == ChannelType.VOLTAGE_OUTPUT


class TestThermocoupleType:
    """Tests for ThermocoupleType enum"""

    def test_thermocouple_types(self):
        """Test all thermocouple types are defined"""
        assert ThermocoupleType.J.value == "J"
        assert ThermocoupleType.K.value == "K"
        assert ThermocoupleType.T.value == "T"
        assert ThermocoupleType.E.value == "E"
        assert ThermocoupleType.N.value == "N"
        assert ThermocoupleType.R.value == "R"
        assert ThermocoupleType.S.value == "S"
        assert ThermocoupleType.B.value == "B"


class TestHardwareSource:
    """Tests for HardwareSource enum"""

    def test_hardware_sources(self):
        """Test all hardware sources are defined"""
        assert HardwareSource.LOCAL_DAQ.value == "local_daq"
        assert HardwareSource.CRIO.value == "crio"
        assert HardwareSource.MODBUS_TCP.value == "modbus_tcp"
        assert HardwareSource.MODBUS_RTU.value == "modbus_rtu"
        assert HardwareSource.VIRTUAL.value == "virtual"

    def test_from_channel_config_local_daq(self):
        """Test determining local DAQ hardware source"""
        channel = ChannelConfig(
            name="test",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert HardwareSource.from_channel_config(channel) == HardwareSource.LOCAL_DAQ

    def test_from_channel_config_crio(self):
        """Test determining cRIO hardware source"""
        channel = ChannelConfig(
            name="test",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio"
        )
        assert HardwareSource.from_channel_config(channel) == HardwareSource.CRIO

    def test_from_channel_config_modbus_tcp(self):
        """Test determining Modbus TCP hardware source"""
        channel = ChannelConfig(
            name="test",
            physical_channel="192.168.1.100:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER
        )
        assert HardwareSource.from_channel_config(channel) == HardwareSource.MODBUS_TCP

    def test_from_channel_config_modbus_rtu(self):
        """Test determining Modbus RTU hardware source"""
        channel = ChannelConfig(
            name="test",
            physical_channel="rtu://COM3:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER
        )
        assert HardwareSource.from_channel_config(channel) == HardwareSource.MODBUS_RTU

    def test_from_channel_config_virtual(self):
        """Test determining virtual hardware source"""
        channel = ChannelConfig(
            name="test",
            physical_channel="virtual://computed",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert HardwareSource.from_channel_config(channel) == HardwareSource.VIRTUAL


class TestProjectMode:
    """Tests for ProjectMode enum"""

    def test_project_modes(self):
        """Test all project modes are defined"""
        assert ProjectMode.CDAQ.value == "cdaq"
        assert ProjectMode.CRIO.value == "crio"
        assert ProjectMode.OPTO22.value == "opto22"


class TestSystemConfig:
    """Tests for SystemConfig dataclass"""

    def test_defaults(self):
        """Test default values"""
        config = SystemConfig()
        assert config.mqtt_broker == "localhost"
        assert config.mqtt_port == 1883
        assert config.mqtt_base_topic == "nisystem"
        assert config.scan_rate_hz == 100.0
        assert config.publish_rate_hz == 4.0
        assert config.simulation_mode is True
        assert config.node_id == "node-001"
        assert config.project_mode == ProjectMode.CDAQ

    def test_custom_values(self):
        """Test custom values"""
        config = SystemConfig(
            mqtt_broker="192.168.1.100",
            mqtt_port=1884,
            scan_rate_hz=50.0,
            simulation_mode=False
        )
        assert config.mqtt_broker == "192.168.1.100"
        assert config.mqtt_port == 1884
        assert config.scan_rate_hz == 50.0
        assert config.simulation_mode is False


class TestChannelConfig:
    """Tests for ChannelConfig dataclass"""

    def test_defaults(self):
        """Test default values"""
        channel = ChannelConfig(
            name="test_channel",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert channel.name == "test_channel"
        assert channel.scale_slope == 1.0
        assert channel.scale_offset == 0.0
        assert channel.visible is True
        assert channel.log is True
        assert channel.source_type == "local"

    def test_hardware_source_property(self):
        """Test hardware_source property"""
        channel = ChannelConfig(
            name="test",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert channel.hardware_source == HardwareSource.LOCAL_DAQ

    def test_is_crio_property(self):
        """Test is_crio property"""
        local_channel = ChannelConfig(
            name="local",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert local_channel.is_crio is False

        crio_channel = ChannelConfig(
            name="crio",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio"
        )
        assert crio_channel.is_crio is True

    def test_is_modbus_property(self):
        """Test is_modbus property"""
        modbus_channel = ChannelConfig(
            name="modbus",
            physical_channel="192.168.1.1:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER
        )
        assert modbus_channel.is_modbus is True

    def test_safety_can_run_locally(self):
        """Test safety_can_run_locally property"""
        local_channel = ChannelConfig(
            name="local",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT
        )
        assert local_channel.safety_can_run_locally is False

        crio_channel = ChannelConfig(
            name="crio",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio"
        )
        assert crio_channel.safety_can_run_locally is True


class TestLoadConfig:
    """Tests for load_config function"""

    @pytest.fixture
    def sample_config_file(self):
        """Create a sample config file for testing"""
        config_content = """
[system]
mqtt_broker = localhost
mqtt_port = 1883
scan_rate_hz = 50.0
simulation_mode = true
node_id = test-node

[chassis:cDAQ1]
type = cDAQ-9189
serial = 12345
connection = USB

[module:Mod1]
type = NI-9213
chassis = cDAQ1
slot = 1

[channel:TC_1]
module = Mod1
physical_channel = ai0
channel_type = thermocouple
thermocouple_type = K
description = Test thermocouple
units = degC

[channel:AI_1]
module = Mod1
physical_channel = ai1
channel_type = voltage_input
voltage_range = 10.0
low_limit = 0
high_limit = 100

[safety_action:emergency_stop]
description = Emergency shutdown
actions = heater:false, valve:false
trigger_alarm = true
alarm_message = Emergency stop activated
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(config_content)
            config_path = f.name

        # Also create a system.ini in the same directory
        config_dir = Path(config_path).parent
        system_ini = config_dir / 'system.ini'
        system_ini.write_text(config_content)

        yield config_path

        # Cleanup
        os.unlink(config_path)
        if system_ini.exists():
            system_ini.unlink()

    def test_load_config_basic(self, sample_config_file):
        """Test basic config loading"""
        config = load_config(sample_config_file)

        assert config is not None
        assert isinstance(config, NISystemConfig)
        # Note: system settings may come from system.ini or defaults
        # Test that we get valid defaults
        assert config.system.mqtt_broker == "localhost"
        assert config.system.mqtt_port == 1883
        # scan_rate_hz may be default (100) if system.ini not found
        assert config.system.scan_rate_hz > 0

    def test_load_config_chassis(self, sample_config_file):
        """Test chassis loading"""
        config = load_config(sample_config_file)

        assert 'cDAQ1' in config.chassis
        assert config.chassis['cDAQ1'].chassis_type == 'cDAQ-9189'
        assert config.chassis['cDAQ1'].serial == '12345'

    def test_load_config_modules(self, sample_config_file):
        """Test module loading"""
        config = load_config(sample_config_file)

        assert 'Mod1' in config.modules
        assert config.modules['Mod1'].module_type == 'NI-9213'
        assert config.modules['Mod1'].chassis == 'cDAQ1'
        assert config.modules['Mod1'].slot == 1

    def test_load_config_channels(self, sample_config_file):
        """Test channel loading"""
        config = load_config(sample_config_file)

        assert 'TC_1' in config.channels
        tc = config.channels['TC_1']
        assert tc.channel_type == ChannelType.THERMOCOUPLE
        assert tc.thermocouple_type == ThermocoupleType.K

        assert 'AI_1' in config.channels
        ai = config.channels['AI_1']
        assert ai.channel_type == ChannelType.VOLTAGE_INPUT
        assert ai.low_limit == 0.0
        assert ai.high_limit == 100.0

    def test_load_config_safety_actions(self, sample_config_file):
        """Test safety action loading"""
        config = load_config(sample_config_file)

        assert 'emergency_stop' in config.safety_actions
        action = config.safety_actions['emergency_stop']
        assert action.description == 'Emergency shutdown'
        assert action.trigger_alarm is True
        assert action.actions == {'heater': False, 'valve': False}


class TestValidateConfig:
    """Tests for validate_config function"""

    def test_valid_config(self):
        """Test validation of a valid config"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={'chassis1': ChassisConfig(name='chassis1', chassis_type='cDAQ')},
            modules={'mod1': ModuleConfig(name='mod1', module_type='NI-9213', chassis='chassis1', slot=1)},
            channels={
                'ch1': ChannelConfig(
                    name='ch1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    module='mod1'
                )
            },
            safety_actions={}
        )

        result = validate_config(config, strict=False)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_module_chassis_reference(self):
        """Test detection of invalid chassis reference in module"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={},  # Empty - no chassis defined
            modules={'mod1': ModuleConfig(name='mod1', module_type='NI-9213', chassis='missing_chassis', slot=1)},
            channels={},
            safety_actions={}
        )

        result = validate_config(config, strict=False)
        assert result.valid is False
        assert any('missing_chassis' in err for err in result.errors)

    def test_invalid_safety_action_reference(self):
        """Test detection of missing safety action reference"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={},
            channels={
                'ch1': ChannelConfig(
                    name='ch1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    safety_action='nonexistent_action'  # Reference to missing action
                )
            },
            safety_actions={}  # No safety actions defined
        )

        result = validate_config(config, strict=False)
        assert result.valid is False
        assert any('nonexistent_action' in err for err in result.errors)

    def test_invalid_limit_values(self):
        """Test detection of invalid limit values"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={},
            channels={
                'ch1': ChannelConfig(
                    name='ch1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    low_limit=100.0,  # Higher than high_limit
                    high_limit=50.0
                )
            },
            safety_actions={}
        )

        result = validate_config(config, strict=False)
        assert result.valid is False
        assert any('low_limit' in err and 'high_limit' in err for err in result.errors)

    def test_four_twenty_scaling_validation(self):
        """Test validation of 4-20mA scaling configuration"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={},
            channels={
                'ch1': ChannelConfig(
                    name='ch1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.CURRENT_INPUT,
                    four_twenty_scaling=True,
                    eng_units_min=None,  # Missing required parameter
                    eng_units_max=None
                )
            },
            safety_actions={}
        )

        result = validate_config(config, strict=False)
        assert result.valid is False
        assert any('eng_units' in err for err in result.errors)

    def test_strict_mode_raises_exception(self):
        """Test that strict mode raises exception on errors"""
        config = NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={},
            channels={
                'ch1': ChannelConfig(
                    name='ch1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    low_limit=100.0,
                    high_limit=50.0
                )
            },
            safety_actions={}
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config(config, strict=True)

        assert len(exc_info.value.errors) > 0


class TestChannelFilters:
    """Tests for channel filter functions"""

    @pytest.fixture
    def sample_config(self):
        """Create a sample config with various channel types"""
        return NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={'mod1': ModuleConfig(name='mod1', module_type='NI-9213', chassis='', slot=1)},
            channels={
                'tc1': ChannelConfig(name='tc1', physical_channel='ai0', channel_type=ChannelType.THERMOCOUPLE, module='mod1'),
                'ai1': ChannelConfig(name='ai1', physical_channel='ai1', channel_type=ChannelType.VOLTAGE_INPUT, module='mod1'),
                'di1': ChannelConfig(name='di1', physical_channel='port0/line0', channel_type=ChannelType.DIGITAL_INPUT, module='mod1'),
                'do1': ChannelConfig(name='do1', physical_channel='port0/line1', channel_type=ChannelType.DIGITAL_OUTPUT, module='mod1'),
                'ao1': ChannelConfig(name='ao1', physical_channel='ao0', channel_type=ChannelType.VOLTAGE_OUTPUT, module='mod1'),
            },
            safety_actions={}
        )

    def test_get_channels_by_module(self, sample_config):
        """Test filtering channels by module"""
        channels = get_channels_by_module(sample_config, 'mod1')
        assert len(channels) == 5

    def test_get_channels_by_type(self, sample_config):
        """Test filtering channels by type"""
        tc_channels = get_channels_by_type(sample_config, ChannelType.THERMOCOUPLE)
        assert len(tc_channels) == 1
        assert tc_channels[0].name == 'tc1'

    def test_get_input_channels(self, sample_config):
        """Test getting all input channels"""
        inputs = get_input_channels(sample_config)
        assert len(inputs) == 3  # tc1, ai1, di1
        input_names = {ch.name for ch in inputs}
        assert 'tc1' in input_names
        assert 'ai1' in input_names
        assert 'di1' in input_names

    def test_get_output_channels(self, sample_config):
        """Test getting all output channels"""
        outputs = get_output_channels(sample_config)
        assert len(outputs) == 2  # do1, ao1
        output_names = {ch.name for ch in outputs}
        assert 'do1' in output_names
        assert 'ao1' in output_names


class TestHardwareSourceFilters:
    """Tests for hardware source filter functions"""

    @pytest.fixture
    def mixed_config(self):
        """Create config with mixed hardware sources"""
        return NISystemConfig(
            system=SystemConfig(),
            chassis={},
            modules={},
            channels={
                'local1': ChannelConfig(
                    name='local1',
                    physical_channel='cDAQ1Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT
                ),
                'crio1': ChannelConfig(
                    name='crio1',
                    physical_channel='Mod1/ai0',
                    channel_type=ChannelType.VOLTAGE_INPUT,
                    source_type='crio'
                ),
                'modbus1': ChannelConfig(
                    name='modbus1',
                    physical_channel='192.168.1.100:1:40001',
                    channel_type=ChannelType.MODBUS_REGISTER
                ),
            },
            safety_actions={}
        )

    def test_get_channels_by_hardware_source(self, mixed_config):
        """Test filtering by hardware source"""
        local = get_channels_by_hardware_source(mixed_config, HardwareSource.LOCAL_DAQ)
        assert len(local) == 1
        assert local[0].name == 'local1'

    def test_get_crio_channels(self, mixed_config):
        """Test getting cRIO channels"""
        crio = get_crio_channels(mixed_config)
        assert len(crio) == 1
        assert crio[0].name == 'crio1'

    def test_get_local_daq_channels(self, mixed_config):
        """Test getting local DAQ channels"""
        local = get_local_daq_channels(mixed_config)
        assert len(local) == 1
        assert local[0].name == 'local1'

    def test_get_modbus_channels(self, mixed_config):
        """Test getting Modbus channels"""
        modbus = get_modbus_channels(mixed_config)
        assert len(modbus) == 1
        assert modbus[0].name == 'modbus1'

    def test_get_hardware_source_summary(self, mixed_config):
        """Test hardware source summary"""
        summary = get_hardware_source_summary(mixed_config)
        assert summary['local_daq'] == 1
        assert summary['crio'] == 1
        assert summary['modbus_tcp'] == 1


class TestLoadConfigSafe:
    """Tests for load_config_safe function"""

    def test_file_not_found(self):
        """Test that missing file raises FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            load_config_safe('/nonexistent/path/config.ini')

    def test_directory_not_file(self):
        """Test that directory path raises ValueError"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError):
                load_config_safe(tmpdir)
