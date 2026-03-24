# GTI Energy - H2-Ready Boiler Combustion Research
# EPA-Compliant Emissions Data Logger
#
# Performs emissions averaging, air-to-fuel ratio calculations,
# and regulatory compliance monitoring.

# === EPA LIMITS (typical for industrial boilers) ===
NOX_LIMIT = 100  # ppm @ 3% O2
CO_LIMIT = 400   # ppm @ 3% O2
O2_REF = 3.0     # Reference O2 for corrections

# Initialize rolling statistics for averaging
o2_stats = RollingStats(window=300)   # 5-minute rolling
co_stats = RollingStats(window=300)
nox_stats = RollingStats(window=300)
co2_stats = RollingStats(window=300)

# Track high-emission events
high_co_events = 0
high_nox_events = 0
test_start_time = now()

while True:
    # Read emissions analyzers
    o2_raw = tags.O2_Flue      # % O2
    co_raw = tags.CO_Flue      # ppm
    co2_raw = tags.CO2_Flue    # % CO2
    nox_raw = tags.NOx_Flue    # ppm

    # Read operating conditions
    firing_rate = tags.Burner_Firing_Rate  # %
    h2_blend = tags.H2_Blend_Setpoint      # %
    t_flue = tags.TC_Flue_1                # degF

    # Add to rolling averages
    o2_stats.add(o2_raw)
    co_stats.add(co_raw)
    nox_stats.add(nox_raw)
    co2_stats.add(co2_raw)

    # Correct emissions to reference O2 (3%)
    # Correction factor = (21 - O2_ref) / (21 - O2_meas)
    if o2_raw < 20.5:  # Avoid division issues
        correction = (21 - O2_REF) / (21 - o2_raw)
    else:
        correction = 1.0

    co_corrected = co_raw * correction
    nox_corrected = nox_raw * correction

    # Calculate air-to-fuel ratio indicators
    # Stoichiometric for NG: ~10:1 by volume, ~17:1 by mass
    # With H2 blending, stoichiometric shifts
    if o2_raw > 0 and o2_raw < 21:
        # Approximate excess air from O2
        excess_air_pct = (o2_raw / (21 - o2_raw)) * 100
        lambda_value = 1 + (excess_air_pct / 100)
    else:
        excess_air_pct = 0
        lambda_value = 1.0

    # Track high emission events
    if co_corrected > CO_LIMIT:
        high_co_events += 1
    if nox_corrected > NOX_LIMIT:
        high_nox_events += 1

    # Calculate compliance status
    co_margin = ((CO_LIMIT - co_corrected) / CO_LIMIT) * 100
    nox_margin = ((NOX_LIMIT - nox_corrected) / NOX_LIMIT) * 100

    # Test duration
    test_duration_hr = elapsed_since(test_start_time) / 3600

    # Emissions intensity (lb/MMBTU) - simplified
    # CO: molecular weight 28, ppm to lb/MMBTU ~ ppm * 0.00057
    # NOx: as NO2, MW 46, ppm to lb/MMBTU ~ ppm * 0.00094
    co_intensity = co_corrected * 0.00057
    nox_intensity = nox_corrected * 0.00094

    # Publish emissions data
    publish('O2_5min_Avg', o2_stats.mean(), '%', '5-minute O2 average')
    publish('CO_Corrected', co_corrected, 'ppm', 'CO corrected to 3% O2')
    publish('NOx_Corrected', nox_corrected, 'ppm', 'NOx corrected to 3% O2')
    publish('CO_5min_Avg', co_stats.mean(), 'ppm', '5-minute CO average')
    publish('NOx_5min_Avg', nox_stats.mean(), 'ppm', '5-minute NOx average')
    publish('CO2_5min_Avg', co2_stats.mean(), '%', '5-minute CO2 average')

    # Publish compliance metrics
    publish('Lambda', lambda_value, '', 'Air-fuel equivalence ratio')
    publish('Excess_Air_Pct', excess_air_pct, '%', 'Excess air percentage')
    publish('CO_Compliance_Margin', co_margin, '%', 'CO margin below limit')
    publish('NOx_Compliance_Margin', nox_margin, '%', 'NOx margin below limit')
    publish('CO_Intensity', co_intensity, 'lb/MMBTU', 'CO emissions intensity')
    publish('NOx_Intensity', nox_intensity, 'lb/MMBTU', 'NOx emissions intensity')

    # Publish test statistics
    publish('High_CO_Events', high_co_events, 'count', 'High CO events this test')
    publish('High_NOx_Events', high_nox_events, 'count', 'High NOx events this test')
    publish('Test_Duration', test_duration_hr, 'hr', 'Test duration')

    # H2 impact indicator - NOx reduction expected with H2
    # Typically see 15-30% NOx reduction with 20% H2 blend
    if h2_blend > 5:
        estimated_nox_reduction = h2_blend * 1.2  # Rough estimate
        publish('Est_NOx_Reduction', estimated_nox_reduction, '%', 'Est NOx reduction from H2')

    next_scan()
