# ICCSFlux Python Script Generation Guide

**Purpose**: This guide provides all information needed for an AI to generate valid Python scripts for the ICCSFlux data acquisition and control system.

---

## Overview

ICCSFlux Python scripts run on the backend server, synchronized with the data acquisition scan cycle. Scripts can:

- Read live sensor data from any connected hardware
- Control digital and analog outputs
- Publish computed values that appear as new tags
- Persist data across restarts
- Automate test sequences
- Schedule recurring tasks
- Continue running even if the browser is closed

---

## Script Structure

Every ICCSFlux script follows this structure:

```python
# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: IMPORTS (execute once at script start)
# ═══════════════════════════════════════════════════════════════════════════════
import numpy as np
from collections import deque

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: INITIALIZATION (execute once before main loop)
# ═══════════════════════════════════════════════════════════════════════════════
my_buffer = deque(maxlen=100)
total_count = 0
calibration_offset = 2.5

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: MAIN LOOP (runs repeatedly, synchronized with scan cycle)
# ═══════════════════════════════════════════════════════════════════════════════
while session.active:
    # Your code here
    temp = tags.TC001

    # Always end with next_scan()
    await next_scan()
```

### Critical Rules

1. **Always use `while session.active:`** - This ensures the script stops when acquisition stops
2. **Always call `await next_scan()` inside the loop** - This synchronizes with the scan cycle
3. **Initialize variables BEFORE the loop** - Variables inside the loop reset each iteration
4. **Use `try/finally` for cleanup** - Ensures outputs are safely set when script stops

---

## Pre-loaded Objects (No Import Needed)

These objects and functions are available immediately without any import statements.

### Core Objects

| Object | Description |
|--------|-------------|
| `tags` | Read channel values from any hardware |
| `outputs` | Control digital and analog outputs |
| `session` | Session state and control methods |
| `vars` | Read/write user-defined variables (constants, manual values, strings) |
| `pid` | Access and control PID loops |

### Core Functions

| Function | Description |
|----------|-------------|
| `publish(name, value, units='', description='')` | Create a computed tag |
| `next_scan()` | Wait for next scan cycle |
| `wait_for(seconds)` | Wait for a duration |
| `wait_until(condition, timeout=0)` | Wait for a condition to be true |
| `persist(key, value)` | Save value to disk (survives restarts) |
| `restore(key, default=None)` | Restore persisted value |

### Time Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `now()` | float | Unix timestamp in seconds |
| `now_ms()` | int | Unix timestamp in milliseconds |
| `now_iso()` | string | ISO 8601 formatted time |
| `time_of_day()` | string | "HH:MM:SS" format |
| `elapsed_since(start)` | float | Seconds since start timestamp |
| `format_timestamp(ts_ms, fmt='%Y-%m-%d %H:%M:%S')` | string | Format timestamp |

### Unit Conversion Functions

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
| `Counter(target, window, debounce, auto_reset, mode)` | Universal counter: totalizing, targets, duty cycle, run hours, cycles |
| `RateCalculator(window_seconds)` | Calculate rate of change |
| `Accumulator(initial=0)` | Track cumulative totals |
| `EdgeDetector(threshold=0.5)` | Detect rising/falling edges |
| `RollingStats(window_size)` | Calculate running statistics |
| `Scheduler()` | Schedule recurring tasks |

### Pre-imported Libraries

| Library | Available As |
|---------|--------------|
| `time` | `time` |
| `datetime` | `datetime` |
| `math` | `math` |
| `json` | `json` |
| `re` | `re` |
| `statistics` | `statistics` |
| `numpy` | `numpy`, `np` |
| `scipy` | `scipy` |

### Built-in Functions

All standard Python built-ins: `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `filter`, `float`, `int`, `len`, `list`, `map`, `max`, `min`, `pow`, `range`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip`

---

## Reading Channel Data: The `tags` Object

The `tags` object provides access to all channel values regardless of hardware source.

### Basic Access

```python
# Bracket access (recommended — works with ISA-5.1 dashed names)
temp = tags['TC-001']
pressure = tags['PT-001']

# Dot access (only works for names without dashes)
temp = tags.TC001
pressure = tags.Inlet_Temp
# tags.PT-001  # WON'T WORK — Python reads dash as subtraction
```

### Safe Access with Default

```python
# Returns default if tag doesn't exist
temp = tags.get('TC001', default=0.0)
pressure = tags.get('OptionalSensor', default=-1)
```

### Check Tag Existence

```python
# Using 'in' operator
if 'TC001' in tags:
    temp = tags.TC001

# Using exists() method
if tags.exists('TC001'):
    temp = tags.TC001
```

### Get All Tag Names

```python
# Get list of all available tags
all_tags = tags.keys()
print(f"Available tags: {all_tags}")

# Iterate over all tags
for name in tags.keys():
    value = tags[name]
    print(f"{name}: {value}")
```

### Timestamp Access

```python
# Get acquisition timestamp (Unix milliseconds)
ts = tags.timestamp('TC001')

# Get value and timestamp together
value, timestamp = tags.get_with_timestamp('TC001')

# Check data age (seconds since acquisition)
age = tags.age('TC001')
if age > 5.0:
    print("Warning: Data is stale!")
```

### What Tags Are Available

Tags come from:
- **Hardware channels**: `TC001`, `PT001`, `Valve_1` (defined in project)
- **Published values**: `py.Efficiency`, `py.HeatRate` (from scripts)
- **System values**: Various system status tags

---

## Controlling Outputs: The `outputs` Object

The `outputs` object controls digital and analog outputs.

### Set Output Value

```python
# Digital outputs (True/False)
outputs.set('Valve_1', True)    # Turn ON
outputs.set('Valve_1', False)   # Turn OFF
outputs.set('Pump_Start', True)
outputs.set('Alarm_Horn', False)

# Analog outputs (numbers)
outputs.set('Temp_Setpoint', 150.0)
outputs.set('Speed_Command', 1500)
outputs.set('Firing_Rate', 75)
```

### Dictionary-Style Access

```python
outputs['Valve_1'] = True
outputs['Temp_Setpoint'] = 150.0
```

### Check If Command Succeeded

`outputs.set()` returns `True` if the command was accepted:

```python
if outputs.set('Valve_1', True):
    print("Valve command sent successfully")
else:
    print("Command failed - channel may not exist or be blocked by interlock")
```

### Interlock Blocking

Scripts respect the safety interlock system. If an output is blocked by an interlock:

```python
# Output blocked by interlock
if not outputs.set('Heater', True):
    print("Heater blocked by interlock!")

# Robust pattern with retry
def safe_set_output(channel, value, retries=3, delay=1.0):
    """Attempt to set output with retries"""
    for attempt in range(retries):
        if outputs.set(channel, value):
            return True
        print(f"Attempt {attempt + 1} failed, retrying...")
        time.sleep(delay)
    return False
```

---

## Publishing Computed Values: The `publish()` Function

Create new tags from calculated values that appear in the dashboard.

### Basic Usage

```python
# Simple publish
publish('Efficiency', 92.5)

# With units
publish('Efficiency', 92.5, units='%')

# With units and description
publish('HeatRate', 12500, units='BTU/hr', description='Calculated heat transfer rate')
```

### Naming Rules

**Valid names:**
- Letters, numbers, underscores only
- Must start with a letter
- No spaces or special characters

```python
# Valid names
publish('Efficiency', 92.5)        # OK
publish('Heat_Rate', 1250)         # OK
publish('Heat-Rate', 100)          # OK — dashes allowed (ISA-5.1)
publish('Value1', 100)             # OK
publish('_internal', 0)            # OK

# Invalid names (will error)
publish('123abc', 100)             # Can't start with number
publish('Heat Rate', 100)          # No spaces
publish('py.Value', 100)           # Don't add py. prefix
publish('TC-001', 100)             # Can't conflict with hardware channel
```

### Value Requirements

- Must be a number (int or float)
- No strings, None, or other types

```python
# Valid
publish('Value', 123)
publish('Value', 123.456)
publish('Value', int(some_string))
publish('Value', float(some_value))

# Invalid
publish('Value', 'text')           # No strings
publish('Value', None)             # No None
publish('Value', [1, 2, 3])        # No arrays
```

### Accessing Published Values

Published values are available as tags with `py.` prefix:

```python
# Script 1 publishes
publish('Efficiency', 92.5)

# Script 2 (or same script later) can read
eff = tags.get('py.Efficiency', default=0)

# Also available in dashboard widgets
# Channel dropdown shows: py.Efficiency
```

---

## Session Control: The `session` Object

### Session Properties

```python
session.active       # True if acquisition is running
session.elapsed      # Seconds since session started
session.recording    # True if currently recording to file
```

### Session Control Methods

```python
# Start/stop acquisition
session.start()                    # Start data acquisition
session.stop()                     # Stop data acquisition

# Start/stop recording
session.start_recording()          # Start recording with default filename
session.start_recording('test.csv')  # Start with custom filename
session.stop_recording()           # Stop recording
```

### Main Loop Pattern

```python
while session.active:
    # Your processing code
    temp = tags.TC001
    publish('ProcessedTemp', temp * 1.1)

    # Always end with next_scan()
    await next_scan()
```

---

## User Variables: The `vars` Object

Access user-defined variables configured in the Variables tab.

### Reading Variables

```python
# Attribute access
k_factor = vars.CalibrationFactor
target = vars.TargetTemp

# Dictionary access (for names with special characters)
offset = vars['TC001_Offset']

# Safe access with default
value = vars.get('OptionalVar', default=0.0)
```

### Writing Variables

```python
# Set manual/string variable values
vars.set('TargetTemp', 350.0)
vars.set('BatchID', 'BATCH-2024-0542')
```

### Resetting Variables

```python
# Reset accumulators, counters, timers to 0
vars.reset('TotalFlow')
vars.reset('CycleCount')
```

### Check Existence

```python
if 'MyVariable' in vars:
    value = vars.MyVariable

# List all variable names
all_vars = vars.keys()
```

### Variable Types

| Type | Description | Access |
|------|-------------|--------|
| `constant` | Fixed values | Read-only |
| `manual` | User-adjustable numbers | Read/write |
| `string` | Text values (batch IDs, notes) | Read/write |
| `accumulator` | Running totals | Read, reset |
| `counter` | Edge counts | Read, reset |
| `timer` | Elapsed time | Read, reset |
| `expression` | Calculated | Read-only |

---

## PID Control: The `pid` Object

Access and control PID loops configured in the project.

### Accessing Loops

```python
# Attribute access
loop = pid.TempControl

# Dictionary access
loop = pid['TC-Loop-1']
```

### Reading Loop Status

```python
pv = pid.TempControl.pv          # Process variable
sp = pid.TempControl.setpoint    # Current setpoint
output = pid.TempControl.output  # Control output (0-100%)
error = pid.TempControl.error    # Setpoint - PV
mode = pid.TempControl.mode      # 'auto' or 'manual'
```

### Controlling Loops

```python
# Change setpoint
pid.TempControl.setpoint = 150.0

# Switch modes
pid.TempControl.mode = 'auto'
pid.TempControl.mode = 'manual'

# Or use convenience methods
pid.TempControl.auto()
pid.TempControl.manual()

# Set manual output (manual mode only)
pid.TempControl.output = 50.0

# Enable/disable
pid.TempControl.enable()
pid.TempControl.disable()
```

### Tuning

```python
# Update tuning parameters
pid.TempControl.tune(kp=2.0, ki=0.1, kd=0.05)
```

### Listing Loops

```python
loop_ids = pid.keys()
if 'TempControl' in pid:
    print(f"PV: {pid.TempControl.pv}")
```

---

## Timing and Wait Functions

### `next_scan()` - Wait for Next Scan Cycle

Synchronizes script with the data acquisition scan cycle.

```python
while session.active:
    # Process data
    temp = tags.TC001

    # Wait for next scan
    await next_scan()
```

**Critical:** Always use `next_scan()` in loops. Without it, the script will timeout.

### `wait_for(seconds)` - Wait for Duration

Pauses script execution for specified time.

```python
# Wait 5 seconds
await wait_for(5.0)

# Wait 0.5 seconds
await wait_for(0.5)

# Wait 2 minutes
await wait_for(120)
```

### `wait_until(condition, timeout=0)` - Wait for Condition

Waits until a condition becomes true.

```python
# Wait until temperature exceeds 150°F
await wait_until(lambda: tags.TC001 > 150)

# With timeout (returns True if condition met, False if timeout)
reached = await wait_until(lambda: tags.TC001 > 150, timeout=60)
if not reached:
    print("Timeout waiting for temperature")

# Wait until digital input is true
await wait_until(lambda: tags.Ready_Signal == True)

# Complex condition
await wait_until(lambda: tags.TC001 > 100 and tags.PT001 < 50)
```

---

## Time Functions

### Current Time

```python
# Unix timestamp in seconds (float)
ts = now()                        # e.g., 1704299400.123456

# Unix timestamp in milliseconds (integer)
ts_ms = now_ms()                  # e.g., 1704299400123

# ISO 8601 formatted string
iso = now_iso()                   # e.g., "2026-01-20T14:30:00.123456"

# Time of day as HH:MM:SS
tod = time_of_day()               # e.g., "14:30:00"
```

### Elapsed Time

```python
start = now()

while session.active:
    elapsed = elapsed_since(start)
    print(f"Running for {elapsed:.1f} seconds")

    if elapsed > 300:
        print("5 minutes elapsed")
        break

    await next_scan()
```

### Format Timestamps

```python
ts_ms = now_ms()

# Default format
formatted = format_timestamp(ts_ms)          # "2026-01-20 14:30:00"

# Custom formats
formatted = format_timestamp(ts_ms, '%Y-%m-%d')        # "2026-01-20"
formatted = format_timestamp(ts_ms, '%H:%M:%S')        # "14:30:00"
formatted = format_timestamp(ts_ms, '%Y%m%d_%H%M%S')   # "20260120_143000"
```

---

## State Persistence

### `persist(key, value)` - Save to Disk

Saves a value that survives script/service restarts.

```python
# Persist simple values
persist('total_gallons', 12345.67)
persist('run_count', 42)
persist('last_calibration', '2026-01-20')

# Persist complex values (must be JSON-serializable)
persist('calibration_data', {'offset': 2.5, 'scale': 1.02})
persist('history', [100, 102, 98, 105])
```

### `restore(key, default=None)` - Load from Disk

Retrieves a previously persisted value.

```python
# Restore with default if not found
total = restore('total_gallons', 0.0)
count = restore('run_count', 0)
cal_data = restore('calibration_data', {'offset': 0, 'scale': 1.0})
```

### Persistence Pattern

```python
# Restore state on startup
total_flow = restore('total_flow', 0.0)
run_hours = restore('run_hours', 0.0)

while session.active:
    # Accumulate values
    flow_rate = tags.FT001
    total_flow += flow_rate / 60  # GPM to gallons per second
    run_hours += 1/3600           # Seconds to hours

    # Persist periodically (not every scan to reduce disk I/O)
    if session.elapsed % 60 < 1:  # Every minute
        persist('total_flow', total_flow)
        persist('run_hours', run_hours)

    publish('TotalFlow', total_flow, units='gal')
    publish('RunHours', run_hours, units='hrs')

    await next_scan()
```

---

## Helper Classes

### Counter

Universal counter with totalizing, batch targets, sliding window, debounce, duty cycle, run hours, and cycle tracking.

**Constructor**: `Counter(target=None, window=None, debounce=0, auto_reset=False, mode='rate')`

- `mode='rate'` (default): `update()` integrates a rate signal (Hz, GPM) over time
- `mode='cumulative'`: `update()` tracks delta between readings (hardware edge counts)

```python
# Totalizer from frequency counter (rate mode)
fuel = Counter()
while session.active:
    fuel.update(tags.Gas_Flow_Hz)
    publish('TotalFuel', fuel.total, units='SCF')
    await next_scan()

# Hardware edge counter (cumulative mode)
flow = Counter(mode='cumulative')
while session.active:
    flow.update(tags.Flow_Pulses)
    publish('TotalGallons', flow.total / 100, units='gal')
    await next_scan()

# Production counter with batch target
parts = Counter(target=500, auto_reset=True)
while session.active:
    if tags.Part_Sensor:
        parts.increment()
    publish('Count', parts.count)
    publish('Batch', parts.batch)
    await next_scan()

# Pump duty cycle and run hours
pump = Counter(window=3600)
while session.active:
    pump.update(tags.Pump_Status)  # 0/1 digital
    publish('Duty', pump.duty, units='%')
    publish('RunHours', pump.run_hours, units='hr')
    publish('Cycles', pump.cycles)
    await next_scan()
```

**Key properties**: `count`, `total`, `done`, `remaining`, `batch`, `window_count`, `rate`, `duty`, `run_time`, `run_hours`, `cycles`, `cycle_avg`, `cycle_min`, `cycle_max`, `state`, `stable`, `elapsed`

**Key methods**: `increment(n)`, `decrement(n)`, `tick()`, `reset()`, `set(value)`, `update(value)`, `lap(name)`

> Use `mode='cumulative'` when reading hardware counter channels in edge count mode. Default `mode='rate'` is for frequency/rate signals only.

### RateCalculator

Calculates rate of change over a time window.

```python
# Create calculator with 60-second window
flow_rate = RateCalculator(window_seconds=60)

while session.active:
    counter = tags.FlowPulseCounter  # Pulse counter input

    # Calculate rate (pulses per second)
    pulses_per_sec = flow_rate.update(counter)

    # Convert to engineering units (e.g., 100 pulses = 1 gallon)
    gpm = (pulses_per_sec / 100) * 60

    publish('FlowRate', gpm, units='GPM')
    await next_scan()
```

### Accumulator

Tracks cumulative totals from counter values.

```python
# Create accumulator starting at 0
total_flow = Accumulator(initial=0)

while session.active:
    counter = tags.FlowPulseCounter

    # Accumulate delta between readings
    total_pulses = total_flow.update(counter)

    # Convert to gallons
    total_gallons = total_pulses / 100

    publish('TotalFlow', total_gallons, units='gal')
    await next_scan()

# Reset if needed
total_flow.reset()
```

### EdgeDetector

Detects rising and falling edges on signals.

```python
# Create detector
pump_edge = EdgeDetector(threshold=0.5)

while session.active:
    pump_status = tags.PumpRunning  # Can be digital (0/1) or analog

    # Detect edges
    rising, falling, current_state = pump_edge.update(pump_status)

    if rising:
        print(f"[{now_iso()}] Pump STARTED")

    if falling:
        print(f"[{now_iso()}] Pump STOPPED")

    await next_scan()
```

### RollingStats

Calculates running statistics over a sample window.

```python
# Create stats calculator with 100-sample window
temp_stats = RollingStats(window_size=100)

while session.active:
    temp = tags.TC001

    # Update and get statistics
    stats = temp_stats.update(temp)

    publish('TempAvg', stats['mean'], units='degF')
    publish('TempMin', stats['min'], units='degF')
    publish('TempMax', stats['max'], units='degF')
    publish('TempStd', stats['std'], units='degF')

    await next_scan()
```

**Available statistics:**
- `stats['mean']` - Average
- `stats['min']` - Minimum
- `stats['max']` - Maximum
- `stats['std']` - Standard deviation
- `stats['count']` - Sample count

### Scheduler

Schedule recurring tasks (similar to APScheduler/cron).

```python
# Create scheduler
scheduler = Scheduler()

# Define task functions
def log_temps():
    print(f"TC001={tags.TC001:.1f}, TC002={tags.TC002:.1f}")

def hourly_report():
    print(f"=== Hourly Report at {time_of_day()} ===")

def start_pump():
    outputs.set('Pump', True)
    print("Pump started after warmup")

# Add interval job (every N seconds/minutes/hours)
scheduler.add_interval('temp_log', seconds=30, func=log_temps)
scheduler.add_interval('status', minutes=5, func=check_status)

# Add cron-like job (at specific times)
scheduler.add_cron('hourly', minute=0, func=hourly_report)           # Top of every hour
scheduler.add_cron('daily', hour=8, minute=0, func=daily_report)     # 8:00 AM daily
scheduler.add_cron('weekly', hour=8, minute=0, day_of_week=0, func=weekly_report)  # Monday 8AM

# Add one-shot delayed job
scheduler.add_once('pump_start', delay=60, func=start_pump)  # Run once after 60 seconds

# Main loop - must call tick()
while session.active:
    # Your normal processing
    temp = tags.TC001

    # Run scheduled jobs
    await scheduler.tick()

    await next_scan()
```

**Scheduler Methods:**
- `add_interval(name, seconds/minutes/hours, func)` - Recurring interval
- `add_cron(name, minute/hour/day_of_week, func)` - Cron-like schedule
- `add_once(name, delay, func)` - One-shot delayed
- `pause(name)` - Pause a job
- `resume(name)` - Resume a paused job
- `remove(name)` - Remove a job
- `is_paused(name)` - Check if paused
- `get_jobs()` - Get all job statuses
- `tick()` - Check and run due jobs (MUST call in loop)

---

## Error Handling

### Basic Try/Except

```python
while session.active:
    try:
        temp = tags.TC001
        pressure = tags.PT001

        # This could fail if pressure is 0
        ratio = temp / pressure
        publish('Ratio', ratio)

    except ZeroDivisionError:
        publish('Ratio', 0)
        print("Warning: Division by zero")

    except Exception as e:
        print(f"Error: {e}")

    await next_scan()
```

### Safe Cleanup with Finally

**Critical pattern for scripts that control outputs:**

```python
try:
    # Enable outputs at start
    outputs.set('HeaterEnable', True)
    outputs.set('PumpEnable', True)

    while session.active:
        # Control logic
        temp = tags.TC001
        if temp > 180:
            outputs.set('HeaterEnable', False)

        await next_scan()

finally:
    # ALWAYS runs when script stops (manual stop, error, or session end)
    outputs.set('HeaterEnable', False)
    outputs.set('PumpEnable', False)
    print("Outputs safely disabled")
```

### Handling Missing Tags

```python
while session.active:
    # Method 1: Check existence
    if tags.exists('OptionalSensor'):
        optional_value = tags.OptionalSensor
    else:
        optional_value = 0

    # Method 2: Use get() with default (preferred)
    optional_value = tags.get('OptionalSensor', default=0)

    # Method 3: Try/except
    try:
        optional_value = tags.OptionalSensor
    except:
        optional_value = 0

    await next_scan()
```

### Timeout Protection

```python
try:
    # Wait with timeout
    reached = await wait_until(lambda: tags.TC001 > 150, timeout=60)

    if reached:
        print("Temperature reached!")
    else:
        print("Timeout - taking alternative action")
        outputs.set('Alarm', True)

except Exception as e:
    print(f"Wait failed: {e}")
```

---

## Common Script Patterns

### Pattern 1: Simple Monitor with Alarm

```python
# Monitor temperature and activate alarm on high limit
HIGH_LIMIT = 180.0
LOW_LIMIT = 50.0

while session.active:
    temp = tags.TC001

    # Check limits
    high_alarm = temp > HIGH_LIMIT
    low_alarm = temp < LOW_LIMIT

    # Set alarm outputs
    outputs.set('HighTempAlarm', high_alarm)
    outputs.set('LowTempAlarm', low_alarm)

    # Publish status (1=high, -1=low, 0=normal)
    if high_alarm:
        status = 1
    elif low_alarm:
        status = -1
    else:
        status = 0

    publish('TempStatus', status)
    await next_scan()
```

### Pattern 2: Rolling Average with Buffer

```python
from collections import deque

# Initialize buffer
BUFFER_SIZE = 100
temp_buffer = deque(maxlen=BUFFER_SIZE)

while session.active:
    temp = tags.TC001
    temp_buffer.append(temp)

    # Calculate rolling average
    if len(temp_buffer) > 0:
        avg = sum(temp_buffer) / len(temp_buffer)
        publish('TempAvg', avg, units='degF')

    await next_scan()
```

### Pattern 3: Heat Transfer Calculation

```python
# Q = m * Cp * deltaT
CP_WATER = 1.0      # BTU/(lb·°F)
DENSITY = 8.34      # lb/gal

while session.active:
    flow_gpm = tags.FT_Water
    temp_in = tags.TC_Inlet
    temp_out = tags.TC_Outlet

    # Temperature difference
    delta_t = temp_out - temp_in

    # Mass flow rate
    mass_flow = flow_gpm * DENSITY  # lb/min

    # Heat rate
    q_btu_min = mass_flow * CP_WATER * delta_t
    q_btu_hr = q_btu_min * 60

    publish('DeltaT', delta_t, units='degF')
    publish('HeatRate', q_btu_hr, units='BTU/hr')

    await next_scan()
```

### Pattern 4: Efficiency Calculation

```python
while session.active:
    power_in = tags.PowerInput
    power_out = tags.PowerOutput

    # Avoid division by zero
    if power_in > 0:
        efficiency = (power_out / power_in) * 100
    else:
        efficiency = 0

    publish('Efficiency', efficiency, units='%')
    await next_scan()
```

### Pattern 5: Flow Totalizer with Persistence

```python
# Restore previous total
total_gallons = restore('total_gallons', 0.0)
last_persist = now()

while session.active:
    flow_gpm = tags.FT001

    # Accumulate flow (GPM / 60 = gallons per second, * scan_interval)
    # Assuming 10 Hz scan rate (0.1 second interval)
    total_gallons += flow_gpm / 60 * 0.1

    # Persist every 60 seconds
    if elapsed_since(last_persist) >= 60:
        persist('total_gallons', total_gallons)
        last_persist = now()

    publish('TotalFlow', total_gallons, units='gal')
    await next_scan()
```

### Pattern 6: Valve Cycling Sequence

```python
CYCLE_TIME = 30.0  # Toggle every 30 seconds
valve_state = False

while session.active:
    # Toggle valve
    valve_state = not valve_state
    outputs.set('CycleValve', valve_state)

    state_str = 'OPEN' if valve_state else 'CLOSED'
    print(f"[{time_of_day()}] Valve {state_str}")

    # Wait for cycle time
    await wait_for(CYCLE_TIME)
```

### Pattern 7: Multi-Stage Test Sequence

```python
# Define test stages
STAGES = [
    {'name': 'Preheat', 'setpoint': 100, 'duration': 60},
    {'name': 'Ramp', 'setpoint': 150, 'duration': 120},
    {'name': 'Soak', 'setpoint': 150, 'duration': 300},
    {'name': 'Cool', 'setpoint': 70, 'duration': 180},
]

try:
    for i, stage in enumerate(STAGES):
        if not session.active:
            break

        print(f"Stage {i+1}/{len(STAGES)}: {stage['name']}")

        # Set the setpoint
        outputs.set('TempSetpoint', stage['setpoint'])

        # Publish progress
        publish('CurrentStage', i + 1)
        publish('StageName', stage['name'])

        # Wait for stage duration
        await wait_for(stage['duration'])

    print("Test sequence complete!")

finally:
    # Return to safe state
    outputs.set('TempSetpoint', 70)
    print("Returned to safe state")
```

### Pattern 8: Conditional Recording

```python
recording = False
TEMP_THRESHOLD = 150

while session.active:
    temp = tags.TC001

    # Start recording when temp exceeds threshold
    if not recording and temp > TEMP_THRESHOLD:
        session.start_recording('high_temp_event.csv')
        recording = True
        print(f"Recording started - temp = {temp}°F")

    # Stop recording when temp returns to normal
    elif recording and temp < (TEMP_THRESHOLD - 10):  # 10° hysteresis
        session.stop_recording()
        recording = False
        print(f"Recording stopped - temp = {temp}°F")

    await next_scan()
```

### Pattern 9: Scheduled Logging

```python
scheduler = Scheduler()

def log_process_values():
    tc1 = tags.TC001
    tc2 = tags.TC002
    pt1 = tags.PT001
    print(f"[{time_of_day()}] TC001={tc1:.1f} TC002={tc2:.1f} PT001={pt1:.2f}")

def hourly_summary():
    print(f"=== Hourly Summary at {now_iso()} ===")
    print(f"Session elapsed: {session.elapsed:.0f} seconds")

# Log every 30 seconds
scheduler.add_interval('process_log', seconds=30, func=log_process_values)

# Summary at top of each hour
scheduler.add_cron('hourly', minute=0, func=hourly_summary)

while session.active:
    await scheduler.tick()
    await next_scan()
```

### Pattern 10: PID-like Control

```python
# Simple proportional control (not a full PID)
SETPOINT = 150.0
KP = 2.0  # Proportional gain
OUTPUT_MIN = 0
OUTPUT_MAX = 100

while session.active:
    # Read process variable
    temp = tags.TC001

    # Calculate error
    error = SETPOINT - temp

    # Calculate output (proportional only)
    output = KP * error

    # Clamp to limits
    output = max(OUTPUT_MIN, min(OUTPUT_MAX, output))

    # Send to output
    outputs.set('HeaterOutput', output)

    # Publish values
    publish('Error', error, units='degF')
    publish('ControlOutput', output, units='%')

    await next_scan()
```

---

## Best Practices

### Do's

```python
# DO: Always use next_scan() in loops
while session.active:
    # work
    await next_scan()

# DO: Initialize variables before the loop
counter = 0
buffer = []
while session.active:
    counter += 1
    buffer.append(tags.TC001)
    await next_scan()

# DO: Use try/finally for cleanup
try:
    outputs.set('Running', True)
    while session.active:
        await next_scan()
finally:
    outputs.set('Running', False)

# DO: Handle division by zero
if denominator != 0:
    result = numerator / denominator
else:
    result = 0

# DO: Use descriptive published names
publish('TotalGallonsToday', total, units='gal')

# DO: Use get() with default for optional tags
value = tags.get('OptionalSensor', default=0)

# DO: Limit print statements (use periodic logging)
if iteration % 100 == 0:
    print(f"Status: {value}")
```

### Don'ts

```python
# DON'T: Forget next_scan() (causes timeout)
while session.active:
    temp = tags.TC001  # No next_scan() = script will timeout!

# DON'T: Initialize variables inside the loop
while session.active:
    counter = 0  # Resets every iteration!
    counter += 1  # Always 1
    await next_scan()

# DON'T: Use cryptic published names
publish('v1', total)  # What is v1?

# DON'T: Print every scan cycle
while session.active:
    print(f"Temp: {tags.TC001}")  # Floods console
    await next_scan()

# DON'T: Rely on scripts for safety-critical logic
# Use hardware interlocks instead
```

---

## Script Generation Checklist

When generating a script, ensure:

- [ ] Script has `while session.active:` main loop
- [ ] Loop contains `await next_scan()` at the end
- [ ] Variables are initialized BEFORE the loop
- [ ] Published names follow rules (letters, numbers, underscores only)
- [ ] Published names don't conflict with hardware channels
- [ ] Division by zero is handled
- [ ] Output control uses `try/finally` for cleanup
- [ ] Print statements are limited (not every scan)
- [ ] Optional tag access uses `get()` with default
- [ ] Complex calculations are commented
- [ ] Units are specified for published values

---

## Example Complete Scripts

### Script: Thermal Efficiency Calculator

```python
"""
Thermal Efficiency Calculator
Calculates boiler/heater efficiency from input/output heat flows
"""

# Constants
CP_WATER = 1.0      # BTU/(lb·°F) - specific heat of water
DENSITY = 8.34      # lb/gal - water density
BTU_PER_KWH = 3412  # BTU per kWh

# Initialize smoothing
inlet_stats = RollingStats(window_size=20)
outlet_stats = RollingStats(window_size=20)

while session.active:
    # Read sensors
    flow_gpm = tags.get('FT_Water', default=0)
    temp_in = tags.get('TC_Inlet', default=70)
    temp_out = tags.get('TC_Outlet', default=70)
    power_kw = tags.get('Power_Input', default=0)

    # Smooth temperature readings
    inlet_smooth = inlet_stats.update(temp_in)['mean']
    outlet_smooth = outlet_stats.update(temp_out)['mean']

    # Calculate heat output
    delta_t = outlet_smooth - inlet_smooth
    mass_flow = flow_gpm * DENSITY  # lb/min
    q_output_btu_hr = mass_flow * CP_WATER * abs(delta_t) * 60

    # Calculate heat input
    q_input_btu_hr = power_kw * BTU_PER_KWH

    # Calculate efficiency
    if q_input_btu_hr > 0:
        efficiency = (q_output_btu_hr / q_input_btu_hr) * 100
        efficiency = min(100, max(0, efficiency))  # Clamp 0-100
    else:
        efficiency = 0

    # Publish results
    publish('DeltaT', delta_t, units='degF', description='Temperature rise')
    publish('HeatOutput', q_output_btu_hr, units='BTU/hr', description='Heat delivered to water')
    publish('HeatInput', q_input_btu_hr, units='BTU/hr', description='Energy input')
    publish('Efficiency', efficiency, units='%', description='Thermal efficiency')

    await next_scan()
```

### Script: Automated Pump Cycling Test

```python
"""
Automated Pump Cycling Test
Cycles pump on/off and records flow response
"""

# Test parameters
CYCLE_COUNT = 10
ON_TIME = 30        # seconds
OFF_TIME = 15       # seconds
STABILIZE_TIME = 5  # seconds to wait before measuring

# Restore test progress
cycles_completed = restore('pump_test_cycles', 0)
results = restore('pump_test_results', [])

try:
    print(f"Starting pump cycling test, {CYCLE_COUNT - cycles_completed} cycles remaining")

    for cycle in range(cycles_completed, CYCLE_COUNT):
        if not session.active:
            break

        print(f"Cycle {cycle + 1}/{CYCLE_COUNT}")
        publish('TestCycle', cycle + 1)

        # Turn pump ON
        outputs.set('TestPump', True)
        await wait_for(STABILIZE_TIME)

        # Measure flow while ON
        flow_on = tags.FT_Test
        print(f"  Flow ON: {flow_on:.2f} GPM")

        # Continue ON period
        await wait_for(ON_TIME - STABILIZE_TIME)

        # Turn pump OFF
        outputs.set('TestPump', False)
        await wait_for(STABILIZE_TIME)

        # Measure flow while OFF
        flow_off = tags.FT_Test
        print(f"  Flow OFF: {flow_off:.2f} GPM")

        # Continue OFF period
        await wait_for(OFF_TIME - STABILIZE_TIME)

        # Record result
        results.append({
            'cycle': cycle + 1,
            'flow_on': flow_on,
            'flow_off': flow_off,
            'timestamp': now_iso()
        })

        # Persist progress
        cycles_completed = cycle + 1
        persist('pump_test_cycles', cycles_completed)
        persist('pump_test_results', results)

    # Test complete - calculate summary
    if results:
        avg_flow_on = sum(r['flow_on'] for r in results) / len(results)
        avg_flow_off = sum(r['flow_off'] for r in results) / len(results)
        print(f"\n=== Test Complete ===")
        print(f"Average flow ON: {avg_flow_on:.2f} GPM")
        print(f"Average flow OFF: {avg_flow_off:.2f} GPM")

    # Reset for next test
    persist('pump_test_cycles', 0)
    persist('pump_test_results', [])

finally:
    # Ensure pump is OFF
    outputs.set('TestPump', False)
    print("Pump test ended, pump OFF")
```

### Script: Real-Time Data Quality Monitor

```python
"""
Data Quality Monitor
Monitors sensor data for anomalies and stale readings
"""

# Configuration
STALE_THRESHOLD = 5.0       # seconds
RATE_THRESHOLD = 10.0       # max change per second
CHECK_INTERVAL = 10         # check every N scans

# Channels to monitor
MONITORED_CHANNELS = ['TC001', 'TC002', 'PT001', 'FT001']

# Initialize tracking
last_values = {}
scan_count = 0

while session.active:
    scan_count += 1

    # Only check periodically to reduce overhead
    if scan_count % CHECK_INTERVAL == 0:
        issues = []

        for channel in MONITORED_CHANNELS:
            if not tags.exists(channel):
                issues.append(f"{channel}: NOT FOUND")
                continue

            current_value = tags[channel]
            age = tags.age(channel)

            # Check for stale data
            if age > STALE_THRESHOLD:
                issues.append(f"{channel}: STALE ({age:.1f}s)")

            # Check for excessive rate of change
            if channel in last_values:
                last_val, last_time = last_values[channel]
                dt = now() - last_time
                if dt > 0:
                    rate = abs(current_value - last_val) / dt
                    if rate > RATE_THRESHOLD:
                        issues.append(f"{channel}: SPIKE ({rate:.1f}/s)")

            # Update tracking
            last_values[channel] = (current_value, now())

        # Publish status
        if issues:
            print(f"[{time_of_day()}] Data quality issues: {', '.join(issues)}")
            publish('DataQualityOK', 0)
        else:
            publish('DataQualityOK', 1)

        publish('ChannelsMonitored', len(MONITORED_CHANNELS))

    await next_scan()
```
