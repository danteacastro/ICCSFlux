# Python Scripting in DCFlux

Run custom Python scripts directly in your browser to process cDAQ data, control outputs, calculate derived values, and automate sequences.

## Overview

DCFlux includes **Pyodide** - a complete Python interpreter running in WebAssembly. This means you can write real Python code that:

- Reads live channel data from your cDAQ
- Controls digital and analog outputs
- Publishes computed values that appear as new tags
- Runs synchronized loops with your scan cycle
- Performs unit conversions and calculations
- Automates sequences and schedules

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

## Reading Channel Data

Access any cDAQ channel using the `tags` object.

### Attribute Access
```python
temp = tags.TC001
pressure = tags.PT001
flow = tags.FT001
```

### Dictionary Access
```python
temp = tags['TC001']
pressure = tags['PT-001']  # Use for names with dashes
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
# Get timestamp (Unix milliseconds from cDAQ backend)
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

The timestamps come from the cDAQ backend, not the browser, so they're accurate to the actual acquisition time. This is useful for:
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
Published values integrate with the DCFlux recording system:

1. Go to **Recording** tab
2. Published values appear in the channel list as `py.YourName`
3. Select them like any hardware channel
4. They're recorded alongside hardware data in the same CSV/database

This means calculated values are timestamped and logged with your raw sensor data.

---

## Session Control

Scripts run while the acquisition session is active.

### Main Loop Pattern
```python
while session.active:
    # Your processing code here
    await next_scan()  # Wait for next cDAQ scan
```

### Session Properties
```python
session.active   # True if acquisition is running
session.elapsed  # Seconds since session started
```

### Important
- Always use `await next_scan()` in your loop
- Scripts automatically stop when session ends
- Click **■ Stop** to manually stop a script

---

## Timing Functions

### Wait for Next Scan
Synchronizes with the cDAQ scan cycle:
```python
await next_scan()
```

### Wait for Duration
Pause for a specific time:
```python
await wait_for(5.0)  # Wait 5 seconds
```

### Wait Until Condition
Wait until a condition is true:
```python
# Wait until temperature exceeds 150°F
await wait_until(lambda: tags.TC001 > 150)

# With timeout (returns True if condition met, False if timeout)
reached = await wait_until(lambda: tags.TC001 > 150, timeout=60)
if not reached:
    print("Timeout waiting for temperature")
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

---

## Troubleshooting

### Script Won't Start
- Check for syntax errors in the console
- Ensure Pyodide has finished loading (first load takes ~5 seconds)

### Values Not Updating
- Make sure you're using `await next_scan()` in your loop
- Check that the acquisition session is running

### Published Values Not Appearing
- Values appear after the first `publish()` call
- Refresh widget channel list to see new values

### Script Runs Slowly
- Reduce print statements
- Use `await wait_for()` if you don't need every scan
- Complex calculations may need optimization

---

## API Reference

### Objects
| Object | Description |
|--------|-------------|
| `tags` | Read channel values: `tags.TC001` or `tags['TC001']` |
| `tags.timestamp(name)` | Get backend acquisition timestamp (Unix ms) |
| `tags.get_with_timestamp(name)` | Get `(value, timestamp)` tuple |
| `tags.age(name)` | Get data age in seconds |
| `session` | Session state: `session.active`, `session.elapsed` |
| `outputs` | Control outputs: `outputs.set('name', value)` |

### Functions
| Function | Description |
|----------|-------------|
| `publish(name, value, units='', description='')` | Create a computed tag |
| `await next_scan()` | Wait for next cDAQ scan |
| `await wait_for(seconds)` | Wait for duration |
| `await wait_until(condition, timeout=0)` | Wait for condition |

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

### Complete Example
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

## Limitations

- **Browser-based**: Scripts run in the browser, not on a server
- **No file I/O**: Cannot read/write files directly (use MQTT for data export)
- **Single thread**: Long calculations may affect UI responsiveness
- **Memory**: Large data arrays may consume browser memory

---

## Future Enhancements (Planned)

- `alarm.trigger()` / `alarm.clear()` - Raise system alarms
- `system.shutdown()` - Trigger controlled shutdown
- Auto-start scripts on session start
- Script templates and examples library
- Additional Python packages (Pandas for data analysis)
