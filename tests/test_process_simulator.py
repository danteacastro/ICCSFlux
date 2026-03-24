"""
Tests for the Process Simulator — closed-loop physics models.

Tests all 6 process models (ThermalMass, FlowLoop, PressureVessel, LevelTank,
GenericFirstOrder, HeatExchanger) plus ProcessSimulator integration.
"""

import math
import sys
import os
import time
import pytest

# Add tools/ and services/daq_service/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from process_simulator import (
    ThermalMass, FlowLoop, PressureVessel, LevelTank,
    GenericFirstOrder, HeatExchanger, ProcessSimulator,
    ModelBinding, ProcessModel, MODEL_TYPES,
)

# ===== ThermalMass Tests =====

class TestThermalMass:
    def test_initial_temperature(self):
        m = ThermalMass('test', {'mass': 100, 'Cp': 500, 'UA': 10, 'T_ambient': 25})
        assert m.state['temperature'] == 25.0

    def test_custom_initial_temperature(self):
        m = ThermalMass('test', {'T_initial': 100, 'T_ambient': 25})
        assert m.state['temperature'] == 100.0

    def test_heating_increases_temperature(self):
        m = ThermalMass('test', {'mass': 10, 'Cp': 100, 'UA': 1, 'T_ambient': 25})
        initial = m.state['temperature']
        m.update(1.0, {'heater_power': 1000})
        assert m.state['temperature'] > initial

    def test_no_heat_decays_to_ambient(self):
        m = ThermalMass('test', {'mass': 10, 'Cp': 100, 'UA': 10, 'T_ambient': 25, 'T_initial': 100})
        # Time constant = m*Cp/UA = 100s; need ~5*tau = 500s to converge
        for _ in range(10000):
            m.update(0.1, {'heater_power': 0})
        assert abs(m.state['temperature'] - 25.0) < 1.0

    def test_steady_state_prediction(self):
        m = ThermalMass('test', {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 20})
        ss = m.steady_state_temperature(500)  # Q=500W, UA=5 => dT=100 => T=120
        assert abs(ss - 120.0) < 0.01

    def test_convergence_to_steady_state(self):
        m = ThermalMass('test', {'mass': 5, 'Cp': 100, 'UA': 5, 'T_ambient': 20})
        expected_ss = 20 + 1000 / 5  # 220
        # Time constant = m*Cp/UA = 100s; need ~5*tau = 500s
        for _ in range(10000):
            m.update(0.1, {'heater_power': 1000})
        assert abs(m.state['temperature'] - expected_ss) < 1.0

    def test_reset(self):
        m = ThermalMass('test', {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25})
        m.update(1.0, {'heater_power': 1000})
        assert m.state['temperature'] != 25.0
        m.reset()
        assert m.state['temperature'] == 25.0

    def test_zero_heat_input(self):
        m = ThermalMass('test', {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25})
        outputs = m.update(1.0, {})
        assert 'temperature' in outputs

    def test_get_state(self):
        m = ThermalMass('test', {'T_initial': 50})
        state = m.get_state()
        assert state == {'temperature': 50.0}

    def test_large_dt(self):
        """Large time steps should still produce reasonable values."""
        m = ThermalMass('test', {'mass': 100, 'Cp': 500, 'UA': 10, 'T_ambient': 25})
        m.update(100.0, {'heater_power': 500})
        assert m.state['temperature'] > 25.0
        assert m.state['temperature'] < 200.0  # Should not blow up

# ===== FlowLoop Tests =====

class TestFlowLoop:
    def test_zero_valve_zero_flow(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100, 'downstream_pressure': 0})
        outputs = m.update(0.1, {'valve_position': 0})
        assert outputs['flow_rate'] == 0.0

    def test_full_valve_max_flow(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100, 'downstream_pressure': 0})
        outputs = m.update(0.1, {'valve_position': 100})
        expected = 10 * 1.0 * math.sqrt(100)
        assert abs(outputs['flow_rate'] - expected) < 0.01

    def test_half_valve(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100, 'downstream_pressure': 0})
        outputs = m.update(0.1, {'valve_position': 50})
        expected = 10 * 0.5 * math.sqrt(100)
        assert abs(outputs['flow_rate'] - expected) < 0.01

    def test_valve_clamps_to_100(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100, 'downstream_pressure': 0})
        out1 = m.update(0.1, {'valve_position': 100})
        out2 = m.update(0.1, {'valve_position': 200})  # Should clamp
        assert out1['flow_rate'] == out2['flow_rate']

    def test_valve_clamps_to_0(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100})
        outputs = m.update(0.1, {'valve_position': -50})
        assert outputs['flow_rate'] == 0.0

    def test_no_pressure_diff_no_flow(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 50, 'downstream_pressure': 50})
        outputs = m.update(0.1, {'valve_position': 100})
        assert outputs['flow_rate'] == 0.0

    def test_reset(self):
        m = FlowLoop('test', {'Cv': 10, 'upstream_pressure': 100})
        m.update(0.1, {'valve_position': 50})
        m.reset()
        assert m.state['flow_rate'] == 0.0

# ===== PressureVessel Tests =====

class TestPressureVessel:
    def test_initial_pressure(self):
        m = PressureVessel('test', {'volume': 1, 'P_initial': 101325})
        assert m.state['pressure'] == 101325.0

    def test_flow_in_increases_pressure(self):
        m = PressureVessel('test', {'volume': 1, 'temperature': 300, 'R': 8.314})
        initial = m.state['pressure']
        m.update(1.0, {'flow_in': 10, 'flow_out': 0})
        assert m.state['pressure'] > initial

    def test_flow_out_decreases_pressure(self):
        m = PressureVessel('test', {'volume': 1, 'temperature': 300, 'P_initial': 200000})
        initial = m.state['pressure']
        m.update(1.0, {'flow_in': 0, 'flow_out': 10})
        assert m.state['pressure'] < initial

    def test_pressure_floor_at_zero(self):
        m = PressureVessel('test', {'volume': 0.001, 'P_initial': 100})
        m.update(100.0, {'flow_in': 0, 'flow_out': 1000})
        assert m.state['pressure'] >= 0.0

    def test_balanced_flow_constant_pressure(self):
        m = PressureVessel('test', {'volume': 1, 'P_initial': 101325})
        m.update(1.0, {'flow_in': 5, 'flow_out': 5})
        assert m.state['pressure'] == 101325.0

    def test_reset(self):
        m = PressureVessel('test', {'P_initial': 200000})
        m.update(1.0, {'flow_in': 100})
        m.reset()
        assert m.state['pressure'] == 200000.0

# ===== LevelTank Tests =====

class TestLevelTank:
    def test_initial_level(self):
        m = LevelTank('test', {'area': 1, 'max_level': 10, 'L_initial': 5})
        assert m.state['level'] == 5.0

    def test_fill_increases_level(self):
        m = LevelTank('test', {'area': 1, 'max_level': 10, 'L_initial': 0})
        m.update(1.0, {'flow_in': 2, 'flow_out': 0})
        assert m.state['level'] == 2.0

    def test_drain_decreases_level(self):
        m = LevelTank('test', {'area': 1, 'max_level': 10, 'L_initial': 5})
        m.update(1.0, {'flow_in': 0, 'flow_out': 2})
        assert m.state['level'] == 3.0

    def test_level_clamped_at_max(self):
        m = LevelTank('test', {'area': 1, 'max_level': 10, 'L_initial': 9})
        m.update(10.0, {'flow_in': 100, 'flow_out': 0})
        assert m.state['level'] == 10.0

    def test_level_clamped_at_zero(self):
        m = LevelTank('test', {'area': 1, 'max_level': 10, 'L_initial': 1})
        m.update(10.0, {'flow_in': 0, 'flow_out': 100})
        assert m.state['level'] == 0.0

    def test_fill_rate_with_area(self):
        """Level change = flow / area, so area=2 means half the level change."""
        m = LevelTank('test', {'area': 2, 'max_level': 100, 'L_initial': 0})
        m.update(1.0, {'flow_in': 4, 'flow_out': 0})
        assert m.state['level'] == 2.0  # 4/2 = 2

    def test_reset(self):
        m = LevelTank('test', {'L_initial': 3})
        m.update(1.0, {'flow_in': 10})
        m.reset()
        assert m.state['level'] == 3.0

# ===== GenericFirstOrder Tests =====

class TestGenericFirstOrder:
    def test_step_response(self):
        m = GenericFirstOrder('test', {'K': 2.0, 'tau': 1.0, 'y_initial': 0})
        # After many time constants, should approach K*u
        for _ in range(500):
            m.update(0.1, {'input': 5.0})
        assert abs(m.state['output'] - 10.0) < 0.1  # K*u = 2*5 = 10

    def test_zero_tau_instant_response(self):
        m = GenericFirstOrder('test', {'K': 3.0, 'tau': 0.0})
        outputs = m.update(0.1, {'input': 4.0})
        assert outputs['output'] == 12.0  # K*u = 3*4

    def test_initial_value(self):
        m = GenericFirstOrder('test', {'y_initial': 42.0})
        assert m.state['output'] == 42.0

    def test_no_input_decays_to_zero(self):
        m = GenericFirstOrder('test', {'K': 1.0, 'tau': 1.0, 'y_initial': 100})
        for _ in range(500):
            m.update(0.1, {'input': 0})
        assert abs(m.state['output']) < 0.1

    def test_time_constant_63pct(self):
        """After 1 time constant, response should be ~63.2% of final value."""
        m = GenericFirstOrder('test', {'K': 1.0, 'tau': 10.0, 'y_initial': 0})
        dt = 0.01
        for _ in range(1000):  # 10 seconds
            m.update(dt, {'input': 100.0})
        # Should be at ~63.2% of 100 = ~63.2
        assert abs(m.state['output'] - 63.2) < 2.0

    def test_reset(self):
        m = GenericFirstOrder('test', {'y_initial': 5})
        m.update(1.0, {'input': 100})
        m.reset()
        assert m.state['output'] == 5.0

# ===== HeatExchanger Tests =====

class TestHeatExchanger:
    def test_hot_cools_cold_heats(self):
        m = HeatExchanger('test', {'UA': 500, 'Cp_hot': 4186, 'Cp_cold': 4186})
        outputs = m.update(1.0, {
            'T_hot_in': 80, 'T_cold_in': 20,
            'flow_hot': 1.0, 'flow_cold': 1.0,
        })
        assert outputs['T_hot_out'] < 80
        assert outputs['T_cold_out'] > 20

    def test_equal_flows_symmetric(self):
        m = HeatExchanger('test', {'UA': 500, 'Cp_hot': 4186, 'Cp_cold': 4186})
        outputs = m.update(1.0, {
            'T_hot_in': 80, 'T_cold_in': 20,
            'flow_hot': 1.0, 'flow_cold': 1.0,
        })
        # Heat lost by hot side = heat gained by cold side
        dT_hot = 80 - outputs['T_hot_out']
        dT_cold = outputs['T_cold_out'] - 20
        assert abs(dT_hot - dT_cold) < 0.1

    def test_no_temp_diff_no_exchange(self):
        m = HeatExchanger('test', {'UA': 500})
        outputs = m.update(1.0, {
            'T_hot_in': 50, 'T_cold_in': 50,
            'flow_hot': 1.0, 'flow_cold': 1.0,
        })
        assert abs(outputs['T_hot_out'] - 50) < 0.1
        assert abs(outputs['T_cold_out'] - 50) < 0.1

    def test_high_ua_approaches_max_exchange(self):
        m = HeatExchanger('test', {'UA': 100000, 'Cp_hot': 4186, 'Cp_cold': 4186})
        outputs = m.update(1.0, {
            'T_hot_in': 80, 'T_cold_in': 20,
            'flow_hot': 1.0, 'flow_cold': 1.0,
        })
        # With very high UA and C_ratio=1: effectiveness = NTU/(1+NTU) ≈ 0.96
        # Near-complete exchange: hot exits near cold inlet, cold exits near hot inlet
        assert outputs['T_hot_out'] < 30  # Hot cools toward cold inlet temp
        assert outputs['T_cold_out'] > 70  # Cold heats toward hot inlet temp

    def test_reset(self):
        m = HeatExchanger('test', {})
        m.update(1.0, {'T_hot_in': 90, 'T_cold_in': 10, 'flow_hot': 1, 'flow_cold': 1})
        m.reset()
        assert m.state == {'T_hot_out': 25.0, 'T_cold_out': 25.0}

# ===== Model Registry Tests =====

class TestModelRegistry:
    def test_all_types_registered(self):
        assert 'thermalMass' in MODEL_TYPES
        assert 'flowLoop' in MODEL_TYPES
        assert 'pressureVessel' in MODEL_TYPES
        assert 'levelTank' in MODEL_TYPES
        assert 'genericFirstOrder' in MODEL_TYPES
        assert 'heatExchanger' in MODEL_TYPES

    def test_all_types_are_process_model(self):
        for name, cls in MODEL_TYPES.items():
            assert issubclass(cls, ProcessModel), f"{name} is not a ProcessModel"

# ===== ProcessSimulator Integration Tests =====

class TestProcessSimulator:
    @pytest.fixture
    def mock_config(self):
        """Create a minimal config for testing."""
        from config_parser import NISystemConfig, SystemConfig, ChannelConfig, ChannelType

        config = NISystemConfig(
            system=SystemConfig(simulation_mode=True),
            chassis={},
            modules={},
            channels={},
            safety_actions={},
        )

        # Add channels
        heater = ChannelConfig(
            name='HeaterOutput',
            physical_channel='Mod1/ao0',
            channel_type=ChannelType.VOLTAGE_OUTPUT,
        )
        heater.default_value = 0.0
        config.channels['HeaterOutput'] = heater

        temp = ChannelConfig(
            name='FurnaceTemp',
            physical_channel='Mod2/ai0',
            channel_type=ChannelType.THERMOCOUPLE,
        )
        config.channels['FurnaceTemp'] = temp

        valve = ChannelConfig(
            name='ValvePos',
            physical_channel='Mod1/ao1',
            channel_type=ChannelType.VOLTAGE_OUTPUT,
        )
        valve.default_value = 0.0
        config.channels['ValvePos'] = valve

        flow = ChannelConfig(
            name='FlowRate',
            physical_channel='Mod2/ai1',
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        config.channels['FlowRate'] = flow

        return config

    def test_constructor(self, mock_config):
        sim = ProcessSimulator(mock_config)
        assert len(sim.bindings) == 0

    def test_add_model_from_config(self, mock_config):
        sim = ProcessSimulator(mock_config)
        model = sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        })
        assert model is not None
        assert len(sim.bindings) == 1

    def test_unknown_model_type_raises(self, mock_config):
        sim = ProcessSimulator(mock_config)
        with pytest.raises(ValueError, match='Unknown process model type'):
            sim.add_model_from_config({'type': 'nonExistent'})

    def test_constructor_with_model_configs(self, mock_config):
        configs = [
            {
                'type': 'thermalMass',
                'name': 'Furnace',
                'inputChannels': {'heater_power': 'HeaterOutput'},
                'outputChannels': {'temperature': 'FurnaceTemp'},
                'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
            }
        ]
        sim = ProcessSimulator(mock_config, model_configs=configs)
        assert len(sim.bindings) == 1

    def test_step_models(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        })

        # Write heater power
        sim.write_channel('HeaterOutput', 500)
        sim.step_models(1.0)

        assert 'FurnaceTemp' in sim._output_overrides
        assert sim._output_overrides['FurnaceTemp'] > 25.0

    def test_read_all_includes_overrides(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        })

        sim.write_channel('HeaterOutput', 1000)
        values = sim.read_all()

        assert 'FurnaceTemp' in values
        assert 'HeaterOutput' in values

    def test_read_channel_uses_override(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25, 'T_initial': 50},
        })

        sim.step_models(0.0)
        val = sim.read_channel('FurnaceTemp')
        assert val is not None
        # Value is 50.0 + sensor noise (thermocouple noise_level=0.5)
        assert abs(val - 50.0) < 3.0

    def test_reset_models(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        })

        sim.write_channel('HeaterOutput', 1000)
        sim.step_models(10.0)
        assert sim._output_overrides.get('FurnaceTemp', 0) > 25.0

        sim.reset_models()
        assert len(sim._output_overrides) == 0
        assert sim.bindings[0].model.state['temperature'] == 25.0

    def test_get_model_states(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'T_initial': 42},
        })

        states = sim.get_model_states()
        assert 'Furnace' in states
        assert states['Furnace']['temperature'] == 42.0

    def test_multiple_models(self, mock_config):
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterOutput'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 10, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        })
        sim.add_model_from_config({
            'type': 'flowLoop',
            'name': 'CoolantFlow',
            'inputChannels': {'valve_position': 'ValvePos'},
            'outputChannels': {'flow_rate': 'FlowRate'},
            'params': {'Cv': 10, 'upstream_pressure': 100},
        })

        assert len(sim.bindings) == 2

        sim.write_channel('HeaterOutput', 500)
        sim.write_channel('ValvePos', 50)
        sim.step_models(1.0)

        assert 'FurnaceTemp' in sim._output_overrides
        assert 'FlowRate' in sim._output_overrides
        assert sim._output_overrides['FurnaceTemp'] > 25.0
        assert sim._output_overrides['FlowRate'] > 0.0

    def test_add_model_direct(self, mock_config):
        sim = ProcessSimulator(mock_config)
        model = ThermalMass('Direct', {'T_initial': 30})
        sim.add_model(model,
                      input_channels={'heater_power': 'HeaterOutput'},
                      output_channels={'temperature': 'FurnaceTemp'})
        assert len(sim.bindings) == 1
        assert sim.bindings[0].model is model

    def test_missing_input_channel_uses_zero(self, mock_config):
        """If input channel doesn't exist in simulator, use 0."""
        sim = ProcessSimulator(mock_config)
        sim.add_model_from_config({
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'NonExistentChannel'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'T_initial': 50, 'T_ambient': 25, 'UA': 5, 'mass': 10, 'Cp': 100},
        })
        sim.step_models(1.0)
        # With 0 power, temp should start cooling from 50 toward 25
        assert sim._output_overrides['FurnaceTemp'] < 50.0

# ===== Coupled System Test =====

class TestCoupledSystem:
    """Test a coupled multi-model system (furnace + coolant)."""

    @pytest.fixture
    def config(self):
        from config_parser import NISystemConfig, SystemConfig, ChannelConfig, ChannelType
        config = NISystemConfig(
            system=SystemConfig(simulation_mode=True),
            chassis={}, modules={}, channels={}, safety_actions={},
        )
        for name, ch_type, default in [
            ('HeaterPower', ChannelType.VOLTAGE_OUTPUT, 0.0),
            ('FurnaceTemp', ChannelType.THERMOCOUPLE, 0.0),
        ]:
            ch = ChannelConfig(name=name, physical_channel=f'sim/{name}', channel_type=ch_type)
            ch.default_value = default
            config.channels[name] = ch
        return config

    def test_heating_and_cooling_cycle(self, config):
        sim = ProcessSimulator(config, model_configs=[{
            'type': 'thermalMass',
            'name': 'Furnace',
            'inputChannels': {'heater_power': 'HeaterPower'},
            'outputChannels': {'temperature': 'FurnaceTemp'},
            'params': {'mass': 5, 'Cp': 100, 'UA': 5, 'T_ambient': 25},
        }])

        # Heat up (tau=100s, 50s of heating should reach ~40% of SS rise)
        sim.write_channel('HeaterPower', 2000)
        for _ in range(500):
            sim.step_models(0.1)

        hot_temp = sim._output_overrides['FurnaceTemp']
        assert hot_temp > 100  # Should have heated significantly

        # Cool down
        sim.write_channel('HeaterPower', 0)
        for _ in range(500):
            sim.step_models(0.1)

        cool_temp = sim._output_overrides['FurnaceTemp']
        assert cool_temp < hot_temp  # Should have cooled
