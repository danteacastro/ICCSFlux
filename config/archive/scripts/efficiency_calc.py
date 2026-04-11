# ICCSFlux - H2-Ready Boiler Combustion Research
# Real-time Thermal Efficiency Calculator
#
# Calculates combustion efficiency, thermal efficiency, and heat transfer
# rates based on measured temperatures, flows, and fuel composition.

# === CONSTANTS ===
NG_HHV = 1020  # BTU/SCF - Natural gas higher heating value
H2_HHV = 325   # BTU/SCF - Hydrogen higher heating value
WATER_CP = 1.0  # BTU/lb-F - Water specific heat
WATER_DENSITY = 8.34  # lb/gal

# Initialize accumulators
total_fuel_btu = Accumulator()
total_heat_output = Accumulator()
efficiency_stats = RollingStats(window=60)  # 1-minute rolling average

while True:
    # Read current values
    ng_flow = tags.FT_NG  # SCFH
    h2_flow = tags.FT_H2  # SCFH
    water_flow = tags.FT_Water  # GPM
    t_supply = tags.RTD_Water_Supply  # degF
    t_return = tags.RTD_Water_Return  # degF
    o2_flue = tags.O2_Flue  # %
    t_flue = tags.TC_Flue_1  # degF
    t_ambient = tags.RTD_Ambient  # degF
    h2_blend = tags.H2_Blend_Setpoint  # % setpoint

    # Calculate fuel input rate (BTU/hr)
    ng_btu_hr = ng_flow * NG_HHV
    h2_btu_hr = h2_flow * H2_HHV
    total_fuel_btu_hr = ng_btu_hr + h2_btu_hr

    # Calculate actual H2 blend percentage
    if ng_flow + h2_flow > 0:
        actual_h2_blend = (h2_flow / (ng_flow + h2_flow)) * 100
    else:
        actual_h2_blend = 0

    # Calculate heat output to water (BTU/hr)
    water_mass_flow = water_flow * 60 * WATER_DENSITY  # lb/hr
    delta_t = t_return - t_supply
    heat_output_btu_hr = water_mass_flow * WATER_CP * delta_t

    # Calculate thermal efficiency
    if total_fuel_btu_hr > 0:
        thermal_eff = (heat_output_btu_hr / total_fuel_btu_hr) * 100
    else:
        thermal_eff = 0

    # Calculate combustion efficiency (simplified stack loss method)
    # Based on O2 and flue gas temperature
    if o2_flue < 21:
        excess_air = (o2_flue / (21 - o2_flue)) * 100
        stack_loss = 0.37 * (t_flue - t_ambient) * (1 + excess_air/100) / 100
        combustion_eff = 100 - stack_loss
    else:
        combustion_eff = 0
        excess_air = 999

    # Accumulate totals
    total_fuel_btu.add(total_fuel_btu_hr / 3600)  # Convert to BTU/sec for accumulation
    total_heat_output.add(heat_output_btu_hr / 3600)
    efficiency_stats.add(thermal_eff)

    # Calculate firing rate percentage (assuming 500kW = 1,706,000 BTU/hr max)
    max_firing_btu = 1706000
    firing_rate_pct = (total_fuel_btu_hr / max_firing_btu) * 100

    # Convert heat output to kW (1 BTU/hr = 0.000293071 kW)
    heat_output_kw = heat_output_btu_hr * 0.000293071

    # Publish calculated values
    publish('Thermal_Efficiency', thermal_eff, '%', 'Overall thermal efficiency')
    publish('Combustion_Efficiency', combustion_eff, '%', 'Stack-loss combustion efficiency')
    publish('Heat_Output_kW', heat_output_kw, 'kW', 'Heat transfer to water')
    publish('Fuel_Input_BTU', total_fuel_btu_hr, 'BTU/hr', 'Total fuel energy input rate')
    publish('Excess_Air', excess_air, '%', 'Excess air percentage')
    publish('Actual_H2_Blend', actual_h2_blend, '%', 'Measured H2 blend ratio')
    publish('Firing_Rate', firing_rate_pct, '%', 'Current firing rate')
    publish('Water_DeltaT', delta_t, 'degF', 'Water temperature rise')
    publish('Avg_Efficiency_1min', efficiency_stats.mean(), '%', '1-minute rolling avg efficiency')
    publish('Total_Fuel_MBTU', total_fuel_btu.total / 1000000, 'MBTU', 'Cumulative fuel consumption')
    publish('Total_Heat_MBTU', total_heat_output.total / 1000000, 'MBTU', 'Cumulative heat output')

    next_scan()
