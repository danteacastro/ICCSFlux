"""
Configuration Save/Load Roundtrip Tests
Validates that all channel configuration fields can be saved and loaded correctly.
"""

import pytest
import sys
import tempfile
import configparser
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import (
    ChannelConfig, ChannelType, ThermocoupleType, NISystemConfig,
    SystemConfig, ChassisConfig, ModuleConfig, SafetyActionConfig,
    load_config
)


class TestChannelConfigFields:
    """Test that all ChannelConfig fields have correct defaults and can be set."""

    def test_basic_fields(self):
        """Test basic channel fields."""
        ch = ChannelConfig(
            name="test_channel",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE
        )
        assert ch.name == "test_channel"
        assert ch.module == "mod1"
        assert ch.physical_channel == "ai0"
        assert ch.channel_type == ChannelType.VOLTAGE
        assert ch.description == ""
        assert ch.units == ""
        assert ch.visible == True
        assert ch.group == ""

    def test_scaling_fields(self):
        """Test scaling-related fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            scale_slope=2.5,
            scale_offset=10.0,
            scale_type="linear"
        )
        assert ch.scale_slope == 2.5
        assert ch.scale_offset == 10.0
        assert ch.scale_type == "linear"

    def test_four_twenty_scaling(self):
        """Test 4-20mA scaling fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT,
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        assert ch.four_twenty_scaling == True
        assert ch.eng_units_min == 0.0
        assert ch.eng_units_max == 100.0

    def test_map_scaling(self):
        """Test map scaling fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=1000.0
        )
        assert ch.pre_scaled_min == 0.0
        assert ch.pre_scaled_max == 10.0
        assert ch.scaled_min == 0.0
        assert ch.scaled_max == 1000.0

    def test_thermocouple_fields(self):
        """Test thermocouple-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.THERMOCOUPLE,
            thermocouple_type=ThermocoupleType.K,
            cjc_source="internal"
        )
        assert ch.thermocouple_type == ThermocoupleType.K
        assert ch.cjc_source == "internal"

    def test_rtd_fields(self):
        """Test RTD-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.RTD,
            rtd_type="Pt100",
            rtd_resistance=100.0,
            rtd_wiring="4-wire",
            rtd_current=0.001
        )
        assert ch.rtd_type == "Pt100"
        assert ch.rtd_resistance == 100.0
        assert ch.rtd_wiring == "4-wire"
        assert ch.rtd_current == 0.001

    def test_strain_fields(self):
        """Test strain gauge-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.STRAIN,
            strain_config="full-bridge",
            strain_excitation_voltage=2.5,
            strain_gage_factor=2.0,
            strain_resistance=350.0
        )
        assert ch.strain_config == "full-bridge"
        assert ch.strain_excitation_voltage == 2.5
        assert ch.strain_gage_factor == 2.0
        assert ch.strain_resistance == 350.0

    def test_iepe_fields(self):
        """Test IEPE-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.IEPE,
            iepe_sensitivity=100.0,
            iepe_current=0.004,
            iepe_coupling="AC"
        )
        assert ch.iepe_sensitivity == 100.0
        assert ch.iepe_current == 0.004
        assert ch.iepe_coupling == "AC"

    def test_resistance_fields(self):
        """Test resistance-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.RESISTANCE,
            resistance_range=1000.0,
            resistance_wiring="4-wire"
        )
        assert ch.resistance_range == 1000.0
        assert ch.resistance_wiring == "4-wire"

    def test_counter_fields(self):
        """Test counter-specific fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ctr0",
            channel_type=ChannelType.COUNTER,
            counter_mode="frequency",
            pulses_per_unit=100.0,
            counter_edge="rising",
            counter_reset_on_read=False,
            counter_min_freq=0.1,
            counter_max_freq=1000.0
        )
        assert ch.counter_mode == "frequency"
        assert ch.pulses_per_unit == 100.0
        assert ch.counter_edge == "rising"
        assert ch.counter_reset_on_read == False
        assert ch.counter_min_freq == 0.1
        assert ch.counter_max_freq == 1000.0

    def test_terminal_config(self):
        """Test terminal configuration field."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            terminal_config="DIFF"
        )
        assert ch.terminal_config == "DIFF"

    def test_digital_io_fields(self):
        """Test digital I/O fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="port0/line0",
            channel_type=ChannelType.DIGITAL_OUTPUT,
            invert=True,
            default_state=True,
            default_value=1.0
        )
        assert ch.invert == True
        assert ch.default_state == True
        assert ch.default_value == 1.0

    def test_safety_fields(self):
        """Test safety-related fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            safety_action="emergency_stop",
            safety_interlock="door_closed"
        )
        assert ch.safety_action == "emergency_stop"
        assert ch.safety_interlock == "door_closed"

    def test_logging_fields(self):
        """Test logging-related fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            log=True,
            log_interval_ms=500
        )
        assert ch.log == True
        assert ch.log_interval_ms == 500

    def test_limit_fields(self):
        """Test limit and warning fields."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE,
            low_limit=0.0,
            high_limit=100.0,
            low_warning=10.0,
            high_warning=90.0
        )
        assert ch.low_limit == 0.0
        assert ch.high_limit == 100.0
        assert ch.low_warning == 10.0
        assert ch.high_warning == 90.0


class TestConfigRoundtrip:
    """Test saving and loading configuration preserves all fields."""

    @pytest.fixture
    def sample_config(self):
        """Create a sample configuration with all field types."""
        return NISystemConfig(
            system=SystemConfig(
                mqtt_broker="localhost",
                mqtt_port=1883,
                mqtt_base_topic="nisystem",
                scan_rate_hz=1.0,
                publish_rate_hz=1.0,
                simulation_mode=True,
                log_directory="./logs"
            ),
            chassis={
                "main_chassis": ChassisConfig(
                    name="main_chassis",
                    chassis_type="cDAQ-9178",
                    serial="12345678",
                    connection="USB",
                    description="Main cDAQ chassis",
                    enabled=True,
                    device_name="cDAQ1"
                )
            },
            modules={
                "temp_module": ModuleConfig(
                    name="temp_module",
                    module_type="NI-9213",
                    chassis="main_chassis",
                    slot=1,
                    description="Thermocouple module",
                    enabled=True
                ),
                "voltage_module": ModuleConfig(
                    name="voltage_module",
                    module_type="NI-9205",
                    chassis="main_chassis",
                    slot=2,
                    description="Voltage input module",
                    enabled=True
                )
            },
            channels={
                "temp_1": ChannelConfig(
                    name="temp_1",
                    module="temp_module",
                    physical_channel="ai0",
                    channel_type=ChannelType.THERMOCOUPLE,
                    description="Zone 1 Temperature",
                    units="C",
                    thermocouple_type=ThermocoupleType.K,
                    cjc_source="internal",
                    low_limit=0.0,
                    high_limit=500.0,
                    low_warning=50.0,
                    high_warning=450.0
                ),
                "voltage_1": ChannelConfig(
                    name="voltage_1",
                    module="voltage_module",
                    physical_channel="ai0",
                    channel_type=ChannelType.VOLTAGE,
                    description="Pressure Transducer",
                    units="PSI",
                    terminal_config="DIFF",
                    voltage_range=10.0,
                    scale_type="map",
                    pre_scaled_min=0.0,
                    pre_scaled_max=10.0,
                    scaled_min=0.0,
                    scaled_max=100.0
                ),
                "counter_1": ChannelConfig(
                    name="counter_1",
                    module="voltage_module",
                    physical_channel="ctr0",
                    channel_type=ChannelType.COUNTER,
                    description="Flow Totalizer",
                    units="gal",
                    counter_mode="count",
                    counter_edge="rising",
                    pulses_per_unit=100.0,
                    counter_min_freq=1.0,
                    counter_max_freq=500.0
                )
            },
            safety_actions={}
        )

    def test_save_and_load_config(self, sample_config, tmp_path):
        """Test that config can be saved and loaded without data loss."""
        config_file = tmp_path / "test_config.ini"

        # Save config to file
        self._save_config_to_file(sample_config, config_file)

        # Verify file was created
        assert config_file.exists()

        # Load config back
        loaded_config = load_config(str(config_file))

        # Verify system config
        assert loaded_config.system.mqtt_broker == sample_config.system.mqtt_broker
        assert loaded_config.system.mqtt_port == sample_config.system.mqtt_port
        assert loaded_config.system.simulation_mode == sample_config.system.simulation_mode

        # Verify chassis
        assert "main_chassis" in loaded_config.chassis
        assert loaded_config.chassis["main_chassis"].chassis_type == "cDAQ-9178"

        # Verify modules
        assert "temp_module" in loaded_config.modules
        assert loaded_config.modules["temp_module"].slot == 1

        # Verify thermocouple channel
        assert "temp_1" in loaded_config.channels
        ch = loaded_config.channels["temp_1"]
        assert ch.channel_type == ChannelType.THERMOCOUPLE
        assert ch.thermocouple_type == ThermocoupleType.K
        assert ch.cjc_source == "internal"
        assert ch.low_limit == 0.0
        assert ch.high_limit == 500.0

        # Verify voltage channel with scaling
        assert "voltage_1" in loaded_config.channels
        ch = loaded_config.channels["voltage_1"]
        assert ch.channel_type == ChannelType.VOLTAGE
        assert ch.terminal_config == "DIFF"
        assert ch.scale_type == "map"
        assert ch.pre_scaled_min == 0.0
        assert ch.pre_scaled_max == 10.0
        assert ch.scaled_min == 0.0
        assert ch.scaled_max == 100.0

        # Verify counter channel
        assert "counter_1" in loaded_config.channels
        ch = loaded_config.channels["counter_1"]
        assert ch.channel_type == ChannelType.COUNTER
        assert ch.counter_mode == "count"
        assert ch.counter_edge == "rising"
        assert ch.pulses_per_unit == 100.0
        assert ch.counter_min_freq == 1.0
        assert ch.counter_max_freq == 500.0

    def _save_config_to_file(self, config: NISystemConfig, path: Path):
        """Helper to save config to INI file (mirrors daq_service implementation)."""
        import configparser

        parser = configparser.ConfigParser()

        # System section
        parser['system'] = {
            'mqtt_broker': config.system.mqtt_broker,
            'mqtt_port': str(config.system.mqtt_port),
            'mqtt_base_topic': config.system.mqtt_base_topic,
            'scan_rate_hz': str(config.system.scan_rate_hz),
            'publish_rate_hz': str(config.system.publish_rate_hz),
            'simulation_mode': str(config.system.simulation_mode).lower(),
            'log_directory': config.system.log_directory
        }

        # Chassis sections
        for name, chassis in config.chassis.items():
            parser[f'chassis:{name}'] = {
                'type': chassis.chassis_type,
                'serial': chassis.serial,
                'connection': chassis.connection,
                'description': chassis.description,
                'enabled': str(chassis.enabled).lower()
            }
            if chassis.device_name:
                parser[f'chassis:{name}']['device_name'] = chassis.device_name

        # Module sections
        for name, module in config.modules.items():
            parser[f'module:{name}'] = {
                'type': module.module_type,
                'chassis': module.chassis,
                'slot': str(module.slot),
                'description': module.description,
                'enabled': str(module.enabled).lower()
            }

        # Channel sections
        for name, ch in config.channels.items():
            section = {
                'module': ch.module,
                'physical_channel': ch.physical_channel,
                'channel_type': ch.channel_type.value,
                'description': ch.description,
                'units': ch.units,
                'log': str(ch.log).lower()
            }

            # Add non-default fields
            if not ch.visible:
                section['visible'] = 'false'
            if ch.group:
                section['group'] = ch.group
            if ch.scale_slope != 1.0:
                section['scale_slope'] = str(ch.scale_slope)
            if ch.scale_offset != 0.0:
                section['scale_offset'] = str(ch.scale_offset)
            if ch.scale_type != 'none':
                section['scale_type'] = ch.scale_type
            if ch.four_twenty_scaling:
                section['four_twenty_scaling'] = 'true'
            if ch.eng_units_min is not None:
                section['eng_units_min'] = str(ch.eng_units_min)
            if ch.eng_units_max is not None:
                section['eng_units_max'] = str(ch.eng_units_max)
            if ch.pre_scaled_min is not None:
                section['pre_scaled_min'] = str(ch.pre_scaled_min)
            if ch.pre_scaled_max is not None:
                section['pre_scaled_max'] = str(ch.pre_scaled_max)
            if ch.scaled_min is not None:
                section['scaled_min'] = str(ch.scaled_min)
            if ch.scaled_max is not None:
                section['scaled_max'] = str(ch.scaled_max)
            if ch.low_limit is not None:
                section['low_limit'] = str(ch.low_limit)
            if ch.high_limit is not None:
                section['high_limit'] = str(ch.high_limit)
            if ch.low_warning is not None:
                section['low_warning'] = str(ch.low_warning)
            if ch.high_warning is not None:
                section['high_warning'] = str(ch.high_warning)
            if ch.thermocouple_type:
                section['thermocouple_type'] = ch.thermocouple_type.value
            if ch.cjc_source != 'internal':
                section['cjc_source'] = ch.cjc_source
            if ch.terminal_config != 'RSE':
                section['terminal_config'] = ch.terminal_config
            if ch.voltage_range != 10.0:
                section['voltage_range'] = str(ch.voltage_range)
            if ch.current_range_ma != 20.0:
                section['current_range_ma'] = str(ch.current_range_ma)
            # RTD
            if ch.rtd_type != 'Pt100':
                section['rtd_type'] = ch.rtd_type
            if ch.rtd_resistance != 100.0:
                section['rtd_resistance'] = str(ch.rtd_resistance)
            if ch.rtd_wiring != '4-wire':
                section['rtd_wiring'] = ch.rtd_wiring
            if ch.rtd_current != 0.001:
                section['rtd_current'] = str(ch.rtd_current)
            # Strain
            if ch.strain_config != 'full-bridge':
                section['strain_config'] = ch.strain_config
            if ch.strain_excitation_voltage != 2.5:
                section['strain_excitation_voltage'] = str(ch.strain_excitation_voltage)
            if ch.strain_gage_factor != 2.0:
                section['strain_gage_factor'] = str(ch.strain_gage_factor)
            if ch.strain_resistance != 350.0:
                section['strain_resistance'] = str(ch.strain_resistance)
            # IEPE
            if ch.iepe_sensitivity != 100.0:
                section['iepe_sensitivity'] = str(ch.iepe_sensitivity)
            if ch.iepe_current != 0.004:
                section['iepe_current'] = str(ch.iepe_current)
            if ch.iepe_coupling != 'AC':
                section['iepe_coupling'] = ch.iepe_coupling
            # Resistance
            if ch.resistance_range != 1000.0:
                section['resistance_range'] = str(ch.resistance_range)
            if ch.resistance_wiring != '4-wire':
                section['resistance_wiring'] = ch.resistance_wiring
            # Counter
            if ch.counter_mode != 'frequency':
                section['counter_mode'] = ch.counter_mode
            if ch.pulses_per_unit != 1.0:
                section['pulses_per_unit'] = str(ch.pulses_per_unit)
            if ch.counter_edge != 'rising':
                section['counter_edge'] = ch.counter_edge
            if ch.counter_reset_on_read:
                section['counter_reset_on_read'] = 'true'
            if ch.counter_min_freq != 0.1:
                section['counter_min_freq'] = str(ch.counter_min_freq)
            if ch.counter_max_freq != 1000.0:
                section['counter_max_freq'] = str(ch.counter_max_freq)
            # Digital I/O
            if ch.invert:
                section['invert'] = 'true'
            if ch.default_state:
                section['default_state'] = 'true'
            if ch.default_value != 0.0:
                section['default_value'] = str(ch.default_value)
            if ch.log_interval_ms != 1000:
                section['log_interval_ms'] = str(ch.log_interval_ms)
            if ch.safety_action:
                section['safety_action'] = ch.safety_action
            if ch.safety_interlock:
                section['safety_interlock'] = ch.safety_interlock

            parser[f'channel:{name}'] = section

        with open(path, 'w') as f:
            parser.write(f)


class TestAllChannelTypes:
    """Test that all channel types can be created and have correct defaults."""

    @pytest.mark.parametrize("channel_type", [
        ChannelType.THERMOCOUPLE,
        ChannelType.VOLTAGE,
        ChannelType.CURRENT,
        ChannelType.RTD,
        ChannelType.STRAIN,
        ChannelType.IEPE,
        ChannelType.RESISTANCE,
        ChannelType.COUNTER,
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.ANALOG_OUTPUT
    ])
    def test_channel_type_creation(self, channel_type):
        """Test that each channel type can be created with defaults."""
        ch = ChannelConfig(
            name=f"test_{channel_type.value}",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type
        )
        assert ch.channel_type == channel_type
        assert ch.name == f"test_{channel_type.value}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
