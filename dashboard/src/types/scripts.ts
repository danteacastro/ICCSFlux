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
  | 'loop'          // For loop - fixed iterations
  | 'endLoop'       // End loop marker
  | 'whileLoop'     // While loop - condition-based
  | 'endWhile'      // End while loop
  | 'forEachLoop'   // For each - iterate over channels/items
  | 'endForEach'    // End for each loop
  | 'repeatUntil'   // Repeat until condition becomes true
  | 'endRepeat'     // End repeat until
  | 'break'         // Break out of current loop
  | 'continue'      // Skip to next iteration
  | 'message'       // Display message/notification
  | 'if'            // Conditional branch start
  | 'elseIf'        // Else if branch
  | 'else'          // Else branch
  | 'endIf'         // End conditional block
  | 'switch'        // Switch/case statement start
  | 'case'          // Case branch
  | 'defaultCase'   // Default case
  | 'endSwitch'     // End switch block
  | 'recording'     // Start/stop data recording
  | 'safetyCheck'   // Check safety interlock before proceeding
  | 'callSequence'  // Call another sequence as subroutine
  | 'parallel'      // Parallel branch step
  | 'endParallel'   // End parallel branch
  | 'goto'          // Jump to another step
  | 'retry'         // Retry wrapper start
  | 'endRetry'      // End retry wrapper
  | 'callSequenceWithParams'  // Call sequence with parameters
  | 'runDrawPattern' // Execute a draw pattern (valve dosing sequence)
  | 'singleDraw'    // Execute a single valve draw (dispense target volume)
  | 'calculate'     // Evaluate expression and store result
  | 'delay'         // Simple delay/sleep
  | 'log'           // Log value to console/file

export interface SequenceStepBase {
  id: string
  type: SequenceStepType
  enabled: boolean
  label?: string
  notes?: string              // Documentation/comments for the step
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
  timeoutAction: 'abort' | 'continue' | 'alarm' | 'retry' | 'skip'
  // Retry options (when timeoutAction is 'retry')
  retryCount?: number         // Number of retries before final failure (default: 3)
  retryDelayMs?: number       // Delay between retries in ms (default: 1000)
  onFinalFailure?: 'abort' | 'continue' | 'alarm'  // Action after all retries exhausted
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

// Conditional branching - If statement
export interface IfStep extends SequenceStepBase {
  type: 'if'
  condition: string           // Formula that returns boolean/truthy
  ifId: string                // Unique ID to match with else/endIf
}

export interface ElseStep extends SequenceStepBase {
  type: 'else'
  ifId: string                // Matches the if start
}

export interface EndIfStep extends SequenceStepBase {
  type: 'endIf'
  ifId: string                // Matches the if start
}

// Recording control
export interface RecordingStep extends SequenceStepBase {
  type: 'recording'
  action: 'start' | 'stop'
  filename?: string           // Optional custom filename for start
}

// Safety interlock check
export interface SafetyCheckStep extends SequenceStepBase {
  type: 'safetyCheck'
  condition: string           // Safety condition that must be true
  failAction: 'abort' | 'pause' | 'alarm'
  failMessage: string         // Message to show if check fails
}

// Call another sequence
export interface CallSequenceStep extends SequenceStepBase {
  type: 'callSequence'
  sequenceId: string          // ID of sequence to call
  waitForCompletion: boolean  // If true, wait for called sequence to finish
}

// Run a draw pattern (valve dosing sequence)
export interface RunDrawPatternStep extends SequenceStepBase {
  type: 'runDrawPattern'
  drawPatternId: string       // ID of draw pattern to execute
  waitForCompletion: boolean  // If true, wait for pattern to complete
}

// Execute a single valve draw (dispense target volume)
export interface SingleDrawStep extends SequenceStepBase {
  type: 'singleDraw'
  valve: string               // Valve/output channel
  flowChannel: string         // Flow totalizer channel
  volumeTarget: number        // Target volume to dispense
  volumeUnit: string          // Unit (gal, L, etc.)
  maxDuration: number         // Safety timeout in seconds
}

// While loop - repeat while condition is true
export interface WhileLoopStep extends SequenceStepBase {
  type: 'whileLoop'
  condition: string           // Formula that returns boolean - loop while true
  loopId: string              // Unique ID to match with endWhile
  maxIterations?: number      // Safety limit (default: 10000)
}

export interface EndWhileStep extends SequenceStepBase {
  type: 'endWhile'
  loopId: string              // Matches the while loop start
}

// For each loop - iterate over a list of items
export interface ForEachLoopStep extends SequenceStepBase {
  type: 'forEachLoop'
  loopId: string              // Unique ID to match with endForEach
  iteratorVar: string         // Variable name for current item (e.g., "item", "channel")
  indexVar?: string           // Variable name for current index (e.g., "i")
  source: ForEachSource       // What to iterate over
}

export type ForEachSource =
  | { type: 'channels'; filter?: 'all' | 'input' | 'output' | 'digital' | 'analog'; pattern?: string }
  | { type: 'range'; start: number; end: number; step?: number }
  | { type: 'array'; values: (number | string)[] }
  | { type: 'variable'; variableName: string }  // Iterate over array stored in variable

export interface EndForEachStep extends SequenceStepBase {
  type: 'endForEach'
  loopId: string              // Matches the for each loop start
}

// Repeat until - repeat until condition becomes true
export interface RepeatUntilStep extends SequenceStepBase {
  type: 'repeatUntil'
  condition: string           // Formula - loop UNTIL this becomes true
  loopId: string              // Unique ID to match with endRepeat
  maxIterations?: number      // Safety limit (default: 10000)
  checkAfter?: boolean        // If true, check condition after loop body (do-while style), default: false
}

export interface EndRepeatStep extends SequenceStepBase {
  type: 'endRepeat'
  loopId: string              // Matches the repeat until start
}

// Break - exit current loop immediately
export interface BreakStep extends SequenceStepBase {
  type: 'break'
  loopId?: string             // Optional: specific loop to break (default: innermost)
}

// Continue - skip to next iteration
export interface ContinueStep extends SequenceStepBase {
  type: 'continue'
  loopId?: string             // Optional: specific loop to continue (default: innermost)
}

// Else If - additional condition branch
export interface ElseIfStep extends SequenceStepBase {
  type: 'elseIf'
  condition: string           // Formula that returns boolean
  ifId: string                // Matches the if start
}

// Switch/Case statement
export interface SwitchStep extends SequenceStepBase {
  type: 'switch'
  expression: string          // Formula to evaluate and compare
  switchId: string            // Unique ID to match with cases and endSwitch
}

export interface CaseStep extends SequenceStepBase {
  type: 'case'
  switchId: string            // Matches the switch start
  value: number | string      // Value to match against switch expression
  compareOperator?: '==' | '===' | '>=' | '<=' | '>' | '<'  // Default: '==='
}

export interface DefaultCaseStep extends SequenceStepBase {
  type: 'defaultCase'
  switchId: string            // Matches the switch start
}

export interface EndSwitchStep extends SequenceStepBase {
  type: 'endSwitch'
  switchId: string            // Matches the switch start
}

// Calculate - evaluate expression and store result
export interface CalculateStep extends SequenceStepBase {
  type: 'calculate'
  expression: string          // Formula to evaluate
  resultVar: string           // Variable name to store result
  precision?: number          // Decimal places for rounding (optional)
}

// Delay - simple sleep/wait
export interface DelayStep extends SequenceStepBase {
  type: 'delay'
  duration: number            // Duration in milliseconds
  durationUnit?: 'ms' | 's' | 'm' | 'h'  // Default: 'ms'
}

// Log - output value for debugging/recording
export interface LogStep extends SequenceStepBase {
  type: 'log'
  message: string             // Message template (can include {variables})
  level: 'debug' | 'info' | 'warn' | 'error'
  values?: Record<string, string>  // Variable name -> formula mapping
}

export type SequenceStep =
  | RampStep
  | SoakStep
  | WaitStep
  | SetOutputStep
  | SetVariableStep
  | LoopStep
  | EndLoopStep
  | WhileLoopStep
  | EndWhileStep
  | ForEachLoopStep
  | EndForEachStep
  | RepeatUntilStep
  | EndRepeatStep
  | BreakStep
  | ContinueStep
  | MessageStep
  | IfStep
  | ElseIfStep
  | ElseStep
  | EndIfStep
  | SwitchStep
  | CaseStep
  | DefaultCaseStep
  | EndSwitchStep
  | RecordingStep
  | SafetyCheckStep
  | CallSequenceStep
  | RunDrawPatternStep
  | SingleDrawStep
  | CalculateStep
  | DelayStep
  | LogStep

export type SequenceState =
  | 'idle'
  | 'running'
  | 'paused'
  | 'completed'
  | 'aborted'
  | 'error'

export interface SequenceRunHistory {
  id: string
  startTime: number
  endTime: number
  state: SequenceState           // Final state: completed, aborted, error
  duration: number               // ms
  stepsCompleted: number
  totalSteps: number
  error?: string
  triggeredBy?: 'manual' | 'schedule' | 'trigger' | 'sequence'  // How it was started
}

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
  currentIfResults: Record<string, boolean>      // ifId -> condition result (for else/endIf navigation)
  variables: Record<string, number>              // Script variables set by setVariable steps
  startTime?: number
  pausedTime?: number
  error?: string
  // Nested sequence call stack
  callStack?: string[]                           // Stack of sequence IDs for nested calls
  parentSequenceId?: string                      // If this is a sub-sequence call
  // Wait step retry tracking
  currentRetryCount?: number                     // Current retry attempt for wait steps
  // Execution history
  runHistory?: SequenceRunHistory[]              // Last N runs (kept for logs)
  lastRunTime?: number                           // Timestamp of last run
  runCount?: number                              // Total times run
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
  | 'runSequence'     // Alias for startSequence
  | 'stopSequence'
  | 'setOutput'
  | 'setSetpoint'     // Set a setpoint value
  | 'startRecording'
  | 'stopRecording'
  | 'notification'
  | 'runFormula'
  | 'sound'           // Play a sound
  | 'log'             // Log to file

export interface TriggerAction {
  type: TriggerActionType
  sequenceId?: string
  channel?: string
  value?: number | boolean
  message?: string
  formula?: string
  sound?: string      // Sound file to play
  logFile?: string    // Log file path
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
// SEQUENCE TEMPLATES
// =============================================================================

export type SequenceTemplateCategory = 'calibration' | 'thermal' | 'safety' | 'testing' | 'maintenance'

export interface SequenceTemplate {
  id: string
  name: string
  description: string
  category: SequenceTemplateCategory
  icon: string
  steps: Omit<SequenceStep, 'id'>[]    // Steps without IDs (generated on create)
}

export const SEQUENCE_TEMPLATES: SequenceTemplate[] = [
  {
    id: 'warmup-sequence',
    name: 'Warmup Procedure',
    description: 'Gradual warmup with safety checks and stabilization',
    category: 'thermal',
    icon: '🔥',
    steps: [
      { type: 'safetyCheck', enabled: true, label: 'Pre-warmup safety', condition: '', failAction: 'abort', failMessage: 'Safety conditions not met' },
      { type: 'message', enabled: true, label: 'Warmup start', message: 'Starting warmup procedure', severity: 'info', pauseExecution: false },
      { type: 'recording', enabled: true, label: 'Start recording', action: 'start', filename: 'warmup' },
      { type: 'ramp', enabled: true, label: 'Ramp to target', targetChannel: '', monitorChannel: '', targetValue: 100, rampRate: 5, rampRateUnit: '°C/min', tolerance: 2 },
      { type: 'soak', enabled: true, label: 'Stabilize', duration: 300 },
      { type: 'message', enabled: true, label: 'Warmup complete', message: 'Warmup procedure completed', severity: 'success', pauseExecution: false },
      { type: 'recording', enabled: true, label: 'Stop recording', action: 'stop' }
    ] as any[]
  },
  {
    id: 'valve-calibration',
    name: 'Valve Calibration Sequence',
    description: 'Sequential valve calibration with flow measurement',
    category: 'calibration',
    icon: '🔧',
    steps: [
      { type: 'safetyCheck', enabled: true, label: 'Check system ready', condition: '', failAction: 'abort', failMessage: 'System not ready for calibration' },
      { type: 'setVariable', enabled: true, label: 'Init valve counter', variableName: 'valveIndex', value: 1, isFormula: false },
      { type: 'recording', enabled: true, label: 'Start cal recording', action: 'start', filename: 'valve_cal' },
      { type: 'loop', enabled: true, label: 'For each valve', iterations: 4, loopId: 'valve-loop' },
      { type: 'message', enabled: true, label: 'Calibrating valve', message: 'Calibrating valve ${valveIndex}', severity: 'info', pauseExecution: false },
      { type: 'wait', enabled: true, label: 'Wait for flow', condition: '', timeout: 30, timeoutAction: 'continue' },
      { type: 'soak', enabled: true, label: 'Measure stable flow', duration: 10 },
      { type: 'setVariable', enabled: true, label: 'Next valve', variableName: 'valveIndex', value: 'valveIndex + 1', isFormula: true },
      { type: 'endLoop', enabled: true, label: 'End valve loop', loopId: 'valve-loop' },
      { type: 'recording', enabled: true, label: 'Stop recording', action: 'stop' },
      { type: 'message', enabled: true, label: 'Calibration complete', message: 'Valve calibration completed', severity: 'success', pauseExecution: false }
    ] as any[]
  },
  {
    id: 'emergency-shutdown',
    name: 'Emergency Shutdown',
    description: 'Safe shutdown procedure for emergency situations',
    category: 'safety',
    icon: '🛑',
    steps: [
      { type: 'message', enabled: true, label: 'Emergency alert', message: 'EMERGENCY SHUTDOWN INITIATED', severity: 'error', pauseExecution: false },
      { type: 'setOutput', enabled: true, label: 'Disable heaters', channel: '', value: false },
      { type: 'setOutput', enabled: true, label: 'Close all valves', channel: '', value: false },
      { type: 'recording', enabled: true, label: 'Log emergency', action: 'start', filename: 'emergency' },
      { type: 'soak', enabled: true, label: 'Wait for safe state', duration: 30 },
      { type: 'message', enabled: true, label: 'Shutdown complete', message: 'System in safe state - manual inspection required', severity: 'warning', pauseExecution: true }
    ] as any[]
  },
  {
    id: 'cycle-test',
    name: 'Thermal Cycle Test',
    description: 'Repeated heating/cooling cycles for stress testing',
    category: 'testing',
    icon: '🔄',
    steps: [
      { type: 'safetyCheck', enabled: true, label: 'Pre-test safety', condition: '', failAction: 'abort', failMessage: 'Safety conditions not met' },
      { type: 'setVariable', enabled: true, label: 'Set cycle count', variableName: 'cycleCount', value: 1, isFormula: false },
      { type: 'recording', enabled: true, label: 'Start test recording', action: 'start', filename: 'cycle_test' },
      { type: 'loop', enabled: true, label: 'Cycle loop', iterations: 10, loopId: 'cycle-loop' },
      { type: 'message', enabled: true, label: 'Cycle start', message: 'Starting cycle ${cycleCount}', severity: 'info', pauseExecution: false },
      { type: 'ramp', enabled: true, label: 'Heat up', targetChannel: '', monitorChannel: '', targetValue: 150, rampRate: 10, rampRateUnit: '°C/min', tolerance: 2 },
      { type: 'soak', enabled: true, label: 'Hot soak', duration: 60 },
      { type: 'ramp', enabled: true, label: 'Cool down', targetChannel: '', monitorChannel: '', targetValue: 25, rampRate: 10, rampRateUnit: '°C/min', tolerance: 2 },
      { type: 'soak', enabled: true, label: 'Cold soak', duration: 60 },
      { type: 'setVariable', enabled: true, label: 'Increment cycle', variableName: 'cycleCount', value: 'cycleCount + 1', isFormula: true },
      { type: 'endLoop', enabled: true, label: 'End cycle loop', loopId: 'cycle-loop' },
      { type: 'recording', enabled: true, label: 'Stop recording', action: 'stop' },
      { type: 'message', enabled: true, label: 'Test complete', message: 'Cycle test completed successfully', severity: 'success', pauseExecution: false }
    ] as any[]
  },
  {
    id: 'system-check',
    name: 'Daily System Check',
    description: 'Routine system verification and diagnostics',
    category: 'maintenance',
    icon: '📋',
    steps: [
      { type: 'message', enabled: true, label: 'Starting check', message: 'Starting daily system check', severity: 'info', pauseExecution: false },
      { type: 'safetyCheck', enabled: true, label: 'Verify E-Stop', condition: '', failAction: 'pause', failMessage: 'E-Stop circuit fault detected' },
      { type: 'safetyCheck', enabled: true, label: 'Verify interlocks', condition: '', failAction: 'pause', failMessage: 'Interlock fault detected' },
      { type: 'recording', enabled: true, label: 'Log diagnostics', action: 'start', filename: 'daily_check' },
      { type: 'soak', enabled: true, label: 'Collect baseline', duration: 30 },
      { type: 'recording', enabled: true, label: 'Stop recording', action: 'stop' },
      { type: 'message', enabled: true, label: 'Check complete', message: 'Daily system check completed - review logs', severity: 'success', pauseExecution: false }
    ] as any[]
  }
]

// =============================================================================
// DRAW PATTERNS - Valve dosing sequences
// =============================================================================

export type DrawState = 'pending' | 'active' | 'completed' | 'skipped' | 'error'
export type DrawPatternState = 'idle' | 'running' | 'paused' | 'completed' | 'error'

/**
 * A single draw in a draw pattern (one valve actuation to dispense a target volume)
 */
export interface Draw {
  id: string
  drawNumber: number           // Sequence number (1, 2, 3...) for reports
  valve: string                // Valve/output channel name (e.g., "SV1")
  volumeTarget: number         // Target volume to dispense
  volumeUnit: string           // Unit (gal, L, etc.)
  maxDuration: number          // Safety timeout in seconds
  enabled: boolean             // Include in pattern
  // Runtime state
  state: DrawState
  volumeDispensed: number
  elapsedTime: number
  startVolume?: number         // Flow totalizer value when draw started
  startTime?: number           // Timestamp when draw started
  endTime?: number             // Timestamp when draw completed
  completedBy?: 'volume' | 'timeout' | 'manual' | 'error'
}

/**
 * A draw pattern is a sequence of valve draws that execute in order.
 * Used for water heater testing (UEF-FHR draw patterns), dosing cycles, etc.
 */
export interface DrawPattern {
  id: string
  name: string
  description: string
  enabled: boolean
  // Flow measurement
  flowChannel: string          // Flow totalizer channel to monitor
  flowUnit: string             // Unit for volume (gal, L, etc.)
  // Draws
  draws: Draw[]
  // Timing
  delayBetweenDraws: number    // Seconds between closing one valve and opening next
  loopContinuously: boolean    // Restart from draw #1 after completing all
  // Runtime state
  state: DrawPatternState
  currentDrawIndex: number     // Which draw is active (-1 if none)
  cycleCount: number           // Number of complete cycles
  startTime?: number           // Timestamp when pattern started
  pausedTime?: number          // Timestamp when paused
  totalVolumeDispensed: number // Total volume across all draws
  error?: string
  // History
  lastRun?: string             // ISO timestamp
  runCount?: number            // Total times run
}

/**
 * Draw pattern run history entry
 */
export interface DrawPatternRunHistory {
  id: string
  patternId: string
  patternName: string
  startTime: number
  endTime: number
  state: DrawPatternState
  cyclesCompleted: number
  drawResults: {
    drawNumber: number
    valve: string
    volumeDispensed: number
    duration: number
    completedBy: 'volume' | 'timeout' | 'manual' | 'error'
  }[]
  totalVolumeDispensed: number
  error?: string
}

// Storage key for draw patterns
export const DRAW_PATTERNS_STORAGE_KEY = 'nisystem-draw-patterns'

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
  | 'valve_draw'           // Execute a valve draw (dispense volume)
  | 'start_draw_pattern'   // Start a draw pattern sequence

export interface ScheduleAction {
  type: ScheduleActionType
  sequenceId?: string       // For start_sequence
  channel?: string          // For set_output
  value?: number | boolean  // For set_output
  formula?: string          // For run_formula
  recordingFilename?: string // For start_recording
  // For valve_draw
  drawPatternId?: string    // Reference to a draw pattern
  drawNumber?: number       // Specific draw to execute (1-based)
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

// =============================================================================
// STATE MACHINES
// =============================================================================

export type StateTransitionConditionType =
  | 'channel_value'     // Channel reaches a value
  | 'timeout'           // After time in state
  | 'event'             // External event (button, trigger, etc.)
  | 'formula'           // Formula evaluates to true
  | 'sequence_complete' // Sequence finished

export interface StateTransitionCondition {
  type: StateTransitionConditionType
  // For channel_value
  channel?: string
  operator?: '<' | '>' | '<=' | '>=' | '==' | '!='
  value?: number
  // For timeout
  timeoutMs?: number
  // For event
  eventName?: string
  // For formula
  formula?: string
  // For sequence_complete
  sequenceId?: string
}

export interface StateTransition {
  id: string
  fromState: string        // State ID
  toState: string          // State ID
  condition: StateTransitionCondition
  priority: number         // Lower = higher priority (for multiple valid transitions)
}

export interface StateEntryAction {
  type: 'setOutput' | 'startSequence' | 'stopSequence' | 'notification' | 'setSetpoint' | 'log'
  channel?: string
  value?: number | boolean
  sequenceId?: string
  message?: string
}

export interface StateMachineState {
  id: string
  name: string
  description?: string
  color?: string           // For visual display
  // Actions to perform when entering this state
  entryActions: StateEntryAction[]
  // Actions to perform when exiting this state
  exitActions: StateEntryAction[]
  // Is this an error/fault state?
  isFaultState?: boolean
  // Is this a terminal state (no outgoing transitions)?
  isTerminal?: boolean
}

export interface StateMachine {
  id: string
  name: string
  description: string
  enabled: boolean
  // States
  states: StateMachineState[]
  initialStateId: string
  // Transitions
  transitions: StateTransition[]
  // Runtime state
  currentStateId: string
  previousStateId?: string
  stateEnteredAt?: number       // Timestamp when entered current state
  isRunning: boolean
  // History
  stateHistory: { stateId: string; enteredAt: number; exitedAt?: number }[]
  // Metadata
  createdAt: string
  modifiedAt: string
}

// =============================================================================
// REPORTS
// =============================================================================

export type ReportFormat = 'pdf' | 'csv' | 'excel' | 'html'
export type ReportPeriod = 'last_hour' | 'last_24h' | 'last_week' | 'custom' | 'recording'

export interface ReportSection {
  id: string
  type: 'summary' | 'chart' | 'table' | 'statistics' | 'alarms' | 'events'
  title: string
  enabled: boolean
  // For chart section
  channels?: string[]
  // For table section
  columns?: { channel: string; label: string }[]
  // For statistics section
  statisticsChannels?: string[]
  includeMin?: boolean
  includeMax?: boolean
  includeAvg?: boolean
  includeStdDev?: boolean
}

export interface ReportTemplate {
  id: string
  name: string
  description: string
  format: ReportFormat
  sections: ReportSection[]
  // Header/footer
  includeHeader: boolean
  headerText?: string
  includeFooter: boolean
  footerText?: string
  includeLogo?: boolean
  // Data range
  period: ReportPeriod
  customStartTime?: string      // ISO timestamp for custom period
  customEndTime?: string
}

export interface ScheduledReport {
  id: string
  name: string
  templateId: string
  enabled: boolean
  // Schedule
  schedule: 'daily' | 'weekly' | 'monthly' | 'on_recording_stop'
  time?: string                 // HH:MM for scheduled
  dayOfWeek?: number           // 0-6 for weekly
  dayOfMonth?: number          // 1-31 for monthly
  // Output
  outputPath?: string          // Directory to save reports
  emailRecipients?: string[]   // Email addresses
  // Runtime
  lastGenerated?: string       // ISO timestamp
  lastError?: string
}

// =============================================================================
// WATCHDOG
// =============================================================================

export interface WatchdogCondition {
  type: 'stale_data' | 'out_of_range' | 'rate_exceeded' | 'stuck_value'
  // For stale_data
  maxStaleMs?: number          // Max time without update
  // For out_of_range
  minValue?: number
  maxValue?: number
  // For rate_exceeded
  maxRatePerMin?: number
  // For stuck_value
  stuckDurationMs?: number     // How long value hasn't changed
  stuckTolerance?: number      // Tolerance for "stuck" detection
}

export interface WatchdogAction {
  type: 'notification' | 'alarm' | 'setOutput' | 'stopSequence' | 'stopRecording' | 'runSequence'
  message?: string
  channel?: string
  value?: number | boolean
  sequenceId?: string
  alarmSeverity?: 'info' | 'warning' | 'critical'
}

export interface Watchdog {
  id: string
  name: string
  description: string
  enabled: boolean
  // What to monitor
  channels: string[]
  condition: WatchdogCondition
  // Actions when triggered
  actions: WatchdogAction[]
  // Recovery
  autoRecover: boolean         // Auto-clear when condition clears
  recoveryActions?: WatchdogAction[]  // Actions when recovered
  // State
  isTriggered: boolean
  triggeredAt?: number
  triggeredChannels?: string[]
  // Cooldown
  cooldownMs: number           // Min time between triggers
  lastTriggered?: number
}

// =============================================================================
// ENHANCED ALARM FEATURES
// =============================================================================

export interface AlarmEscalation {
  delayMs: number              // Time after initial alarm
  actions: AlarmAction[]       // Additional actions to take
  notifyLevel: 'operator' | 'supervisor' | 'manager' | 'emergency'
}

export interface AlarmEnhanced extends Alarm {
  // Shelving
  shelvingEnabled: boolean
  shelvedUntil?: number        // Timestamp when shelving expires
  shelvedBy?: string
  shelvedReason?: string
  maxShelveDurationMs: number  // Max time alarm can be shelved
  // Acknowledgement
  requiresAcknowledgement: boolean
  acknowledgeTimeoutMs?: number   // Time to acknowledge before escalation
  // Escalation
  escalations?: AlarmEscalation[]
  currentEscalationLevel?: number
  // Dead-banding
  returnToNormalDelay: number  // Time condition must be clear before resetting
  // Rate of change alarms
  rateAlarmEnabled?: boolean
  rateThreshold?: number       // Rate per minute
  rateDirection?: 'rising' | 'falling' | 'both'
}

// =============================================================================
// ENHANCED TRIGGER FEATURES
// =============================================================================

export interface TriggerEnhanced extends AutomationTrigger {
  // Debounce
  debounceMs: number           // Time condition must be true before triggering
  // Hysteresis (for value triggers)
  hysteresis?: number          // Value must cross threshold ± hysteresis
  hysteresisState?: 'above' | 'below' | null
  // Trigger chains
  chainedTriggerId?: string    // ID of next trigger to fire after this one
  chainDelayMs?: number        // Delay before firing chained trigger
  // Conditions
  additionalConditions?: {     // All must be true for trigger to fire
    channel: string
    operator: '<' | '>' | '<=' | '>=' | '==' | '!='
    value: number
  }[]
}

// =============================================================================
// ENHANCED SCHEDULE FEATURES
// =============================================================================

export type RecurringPattern =
  | { type: 'daily'; time: string }
  | { type: 'weekly'; time: string; daysOfWeek: number[] }
  | { type: 'monthly'; time: string; daysOfMonth: number[] }
  | { type: 'interval'; intervalMs: number; startTime?: string; endTime?: string }
  | { type: 'cron'; expression: string }

export interface ScheduleEnhanced extends Schedule {
  // Recurring patterns
  pattern?: RecurringPattern
  // Exceptions
  exceptDates?: string[]       // ISO dates to skip
  exceptDateRanges?: { start: string; end: string }[]
  // Holiday calendar
  respectHolidays?: boolean
  holidayCalendar?: string     // Calendar ID
  // Active time window
  activeWindow?: {
    startTime: string          // HH:MM - only run within this window
    endTime: string
    daysOfWeek?: number[]      // Only on these days
  }
  // Timezone
  timezone?: string            // IANA timezone
  // Missed run handling
  onMissedRun: 'skip' | 'run_immediately' | 'run_at_next_slot'
  maxCatchupRuns?: number      // Max missed runs to catch up
}

// =============================================================================
// ENHANCED SEQUENCE FEATURES
// =============================================================================

// Parallel branch step - run multiple paths simultaneously
export interface ParallelStep extends SequenceStepBase {
  type: 'parallel'
  parallelId: string
  branches: {
    id: string
    name: string
    steps: SequenceStep[]
  }[]
  waitMode: 'all' | 'any' | 'first'  // Wait for all, any, or first branch to complete
}

export interface EndParallelStep extends SequenceStepBase {
  type: 'endParallel'
  parallelId: string
}

// Goto/jump step
export interface GotoStep extends SequenceStepBase {
  type: 'goto'
  targetStepId: string         // Jump to this step
  condition?: string           // Optional condition formula
}

// Retry wrapper
export interface RetryStep extends SequenceStepBase {
  type: 'retry'
  retryId: string
  maxRetries: number
  retryDelayMs: number
  onFailure: 'abort' | 'continue' | 'goto'
  failureGotoStepId?: string
}

export interface EndRetryStep extends SequenceStepBase {
  type: 'endRetry'
  retryId: string
}

// Sub-sequence with parameters
export interface CallSequenceWithParamsStep extends SequenceStepBase {
  type: 'callSequenceWithParams'
  sequenceId: string
  parameters: Record<string, number | string>  // Pass values to sub-sequence
  waitForCompletion: boolean
}

// Update the SequenceStep union to include new types
export type SequenceStepExtended =
  | SequenceStep
  | ParallelStep
  | EndParallelStep
  | GotoStep
  | RetryStep
  | EndRetryStep
  | CallSequenceWithParamsStep

// =============================================================================
// UPDATED SCRIPTS STATE
// =============================================================================

export interface ScriptsStateExtended extends ScriptsState {
  stateMachines: StateMachine[]
  reportTemplates: ReportTemplate[]
  scheduledReports: ScheduledReport[]
  watchdogs: Watchdog[]
}

// =============================================================================
// UPDATED SUB-TABS
// =============================================================================

export type ScriptsSubTabExtended =
  | ScriptsSubTab
  | 'session'
  | 'variables'
  | 'python'
  | 'stateMachines'
  | 'reports'
  | 'watchdogs'
  | 'drawPatterns'

// Storage keys for new features
export const STORAGE_KEYS_EXTENDED = {
  ...STORAGE_KEYS,
  STATE_MACHINES: 'dcflux-state-machines',
  REPORT_TEMPLATES: 'dcflux-report-templates',
  SCHEDULED_REPORTS: 'dcflux-scheduled-reports',
  WATCHDOGS: 'dcflux-watchdogs',
  VALVE_DOSING: 'nisystem-valve-dosing'
} as const

// =============================================================================
// VALVE DOSING SYSTEM
// =============================================================================

export type ValveDosingState = 'idle' | 'running' | 'paused' | 'completed' | 'error'
export type ValveState = 'pending' | 'active' | 'completed' | 'skipped' | 'error'
export type ScheduleEntryState = 'pending' | 'active' | 'completed' | 'skipped' | 'error'

// Schedule entry for CSV-style schedule grid
export interface ValveScheduleEntry {
  id: string
  drawNumber: number             // Draw sequence number (1, 2, 3...) - used in test reports
  timeOfDay: string              // HH:MM format (e.g., "06:00")
  valve: string                  // Valve/output channel name (e.g., "Valve_1")
  volumeTarget: number           // GAL target (or other unit)
  volumeUnit: string             // Unit (gal, L, mL, etc.)
  maxDuration: number            // Safety timeout in seconds
  enabled: boolean               // Include in schedule
  // Runtime state
  state: ScheduleEntryState
  volumeDispensed: number
  elapsedTime: number
  startVolume?: number
}

export interface ValveConfig {
  id: string
  name: string                    // Display name
  outputChannel: string           // Digital output channel name (e.g., "Valve_1")
  flowChannel: string             // Flow totalizer channel (counter input)
  volumeTarget: number            // Target volume to dispense
  volumeUnit: string              // Unit for volume (gal, L, etc.)
  maxDuration: number             // Max duration in seconds (safety timeout)
  enabled: boolean                // Is this valve part of the cycle?
  // Runtime state
  state: ValveState
  volumeDispensed: number         // Current volume dispensed
  elapsedTime: number             // Time valve has been open (seconds)
  startVolume?: number            // Flow totalizer value when valve opened
}

export interface ValveDosingConfig {
  id: string
  name: string
  description: string
  enabled: boolean
  // Valves in rotation order
  valves: ValveConfig[]
  // Cycle settings
  loopContinuously: boolean       // Loop back to first valve after last
  delayBetweenValves: number      // Delay in seconds between closing one and opening next
  // Flow settings
  flowUnit: string                // Global unit for flow (gal, L, etc.)
  // Safety
  requireInterlock: boolean       // Require interlock satisfied before running
  interlockId?: string            // ID of required interlock
  // Runtime state
  state: ValveDosingState
  currentValveIndex: number       // Which valve is currently active (-1 if none)
  cycleCount: number              // Number of complete cycles
  startTime?: number              // Timestamp when cycle started
  pausedTime?: number             // Timestamp when paused
  totalVolumeDispensed: number    // Total volume across all valves in current cycle
  error?: string
  // Schedule
  scheduleEnabled: boolean
  scheduleTime?: string           // HH:MM for daily schedule (legacy)
  scheduleDays?: number[]         // Days of week (0-6, 0=Sunday)
  lastRun?: string                // ISO timestamp
  nextRun?: string                // ISO timestamp
  // Schedule Grid (CSV-style entries)
  scheduleEntries: ValveScheduleEntry[]
  currentScheduleIndex: number    // Which schedule entry is active (-1 if none)
  flowChannel: string             // Flow totalizer channel for all entries
}

// Default valve dosing configuration
export const DEFAULT_VALVE_DOSING_CONFIG: Omit<ValveDosingConfig, 'id'> = {
  name: 'Valve Rotation',
  description: 'Sequential valve dosing cycle',
  enabled: true,
  valves: [
    {
      id: 'v1',
      name: 'Valve 1',
      outputChannel: 'Valve_1',
      flowChannel: 'Flow_1',
      volumeTarget: 100,
      volumeUnit: 'gal',
      maxDuration: 1800, // 30 minutes
      enabled: true,
      state: 'pending',
      volumeDispensed: 0,
      elapsedTime: 0
    },
    {
      id: 'v2',
      name: 'Valve 2',
      outputChannel: 'Valve_2',
      flowChannel: 'Flow_2',
      volumeTarget: 100,
      volumeUnit: 'gal',
      maxDuration: 1800,
      enabled: true,
      state: 'pending',
      volumeDispensed: 0,
      elapsedTime: 0
    },
    {
      id: 'v3',
      name: 'Valve 3',
      outputChannel: 'Valve_3',
      flowChannel: 'Flow_3',
      volumeTarget: 100,
      volumeUnit: 'gal',
      maxDuration: 1800,
      enabled: true,
      state: 'pending',
      volumeDispensed: 0,
      elapsedTime: 0
    }
  ],
  loopContinuously: true,
  delayBetweenValves: 5,
  flowUnit: 'gal',
  requireInterlock: false,
  state: 'idle',
  currentValveIndex: -1,
  cycleCount: 0,
  totalVolumeDispensed: 0,
  scheduleEnabled: false,
  scheduleEntries: [],
  currentScheduleIndex: -1,
  flowChannel: 'Flow_1'
}

// Valve dosing run history
export interface ValveDosingRunHistory {
  id: string
  startTime: number
  endTime: number
  state: ValveDosingState
  cyclesCompleted: number
  valveResults: {
    valveId: string
    name: string
    volumeDispensed: number
    duration: number
    completedBy: 'volume' | 'timeout' | 'manual' | 'error'
  }[]
  totalVolumeDispensed: number
  error?: string
}
