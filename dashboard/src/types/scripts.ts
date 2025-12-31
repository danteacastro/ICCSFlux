// Scripts Tab Types - Sequences, Alarms, Transformations, Triggers

// =============================================================================
// CALCULATED PARAMETERS (existing, enhanced)
// =============================================================================

export interface CalculatedParam {
  id: string
  name: string
  displayName: string
  formula: string
  unit: string
  enabled: boolean
  lastValue: number | null
  lastError: string | null
  // New: category for organization
  category?: 'custom' | 'template'
  templateId?: string
}

// =============================================================================
// TEST SEQUENCES / RECIPES
// =============================================================================

export type SequenceStepType =
  | 'ramp'          // Ramp to temperature at rate
  | 'soak'          // Hold at temperature for duration
  | 'wait'          // Wait for condition
  | 'setOutput'     // Set digital/analog output
  | 'setVariable'   // Set a script variable (for use in conditions/formulas)
  | 'loop'          // Loop marker
  | 'endLoop'       // End loop marker
  | 'message'       // Display message/notification

export interface SequenceStepBase {
  id: string
  type: SequenceStepType
  enabled: boolean
  label?: string
}

export interface RampStep extends SequenceStepBase {
  type: 'ramp'
  targetChannel: string       // Output channel to control (e.g., setpoint)
  monitorChannel: string      // Channel to monitor for completion
  targetValue: number         // Target temperature/value
  rampRate: number            // Rate per minute (e.g., °C/min)
  rampRateUnit: string        // e.g., "°C/min"
  tolerance: number           // Tolerance for "reached" detection
}

export interface SoakStep extends SequenceStepBase {
  type: 'soak'
  monitorChannel?: string     // Channel to monitor (optional)
  targetValue?: number        // Value to maintain
  tolerance?: number          // Tolerance band
  duration: number            // Duration in seconds
}

export interface WaitStep extends SequenceStepBase {
  type: 'wait'
  condition: string           // Formula that returns boolean
  timeout?: number            // Max wait time in seconds (0 = infinite)
  timeoutAction: 'abort' | 'continue' | 'alarm'
}

export interface SetOutputStep extends SequenceStepBase {
  type: 'setOutput'
  channel: string
  value: number | boolean
}

export interface SetVariableStep extends SequenceStepBase {
  type: 'setVariable'
  variableName: string        // Name of the variable (accessible as seq.variableName in formulas)
  value: number | string      // Constant value or formula to evaluate
  isFormula?: boolean         // If true, evaluate 'value' as a formula
}

export interface LoopStep extends SequenceStepBase {
  type: 'loop'
  iterations: number          // Number of loops (0 = infinite until abort)
  loopId: string              // Unique ID to match with endLoop
}

export interface EndLoopStep extends SequenceStepBase {
  type: 'endLoop'
  loopId: string              // Matches the loop start
}

export interface MessageStep extends SequenceStepBase {
  type: 'message'
  message: string
  severity: 'info' | 'warning' | 'error'
  pauseExecution: boolean     // Wait for user acknowledgment
}

export type SequenceStep =
  | RampStep
  | SoakStep
  | WaitStep
  | SetOutputStep
  | SetVariableStep
  | LoopStep
  | EndLoopStep
  | MessageStep

export type SequenceState =
  | 'idle'
  | 'running'
  | 'paused'
  | 'completed'
  | 'aborted'
  | 'error'

export interface Sequence {
  id: string
  name: string
  description: string
  steps: SequenceStep[]
  enabled: boolean
  createdAt: string
  modifiedAt: string
  // Runtime state
  state: SequenceState
  currentStepIndex: number
  currentLoopIterations: Record<string, number>  // loopId -> current iteration
  variables: Record<string, number>              // Script variables set by setVariable steps
  startTime?: number
  pausedTime?: number
  error?: string
}

// =============================================================================
// ALARMS / CONDITIONAL LOGIC
// =============================================================================

export type AlarmSeverity = 'info' | 'warning' | 'critical'
export type AlarmState = 'normal' | 'active' | 'acknowledged' | 'latched'

export type AlarmConditionOperator =
  | '>'    // greater than
  | '<'    // less than
  | '>='   // greater than or equal
  | '<='   // less than or equal
  | '=='   // equal
  | '!='   // not equal
  | 'roc>' // rate of change greater than
  | 'roc<' // rate of change less than

export interface AlarmCondition {
  channel: string
  operator: AlarmConditionOperator
  value: number
  // For compound conditions
  logic?: 'AND' | 'OR'
}

export type AlarmActionType =
  | 'notification'    // Show notification in UI
  | 'setOutput'       // Set a digital/analog output
  | 'abortSequence'   // Stop any running sequence
  | 'runSequence'     // Start a sequence (e.g., safety shutdown)
  | 'sound'           // Play alarm sound
  | 'log'             // Log to file

export interface AlarmAction {
  type: AlarmActionType
  // For setOutput
  channel?: string
  value?: number | boolean
  // For runSequence
  sequenceId?: string
  // For notification
  message?: string
  // For sound
  soundFile?: string
}

export interface Alarm {
  id: string
  name: string
  description: string
  enabled: boolean
  severity: AlarmSeverity

  // Trigger conditions
  conditions: AlarmCondition[]
  conditionLogic: 'AND' | 'OR'  // How to combine multiple conditions

  // Timing
  debounceMs: number           // Debounce time before triggering
  autoResetMs: number          // Auto-reset after condition clears (0 = manual)

  // Actions when triggered
  actions: AlarmAction[]

  // State
  state: AlarmState
  triggeredAt?: number
  acknowledgedAt?: number
  acknowledgedBy?: string

  // History
  triggerCount: number
  lastTriggered?: number
}

// =============================================================================
// DATA TRANSFORMATIONS
// =============================================================================

export type TransformationType =
  | 'rollingAverage'
  | 'rollingMin'
  | 'rollingMax'
  | 'rollingStdDev'
  | 'rateOfChange'
  | 'unitConversion'
  | 'polynomial'
  | 'lowPassFilter'
  | 'highPassFilter'
  | 'deadband'
  | 'clamp'

export interface TransformationBase {
  id: string
  name: string
  displayName: string
  type: TransformationType
  inputChannel: string
  outputUnit: string
  enabled: boolean
  lastValue: number | null
  lastError: string | null
}

export interface RollingTransformation extends TransformationBase {
  type: 'rollingAverage' | 'rollingMin' | 'rollingMax' | 'rollingStdDev'
  windowSize: number          // Number of samples
  windowType: 'samples' | 'time'  // samples or time-based
  windowTimeMs?: number       // If time-based, window in ms
}

export interface RateOfChangeTransformation extends TransformationBase {
  type: 'rateOfChange'
  timeWindowMs: number        // Calculate rate over this period
  rateUnit: string            // e.g., "°C/min"
}

export interface UnitConversionTransformation extends TransformationBase {
  type: 'unitConversion'
  conversionType: 'celsius_to_fahrenheit' | 'fahrenheit_to_celsius' |
                  'psi_to_bar' | 'bar_to_psi' |
                  'lpm_to_gpm' | 'gpm_to_lpm' |
                  'custom'
  // For custom conversion: output = (input * multiplier) + offset
  multiplier?: number
  offset?: number
}

export interface PolynomialTransformation extends TransformationBase {
  type: 'polynomial'
  // y = c0 + c1*x + c2*x^2 + c3*x^3 + ...
  coefficients: number[]
}

export interface FilterTransformation extends TransformationBase {
  type: 'lowPassFilter' | 'highPassFilter'
  cutoffFrequency: number     // Hz
  sampleRate: number          // Hz (should match system scan rate)
}

export interface DeadbandTransformation extends TransformationBase {
  type: 'deadband'
  deadband: number            // Only update if change exceeds this
}

export interface ClampTransformation extends TransformationBase {
  type: 'clamp'
  minValue: number
  maxValue: number
}

export type Transformation =
  | RollingTransformation
  | RateOfChangeTransformation
  | UnitConversionTransformation
  | PolynomialTransformation
  | FilterTransformation
  | DeadbandTransformation
  | ClampTransformation

// =============================================================================
// AUTOMATION TRIGGERS
// =============================================================================

export type TriggerType =
  | 'valueReached'    // When a channel reaches a value
  | 'timeElapsed'     // After a duration
  | 'scheduled'       // At specific time/date
  | 'stateChange'     // When system state changes
  | 'sequenceEvent'   // When sequence starts/completes/errors

export interface TriggerBase {
  id: string
  name: string
  description: string
  type: TriggerType
  enabled: boolean
  oneShot: boolean            // Fire once then disable
  cooldownMs: number          // Minimum time between triggers
  lastTriggered?: number
}

export interface ValueReachedTrigger extends TriggerBase {
  type: 'valueReached'
  channel: string
  operator: '<' | '>' | '<=' | '>=' | '==' | '!='
  value: number
  hysteresis: number          // Prevent rapid re-triggering
}

export interface TimeElapsedTrigger extends TriggerBase {
  type: 'timeElapsed'
  durationMs: number
  startEvent: 'acquisitionStart' | 'sequenceStart' | 'manual'
}

export interface ScheduledTrigger extends TriggerBase {
  type: 'scheduled'
  schedule: {
    type: 'once' | 'daily' | 'weekly'
    time: string              // HH:MM format
    daysOfWeek?: number[]     // 0-6, Sunday = 0
    date?: string             // For 'once' type, YYYY-MM-DD
  }
}

export interface StateChangeTrigger extends TriggerBase {
  type: 'stateChange'
  stateType: 'acquisition' | 'recording' | 'scheduler' | 'connection'
  fromState?: string
  toState: string
}

export interface SequenceEventTrigger extends TriggerBase {
  type: 'sequenceEvent'
  sequenceId?: string         // Specific sequence or any
  event: 'started' | 'completed' | 'aborted' | 'error' | 'stepCompleted'
}

export type Trigger =
  | ValueReachedTrigger
  | TimeElapsedTrigger
  | ScheduledTrigger
  | StateChangeTrigger
  | SequenceEventTrigger

export type TriggerActionType =
  | 'startSequence'
  | 'stopSequence'
  | 'setOutput'
  | 'startRecording'
  | 'stopRecording'
  | 'notification'
  | 'runFormula'

export interface TriggerAction {
  type: TriggerActionType
  sequenceId?: string
  channel?: string
  value?: number | boolean
  message?: string
  formula?: string
}

export interface AutomationTrigger extends TriggerBase {
  trigger: Trigger
  actions: TriggerAction[]
}

// =============================================================================
// SCRIPT TEMPLATES
// =============================================================================

export interface ScriptTemplate {
  id: string
  name: string
  description: string
  category: 'thermal' | 'pid' | 'statistics' | 'conversion' | 'safety'
  formula: string
  parameters: TemplateParameter[]
  unit: string
  icon?: string
}

export interface TemplateParameter {
  name: string
  label: string
  type: 'channel' | 'number' | 'select'
  options?: { value: string; label: string }[]
  default?: string | number
  placeholder?: string
}

// =============================================================================
// SCHEDULES - Time-based automation
// =============================================================================

export type ScheduleRepeat = 'once' | 'daily' | 'weekly' | 'monthly'

export type ScheduleActionType =
  | 'start_sequence'
  | 'start_recording'
  | 'stop_recording'
  | 'set_output'
  | 'run_formula'

export interface ScheduleAction {
  type: ScheduleActionType
  sequenceId?: string       // For start_sequence
  channel?: string          // For set_output
  value?: number | boolean  // For set_output
  formula?: string          // For run_formula
  recordingFilename?: string // For start_recording
}

export interface Schedule {
  id: string
  name: string
  description: string
  enabled: boolean
  // Timing
  startTime: string         // HH:MM format
  endTime?: string          // HH:MM format (optional, for duration-based)
  repeat: ScheduleRepeat
  daysOfWeek?: number[]     // 0-6 for weekly (0 = Sunday)
  dayOfMonth?: number       // 1-31 for monthly
  date?: string             // YYYY-MM-DD for once
  // Actions
  startActions: ScheduleAction[]  // Actions to run at start time
  endActions?: ScheduleAction[]   // Actions to run at end time (optional)
  // Runtime state
  lastRun?: string          // ISO timestamp
  nextRun?: string          // ISO timestamp
  isRunning: boolean
}

// =============================================================================
// SCRIPTS TAB STATE
// =============================================================================

export type ScriptsSubTab =
  | 'formulas'
  | 'functionBlocks'
  | 'sequences'
  | 'schedule'
  | 'alarms'
  | 'transformations'
  | 'triggers'
  | 'templates'

export interface ScriptsState {
  // UI State
  activeSubTab: ScriptsSubTab

  // Data
  calculatedParams: CalculatedParam[]
  sequences: Sequence[]
  alarms: Alarm[]
  transformations: Transformation[]
  triggers: AutomationTrigger[]

  // Runtime
  runningSequenceId: string | null
  activeAlarmIds: string[]
}

// Storage keys
export const STORAGE_KEYS = {
  CALCULATED_PARAMS: 'nisystem-scripts',
  SEQUENCES: 'nisystem-sequences',
  SCHEDULES: 'nisystem-schedules',
  ALARMS: 'nisystem-alarms',
  TRANSFORMATIONS: 'nisystem-transformations',
  TRIGGERS: 'nisystem-triggers'
} as const

// =============================================================================
// PREDEFINED TEMPLATES
// =============================================================================

export const SCRIPT_TEMPLATES: ScriptTemplate[] = [
  // Thermal calculations
  {
    id: 'temp-avg-2zone',
    name: 'Average Temperature (2 Zones)',
    description: 'Calculate average of two temperature zones',
    category: 'thermal',
    formula: '(ch.${zone1} + ch.${zone2}) / 2',
    parameters: [
      { name: 'zone1', label: 'Zone 1 Channel', type: 'channel' },
      { name: 'zone2', label: 'Zone 2 Channel', type: 'channel' }
    ],
    unit: '°C'
  },
  {
    id: 'temp-gradient',
    name: 'Temperature Gradient',
    description: 'Calculate temperature difference between two points',
    category: 'thermal',
    formula: 'abs(ch.${hot} - ch.${cold})',
    parameters: [
      { name: 'hot', label: 'Hot Side Channel', type: 'channel' },
      { name: 'cold', label: 'Cold Side Channel', type: 'channel' }
    ],
    unit: '°C'
  },
  {
    id: 'temp-uniformity',
    name: 'Temperature Uniformity',
    description: 'Calculate max deviation from average (multi-zone)',
    category: 'thermal',
    formula: 'max(abs(ch.${zone1} - ${avg}), abs(ch.${zone2} - ${avg}), abs(ch.${zone3} - ${avg}))',
    parameters: [
      { name: 'zone1', label: 'Zone 1', type: 'channel' },
      { name: 'zone2', label: 'Zone 2', type: 'channel' },
      { name: 'zone3', label: 'Zone 3', type: 'channel' },
      { name: 'avg', label: 'Average Value', type: 'number', default: 0 }
    ],
    unit: '°C'
  },

  // PID helpers
  {
    id: 'pid-error',
    name: 'PID Error',
    description: 'Calculate error between setpoint and process value',
    category: 'pid',
    formula: '${setpoint} - ch.${pv}',
    parameters: [
      { name: 'setpoint', label: 'Setpoint Value', type: 'number', default: 100 },
      { name: 'pv', label: 'Process Variable Channel', type: 'channel' }
    ],
    unit: ''
  },
  {
    id: 'pid-error-percent',
    name: 'PID Error %',
    description: 'Error as percentage of setpoint',
    category: 'pid',
    formula: '((${setpoint} - ch.${pv}) / ${setpoint}) * 100',
    parameters: [
      { name: 'setpoint', label: 'Setpoint Value', type: 'number', default: 100 },
      { name: 'pv', label: 'Process Variable Channel', type: 'channel' }
    ],
    unit: '%'
  },

  // Statistical
  {
    id: 'stats-range',
    name: 'Range (Max - Min)',
    description: 'Calculate range between two channels',
    category: 'statistics',
    formula: 'ch.${max} - ch.${min}',
    parameters: [
      { name: 'max', label: 'Maximum Channel', type: 'channel' },
      { name: 'min', label: 'Minimum Channel', type: 'channel' }
    ],
    unit: ''
  },
  {
    id: 'stats-percent',
    name: 'Percentage',
    description: 'Calculate percentage of value relative to maximum',
    category: 'statistics',
    formula: '(ch.${value} / ${maximum}) * 100',
    parameters: [
      { name: 'value', label: 'Value Channel', type: 'channel' },
      { name: 'maximum', label: 'Maximum Value', type: 'number', default: 100 }
    ],
    unit: '%'
  },

  // Unit conversions
  {
    id: 'conv-c-to-f',
    name: 'Celsius to Fahrenheit',
    description: 'Convert temperature from Celsius to Fahrenheit',
    category: 'conversion',
    formula: '(ch.${input} * 9/5) + 32',
    parameters: [
      { name: 'input', label: 'Celsius Channel', type: 'channel' }
    ],
    unit: '°F'
  },
  {
    id: 'conv-f-to-c',
    name: 'Fahrenheit to Celsius',
    description: 'Convert temperature from Fahrenheit to Celsius',
    category: 'conversion',
    formula: '(ch.${input} - 32) * 5/9',
    parameters: [
      { name: 'input', label: 'Fahrenheit Channel', type: 'channel' }
    ],
    unit: '°C'
  },
  {
    id: 'conv-psi-to-bar',
    name: 'PSI to Bar',
    description: 'Convert pressure from PSI to Bar',
    category: 'conversion',
    formula: 'ch.${input} * 0.0689476',
    parameters: [
      { name: 'input', label: 'PSI Channel', type: 'channel' }
    ],
    unit: 'bar'
  },
  {
    id: 'conv-bar-to-psi',
    name: 'Bar to PSI',
    description: 'Convert pressure from Bar to PSI',
    category: 'conversion',
    formula: 'ch.${input} * 14.5038',
    parameters: [
      { name: 'input', label: 'Bar Channel', type: 'channel' }
    ],
    unit: 'PSI'
  },
  {
    id: 'conv-420ma-scale',
    name: '4-20mA Scaling',
    description: 'Scale 4-20mA signal to engineering units',
    category: 'conversion',
    formula: '${min} + ((ch.${input} - 4) / 16) * (${max} - ${min})',
    parameters: [
      { name: 'input', label: '4-20mA Channel', type: 'channel' },
      { name: 'min', label: 'Engineering Min', type: 'number', default: 0 },
      { name: 'max', label: 'Engineering Max', type: 'number', default: 100 }
    ],
    unit: ''
  },

  // Safety
  {
    id: 'safety-limit-check',
    name: 'Limit Check',
    description: 'Returns 1 if value is within limits, 0 if outside',
    category: 'safety',
    formula: '(ch.${input} >= ${low} && ch.${input} <= ${high}) ? 1 : 0',
    parameters: [
      { name: 'input', label: 'Input Channel', type: 'channel' },
      { name: 'low', label: 'Low Limit', type: 'number', default: 0 },
      { name: 'high', label: 'High Limit', type: 'number', default: 100 }
    ],
    unit: ''
  },
  {
    id: 'safety-deviation',
    name: 'Deviation from Setpoint',
    description: 'Absolute deviation from a setpoint',
    category: 'safety',
    formula: 'abs(ch.${input} - ${setpoint})',
    parameters: [
      { name: 'input', label: 'Input Channel', type: 'channel' },
      { name: 'setpoint', label: 'Setpoint', type: 'number', default: 100 }
    ],
    unit: ''
  }
]

// =============================================================================
// UNIT CONVERSION HELPERS
// =============================================================================

export const UNIT_CONVERSIONS = {
  // Temperature
  celsius_to_fahrenheit: { formula: (x: number) => x * 9/5 + 32, fromUnit: '°C', toUnit: '°F' },
  fahrenheit_to_celsius: { formula: (x: number) => (x - 32) * 5/9, fromUnit: '°F', toUnit: '°C' },
  celsius_to_kelvin: { formula: (x: number) => x + 273.15, fromUnit: '°C', toUnit: 'K' },
  kelvin_to_celsius: { formula: (x: number) => x - 273.15, fromUnit: 'K', toUnit: '°C' },

  // Pressure
  psi_to_bar: { formula: (x: number) => x * 0.0689476, fromUnit: 'PSI', toUnit: 'bar' },
  bar_to_psi: { formula: (x: number) => x * 14.5038, fromUnit: 'bar', toUnit: 'PSI' },
  psi_to_kpa: { formula: (x: number) => x * 6.89476, fromUnit: 'PSI', toUnit: 'kPa' },
  kpa_to_psi: { formula: (x: number) => x * 0.145038, fromUnit: 'kPa', toUnit: 'PSI' },
  bar_to_kpa: { formula: (x: number) => x * 100, fromUnit: 'bar', toUnit: 'kPa' },
  kpa_to_bar: { formula: (x: number) => x * 0.01, fromUnit: 'kPa', toUnit: 'bar' },

  // Flow
  lpm_to_gpm: { formula: (x: number) => x * 0.264172, fromUnit: 'L/min', toUnit: 'GPM' },
  gpm_to_lpm: { formula: (x: number) => x * 3.78541, fromUnit: 'GPM', toUnit: 'L/min' },

  // Length
  mm_to_inch: { formula: (x: number) => x * 0.0393701, fromUnit: 'mm', toUnit: 'in' },
  inch_to_mm: { formula: (x: number) => x * 25.4, fromUnit: 'in', toUnit: 'mm' }
} as const

export type UnitConversionType = keyof typeof UNIT_CONVERSIONS

// =============================================================================
// FUNCTION BLOCKS - LabVIEW-style Multi-Input/Multi-Output Blocks
// =============================================================================

export type FunctionBlockInputType = 'channel' | 'number' | 'boolean' | 'block_output'

export interface FunctionBlockInput {
  name: string                    // Internal name (e.g., "setpoint")
  label: string                   // Display label (e.g., "Setpoint")
  type: FunctionBlockInputType
  required: boolean
  defaultValue?: number | boolean
  min?: number                    // For number type
  max?: number                    // For number type
  unit?: string                   // Display unit hint
  // Runtime binding
  binding?: string                // Channel name, constant value, or "blockId.outputName"
}

export interface FunctionBlockOutput {
  name: string                    // Internal name (e.g., "output")
  label: string                   // Display label (e.g., "Control Output")
  formula?: string                // Formula using input names (for simple outputs)
  unit: string
  // Runtime
  value: number | null
  error: string | null
}

export type FunctionBlockCategory =
  | 'control'      // PID, On/Off, Ramp
  | 'math'         // Average, Min/Max, Scale
  | 'filter'       // Low-pass, High-pass, Moving average
  | 'statistics'   // StdDev, Variance, Range
  | 'thermal'      // Heat rate, Uniformity
  | 'logic'        // AND, OR, Compare
  | 'timing'       // Timer, Counter, Rate limit
  | 'custom'       // User-defined

export interface FunctionBlockState {
  // For stateful blocks (PID integral, filters, etc.)
  [key: string]: any
}

export interface FunctionBlock {
  id: string
  name: string
  displayName: string
  description: string
  category: FunctionBlockCategory
  templateId?: string             // If created from a template
  enabled: boolean

  // Interface definition
  inputs: FunctionBlockInput[]
  outputs: FunctionBlockOutput[]

  // For stateful blocks
  state: FunctionBlockState

  // Execution order (for chaining)
  priority: number                // Lower = executes first

  // Metadata
  createdAt: string
  modifiedAt: string
}

// =============================================================================
// FUNCTION BLOCK TEMPLATES
// =============================================================================

export interface FunctionBlockTemplate {
  id: string
  name: string
  description: string
  category: FunctionBlockCategory
  icon: string

  // Template interface
  inputs: Omit<FunctionBlockInput, 'binding'>[]
  outputs: Omit<FunctionBlockOutput, 'value' | 'error'>[]

  // Initial state for stateful blocks
  initialState?: FunctionBlockState

  // Custom evaluation function name (for complex blocks like PID)
  evaluator?: string
}

export const FUNCTION_BLOCK_TEMPLATES: FunctionBlockTemplate[] = [
  // ═══════════════════════════════════════════════════════════════════════════
  // CONTROL BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'pid',
    name: 'PID Controller',
    description: 'Proportional-Integral-Derivative controller with anti-windup',
    category: 'control',
    icon: '⚙️',
    inputs: [
      { name: 'setpoint', label: 'Setpoint', type: 'number', required: true, defaultValue: 100, unit: '' },
      { name: 'pv', label: 'Process Variable', type: 'channel', required: true },
      { name: 'kp', label: 'Proportional Gain (Kp)', type: 'number', required: true, defaultValue: 1.0, min: 0 },
      { name: 'ki', label: 'Integral Gain (Ki)', type: 'number', required: true, defaultValue: 0.1, min: 0 },
      { name: 'kd', label: 'Derivative Gain (Kd)', type: 'number', required: true, defaultValue: 0.01, min: 0 },
      { name: 'outMin', label: 'Output Min', type: 'number', required: false, defaultValue: 0 },
      { name: 'outMax', label: 'Output Max', type: 'number', required: false, defaultValue: 100 },
    ],
    outputs: [
      { name: 'output', label: 'Control Output', unit: '%' },
      { name: 'error', label: 'Error', unit: '' },
      { name: 'pTerm', label: 'P Term', unit: '' },
      { name: 'iTerm', label: 'I Term', unit: '' },
      { name: 'dTerm', label: 'D Term', unit: '' },
    ],
    initialState: {
      integral: 0,
      lastError: 0,
      lastTime: 0,
    },
    evaluator: 'pid',
  },
  {
    id: 'onoff',
    name: 'On/Off Controller',
    description: 'Simple on/off control with hysteresis (deadband)',
    category: 'control',
    icon: '🔘',
    inputs: [
      { name: 'setpoint', label: 'Setpoint', type: 'number', required: true, defaultValue: 100 },
      { name: 'pv', label: 'Process Variable', type: 'channel', required: true },
      { name: 'hysteresis', label: 'Hysteresis', type: 'number', required: true, defaultValue: 2, min: 0 },
    ],
    outputs: [
      { name: 'output', label: 'Output (0 or 1)', unit: '' },
      { name: 'error', label: 'Error', unit: '' },
    ],
    initialState: {
      lastOutput: 0,
    },
    evaluator: 'onoff',
  },
  {
    id: 'ramp-generator',
    name: 'Ramp Generator',
    description: 'Generate a ramping setpoint from start to target at specified rate',
    category: 'control',
    icon: '📈',
    inputs: [
      { name: 'startValue', label: 'Start Value', type: 'number', required: true, defaultValue: 0 },
      { name: 'targetValue', label: 'Target Value', type: 'number', required: true, defaultValue: 100 },
      { name: 'rampRate', label: 'Ramp Rate (per minute)', type: 'number', required: true, defaultValue: 10, min: 0 },
      { name: 'enable', label: 'Enable', type: 'boolean', required: true, defaultValue: false },
    ],
    outputs: [
      { name: 'output', label: 'Current Setpoint', unit: '' },
      { name: 'complete', label: 'Ramp Complete (0/1)', unit: '' },
      { name: 'progress', label: 'Progress %', unit: '%' },
    ],
    initialState: {
      currentValue: 0,
      startTime: 0,
      isRunning: false,
    },
    evaluator: 'ramp',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // MATH BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'average-2',
    name: 'Average (2 inputs)',
    description: 'Calculate average of two values',
    category: 'math',
    icon: '➗',
    inputs: [
      { name: 'a', label: 'Input A', type: 'channel', required: true },
      { name: 'b', label: 'Input B', type: 'channel', required: true },
    ],
    outputs: [
      { name: 'avg', label: 'Average', formula: '(a + b) / 2', unit: '' },
      { name: 'diff', label: 'Difference (A-B)', formula: 'a - b', unit: '' },
    ],
  },
  {
    id: 'average-4',
    name: 'Average (4 inputs)',
    description: 'Calculate average of four values',
    category: 'math',
    icon: '➗',
    inputs: [
      { name: 'a', label: 'Input A', type: 'channel', required: true },
      { name: 'b', label: 'Input B', type: 'channel', required: true },
      { name: 'c', label: 'Input C', type: 'channel', required: false },
      { name: 'd', label: 'Input D', type: 'channel', required: false },
    ],
    outputs: [
      { name: 'avg', label: 'Average', unit: '' },
      { name: 'min', label: 'Minimum', unit: '' },
      { name: 'max', label: 'Maximum', unit: '' },
      { name: 'range', label: 'Range (Max-Min)', unit: '' },
    ],
    evaluator: 'average4',
  },
  {
    id: 'scale',
    name: 'Linear Scale',
    description: 'Scale input from one range to another (y = mx + b)',
    category: 'math',
    icon: '📏',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'inMin', label: 'Input Min', type: 'number', required: true, defaultValue: 0 },
      { name: 'inMax', label: 'Input Max', type: 'number', required: true, defaultValue: 100 },
      { name: 'outMin', label: 'Output Min', type: 'number', required: true, defaultValue: 0 },
      { name: 'outMax', label: 'Output Max', type: 'number', required: true, defaultValue: 100 },
    ],
    outputs: [
      { name: 'output', label: 'Scaled Output', formula: 'outMin + ((input - inMin) / (inMax - inMin)) * (outMax - outMin)', unit: '' },
      { name: 'percent', label: 'Percent of Range', formula: '((input - inMin) / (inMax - inMin)) * 100', unit: '%' },
    ],
  },
  {
    id: 'clamp',
    name: 'Clamp/Limit',
    description: 'Limit a value to a specified range',
    category: 'math',
    icon: '📎',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'min', label: 'Minimum', type: 'number', required: true, defaultValue: 0 },
      { name: 'max', label: 'Maximum', type: 'number', required: true, defaultValue: 100 },
    ],
    outputs: [
      { name: 'output', label: 'Clamped Output', unit: '' },
      { name: 'limited', label: 'Is Limited (0/1)', unit: '' },
    ],
    evaluator: 'clamp',
  },
  {
    id: 'deadband',
    name: 'Deadband',
    description: 'Only update output when input changes by more than deadband',
    category: 'math',
    icon: '🎯',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'deadband', label: 'Deadband', type: 'number', required: true, defaultValue: 1, min: 0 },
    ],
    outputs: [
      { name: 'output', label: 'Output', unit: '' },
      { name: 'changed', label: 'Changed (0/1)', unit: '' },
    ],
    initialState: {
      lastOutput: null,
    },
    evaluator: 'deadband',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // FILTER BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'moving-avg',
    name: 'Moving Average',
    description: 'Calculate moving average over N samples',
    category: 'filter',
    icon: '〰️',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'samples', label: 'Sample Count', type: 'number', required: true, defaultValue: 10, min: 1, max: 1000 },
    ],
    outputs: [
      { name: 'output', label: 'Filtered Output', unit: '' },
      { name: 'stddev', label: 'Std Deviation', unit: '' },
    ],
    initialState: {
      buffer: [],
    },
    evaluator: 'movingAvg',
  },
  {
    id: 'lowpass',
    name: 'Low-Pass Filter',
    description: 'First-order low-pass filter (exponential smoothing)',
    category: 'filter',
    icon: '📉',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'alpha', label: 'Smoothing Factor (0-1)', type: 'number', required: true, defaultValue: 0.1, min: 0.01, max: 1 },
    ],
    outputs: [
      { name: 'output', label: 'Filtered Output', unit: '' },
    ],
    initialState: {
      lastOutput: null,
    },
    evaluator: 'lowpass',
  },
  {
    id: 'rate-of-change',
    name: 'Rate of Change',
    description: 'Calculate rate of change (derivative) per minute',
    category: 'filter',
    icon: '📊',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
    ],
    outputs: [
      { name: 'rate', label: 'Rate (per minute)', unit: '/min' },
      { name: 'ratePerSec', label: 'Rate (per second)', unit: '/s' },
    ],
    initialState: {
      lastValue: null,
      lastTime: 0,
    },
    evaluator: 'rateOfChange',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // STATISTICS BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'min-max-tracker',
    name: 'Min/Max Tracker',
    description: 'Track minimum and maximum values (resettable)',
    category: 'statistics',
    icon: '📈',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'reset', label: 'Reset', type: 'boolean', required: false, defaultValue: false },
    ],
    outputs: [
      { name: 'current', label: 'Current Value', unit: '' },
      { name: 'min', label: 'Minimum', unit: '' },
      { name: 'max', label: 'Maximum', unit: '' },
      { name: 'range', label: 'Range', unit: '' },
    ],
    initialState: {
      min: null,
      max: null,
    },
    evaluator: 'minMaxTracker',
  },
  {
    id: 'accumulator',
    name: 'Accumulator/Integrator',
    description: 'Accumulate (integrate) input values over time',
    category: 'statistics',
    icon: '∑',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'reset', label: 'Reset', type: 'boolean', required: false, defaultValue: false },
      { name: 'scale', label: 'Scale Factor', type: 'number', required: false, defaultValue: 1 },
    ],
    outputs: [
      { name: 'total', label: 'Total', unit: '' },
      { name: 'count', label: 'Sample Count', unit: '' },
      { name: 'average', label: 'Average', unit: '' },
    ],
    initialState: {
      total: 0,
      count: 0,
    },
    evaluator: 'accumulator',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // THERMAL BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'temp-uniformity',
    name: 'Temperature Uniformity',
    description: 'Calculate temperature uniformity across multiple zones',
    category: 'thermal',
    icon: '🌡️',
    inputs: [
      { name: 'zone1', label: 'Zone 1', type: 'channel', required: true },
      { name: 'zone2', label: 'Zone 2', type: 'channel', required: true },
      { name: 'zone3', label: 'Zone 3', type: 'channel', required: false },
      { name: 'zone4', label: 'Zone 4', type: 'channel', required: false },
    ],
    outputs: [
      { name: 'average', label: 'Average Temp', unit: '°C' },
      { name: 'uniformity', label: 'Uniformity (±)', unit: '°C' },
      { name: 'min', label: 'Min Temp', unit: '°C' },
      { name: 'max', label: 'Max Temp', unit: '°C' },
      { name: 'spread', label: 'Spread (Max-Min)', unit: '°C' },
    ],
    evaluator: 'tempUniformity',
  },
  {
    id: 'heat-rate',
    name: 'Heat Rate Calculator',
    description: 'Calculate heating/cooling rate',
    category: 'thermal',
    icon: '🔥',
    inputs: [
      { name: 'temperature', label: 'Temperature', type: 'channel', required: true },
      { name: 'windowSec', label: 'Calculation Window (sec)', type: 'number', required: true, defaultValue: 60, min: 1 },
    ],
    outputs: [
      { name: 'ratePerMin', label: 'Rate (°/min)', unit: '°C/min' },
      { name: 'ratePerHour', label: 'Rate (°/hour)', unit: '°C/hr' },
      { name: 'isHeating', label: 'Is Heating (0/1)', unit: '' },
    ],
    initialState: {
      samples: [],
    },
    evaluator: 'heatRate',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // LOGIC BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'compare',
    name: 'Compare',
    description: 'Compare a value against a threshold',
    category: 'logic',
    icon: '⚖️',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'threshold', label: 'Threshold', type: 'number', required: true, defaultValue: 100 },
      { name: 'hysteresis', label: 'Hysteresis', type: 'number', required: false, defaultValue: 0, min: 0 },
    ],
    outputs: [
      { name: 'above', label: 'Above Threshold (0/1)', unit: '' },
      { name: 'below', label: 'Below Threshold (0/1)', unit: '' },
      { name: 'equal', label: 'At Threshold (0/1)', unit: '' },
      { name: 'deviation', label: 'Deviation from Threshold', unit: '' },
    ],
    evaluator: 'compare',
  },
  {
    id: 'select',
    name: 'Select (Mux)',
    description: 'Select between two inputs based on condition',
    category: 'logic',
    icon: '🔀',
    inputs: [
      { name: 'condition', label: 'Condition (0=A, 1=B)', type: 'channel', required: true },
      { name: 'inputA', label: 'Input A', type: 'channel', required: true },
      { name: 'inputB', label: 'Input B', type: 'channel', required: true },
    ],
    outputs: [
      { name: 'output', label: 'Selected Output', unit: '' },
      { name: 'selected', label: 'Selected Input (0=A, 1=B)', unit: '' },
    ],
    evaluator: 'select',
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // TIMING BLOCKS
  // ═══════════════════════════════════════════════════════════════════════════
  {
    id: 'timer',
    name: 'Timer',
    description: 'Measure elapsed time while condition is true',
    category: 'timing',
    icon: '⏱️',
    inputs: [
      { name: 'condition', label: 'Condition', type: 'channel', required: true },
      { name: 'reset', label: 'Reset', type: 'boolean', required: false, defaultValue: false },
    ],
    outputs: [
      { name: 'seconds', label: 'Elapsed Seconds', unit: 's' },
      { name: 'minutes', label: 'Elapsed Minutes', unit: 'min' },
      { name: 'hours', label: 'Elapsed Hours', unit: 'hr' },
      { name: 'isRunning', label: 'Is Running (0/1)', unit: '' },
    ],
    initialState: {
      startTime: null,
      accumulatedTime: 0,
      wasRunning: false,
    },
    evaluator: 'timer',
  },
  {
    id: 'pulse-counter',
    name: 'Pulse Counter',
    description: 'Count rising edges (0→1 transitions)',
    category: 'timing',
    icon: '🔢',
    inputs: [
      { name: 'input', label: 'Input', type: 'channel', required: true },
      { name: 'threshold', label: 'Threshold', type: 'number', required: true, defaultValue: 0.5 },
      { name: 'reset', label: 'Reset', type: 'boolean', required: false, defaultValue: false },
    ],
    outputs: [
      { name: 'count', label: 'Pulse Count', unit: '' },
      { name: 'state', label: 'Current State (0/1)', unit: '' },
    ],
    initialState: {
      count: 0,
      lastState: false,
    },
    evaluator: 'pulseCounter',
  },
]

// Storage key for function blocks
export const FUNCTION_BLOCKS_STORAGE_KEY = 'nisystem-function-blocks'
