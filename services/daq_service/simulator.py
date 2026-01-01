"""
Hardware Simulator for NISystem
Generates realistic simulated data when no real hardware is present
"""

import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional
from config_parser import ChannelConfig, ChannelType, NISystemConfig

logger = logging.getLogger('Simulator')


@dataclass
class SimulatorState:
    """Tracks internal state for realistic simulation"""
    value: float = 0.0
    target: float = 0.0
    trend: float = 0.0
    noise_level: float = 0.01
    last_update: float = 0.0


class ChannelSimulator:
    """Simulates a single channel with realistic behavior"""

    def __init__(self, channel: ChannelConfig):
        self.channel = channel
        self.state = SimulatorState()
        self._initialize_state()

    def _initialize_state(self):
        """Set initial values based on channel type"""
        ch = self.channel

        if ch.channel_type == ChannelType.THERMOCOUPLE:
            # Start at room temperature, simulate heating/cooling
            self.state.value = 25.0 + random.uniform(-2, 2)
            self.state.target = 25.0
            self.state.noise_level = 0.5
            self.state.trend = 0.0

        elif ch.channel_type == ChannelType.VOLTAGE:
            # Start at mid-range
            if ch.low_limit is not None and ch.high_limit is not None:
                mid = (ch.low_limit + ch.high_limit) / 2
                self.state.value = mid + random.uniform(-mid * 0.1, mid * 0.1)
            else:
                self.state.value = 0.0
            self.state.noise_level = 0.02

        elif ch.channel_type == ChannelType.CURRENT:
            # Simulate 4-20mA sensor behavior
            if ch.low_limit is not None and ch.high_limit is not None:
                mid = (ch.low_limit + ch.high_limit) / 2
                self.state.value = mid
            else:
                self.state.value = 0.0
            self.state.noise_level = 0.01

        elif ch.channel_type == ChannelType.DIGITAL_INPUT:
            # Safety inputs default to safe state (1.0 = OK)
            # Other digital inputs get random initial state
            name_lower = ch.name.lower()
            safety_keywords = ['e_stop', 'estop', 'emergency', 'overtemp', 'over_temp',
                               'door', 'interlock', 'water_flow', 'flow_ok',
                               'air_ok', 'compressed_air', 'power_ok']
            is_safety = any(kw in name_lower for kw in safety_keywords)
            self.state.value = 1.0 if is_safety else (1.0 if random.random() > 0.3 else 0.0)

        elif ch.channel_type == ChannelType.RTD:
            # RTD starts at room temperature (same as thermocouple)
            self.state.value = 25.0 + random.uniform(-2, 2)
            self.state.target = 25.0
            self.state.noise_level = 0.3  # RTDs are typically more stable

        elif ch.channel_type == ChannelType.STRAIN:
            # Strain gauge starts near zero (no load)
            self.state.value = random.uniform(-50, 50)  # microstrain
            self.state.noise_level = 5.0

        elif ch.channel_type == ChannelType.IEPE:
            # IEPE accelerometer starts near zero
            self.state.value = 0.0
            self.state.noise_level = 0.1  # g

        elif ch.channel_type == ChannelType.RESISTANCE:
            # Start at mid-range resistance
            mid = ch.resistance_range / 2
            self.state.value = mid + random.uniform(-mid * 0.1, mid * 0.1)
            self.state.noise_level = ch.resistance_range * 0.001

        elif ch.channel_type == ChannelType.DIGITAL_OUTPUT:
            self.state.value = 1.0 if ch.default_state else 0.0

        elif ch.channel_type == ChannelType.ANALOG_OUTPUT:
            self.state.value = ch.default_value

        self.state.last_update = time.time()

    def read(self) -> float:
        """Read the current simulated value"""
        now = time.time()
        dt = now - self.state.last_update
        self.state.last_update = now

        ch = self.channel

        if ch.channel_type == ChannelType.THERMOCOUPLE:
            return self._simulate_temperature(dt)

        elif ch.channel_type == ChannelType.VOLTAGE:
            return self._simulate_voltage(dt)

        elif ch.channel_type == ChannelType.CURRENT:
            return self._simulate_current(dt)

        elif ch.channel_type == ChannelType.RTD:
            return self._simulate_rtd(dt)

        elif ch.channel_type == ChannelType.STRAIN:
            return self._simulate_strain(dt)

        elif ch.channel_type == ChannelType.IEPE:
            return self._simulate_iepe(dt)

        elif ch.channel_type == ChannelType.RESISTANCE:
            return self._simulate_resistance(dt)

        elif ch.channel_type == ChannelType.COUNTER:
            return self._simulate_counter(dt)

        elif ch.channel_type == ChannelType.DIGITAL_INPUT:
            return self._simulate_digital_input()

        elif ch.channel_type in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT):
            return self.state.value

        return 0.0

    def write(self, value: Any) -> bool:
        """Write a value to the simulated channel"""
        ch = self.channel

        if ch.channel_type == ChannelType.DIGITAL_OUTPUT:
            self.state.value = 1.0 if value else 0.0
            return True

        elif ch.channel_type == ChannelType.ANALOG_OUTPUT:
            self.state.value = float(value)
            return True

        return False

    def set_target(self, target: float):
        """Set target value for channels that trend toward a setpoint"""
        self.state.target = target

    def _simulate_temperature(self, dt: float) -> float:
        """Simulate realistic temperature behavior"""
        # Slowly trend toward target with noise
        diff = self.state.target - self.state.value
        self.state.value += diff * 0.01 * dt  # Slow thermal response

        # Add random walk
        self.state.value += random.gauss(0, self.state.noise_level * math.sqrt(dt))

        # Add sine wave for cyclical heating behavior (added to output, not state)
        output = self.state.value + math.sin(time.time() * 0.1) * 2.0

        return round(output, 2)

    def _simulate_voltage(self, dt: float) -> float:
        """
        Simulate voltage input with realistic noise and drift.
        Returns RAW voltage in V (within the configured voltage_range).
        Scaling to engineering units is applied later by the DAQ service.
        """
        ch = self.channel

        # Use the voltage range from config (default ±10V)
        v_range = ch.voltage_range if ch.voltage_range else 10.0

        # For channels with map scaling configured, simulate within pre_scaled range
        if ch.pre_scaled_min is not None and ch.pre_scaled_max is not None:
            min_v = ch.pre_scaled_min
            max_v = ch.pre_scaled_max
        else:
            # Default to 0 to voltage_range (unipolar) or use limits if set
            min_v = 0.0
            max_v = v_range

        mid = (min_v + max_v) / 2
        range_val = max_v - min_v

        # Mean reversion toward center of range
        diff = mid - self.state.value
        self.state.value += diff * 0.001 * dt

        # Random walk
        self.state.value += random.gauss(0, range_val * 0.001 * math.sqrt(dt))

        # Add some periodic variation
        self.state.value += math.sin(time.time() * 0.5) * range_val * 0.02

        # Clamp to voltage range
        self.state.value = max(min_v, min(max_v, self.state.value))

        return round(self.state.value, 4)

    def _simulate_current(self, dt: float) -> float:
        """
        Simulate 4-20mA sensor behavior.
        Returns RAW current in mA (4-20 range typically).
        Scaling to engineering units is applied later by the DAQ service.
        """
        ch = self.channel

        # Simulate a slowly varying 4-20mA signal
        # The value is in mA, not engineering units
        # Use eng_units_min/max if 4-20 scaling is configured, otherwise use limits

        # Determine what the "target range" should be in mA
        # For 4-20mA, we want to output values in the 4-20 mA range
        min_ma = 4.0
        max_ma = 20.0

        mid_ma = (min_ma + max_ma) / 2  # 12 mA
        range_ma = max_ma - min_ma      # 16 mA

        # Slowly varying process value (in mA)
        self.state.trend += random.gauss(0, 0.1 * dt)
        self.state.trend = max(-1, min(1, self.state.trend))

        # Value varies around midpoint
        self.state.value = mid_ma + self.state.trend * range_ma * 0.3
        self.state.value += random.gauss(0, range_ma * 0.005)

        # Add periodic variation (like a pump cycle)
        self.state.value += math.sin(time.time() * 0.3) * range_ma * 0.05

        # Clamp to 4-20mA range (with slight allowance for under/over)
        self.state.value = max(3.8, min(20.5, self.state.value))

        return round(self.state.value, 3)

    def _simulate_rtd(self, dt: float) -> float:
        """
        Simulate RTD temperature sensor.
        Returns temperature in °C (similar to thermocouple but more stable).
        """
        # Slowly trend toward target with noise (RTDs are more stable than TCs)
        diff = self.state.target - self.state.value
        self.state.value += diff * 0.008 * dt  # Slightly faster than TC

        # Add random walk (less noise than thermocouple)
        self.state.value += random.gauss(0, self.state.noise_level * math.sqrt(dt))

        # Add gentle sine wave for cyclical behavior
        output = self.state.value + math.sin(time.time() * 0.08) * 1.0

        return round(output, 2)

    def _simulate_strain(self, dt: float) -> float:
        """
        Simulate strain gauge output.
        Returns strain in microstrain (µε).
        """
        ch = self.channel

        # Simulate slowly varying mechanical load
        self.state.trend += random.gauss(0, 0.05 * dt)
        self.state.trend = max(-1, min(1, self.state.trend))

        # Base strain varies with trend
        self.state.value = self.state.trend * 500  # ±500 µε range

        # Add mechanical vibration noise
        self.state.value += random.gauss(0, self.state.noise_level)

        # Add periodic variation (like a rotating shaft)
        self.state.value += math.sin(time.time() * 2.0) * 50

        return round(self.state.value, 1)

    def _simulate_iepe(self, dt: float) -> float:
        """
        Simulate IEPE accelerometer output.
        Returns acceleration in g.
        """
        # Simulate vibration with varying amplitude
        freq = 10 + random.uniform(-2, 2)  # ~10 Hz vibration

        # Base vibration signal
        self.state.value = math.sin(time.time() * freq * 2 * math.pi) * 0.5

        # Add higher frequency harmonics
        self.state.value += math.sin(time.time() * freq * 4 * math.pi) * 0.2
        self.state.value += math.sin(time.time() * freq * 6 * math.pi) * 0.1

        # Add random noise
        self.state.value += random.gauss(0, self.state.noise_level)

        # Occasional impact events
        if random.random() < 0.001:
            self.state.value += random.choice([-1, 1]) * random.uniform(2, 5)

        return round(self.state.value, 3)

    def _simulate_resistance(self, dt: float) -> float:
        """
        Simulate resistance measurement.
        Returns resistance in Ohms.
        """
        ch = self.channel

        # Mean reversion toward mid-range
        mid = ch.resistance_range / 2
        diff = mid - self.state.value
        self.state.value += diff * 0.001 * dt

        # Random walk
        self.state.value += random.gauss(0, self.state.noise_level * math.sqrt(dt))

        # Small periodic variation (temperature drift)
        self.state.value += math.sin(time.time() * 0.1) * ch.resistance_range * 0.01

        # Clamp to valid range
        self.state.value = max(0, min(ch.resistance_range, self.state.value))

        return round(self.state.value, 2)

    def _simulate_counter(self, dt: float) -> float:
        """
        Simulate counter/pulse input as a TOTALIZER (accumulating counter).
        Returns accumulated pulse count (which gets scaled to volume by DAQ service).

        For valve dosing simulation:
        - Flow_1, Flow_2, Flow_3 channels accumulate when their associated valve is open
        - The simulator tracks a reference to the parent HardwareSimulator to check valve states
        """
        ch = self.channel
        name_lower = ch.name.lower()

        # Check if this is a valve dosing flow totalizer
        # These accumulate based on associated valve state
        is_flow_totalizer = name_lower.startswith('flow_')

        if is_flow_totalizer:
            # Try to get associated valve channel name
            # Flow_1 -> Valve_1, Flow_2 -> Valve_2, etc.
            valve_name = name_lower.replace('flow_', 'valve_').title().replace('_', '_')
            # Normalize: flow_1 -> Valve_1
            parts = ch.name.split('_')
            if len(parts) == 2:
                valve_name = f"Valve_{parts[1]}"

            # Check if we have a parent simulator reference and valve is open
            valve_open = False
            if hasattr(self, '_parent_simulator') and self._parent_simulator:
                valve_sim = self._parent_simulator.channel_simulators.get(valve_name)
                if valve_sim:
                    valve_open = valve_sim.state.value > 0.5

            if valve_open:
                # Valve is open - accumulate flow
                # Simulate ~10 units/second flow rate with some variation
                flow_rate = 10.0 + random.gauss(0, 0.5)
                self.state.value += flow_rate * dt
            # If valve closed, no accumulation (hold current value)

        else:
            # Standard counter behavior - frequency-based accumulation
            # Base frequency when "flowing"
            base_freq = 50.0  # Hz - typical flow meter output

            # Slowly varying frequency to simulate flow changes
            self.state.trend += random.gauss(0, 0.05 * dt)
            self.state.trend = max(-1, min(1, self.state.trend))

            # Base frequency with variation
            freq = base_freq * (0.8 + 0.4 * (self.state.trend + 1) / 2)

            # Add some noise
            freq += random.gauss(0, base_freq * 0.02)

            # Accumulate pulses
            self.state.value += freq * dt

        return round(self.state.value, 2)

    def _simulate_digital_input(self) -> float:
        """Simulate digital input with occasional state changes"""
        ch = self.channel
        name_lower = ch.name.lower()

        # Safety-critical inputs - always return safe state (1.0 = OK)
        # These should never randomly toggle in simulation
        safety_keywords = [
            'e_stop', 'estop', 'emergency',      # Emergency stops
            'overtemp', 'over_temp',             # Overtemperature switches
            'door', 'interlock',                 # Door/interlock switches
            'water_flow', 'flow_ok',             # Flow switches
            'air_ok', 'compressed_air',          # Pressure switches
            'power_ok',                          # Power status
        ]

        for keyword in safety_keywords:
            if keyword in name_lower:
                # Safety input - always OK (1.0)
                return 1.0

        # Limit switches occasionally trigger
        if 'limit' in name_lower:
            if random.random() < 0.001:
                self.state.value = 1.0 - self.state.value
            return self.state.value

        # Other digital inputs - occasional random changes
        if random.random() < 0.002:
            self.state.value = 1.0 - self.state.value

        return self.state.value


class HardwareSimulator:
    """Manages simulation of all channels"""

    def __init__(self, config: NISystemConfig):
        self.config = config
        self.channel_simulators: Dict[str, ChannelSimulator] = {}
        self._initialize_simulators()

    def _initialize_simulators(self):
        """Create simulators for all channels"""
        for name, channel in self.config.channels.items():
            sim = ChannelSimulator(channel)
            # Set parent reference for counter channels that need to check valve states
            sim._parent_simulator = self
            self.channel_simulators[name] = sim

    def read_channel(self, channel_name: str) -> Optional[float]:
        """Read a simulated channel value"""
        if channel_name in self.channel_simulators:
            return self.channel_simulators[channel_name].read()
        return None

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write a value to a simulated channel"""
        if channel_name in self.channel_simulators:
            return self.channel_simulators[channel_name].write(value)
        return False

    def read_all_inputs(self) -> Dict[str, float]:
        """Read all input channels"""
        values = {}
        for name, sim in self.channel_simulators.items():
            if sim.channel.channel_type in (
                ChannelType.THERMOCOUPLE,
                ChannelType.VOLTAGE,
                ChannelType.CURRENT,
                ChannelType.RTD,
                ChannelType.STRAIN,
                ChannelType.IEPE,
                ChannelType.RESISTANCE,
                ChannelType.COUNTER,
                ChannelType.DIGITAL_INPUT
            ):
                values[name] = sim.read()
        return values

    def read_all_outputs(self) -> Dict[str, float]:
        """Read current state of all output channels"""
        values = {}
        for name, sim in self.channel_simulators.items():
            if sim.channel.channel_type in (
                ChannelType.DIGITAL_OUTPUT,
                ChannelType.ANALOG_OUTPUT
            ):
                values[name] = sim.read()
        return values

    def read_all(self) -> Dict[str, float]:
        """Read all channels"""
        values = {}
        for name, sim in self.channel_simulators.items():
            values[name] = sim.read()
        return values

    def set_temperature_target(self, channel_name: str, target: float):
        """Set target temperature for thermocouple simulation"""
        if channel_name in self.channel_simulators:
            sim = self.channel_simulators[channel_name]
            if sim.channel.channel_type == ChannelType.THERMOCOUPLE:
                sim.set_target(target)

    def add_channel(self, channel: ChannelConfig):
        """Add a new channel to the simulator"""
        sim = ChannelSimulator(channel)
        sim._parent_simulator = self
        self.channel_simulators[channel.name] = sim

    def remove_channel(self, channel_name: str):
        """Remove a channel from the simulator"""
        if channel_name in self.channel_simulators:
            del self.channel_simulators[channel_name]

    def trigger_event(self, event_type: str):
        """Trigger a simulated event (for testing)"""
        if event_type == "e_stop":
            # Simulate e-stop pressed
            if "e_stop_status" in self.channel_simulators:
                self.channel_simulators["e_stop_status"].state.value = 0.0

        elif event_type == "door_open":
            if "door_interlock" in self.channel_simulators:
                self.channel_simulators["door_interlock"].state.value = 0.0

        elif event_type == "high_temp":
            # Simulate high temperature condition
            for name, sim in self.channel_simulators.items():
                if sim.channel.channel_type == ChannelType.THERMOCOUPLE:
                    sim.state.value = 1150.0

        elif event_type == "reset":
            # Reset all to safe defaults
            self._initialize_simulators()

    def reset_counter(self, channel_name: str):
        """Reset a counter channel to zero"""
        if channel_name in self.channel_simulators:
            sim = self.channel_simulators[channel_name]
            if sim.channel.channel_type == ChannelType.COUNTER:
                sim.state.value = 0.0
                logger.info(f"Simulator: Reset counter {channel_name} to 0")


if __name__ == "__main__":
    from pathlib import Path
    from config_parser import load_config

    config_path = Path(__file__).parent.parent.parent / "config" / "system.ini"
    config = load_config(str(config_path))

    simulator = HardwareSimulator(config)

    print("Starting simulation test...")
    print("-" * 60)

    for i in range(5):
        print(f"\nSample {i + 1}:")
        values = simulator.read_all()

        # Group by type
        temps = {k: v for k, v in values.items()
                 if config.channels[k].channel_type == ChannelType.THERMOCOUPLE}
        voltages = {k: v for k, v in values.items()
                    if config.channels[k].channel_type == ChannelType.VOLTAGE}
        currents = {k: v for k, v in values.items()
                    if config.channels[k].channel_type == ChannelType.CURRENT}
        di = {k: v for k, v in values.items()
              if config.channels[k].channel_type == ChannelType.DIGITAL_INPUT}
        do = {k: v for k, v in values.items()
              if config.channels[k].channel_type == ChannelType.DIGITAL_OUTPUT}

        print(f"  Temperatures: {temps}")
        print(f"  Voltages: {voltages}")
        print(f"  Currents: {currents}")
        print(f"  Digital In: {di}")
        print(f"  Digital Out: {do}")

        time.sleep(0.5)

    # Test write
    print("\n" + "-" * 60)
    print("Testing write to digital output...")
    print(f"main_contactor before: {simulator.read_channel('main_contactor')}")
    simulator.write_channel('main_contactor', True)
    print(f"main_contactor after: {simulator.read_channel('main_contactor')}")
