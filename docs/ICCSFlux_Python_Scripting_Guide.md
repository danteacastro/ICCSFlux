# Python Scripting in CZFlux

Run custom Python scripts directly in your browser to process data from cDAQ, cRIO, and Opto22 hardware, control outputs, calculate derived values, and automate sequences.

## Overview

CZFlux includes **Pyodide** - a complete Python interpreter running in WebAssembly. This means you can write real Python code that:

- Reads live channel data from **any hardware source** (cDAQ, cRIO, Opto22)
- Controls digital and analog outputs across all connected nodes
- Publishes computed values that appear as new tags
- Runs synchronized loops with your scan cycle
- Performs unit conversions and calculations
- Automates sequences and schedules

> **Multi-Hardware Support**: Scripts access all channels uniformly through the `tags` object, regardless of whether they come from local cDAQ hardware, remote cRIO nodes, or Opto22 groov devices. The hardware source is transparent to your scripts.

---

## Getting Started

1. Navigate to **Playground** tab
2. Click the **Python** subtab
3. Click **+ New Script** to create your first script
4. Write your code and click **▶ Run**

### Your First Script

```python
# Read a temperature and publish a converted value
while session.active:
    temp_f = tags.TC001
    temp_c = F_to_C(temp_f)
    publish('TempC', temp_c, units='°C')
    await next_scan()
```

---

## Imports and Initialization

Your script code runs inside an async function. Any code **before** the `while session.active:` loop executes once when the script starts. This is where you put imports and initialization.

### Script Structure

```python
# ═══════════════════════════════════════════════════════════════════
# IMPORTS - execute once at script start
# ═══════════════════════════════════════════════════════════════════
import numpy as np
from collections import deque
import math

# ═══════════════════════════════════════════════════════════════════
# INITIALIZATION - execute once before loop starts
# ═══════════════════════════════════════════════════════════════════
my_buffer = deque(maxlen=100)
accumulator = 0
rate_calc = RateCalculator()
calibration_offset = 2.5

# ═══════════════════════════════════════════════════════════════════
# MAIN LOOP - runs repeatedly synchronized with scan cycle
# ═══════════════════════════════════════════════════════════════════
while session.active:
    temp = tags.TC001 + calibration_offset
    my_buffer.append(temp)

    avg = np.mean(list(my_buffer))
    publish('RollingAvg', avg, units='F')

    await next_scan()
```

### Pre-loaded (No Import Needed)

These are available immediately without imports:

| Category | Available |
|----------|-----------|
| **Core** | `tags`, `session`, `outputs`, `publish`, `next_scan`, `wait_for`, `wait_until` |
| **Time** | `now`, `now_ms`, `now_iso`, `time_of_day`, `elapsed_since`, `format_timestamp` |
| **Conversions** | `F_to_C`, `C_to_F`, `GPM_to_LPM`, `PSI_to_bar`, `gal_to_L`, `BTU_to_kJ`, `lb_to_kg`, etc. |
| **Helpers** | `RateCalculator`, `Accumulator`, `EdgeDetector`, `RollingStats`, `Scheduler` |
| **NumPy** | Pre-loaded by Pyodide (just `import numpy as np`) |

### Importing CSV/Excel Data

Use the **Import Data** button in the Python tab UI to import CSV files. The data becomes a variable in your script namespace automatically:

```python
# If you imported "calibration.csv" as variable "cal_data":
# cal_data is available as a list of dicts - no import statement needed!

# Use the data in initialization
offset_table = {row['channel']: row['offset'] for row in cal_data}

while session.active:
    raw = tags.TC001
    corrected = raw + offset_table.get('TC001', 0)
    publish('TC001_Corrected', corrected)
    await next_scan()
```

### Complete Example with Imports

```python
# Imports
import numpy as np
from scipy import signal

# Initialization - create filter coefficients once
CUTOFF_FREQ = 0.1  # Normalized frequency
b, a = signal.butter(4, CUTOFF_FREQ, 'low')
filter_state = signal.lfilter_zi(b, a) * 0

# Buffer for filtering
data_buffer = []

while session.active:
    # Collect sample
    data_buffer.append(tags.TC001)

    # Apply filter when we have enough samples
    if len(data_buffer) >= 10:
        filtered, filter_state = signal.lfilter(b, a, data_buffer, zi=filter_state)
        publish('TC001_Filtered', filtered[-1], units='°F')
        data_buffer.clear()

    await next_scan()
```

---

## Available Libraries

The following Python packages are pre-loaded and ready to use:

### NumPy
```python
import numpy as np

# Array operations
data = np.array([1, 2, 3, 4, 5])
mean = np.mean(data)
std = np.std(data)

# Signal generation
t = np.linspace(0, 1, 1000)
signal = np.sin(2 * np.pi * 10 * t)
```

### SciPy
```python
from scipy import signal
from scipy.fft import fft, fftfreq

# Low-pass filter
b, a = signal.butter(4, 0.1, 'low')
filtered = signal.filtfilt(b, a, data)

# FFT analysis
spectrum = fft(data)
freqs = fftfreq(len(data), d=1/sample_rate)

# Peak detection
peaks, _ = signal.find_peaks(data, height=threshold)
```

### Standard Library
Python's standard library is fully available:
- `time` - timestamps, delays
- `math` - mathematical functions
- `json` - JSON parsing
- `re` - regular expressions
- `collections` - specialized containers
- `itertools` - iteration utilities

---

## Reading Channel Data

Access any channel using the `tags` object. Channels from all hardware sources (cDAQ, cRIO, Opto22) are available through the same interface.

### Attribute Access
```python
temp = tags.TC001          # Local cDAQ thermocouple
pressure = tags.PT001      # cRIO pressure sensor
flow = tags.FT001          # Opto22 flow meter
```

### Dictionary Access
```python
temp = tags['TC001']
pressure = tags['PT-001']  # Use for names with dashes
```

### Hardware-Agnostic Access
Scripts don't need to know which hardware a channel comes from:
```python
# These all work the same regardless of source
inlet_temp = tags.Inlet_Temp      # Could be cDAQ, cRIO, or Opto22
outlet_temp = tags.Outlet_Temp    # Hardware source is transparent
delta_t = outlet_temp - inlet_temp
publish('DeltaT', delta_t, units='°F')
```

### Get All Channel Names
```python
for name in tags.keys():
    print(f"{name}: {tags[name]}")
```

### Safe Access with Default
```python
value = tags.get('MaybeExists', default=0.0)
```

### Check if Tag Exists
```python
if 'TC001' in tags:
    temp = tags.TC001

# Or use exists()
if tags.exists('TC001'):
    temp = tags.TC001
```

### List All Available Tags
```python
print(tags.keys())  # ['TC001', 'PT001', 'py.Efficiency', ...]
```

### Timestamp Access

Get the backend acquisition timestamp for accurate timing:
```python
# Get timestamp (Unix milliseconds from backend)
ts = tags.timestamp('TC001')
print(f"TC001 acquired at {ts} ms")

# Get value and timestamp together (more efficient)
value, timestamp = tags.get_with_timestamp('TC001')
print(f"TC001 = {value} at {timestamp} ms")

# Get data age in seconds (time since acquisition)
age = tags.age('TC001')
if age > 5.0:
    print("Warning: TC001 data is stale!")
```

The timestamps come from the backend (or remote node), not the browser, so they're accurate to the actual acquisition time. This is useful for:
- Calculating precise rates of change
- Detecting stale data
- Correlating events across channels
- Logging with accurate timestamps

### Validation
Tags are automatically validated. If you access a tag that doesn't exist, you'll see a warning in the console:
```
Warning: Unknown tag: "TC999" - available: TC001, TC002, PT001...
```

---

## Controlling Outputs

Use the `outputs` object to control digital and analog outputs.

### Set a Digital Output
```python
outputs.set('Valve_1', True)   # Turn ON
outputs.set('Valve_1', False)  # Turn OFF
```

### Set an Analog Output
```python
outputs.set('Heater_SP', 75.0)
outputs.set('Speed_Cmd', 1500)
```

### Dictionary Style
```python
outputs['Pump_1'] = True
outputs['Flow_SP'] = 10.5
```

---

## Publishing Computed Values

Create new "tags" from calculated values. Published values appear as `py.YourName` and can be used in widgets.

### Basic Publish
```python
publish('Efficiency', 92.5)
```

### With Units
```python
publish('Efficiency', 92.5, units='%')
```

### With Description
```python
publish('HeatRate', 1250.3, units='BTU/hr', description='Calculated heat transfer rate')
```

### Publish Validation
Published values are automatically validated:

```python
# ✅ Valid names
publish('Efficiency', 92.5)
publish('Heat_Rate', 1250)
publish('_internal', 0)

# ❌ Invalid - will show error
publish('Heat-Rate', 100)   # No dashes allowed
publish('123abc', 100)      # Can't start with number
publish('py.Value', 100)    # Don't use py. prefix
publish('TC001', 100)       # Can't conflict with hardware channel
publish('Rate', 'text')     # Value must be a number
```

### Published Tags
Published values are available as tags with the `py.` prefix:
- `publish('Efficiency', 92.5)` → Available as `py.Efficiency`
- Use in widgets, calculated parameters, or other scripts

### Recording Published Values
Published values integrate with the CZFlux recording system:

1. Go to **Recording** tab
2. Published values appear in the channel list as `py.YourName`
3. Select them like any hardware channel
4. They're recorded alongside hardware data in the same CSV/database

This means calculated values are timestamped and logged with your raw sensor data.

---

## Session Control

Scripts run while the acquisition session is active. You can also control the session from within your scripts.

### Main Loop Pattern
```python
while session.active:
    # Your processing code here
    await next_scan()  # Wait for next scan cycle
```

### Session Properties
```python
session.active    # True if acquisition is running
session.elapsed   # Seconds since session started
session.recording # True if currently recording to file
```

### Session Control Methods
Control the acquisition and recording from your scripts:

```python
# Start/Stop acquisition
session.start()           # Start data acquisition
session.stop()            # Stop data acquisition

# Start/Stop recording
session.start_recording()           # Start recording to file
session.start_recording('test.csv') # Start with custom filename
session.stop_recording()            # Stop recording
```

### Timed Recording Example
```python
# Record for 60 seconds, then stop
RECORD_DURATION = 60

session.start_recording('my_test.csv')
start_time = now()

while session.active:
    elapsed = elapsed_since(start_time)

    if elapsed >= RECORD_DURATION:
        session.stop_recording()
        print(f"Recorded {RECORD_DURATION}s of data")
        break

    await next_scan()
```

### Conditional Recording Example
```python
# Only record when conditions are met
recording = False

while session.active:
    temp = tags.TC001

    # Start recording on high temperature
    if not recording and temp > 150:
        session.start_recording()
        recording = True
        print("Recording started - high temp detected")

    # Stop recording when temp returns to normal
    elif recording and temp < 140:
        session.stop_recording()
        recording = False
        print("Recording stopped - temp normalized")

    await next_scan()
```

### Important
- Always use `await next_scan()` in your loop
- Scripts automatically stop when session ends
- Click **■ Stop** to manually stop a script
- Use session control methods sparingly - they affect the entire system

---

## Timing and Time Functions

### Wait Functions

**Wait for Next Scan** - Synchronizes with the data acquisition scan cycle:
```python
await next_scan()
```

**Wait for Duration** - Pause for a specific time:
```python
await wait_for(5.0)  # Wait 5 seconds
```

**Wait Until Condition** - Wait until a condition is true:
```python
# Wait until temperature exceeds 150°F
await wait_until(lambda: tags.TC001 > 150)

# With timeout (returns True if condition met, False if timeout)
reached = await wait_until(lambda: tags.TC001 > 150, timeout=60)
if not reached:
    print("Timeout waiting for temperature")
```

### Current Time

```python
# Unix timestamp in seconds (float)
ts = now()                    # e.g., 1704299400.123

# Unix timestamp in milliseconds (integer)
ts_ms = now_ms()              # e.g., 1704299400123

# ISO 8601 formatted string
iso = now_iso()               # e.g., "2024-01-03T14:30:00.123456"

# Time of day as HH:MM:SS
tod = time_of_day()           # e.g., "14:30:00"
```

### Elapsed Time
```python
start = now()

while session.active:
    # ... do work ...

    elapsed = elapsed_since(start)
    print(f"Running for {elapsed:.1f} seconds")

    if elapsed > 300:
        print("5 minutes elapsed, stopping")
        break

    await next_scan()
```

### Formatting Timestamps
```python
# Format a millisecond timestamp to string
ts_ms = now_ms()
formatted = format_timestamp(ts_ms)  # "2024-01-03 14:30:00"

# Custom format
formatted = format_timestamp(ts_ms, fmt="%Y-%m-%d")  # "2024-01-03"
formatted = format_timestamp(ts_ms, fmt="%H:%M:%S")  # "14:30:00"
```

### Practical Examples

**Timestamped Logging:**
```python
while session.active:
    temp = tags.TC001

    if temp > 200:
        print(f"[{now_iso()}] HIGH TEMP: {temp}°F")

    await next_scan()
```

**Scheduled Tasks:**
```python
last_log = now()
LOG_INTERVAL = 60  # Log every 60 seconds

while session.active:
    if elapsed_since(last_log) >= LOG_INTERVAL:
        print(f"[{time_of_day()}] TC001={tags.TC001:.1f}°F")
        last_log = now()

    await next_scan()
```

**Timed Test with Progress:**
```python
TEST_DURATION = 300  # 5 minutes
start = now()

while session.active:
    elapsed = elapsed_since(start)
    remaining = TEST_DURATION - elapsed
    progress = (elapsed / TEST_DURATION) * 100

    publish('TestProgress', round(progress, 1), units='%')
    publish('TimeRemaining', round(remaining), units='s')

    if elapsed >= TEST_DURATION:
        print(f"Test complete at {time_of_day()}")
        session.stop_recording()
        break

    await next_scan()
```

---

## Unit Conversions

Built-in functions for common unit conversions:

### Temperature
```python
temp_c = F_to_C(tags.TC001)      # Fahrenheit to Celsius
temp_f = C_to_F(temp_celsius)    # Celsius to Fahrenheit
```

### Flow
```python
flow_lpm = GPM_to_LPM(tags.FT001)  # Gallons/min to Liters/min
flow_gpm = LPM_to_GPM(flow_lpm)    # Liters/min to Gallons/min
```

### Pressure
```python
press_bar = PSI_to_bar(tags.PT001)  # PSI to Bar
press_psi = bar_to_PSI(press_bar)   # Bar to PSI
```

### Volume
```python
liters = gal_to_L(gallons)    # Gallons to Liters
gallons = L_to_gal(liters)    # Liters to Gallons
```

### Energy
```python
kj = BTU_to_kJ(btu)           # BTU to Kilojoules
btu = kJ_to_BTU(kj)           # Kilojoules to BTU
```

### Mass
```python
kg = lb_to_kg(pounds)         # Pounds to Kilograms
lb = kg_to_lb(kilograms)      # Kilograms to Pounds
```

---

## Derived Value Helpers

Pre-built classes for common calculations.

### Rate Calculator
Calculate rate of change over a time window:
```python
flow_rate = RateCalculator(window_seconds=60)

while session.active:
    counter = tags.FlowCounter
    gpm = flow_rate.update(counter)  # Returns rate in units/second
    publish('FlowGPM', gpm * 60, units='GPM')  # Convert to per-minute
    await next_scan()
```

### Accumulator
Track cumulative totals from counter values:
```python
total_flow = Accumulator(initial=0)

while session.active:
    counter = tags.FlowCounter
    total = total_flow.update(counter)
    publish('TotalGallons', total, units='gal')
    await next_scan()

# Reset if needed
total_flow.reset()
```

### Edge Detector
Detect rising and falling edges:
```python
pump_edge = EdgeDetector(threshold=0.5)

while session.active:
    pump_on = tags.Pump_Status
    rising, falling, state = pump_edge.update(pump_on)

    if rising:
        print("Pump started!")
    if falling:
        print("Pump stopped!")

    await next_scan()
```

### Rolling Statistics
Calculate running statistics over a sample window:
```python
temp_stats = RollingStats(window_size=100)

while session.active:
    stats = temp_stats.update(tags.TC001)
    publish('TempAvg', stats['mean'], units='°F')
    publish('TempMin', stats['min'], units='°F')
    publish('TempMax', stats['max'], units='°F')
    publish('TempStd', stats['std'], units='°F')
    await next_scan()
```

---

## Scheduler

The `Scheduler` class provides APScheduler-like job scheduling for timed operations.

### Creating a Scheduler
```python
scheduler = Scheduler()
```

### Interval Jobs
Run a function at fixed intervals:
```python
def log_temps():
    print(f"Temp: {tags.TC001:.1f}°F")

# Run every 60 seconds
scheduler.add_interval('temp_log', seconds=60, func=log_temps)

# Run every 5 minutes
scheduler.add_interval('status', minutes=5, func=check_status)

# Run every 2 hours
scheduler.add_interval('report', hours=2, func=generate_report)
```

### Cron-Like Jobs
Run at specific times:
```python
def daily_report():
    print("Generating daily report...")

# Run at 3:00 PM every day
scheduler.add_cron('daily', hour=15, minute=0, func=daily_report)

# Run at the top of every hour
scheduler.add_cron('hourly', minute=0, func=hourly_check)

# Run every Monday at 8:00 AM (day_of_week: 0=Mon, 6=Sun)
scheduler.add_cron('weekly', hour=8, minute=0, day_of_week=0, func=weekly_report)
```

### One-Shot Delayed Jobs
Run once after a delay:
```python
def start_sequence():
    print("Starting delayed sequence...")
    outputs.set('Pump', True)

# Run once after 30 seconds
scheduler.add_once('delayed_start', delay=30, func=start_sequence)
```

### Job Control
```python
# Pause a job
scheduler.pause('temp_log')

# Resume a paused job
scheduler.resume('temp_log')

# Remove a job
scheduler.remove('hourly')

# Check if paused
if scheduler.is_paused('temp_log'):
    print("Job is paused")

# Get all jobs status
jobs = scheduler.get_jobs()
# {'temp_log': {'type': 'interval', 'paused': False, 'run_count': 5}, ...}
```

### Running the Scheduler
Call `tick()` in your main loop to check and run due jobs:
```python
scheduler = Scheduler()
scheduler.add_interval('log', seconds=10, func=my_log_function)

while session.active:
    # Your normal processing
    temp = tags.TC001
    publish('Temp', temp)

    # Check and run scheduled jobs
    await scheduler.tick()

    await next_scan()
```

### Complete Scheduler Example
```python
# Multi-schedule monitoring script
scheduler = Scheduler()

def log_current_values():
    print(f"TC001={tags.TC001:.1f}°F, PT001={tags.PT001:.1f} PSI")

def generate_hourly_stats():
    print(f"=== Hourly Stats at {session.elapsed:.0f}s ===")

def start_pump_after_warmup():
    print("Warmup complete, starting pump")
    outputs.set('MainPump', True)

# Log every 30 seconds
scheduler.add_interval('logging', seconds=30, func=log_current_values)

# Stats at top of each hour
scheduler.add_cron('hourly_stats', minute=0, func=generate_hourly_stats)

# Start pump 60 seconds after script starts
scheduler.add_once('pump_start', delay=60, func=start_pump_after_warmup)

while session.active:
    # Normal processing
    temp = tags.TC001

    # High temp protection
    if temp > 200:
        scheduler.pause('pump_start')  # Don't start pump if too hot

    await scheduler.tick()
    await next_scan()
```

---

## Example Scripts

### Temperature Monitor with Alarm
```python
# Monitor temperature and set alarm output
HIGH_LIMIT = 180.0
LOW_LIMIT = 50.0

while session.active:
    temp = tags.TC001

    # Check limits
    high_alarm = temp > HIGH_LIMIT
    low_alarm = temp < LOW_LIMIT

    # Set outputs
    outputs.set('HighTempAlarm', high_alarm)
    outputs.set('LowTempAlarm', low_alarm)

    # Publish status
    publish('TempStatus', 1 if high_alarm else (-1 if low_alarm else 0))

    await next_scan()
```

### Flow Totalizer
```python
# Calculate flow rate and total from counter
flow_calc = RateCalculator(window_seconds=10)
flow_total = Accumulator()

while session.active:
    counter = tags.FlowCounter

    # Calculate rate (pulses per second → GPM)
    # Assuming 100 pulses per gallon
    pulses_per_sec = flow_calc.update(counter)
    gpm = pulses_per_sec / 100 * 60

    # Accumulate total
    total_gal = flow_total.update(counter) / 100

    publish('FlowRate', gpm, units='GPM')
    publish('TotalFlow', total_gal, units='gal')

    await next_scan()
```

### Valve Cycling Sequence
```python
# Cycle valves every 30 seconds
CYCLE_TIME = 30.0

valve_state = False

while session.active:
    # Toggle valve
    valve_state = not valve_state
    outputs.set('CycleValve', valve_state)

    print(f"Valve {'OPEN' if valve_state else 'CLOSED'}")

    # Wait for cycle time
    await wait_for(CYCLE_TIME)
```

### Heat Transfer Calculation
```python
# Calculate heat transfer rate: Q = m * Cp * ΔT
# Flow in GPM, temps in °F
CP_WATER = 1.0  # BTU/(lb·°F)
DENSITY = 8.34  # lb/gal

while session.active:
    flow_gpm = tags.FlowRate
    temp_in = tags.TempIn
    temp_out = tags.TempOut

    # Mass flow rate (lb/min)
    mass_flow = flow_gpm * DENSITY

    # Temperature difference
    delta_t = temp_out - temp_in

    # Heat rate (BTU/min → BTU/hr)
    q_btu_hr = mass_flow * CP_WATER * delta_t * 60

    publish('HeatRate', q_btu_hr, units='BTU/hr')
    publish('DeltaT', delta_t, units='°F')

    await next_scan()
```

### Efficiency Calculator
```python
# Calculate system efficiency from power measurements
while session.active:
    power_in = tags.PowerInput
    power_out = tags.PowerOutput

    if power_in > 0:
        efficiency = (power_out / power_in) * 100
    else:
        efficiency = 0

    publish('Efficiency', efficiency, units='%')

    await next_scan()
```

### Scheduled Data Logging
```python
# Log data every 5 minutes
import time

LOG_INTERVAL = 300  # 5 minutes in seconds
last_log = time.time()

while session.active:
    now = time.time()

    if now - last_log >= LOG_INTERVAL:
        # Log current values
        print(f"=== Log at {session.elapsed:.1f}s ===")
        print(f"  TC001: {tags.TC001:.2f}°F")
        print(f"  PT001: {tags.PT001:.2f} PSI")
        print(f"  FT001: {tags.FT001:.2f} GPM")

        last_log = now

    await next_scan()
```

### Multi-Stage Sequence
```python
# Run a multi-stage test sequence
stages = [
    {'name': 'Preheat', 'setpoint': 100, 'duration': 60},
    {'name': 'Ramp', 'setpoint': 200, 'duration': 120},
    {'name': 'Soak', 'setpoint': 200, 'duration': 300},
    {'name': 'Cool', 'setpoint': 70, 'duration': 180},
]

for i, stage in enumerate(stages):
    if not session.active:
        break

    print(f"Stage {i+1}: {stage['name']}")
    outputs.set('TempSetpoint', stage['setpoint'])
    publish('CurrentStage', i + 1)
    publish('StageName', stage['name'])

    await wait_for(stage['duration'])

print("Sequence complete!")
outputs.set('TempSetpoint', 70)  # Return to safe value
```

### Multi-Node Data Aggregation
```python
# Aggregate data from multiple remote nodes (cRIO + Opto22)
# All channels accessible through the same tags interface

while session.active:
    # Read from different hardware sources
    crio_temp = tags.CRIO_TC001       # cRIO thermocouple
    opto_temp = tags.OPTO_TempIn      # Opto22 analog input
    local_temp = tags.TC001           # Local cDAQ

    # Calculate average across all nodes
    avg_temp = (crio_temp + opto_temp + local_temp) / 3
    publish('SystemAvgTemp', avg_temp, units='°F')

    # Monitor spread between nodes (quality check)
    temps = [crio_temp, opto_temp, local_temp]
    spread = max(temps) - min(temps)
    publish('TempSpread', spread, units='°F')

    if spread > 10:
        print(f"Warning: Large temperature spread ({spread:.1f}°F)")

    await next_scan()
```

### Cross-Node Control
```python
# Control outputs on different hardware nodes
# Works the same regardless of hardware type

while session.active:
    master_temp = tags.MasterTC  # Primary sensor (any node)

    # Control outputs on different nodes
    if master_temp > 180:
        outputs.set('CRIO_Alarm', True)      # cRIO digital output
        outputs.set('OPTO_CoolValve', True)  # Opto22 relay
        outputs.set('LocalFan', True)        # cDAQ digital output
    else:
        outputs.set('CRIO_Alarm', False)
        outputs.set('OPTO_CoolValve', False)
        outputs.set('LocalFan', False)

    await next_scan()
```

### Remote Node Health Monitoring
```python
# Monitor data freshness from remote nodes
STALE_THRESHOLD = 5.0  # seconds

while session.active:
    # Check data age for remote node channels
    crio_age = tags.age('CRIO_TC001')
    opto_age = tags.age('OPTO_TempIn')

    # Publish node health status
    crio_healthy = 1 if crio_age < STALE_THRESHOLD else 0
    opto_healthy = 1 if opto_age < STALE_THRESHOLD else 0

    publish('CRIO_NodeHealth', crio_healthy)
    publish('OPTO_NodeHealth', opto_healthy)

    if crio_age >= STALE_THRESHOLD:
        print(f"Warning: cRIO data stale ({crio_age:.1f}s)")
    if opto_age >= STALE_THRESHOLD:
        print(f"Warning: Opto22 data stale ({opto_age:.1f}s)")

    await next_scan()
```

---

## Using Published Values

### In Widgets
Published values appear in channel dropdowns with the `py.` prefix:
- Create a Gauge widget
- Select channel: `py.Efficiency`
- The widget displays your calculated value in real-time

### In Other Scripts
Access published values from the same `tags` object:
```python
# Script 1 publishes
publish('CalcValue', 123.4)

# Script 2 can read it (after a scan cycle)
value = tags.get('py.CalcValue', default=0)
```

### In Calculated Parameters
Published values can be used in the Calculated Parameters feature just like any other channel.

---

## Error Handling

Scripts run inside an async function with automatic error catching. Use try/except for graceful error handling.

### Basic Error Handling
```python
while session.active:
    try:
        temp = tags.TC001
        pressure = tags.PT001

        # This could fail if pressure is 0
        ratio = temp / pressure
        publish('TempPressureRatio', ratio)

    except ZeroDivisionError:
        publish('TempPressureRatio', 0)
        print("Warning: Division by zero avoided")
    except Exception as e:
        print(f"Error: {e}")

    await next_scan()
```

### Safe Resource Cleanup
Use `try/finally` to ensure outputs are reset when script stops:
```python
try:
    outputs.set('HeaterEnable', True)
    outputs.set('PumpEnable', True)

    while session.active:
        # Control logic here
        await next_scan()

finally:
    # Always runs when script stops (manual stop, error, or session end)
    outputs.set('HeaterEnable', False)
    outputs.set('PumpEnable', False)
    print("Outputs safely disabled")
```

### Handling Missing Tags
```python
while session.active:
    # Safe way to handle optional tags
    if tags.exists('OptionalSensor'):
        value = tags.OptionalSensor
    else:
        value = 0  # Default when sensor not configured

    # Or use get() with default
    value = tags.get('OptionalSensor', default=0)

    await next_scan()
```

### Timeout Protection
```python
# Avoid infinite waits
try:
    # Wait max 60 seconds for temperature to reach setpoint
    reached = await wait_until(lambda: tags.TC001 > 150, timeout=60)

    if reached:
        print("Temperature reached!")
    else:
        print("Timeout - temperature did not reach setpoint")
        outputs.set('Alarm', True)
except Exception as e:
    print(f"Wait failed: {e}")
```

---

## Best Practices

### Always Use `await next_scan()`
Without this, your script won't yield and may freeze the browser:
```python
# ✅ Good
while session.active:
    # work
    await next_scan()

# ❌ Bad - will freeze
while session.active:
    # work (no await)
```

### Handle Division by Zero
```python
if denominator != 0:
    result = numerator / denominator
else:
    result = 0
```

### Use Descriptive Published Names
```python
# ✅ Good
publish('TotalGallonsToday', total, units='gal')

# ❌ Less clear
publish('val1', total)
```

### Clean Up in Finally Block
```python
try:
    while session.active:
        outputs.set('Running', True)
        await next_scan()
finally:
    outputs.set('Running', False)
```

### Limit Print Statements
Too many prints can slow down the console:
```python
# Print every 100 iterations instead of every scan
if iteration % 100 == 0:
    print(f"Status: {value}")
```

### Initialize Variables Before Loop
```python
# ✅ Good - initialized once
counter = 0
buffer = []

while session.active:
    counter += 1
    buffer.append(tags.TC001)
    await next_scan()

# ❌ Bad - resets every iteration
while session.active:
    counter = 0  # Always 0!
    await next_scan()
```

---

## Troubleshooting

### Script Won't Start
- Check for syntax errors in the console output panel
- Ensure Pyodide has finished loading (first load takes ~5 seconds)
- Look for red error messages in the script output

### Values Not Updating
- Make sure you're using `await next_scan()` in your loop
- Check that the acquisition session is running (green status indicator)
- Verify the tag name matches exactly (case-sensitive)

### Published Values Not Appearing
- Values appear after the first `publish()` call
- Refresh widget channel list to see new values
- Check for validation errors in console (invalid names, etc.)

### Script Runs Slowly
- Reduce print statements (console output is expensive)
- Use `await wait_for()` if you don't need every scan
- Complex calculations may need optimization
- Large arrays consume memory - use fixed-size buffers

### Debugging Tips

**Check what tags are available:**
```python
print("Available tags:", tags.keys())
```

**Log values periodically:**
```python
iteration = 0
while session.active:
    iteration += 1

    if iteration % 100 == 0:
        print(f"[{iteration}] TC001={tags.TC001:.2f}")

    await next_scan()
```

**Test conditions:**
```python
temp = tags.TC001
print(f"temp={temp}, type={type(temp)}, >100? {temp > 100}")
```

**Check timing:**
```python
start = now()
# ... your code ...
elapsed = elapsed_since(start)
print(f"Operation took {elapsed*1000:.1f} ms")
```

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown tag: "XYZ"` | Tag doesn't exist | Check spelling, use `tags.keys()` |
| `Script froze browser` | Missing `await next_scan()` | Add await in your loop |
| `Value must be a number` | Publishing string/None | Convert to float: `float(value)` |
| `Invalid name` | Bad publish name | Use letters, numbers, underscore only |

---

## Limitations

- **Browser-based**: Scripts run in the browser, not on a server
- **No file I/O**: Cannot read/write files directly (use MQTT for data export)
- **Single thread**: Long calculations may affect UI responsiveness
- **Memory**: Large data arrays may consume browser memory
- **Network latency**: Remote node data (cRIO, Opto22) has minimal additional latency (~5-10ms on wired Ethernet), typically negligible compared to scan intervals

---

## API Reference

### Objects
| Object | Description |
|--------|-------------|
| `tags` | Read channel values from any hardware (cDAQ, cRIO, Opto22): `tags.TC001` or `tags['TC001']` |
| `tags.timestamp(name)` | Get backend acquisition timestamp (Unix ms) |
| `tags.get_with_timestamp(name)` | Get `(value, timestamp)` tuple |
| `tags.age(name)` | Get data age in seconds (useful for remote node health monitoring) |
| `session` | Session state and control (see below) |
| `outputs` | Control outputs on any node: `outputs.set('name', value)` |

### Session Object
| Property/Method | Description |
|-----------------|-------------|
| `session.active` | True if acquisition is running |
| `session.elapsed` | Seconds since session started |
| `session.recording` | True if currently recording to file |
| `session.start()` | Start data acquisition |
| `session.stop()` | Stop data acquisition |
| `session.start_recording(filename?)` | Start recording (optional filename) |
| `session.stop_recording()` | Stop recording |

### Functions
| Function | Description |
|----------|-------------|
| `publish(name, value, units='', description='')` | Create a computed tag |
| `await next_scan()` | Wait for next scan cycle |
| `await wait_for(seconds)` | Wait for duration |
| `await wait_until(condition, timeout=0)` | Wait for condition |

### Time Functions
| Function | Description |
|----------|-------------|
| `now()` | Unix timestamp in seconds (float) |
| `now_ms()` | Unix timestamp in milliseconds (int) |
| `now_iso()` | Current time as ISO 8601 string |
| `time_of_day()` | Current time as "HH:MM:SS" |
| `format_timestamp(ts_ms, fmt?)` | Format millisecond timestamp to string |
| `elapsed_since(start_ts)` | Seconds elapsed since start_ts (in seconds) |

### Unit Conversions
| Function | Conversion |
|----------|------------|
| `F_to_C(f)` | Fahrenheit → Celsius |
| `C_to_F(c)` | Celsius → Fahrenheit |
| `GPM_to_LPM(gpm)` | Gallons/min → Liters/min |
| `LPM_to_GPM(lpm)` | Liters/min → Gallons/min |
| `PSI_to_bar(psi)` | PSI → Bar |
| `bar_to_PSI(bar)` | Bar → PSI |
| `gal_to_L(gal)` | Gallons → Liters |
| `L_to_gal(L)` | Liters → Gallons |
| `BTU_to_kJ(btu)` | BTU → Kilojoules |
| `kJ_to_BTU(kj)` | Kilojoules → BTU |
| `lb_to_kg(lb)` | Pounds → Kilograms |
| `kg_to_lb(kg)` | Kilograms → Pounds |

### Helper Classes
| Class | Description |
|-------|-------------|
| `RateCalculator(window_seconds)` | Calculate rate of change |
| `Accumulator(initial=0)` | Track cumulative totals |
| `EdgeDetector(threshold=0.5)` | Detect rising/falling edges |
| `RollingStats(window_size)` | Calculate running statistics |
| `Scheduler()` | APScheduler-like job scheduling |

---

## Future Enhancements (Planned)

- `alarm.trigger()` / `alarm.clear()` - Raise system alarms from scripts
- `system.shutdown()` - Trigger controlled shutdown
- Additional Python packages (Pandas for data analysis)
- Script debugging tools (breakpoints, step-through)
