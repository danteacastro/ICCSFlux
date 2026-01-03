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
  category: 'basic' | 'calculation' | 'control' | 'monitoring'
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
  }
]

// =============================================================================
// STORAGE KEY
// =============================================================================

export const PYTHON_SCRIPTS_STORAGE_KEY = 'nisystem-python-scripts'
