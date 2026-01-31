# GTI Energy - H2-Ready Boiler Combustion Research
# Realistic Data Simulator
#
# Generates plausible operating data for demo/screenshots.
# Run this script to simulate a boiler running at various conditions.

import math

# === SIMULATION STATE ===
sim_time = 0
firing_rate = 50.0  # Start at 50% firing
h2_blend = 15.0     # Start at 15% H2 blend
warmup_phase = True
warmup_duration = 60  # seconds

# Base operating parameters at 100% firing, 0% H2
BASE_COMBUSTION_TEMP = 1650  # degF
BASE_FLUE_TEMP = 380        # degF
BASE_O2 = 4.5               # %
BASE_CO = 45                # ppm
BASE_NOX = 85               # ppm
BASE_CO2 = 9.5              # %
BASE_WATER_DELTA_T = 35     # degF

# Noise generators
def add_noise(value, noise_pct=1.0):
    """Add realistic measurement noise"""
    noise = (math.sin(sim_time * 0.7) * 0.3 +
             math.sin(sim_time * 2.1) * 0.2 +
             math.sin(sim_time * 5.3) * 0.1) * noise_pct
    return value * (1 + noise / 100)

def ramp(current, target, rate):
    """Smooth ramping function"""
    if abs(current - target) < rate:
        return target
    elif current < target:
        return current + rate
    else:
        return current - rate

# Initialize outputs to safe state
outputs.Burner_Enable = True
outputs.Blower_Start = True
outputs.Circ_Pump_Start = True
outputs.Pilot_Valve = True
outputs.Main_Gas_Valve = True
outputs.H2_Shutoff_Valve = True
outputs.Ignition_Spark = False
outputs.Alarm_Horn = False

# Set initial analog outputs
outputs.Burner_Firing_Rate = firing_rate
outputs.H2_Blend_Setpoint = h2_blend
outputs.Air_Damper_Pos = 60

print("=== GTI Boiler Simulator Starting ===")
print(f"Initial firing rate: {firing_rate}%")
print(f"Initial H2 blend: {h2_blend}%")

while True:
    sim_time += 1 / session.scan_rate if session.scan_rate > 0 else 0.1

    # === WARMUP PHASE ===
    if warmup_phase and sim_time < warmup_duration:
        warmup_factor = sim_time / warmup_duration
        print(f"Warmup: {warmup_factor*100:.0f}%") if int(sim_time) % 10 == 0 else None
    else:
        warmup_phase = False
        warmup_factor = 1.0

    # === VARY OPERATING CONDITIONS (for interesting data) ===
    # Slowly vary firing rate between 40-80%
    target_firing = 60 + 20 * math.sin(sim_time / 120)
    firing_rate = ramp(firing_rate, target_firing, 0.1)

    # Slowly vary H2 blend between 10-25%
    target_h2 = 17.5 + 7.5 * math.sin(sim_time / 180 + 1.5)
    h2_blend = ramp(h2_blend, target_h2, 0.05)

    # Update analog outputs
    outputs.Burner_Firing_Rate = firing_rate
    outputs.H2_Blend_Setpoint = h2_blend
    outputs.Air_Damper_Pos = 50 + firing_rate * 0.4  # Damper follows firing

    # === CALCULATE SIMULATED SENSOR VALUES ===
    firing_factor = firing_rate / 100
    h2_factor = h2_blend / 100

    # Combustion temperatures - higher with firing rate, slightly lower with H2
    t_comb_1 = BASE_COMBUSTION_TEMP * firing_factor * warmup_factor * (1 - h2_factor * 0.05)
    t_comb_2 = t_comb_1 * 0.92
    t_comb_3 = t_comb_1 * 0.85

    # Flue gas temperature
    t_flue_1 = (BASE_FLUE_TEMP + (t_comb_1 - BASE_COMBUSTION_TEMP) * 0.15) * warmup_factor
    t_flue_2 = t_flue_1 * 1.2  # Before economizer

    # Heat exchanger temps
    t_hx_in = t_comb_1 * 0.5
    t_hx_out = t_flue_1 * 1.1

    # Burner tip (watch for flashback with H2)
    t_burner_tip = 180 + firing_rate * 1.5 + h2_blend * 2

    # Water temperatures
    t_water_supply = 65 + 5 * math.sin(sim_time / 300)  # Slight variation in supply
    water_delta_t = BASE_WATER_DELTA_T * firing_factor * warmup_factor
    t_water_return = t_water_supply + water_delta_t

    # Ambient and combustion air
    t_ambient = 72 + 3 * math.sin(sim_time / 600)
    t_comb_air = t_ambient + 20 * firing_factor  # Preheated

    # Fuel flows (SCFH)
    total_fuel_flow = 1500 * firing_factor  # Total at 100%
    ng_flow = total_fuel_flow * (1 - h2_factor)
    h2_flow = total_fuel_flow * h2_factor * 3.1  # H2 has ~3x volume per BTU

    # Air flow (SCFM) - roughly 10:1 air-to-fuel
    air_flow = (ng_flow / 60) * 10 * (1 + BASE_O2 / 100)

    # Water flow
    water_flow = 45 + 15 * firing_factor  # 45-60 GPM

    # Pressures
    p_ng = 7.5 + 2 * firing_factor  # 7.5-9.5 psig
    p_h2 = 55 + 10 * firing_factor  # 55-65 psig
    p_furnace = -0.5 - 1.5 * firing_factor  # Draft increases with firing
    p_water = 45 + 5 * firing_factor

    # === EMISSIONS (H2 reduces NOx, may increase CO at low firing) ===
    # O2 decreases with firing rate
    o2_flue = BASE_O2 - 1.5 * firing_factor + 0.5 * h2_factor

    # CO - may spike at low firing or high H2
    co_base = BASE_CO * (1.5 - firing_factor * 0.5)  # Higher at low firing
    co_flue = co_base * (1 + h2_factor * 0.3)  # Slightly higher with H2

    # CO2 - lower with H2 (less carbon)
    co2_flue = BASE_CO2 * firing_factor * (1 - h2_factor * 0.4)

    # NOx - LOWER with H2 (key benefit!)
    nox_base = BASE_NOX * firing_factor
    nox_flue = nox_base * (1 - h2_factor * 1.5)  # 15-30% reduction with H2

    # Flame signal
    flame_signal = 75 + 20 * firing_factor * warmup_factor

    # H2 leak detectors (should be near zero)
    h2_det_1 = 0 + add_noise(0.5, 50)  # Slight background noise
    h2_det_2 = 0 + add_noise(0.3, 50)

    # === APPLY NOISE AND PUBLISH ===
    # Note: In simulation mode, these would be set via a different mechanism
    # This script publishes calculated values that override simulated ones

    publish('SIM_TC_Combustion_1', add_noise(t_comb_1, 0.5), 'degF')
    publish('SIM_TC_Combustion_2', add_noise(t_comb_2, 0.5), 'degF')
    publish('SIM_TC_Combustion_3', add_noise(t_comb_3, 0.5), 'degF')
    publish('SIM_TC_Flue_1', add_noise(t_flue_1, 1.0), 'degF')
    publish('SIM_TC_Flue_2', add_noise(t_flue_2, 1.0), 'degF')
    publish('SIM_TC_HX_In', add_noise(t_hx_in, 1.0), 'degF')
    publish('SIM_TC_HX_Out', add_noise(t_hx_out, 1.0), 'degF')
    publish('SIM_TC_Burner_Tip', add_noise(t_burner_tip, 2.0), 'degF')

    publish('SIM_RTD_Water_Supply', add_noise(t_water_supply, 0.2), 'degF')
    publish('SIM_RTD_Water_Return', add_noise(t_water_return, 0.2), 'degF')
    publish('SIM_RTD_Ambient', add_noise(t_ambient, 0.5), 'degF')
    publish('SIM_RTD_Combustion_Air', add_noise(t_comb_air, 0.5), 'degF')

    publish('SIM_FT_NG', add_noise(ng_flow, 1.5), 'SCFH')
    publish('SIM_FT_H2', add_noise(h2_flow, 2.0), 'SCFH')
    publish('SIM_FT_Air', add_noise(air_flow, 1.0), 'SCFM')
    publish('SIM_FT_Water', add_noise(water_flow, 0.5), 'GPM')

    publish('SIM_PT_NG_Supply', add_noise(p_ng, 1.0), 'psig')
    publish('SIM_PT_H2_Supply', add_noise(p_h2, 0.5), 'psig')
    publish('SIM_PT_Furnace', add_noise(p_furnace, 3.0), 'inWC')
    publish('SIM_PT_Water', add_noise(p_water, 0.5), 'psig')

    publish('SIM_O2_Flue', add_noise(o2_flue, 2.0), '%')
    publish('SIM_CO_Flue', add_noise(co_flue, 5.0), 'ppm')
    publish('SIM_CO2_Flue', add_noise(co2_flue, 1.5), '%')
    publish('SIM_NOx_Flue', add_noise(nox_flue, 3.0), 'ppm')

    publish('SIM_Flame_Signal', add_noise(flame_signal, 2.0), '%')
    publish('SIM_H2_Ambient_1', max(0, h2_det_1), '% LEL')
    publish('SIM_H2_Ambient_2', max(0, h2_det_2), '% LEL')

    # Status
    publish('SIM_Firing_Rate', firing_rate, '%')
    publish('SIM_H2_Blend', h2_blend, '%')
    publish('SIM_Time', sim_time, 'sec')

    next_scan()
