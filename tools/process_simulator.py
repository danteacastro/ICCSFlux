"""
Process Simulator — Closed-loop physics-based simulation for NISystem.

Subclasses HardwareSimulator to add coupled process dynamics: outputs (AO channels)
affect inputs (AI channels) through physics models (thermal mass, flow loop, etc.).

Usage:
    Configured via project JSON under "simulation.processModels":
    {
        "simulation": {
            "processModels": [
                {
                    "type": "thermalMass",
                    "name": "Furnace",
                    "inputChannels": {"heater_power": "HeaterOutput"},
                    "outputChannels": {"temperature": "FurnaceTemp"},
                    "params": {"mass": 100, "Cp": 500, "UA": 10, "T_ambient": 25}
                }
            ]
        }
    }
"""

import logging
import math
import random
import time
from typing import Dict, List, Any, Optional, Tuple

# Allow running standalone or from daq_service context
try:
    from simulator import HardwareSimulator
    from config_parser import NISystemConfig
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))
    from simulator import HardwareSimulator
    from config_parser import NISystemConfig

logger = logging.getLogger('ProcessSimulator')


# ---------------------------------------------------------------------------
# Process Models
# ---------------------------------------------------------------------------

class ProcessModel:
    """Base class for all process models."""

    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = dict(params)
        self.state: Dict[str, float] = {}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        """Advance the model by dt seconds. Returns output values."""
        raise NotImplementedError

    def reset(self):
        """Reset model to initial conditions."""
        raise NotImplementedError

    def get_state(self) -> Dict[str, float]:
        """Return current internal state for inspection."""
        return dict(self.state)


class ThermalMass(ProcessModel):
    """
    Lumped thermal mass model.

    dT/dt = (Q_in - UA * (T - T_ambient)) / (m * Cp)

    Inputs:  heater_power (W)
    Outputs: temperature (degC)
    Params:  mass (kg), Cp (J/kg·K), UA (W/K), T_ambient (degC), T_initial (degC, optional)
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.mass = float(params.get('mass', 100.0))
        self.Cp = float(params.get('Cp', 500.0))
        self.UA = float(params.get('UA', 10.0))
        self.T_ambient = float(params.get('T_ambient', 25.0))
        self.T_initial = float(params.get('T_initial', self.T_ambient))
        self.state = {'temperature': self.T_initial}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        Q_in = inputs.get('heater_power', 0.0)
        T = self.state['temperature']
        dTdt = (Q_in - self.UA * (T - self.T_ambient)) / (self.mass * self.Cp)
        self.state['temperature'] = T + dTdt * dt
        return {'temperature': self.state['temperature']}

    def reset(self):
        self.state = {'temperature': self.T_initial}

    def steady_state_temperature(self, Q_in: float) -> float:
        """Calculate the steady-state temperature for a given heat input."""
        return self.T_ambient + Q_in / self.UA


class FlowLoop(ProcessModel):
    """
    Valve + flow model using Cv equation.

    flow = Cv * (valve_pct / 100) * sqrt(dP)

    Inputs:  valve_position (0-100%)
    Outputs: flow_rate (units depend on Cv)
    Params:  Cv, upstream_pressure, downstream_pressure
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.Cv = float(params.get('Cv', 10.0))
        self.upstream_pressure = float(params.get('upstream_pressure', 100.0))
        self.downstream_pressure = float(params.get('downstream_pressure', 0.0))
        self.state = {'flow_rate': 0.0}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        valve_pct = max(0.0, min(100.0, inputs.get('valve_position', 0.0)))
        dP = max(0.0, self.upstream_pressure - self.downstream_pressure)
        self.state['flow_rate'] = self.Cv * (valve_pct / 100.0) * math.sqrt(dP)
        return {'flow_rate': self.state['flow_rate']}

    def reset(self):
        self.state = {'flow_rate': 0.0}


class PressureVessel(ProcessModel):
    """
    Ideal gas pressure vessel.

    dP/dt = (flow_in - flow_out) * R * T / V

    Inputs:  flow_in, flow_out (volumetric or mass flow)
    Outputs: pressure
    Params:  volume (m³), temperature (K), R (gas constant factor), P_initial (Pa)
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.volume = float(params.get('volume', 1.0))
        self.temperature = float(params.get('temperature', 300.0))  # K
        self.R = float(params.get('R', 8.314))
        self.P_initial = float(params.get('P_initial', 101325.0))
        self.state = {'pressure': self.P_initial}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        flow_in = inputs.get('flow_in', 0.0)
        flow_out = inputs.get('flow_out', 0.0)
        P = self.state['pressure']
        dPdt = (flow_in - flow_out) * self.R * self.temperature / self.volume
        self.state['pressure'] = max(0.0, P + dPdt * dt)
        return {'pressure': self.state['pressure']}

    def reset(self):
        self.state = {'pressure': self.P_initial}


class LevelTank(ProcessModel):
    """
    Simple tank level model.

    dL/dt = (flow_in - flow_out) / area

    Inputs:  flow_in, flow_out
    Outputs: level
    Params:  area (m²), max_level (m), L_initial (m)
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.area = float(params.get('area', 1.0))
        self.max_level = float(params.get('max_level', 10.0))
        self.L_initial = float(params.get('L_initial', 0.0))
        self.state = {'level': self.L_initial}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        flow_in = inputs.get('flow_in', 0.0)
        flow_out = inputs.get('flow_out', 0.0)
        L = self.state['level']
        dLdt = (flow_in - flow_out) / self.area
        self.state['level'] = max(0.0, min(self.max_level, L + dLdt * dt))
        return {'level': self.state['level']}

    def reset(self):
        self.state = {'level': self.L_initial}


class GenericFirstOrder(ProcessModel):
    """
    Generic first-order transfer function.

    dy/dt = (K * u - y) / tau

    Inputs:  input (any signal)
    Outputs: output
    Params:  K (gain), tau (time constant, s), y_initial
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.K = float(params.get('K', 1.0))
        self.tau = float(params.get('tau', 10.0))
        self.y_initial = float(params.get('y_initial', 0.0))
        self.state = {'output': self.y_initial}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        u = inputs.get('input', 0.0)
        y = self.state['output']
        if self.tau > 0:
            dydt = (self.K * u - y) / self.tau
            self.state['output'] = y + dydt * dt
        else:
            self.state['output'] = self.K * u
        return {'output': self.state['output']}

    def reset(self):
        self.state = {'output': self.y_initial}


class HeatExchanger(ProcessModel):
    """
    Counter-flow heat exchanger (effectiveness-NTU method simplified).

    Q = effectiveness * C_min * (T_hot_in - T_cold_in)

    Inputs:  T_hot_in, T_cold_in, flow_hot, flow_cold
    Outputs: T_hot_out, T_cold_out
    Params:  UA (W/K), Cp_hot (J/kg·K), Cp_cold (J/kg·K)
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        super().__init__(name, params)
        self.UA = float(params.get('UA', 500.0))
        self.Cp_hot = float(params.get('Cp_hot', 4186.0))
        self.Cp_cold = float(params.get('Cp_cold', 4186.0))
        self.state = {'T_hot_out': 25.0, 'T_cold_out': 25.0}

    def update(self, dt: float, inputs: Dict[str, float]) -> Dict[str, float]:
        T_hot_in = inputs.get('T_hot_in', 80.0)
        T_cold_in = inputs.get('T_cold_in', 20.0)
        flow_hot = max(0.001, inputs.get('flow_hot', 1.0))
        flow_cold = max(0.001, inputs.get('flow_cold', 1.0))

        C_hot = flow_hot * self.Cp_hot
        C_cold = flow_cold * self.Cp_cold
        C_min = min(C_hot, C_cold)
        C_max = max(C_hot, C_cold)

        if C_min <= 0:
            return self.state

        NTU = self.UA / C_min
        C_ratio = C_min / C_max
        # Effectiveness for counter-flow
        if C_ratio < 1.0:
            exp_term = math.exp(-NTU * (1 - C_ratio))
            effectiveness = (1 - exp_term) / (1 - C_ratio * exp_term)
        else:
            effectiveness = NTU / (1 + NTU)

        Q = effectiveness * C_min * (T_hot_in - T_cold_in)
        self.state['T_hot_out'] = T_hot_in - Q / C_hot
        self.state['T_cold_out'] = T_cold_in + Q / C_cold
        return dict(self.state)

    def reset(self):
        self.state = {'T_hot_out': 25.0, 'T_cold_out': 25.0}


# Model registry
MODEL_TYPES: Dict[str, type] = {
    'thermalMass': ThermalMass,
    'flowLoop': FlowLoop,
    'pressureVessel': PressureVessel,
    'levelTank': LevelTank,
    'genericFirstOrder': GenericFirstOrder,
    'heatExchanger': HeatExchanger,
}


# ---------------------------------------------------------------------------
# Process Model Binding — connects models to DAQ channels
# ---------------------------------------------------------------------------

class ModelBinding:
    """Connects a process model's inputs/outputs to DAQ channels."""

    def __init__(self, model: ProcessModel,
                 input_channels: Dict[str, str],
                 output_channels: Dict[str, str]):
        """
        Args:
            model: The process model instance
            input_channels: Maps model input name -> DAQ channel name
                e.g. {"heater_power": "HeaterOutput"}
            output_channels: Maps model output name -> DAQ channel name
                e.g. {"temperature": "FurnaceTemp"}
        """
        self.model = model
        self.input_channels = input_channels    # model_input -> daq_channel
        self.output_channels = output_channels  # model_output -> daq_channel


# ---------------------------------------------------------------------------
# ProcessSimulator — subclass of HardwareSimulator
# ---------------------------------------------------------------------------

class ProcessSimulator(HardwareSimulator):
    """
    Physics-based simulator that extends HardwareSimulator with coupled
    process models. AO channel writes feed into model inputs; model outputs
    override AI channel reads.
    """

    def __init__(self, config: NISystemConfig, model_configs: Optional[List[Dict[str, Any]]] = None):
        super().__init__(config)
        self.bindings: List[ModelBinding] = []
        self._last_step_time: float = time.time()
        self._output_overrides: Dict[str, float] = {}

        if model_configs:
            for mc in model_configs:
                self.add_model_from_config(mc)

    def add_model_from_config(self, config: Dict[str, Any]) -> ProcessModel:
        """Add a process model from a JSON config dict."""
        model_type = config.get('type', '')
        name = config.get('name', model_type)
        params = config.get('params', {})
        input_channels = config.get('inputChannels', {})
        output_channels = config.get('outputChannels', {})

        cls = MODEL_TYPES.get(model_type)
        if cls is None:
            raise ValueError(f"Unknown process model type: {model_type!r}. "
                             f"Available: {list(MODEL_TYPES.keys())}")

        model = cls(name, params)
        binding = ModelBinding(model, input_channels, output_channels)
        self.bindings.append(binding)
        logger.info(f"Added process model {name!r} ({model_type}) — "
                     f"inputs: {input_channels}, outputs: {output_channels}")
        return model

    def add_model(self, model: ProcessModel,
                  input_channels: Dict[str, str],
                  output_channels: Dict[str, str]):
        """Add a pre-constructed process model with channel bindings."""
        binding = ModelBinding(model, input_channels, output_channels)
        self.bindings.append(binding)

    def step_models(self, dt: float):
        """Step all process models forward by dt seconds."""
        for binding in self.bindings:
            # Gather inputs from DAQ channel current values
            inputs: Dict[str, float] = {}
            for model_input, daq_channel in binding.input_channels.items():
                if daq_channel in self.channel_simulators:
                    inputs[model_input] = self.channel_simulators[daq_channel].state.value
                else:
                    inputs[model_input] = 0.0

            # Step the model
            outputs = binding.model.update(dt, inputs)

            # Write model outputs to override dict
            for model_output, daq_channel in binding.output_channels.items():
                if model_output in outputs:
                    self._output_overrides[daq_channel] = outputs[model_output]

    def _apply_sensor_noise(self, channel_name: str, value: float) -> float:
        """Apply realistic sensor noise from the channel's simulator config."""
        sim = self.channel_simulators.get(channel_name)
        if sim and sim.state.noise_level > 0:
            value += random.gauss(0, sim.state.noise_level)
        return value

    def read_all(self) -> Dict[str, float]:
        """Read all channels, stepping physics models first."""
        now = time.time()
        dt = now - self._last_step_time
        if dt > 0:
            self.step_models(dt)
        self._last_step_time = now

        # Get base simulator values
        values = super().read_all()

        # Override with process model outputs + sensor noise
        for channel_name, value in self._output_overrides.items():
            values[channel_name] = self._apply_sensor_noise(channel_name, value)

        return values

    def read_channel(self, channel_name: str) -> Optional[float]:
        """Read a single channel, checking process model overrides first."""
        if channel_name in self._output_overrides:
            return self._apply_sensor_noise(channel_name, self._output_overrides[channel_name])
        return super().read_channel(channel_name)

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write to a channel — the value will be picked up by models on next step."""
        return super().write_channel(channel_name, value)

    def reset_models(self):
        """Reset all process models to initial conditions."""
        self._output_overrides.clear()
        for binding in self.bindings:
            binding.model.reset()
        logger.info("All process models reset to initial conditions")

    def get_model_states(self) -> Dict[str, Dict[str, float]]:
        """Return internal state of all process models (for debugging)."""
        return {b.model.name: b.model.get_state() for b in self.bindings}


# ---------------------------------------------------------------------------
# Standalone CLI — run a simulation for testing
# ---------------------------------------------------------------------------

def main():
    """Run the process simulator standalone for testing."""
    import argparse
    parser = argparse.ArgumentParser(description='Process Simulator — closed-loop physics simulation')
    parser.add_argument('project', nargs='?', help='Project JSON file path')
    parser.add_argument('--duration', type=float, default=10.0, help='Simulation duration (seconds)')
    parser.add_argument('--dt', type=float, default=0.1, help='Time step (seconds)')
    parser.add_argument('--demo', action='store_true', help='Run built-in demo (no project file needed)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

    if args.demo:
        _run_demo(args.duration, args.dt)
        return

    if not args.project:
        parser.error('Either --demo or a project file is required')


def _run_demo(duration: float, dt: float):
    """Run a standalone demo: heater heating a thermal mass with PID-like control."""
    # Create a minimal thermal mass model
    model = ThermalMass('DemoFurnace', {
        'mass': 50, 'Cp': 500, 'UA': 5, 'T_ambient': 25, 'T_initial': 25
    })

    setpoint = 200.0
    heater_power = 0.0
    Kp = 50.0

    print(f"{'Time':>6s}  {'Temp':>8s}  {'Power':>8s}  {'Setpoint':>8s}")
    print('-' * 40)

    t = 0.0
    while t < duration:
        outputs = model.update(dt, {'heater_power': heater_power})
        temp = outputs['temperature']

        # Simple proportional control
        error = setpoint - temp
        heater_power = max(0.0, min(5000.0, Kp * error))

        if int(t * 10) % 10 == 0:  # print every 1s
            print(f"{t:6.1f}  {temp:8.2f}  {heater_power:8.1f}  {setpoint:8.1f}")

        t += dt

    print(f"\nSteady-state prediction: {model.steady_state_temperature(heater_power):.2f} degC")


if __name__ == '__main__':
    main()
