/**
 * Python Scripts Type Definitions
 *
 * Types for the Pyodide-based Python scripting system in NISystem.
 * Scripts run as `while session.active:` loops synchronized with cDAQ scan cycle.
 */

// =============================================================================
// CORE TYPES
// =============================================================================

/**
 * When a script should automatically start:
 * - 'manual': User clicks Run button explicitly (no auto-start)
 * - 'acquisition': Starts when cDAQ acquisition starts, stops when it stops
 * - 'session': Starts when test session starts, stops when session ends
 */
export type ScriptRunMode = 'manual' | 'acquisition' | 'session'

export interface PythonScript {
  id: string
  name: string
  description: string
  code: string
  enabled: boolean
  runMode: ScriptRunMode  // When to auto-start this script
  createdAt: string   // ISO timestamp
  modifiedAt: string  // ISO timestamp
  lastRunAt?: string  // ISO timestamp
  lastError?: string
  // Imported data from CSV/Excel files
  importedData?: ImportedDataFile[]
}

export interface ImportedDataFile {
  filename: string
  variableName: string  // Name to use in script (e.g., 'calibration_data')
  data: Record<string, any>[]  // Array of row objects
  columns: string[]  // Column headers
  importedAt: string  // ISO timestamp
}

export interface PublishedValue {
  name: string
  value: number
  units: string
  description: string
  scriptId: string
  timestamp: number  // ms since epoch
}

export type ScriptOutputType = 'stdout' | 'stderr' | 'error' | 'info' | 'warning'

export interface ScriptOutput {
  type: ScriptOutputType
  message: string
  timestamp: number
  lineNumber?: number
}

export type ScriptState = 'idle' | 'running' | 'stopping' | 'error'

export interface ScriptStatus {
  scriptId: string
  state: ScriptState
  startedAt?: number
  iterations?: number     // Loop count
  lastScanDuration?: number  // ms
  error?: string
}

export type PyodideStatus = 'not_loaded' | 'loading' | 'ready' | 'error'

// =============================================================================
// SCRIPT EXECUTION CONTEXT
// =============================================================================

/**
 * Context passed to Python scripts via the bridge
 */
export interface ScriptContext {
  // Current channel values (read-only)
  channelValues: Record<string, number>

  // Channel metadata
  channelUnits: Record<string, string>

  // Session state
  sessionActive: boolean
  sessionElapsed: number  // seconds

  // Functions exposed to Python
  setOutput: (channel: string, value: number | boolean) => void
  publish: (name: string, value: number, units?: string, description?: string) => void
  triggerAlarm: (name: string, message: string, severity: string) => void
  clearAlarm: (name: string) => void
  log: (type: ScriptOutputType, message: string) => void
}

// =============================================================================
// DEFAULT SCRIPT TEMPLATE
// =============================================================================

export const DEFAULT_SCRIPT_CODE = `# NISystem Python Script
# This script runs synchronized with your cDAQ scan cycle.

while session.active:
    # Read channel values
    # temp = tags.TC001
    # flow = tags.Flow_Rate

    # Perform calculations
    # avg_temp = (tags.TC001 + tags.TC002) / 2

    # Publish computed values (appear in widget channel list)
    # publish('AvgTemp', avg_temp, units='F')

    # Control outputs
    # outputs.set('Valve_1', True)

    # Time functions available:
    # now()          - Unix timestamp in seconds (float)
    # now_ms()       - Unix timestamp in milliseconds (int)
    # now_iso()      - Current time as ISO 8601 string
    # time_of_day()  - Current time as "HH:MM:SS"
    # elapsed_since(start_ts) - Seconds since start_ts

    # Session control (use sparingly):
    # session.start()           - Start acquisition
    # session.stop()            - Stop acquisition
    # session.start_recording() - Start recording to file
    # session.stop_recording()  - Stop recording
    # session.recording         - True if currently recording

    # Wait for next scan cycle (REQUIRED in while loop)
    await next_scan()
`

// =============================================================================
// SCRIPT TEMPLATES
// =============================================================================

export interface ScriptTemplate {
  id: string
  name: string
  description: string
  category: 'basic' | 'calculation' | 'control' | 'monitoring' | 'session' | 'scheduling'
  code: string
}

export const SCRIPT_TEMPLATES: ScriptTemplate[] = [
  {
    id: 'basic-loop',
    name: 'Basic Loop',
    description: 'Simple while loop reading channels',
    category: 'basic',
    code: `# Basic monitoring loop
while session.active:
    value = tags.Channel_1
    print(f"Channel_1 = {value}")
    await next_scan()
`
  },
  {
    id: 'efficiency-calc',
    name: 'Efficiency Calculator',
    description: 'Calculate and publish efficiency from input/output',
    category: 'calculation',
    code: `# Efficiency calculation
while session.active:
    input_power = tags.Power_In
    output_power = tags.Power_Out

    if input_power > 0:
        efficiency = (output_power / input_power) * 100
    else:
        efficiency = 0

    publish('Efficiency', round(efficiency, 1), units='%')
    await next_scan()
`
  },
  {
    id: 'flow-from-counter',
    name: 'Flow Rate from Counter',
    description: 'Calculate flow rate (GPM) from pulse counter',
    category: 'calculation',
    code: `# Flow rate from pulse counter
K_FACTOR = 100.0  # pulses per gallon

rate = RateCalculator(window_seconds=60)

while session.active:
    pulses = tags.Flow_Counter
    gpm = rate.update(pulses) / K_FACTOR * 60  # per minute

    publish('Flow_GPM', round(gpm, 2), units='GPM')
    await next_scan()
`
  },
  {
    id: 'valve-cycle',
    name: 'Valve Cycling',
    description: 'Cycle a valve on/off at intervals',
    category: 'control',
    code: `# Valve cycling control
import time

CYCLE_ON = 5.0   # seconds
CYCLE_OFF = 5.0  # seconds

valve_on = False
last_toggle = time.time()

while session.active:
    elapsed = time.time() - last_toggle

    if valve_on and elapsed >= CYCLE_ON:
        outputs.set('Valve_1', False)
        valve_on = False
        last_toggle = time.time()
    elif not valve_on and elapsed >= CYCLE_OFF:
        outputs.set('Valve_1', True)
        valve_on = True
        last_toggle = time.time()

    await next_scan()
`
  },
  {
    id: 'temp-monitor',
    name: 'Temperature Monitor',
    description: 'Monitor temperature with rolling statistics',
    category: 'monitoring',
    code: `# Temperature monitoring with statistics
stats = RollingStats(window_size=100)

while session.active:
    temp = tags.TC001
    s = stats.update(temp)

    publish('TC001_Avg', round(s['mean'], 1), units='F')
    publish('TC001_Min', round(s['min'], 1), units='F')
    publish('TC001_Max', round(s['max'], 1), units='F')

    # Check for high temperature
    if temp > 200:
        print(f"WARNING: High temperature: {temp}F")

    await next_scan()
`
  },
  {
    id: 'timed-recording',
    name: 'Timed Recording',
    description: 'Start recording, run for duration, stop recording',
    category: 'session',
    code: `# Timed recording session
# Automatically starts recording for a fixed duration

RECORD_DURATION = 60  # seconds

print(f"Starting {RECORD_DURATION}s recording at {time_of_day()}")
session.start_recording()
start_time = now()

while session.active:
    elapsed = elapsed_since(start_time)

    # Publish elapsed time
    publish('RecordTime', round(elapsed, 1), units='s')

    # Stop after duration
    if elapsed >= RECORD_DURATION:
        session.stop_recording()
        print(f"Recording complete at {time_of_day()}")
        break

    await next_scan()
`
  },
  {
    id: 'condition-recording',
    name: 'Conditional Recording',
    description: 'Start/stop recording based on channel conditions',
    category: 'session',
    code: `# Conditional recording
# Records data when temperature exceeds threshold

TEMP_THRESHOLD = 150  # Start recording above this
HYSTERESIS = 5        # Stop when below threshold - hysteresis

recording_active = False

while session.active:
    temp = tags.TC001

    # Start recording on high temperature
    if not recording_active and temp > TEMP_THRESHOLD:
        session.start_recording()
        recording_active = True
        print(f"Started recording - temp {temp}F at {time_of_day()}")

    # Stop recording when temperature drops
    elif recording_active and temp < (TEMP_THRESHOLD - HYSTERESIS):
        session.stop_recording()
        recording_active = False
        print(f"Stopped recording - temp {temp}F at {time_of_day()}")

    publish('Recording', 1 if recording_active else 0)
    await next_scan()
`
  },
  {
    id: 'timestamped-log',
    name: 'Timestamped Logging',
    description: 'Log events with timestamps',
    category: 'monitoring',
    code: `# Timestamped event logging
# Logs state changes with precise timestamps

last_state = None

while session.active:
    # Detect state changes
    current = tags.Digital_Input > 0.5

    if current != last_state:
        timestamp = now_iso()
        state_str = "ON" if current else "OFF"
        print(f"[{timestamp}] State changed to {state_str}")

        # Publish change count
        if last_state is not None:
            publish('StateChanges', tags.get('StateChanges', 0) + 1)

    last_state = current
    await next_scan()
`
  },
  {
    id: 'scheduled-actions',
    name: 'Scheduled Actions',
    description: 'Run actions on a schedule (interval, cron, one-shot)',
    category: 'scheduling',
    code: `# Scheduled actions using Scheduler
# Supports interval, cron-like, and one-shot jobs

scheduler = Scheduler()

def log_stats():
    print(f"[{time_of_day()}] Stats: Temp={tags.TC001:.1f}F")

def hourly_report():
    print(f"=== Hourly Report at {now_iso()} ===")
    print(f"Average temp: {tags.get('TC001_Avg', 0):.1f}F")

# Log every 30 seconds
scheduler.add_interval('stats', seconds=30, func=log_stats)

# Run at the top of each hour
scheduler.add_cron('hourly', minute=0, func=hourly_report)

# One-shot reminder in 5 minutes
scheduler.add_once('reminder', delay=300,
    func=lambda: print("5 minute reminder!"))

while session.active:
    await scheduler.tick()
    await next_scan()
`
  },
  {
    id: 'auto-start-stop',
    name: 'Auto Start/Stop Session',
    description: 'Automatically control acquisition based on conditions',
    category: 'session',
    code: `# Automatic session control
# Starts acquisition when trigger detected, stops on completion

TRIGGER_THRESHOLD = 5.0   # Start above this
COMPLETE_THRESHOLD = 2.0  # Stop below this
STABLE_TIME = 5.0         # Seconds stable before stopping

stable_start = None

while session.active:
    signal = tags.Trigger_Signal

    # Check if signal has been below threshold long enough
    if signal < COMPLETE_THRESHOLD:
        if stable_start is None:
            stable_start = now()
        elif elapsed_since(stable_start) >= STABLE_TIME:
            print(f"Test complete at {time_of_day()}")
            session.stop_recording()
            session.stop()
            break
    else:
        stable_start = None

    publish('TestActive', 1)
    await next_scan()

print("Session ended")
`
  },
  {
    id: 'imported-data-lookup',
    name: 'Lookup Table',
    description: 'Use imported CSV/Excel data as a lookup table',
    category: 'calculation',
    code: `# Lookup table from imported data
# First, click "Load Data" and import a CSV with columns: temp, correction
# Example CSV:
#   temp,correction
#   70,0.0
#   80,0.5
#   90,1.2
#   100,2.1

def find_correction(temp_value):
    """Linear interpolation lookup in imported data table"""
    if not data or len(data) == 0:
        return 0.0

    # Sort by temperature
    sorted_data = sorted(data, key=lambda r: r.get('temp', 0))

    # Find surrounding points
    for i, row in enumerate(sorted_data):
        if row['temp'] >= temp_value:
            if i == 0:
                return row['correction']
            # Interpolate between previous and current
            prev = sorted_data[i-1]
            t_range = row['temp'] - prev['temp']
            if t_range == 0:
                return row['correction']
            t_frac = (temp_value - prev['temp']) / t_range
            return prev['correction'] + t_frac * (row['correction'] - prev['correction'])

    # Beyond table, use last value
    return sorted_data[-1]['correction']

while session.active:
    raw_temp = tags.TC001
    correction = find_correction(raw_temp)
    corrected = raw_temp + correction

    publish('CorrectedTemp', corrected, units='F')
    await next_scan()
`
  },
  {
    id: 'imported-data-calibration',
    name: 'Calibration Curve',
    description: 'Apply calibration from imported data',
    category: 'calculation',
    code: `# Calibration curve from imported CSV
# Import a CSV with columns: raw, calibrated
# The script will interpolate between points

import bisect

# Pre-process imported data into sorted arrays
raw_values = []
cal_values = []

if data and len(data) > 0:
    sorted_data = sorted(data, key=lambda r: r.get('raw', 0))
    raw_values = [r['raw'] for r in sorted_data]
    cal_values = [r['calibrated'] for r in sorted_data]
    print(f"Loaded calibration with {len(raw_values)} points")

def apply_calibration(raw):
    """Apply calibration curve with linear interpolation"""
    if len(raw_values) == 0:
        return raw

    # Find position in sorted array
    idx = bisect.bisect_left(raw_values, raw)

    if idx == 0:
        return cal_values[0]
    if idx >= len(raw_values):
        return cal_values[-1]

    # Linear interpolation
    x0, x1 = raw_values[idx-1], raw_values[idx]
    y0, y1 = cal_values[idx-1], cal_values[idx]
    t = (raw - x0) / (x1 - x0) if x1 != x0 else 0
    return y0 + t * (y1 - y0)

while session.active:
    raw = tags.Sensor_Raw
    calibrated = apply_calibration(raw)

    publish('Sensor_Cal', calibrated, units='psi')
    await next_scan()
`
  }
]

// =============================================================================
// STORAGE KEY
// =============================================================================

export const PYTHON_SCRIPTS_STORAGE_KEY = 'nisystem-python-scripts'
