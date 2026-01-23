# Python Scripting in ICCSFlux

Run custom Python scripts on the backend to process data from cDAQ, cRIO, and Opto22 hardware, control outputs, calculate derived values, and automate sequences.

## Overview

ICCSFlux includes a **server-side Python script engine** running in the daq_service backend. Scripts execute in isolated threads with full access to the Python ecosystem. This means you can write real Python code that:

- Reads live channel data from **any hardware source** (cDAQ, cRIO, Opto22)
- Controls digital and analog outputs across all connected nodes
- Publishes computed values that appear as new tags
- Runs synchronized loops with your scan cycle
- Performs unit conversions and calculations
- Automates sequences and schedules
- **Continues running even if the browser is closed** (headless operation)

> **Multi-Hardware Support**: Scripts access all channels uniformly through the `tags` object, regardless of whether they come from local cDAQ hardware, remote cRIO nodes, or Opto22 groov devices. The hardware source is transparent to your scripts.

> **Safety Architecture**: Scripts respect the SafetyManager interlock system - output commands are blocked when interlocks are not satisfied. However, **safety-critical logic should always reside in the edge nodes** (cRIO/Opto22) where hardware watchdogs and SIL-rated interlock checks operate independently of the PC. The edge nodes validate interlocks even if the PC or network connection fails.

> **Edge Node Scripts**: Scripts can also run directly on cRIO and Opto22 nodes, using the same API documented here. Edge node scripts have local persistence, continue running independently of PC connectivity, and automatically start/stop with acquisition or session events. This enables autonomous edge computing for remote installations.

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

Your script code runs in an isolated thread on the backend. Any code **before** the `while session.active:` loop executes once when the script starts. This is where you put imports and initialization.

> **Note**: The `await` keyword is optional. Scripts written with `await next_scan()` will work identically to those without - the backend automatically handles synchronization.

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
| **Core** | `tags`, `session`, `outputs`, `vars`, `pid`, `publish`, `next_scan`, `wait_for`, `wait_until` |
| **Persistence** | `persist(key, value)`, `restore(key, default=None)` |
| **Time Functions** | `now`, `now_ms`, `now_iso`, `time_of_day`, `elapsed_since`, `format_timestamp` |
| **Conversions** | `F_to_C`, `C_to_F`, `GPM_to_LPM`, `LPM_to_GPM`, `PSI_to_bar`, `bar_to_PSI`, `gal_to_L`, `L_to_gal`, `BTU_to_kJ`, `kJ_to_BTU`, `lb_to_kg`, `kg_to_lb` |
| **Helpers** | `RateCalculator`, `Accumulator`, `EdgeDetector`, `RollingStats`, `Scheduler`, `StateMachine` |
| **Libraries** | `time`, `datetime`, `math`, `json`, `re`, `statistics`, `numpy` (also as `np`), `scipy` |
| **Built-ins** | `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `filter`, `float`, `int`, `len`, `list`, `map`, `max`, `min`, `pow`, `range`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip` |

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

### Output Validation
`outputs.set()` returns `True` if the command was accepted:
```python
if outputs.set('Valve_1', True):
    print("Valve command sent")
else:
    print("Failed - channel may not exist, not an output, or blocked by interlock")
```

> **Note**: For local cDAQ outputs, `True` means the write succeeded. For remote nodes (cRIO/Opto22), `True` means the command was sent via MQTT. The actual hardware confirmation comes asynchronously.

### Interlock Blocking

Scripts respect the SafetyManager interlock system. If an interlock blocks a channel, `outputs.set()` returns `False`:

```python
# Check if output was blocked
if not outputs.set('Heater', True):
    print("Heater blocked by interlock - check safety conditions")
    # Optionally wait and retry, or take alternative action

# Robust pattern for interlock-aware control
def safe_set_output(channel, value, retries=3, delay=1.0):
    """Attempt to set output with retries (in case interlock clears)"""
    for attempt in range(retries):
        if outputs.set(channel, value):
            return True
        print(f"Output {channel} blocked, attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    return False
```

> **Safety Note**: Interlock blocking is enforced at the backend level. Scripts cannot bypass configured interlocks. For safety-critical applications, always configure interlocks in the Safety tab and use edge-node interlocks for hardware-level protection.

### Output Arbitration (Multiple Scripts)

When multiple scripts run in parallel, they can potentially conflict by writing to the same output. Use **output claiming** to prevent conflicts:

```python
# Claim exclusive control of an output
if outputs.claim('Heater'):
    print("We have exclusive control of Heater")
    # Now only this script can write to Heater
    outputs.set('Heater', True)
else:
    owner = outputs.claimed_by('Heater')
    print(f"Heater already controlled by script: {owner}")
```

#### Claim API

| Method | Description |
|--------|-------------|
| `outputs.claim(channel)` | Claim exclusive control. Returns `True` if successful, `False` if already claimed by another script |
| `outputs.release(channel)` | Release a claimed output (automatic on script stop) |
| `outputs.available(channel)` | Check if output is unclaimed or claimed by you |
| `outputs.claimed_by(channel)` | Get script_id of claim owner, or `None` if unclaimed |
| `outputs.claims()` | Get dict of all claims: `{channel: script_id}` |

#### Behavior

- **Claims are optional**: `outputs.set()` works without claiming, but writes will be rejected if another script has claimed that output
- **Auto-release**: Claims are automatically released when a script stops (whether normally, on error, or timeout)
- **Same-script OK**: A script can always write to outputs it has claimed
- **Transparent conflicts**: When a write is blocked, it returns `False` and logs a warning

#### Example: Temperature Control with Claim

```python
# Temperature control script - claims heater outputs
HEATER_OUTPUTS = ['Zone1_Heater', 'Zone2_Heater', 'Zone3_Heater']

# Claim all heater outputs at startup
for output in HEATER_OUTPUTS:
    if not outputs.claim(output):
        print(f"ERROR: Cannot claim {output} - another script controls it")
        raise Exception("Failed to claim heater outputs")

print("Heater control script has exclusive control")

while session.active:
    # Control logic here - no other script can interfere
    for i, output in enumerate(HEATER_OUTPUTS):
        temp = tags[f'Zone{i+1}_Temp']
        setpoint = vars[f'Zone{i+1}_SP']
        outputs.set(output, temp < setpoint)

    await next_scan()

# Claims auto-released when script stops
```

#### Example: Check Before Writing

```python
# Script that doesn't claim but checks availability
while session.active:
    if outputs.available('EmergencyVent'):
        # Safe to write - no other script controls this
        if tags.Pressure > 100:
            outputs.set('EmergencyVent', True)
    else:
        # Another script has claimed it - let them handle it
        pass

    await next_scan()
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
Published values integrate with the ICCSFlux recording system:

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
- Always use `next_scan()` in your loop (with or without `await`)
- Scripts automatically stop when session ends
- Click **Stop** to manually stop a script
- Scripts continue running even if you close the browser (headless operation)
- Use session control methods sparingly - they affect the entire system

---

## User Variables (vars)

Access user-defined variables configured in the Variables tab. These include constants, manual values, accumulators, counters, timers, and calculated expressions.

### Reading Variables
```python
# Attribute access
k_factor = vars.CalibrationFactor
target_temp = vars.TargetSetpoint

# Dictionary access (for names with special characters)
offset = vars['TC001_Offset']

# Safe access with default
value = vars.get('OptionalVar', default=0.0)
```

### Setting Variables
```python
# Set a manual variable's value
vars.set('TargetTemp', 350.0)
vars.set('BatchCount', 42)

# Useful for operator-adjustable parameters
if vars.AutoMode:
    setpoint = vars.AutoSetpoint
else:
    setpoint = vars.ManualSetpoint
```

### Resetting Variables
```python
# Reset an accumulator or counter to 0
vars.reset('TotalFlow')
vars.reset('CycleCount')
```

### Check if Variable Exists
```python
if 'MyVariable' in vars:
    value = vars.MyVariable

# List all variable names
print(vars.keys())
```

### Variable Types
Variables are configured in the **Variables** tab and can be:

| Type | Description | Script Access |
|------|-------------|---------------|
| `constant` | Fixed calibration factors, setpoints | Read-only (use `vars.Name`) |
| `manual` | User-adjustable values | Read/write (use `vars.set()`) |
| `string` | Text values (batch IDs, notes, operator names) | Read/write (use `vars.set()`) |
| `accumulator` | Running total from counter channel | Read-only, reset with `vars.reset()` |
| `counter` | Counts edge transitions | Read-only, reset with `vars.reset()` |
| `timer` | Elapsed time since start | Read-only, reset with `vars.reset()` |
| `average` | Running average of channel | Read-only, reset with `vars.reset()` |
| `expression` | Calculated from formula | Read-only |

### String Variables
String variables store text values like batch IDs, operator names, or notes:

```python
# Read string variables
batch_id = vars.BatchID
operator = vars.OperatorName

# Set string variables
vars.set('BatchID', 'BATCH-2024-0542')
vars.set('Notes', 'Test run for calibration')

# Use in logging
print(f"Starting batch {vars.BatchID} by {vars.OperatorName}")
```

### Example: Using Constants for Calibration
```python
# Constants configured in Variables tab:
# - K_Factor: 0.95 (calibration factor)
# - TempOffset: 2.3 (sensor offset)

while session.active:
    raw_flow = tags.FlowCounter
    raw_temp = tags.TC001

    # Apply calibration using user variables
    cal_flow = raw_flow * vars.K_Factor
    cal_temp = raw_temp + vars.TempOffset

    publish('CalibratedFlow', cal_flow, units='GPM')
    publish('CalibratedTemp', cal_temp, units='°F')

    await next_scan()
```

### Example: Operator-Adjustable Setpoints
```python
# Manual variable 'TargetTemp' can be changed from dashboard widget
# using the Variable Input widget

while session.active:
    current_temp = tags.TC001
    target = vars.TargetTemp  # Reads latest operator-set value

    error = target - current_temp

    # Simple proportional control
    heater_cmd = max(0, min(100, error * 5))
    outputs.set('HeaterPower', heater_cmd)

    publish('TempError', error, units='°F')

    await next_scan()
```

### Example: Reset Accumulator on Button Press
```python
# Works with Action Button widget configured with variable_reset action
# Or reset programmatically when conditions are met

while session.active:
    total_flow = vars.DailyTotal  # Accumulator variable

    # Reset at midnight (if configured in Variables tab)
    # Or reset via dashboard button
    # Or reset when batch complete:
    if total_flow >= vars.BatchSize:
        print(f"Batch complete: {total_flow:.1f} gallons")
        vars.reset('DailyTotal')

    publish('BatchProgress', (total_flow / vars.BatchSize) * 100, units='%')

    await next_scan()
```

### Difference from `tags` and `persist`

| API | Purpose | Storage |
|-----|---------|---------|
| `tags` | Hardware channel values (read-only) | Real-time from hardware |
| `vars` | User-configured variables | Persisted, shared across scripts |
| `persist` | Script-specific state | Per-script, survives restarts |

Use `vars` when you need values that:
- Are configured once and used across multiple scripts
- Can be adjusted by operators during runtime
- Accumulate data (counters, timers) managed by the system

Use `persist` when you need values that:
- Are private to a single script
- Need to survive script restarts
- Track internal script state

---

## PID Control (pid)

Access and control PID loops configured in the project. PID loops run in the backend and can be monitored and adjusted from scripts.

### Accessing PID Loops

```python
# Attribute access (preferred)
loop = pid.TempControl

# Dictionary access (for names with special characters)
loop = pid['TC-Loop-1']
```

### Reading Loop Status

```python
# Get current values
pv = pid.TempControl.pv          # Process variable (current value)
sp = pid.TempControl.setpoint    # Current setpoint
output = pid.TempControl.output  # Control output (0-100%)
error = pid.TempControl.error    # Setpoint - PV

# Get mode
mode = pid.TempControl.mode      # 'auto' or 'manual'
enabled = pid.TempControl.enabled

# Get tuning parameters
kp = pid.TempControl.kp
ki = pid.TempControl.ki
kd = pid.TempControl.kd

# Check saturation
saturated = pid.TempControl.output_saturated
```

### Controlling Loops

```python
# Change setpoint
pid.TempControl.setpoint = 150.0

# Switch modes
pid.TempControl.mode = 'manual'
pid.TempControl.mode = 'auto'

# Or use convenience methods
pid.TempControl.auto()
pid.TempControl.manual()

# Set manual output (only in manual mode)
pid.TempControl.output = 50.0

# Enable/disable loop
pid.TempControl.enable()
pid.TempControl.disable()
```

### Tuning

```python
# Update tuning parameters
pid.TempControl.tune(kp=2.0, ki=0.1, kd=0.05)

# Or set individually
pid.TempControl.kp = 2.0
pid.TempControl.ki = 0.1
pid.TempControl.kd = 0.05
```

### Listing Loops

```python
# Get all configured loop IDs
loop_ids = pid.keys()
print(f"Available loops: {loop_ids}")

# Check if loop exists
if 'TempControl' in pid:
    print(f"TempControl PV: {pid.TempControl.pv}")
```

### Example: Cascade Control

```python
# Outer loop controls setpoint of inner loop
while session.active:
    # Outer loop (slow) - master temperature control
    master_output = pid.MasterTemp.output

    # Feed master output to slave setpoint
    pid.SlaveFlow.setpoint = master_output * 10  # Scale as needed

    # Publish status
    publish('CascadeOutput', master_output, units='%')

    await next_scan()
```

### Example: Setpoint Ramping

```python
# Gradually ramp setpoint from current to target
target_temp = 300.0
ramp_rate = 5.0  # degrees per minute
ramp_interval = 1.0  # seconds

current_sp = pid.TempControl.setpoint

while session.active:
    if current_sp < target_temp:
        # Increment setpoint
        current_sp = min(current_sp + (ramp_rate / 60) * ramp_interval, target_temp)
        pid.TempControl.setpoint = current_sp

    publish('RampProgress', (current_sp / target_temp) * 100, units='%')

    await wait_for(ramp_interval)
```

### Example: Auto-Tune Detection

```python
# Monitor loop for oscillation (auto-tune detection)
from collections import deque

error_history = deque(maxlen=100)
zero_crossings = 0
last_sign = None

while session.active:
    error = pid.TempControl.error
    error_history.append(error)

    # Count zero crossings
    current_sign = error >= 0
    if last_sign is not None and current_sign != last_sign:
        zero_crossings += 1
    last_sign = current_sign

    # If oscillating, report
    if len(error_history) == 100:
        if zero_crossings > 10:
            publish('TuneStatus', 1, description='Loop oscillating')
        zero_crossings = 0

    await next_scan()
```

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

## State Persistence

Scripts can persist values that survive service restarts using `persist()` and `restore()`.

### Basic Usage
```python
# Restore previous total on script start (or 0.0 if first run)
total_gallons = restore('flow_total', 0.0)

while session.active:
    # Accumulate flow
    total_gallons += tags.FlowRate / 60  # GPM to gallons per scan

    # Persist every scan (stored to disk)
    persist('flow_total', total_gallons)

    publish('TotalGallons', total_gallons, units='gal')
    next_scan()
```

### With Helper Classes
```python
# Restore Accumulator state
initial_total = restore('pump_cycles', 0.0)
cycle_counter = Accumulator(initial=initial_total)

pump_edge = EdgeDetector()

while session.active:
    rising, falling, state = pump_edge.update(tags.PumpStatus)

    if rising:
        cycles = cycle_counter.update(cycle_counter.total + 1)
        persist('pump_cycles', cycles)
        print(f"Pump cycle #{cycles}")

    publish('PumpCycles', cycle_counter.total)
    next_scan()
```

### Multiple Values
```python
# Restore multiple values
run_hours = restore('run_hours', 0.0)
start_count = restore('start_count', 0)
last_maintenance = restore('last_maintenance', None)

while session.active:
    # Track run time
    if tags.MotorRunning:
        run_hours += 1/3600  # Add seconds converted to hours
        persist('run_hours', run_hours)

    publish('RunHours', run_hours, units='hrs')
    next_scan()
```

### Persistence Notes

- **Automatic namespace**: Each script's values are isolated by script ID
- **JSON-compatible**: Persist numbers, strings, bools, lists, and dicts
- **Survives restarts**: Values persist across service restarts and reboots

**Storage Locations by Platform:**

| Platform | Storage Location |
|----------|------------------|
| PC (DAQ Service) | `data/script_state.json` |
| cRIO Node | `/home/admin/crio_node/state/script_state.json` |
| Opto22 Node | `/home/dev/opto22_node/state/script_state.json` |

> **Tip**: Persist only what you need. For high-frequency updates, consider persisting periodically (e.g., every 100 scans) rather than every scan to reduce disk I/O.

> **Edge Node Autonomy**: Scripts running on cRIO or Opto22 nodes persist data locally, ensuring accumulated values survive even if the PC connection is lost.

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

Scripts run in isolated threads with automatic error catching. Use try/except for graceful error handling.

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

### Always Use `next_scan()` in Loops
Without this, your script won't synchronize with the scan cycle and may timeout:
```python
# ✅ Good - synchronizes with scan cycle
while session.active:
    # work
    next_scan()  # await is optional

# ❌ Bad - tight loop, will timeout
while session.active:
    # work (no next_scan)
```

### Keep Safety Logic on Edge Nodes
Scripts are for calculations, not safety:
```python
# ✅ Good - monitoring and derived values
while session.active:
    temp = tags.TC001
    publish('TempStatus', 1 if temp > 180 else 0)  # Just status
    next_scan()

# ❌ Don't rely on scripts for safety-critical control
# Instead, configure interlocks in the Safety tab - they run on edge nodes
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
- Look for red error messages in the script output
- Verify the script is enabled and acquisition is running

### Values Not Updating
- Make sure you're using `next_scan()` in your loop (with or without `await`)
- Check that the acquisition session is running (green status indicator)
- Verify the tag name matches exactly (case-sensitive)

### Published Values Not Appearing
- Values appear after the first `publish()` call
- Refresh widget channel list to see new values
- Check for validation errors in console (invalid names, etc.)

### Script Runs Slowly
- Reduce print statements (console output is forwarded via MQTT)
- Use `wait_for()` if you don't need every scan
- Complex calculations may need optimization
- Keep per-scan compute light for high scan rates

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
| `Script timeout` | Script exceeded max runtime | Add `next_scan()` to yield, or increase timeout |
| `Value must be a number` | Publishing string/None | Convert to float: `float(value)` |
| `Invalid name` | Bad publish name | Use letters, numbers, underscore only |
| `Script stopped` | Session ended or manual stop | Normal - restart when ready |

---

## Limitations

- **Supervisory only**: PC backend scripts are for supervisory logic - for safety-critical control, use edge node interlocks (cRIO/Opto22) which operate independently
- **Edge node scripts**: cRIO and Opto22 nodes support the same script API with local execution and persistence, enabling autonomous operation
- **Script timeout**: Scripts have a configurable max runtime (default 5 minutes) to prevent runaway execution
- **Restricted namespace**: Only a safe subset of Python built-ins and libraries are available (no `open()`, `exec()`, `eval()`, `__import__` on arbitrary modules)
- **Network latency**: Remote node data (cRIO, Opto22) has minimal additional latency (~5-10ms on wired Ethernet), typically negligible compared to scan intervals

### What Scripts Are Good For
- Calculated/derived values (efficiency, heat transfer rates, rolling averages)
- Data quality monitoring (stale data detection, range checks)
- Non-critical automation (scheduled logging, conditional recording)
- Cross-node data aggregation

### What Should Stay on Edge Nodes
- Safety interlocks (temperature limits, pressure relief)
- Emergency stop logic
- Any logic that must operate if PC/network fails

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
| `outputs` | Control outputs on any node: `outputs.set('name', value)` returns `bool` |
| `vars` | Read/write user variables: `vars.MyVar`, `vars.set('MyVar', value)`, `vars.reset('MyVar')` |

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

### Vars Object
| Property/Method | Description |
|-----------------|-------------|
| `vars.Name` or `vars['Name']` | Read a user variable value |
| `vars.get(name, default=0.0)` | Read with default if not found |
| `vars.set(name, value)` | Set a variable's value (returns `bool`) |
| `vars.reset(name)` | Reset a variable to 0 (returns `bool`) |
| `vars.keys()` | Get list of all variable names |
| `name in vars` | Check if variable exists |

### Functions
| Function | Description |
|----------|-------------|
| `publish(name, value, units='', description='')` | Create a computed tag |
| `await next_scan()` | Wait for next scan cycle |
| `await wait_for(seconds)` | Wait for duration |
| `await wait_until(condition, timeout=0)` | Wait for condition |
| `persist(key, value)` | Save value to disk (survives restarts) |
| `restore(key, default=None)` | Restore persisted value or return default |

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
| `StateMachine(initial_state)` | Finite state machine for sequences/recipes |

---

## State Machines and Recipes

Use the `StateMachine` helper class to implement sequences, recipes, and batch processes in transparent Python code.

### Basic StateMachine

```python
# Create state machine starting in IDLE
sm = StateMachine('IDLE')

# Define states with optional entry/exit actions
sm.add_state('IDLE')
sm.add_state('HEATING',
    on_enter=lambda: outputs.set('Heater', True),
    on_exit=lambda: outputs.set('Heater', False))
sm.add_state('SOAKING')
sm.add_state('COOLING',
    on_enter=lambda: outputs.set('CoolValve', True),
    on_exit=lambda: outputs.set('CoolValve', False))
sm.add_state('COMPLETE')

# Define transitions with conditions
sm.add_transition('IDLE', 'HEATING', lambda: vars.StartCmd > 0)
sm.add_transition('HEATING', 'SOAKING', lambda: tags.Temp >= vars.TargetTemp)
sm.add_transition('SOAKING', 'COOLING', lambda: sm.time_in_state() >= vars.SoakTime)
sm.add_transition('COOLING', 'COMPLETE', lambda: tags.Temp <= 50)
sm.add_transition('COMPLETE', 'IDLE', lambda: vars.ResetCmd > 0)

# Main loop
while session.active:
    sm.tick()  # Evaluate transitions, run callbacks

    # Publish state for dashboard widgets
    publish('SM_State', sm.state)
    publish('SM_StateTime', sm.time_in_state())

    next_scan()
```

### StateMachine API

| Method | Description |
|--------|-------------|
| `add_state(name, on_enter, on_exit, on_tick)` | Define a state with optional callbacks |
| `add_transition(from, to, condition, priority, action)` | Add transition between states |
| `tick()` | Evaluate transitions (call every scan) |
| `force_state(state)` | Force transition (manual override) |
| `state` | Current state name (property) |
| `previous_state` | Previous state name (property) |
| `time_in_state()` | Seconds in current state |
| `is_in(*states)` | Check if in one of given states |
| `reset(initial_state)` | Reset to initial state |

### Multi-Phase Recipe Pattern

```python
# Recipe with named phases and parameters
recipe = StateMachine('IDLE')

# Recipe parameters (from user variables)
def get_params():
    return {
        'phase1_temp': vars.get('Phase1_Temp', 100),
        'phase1_time': vars.get('Phase1_Time', 300),
        'phase2_temp': vars.get('Phase2_Temp', 200),
        'phase2_time': vars.get('Phase2_Time', 600),
        'cooldown_temp': vars.get('Cooldown_Temp', 40),
    }

# Phase actions
def start_phase1():
    print(f"Phase 1: Heating to {get_params()['phase1_temp']}°C")
    outputs.set('TempSetpoint', get_params()['phase1_temp'])
    outputs.set('Heater', True)

def start_phase2():
    print(f"Phase 2: Heating to {get_params()['phase2_temp']}°C")
    outputs.set('TempSetpoint', get_params()['phase2_temp'])

def start_cooldown():
    print("Cooldown: Cooling to ambient")
    outputs.set('Heater', False)
    outputs.set('CoolValve', True)

def finish_recipe():
    print("Recipe complete!")
    outputs.set('CoolValve', False)
    outputs.set('TempSetpoint', 25)

# Define states
recipe.add_state('IDLE')
recipe.add_state('PHASE1_HEAT', on_enter=start_phase1)
recipe.add_state('PHASE1_HOLD')
recipe.add_state('PHASE2_HEAT', on_enter=start_phase2)
recipe.add_state('PHASE2_HOLD')
recipe.add_state('COOLDOWN', on_enter=start_cooldown)
recipe.add_state('COMPLETE', on_enter=finish_recipe)
recipe.add_state('ABORTED')

# Transitions
recipe.add_transition('IDLE', 'PHASE1_HEAT',
    lambda: vars.StartRecipe > 0)
recipe.add_transition('PHASE1_HEAT', 'PHASE1_HOLD',
    lambda: tags.Temp >= get_params()['phase1_temp'])
recipe.add_transition('PHASE1_HOLD', 'PHASE2_HEAT',
    lambda: recipe.time_in_state() >= get_params()['phase1_time'])
recipe.add_transition('PHASE2_HEAT', 'PHASE2_HOLD',
    lambda: tags.Temp >= get_params()['phase2_temp'])
recipe.add_transition('PHASE2_HOLD', 'COOLDOWN',
    lambda: recipe.time_in_state() >= get_params()['phase2_time'])
recipe.add_transition('COOLDOWN', 'COMPLETE',
    lambda: tags.Temp <= get_params()['cooldown_temp'])
recipe.add_transition('COMPLETE', 'IDLE',
    lambda: vars.ResetRecipe > 0)

# Abort from any running state (high priority)
for state in ['PHASE1_HEAT', 'PHASE1_HOLD', 'PHASE2_HEAT', 'PHASE2_HOLD', 'COOLDOWN']:
    recipe.add_transition(state, 'ABORTED', lambda: vars.AbortRecipe > 0, priority=10)
recipe.add_transition('ABORTED', 'IDLE', lambda: vars.ResetRecipe > 0)

# Main loop
while session.active:
    recipe.tick()

    # Publish status
    publish('Recipe_State', recipe.state)
    publish('Recipe_Phase', recipe.state.replace('_HEAT', '').replace('_HOLD', ''))
    publish('Recipe_TimeInPhase', recipe.time_in_state())

    next_scan()
```

### Batch Process with Lot Tracking

```python
# Batch process with persistence for crash recovery

batch = StateMachine('IDLE')

# Restore state after restart
saved_state = restore('batch_state', 'IDLE')
saved_lot = restore('batch_lot', '')
batch.force_state(saved_state, run_callbacks=False)

def start_batch():
    lot = f"LOT-{now_iso()[:10]}-{now_ms() % 10000:04d}"
    persist('batch_lot', lot)
    persist('batch_start', now_iso())
    print(f"Starting batch: {lot}")

def complete_batch():
    lot = restore('batch_lot', 'unknown')
    duration = elapsed_since(restore('batch_start', now()))
    print(f"Batch {lot} complete in {duration:.0f}s")
    persist('batch_state', 'IDLE')
    persist('batch_lot', '')

# Define states
batch.add_state('IDLE')
batch.add_state('RUNNING', on_enter=start_batch)
batch.add_state('COMPLETE', on_enter=complete_batch)

batch.add_transition('IDLE', 'RUNNING', lambda: vars.StartBatch > 0)
batch.add_transition('RUNNING', 'COMPLETE', lambda: vars.BatchDone > 0)
batch.add_transition('COMPLETE', 'IDLE', lambda: True)  # Auto-return to IDLE

# Main loop
while session.active:
    batch.tick()

    # Persist state for crash recovery
    if batch.state != restore('batch_state', 'IDLE'):
        persist('batch_state', batch.state)

    publish('Batch_State', batch.state)
    publish('Batch_Lot', restore('batch_lot', ''))

    next_scan()
```

### Simple Sequence Without StateMachine

For simple linear sequences, you can use plain Python:

```python
# Simple linear sequence - no StateMachine needed
stages = [
    {'name': 'Preheat', 'temp': 50, 'duration': 60},
    {'name': 'Ramp1', 'temp': 100, 'duration': 120},
    {'name': 'Soak1', 'temp': 100, 'duration': 300},
    {'name': 'Ramp2', 'temp': 150, 'duration': 120},
    {'name': 'Soak2', 'temp': 150, 'duration': 600},
    {'name': 'Cool', 'temp': 30, 'duration': 180},
]

# Wait for start command
while session.active and vars.StartSequence <= 0:
    publish('SeqStatus', 'WAITING')
    next_scan()

# Run sequence
for i, stage in enumerate(stages):
    publish('SeqStatus', stage['name'])
    publish('SeqStage', i + 1)
    outputs.set('TempSetpoint', stage['temp'])

    # Wait for temperature
    while session.active and abs(tags.Temp - stage['temp']) > 2:
        publish('SeqWaiting', 'TEMP')
        next_scan()

    # Hold for duration
    stage_start = now()
    while session.active and elapsed_since(stage_start) < stage['duration']:
        publish('SeqTimeRemaining', stage['duration'] - elapsed_since(stage_start))
        next_scan()

publish('SeqStatus', 'COMPLETE')
outputs.set('TempSetpoint', 25)
```

---

## Future Enhancements (Planned)

- `alarm.trigger()` / `alarm.clear()` - Raise system alarms from scripts
- `system.shutdown()` - Trigger controlled shutdown
- Additional Python packages (Pandas for data analysis)
- Script debugging tools (breakpoints, step-through)
