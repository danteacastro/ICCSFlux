# ═══════════════════════════════════════════════════════════════════════════════
# DHW Draw Profile Test Script
# ═══════════════════════════════════════════════════════════════════════════════
# Runs a 24-hour domestic hot water draw profile test
#
# Hardware:
#   - Ifm_cnt: Flow meter counter (6000 pulses per gallon)
#   - Power_Draw: Power consumption counter
#   - SV1, SV2, SV3: Solenoid valves (digital outputs)
#
# The script:
#   1. Opens solenoid valve(s) to start draw
#   2. Monitors Ifm_cnt until target gallons reached
#   3. Closes valve when target reached
#   4. Waits for draw period to complete
#   5. Resets counter and moves to next draw
#   6. Repeats for 24 hours
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION - Edit these values for your test
# ═══════════════════════════════════════════════════════════════════════════════

# Flow meter calibration
PULSES_PER_GALLON = 6000  # 1/6000 gallons per pulse

# Test duration
TEST_DURATION_HOURS = 24

# Draw schedule: list of (target_gallons, period_seconds, solenoids)
#   - target_gallons: how much water to draw
#   - period_seconds: total time from start of this draw to start of next
#   - solenoids: which valve(s) to open for this draw
#
# Example: DOE-style 6 draws per hour, 10 gallons each, alternating valves
DRAW_SCHEDULE = [
    # (gallons, period, solenoids)
    (10.0, 600, ['SV1']),        # Draw 1: 10 gal via SV1, wait until 10 min
    (10.0, 600, ['SV1']),        # Draw 2: 10 gal via SV1, wait until 20 min
    (10.0, 600, ['SV1']),        # Draw 3: 10 gal via SV1, wait until 30 min
    (10.0, 600, ['SV1']),        # Draw 4: 10 gal via SV1, wait until 40 min
    (10.0, 600, ['SV1']),        # Draw 5: 10 gal via SV1, wait until 50 min
    (10.0, 600, ['SV1']),        # Draw 6: 10 gal via SV1, wait until 60 min
]

# Safety limits
MAX_DRAW_TIME_SECONDS = 300  # Max time valve can be open per draw
MIN_FLOW_RATE_GPM = 0.5      # Minimum flow to detect (safety cutoff)
FLOW_CHECK_DELAY = 10        # Seconds to wait before checking flow rate

# ═══════════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

# State tracking
draw_number = 0
schedule_index = 0
total_gallons_drawn = 0
total_draws_completed = 0
test_start_time = None
draw_start_time = None
draw_start_pulses = 0

# Flow rate calculator for safety monitoring
flow_rate_calc = RateCalculator(window_seconds=5)

def pulses_to_gallons(pulses):
    """Convert counter pulses to gallons"""
    return pulses / PULSES_PER_GALLON

def open_valves(solenoids):
    """Open specified solenoid valves"""
    for valve in solenoids:
        outputs.set(valve, True)
    print(f"[{time_of_day()}] Valves OPEN: {', '.join(solenoids)}")

def close_valves():
    """Close all solenoid valves"""
    for valve in ['SV1', 'SV2', 'SV3']:
        outputs.set(valve, False)
    print(f"[{time_of_day()}] Valves CLOSED")

def get_current_pulses():
    """Get current flow counter value"""
    return tags.get('Ifm_cnt', default=0)

def get_power_pulses():
    """Get current power counter value"""
    return tags.get('Power_Draw', default=0)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN TEST LOOP
# ═══════════════════════════════════════════════════════════════════════════════

# Ensure valves are closed at start
close_valves()

# Record test start
test_start_time = now()
print(f"")
print(f"═══════════════════════════════════════════════════════════════════")
print(f"  DHW DRAW PROFILE TEST STARTED")
print(f"  Time: {now_iso()}")
print(f"  Duration: {TEST_DURATION_HOURS} hours")
print(f"  Schedule: {len(DRAW_SCHEDULE)} draws per cycle")
print(f"═══════════════════════════════════════════════════════════════════")
print(f"")

try:
    while session.active:
        test_elapsed = elapsed_since(test_start_time)
        test_elapsed_hours = test_elapsed / 3600

        # Check if test is complete
        if test_elapsed_hours >= TEST_DURATION_HOURS:
            print(f"")
            print(f"═══════════════════════════════════════════════════════════════════")
            print(f"  TEST COMPLETE!")
            print(f"  Total draws: {total_draws_completed}")
            print(f"  Total gallons: {total_gallons_drawn:.2f}")
            print(f"  Duration: {test_elapsed_hours:.2f} hours")
            print(f"═══════════════════════════════════════════════════════════════════")
            break

        # Get current draw from schedule (cycles through)
        target_gallons, draw_period, solenoids = DRAW_SCHEDULE[schedule_index]

        # Increment draw counter
        draw_number += 1

        print(f"")
        print(f"─── DRAW #{draw_number} ───────────────────────────────────────────────")
        print(f"  Target: {target_gallons:.2f} gallons")
        print(f"  Period: {draw_period} seconds")
        print(f"  Valves: {', '.join(solenoids)}")
        print(f"  Test elapsed: {test_elapsed/3600:.2f} hours")

        # Record draw start
        draw_start_time = now()
        draw_start_pulses = get_current_pulses()

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 1: Draw water until target reached
        # ═══════════════════════════════════════════════════════════════════

        open_valves(solenoids)

        draw_complete = False
        draw_aborted = False
        gallons_this_draw = 0

        while session.active and not draw_complete and not draw_aborted:
            current_pulses = get_current_pulses()
            pulses_this_draw = current_pulses - draw_start_pulses
            gallons_this_draw = pulses_to_gallons(pulses_this_draw)

            draw_elapsed = elapsed_since(draw_start_time)

            # Update flow rate for safety monitoring
            flow_rate_pulses = flow_rate_calc.update(current_pulses)
            flow_rate_gpm = pulses_to_gallons(flow_rate_pulses) * 60  # Convert to GPM

            # Publish live values
            publish('DrawNumber', draw_number)
            publish('DrawTarget', target_gallons, units='gal')
            publish('DrawCurrent', gallons_this_draw, units='gal')
            publish('DrawProgress', min(100, (gallons_this_draw / target_gallons) * 100), units='%')
            publish('FlowRate', flow_rate_gpm, units='GPM')
            publish('DrawElapsed', draw_elapsed, units='s')
            publish('TestProgress', (test_elapsed / (TEST_DURATION_HOURS * 3600)) * 100, units='%')
            publish('TotalGallons', total_gallons_drawn + gallons_this_draw, units='gal')

            # Check if target reached
            if gallons_this_draw >= target_gallons:
                draw_complete = True
                print(f"  [TARGET REACHED] {gallons_this_draw:.2f} gal in {draw_elapsed:.1f}s")
                break

            # Safety: Max draw time exceeded
            if draw_elapsed > MAX_DRAW_TIME_SECONDS:
                draw_aborted = True
                print(f"  [SAFETY] Max draw time exceeded! Got {gallons_this_draw:.2f} gal")
                break

            # Safety: Check for no flow (after initial delay)
            if draw_elapsed > FLOW_CHECK_DELAY and flow_rate_gpm < MIN_FLOW_RATE_GPM:
                draw_aborted = True
                print(f"  [SAFETY] No flow detected! Rate: {flow_rate_gpm:.2f} GPM")
                break

            await next_scan()

        # Close valves
        close_valves()

        # Update totals
        total_gallons_drawn += gallons_this_draw
        total_draws_completed += 1

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 2: Wait for remainder of draw period
        # ═══════════════════════════════════════════════════════════════════

        draw_elapsed = elapsed_since(draw_start_time)
        wait_time = draw_period - draw_elapsed

        if wait_time > 0:
            print(f"  Waiting {wait_time:.1f}s until next draw...")

            while session.active and elapsed_since(draw_start_time) < draw_period:
                # Update published values during wait
                remaining = draw_period - elapsed_since(draw_start_time)
                publish('WaitRemaining', max(0, remaining), units='s')
                publish('DrawStatus', 0)  # 0 = waiting

                # Update test progress
                current_test_elapsed = elapsed_since(test_start_time)
                publish('TestProgress', (current_test_elapsed / (TEST_DURATION_HOURS * 3600)) * 100, units='%')

                await next_scan()

        # Move to next draw in schedule (cycle back to start if needed)
        schedule_index = (schedule_index + 1) % len(DRAW_SCHEDULE)

        print(f"  Draw #{draw_number} complete. Total: {total_gallons_drawn:.2f} gal")

finally:
    # ═══════════════════════════════════════════════════════════════════
    # CLEANUP - Always close valves when script stops
    # ═══════════════════════════════════════════════════════════════════
    close_valves()
    print(f"")
    print(f"[{time_of_day()}] Script stopped. Valves closed.")
    print(f"  Total draws: {total_draws_completed}")
    print(f"  Total gallons: {total_gallons_drawn:.2f}")
