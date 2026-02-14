import { ref, computed, shallowRef } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type {
  CalculatedParam,
  Sequence,
  RampStep,
  SoakStep,
  WaitStep,
  SetOutputStep,
  SetVariableStep,
  LoopStep,
  EndLoopStep,
  IfStep,
  ElseStep,
  EndIfStep,
  MessageStep,
  RecordingStep,
  SafetyCheckStep,
  CallSequenceStep,
  Alarm,
  Transformation,
  RollingTransformation,
  RateOfChangeTransformation,
  UnitConversionTransformation,
  PolynomialTransformation,
  DeadbandTransformation,
  ClampTransformation,
  AutomationTrigger,
  ValueReachedTrigger,
  ScheduledTrigger,
  StateChangeTrigger,
  SequenceEventTrigger,
  UnitConversionType,
  FunctionBlock,
  Schedule,
  ScheduleAction,
  // Draw patterns
  DrawPattern,
  Draw,
  DrawPatternRunHistory,
  // New types
  StateMachine,
  ReportTemplate,
  ScheduledReport,
  Watchdog,
  ScriptsSubTabExtended
} from '../types/scripts'
import { UNIT_CONVERSIONS, FUNCTION_BLOCK_TEMPLATES, FUNCTION_BLOCKS_STORAGE_KEY, STORAGE_KEYS, SEQUENCE_TEMPLATES, DRAW_PATTERNS_STORAGE_KEY } from '../types/scripts'

// ==========================================================================
// SINGLETON STATE - exists outside the composable function
// ==========================================================================

const activeSubTab = ref<ScriptsSubTabExtended>('session')
const calculatedParams = ref<CalculatedParam[]>([])
const sequences = ref<Sequence[]>([])
const runningSequenceId = ref<string | null>(null)
const sequenceTimeoutId = shallowRef<number | null>(null)
const alarms = ref<Alarm[]>([])
const activeAlarmIds = ref<string[]>([])
const alarmHistory = ref<Array<{ alarmId: string; triggeredAt: number; message: string }>>([])
const transformations = ref<Transformation[]>([])
const transformationBuffers = ref<Record<string, number[]>>({})
const lastValues = ref<Record<string, { value: number; timestamp: number }>>({})
const triggers = ref<AutomationTrigger[]>([])
const functionBlocks = ref<FunctionBlock[]>([])
const schedules = ref<Schedule[]>([])

// Draw patterns state
const drawPatterns = ref<DrawPattern[]>([])
const drawPatternHistory = ref<DrawPatternRunHistory[]>([])
const activeDrawPatternId = ref<string | null>(null)
let drawPatternTickIntervalId: number | null = null

// New feature state
const stateMachines = ref<StateMachine[]>([])
const reportTemplates = ref<ReportTemplate[]>([])
const scheduledReports = ref<ScheduledReport[]>([])
const watchdogs = ref<Watchdog[]>([])

// Watchdog state tracking
const watchdogChannelTimestamps = ref<Record<string, number>>({})  // Last update timestamp per channel
const watchdogPreviousValues = ref<Record<string, number>>({})     // Previous value per channel for stuck detection
const watchdogValueChangeTimestamps = ref<Record<string, number>>({})  // When value last changed (for stuck)
const watchdogRateHistory = ref<Record<string, { value: number; timestamp: number }[]>>({})  // For rate calculation

// Notifications queue for UI
const notifications = ref<Array<{
  id: string
  type: 'info' | 'warning' | 'error' | 'success'
  title: string
  message: string
  timestamp: number
  acknowledged: boolean
}>>([])

// MQTT integration - will be set by setMqttHandler
let mqttSetOutput: ((channel: string, value: number | boolean) => void) | null = null
let mqttStartRecording: ((filename?: string) => void) | null = null
let mqttStopRecording: (() => void) | null = null
let mqttSendScriptValues: ((values: Record<string, number>) => void) | null = null

// State tracking for triggers
let previousAcquiring = false
let previousRecording = false
let previousSchedulerEnabled = false

let evaluationIntervalId: number | null = null
let isInitialized = false

// Sequence event listeners for subroutine calls
type SequenceEventType = 'started' | 'completed' | 'aborted' | 'error' | 'stepCompleted'
type SequenceEventListener = (event: SequenceEventType, seq: Sequence) => void
const sequenceEventListeners: SequenceEventListener[] = []

// ==========================================================================
// COMPOSABLE FUNCTION
// ==========================================================================

export function useScripts() {
  const store = useDashboardStore()

  // ========================================================================
  // MQTT INTEGRATION
  // ========================================================================

  function setMqttHandlers(handlers: {
    setOutput: (channel: string, value: number | boolean) => void
    startRecording: (filename?: string) => void
    stopRecording: () => void
    sendScriptValues: (values: Record<string, number>) => void
  }) {
    mqttSetOutput = handlers.setOutput
    mqttStartRecording = handlers.startRecording
    mqttStopRecording = handlers.stopRecording
    mqttSendScriptValues = handlers.sendScriptValues
  }

  function sendOutput(channel: string, value: number | boolean) {
    if (mqttSetOutput) {
      mqttSetOutput(channel, value)
      console.debug(`MQTT: Set ${channel} = ${value}`)
    } else {
      console.warn(`MQTT not connected: Would set ${channel} = ${value}`)
    }
  }

  // ========================================================================
  // NOTIFICATIONS
  // ========================================================================

  // Track auto-dismiss timers so they can be cancelled on manual dismiss
  const notificationTimers = new Map<string, ReturnType<typeof setTimeout>>()

  function addNotification(type: 'info' | 'warning' | 'error' | 'success', title: string, message: string) {
    const notification = {
      id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type,
      title,
      message,
      timestamp: Date.now(),
      acknowledged: false
    }
    notifications.value.unshift(notification)

    // Keep only last 50 notifications
    if (notifications.value.length > 50) {
      notifications.value = notifications.value.slice(0, 50)
    }

    // Auto-dismiss info/success after 5 seconds
    if (type === 'info' || type === 'success') {
      const timerId = setTimeout(() => {
        notificationTimers.delete(notification.id)
        dismissNotification(notification.id)
      }, 5000)
      notificationTimers.set(notification.id, timerId)
    }

    return notification.id
  }

  function dismissNotification(id: string) {
    // Cancel any pending auto-dismiss timer
    const timer = notificationTimers.get(id)
    if (timer) {
      clearTimeout(timer)
      notificationTimers.delete(id)
    }
    const index = notifications.value.findIndex(n => n.id === id)
    if (index >= 0) {
      notifications.value.splice(index, 1)
    }
  }

  function acknowledgeNotification(id: string) {
    const notification = notifications.value.find(n => n.id === id)
    if (notification) {
      notification.acknowledged = true
    }
  }

  function clearAllNotifications() {
    notifications.value = []
  }

  // ========================================================================
  // PERSISTENCE
  // ========================================================================

  function loadAll() {
    if (isInitialized) return
    isInitialized = true

    loadCalculatedParams()
    loadSequences()
    loadSchedules()
    loadAlarms()
    loadTransformations()
    loadTriggers()
    loadFunctionBlocks()
    loadDrawPatterns()
    loadWatchdogs()
  }

  // Force reload all scripts from localStorage (used by node context switching)
  function reloadFromStorage() {
    loadCalculatedParams()
    loadSequences()
    loadSchedules()
    loadAlarms()
    loadTransformations()
    loadTriggers()
    loadFunctionBlocks()
    loadDrawPatterns()
    loadWatchdogs()
  }

  function loadCalculatedParams() {
    try {
      const stored = localStorage.getItem('nisystem-scripts')
      if (stored) {
        calculatedParams.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load calculated params:', e)
    }
  }

  function saveCalculatedParams() {
    try {
      localStorage.setItem('nisystem-scripts', JSON.stringify(calculatedParams.value))
    } catch (e) {
      console.error('Failed to save calculated params:', e)
    }
  }

  function loadSequences() {
    try {
      const stored = localStorage.getItem('nisystem-sequences')
      if (stored) {
        const parsed = JSON.parse(stored)
        sequences.value = parsed.map((seq: Sequence) => ({
          ...seq,
          state: 'idle',
          currentStepIndex: 0,
          currentLoopIterations: {},
          currentIfResults: {},
          variables: {},
          callStack: []
        }))
      }
    } catch (e) {
      console.error('Failed to load sequences:', e)
    }
  }

  function saveSequences() {
    try {
      localStorage.setItem('nisystem-sequences', JSON.stringify(sequences.value))
    } catch (e) {
      console.error('Failed to save sequences:', e)
    }
  }

  function loadAlarms() {
    try {
      const stored = localStorage.getItem('nisystem-alarms')
      if (stored) {
        const parsed = JSON.parse(stored)
        alarms.value = parsed.map((alarm: Alarm) => ({
          ...alarm,
          state: 'normal'
        }))
      }
    } catch (e) {
      console.error('Failed to load alarms:', e)
    }
  }

  function saveAlarms() {
    try {
      localStorage.setItem('nisystem-alarms', JSON.stringify(alarms.value))
    } catch (e) {
      console.error('Failed to save alarms:', e)
    }
  }

  function loadTransformations() {
    try {
      const stored = localStorage.getItem('nisystem-transformations')
      if (stored) {
        transformations.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load transformations:', e)
    }
  }

  function saveTransformations() {
    try {
      localStorage.setItem('nisystem-transformations', JSON.stringify(transformations.value))
    } catch (e) {
      console.error('Failed to save transformations:', e)
    }
  }

  function loadTriggers() {
    try {
      const stored = localStorage.getItem('nisystem-triggers')
      if (stored) {
        triggers.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load triggers:', e)
    }
  }

  function saveTriggers() {
    try {
      localStorage.setItem('nisystem-triggers', JSON.stringify(triggers.value))
    } catch (e) {
      console.error('Failed to save triggers:', e)
    }
  }

  // ========================================================================
  // FORMULA EVALUATION
  // ========================================================================

  // Block dangerous patterns in formulas before they reach new Function()
  const BLOCKED_FORMULA_PATTERNS = [
    /\bimport\b/i, /\brequire\b/i, /\beval\b/i, /\bFunction\b/,
    /\bfetch\b/i, /\bXMLHttpRequest\b/i, /\bdocument\b/i, /\bwindow\b/i,
    /\bprocess\b/i, /\bglobal\b/i, /\bconstructor\b/i,
    /\b__proto__\b/, /\bprototype\b/,
  ]

  function validateFormulaSafety(formula: string): string | null {
    for (const pattern of BLOCKED_FORMULA_PATTERNS) {
      if (pattern.test(formula)) {
        return `Formula contains blocked pattern: ${pattern.source}`
      }
    }
    return null
  }

  function evaluateFormula(formula: string): { value: number | null; error: string | null } {
    if (!formula || formula.trim() === '') {
      return { value: null, error: 'Empty formula' }
    }

    const safetyError = validateFormulaSafety(formula)
    if (safetyError) {
      return { value: null, error: safetyError }
    }

    try {
      // Build namespace with all channel values
      // Supports both direct syntax (TC101) and legacy ch.TC101 syntax
      const namespace: Record<string, number> = {}
      const ch: Record<string, number> = {}  // Legacy ch.NAME support

      if (store.values) {
        Object.entries(store.values).forEach(([name, data]) => {
          if (data && typeof data.value === 'number') {
            const safeName = name.replace(/[^a-zA-Z0-9_]/g, '_')
            namespace[safeName] = data.value
            ch[safeName] = data.value
          }
        })
      }

      // Add transformation outputs
      transformations.value.forEach(t => {
        if (t.enabled && t.lastValue !== null) {
          const safeName = t.name.replace(/[^a-zA-Z0-9_]/g, '_')
          namespace[safeName] = t.lastValue
          ch[safeName] = t.lastValue
        }
      })

      // Add calculated param outputs (for chaining)
      calculatedParams.value.forEach(p => {
        if (p.enabled && p.lastValue !== null) {
          const safeName = p.name.replace(/[^a-zA-Z0-9_]/g, '_')
          namespace[safeName] = p.lastValue
          ch[safeName] = p.lastValue
        }
      })

      const mathFuncs = {
        abs: Math.abs,
        sqrt: Math.sqrt,
        pow: Math.pow,
        log: Math.log,
        log10: Math.log10,
        exp: Math.exp,
        sin: Math.sin,
        cos: Math.cos,
        tan: Math.tan,
        asin: Math.asin,
        acos: Math.acos,
        atan: Math.atan,
        floor: Math.floor,
        ceil: Math.ceil,
        round: Math.round,
        min: Math.min,
        max: Math.max,
        PI: Math.PI,
        pi: Math.PI,  // Python-style lowercase
        E: Math.E,
        e: Math.E,    // Python-style lowercase
        sign: Math.sign,
        trunc: Math.trunc
      }

      // Build function with channel names as direct parameters + ch for legacy support
      const paramNames = Object.keys(namespace)
      const paramValues = Object.values(namespace)
      const evalFunc = new Function('ch', ...paramNames, ...Object.keys(mathFuncs), `return ${formula}`)
      const result = evalFunc(ch, ...paramValues, ...Object.values(mathFuncs))

      if (typeof result === 'number' && !isNaN(result) && isFinite(result)) {
        return { value: result, error: null }
      }
      if (typeof result === 'boolean') {
        return { value: result ? 1 : 0, error: null }
      }
      return { value: null, error: 'Invalid result' }
    } catch (e: any) {
      return { value: null, error: e.message || 'Evaluation error' }
    }
  }

  function updateCalculatedParams() {
    const scriptValues: Record<string, { value: number; name: string; displayName: string }> = {}

    calculatedParams.value.forEach(param => {
      if (param.enabled && param.formula) {
        const result = evaluateFormula(param.formula)
        param.lastValue = result.value
        param.lastError = result.error

        // Add to script values for store injection
        if (result.value !== null) {
          const channelName = `script:${param.name}`
          scriptValues[channelName] = {
            value: result.value,
            name: param.name,
            displayName: param.displayName || param.name
          }
        }
      }
    })

    // Also add transformations
    transformations.value.forEach(t => {
      if (t.enabled && t.lastValue !== null) {
        const channelName = `script:${t.name}`
        scriptValues[channelName] = {
          value: t.lastValue,
          name: t.name,
          displayName: t.name
        }
      }
    })

    // Push to dashboard store so widgets can bind to them
    if (Object.keys(scriptValues).length > 0) {
      store.updateScriptValues(scriptValues)
    }
  }

  // ========================================================================
  // CALCULATED PARAMS CRUD
  // ========================================================================

  function addCalculatedParam(param: Omit<CalculatedParam, 'id' | 'lastValue' | 'lastError'>) {
    const newParam: CalculatedParam = {
      ...param,
      id: `calc-${Date.now()}`,
      lastValue: null,
      lastError: null
    }
    calculatedParams.value.push(newParam)
    saveCalculatedParams()
    return newParam.id
  }

  function updateCalculatedParam(id: string, updates: Partial<CalculatedParam>) {
    const index = calculatedParams.value.findIndex(p => p.id === id)
    if (index >= 0) {
      const existing = calculatedParams.value[index]
      calculatedParams.value[index] = { ...existing, ...updates } as CalculatedParam
      saveCalculatedParams()
    }
  }

  function deleteCalculatedParam(id: string) {
    calculatedParams.value = calculatedParams.value.filter(p => p.id !== id)
    saveCalculatedParams()
  }

  // ========================================================================
  // SEQUENCES CRUD & EXECUTION
  // ========================================================================

  function addSequence(seq: Omit<Sequence, 'id' | 'state' | 'currentStepIndex' | 'currentLoopIterations' | 'currentIfResults' | 'variables' | 'createdAt' | 'modifiedAt'>) {
    const newSeq: Sequence = {
      ...seq,
      id: `seq-${Date.now()}`,
      state: 'idle',
      currentStepIndex: 0,
      currentLoopIterations: {},
      currentIfResults: {},
      variables: {},
      callStack: [],
      createdAt: new Date().toISOString(),
      modifiedAt: new Date().toISOString()
    }
    sequences.value.push(newSeq)
    saveSequences()
    return newSeq.id
  }

  function updateSequence(id: string, updates: Partial<Sequence>) {
    const index = sequences.value.findIndex(s => s.id === id)
    if (index >= 0) {
      const existing = sequences.value[index]
      if (!existing) return

      // SAFETY: If disabling a running sequence, stop it first
      if (updates.enabled === false && existing.state === 'running') {
        addNotification('warning', 'Sequence Stopped', `Stopping ${existing.name} - sequence was disabled`)
        abortSequence(id)
      }

      sequences.value[index] = {
        ...existing,
        ...updates,
        modifiedAt: new Date().toISOString()
      } as Sequence
      saveSequences()
    }
  }

  function deleteSequence(id: string) {
    if (runningSequenceId.value === id) {
      abortSequence(id)
    }
    sequences.value = sequences.value.filter(s => s.id !== id)
    saveSequences()
  }

  function startSequence(id: string) {
    const seq = sequences.value.find(s => s.id === id)
    if (!seq || seq.state === 'running') return false

    // Check if sequence is enabled
    if (!seq.enabled) {
      addNotification('warning', 'Cannot Start', `Sequence "${seq.name}" is disabled`)
      return false
    }

    if (runningSequenceId.value && runningSequenceId.value !== id) {
      abortSequence(runningSequenceId.value)
    }

    seq.state = 'running'
    seq.currentStepIndex = 0
    seq.currentLoopIterations = {}
    seq.currentIfResults = {}
    seq.variables = {}
    seq.callStack = []
    seq.startTime = Date.now()
    seq.error = undefined
    runningSequenceId.value = id

    addNotification('info', 'Sequence Started', `Started sequence: ${seq.name}`)
    emitSequenceEvent('started', seq)

    executeSequenceStep(seq)
    return true
  }

  function pauseSequence(id: string) {
    const seq = sequences.value.find(s => s.id === id)
    if (!seq || seq.state !== 'running') return false

    seq.state = 'paused'
    seq.pausedTime = Date.now()

    if (sequenceTimeoutId.value) {
      clearTimeout(sequenceTimeoutId.value)
      sequenceTimeoutId.value = null
    }

    addNotification('info', 'Sequence Paused', `Paused sequence: ${seq.name}`)
    return true
  }

  function resumeSequence(id: string) {
    const seq = sequences.value.find(s => s.id === id)
    if (!seq || seq.state !== 'paused') return false

    seq.state = 'running'
    addNotification('info', 'Sequence Resumed', `Resumed sequence: ${seq.name}`)
    executeSequenceStep(seq)
    return true
  }

  function abortSequence(id: string) {
    const seq = sequences.value.find(s => s.id === id)
    if (!seq) return false

    seq.state = 'aborted'
    runningSequenceId.value = null

    if (sequenceTimeoutId.value) {
      clearTimeout(sequenceTimeoutId.value)
      sequenceTimeoutId.value = null
    }

    addNotification('warning', 'Sequence Aborted', `Aborted sequence: ${seq.name}`)
    emitSequenceEvent('aborted', seq)
    recordSequenceHistory(seq, 'aborted')
    return true
  }

  function recordSequenceHistory(seq: Sequence, finalState: 'completed' | 'aborted' | 'error') {
    const now = Date.now()
    const historyEntry = {
      id: `run-${now}`,
      startTime: seq.startTime || now,
      endTime: now,
      state: finalState,
      duration: seq.startTime ? now - seq.startTime : 0,
      stepsCompleted: seq.currentStepIndex,
      totalSteps: seq.steps.length,
      error: seq.error,
      triggeredBy: 'manual' as const  // TODO: Track actual trigger source
    }

    // Initialize history array if needed
    if (!seq.runHistory) {
      seq.runHistory = []
    }

    // Add to history (keep last 50 runs)
    seq.runHistory.unshift(historyEntry)
    if (seq.runHistory.length > 50) {
      seq.runHistory = seq.runHistory.slice(0, 50)
    }

    // Update run stats
    seq.lastRunTime = now
    seq.runCount = (seq.runCount || 0) + 1

    // Save to localStorage
    saveSequences()
  }

  function emitSequenceEvent(event: 'started' | 'completed' | 'aborted' | 'error' | 'stepCompleted', seq: Sequence) {
    // Notify all registered listeners (for subroutine calls)
    sequenceEventListeners.forEach(listener => {
      try {
        listener(event, seq)
      } catch (e) {
        console.error('Sequence event listener error:', e)
      }
    })

    // Check triggers for sequence events
    triggers.value.forEach(trigger => {
      if (!trigger.enabled) return
      if (trigger.trigger?.type !== 'sequenceEvent') return

      const t = trigger.trigger as SequenceEventTrigger
      if (t.event !== event) return
      if (t.sequenceId && t.sequenceId !== seq.id) return

      // Trigger matches
      executeTriggerActions(trigger)
      trigger.lastTriggered = Date.now()

      if (trigger.oneShot) {
        trigger.enabled = false
        saveTriggers()
      }
    })
  }

  function onSequenceEvent(listener: SequenceEventListener): () => void {
    // Safety cap to prevent unbounded listener accumulation
    if (sequenceEventListeners.length > 100) {
      console.warn('Too many sequence event listeners — clearing stale entries')
      sequenceEventListeners.length = 0
    }
    sequenceEventListeners.push(listener)
    // Return unsubscribe function
    return () => {
      const index = sequenceEventListeners.indexOf(listener)
      if (index >= 0) {
        sequenceEventListeners.splice(index, 1)
      }
    }
  }

  function executeSequenceStep(seq: Sequence) {
    if (seq.state !== 'running') return

    if (seq.currentStepIndex >= seq.steps.length) {
      seq.state = 'completed'
      runningSequenceId.value = null
      addNotification('success', 'Sequence Completed', `Completed sequence: ${seq.name}`)
      emitSequenceEvent('completed', seq)
      recordSequenceHistory(seq, 'completed')
      return
    }

    const step = seq.steps[seq.currentStepIndex]
    if (!step || !step.enabled) {
      seq.currentStepIndex++
      executeSequenceStep(seq)
      return
    }

    try {
      switch (step.type) {
        case 'ramp':
          executeRampStep(seq, step as RampStep)
          break
        case 'soak':
          executeSoakStep(seq, step as SoakStep)
          break
        case 'wait':
          executeWaitStep(seq, step as WaitStep)
          break
        case 'setOutput':
          executeSetOutputStep(step as SetOutputStep)
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
          break
        case 'setVariable':
          executeSetVariableStep(seq, step as SetVariableStep)
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
          break
        case 'loop':
          executeLoopStep(seq, step as LoopStep)
          break
        case 'endLoop':
          executeEndLoopStep(seq, step as EndLoopStep)
          break
        case 'message':
          const msgStep = step as MessageStep
          addNotification(msgStep.severity || 'info', 'Sequence Message', msgStep.message || '')
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          if (!msgStep.pauseExecution) {
            executeSequenceStep(seq)
          }
          break
        case 'if':
          executeIfStep(seq, step as IfStep)
          break
        case 'else':
          executeElseStep(seq, step as ElseStep)
          break
        case 'endIf':
          executeEndIfStep(seq, step as EndIfStep)
          break
        case 'recording':
          executeRecordingStep(seq, step as RecordingStep)
          break
        case 'safetyCheck':
          executeSafetyCheckStep(seq, step as SafetyCheckStep)
          break
        case 'callSequence':
          executeCallSequenceStep(seq, step as CallSequenceStep)
          break
        default:
          seq.currentStepIndex++
          executeSequenceStep(seq)
      }
    } catch (e: any) {
      seq.state = 'error'
      seq.error = e.message
      runningSequenceId.value = null
      addNotification('error', 'Sequence Error', `Error in ${seq.name}: ${e.message}`)
      emitSequenceEvent('error', seq)
    }
  }

  function executeRampStep(seq: Sequence, step: RampStep) {
    // Send initial setpoint
    if (step.targetChannel) {
      sendOutput(step.targetChannel, step.targetValue)
    }

    addNotification('info', 'Ramp Step', `Ramping to ${step.targetValue} at ${step.rampRate} ${step.rampRateUnit}`)

    const checkReached = () => {
      if (seq.state !== 'running') return

      const currentValue = store.values[step.monitorChannel]?.value
      if (currentValue !== undefined) {
        if (Math.abs(currentValue - step.targetValue) <= step.tolerance) {
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
          return
        }
      }

      sequenceTimeoutId.value = window.setTimeout(checkReached, 1000)
    }

    checkReached()
  }

  function executeSoakStep(seq: Sequence, step: SoakStep) {
    addNotification('info', 'Soak Step', `Soaking for ${step.duration} seconds`)

    sequenceTimeoutId.value = window.setTimeout(() => {
      if (seq.state !== 'running') return
      seq.currentStepIndex++
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
    }, step.duration * 1000)
  }

  function executeWaitStep(seq: Sequence, step: WaitStep) {
    addNotification('info', 'Wait Step', `Waiting for: ${step.condition}`)

    const startTime = Date.now()
    const maxRetries = step.retryCount ?? 3
    const retryDelay = step.retryDelayMs ?? 1000

    const checkCondition = () => {
      if (seq.state !== 'running') return

      if (step.condition) {
        const result = evaluateFormula(step.condition)
        if (result.value && result.value !== 0) {
          // Condition met - reset retry counter and continue
          seq.currentRetryCount = 0
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
          return
        }
      }

      if (step.timeout && step.timeout > 0) {
        const elapsed = (Date.now() - startTime) / 1000
        if (elapsed >= step.timeout) {
          // Handle timeout based on action type
          handleWaitTimeout(seq, step, maxRetries, retryDelay)
          return
        }
      }

      sequenceTimeoutId.value = window.setTimeout(checkCondition, 500)
    }

    checkCondition()
  }

  function handleWaitTimeout(seq: Sequence, step: WaitStep, maxRetries: number, retryDelay: number) {
    const currentRetry = seq.currentRetryCount ?? 0

    switch (step.timeoutAction) {
      case 'abort':
        seq.state = 'aborted'
        seq.error = `Wait step timed out`
        seq.currentRetryCount = 0
        runningSequenceId.value = null
        addNotification('error', 'Wait Timeout', `Wait step timed out in ${seq.name}`)
        emitSequenceEvent('aborted', seq)
        recordSequenceHistory(seq, 'aborted')
        break

      case 'continue':
        seq.currentRetryCount = 0
        seq.currentStepIndex++
        emitSequenceEvent('stepCompleted', seq)
        executeSequenceStep(seq)
        break

      case 'alarm':
        addNotification('warning', 'Wait Timeout', `Wait condition not met, continuing...`)
        seq.currentRetryCount = 0
        seq.currentStepIndex++
        emitSequenceEvent('stepCompleted', seq)
        executeSequenceStep(seq)
        break

      case 'skip':
        addNotification('info', 'Step Skipped', `Skipping wait step due to timeout`)
        seq.currentRetryCount = 0
        seq.currentStepIndex++
        emitSequenceEvent('stepCompleted', seq)
        executeSequenceStep(seq)
        break

      case 'retry':
        if (currentRetry < maxRetries) {
          seq.currentRetryCount = currentRetry + 1
          addNotification('warning', 'Wait Retry', `Retrying wait step (${seq.currentRetryCount}/${maxRetries})`)

          // Delay before retry
          sequenceTimeoutId.value = window.setTimeout(() => {
            if (seq.state !== 'running') return
            // Re-execute the same step
            executeWaitStep(seq, step as WaitStep)
          }, retryDelay)
        } else {
          // All retries exhausted - use fallback action
          seq.currentRetryCount = 0
          const fallback = step.onFinalFailure || 'abort'
          addNotification('error', 'Retries Exhausted', `All ${maxRetries} retries failed for wait step`)

          if (fallback === 'abort') {
            seq.state = 'aborted'
            seq.error = `Wait step failed after ${maxRetries} retries`
            runningSequenceId.value = null
            emitSequenceEvent('aborted', seq)
            recordSequenceHistory(seq, 'aborted')
          } else if (fallback === 'alarm') {
            addNotification('error', 'Wait Failed', `Wait step failed - continuing with alarm`)
            seq.currentStepIndex++
            emitSequenceEvent('stepCompleted', seq)
            executeSequenceStep(seq)
          } else {
            // continue
            seq.currentStepIndex++
            emitSequenceEvent('stepCompleted', seq)
            executeSequenceStep(seq)
          }
        }
        break

      default:
        // Unknown action - abort
        seq.state = 'aborted'
        seq.error = `Wait step timed out`
        seq.currentRetryCount = 0
        runningSequenceId.value = null
        emitSequenceEvent('aborted', seq)
        recordSequenceHistory(seq, 'aborted')
    }
  }

  function executeSetOutputStep(step: SetOutputStep) {
    sendOutput(step.channel, step.value)
  }

  function executeSetVariableStep(seq: Sequence, step: SetVariableStep) {
    let value: number

    if (step.isFormula && typeof step.value === 'string') {
      // Evaluate formula with sequence variables available
      const result = evaluateFormulaWithSequenceVars(step.value, seq)
      if (result.error) {
        throw new Error(`Variable ${step.variableName}: ${result.error}`)
      }
      value = result.value ?? 0
    } else {
      value = typeof step.value === 'number' ? step.value : parseFloat(step.value as string) || 0
    }

    // Store in sequence variables
    if (!seq.variables) seq.variables = {}
    seq.variables[step.variableName] = value

    addNotification('info', 'Variable Set', `${step.variableName} = ${value}`)
  }

  function evaluateFormulaWithSequenceVars(formula: string, seq: Sequence): { value: number | null; error: string | null } {
    if (!formula || formula.trim() === '') {
      return { value: null, error: 'Empty formula' }
    }

    const safetyError = validateFormulaSafety(formula)
    if (safetyError) {
      return { value: null, error: safetyError }
    }

    try {
      // Build namespace with all values
      // Supports both direct syntax (TC101) and legacy ch.TC101 / seq.varName syntax
      const namespace: Record<string, number> = {}
      const ch: Record<string, number> = {}  // Legacy ch.NAME support

      // Add channel values
      if (store.values) {
        Object.entries(store.values).forEach(([name, data]) => {
          if (data && typeof data.value === 'number') {
            const safeName = name.replace(/[^a-zA-Z0-9_]/g, '_')
            namespace[safeName] = data.value
            ch[safeName] = data.value
          }
        })
      }

      // Add sequence variables (accessible as seq.varName or just varName)
      const seqVars: Record<string, number> = {}
      if (seq.variables) {
        Object.entries(seq.variables).forEach(([name, value]) => {
          seqVars[name] = value
          namespace[name] = value  // Direct access
          ch[name] = value  // Also via ch.name (legacy)
        })
      }

      // Add loop iteration counters
      if (seq.currentLoopIterations) {
        Object.entries(seq.currentLoopIterations).forEach(([loopId, iteration]) => {
          const name = `loop_${loopId}`
          namespace[name] = iteration
          ch[name] = iteration
        })
      }

      // Add transformation outputs
      transformations.value.forEach(t => {
        if (t.enabled && t.lastValue !== null) {
          const safeName = t.name.replace(/[^a-zA-Z0-9_]/g, '_')
          namespace[safeName] = t.lastValue
          ch[safeName] = t.lastValue
        }
      })

      // Add calculated param outputs
      calculatedParams.value.forEach(p => {
        if (p.enabled && p.lastValue !== null) {
          const safeName = p.name.replace(/[^a-zA-Z0-9_]/g, '_')
          namespace[safeName] = p.lastValue
          ch[safeName] = p.lastValue
        }
      })

      const mathFuncs = {
        abs: Math.abs,
        sqrt: Math.sqrt,
        pow: Math.pow,
        log: Math.log,
        log10: Math.log10,
        exp: Math.exp,
        sin: Math.sin,
        cos: Math.cos,
        tan: Math.tan,
        asin: Math.asin,
        acos: Math.acos,
        atan: Math.atan,
        floor: Math.floor,
        ceil: Math.ceil,
        round: Math.round,
        min: Math.min,
        max: Math.max,
        PI: Math.PI,
        pi: Math.PI,  // Python-style lowercase
        E: Math.E,
        e: Math.E,    // Python-style lowercase
        sign: Math.sign,
        trunc: Math.trunc
      }

      // Build function with all names as direct parameters + ch/seq for legacy support
      const paramNames = Object.keys(namespace)
      const paramValues = Object.values(namespace)
      const evalFunc = new Function('ch', 'seq', ...paramNames, ...Object.keys(mathFuncs), `return ${formula}`)
      const result = evalFunc(ch, seqVars, ...paramValues, ...Object.values(mathFuncs))

      if (typeof result === 'number' && !isNaN(result) && isFinite(result)) {
        return { value: result, error: null }
      }
      if (typeof result === 'boolean') {
        return { value: result ? 1 : 0, error: null }
      }
      return { value: null, error: 'Invalid result' }
    } catch (e: any) {
      return { value: null, error: e.message || 'Evaluation error' }
    }
  }

  function executeLoopStep(seq: Sequence, step: LoopStep) {
    if (!seq.currentLoopIterations[step.loopId]) {
      seq.currentLoopIterations[step.loopId] = 0
    }
    seq.currentStepIndex++
    executeSequenceStep(seq)
  }

  function executeEndLoopStep(seq: Sequence, step: { loopId: string }) {
    const loopStep = seq.steps.find(s => s.type === 'loop' && (s as LoopStep).loopId === step.loopId) as LoopStep | undefined

    if (!loopStep) {
      seq.currentStepIndex++
      executeSequenceStep(seq)
      return
    }

    seq.currentLoopIterations[step.loopId] = (seq.currentLoopIterations[step.loopId] || 0) + 1

    if (loopStep.iterations === 0 || seq.currentLoopIterations[step.loopId]! < loopStep.iterations) {
      const loopStartIndex = seq.steps.findIndex(s => s.id === loopStep.id)
      seq.currentStepIndex = loopStartIndex + 1
    } else {
      delete seq.currentLoopIterations[step.loopId]
      seq.currentStepIndex++
    }

    executeSequenceStep(seq)
  }

  // ========================================================================
  // CONDITIONAL BRANCHING (If/Else/EndIf)
  // ========================================================================

  function executeIfStep(seq: Sequence, step: IfStep) {
    // Initialize currentIfResults if not exists
    if (!seq.currentIfResults) seq.currentIfResults = {}

    // Evaluate the condition
    const result = evaluateFormulaWithSequenceVars(step.condition, seq)
    const conditionResult = result.value !== null && result.value !== 0

    // Store the result for else/endIf navigation
    seq.currentIfResults[step.ifId] = conditionResult

    if (conditionResult) {
      // Condition is true - execute the if block (continue to next step)
      seq.currentStepIndex++
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
    } else {
      // Condition is false - skip to else or endIf
      const elseIndex = seq.steps.findIndex(s =>
        (s.type === 'else' && (s as ElseStep).ifId === step.ifId)
      )
      const endIfIndex = seq.steps.findIndex(s =>
        (s.type === 'endIf' && (s as EndIfStep).ifId === step.ifId)
      )

      if (elseIndex > seq.currentStepIndex) {
        // Jump to else block
        seq.currentStepIndex = elseIndex + 1
      } else if (endIfIndex > seq.currentStepIndex) {
        // No else, jump to endIf
        seq.currentStepIndex = endIfIndex + 1
      } else {
        // Malformed if block - just continue
        seq.currentStepIndex++
      }
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
    }
  }

  function executeElseStep(seq: Sequence, step: ElseStep) {
    // If we reached else, it means the if condition was true and we executed the if block
    // So we need to skip to endIf
    const endIfIndex = seq.steps.findIndex(s =>
      s.type === 'endIf' && (s as EndIfStep).ifId === step.ifId
    )

    if (endIfIndex > seq.currentStepIndex) {
      seq.currentStepIndex = endIfIndex + 1
    } else {
      seq.currentStepIndex++
    }
    emitSequenceEvent('stepCompleted', seq)
    executeSequenceStep(seq)
  }

  function executeEndIfStep(seq: Sequence, step: EndIfStep) {
    // Clean up the if result tracking
    if (seq.currentIfResults) {
      delete seq.currentIfResults[step.ifId]
    }
    seq.currentStepIndex++
    emitSequenceEvent('stepCompleted', seq)
    executeSequenceStep(seq)
  }

  // ========================================================================
  // RECORDING CONTROL
  // ========================================================================

  function executeRecordingStep(seq: Sequence, step: RecordingStep) {
    if (step.action === 'start') {
      // Use MQTT handler to start recording
      if (mqttStartRecording) {
        mqttStartRecording(step.filename)
      }
      addNotification('info', 'Recording Started', step.filename || 'Auto-generated filename')
    } else {
      // Use MQTT handler to stop recording
      if (mqttStopRecording) {
        mqttStopRecording()
      }
      addNotification('info', 'Recording Stopped', 'Data recording stopped by sequence')
    }
    seq.currentStepIndex++
    emitSequenceEvent('stepCompleted', seq)
    executeSequenceStep(seq)
  }

  // ========================================================================
  // SAFETY CHECK
  // ========================================================================

  function executeSafetyCheckStep(seq: Sequence, step: SafetyCheckStep) {
    const result = evaluateFormulaWithSequenceVars(step.condition, seq)
    const safetyOk = result.value !== null && result.value !== 0

    if (safetyOk) {
      // Safety check passed
      seq.currentStepIndex++
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
    } else {
      // Safety check failed
      addNotification('error', 'Safety Check Failed', step.failMessage)

      switch (step.failAction) {
        case 'abort':
          seq.state = 'aborted'
          seq.error = `Safety check failed: ${step.failMessage}`
          runningSequenceId.value = null
          emitSequenceEvent('aborted', seq)
          break
        case 'pause':
          seq.state = 'paused'
          seq.pausedTime = Date.now()
          addNotification('warning', 'Sequence Paused', 'Waiting for safety condition')
          break
        case 'alarm':
          // Just log the alarm and continue
          addNotification('error', 'Safety Alarm', step.failMessage)
          seq.currentStepIndex++
          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
          break
      }
    }
  }

  // ========================================================================
  // CALL SEQUENCE (Subroutine)
  // ========================================================================

  function executeCallSequenceStep(seq: Sequence, step: CallSequenceStep) {
    const targetSequence = sequences.value.find(s => s.id === step.sequenceId)

    if (!targetSequence) {
      addNotification('error', 'Call Sequence Error', `Sequence ${step.sequenceId} not found`)
      seq.currentStepIndex++
      executeSequenceStep(seq)
      return
    }

    if (!targetSequence.enabled) {
      addNotification('warning', 'Called Sequence Disabled', `${targetSequence.name} is disabled, skipping`)
      seq.currentStepIndex++
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
      return
    }

    // Initialize call stack if needed
    if (!seq.callStack) seq.callStack = []

    // Check for recursion (prevent infinite loops)
    if (seq.callStack.includes(step.sequenceId)) {
      addNotification('error', 'Recursion Detected', `Cannot call ${targetSequence.name} - already in call stack`)
      seq.currentStepIndex++
      executeSequenceStep(seq)
      return
    }

    if (step.waitForCompletion) {
      // Synchronous call - pause parent, run child
      seq.state = 'paused'
      seq.callStack.push(step.sequenceId)

      // Set up the child sequence
      targetSequence.state = 'running'
      targetSequence.currentStepIndex = 0
      targetSequence.currentLoopIterations = {}
      targetSequence.currentIfResults = {}
      targetSequence.variables = { ...seq.variables } // Pass variables to child
      targetSequence.startTime = Date.now()
      targetSequence.parentSequenceId = seq.id

      // Subscribe to child completion
      const unsubscribe = onSequenceEvent((event, eventSeq) => {
        if (eventSeq.id === step.sequenceId &&
            (event === 'completed' || event === 'aborted' || event === 'error')) {
          unsubscribe()

          // Resume parent sequence
          seq.callStack = seq.callStack?.filter(id => id !== step.sequenceId)
          seq.state = 'running'
          seq.currentStepIndex++

          // Copy any variables set by child back to parent
          if (targetSequence.variables) {
            seq.variables = { ...seq.variables, ...targetSequence.variables }
          }

          emitSequenceEvent('stepCompleted', seq)
          executeSequenceStep(seq)
        }
      })

      // Start child execution
      runningSequenceId.value = step.sequenceId
      executeSequenceStep(targetSequence)
    } else {
      // Fire-and-forget - start child and continue parent
      addNotification('info', 'Starting Sequence', `Starting ${targetSequence.name} (async)`)
      startSequence(step.sequenceId)
      seq.currentStepIndex++
      emitSequenceEvent('stepCompleted', seq)
      executeSequenceStep(seq)
    }
  }

  // ========================================================================
  // ALARMS
  // ========================================================================

  function addAlarm(alarm: Omit<Alarm, 'id' | 'state' | 'triggerCount'>) {
    const newAlarm: Alarm = {
      ...alarm,
      id: `alarm-${Date.now()}`,
      state: 'normal',
      triggerCount: 0
    }
    alarms.value.push(newAlarm)
    saveAlarms()
    return newAlarm.id
  }

  function updateAlarm(id: string, updates: Partial<Alarm>) {
    const index = alarms.value.findIndex(a => a.id === id)
    if (index >= 0) {
      const existing = alarms.value[index]
      alarms.value[index] = { ...existing, ...updates } as Alarm
      saveAlarms()
    }
  }

  function deleteAlarm(id: string) {
    alarms.value = alarms.value.filter(a => a.id !== id)
    activeAlarmIds.value = activeAlarmIds.value.filter(aid => aid !== id)
    saveAlarms()
  }

  function acknowledgeAlarm(id: string, user?: string) {
    const alarm = alarms.value.find(a => a.id === id)
    if (alarm && alarm.state === 'active') {
      alarm.state = 'acknowledged'
      alarm.acknowledgedAt = Date.now()
      alarm.acknowledgedBy = user
      addNotification('info', 'Alarm Acknowledged', `Acknowledged: ${alarm.name}`)
    }
  }

  function evaluateAlarms() {
    alarms.value.forEach(alarm => {
      if (!alarm.enabled || !alarm.conditions?.length) return

      try {
        const conditionMet = evaluateAlarmConditions(alarm)

        if (conditionMet && alarm.state === 'normal') {
          alarm.state = 'active'
          alarm.triggeredAt = Date.now()
          alarm.triggerCount = (alarm.triggerCount || 0) + 1
          alarm.lastTriggered = Date.now()

          if (!activeAlarmIds.value.includes(alarm.id)) {
            activeAlarmIds.value.push(alarm.id)
          }

          executeAlarmActions(alarm)

          alarmHistory.value.unshift({
            alarmId: alarm.id,
            triggeredAt: Date.now(),
            message: alarm.name
          })
          if (alarmHistory.value.length > 100) {
            alarmHistory.value = alarmHistory.value.slice(0, 100)
          }
        } else if (!conditionMet && (alarm.state === 'active' || alarm.state === 'acknowledged')) {
          if (alarm.autoResetMs > 0) {
            const timeSinceTriggered = Date.now() - (alarm.triggeredAt || 0)
            if (timeSinceTriggered >= alarm.autoResetMs) {
              alarm.state = 'normal'
              activeAlarmIds.value = activeAlarmIds.value.filter(id => id !== alarm.id)
              addNotification('info', 'Alarm Cleared', `Alarm cleared: ${alarm.name}`)
            }
          }
        }
      } catch (e) {
        console.error('Error evaluating alarm:', alarm.name, e)
      }
    })
  }

  function evaluateAlarmConditions(alarm: Alarm): boolean {
    if (!alarm.conditions?.length) return false

    const results = alarm.conditions.map(cond => {
      const channelValue = store.values[cond.channel]?.value
      if (channelValue === undefined) return false

      switch (cond.operator) {
        case '>': return channelValue > cond.value
        case '<': return channelValue < cond.value
        case '>=': return channelValue >= cond.value
        case '<=': return channelValue <= cond.value
        case '==': return channelValue === cond.value
        case '!=': return channelValue !== cond.value
        case 'roc>':
        case 'roc<':
          const roc = calculateRateOfChange(cond.channel)
          if (roc === null) return false
          return cond.operator === 'roc>' ? roc > cond.value : roc < cond.value
        default: return false
      }
    })

    return alarm.conditionLogic === 'AND' ? results.every(r => r) : results.some(r => r)
  }

  function calculateRateOfChange(channel: string): number | null {
    const current = store.values[channel]
    const last = lastValues.value[channel]

    if (!current || !last) return null

    const timeDeltaMin = (current.timestamp - last.timestamp) / 60000
    if (timeDeltaMin <= 0) return null

    return (current.value - last.value) / timeDeltaMin
  }

  function executeAlarmActions(alarm: Alarm) {
    if (!alarm.actions?.length) return

    // Add notification for alarm
    const notifType = alarm.severity === 'critical' ? 'error' : alarm.severity === 'warning' ? 'warning' : 'info'
    addNotification(notifType, `ALARM: ${alarm.name}`, alarm.description || 'Alarm triggered')

    alarm.actions.forEach(action => {
      try {
        switch (action.type) {
          case 'notification':
            addNotification(notifType, alarm.name, action.message || alarm.description || '')
            break
          case 'setOutput':
            if (action.channel && action.value !== undefined) {
              sendOutput(action.channel, action.value)
            }
            break
          case 'abortSequence':
            if (runningSequenceId.value) {
              abortSequence(runningSequenceId.value)
            }
            break
          case 'runSequence':
            if (action.sequenceId) {
              startSequence(action.sequenceId)
            }
            break
          case 'sound':
            playAlarmSound()
            break
          case 'log':
            console.debug(`[ALARM LOG] ${new Date().toISOString()} - ${alarm.name}: ${alarm.description}`)
            break
        }
      } catch (e) {
        console.error('Error executing alarm action:', e)
      }
    })
  }

  function playAlarmSound() {
    try {
      // Create a simple beep using Web Audio API
      const audioContext = new (window.AudioContext || (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)!()
      const oscillator = audioContext.createOscillator()
      const gainNode = audioContext.createGain()

      oscillator.connect(gainNode)
      gainNode.connect(audioContext.destination)

      oscillator.frequency.value = 800
      oscillator.type = 'square'
      gainNode.gain.value = 0.3

      oscillator.start()
      setTimeout(() => {
        oscillator.stop()
        audioContext.close()
      }, 500)
    } catch (e) {
      console.warn('Could not play alarm sound:', e)
    }
  }

  // ========================================================================
  // TRANSFORMATIONS
  // ========================================================================

  function addTransformation(transform: Omit<Transformation, 'id' | 'lastValue' | 'lastError'>) {
    const newTransform = {
      ...transform,
      id: `transform-${Date.now()}`,
      lastValue: null,
      lastError: null
    } as Transformation
    transformations.value.push(newTransform)
    transformationBuffers.value[newTransform.id] = []
    saveTransformations()
    return newTransform.id
  }

  function updateTransformation(id: string, updates: Partial<Transformation>) {
    const index = transformations.value.findIndex(t => t.id === id)
    if (index >= 0) {
      transformations.value[index] = { ...transformations.value[index], ...updates } as Transformation
      saveTransformations()
    }
  }

  function deleteTransformation(id: string) {
    transformations.value = transformations.value.filter(t => t.id !== id)
    delete transformationBuffers.value[id]
    saveTransformations()
  }

  function evaluateTransformations() {
    transformations.value.forEach(transform => {
      if (!transform.enabled) return

      try {
        const inputValue = store.values[transform.inputChannel]?.value
        if (inputValue === undefined) {
          transform.lastValue = null
          transform.lastError = 'No input value'
          return
        }

        let result: number | null = null

        switch (transform.type) {
          case 'rollingAverage':
          case 'rollingMin':
          case 'rollingMax':
          case 'rollingStdDev':
            result = calculateRolling(transform as RollingTransformation, inputValue)
            break
          case 'rateOfChange':
            result = calculateRateOfChangeTransform(transform as RateOfChangeTransformation, inputValue)
            break
          case 'unitConversion':
            result = calculateUnitConversion(transform as UnitConversionTransformation, inputValue)
            break
          case 'polynomial':
            result = calculatePolynomial(transform as PolynomialTransformation, inputValue)
            break
          case 'deadband':
            const db = transform as DeadbandTransformation
            if (transform.lastValue === null || Math.abs(inputValue - transform.lastValue) >= (db.deadband || 1)) {
              result = inputValue
            } else {
              result = transform.lastValue
            }
            break
          case 'clamp':
            const cl = transform as ClampTransformation
            result = Math.max(cl.minValue || 0, Math.min(cl.maxValue || 100, inputValue))
            break
          default:
            result = inputValue
        }

        transform.lastValue = result
        transform.lastError = null
      } catch (e: any) {
        transform.lastValue = null
        transform.lastError = e.message
      }
    })
  }

  function calculateRolling(transform: RollingTransformation, inputValue: number): number {
    const buffer = transformationBuffers.value[transform.id] || []
    buffer.push(inputValue)

    const windowSize = transform.windowSize || 10
    while (buffer.length > windowSize) {
      buffer.shift()
    }
    transformationBuffers.value[transform.id] = buffer

    if (buffer.length === 0) return inputValue

    switch (transform.type) {
      case 'rollingAverage':
        return buffer.reduce((a, b) => a + b, 0) / buffer.length
      case 'rollingMin':
        return Math.min(...buffer)
      case 'rollingMax':
        return Math.max(...buffer)
      case 'rollingStdDev':
        const mean = buffer.reduce((a, b) => a + b, 0) / buffer.length
        const squaredDiffs = buffer.map(x => Math.pow(x - mean, 2))
        return Math.sqrt(squaredDiffs.reduce((a, b) => a + b, 0) / buffer.length)
      default:
        return inputValue
    }
  }

  function calculateRateOfChangeTransform(transform: RateOfChangeTransformation, inputValue: number): number | null {
    const now = Date.now()
    const last = lastValues.value[transform.inputChannel]

    lastValues.value[transform.inputChannel] = { value: inputValue, timestamp: now }

    if (!last) return null

    const timeDeltaMs = now - last.timestamp
    if (timeDeltaMs <= 0) return null

    const timeDeltaMin = timeDeltaMs / 60000
    return (inputValue - last.value) / timeDeltaMin
  }

  function calculateUnitConversion(transform: UnitConversionTransformation, inputValue: number): number {
    if (transform.conversionType === 'custom') {
      return inputValue * (transform.multiplier || 1) + (transform.offset || 0)
    }

    const conversion = UNIT_CONVERSIONS[transform.conversionType as UnitConversionType]
    if (conversion) {
      return conversion.formula(inputValue)
    }

    return inputValue
  }

  function calculatePolynomial(transform: PolynomialTransformation, inputValue: number): number {
    if (!transform.coefficients?.length) return inputValue

    let result = 0
    transform.coefficients.forEach((coef, power) => {
      result += coef * Math.pow(inputValue, power)
    })
    return result
  }

  // ========================================================================
  // TRIGGERS
  // ========================================================================

  function addTrigger(trigger: Omit<AutomationTrigger, 'id'>) {
    const newTrigger: AutomationTrigger = {
      ...trigger,
      id: `trigger-${Date.now()}`
    }
    triggers.value.push(newTrigger)
    saveTriggers()
    return newTrigger.id
  }

  function updateTrigger(id: string, updates: Partial<AutomationTrigger>) {
    const index = triggers.value.findIndex(t => t.id === id)
    if (index >= 0) {
      const existing = triggers.value[index]
      triggers.value[index] = { ...existing, ...updates } as AutomationTrigger
      saveTriggers()
    }
  }

  function deleteTrigger(id: string) {
    triggers.value = triggers.value.filter(t => t.id !== id)
    saveTriggers()
  }

  // ========================================================================
  // SCHEDULES CRUD & EVALUATION
  // ========================================================================

  function loadSchedules() {
    try {
      const stored = localStorage.getItem(STORAGE_KEYS.SCHEDULES)
      if (stored) {
        schedules.value = JSON.parse(stored)
        // Recalculate next run times
        schedules.value.forEach(s => {
          s.nextRun = calculateNextRun(s)
        })
      }
    } catch (e) {
      console.error('Failed to load schedules:', e)
    }
  }

  function saveSchedules() {
    try {
      localStorage.setItem(STORAGE_KEYS.SCHEDULES, JSON.stringify(schedules.value))
    } catch (e) {
      console.error('Failed to save schedules:', e)
    }
  }

  function addSchedule(schedule: Omit<Schedule, 'id' | 'lastRun' | 'nextRun' | 'isRunning'>): string {
    const newSchedule: Schedule = {
      ...schedule,
      id: `schedule-${Date.now()}`,
      isRunning: false,
      nextRun: undefined
    }
    newSchedule.nextRun = calculateNextRun(newSchedule)
    schedules.value.push(newSchedule)
    saveSchedules()
    return newSchedule.id
  }

  function updateSchedule(id: string, updates: Partial<Schedule>) {
    const index = schedules.value.findIndex(s => s.id === id)
    if (index >= 0) {
      const existing = schedules.value[index]!
      const updated = { ...existing, ...updates } as Schedule
      updated.nextRun = calculateNextRun(updated)
      schedules.value[index] = updated
      saveSchedules()
    }
  }

  function deleteSchedule(id: string) {
    schedules.value = schedules.value.filter(s => s.id !== id)
    saveSchedules()
  }

  function calculateNextRun(schedule: Schedule): string | undefined {
    if (!schedule.enabled) return undefined

    const now = new Date()
    const timeParts = schedule.startTime.split(':').map(Number)
    const hours = timeParts[0] ?? 0
    const minutes = timeParts[1] ?? 0

    let next = new Date()
    next.setHours(hours, minutes, 0, 0)

    switch (schedule.repeat) {
      case 'once':
        if (schedule.date) {
          next = new Date(schedule.date)
          next.setHours(hours, minutes, 0, 0)
        }
        if (next <= now) return undefined // Already passed
        break

      case 'daily':
        if (next <= now) {
          next.setDate(next.getDate() + 1)
        }
        break

      case 'weekly':
        if (schedule.daysOfWeek && schedule.daysOfWeek.length > 0) {
          // Find next matching day
          for (let i = 0; i < 7; i++) {
            const checkDate = new Date(now)
            checkDate.setDate(now.getDate() + i)
            checkDate.setHours(hours, minutes, 0, 0)
            if (schedule.daysOfWeek.includes(checkDate.getDay()) && checkDate > now) {
              next = checkDate
              break
            }
          }
        }
        break

      case 'monthly':
        if (schedule.dayOfMonth) {
          next.setDate(schedule.dayOfMonth)
          if (next <= now) {
            next.setMonth(next.getMonth() + 1)
          }
        }
        break
    }

    return next.toISOString()
  }

  function evaluateSchedules() {
    const now = new Date()

    schedules.value.forEach(schedule => {
      if (!schedule.enabled) return

      // Check if it's time to start
      if (schedule.nextRun && !schedule.isRunning) {
        const nextRunTime = new Date(schedule.nextRun)
        if (now >= nextRunTime) {
          // Execute start actions
          executeScheduleActions(schedule.startActions)
          schedule.isRunning = true
          schedule.lastRun = now.toISOString()
          addNotification('info', 'Schedule Started', `Schedule "${schedule.name}" has started`)
        }
      }

      // Check if it's time to end
      if (schedule.isRunning && schedule.endTime) {
        const endTimeParts = schedule.endTime.split(':').map(Number)
        const endHours = endTimeParts[0] ?? 0
        const endMinutes = endTimeParts[1] ?? 0
        const endTime = new Date()
        endTime.setHours(endHours, endMinutes, 0, 0)

        if (now >= endTime) {
          // Execute end actions
          if (schedule.endActions) {
            executeScheduleActions(schedule.endActions)
          }
          schedule.isRunning = false
          schedule.nextRun = calculateNextRun(schedule)
          addNotification('info', 'Schedule Ended', `Schedule "${schedule.name}" has ended`)
        }
      }
    })

    saveSchedules()
  }

  function executeScheduleActions(actions: ScheduleAction[]) {
    actions.forEach(action => {
      try {
        switch (action.type) {
          case 'start_sequence':
            if (action.sequenceId) {
              const seq = sequences.value.find(s => s.id === action.sequenceId)
              if (seq) startSequence(seq.id)
            }
            break
          case 'start_recording':
            if (mqttStartRecording) {
              mqttStartRecording(action.recordingFilename)
            }
            break
          case 'stop_recording':
            if (mqttStopRecording) {
              mqttStopRecording()
            }
            break
          case 'set_output':
            if (action.channel && action.value !== undefined) {
              sendOutput(action.channel, action.value)
            }
            break
          case 'run_formula':
            if (action.formula) {
              evaluateFormula(action.formula)
            }
            break
          case 'start_draw_pattern':
            if (action.drawPatternId) {
              startDrawPattern(action.drawPatternId)
            }
            break
          case 'valve_draw':
            // Execute a specific draw from a pattern (or standalone draw)
            if (action.drawPatternId && action.drawNumber) {
              const pattern = drawPatterns.value.find(p => p.id === action.drawPatternId)
              if (pattern) {
                const draw = pattern.draws.find(d => d.drawNumber === action.drawNumber)
                if (draw) {
                  // Execute single draw inline
                  executeSingleDraw(draw.valve, pattern.flowChannel, draw.volumeTarget, draw.volumeUnit, draw.maxDuration)
                }
              }
            }
            break
        }
      } catch (e) {
        console.error('Error executing schedule action:', e)
      }
    })
  }

  const enabledSchedules = computed(() => schedules.value.filter(s => s.enabled))
  const hasActiveSchedule = computed(() => schedules.value.some(s => s.enabled && s.isRunning))

  // ========================================================================
  // DRAW PATTERNS CRUD & EXECUTION
  // ========================================================================

  function loadDrawPatterns() {
    try {
      const stored = localStorage.getItem(DRAW_PATTERNS_STORAGE_KEY)
      if (stored) {
        const data = JSON.parse(stored)
        drawPatterns.value = data.patterns || []
        drawPatternHistory.value = (data.history || []).slice(0, 100) // Keep last 100
      }
    } catch (e) {
      console.error('Failed to load draw patterns:', e)
    }
  }

  function saveDrawPatterns() {
    try {
      localStorage.setItem(DRAW_PATTERNS_STORAGE_KEY, JSON.stringify({
        patterns: drawPatterns.value,
        history: drawPatternHistory.value.slice(0, 100)
      }))
    } catch (e) {
      console.error('Failed to save draw patterns:', e)
    }
  }

  function addDrawPattern(pattern: Omit<DrawPattern, 'id' | 'state' | 'currentDrawIndex' | 'cycleCount' | 'totalVolumeDispensed'>): string {
    const newPattern: DrawPattern = {
      ...pattern,
      id: `dp-${Date.now()}`,
      state: 'idle',
      currentDrawIndex: -1,
      cycleCount: 0,
      totalVolumeDispensed: 0
    }
    drawPatterns.value.push(newPattern)
    saveDrawPatterns()
    return newPattern.id
  }

  function updateDrawPattern(id: string, updates: Partial<DrawPattern>) {
    const pattern = drawPatterns.value.find(p => p.id === id)
    if (pattern) {
      Object.assign(pattern, updates)
      saveDrawPatterns()
    }
  }

  function deleteDrawPattern(id: string) {
    if (activeDrawPatternId.value === id) {
      stopDrawPattern(id)
    }
    drawPatterns.value = drawPatterns.value.filter(p => p.id !== id)
    saveDrawPatterns()
  }

  // Draw CRUD within a pattern
  function addDraw(patternId: string, draw: Omit<Draw, 'id' | 'drawNumber' | 'state' | 'volumeDispensed' | 'elapsedTime'>) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern) return

    const maxDrawNumber = pattern.draws.reduce((max, d) => Math.max(max, d.drawNumber || 0), 0)
    const newDraw: Draw = {
      ...draw,
      id: `draw-${Date.now()}`,
      drawNumber: maxDrawNumber + 1,
      state: 'pending',
      volumeDispensed: 0,
      elapsedTime: 0
    }
    pattern.draws.push(newDraw)
    saveDrawPatterns()
  }

  function updateDraw(patternId: string, drawId: string, updates: Partial<Draw>) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern) return

    const draw = pattern.draws.find(d => d.id === drawId)
    if (draw) {
      Object.assign(draw, updates)
      saveDrawPatterns()
    }
  }

  function removeDraw(patternId: string, drawId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern) return

    pattern.draws = pattern.draws.filter(d => d.id !== drawId)
    // Renumber draws
    pattern.draws.forEach((d, i) => { d.drawNumber = i + 1 })
    saveDrawPatterns()
  }

  function reorderDraws(patternId: string, fromIndex: number, toIndex: number) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern) return

    const [moved] = pattern.draws.splice(fromIndex, 1)
    if (moved) {
      pattern.draws.splice(toIndex, 0, moved)
      // Renumber draws
      pattern.draws.forEach((d, i) => { d.drawNumber = i + 1 })
    }
    saveDrawPatterns()
  }

  // Draw pattern execution
  function startDrawPattern(patternId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern || !pattern.enabled) {
      console.error('Draw pattern not found or disabled:', patternId)
      return
    }

    if (pattern.state === 'running') {
      console.warn('Draw pattern already running')
      return
    }

    // Reset all draws
    pattern.draws.forEach(d => {
      d.state = 'pending'
      d.volumeDispensed = 0
      d.elapsedTime = 0
      d.startVolume = undefined
      d.startTime = undefined
      d.endTime = undefined
      d.completedBy = undefined
    })

    pattern.state = 'running'
    pattern.currentDrawIndex = -1
    pattern.startTime = Date.now()
    pattern.totalVolumeDispensed = 0
    pattern.error = undefined
    activeDrawPatternId.value = patternId

    // Start tick loop
    startDrawPatternTickLoop()

    // Advance to first enabled draw
    advanceToNextDraw(pattern)

    saveDrawPatterns()
    addNotification('info', 'Draw Pattern Started', `Started "${pattern.name}"`)
    console.debug('Draw pattern started:', pattern.name)
  }

  function pauseDrawPattern(patternId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern || pattern.state !== 'running') return

    // Close current valve
    const currentDraw = pattern.draws[pattern.currentDrawIndex]
    if (currentDraw) {
      sendOutput(currentDraw.valve, false)
    }

    pattern.state = 'paused'
    pattern.pausedTime = Date.now()
    saveDrawPatterns()
    console.debug('Draw pattern paused')
  }

  function resumeDrawPattern(patternId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern || pattern.state !== 'paused') return

    pattern.state = 'running'
    pattern.pausedTime = undefined

    // Re-open current valve and reset flow reference
    const currentDraw = pattern.draws[pattern.currentDrawIndex]
    if (currentDraw) {
      sendOutput(currentDraw.valve, true)
      currentDraw.startVolume = getFlowTotalizer(pattern.flowChannel) ?? 0
    }

    saveDrawPatterns()
    console.debug('Draw pattern resumed')
  }

  function stopDrawPattern(patternId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern) return

    // Stop tick loop if this was the active pattern
    if (activeDrawPatternId.value === patternId) {
      stopDrawPatternTickLoop()
      activeDrawPatternId.value = null
    }

    // Close all valves
    pattern.draws.forEach(d => {
      sendOutput(d.valve, false)
    })

    // Record history
    if (pattern.startTime) {
      const historyEntry: DrawPatternRunHistory = {
        id: `dph-${Date.now()}`,
        patternId: pattern.id,
        patternName: pattern.name,
        startTime: pattern.startTime,
        endTime: Date.now(),
        state: pattern.state === 'completed' ? 'completed' : 'idle',
        cyclesCompleted: pattern.cycleCount,
        drawResults: pattern.draws.map(d => ({
          drawNumber: d.drawNumber,
          valve: d.valve,
          volumeDispensed: d.volumeDispensed,
          duration: d.elapsedTime,
          completedBy: d.completedBy || 'manual'
        })),
        totalVolumeDispensed: pattern.totalVolumeDispensed
      }
      drawPatternHistory.value.unshift(historyEntry)
    }

    pattern.state = 'idle'
    pattern.currentDrawIndex = -1
    pattern.startTime = undefined
    pattern.pausedTime = undefined
    pattern.lastRun = new Date().toISOString()
    pattern.runCount = (pattern.runCount || 0) + 1

    saveDrawPatterns()
    addNotification('info', 'Draw Pattern Stopped', `Stopped "${pattern.name}"`)
    console.debug('Draw pattern stopped')
  }

  function skipCurrentDraw(patternId: string) {
    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern || pattern.state !== 'running') return

    const currentDraw = pattern.draws[pattern.currentDrawIndex]
    if (currentDraw) {
      sendOutput(currentDraw.valve, false)
      currentDraw.state = 'skipped'
      currentDraw.endTime = Date.now()
      currentDraw.completedBy = 'manual'
    }

    advanceToNextDraw(pattern)
    saveDrawPatterns()
  }

  function advanceToNextDraw(pattern: DrawPattern) {
    let nextIndex = pattern.currentDrawIndex + 1

    // Find next enabled draw
    while (nextIndex < pattern.draws.length) {
      const draw = pattern.draws[nextIndex]
      if (draw && draw.enabled) break
      if (draw) draw.state = 'skipped'
      nextIndex++
    }

    if (nextIndex >= pattern.draws.length) {
      // Reached end of draws
      if (pattern.loopContinuously) {
        pattern.cycleCount++
        // Reset all draws and start over
        pattern.draws.forEach(d => {
          d.state = 'pending'
          d.volumeDispensed = 0
          d.elapsedTime = 0
          d.startVolume = undefined
          d.startTime = undefined
          d.endTime = undefined
          d.completedBy = undefined
        })
        pattern.currentDrawIndex = -1
        advanceToNextDraw(pattern)
      } else {
        // Pattern complete
        pattern.state = 'completed'
        stopDrawPattern(pattern.id)
        addNotification('success', 'Draw Pattern Complete', `"${pattern.name}" completed successfully`)
      }
      return
    }

    pattern.currentDrawIndex = nextIndex
    const nextDraw = pattern.draws[nextIndex]
    if (nextDraw) {
      openDraw(pattern, nextDraw)
    }
  }

  function openDraw(pattern: DrawPattern, draw: Draw) {
    draw.state = 'active'
    draw.startVolume = getFlowTotalizer(pattern.flowChannel) ?? 0
    draw.volumeDispensed = 0
    draw.elapsedTime = 0
    draw.startTime = Date.now()

    sendOutput(draw.valve, true)
    console.debug(`Opened draw #${draw.drawNumber}: ${draw.valve} (target: ${draw.volumeTarget} ${draw.volumeUnit})`)
  }

  function closeDraw(pattern: DrawPattern, draw: Draw, reason: 'volume' | 'timeout') {
    sendOutput(draw.valve, false)
    draw.state = 'completed'
    draw.endTime = Date.now()
    draw.completedBy = reason

    // Update total volume
    pattern.totalVolumeDispensed += draw.volumeDispensed

    console.debug(`Closed draw #${draw.drawNumber}: ${draw.valve} (dispensed: ${draw.volumeDispensed.toFixed(2)} ${draw.volumeUnit}, reason: ${reason})`)

    // Delay before next draw
    if (pattern.delayBetweenDraws > 0) {
      setTimeout(() => {
        if (pattern.state === 'running') {
          advanceToNextDraw(pattern)
          saveDrawPatterns()
        }
      }, pattern.delayBetweenDraws * 1000)
    } else {
      advanceToNextDraw(pattern)
    }
  }

  function getFlowTotalizer(channel: string): number | null {
    const value = store.values[channel]
    if (value && typeof value.value === 'number') {
      return value.value
    }
    return null
  }

  // Execute a single standalone draw (for sequence steps and schedule actions)
  // Returns a promise that resolves when draw completes
  function executeSingleDraw(
    valve: string,
    flowChannel: string,
    volumeTarget: number,
    volumeUnit: string,
    maxDuration: number
  ): Promise<{ success: boolean; volumeDispensed: number; completedBy: 'volume' | 'timeout' | 'error' }> {
    return new Promise((resolve) => {
      const startVolume = getFlowTotalizer(flowChannel) ?? 0
      let elapsedTime = 0
      let volumeDispensed = 0

      // Open valve
      sendOutput(valve, true)
      console.debug(`Single draw started: ${valve} (target: ${volumeTarget} ${volumeUnit})`)

      const tickInterval = window.setInterval(() => {
        elapsedTime++

        // Update volume
        const currentTotal = getFlowTotalizer(flowChannel)
        if (currentTotal !== null) {
          volumeDispensed = currentTotal - startVolume
        }

        // Check completion
        if (volumeDispensed >= volumeTarget) {
          clearInterval(tickInterval)
          sendOutput(valve, false)
          console.debug(`Single draw completed by volume: ${volumeDispensed.toFixed(2)} ${volumeUnit}`)
          resolve({ success: true, volumeDispensed, completedBy: 'volume' })
        } else if (elapsedTime >= maxDuration) {
          clearInterval(tickInterval)
          sendOutput(valve, false)
          console.debug(`Single draw completed by timeout: ${volumeDispensed.toFixed(2)} ${volumeUnit}`)
          resolve({ success: true, volumeDispensed, completedBy: 'timeout' })
        }
      }, 1000)
    })
  }

  function drawPatternTick() {
    const patternId = activeDrawPatternId.value
    if (!patternId) return

    const pattern = drawPatterns.value.find(p => p.id === patternId)
    if (!pattern || pattern.state !== 'running') return

    const draw = pattern.draws[pattern.currentDrawIndex]
    if (!draw || draw.state !== 'active') return

    // Update elapsed time
    draw.elapsedTime++

    // Update volume dispensed
    const currentTotal = getFlowTotalizer(pattern.flowChannel)
    if (currentTotal !== null && draw.startVolume !== undefined) {
      draw.volumeDispensed = currentTotal - draw.startVolume
    }

    // Check completion conditions
    if (draw.volumeDispensed >= draw.volumeTarget) {
      closeDraw(pattern, draw, 'volume')
    } else if (draw.elapsedTime >= draw.maxDuration) {
      closeDraw(pattern, draw, 'timeout')
    }

    // Periodic save (every 10 seconds)
    if (draw.elapsedTime % 10 === 0) {
      saveDrawPatterns()
    }
  }

  function startDrawPatternTickLoop() {
    if (drawPatternTickIntervalId !== null) return
    drawPatternTickIntervalId = window.setInterval(drawPatternTick, 1000)
  }

  function stopDrawPatternTickLoop() {
    if (drawPatternTickIntervalId !== null) {
      clearInterval(drawPatternTickIntervalId)
      drawPatternTickIntervalId = null
    }
  }

  // Computed for draw patterns
  const activeDrawPattern = computed(() => {
    if (!activeDrawPatternId.value) return null
    return drawPatterns.value.find(p => p.id === activeDrawPatternId.value) || null
  })

  const isDrawPatternRunning = computed(() => activeDrawPattern.value?.state === 'running')
  const isDrawPatternPaused = computed(() => activeDrawPattern.value?.state === 'paused')

  const currentDraw = computed(() => {
    const pattern = activeDrawPattern.value
    if (!pattern || pattern.currentDrawIndex < 0) return null
    return pattern.draws[pattern.currentDrawIndex] || null
  })

  const enabledDrawPatterns = computed(() => drawPatterns.value.filter(p => p.enabled))

  function evaluateTriggers() {
    const now = Date.now()

    triggers.value.forEach(trigger => {
      if (!trigger.enabled) return

      try {
        if (trigger.lastTriggered && trigger.cooldownMs > 0) {
          if (now - trigger.lastTriggered < trigger.cooldownMs) return
        }

        let shouldTrigger = false

        switch (trigger.trigger?.type) {
          case 'valueReached':
            shouldTrigger = evaluateValueReachedTrigger(trigger)
            break
          case 'scheduled':
            shouldTrigger = evaluateScheduledTrigger(trigger)
            break
          case 'stateChange':
            shouldTrigger = evaluateStateChangeTrigger(trigger)
            break
          case 'sequenceEvent':
            // Handled by emitSequenceEvent
            break
        }

        if (shouldTrigger) {
          executeTriggerActions(trigger)
          trigger.lastTriggered = now

          if (trigger.oneShot) {
            trigger.enabled = false
            saveTriggers()
          }
        }
      } catch (e) {
        console.error('Error evaluating trigger:', trigger.name, e)
      }
    })
  }

  function evaluateValueReachedTrigger(trigger: AutomationTrigger): boolean {
    const t = trigger.trigger as ValueReachedTrigger
    if (!t?.channel) return false

    const value = store.values[t.channel]?.value
    if (value === undefined) return false

    switch (t.operator) {
      case '>': return value > t.value
      case '<': return value < t.value
      case '>=': return value >= t.value
      case '<=': return value <= t.value
      case '==': return value === t.value
      case '!=': return value !== t.value
      default: return false
    }
  }

  function evaluateScheduledTrigger(trigger: AutomationTrigger): boolean {
    const t = trigger.trigger as ScheduledTrigger
    if (!t?.schedule) return false

    const now = new Date()
    const currentTime = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`
    const currentDay = now.getDay()

    switch (t.schedule.type) {
      case 'once':
        if (t.schedule.date) {
          const scheduleDate = new Date(t.schedule.date + 'T' + t.schedule.time)
          const diffMs = Math.abs(now.getTime() - scheduleDate.getTime())
          return diffMs < 60000 // Within 1 minute
        }
        return false

      case 'daily':
        return currentTime === t.schedule.time

      case 'weekly':
        if (!t.schedule.daysOfWeek?.includes(currentDay)) return false
        return currentTime === t.schedule.time

      default:
        return false
    }
  }

  function evaluateStateChangeTrigger(trigger: AutomationTrigger): boolean {
    const t = trigger.trigger as StateChangeTrigger
    if (!t?.stateType) return false

    const status = store.status
    if (!status) return false

    let currentState: string | undefined
    let prevState: boolean | undefined

    switch (t.stateType) {
      case 'acquisition':
        currentState = status.acquiring ? 'running' : 'stopped'
        prevState = previousAcquiring
        previousAcquiring = status.acquiring
        if (prevState === undefined) return false
        break

      case 'recording':
        currentState = status.recording ? 'running' : 'stopped'
        prevState = previousRecording
        previousRecording = status.recording
        if (prevState === undefined) return false
        break

      case 'scheduler':
        currentState = status.scheduler_enabled ? 'enabled' : 'disabled'
        prevState = previousSchedulerEnabled
        previousSchedulerEnabled = status.scheduler_enabled
        if (prevState === undefined) return false
        break

      default:
        return false
    }

    if (t.fromState && t.fromState !== (prevState ? 'running' : 'stopped')) return false
    return currentState === t.toState
  }

  function executeTriggerActions(trigger: AutomationTrigger) {
    if (!trigger.actions?.length) return

    addNotification('info', 'Trigger Fired', `Trigger activated: ${trigger.name}`)

    trigger.actions.forEach(action => {
      try {
        switch (action.type) {
          case 'startSequence':
            if (action.sequenceId) startSequence(action.sequenceId)
            break
          case 'stopSequence':
            if (runningSequenceId.value) abortSequence(runningSequenceId.value)
            break
          case 'setOutput':
            if (action.channel && action.value !== undefined) {
              sendOutput(action.channel, action.value as number | boolean)
            }
            break
          case 'startRecording':
            if (mqttStartRecording) {
              mqttStartRecording()
              addNotification('info', 'Recording Started', 'Recording started by trigger')
            }
            break
          case 'stopRecording':
            if (mqttStopRecording) {
              mqttStopRecording()
              addNotification('info', 'Recording Stopped', 'Recording stopped by trigger')
            }
            break
          case 'notification':
            addNotification('info', trigger.name, action.message || '')
            break
          case 'runFormula':
            if (action.formula) evaluateFormula(action.formula)
            break
        }
      } catch (e) {
        console.error('Error executing trigger action:', e)
      }
    })
  }

  // ========================================================================
  // FUNCTION BLOCKS
  // ========================================================================

  function loadFunctionBlocks() {
    try {
      const stored = localStorage.getItem(FUNCTION_BLOCKS_STORAGE_KEY)
      if (stored) {
        functionBlocks.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load function blocks:', e)
    }
  }

  function saveFunctionBlocks() {
    try {
      localStorage.setItem(FUNCTION_BLOCKS_STORAGE_KEY, JSON.stringify(functionBlocks.value))
    } catch (e) {
      console.error('Failed to save function blocks:', e)
    }
  }

  function createFunctionBlockFromTemplate(templateId: string, displayName: string): string | null {
    const template = FUNCTION_BLOCK_TEMPLATES.find(t => t.id === templateId)
    if (!template) return null

    const block: FunctionBlock = {
      id: `fb-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: templateId,
      displayName,
      description: template.description,
      category: template.category,
      templateId: template.id,
      enabled: true,
      inputs: template.inputs.map(i => ({ ...i, binding: i.defaultValue?.toString() })),
      outputs: template.outputs.map(o => ({ ...o, value: null, error: null })),
      state: template.initialState ? { ...template.initialState } : {},
      priority: functionBlocks.value.length,
      createdAt: new Date().toISOString(),
      modifiedAt: new Date().toISOString(),
    }

    functionBlocks.value.push(block)
    saveFunctionBlocks()
    return block.id
  }

  function updateFunctionBlock(id: string, updates: Partial<FunctionBlock>) {
    const index = functionBlocks.value.findIndex(b => b.id === id)
    if (index >= 0) {
      const existing = functionBlocks.value[index]!
      functionBlocks.value[index] = {
        ...existing,
        ...updates,
        modifiedAt: new Date().toISOString()
      } as FunctionBlock
      saveFunctionBlocks()
    }
  }

  function deleteFunctionBlock(id: string) {
    functionBlocks.value = functionBlocks.value.filter(b => b.id !== id)
    saveFunctionBlocks()
  }

  function updateFunctionBlockInput(blockId: string, inputName: string, binding: string) {
    const block = functionBlocks.value.find(b => b.id === blockId)
    if (block) {
      const input = block.inputs.find(i => i.name === inputName)
      if (input) {
        input.binding = binding
        block.modifiedAt = new Date().toISOString()
        saveFunctionBlocks()
      }
    }
  }

  function resetFunctionBlockState(blockId: string) {
    const block = functionBlocks.value.find(b => b.id === blockId)
    if (!block) return

    const template = FUNCTION_BLOCK_TEMPLATES.find(t => t.id === block.templateId)
    if (template?.initialState) {
      block.state = { ...template.initialState }
    } else {
      block.state = {}
    }
    saveFunctionBlocks()
  }

  function getInputValue(block: FunctionBlock, inputName: string): number | null {
    const input = block.inputs.find(i => i.name === inputName)
    if (!input || !input.binding) {
      return input?.defaultValue as number ?? null
    }

    // Check if binding is a number constant
    const numValue = parseFloat(input.binding)
    if (!isNaN(numValue)) {
      return numValue
    }

    // Check if binding is a boolean
    if (input.binding === 'true') return 1
    if (input.binding === 'false') return 0

    // Check if binding is another block's output (format: blockId.outputName)
    if (input.binding.includes('.')) {
      const [blockId, outputName] = input.binding.split('.')
      const sourceBlock = functionBlocks.value.find(b => b.id === blockId)
      if (sourceBlock) {
        const output = sourceBlock.outputs.find(o => o.name === outputName)
        if (output && output.value !== null) return output.value
      }
    }

    // Check if binding is a channel name
    const channelData = store.values[input.binding]
    if (channelData) {
      return channelData.value
    }

    // Check if binding is a calculated param
    const param = calculatedParams.value.find(p => p.name === input.binding)
    if (param && param.lastValue !== null) {
      return param.lastValue
    }

    return null
  }

  function setOutputValue(block: FunctionBlock, outputName: string, value: number | null, error: string | null = null) {
    const output = block.outputs.find(o => o.name === outputName)
    if (output) {
      output.value = value
      output.error = error
    }
  }

  function evaluateFunctionBlocks() {
    // Sort by priority for correct evaluation order
    const sortedBlocks = [...functionBlocks.value].sort((a, b) => a.priority - b.priority)

    for (const block of sortedBlocks) {
      if (!block.enabled) continue

      try {
        evaluateSingleBlock(block)
      } catch (e: any) {
        // Set all outputs to error state
        block.outputs.forEach(o => {
          o.value = null
          o.error = e.message
        })
      }
    }
  }

  function evaluateSingleBlock(block: FunctionBlock) {
    const template = FUNCTION_BLOCK_TEMPLATES.find(t => t.id === block.templateId)

    // If template has a custom evaluator, use it
    if (template?.evaluator) {
      evaluateWithCustomEvaluator(block, template.evaluator)
      return
    }

    // Otherwise, evaluate outputs using their formulas
    for (const output of block.outputs) {
      if (output.formula) {
        const result = evaluateBlockFormula(block, output.formula)
        output.value = result.value
        output.error = result.error
      }
    }
  }

  function evaluateBlockFormula(block: FunctionBlock, formula: string): { value: number | null; error: string | null } {
    const safetyError = validateFormulaSafety(formula)
    if (safetyError) {
      return { value: null, error: safetyError }
    }

    try {
      // Build context with input values
      const inputs: Record<string, number> = {}
      for (const input of block.inputs) {
        const val = getInputValue(block, input.name)
        if (val !== null) {
          inputs[input.name] = val
        }
      }

      // Build the function
      const inputNames = Object.keys(inputs)
      const inputValues = Object.values(inputs)

      const mathFuncs = {
        abs: Math.abs, sqrt: Math.sqrt, pow: Math.pow, log: Math.log, log10: Math.log10,
        exp: Math.exp, sin: Math.sin, cos: Math.cos, tan: Math.tan, min: Math.min, max: Math.max,
        floor: Math.floor, ceil: Math.ceil, round: Math.round, PI: Math.PI, E: Math.E
      }

      const evalFunc = new Function(...inputNames, ...Object.keys(mathFuncs), `return ${formula}`)
      const result = evalFunc(...inputValues, ...Object.values(mathFuncs))

      if (typeof result === 'number' && !isNaN(result) && isFinite(result)) {
        return { value: result, error: null }
      }
      return { value: null, error: 'Invalid result' }
    } catch (e: any) {
      return { value: null, error: e.message }
    }
  }

  function evaluateWithCustomEvaluator(block: FunctionBlock, evaluatorName: string) {
    const now = Date.now()

    switch (evaluatorName) {
      case 'pid': {
        const setpoint = getInputValue(block, 'setpoint') ?? 0
        const pv = getInputValue(block, 'pv')
        const kp = getInputValue(block, 'kp') ?? 1
        const ki = getInputValue(block, 'ki') ?? 0
        const kd = getInputValue(block, 'kd') ?? 0
        const outMin = getInputValue(block, 'outMin') ?? 0
        const outMax = getInputValue(block, 'outMax') ?? 100

        if (pv === null) {
          setOutputValue(block, 'output', null, 'No PV')
          return
        }

        const error = setpoint - pv
        const dt = block.state.lastTime ? (now - block.state.lastTime) / 1000 : 0.5

        // P term
        const pTerm = kp * error

        // I term with anti-windup
        let integral = (block.state.integral ?? 0) + error * dt
        let iTerm = ki * integral

        // D term
        const dError = dt > 0 ? (error - (block.state.lastError ?? error)) / dt : 0
        const dTerm = kd * dError

        // Calculate output
        let output = pTerm + iTerm + dTerm

        // Anti-windup: clamp integral if output is saturated
        if (output > outMax) {
          output = outMax
          if (ki > 0) integral = (outMax - pTerm - dTerm) / ki
        } else if (output < outMin) {
          output = outMin
          if (ki > 0) integral = (outMin - pTerm - dTerm) / ki
        }

        // Update state
        block.state.integral = integral
        block.state.lastError = error
        block.state.lastTime = now

        setOutputValue(block, 'output', output)
        setOutputValue(block, 'error', error)
        setOutputValue(block, 'pTerm', pTerm)
        setOutputValue(block, 'iTerm', ki * integral)
        setOutputValue(block, 'dTerm', dTerm)
        break
      }

      case 'onoff': {
        const setpoint = getInputValue(block, 'setpoint') ?? 0
        const pv = getInputValue(block, 'pv')
        const hysteresis = getInputValue(block, 'hysteresis') ?? 0

        if (pv === null) {
          setOutputValue(block, 'output', null, 'No PV')
          return
        }

        const error = setpoint - pv
        const lastOutput = block.state.lastOutput ?? 0

        let output: number
        if (lastOutput === 1) {
          output = pv > setpoint + hysteresis / 2 ? 0 : 1
        } else {
          output = pv < setpoint - hysteresis / 2 ? 1 : 0
        }

        block.state.lastOutput = output
        setOutputValue(block, 'output', output)
        setOutputValue(block, 'error', error)
        break
      }

      case 'ramp': {
        const startValue = getInputValue(block, 'startValue') ?? 0
        const targetValue = getInputValue(block, 'targetValue') ?? 100
        const rampRate = getInputValue(block, 'rampRate') ?? 10
        const enable = getInputValue(block, 'enable') ?? 0

        if (enable && !block.state.isRunning) {
          block.state.isRunning = true
          block.state.startTime = now
          block.state.currentValue = startValue
        } else if (!enable && block.state.isRunning) {
          block.state.isRunning = false
        }

        if (block.state.isRunning) {
          const elapsedMin = (now - block.state.startTime) / 60000
          const direction = targetValue > startValue ? 1 : -1
          const change = rampRate * elapsedMin * direction
          let currentValue = startValue + change

          if ((direction > 0 && currentValue >= targetValue) ||
              (direction < 0 && currentValue <= targetValue)) {
            currentValue = targetValue
          }

          block.state.currentValue = currentValue
        }

        const current = block.state.currentValue ?? startValue
        const totalRange = Math.abs(targetValue - startValue)
        const progress = totalRange > 0 ? Math.abs(current - startValue) / totalRange * 100 : 100
        const complete = current === targetValue ? 1 : 0

        setOutputValue(block, 'output', current)
        setOutputValue(block, 'complete', complete)
        setOutputValue(block, 'progress', Math.min(100, progress))
        break
      }

      case 'average4': {
        const values: number[] = []
        for (const name of ['a', 'b', 'c', 'd']) {
          const v = getInputValue(block, name)
          if (v !== null) values.push(v)
        }

        if (values.length === 0) {
          block.outputs.forEach(o => setOutputValue(block, o.name, null, 'No inputs'))
          return
        }

        const avg = values.reduce((a, b) => a + b, 0) / values.length
        setOutputValue(block, 'avg', avg)
        setOutputValue(block, 'min', Math.min(...values))
        setOutputValue(block, 'max', Math.max(...values))
        setOutputValue(block, 'range', Math.max(...values) - Math.min(...values))
        break
      }

      case 'clamp': {
        const input = getInputValue(block, 'input')
        const min = getInputValue(block, 'min') ?? 0
        const max = getInputValue(block, 'max') ?? 100

        if (input === null) {
          setOutputValue(block, 'output', null, 'No input')
          return
        }

        const clamped = Math.max(min, Math.min(max, input))
        setOutputValue(block, 'output', clamped)
        setOutputValue(block, 'limited', input !== clamped ? 1 : 0)
        break
      }

      case 'deadband': {
        const input = getInputValue(block, 'input')
        const deadband = getInputValue(block, 'deadband') ?? 1

        if (input === null) {
          setOutputValue(block, 'output', null, 'No input')
          return
        }

        const lastOutput = block.state.lastOutput
        let output: number, changed: number

        if (lastOutput === null || Math.abs(input - lastOutput) >= deadband) {
          output = input
          changed = 1
          block.state.lastOutput = input
        } else {
          output = lastOutput
          changed = 0
        }

        setOutputValue(block, 'output', output)
        setOutputValue(block, 'changed', changed)
        break
      }

      case 'movingAvg': {
        const input = getInputValue(block, 'input')
        const samples = Math.floor(getInputValue(block, 'samples') ?? 10)

        if (input === null) {
          setOutputValue(block, 'output', null, 'No input')
          return
        }

        const buffer: number[] = block.state.buffer ?? []
        buffer.push(input)
        while (buffer.length > samples) buffer.shift()
        block.state.buffer = buffer

        const avg = buffer.reduce((a, b) => a + b, 0) / buffer.length
        const variance = buffer.reduce((acc, v) => acc + Math.pow(v - avg, 2), 0) / buffer.length

        setOutputValue(block, 'output', avg)
        setOutputValue(block, 'stddev', Math.sqrt(variance))
        break
      }

      case 'lowpass': {
        const input = getInputValue(block, 'input')
        const alpha = getInputValue(block, 'alpha') ?? 0.1

        if (input === null) {
          setOutputValue(block, 'output', null, 'No input')
          return
        }

        const lastOutput = block.state.lastOutput ?? input
        const output = alpha * input + (1 - alpha) * lastOutput
        block.state.lastOutput = output

        setOutputValue(block, 'output', output)
        break
      }

      case 'rateOfChange': {
        const input = getInputValue(block, 'input')

        if (input === null) {
          setOutputValue(block, 'rate', null, 'No input')
          setOutputValue(block, 'ratePerSec', null, 'No input')
          return
        }

        const lastValue = block.state.lastValue
        const lastTime = block.state.lastTime ?? now

        block.state.lastValue = input
        block.state.lastTime = now

        if (lastValue === null) {
          setOutputValue(block, 'rate', 0)
          setOutputValue(block, 'ratePerSec', 0)
          return
        }

        const dtSec = (now - lastTime) / 1000
        const ratePerSec = dtSec > 0 ? (input - lastValue) / dtSec : 0

        setOutputValue(block, 'rate', ratePerSec * 60)
        setOutputValue(block, 'ratePerSec', ratePerSec)
        break
      }

      case 'minMaxTracker': {
        const input = getInputValue(block, 'input')
        const reset = getInputValue(block, 'reset') ?? 0

        if (reset) {
          block.state.min = null
          block.state.max = null
        }

        if (input === null) {
          setOutputValue(block, 'current', null, 'No input')
          return
        }

        if (block.state.min === null || input < block.state.min) block.state.min = input
        if (block.state.max === null || input > block.state.max) block.state.max = input

        setOutputValue(block, 'current', input)
        setOutputValue(block, 'min', block.state.min)
        setOutputValue(block, 'max', block.state.max)
        setOutputValue(block, 'range', block.state.max - block.state.min)
        break
      }

      case 'accumulator': {
        const input = getInputValue(block, 'input')
        const reset = getInputValue(block, 'reset') ?? 0
        const scale = getInputValue(block, 'scale') ?? 1

        if (reset) {
          block.state.total = 0
          block.state.count = 0
        }

        if (input !== null) {
          block.state.total = (block.state.total ?? 0) + input * scale
          block.state.count = (block.state.count ?? 0) + 1
        }

        setOutputValue(block, 'total', block.state.total ?? 0)
        setOutputValue(block, 'count', block.state.count ?? 0)
        setOutputValue(block, 'average', block.state.count > 0 ? block.state.total / block.state.count : 0)
        break
      }

      case 'tempUniformity': {
        const values: number[] = []
        for (const name of ['zone1', 'zone2', 'zone3', 'zone4']) {
          const v = getInputValue(block, name)
          if (v !== null) values.push(v)
        }

        if (values.length < 2) {
          block.outputs.forEach(o => setOutputValue(block, o.name, null, 'Need 2+ zones'))
          return
        }

        const avg = values.reduce((a, b) => a + b, 0) / values.length
        const min = Math.min(...values)
        const max = Math.max(...values)

        setOutputValue(block, 'average', avg)
        setOutputValue(block, 'uniformity', Math.max(Math.abs(max - avg), Math.abs(min - avg)))
        setOutputValue(block, 'min', min)
        setOutputValue(block, 'max', max)
        setOutputValue(block, 'spread', max - min)
        break
      }

      case 'heatRate': {
        const temp = getInputValue(block, 'temperature')
        const windowSec = getInputValue(block, 'windowSec') ?? 60

        if (temp === null) {
          setOutputValue(block, 'ratePerMin', null, 'No input')
          return
        }

        const samples: Array<{ value: number; time: number }> = block.state.samples ?? []
        samples.push({ value: temp, time: now })

        const cutoff = now - windowSec * 1000
        while (samples.length > 0 && samples[0]!.time < cutoff) samples.shift()
        block.state.samples = samples

        if (samples.length < 2) {
          setOutputValue(block, 'ratePerMin', 0)
          setOutputValue(block, 'ratePerHour', 0)
          setOutputValue(block, 'isHeating', 0)
          return
        }

        const first = samples[0]!
        const last = samples[samples.length - 1]!
        const dtMin = (last.time - first.time) / 60000
        const ratePerMin = dtMin > 0 ? (last.value - first.value) / dtMin : 0

        setOutputValue(block, 'ratePerMin', ratePerMin)
        setOutputValue(block, 'ratePerHour', ratePerMin * 60)
        setOutputValue(block, 'isHeating', ratePerMin > 0 ? 1 : 0)
        break
      }

      case 'compare': {
        const input = getInputValue(block, 'input')
        const threshold = getInputValue(block, 'threshold') ?? 0
        const hysteresis = getInputValue(block, 'hysteresis') ?? 0

        if (input === null) {
          setOutputValue(block, 'above', null, 'No input')
          return
        }

        const deviation = input - threshold
        setOutputValue(block, 'above', deviation > hysteresis / 2 ? 1 : 0)
        setOutputValue(block, 'below', deviation < -hysteresis / 2 ? 1 : 0)
        setOutputValue(block, 'equal', Math.abs(deviation) <= hysteresis / 2 ? 1 : 0)
        setOutputValue(block, 'deviation', deviation)
        break
      }

      case 'select': {
        const condition = getInputValue(block, 'condition')
        const inputA = getInputValue(block, 'inputA')
        const inputB = getInputValue(block, 'inputB')

        const selected = condition && condition !== 0 ? 1 : 0
        setOutputValue(block, 'output', selected ? inputB : inputA)
        setOutputValue(block, 'selected', selected)
        break
      }

      case 'timer': {
        const condition = getInputValue(block, 'condition')
        const reset = getInputValue(block, 'reset') ?? 0

        if (reset) {
          block.state.startTime = null
          block.state.accumulatedTime = 0
          block.state.wasRunning = false
        }

        const isRunning = condition && condition !== 0

        if (isRunning && !block.state.wasRunning) {
          block.state.startTime = now
        } else if (!isRunning && block.state.wasRunning) {
          if (block.state.startTime) {
            block.state.accumulatedTime = (block.state.accumulatedTime ?? 0) + (now - block.state.startTime)
          }
          block.state.startTime = null
        }

        block.state.wasRunning = isRunning

        let totalMs = block.state.accumulatedTime ?? 0
        if (isRunning && block.state.startTime) {
          totalMs += now - block.state.startTime
        }

        const seconds = totalMs / 1000
        setOutputValue(block, 'seconds', seconds)
        setOutputValue(block, 'minutes', seconds / 60)
        setOutputValue(block, 'hours', seconds / 3600)
        setOutputValue(block, 'isRunning', isRunning ? 1 : 0)
        break
      }

      case 'pulseCounter': {
        const input = getInputValue(block, 'input')
        const threshold = getInputValue(block, 'threshold') ?? 0.5
        const reset = getInputValue(block, 'reset') ?? 0

        if (reset) {
          block.state.count = 0
          block.state.lastState = false
        }

        const currentState = input !== null && input > threshold
        if (currentState && !block.state.lastState) {
          block.state.count = (block.state.count ?? 0) + 1
        }
        block.state.lastState = currentState

        setOutputValue(block, 'count', block.state.count ?? 0)
        setOutputValue(block, 'state', currentState ? 1 : 0)
        break
      }

      default:
        console.warn(`Unknown evaluator: ${evaluatorName}`)
    }
  }

  function getFunctionBlockOutputs(): Record<string, number> {
    const outputs: Record<string, number> = {}
    for (const block of functionBlocks.value) {
      if (!block.enabled) continue
      for (const output of block.outputs) {
        if (output.value !== null) {
          outputs[`fb_${block.displayName.replace(/\s+/g, '_')}_${output.name}`] = output.value
        }
      }
    }
    return outputs
  }

  const enabledFunctionBlocks = computed(() =>
    functionBlocks.value.filter(b => b.enabled)
  )

  // ========================================================================
  // SCRIPT VALUES FOR RECORDING
  // ========================================================================

  function getScriptValues(): Record<string, number> {
    const values: Record<string, number> = {}

    // Add calculated params
    calculatedParams.value.forEach(p => {
      if (p.enabled && p.lastValue !== null) {
        values[`calc_${p.name}`] = p.lastValue
      }
    })

    // Add transformations
    transformations.value.forEach(t => {
      if (t.enabled && t.lastValue !== null) {
        values[`transform_${t.name}`] = t.lastValue
      }
    })

    // Add function block outputs
    Object.assign(values, getFunctionBlockOutputs())

    return values
  }

  function sendScriptValuesToRecording() {
    if (mqttSendScriptValues) {
      const values = getScriptValues()
      if (Object.keys(values).length > 0) {
        mqttSendScriptValues(values)
      }
    }
  }

  // ========================================================================
  // WATCHDOGS
  // ========================================================================

  function loadWatchdogs() {
    try {
      const stored = localStorage.getItem('dcflux-watchdogs')
      if (stored) {
        const parsed = JSON.parse(stored)
        watchdogs.value = parsed.map((wd: Watchdog) => ({
          ...wd,
          isTriggered: wd.isTriggered || false,
          triggeredChannels: wd.triggeredChannels || []
        }))
      }
    } catch (e) {
      console.error('Failed to load watchdogs:', e)
    }
  }

  function saveWatchdogs() {
    try {
      localStorage.setItem('dcflux-watchdogs', JSON.stringify(watchdogs.value))
    } catch (e) {
      console.error('Failed to save watchdogs:', e)
    }
  }

  function evaluateWatchdogs() {
    const now = Date.now()

    // Update channel timestamps from current values
    Object.entries(store.values).forEach(([channelName, data]) => {
      if (data && typeof data.value === 'number') {
        const prevValue = watchdogPreviousValues.value[channelName]

        // Update timestamp
        watchdogChannelTimestamps.value[channelName] = data.timestamp || now

        // Track value changes for stuck detection
        if (prevValue === undefined || Math.abs(data.value - prevValue) > 0.0001) {
          watchdogValueChangeTimestamps.value[channelName] = now
        }
        watchdogPreviousValues.value[channelName] = data.value

        // Update rate history (keep last 60 seconds of data)
        if (!watchdogRateHistory.value[channelName]) {
          watchdogRateHistory.value[channelName] = []
        }
        watchdogRateHistory.value[channelName].push({ value: data.value, timestamp: now })
        // Trim to last 60 seconds
        const cutoff = now - 60000
        watchdogRateHistory.value[channelName] = watchdogRateHistory.value[channelName].filter(
          entry => entry.timestamp > cutoff
        )
      }
    })

    // Evaluate each watchdog
    watchdogs.value.forEach(wd => {
      if (!wd.enabled) return
      if (wd.channels.length === 0) return

      // Check cooldown
      if (wd.lastTriggered && now - wd.lastTriggered < wd.cooldownMs) {
        return
      }

      const triggeredChannels: string[] = []
      let conditionMet = false

      // Check each monitored channel
      for (const channelName of wd.channels) {
        const channelData = store.values[channelName]
        if (!channelData) continue

        const isTriggered = evaluateWatchdogCondition(wd.condition, channelName, channelData.value, now)
        if (isTriggered) {
          conditionMet = true
          triggeredChannels.push(channelName)
        }
      }

      // Handle state transitions
      if (conditionMet && !wd.isTriggered) {
        // Trigger the watchdog
        wd.isTriggered = true
        wd.triggeredAt = now
        wd.triggeredChannels = triggeredChannels
        wd.lastTriggered = now
        saveWatchdogs()

        // Execute trigger actions
        executeWatchdogActions(wd, triggeredChannels)

      } else if (!conditionMet && wd.isTriggered && wd.autoRecover) {
        // Auto-recover
        wd.isTriggered = false
        wd.triggeredAt = undefined
        wd.triggeredChannels = []
        saveWatchdogs()

        // Execute recovery actions
        if (wd.recoveryActions && wd.recoveryActions.length > 0) {
          executeWatchdogRecoveryActions(wd)
        } else {
          addNotification('success', 'Watchdog Recovered', `"${wd.name}" condition cleared`)
        }
      }
    })
  }

  function evaluateWatchdogCondition(
    condition: Watchdog['condition'],
    channelName: string,
    value: number,
    now: number
  ): boolean {
    switch (condition.type) {
      case 'stale_data': {
        const lastUpdate = watchdogChannelTimestamps.value[channelName]
        if (!lastUpdate) return false
        const maxStaleMs = condition.maxStaleMs || 5000
        return (now - lastUpdate) > maxStaleMs
      }

      case 'out_of_range': {
        const minValue = condition.minValue
        const maxValue = condition.maxValue
        if (minValue !== undefined && value < minValue) return true
        if (maxValue !== undefined && value > maxValue) return true
        return false
      }

      case 'rate_exceeded': {
        const maxRate = condition.maxRatePerMin
        if (maxRate === undefined) return false

        const history = watchdogRateHistory.value[channelName]
        if (!history || history.length < 2) return false

        // Calculate rate over last 10 seconds
        const recentEntries = history.filter(e => e.timestamp > now - 10000)
        if (recentEntries.length < 2) return false

        const first = recentEntries[0]
        const last = recentEntries[recentEntries.length - 1]
        if (!first || !last) return false

        const deltaValue = Math.abs(last.value - first.value)
        const deltaTimeMin = (last.timestamp - first.timestamp) / 60000

        if (deltaTimeMin <= 0) return false
        const ratePerMin = deltaValue / deltaTimeMin

        return ratePerMin > maxRate
      }

      case 'stuck_value': {
        const stuckDurationMs = condition.stuckDurationMs || 60000
        const lastChange = watchdogValueChangeTimestamps.value[channelName]
        if (!lastChange) return false
        return (now - lastChange) > stuckDurationMs
      }

      default:
        return false
    }
  }

  function executeWatchdogActions(wd: Watchdog, triggeredChannels: string[]) {
    const message = `Watchdog "${wd.name}" triggered on: ${triggeredChannels.join(', ')}`

    wd.actions.forEach(action => {
      switch (action.type) {
        case 'notification':
          addNotification('warning', 'Watchdog Alert', action.message || message)
          break

        case 'alarm':
          addNotification(
            action.alarmSeverity === 'critical' ? 'error' :
            action.alarmSeverity === 'warning' ? 'warning' : 'info',
            'Watchdog Alarm',
            action.message || message
          )
          break

        case 'setOutput':
          if (action.channel && mqttSetOutput) {
            mqttSetOutput(action.channel, action.value ?? 0)
          }
          break

        case 'stopSequence':
          if (runningSequenceId.value) {
            abortSequence(runningSequenceId.value)
          }
          break

        case 'stopRecording':
          if (mqttStopRecording) {
            mqttStopRecording()
          }
          break

        case 'runSequence':
          if (action.sequenceId) {
            startSequence(action.sequenceId)
          }
          break
      }
    })
  }

  function executeWatchdogRecoveryActions(wd: Watchdog) {
    addNotification('success', 'Watchdog Recovered', `"${wd.name}" condition cleared`)

    if (wd.recoveryActions) {
      wd.recoveryActions.forEach(action => {
        switch (action.type) {
          case 'notification':
            addNotification('success', 'Watchdog Recovery', action.message || `${wd.name} recovered`)
            break

          case 'setOutput':
            if (action.channel && mqttSetOutput) {
              mqttSetOutput(action.channel, action.value ?? 0)
            }
            break

          case 'runSequence':
            if (action.sequenceId) {
              startSequence(action.sequenceId)
            }
            break
        }
      })
    }
  }

  // ========================================================================
  // EVALUATION LOOP
  // ========================================================================

  function startEvaluation() {
    if (evaluationIntervalId) return

    evaluationIntervalId = window.setInterval(() => {
      try {
        // Store current values for rate of change
        Object.entries(store.values).forEach(([name, data]) => {
          if (!lastValues.value[name]) {
            lastValues.value[name] = { value: data.value, timestamp: data.timestamp }
          }
        })

        // Run all evaluations — each isolated so one failure doesn't crash others
        try { updateCalculatedParams() } catch (e) { console.error('updateCalculatedParams error:', e) }
        try { evaluateTransformations() } catch (e) { console.error('evaluateTransformations error:', e) }
        try { evaluateFunctionBlocks() } catch (e) { console.error('evaluateFunctionBlocks error:', e) }
        try { evaluateAlarms() } catch (e) { console.error('evaluateAlarms error:', e) }
        try { evaluateTriggers() } catch (e) { console.error('evaluateTriggers error:', e) }
        try { evaluateSchedules() } catch (e) { console.error('evaluateSchedules error:', e) }
        try { evaluateWatchdogs() } catch (e) { console.error('evaluateWatchdogs error:', e) }

        // Send script values to recording (if recording)
        if (store.status?.recording) {
          try { sendScriptValuesToRecording() } catch (e) { console.error('sendScriptValuesToRecording error:', e) }
        }

        // Update last values after evaluation
        Object.entries(store.values).forEach(([name, data]) => {
          lastValues.value[name] = { value: data.value, timestamp: data.timestamp }
        })
      } catch (e) {
        console.error('Evaluation error:', e)
      }
    }, 500) // 2 Hz evaluation rate
  }

  function stopEvaluation() {
    if (evaluationIntervalId) {
      clearInterval(evaluationIntervalId)
      evaluationIntervalId = null
    }
  }

  // ========================================================================
  // COMPUTED
  // ========================================================================

  const runningSequence = computed(() =>
    runningSequenceId.value
      ? sequences.value.find(s => s.id === runningSequenceId.value)
      : null
  )

  const activeAlarms = computed(() =>
    alarms.value.filter(a => activeAlarmIds.value.includes(a.id))
  )

  const enabledCalculatedParams = computed(() =>
    calculatedParams.value.filter(p => p.enabled)
  )

  const enabledTransformations = computed(() =>
    transformations.value.filter(t => t.enabled)
  )

  const unacknowledgedNotifications = computed(() =>
    notifications.value.filter(n => !n.acknowledged && (n.type === 'warning' || n.type === 'error'))
  )

  // ========================================================================
  // SEQUENCE IMPORT/EXPORT
  // ========================================================================

  function exportSequence(id: string): string | null {
    const seq = sequences.value.find(s => s.id === id)
    if (!seq) return null

    // Export only the definition, not runtime state
    const exportData = {
      version: 1,
      exportDate: new Date().toISOString(),
      sequence: {
        name: seq.name,
        description: seq.description,
        steps: seq.steps,
        enabled: seq.enabled
      }
    }

    return JSON.stringify(exportData, null, 2)
  }

  function exportAllSequences(): string {
    const exportData = {
      version: 1,
      exportDate: new Date().toISOString(),
      sequences: sequences.value.map(seq => ({
        name: seq.name,
        description: seq.description,
        steps: seq.steps,
        enabled: seq.enabled
      }))
    }

    return JSON.stringify(exportData, null, 2)
  }

  function importSequence(jsonData: string): { success: boolean; message: string; sequenceId?: string } {
    try {
      const data = JSON.parse(jsonData)

      if (!data.sequence && !data.sequences) {
        return { success: false, message: 'Invalid format: missing sequence data' }
      }

      if (data.sequence) {
        // Single sequence import
        const seq = data.sequence
        if (!seq.name || !Array.isArray(seq.steps)) {
          return { success: false, message: 'Invalid sequence: missing name or steps' }
        }

        // Generate new IDs for all steps
        const steps = seq.steps.map((step: any) => ({
          ...step,
          id: `step-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
        }))

        const newId = addSequence({
          name: seq.name + ' (imported)',
          description: seq.description || '',
          steps,
          enabled: seq.enabled ?? true
        })

        return { success: true, message: `Imported sequence: ${seq.name}`, sequenceId: newId }
      }

      if (data.sequences) {
        // Multiple sequences import
        let imported = 0
        for (const seq of data.sequences) {
          if (!seq.name || !Array.isArray(seq.steps)) continue

          const steps = seq.steps.map((step: any) => ({
            ...step,
            id: `step-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
          }))

          addSequence({
            name: seq.name + ' (imported)',
            description: seq.description || '',
            steps,
            enabled: seq.enabled ?? true
          })
          imported++
        }

        return { success: true, message: `Imported ${imported} sequences` }
      }

      return { success: false, message: 'Unknown format' }
    } catch (e: any) {
      return { success: false, message: `Parse error: ${e.message}` }
    }
  }

  function createSequenceFromTemplate(templateId: string, name: string): string | null {
    const template = SEQUENCE_TEMPLATES.find(t => t.id === templateId)

    if (!template) return null

    // Generate unique IDs for all steps and handle loopId/ifId references
    const idMap: Record<string, string> = {}
    const steps = template.steps.map((step: any) => {
      const newId = `step-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`

      // Track loopId and ifId mappings
      if (step.loopId) {
        if (!idMap[step.loopId]) {
          idMap[step.loopId] = `loop-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
        }
      }
      if (step.ifId) {
        if (!idMap[step.ifId]) {
          idMap[step.ifId] = `if-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
        }
      }

      return {
        ...step,
        id: newId,
        loopId: step.loopId ? idMap[step.loopId] : undefined,
        ifId: step.ifId ? idMap[step.ifId] : undefined
      }
    })

    return addSequence({
      name: name || template.name,
      description: template.description,
      steps,
      enabled: true
    })
  }

  // ========================================================================
  // ALARM SAFETY CONFIRMATION
  // ========================================================================

  function canDisableAlarmSafely(alarmId: string): { safe: boolean; reason?: string } {
    const alarm = alarms.value.find(a => a.id === alarmId)
    if (!alarm) return { safe: true }

    if (alarm.state === 'active') {
      return {
        safe: false,
        reason: `This alarm is currently ACTIVE. Disabling it will prevent safety actions from executing.`
      }
    }

    if (alarm.state === 'acknowledged') {
      return {
        safe: false,
        reason: `This alarm is in acknowledged state. The condition may still be present.`
      }
    }

    if (alarm.state === 'latched') {
      return {
        safe: false,
        reason: `This alarm is latched. The triggering condition occurred recently.`
      }
    }

    return { safe: true }
  }

  // ========================================================================
  // RETURN
  // ========================================================================

  return {
    // State
    activeSubTab,
    calculatedParams,
    sequences,
    schedules,
    alarms,
    transformations,
    triggers,
    runningSequenceId,
    activeAlarmIds,
    alarmHistory,
    notifications,

    // Computed
    runningSequence,
    activeAlarms,
    enabledCalculatedParams,
    enabledTransformations,
    enabledSchedules,
    hasActiveSchedule,
    unacknowledgedNotifications,

    // MQTT Integration
    setMqttHandlers,

    // Notifications
    addNotification,
    dismissNotification,
    acknowledgeNotification,
    clearAllNotifications,

    // Persistence
    loadAll,
    reloadFromStorage,
    saveCalculatedParams,
    saveSequences,
    saveAlarms,
    saveTransformations,
    saveTriggers,

    // Formula
    evaluateFormula,
    getScriptValues,

    // Calculated Params
    addCalculatedParam,
    updateCalculatedParam,
    deleteCalculatedParam,

    // Sequences
    addSequence,
    updateSequence,
    deleteSequence,
    startSequence,
    pauseSequence,
    resumeSequence,
    abortSequence,
    exportSequence,
    exportAllSequences,
    importSequence,
    createSequenceFromTemplate,

    // Alarms
    addAlarm,
    updateAlarm,
    deleteAlarm,
    acknowledgeAlarm,
    canDisableAlarmSafely,

    // Transformations
    addTransformation,
    updateTransformation,
    deleteTransformation,

    // Triggers
    addTrigger,
    updateTrigger,
    deleteTrigger,

    // Schedules
    addSchedule,
    updateSchedule,
    deleteSchedule,
    saveSchedules,

    // Draw Patterns
    drawPatterns,
    drawPatternHistory,
    activeDrawPatternId,
    activeDrawPattern,
    isDrawPatternRunning,
    isDrawPatternPaused,
    currentDraw,
    enabledDrawPatterns,
    addDrawPattern,
    updateDrawPattern,
    deleteDrawPattern,
    addDraw,
    updateDraw,
    removeDraw,
    reorderDraws,
    startDrawPattern,
    pauseDrawPattern,
    resumeDrawPattern,
    stopDrawPattern,
    skipCurrentDraw,
    executeSingleDraw,
    saveDrawPatterns,

    // Function Blocks
    functionBlocks,
    enabledFunctionBlocks,
    createFunctionBlockFromTemplate,
    updateFunctionBlock,
    deleteFunctionBlock,
    updateFunctionBlockInput,
    resetFunctionBlockState,
    saveFunctionBlocks,

    // State Machines
    stateMachines,

    // Reports
    reportTemplates,
    scheduledReports,

    // Watchdogs
    watchdogs,
    saveWatchdogs,

    // Evaluation
    startEvaluation,
    stopEvaluation
  }
}
