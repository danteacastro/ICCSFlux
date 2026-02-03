import { ref, computed } from 'vue'
import type {
  UserVariable,
  UserVariableType,
  UserVariableValue,
  TestSession,
  TestSessionConfig,
  ResetMode,
  EdgeType,
  FormulaBlock,
  FormulaBlockValues
} from '../types'

// ==========================================================================
// SINGLETON STATE - exists outside the composable function
// ==========================================================================

const variables = ref<Record<string, UserVariable>>({})
const variableValues = ref<Record<string, UserVariableValue>>({})
const testSession = ref<TestSession>({
  active: false,
  config: {
    enableScheduler: true,
    startRecording: true,
    enableTriggers: true,
    resetVariables: []
  }
})

// Formula blocks state
const formulaBlocks = ref<Record<string, FormulaBlock>>({})
const formulaValues = ref<Record<string, FormulaBlockValues>>({})

// MQTT handlers - will be set by setMqttHandlers
let mqttPublish: ((topic: string, payload: any) => void) | null = null

// State (reserved for future use)
let _isInitialized = false
void _isInitialized // suppress unused warning

// ==========================================================================
// COMPOSABLE FUNCTION
// ==========================================================================

export function usePlayground() {

  // ========================================================================
  // MQTT INTEGRATION
  // ========================================================================

  function setMqttHandlers(handlers: {
    publish: (topic: string, payload: any) => void
  }) {
    mqttPublish = handlers.publish
  }

  function publish(topic: string, payload: any) {
    if (mqttPublish) {
      console.debug('Playground: Publishing to', topic, payload)
      mqttPublish(topic, payload)
    } else {
      console.warn('Playground: MQTT not connected, cannot publish:', topic, payload)
    }
  }

  // ========================================================================
  // VARIABLE MANAGEMENT
  // ========================================================================

  function createVariable(config: Partial<UserVariable> & { description?: string }): void {
    const id = config.id || `var_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    const name = config.name || id

    // Optimistic update: add to local state immediately so UI shows the variable
    variables.value[id] = {
      id,
      name,
      displayName: config.displayName || name,
      variableType: config.variableType || 'manual',
      value: config.value ?? 0,
      units: config.units || '',
      persistent: config.persistent ?? true,
      sourceChannel: config.sourceChannel || null,
      edgeType: config.edgeType || 'increment',
      scaleFactor: config.scaleFactor ?? 1.0,
      resetMode: config.resetMode || 'manual',
      resetTime: config.resetTime || null,
      resetElapsedS: config.resetElapsedS || null,
      formula: config.formula || null,
    } as UserVariable

    // Convert to snake_case for backend
    const payload = {
      id,
      name,
      display_name: config.displayName || name,
      variable_type: config.variableType || 'manual',
      description: config.description || '',
      value: config.value ?? 0,
      units: config.units || '',
      persistent: config.persistent ?? true,
      reset_mode: config.resetMode || 'manual',
      source_channel: config.sourceChannel || null,
      edge_type: config.edgeType || 'increment',
      scale_factor: config.scaleFactor ?? 1.0,
      source_rate_unit: config.sourceRateUnit || 'per_second',
      reset_time: config.resetTime || null,
      reset_elapsed_s: config.resetElapsedS || null,
      formula: config.formula || null,
      rolling_window_s: config.rollingWindowS || 86400,  // Default 24 hours
    }

    publish('nisystem/variables/create', payload)
  }

  function updateVariable(id: string, updates: Partial<UserVariable>): void {
    // Convert to snake_case for backend
    const payload: Record<string, any> = { id }
    if (updates.name !== undefined) payload.name = updates.name
    if (updates.displayName !== undefined) payload.display_name = updates.displayName
    if (updates.variableType !== undefined) payload.variable_type = updates.variableType
    if (updates.value !== undefined) payload.value = updates.value
    if (updates.units !== undefined) payload.units = updates.units
    if (updates.persistent !== undefined) payload.persistent = updates.persistent
    if (updates.resetMode !== undefined) payload.reset_mode = updates.resetMode
    if (updates.sourceChannel !== undefined) payload.source_channel = updates.sourceChannel
    if (updates.edgeType !== undefined) payload.edge_type = updates.edgeType
    if (updates.scaleFactor !== undefined) payload.scale_factor = updates.scaleFactor
    if (updates.sourceRateUnit !== undefined) payload.source_rate_unit = updates.sourceRateUnit
    if (updates.resetTime !== undefined) payload.reset_time = updates.resetTime
    if (updates.resetElapsedS !== undefined) payload.reset_elapsed_s = updates.resetElapsedS
    if (updates.formula !== undefined) payload.formula = updates.formula
    if (updates.rollingWindowS !== undefined) payload.rolling_window_s = updates.rollingWindowS

    publish('nisystem/variables/update', payload)
  }

  function deleteVariable(id: string): void {
    // Optimistic update: remove from local state immediately
    delete variables.value[id]
    publish('nisystem/variables/delete', { id })
  }

  function setVariableValue(id: string, value: number): void {
    publish('nisystem/variables/set', { id, value })
  }

  function resetVariable(id: string): void {
    publish('nisystem/variables/reset', { id })
  }

  function resetAllVariables(ids?: string[]): void {
    if (ids && ids.length > 0) {
      publish('nisystem/variables/reset', { ids })
    } else {
      publish('nisystem/variables/reset', {})
    }
  }

  function startTimer(id: string): void {
    publish('nisystem/variables/timer/start', { id })
  }

  function stopTimer(id: string): void {
    publish('nisystem/variables/timer/stop', { id })
  }

  function refreshVariables(): void {
    publish('nisystem/variables/list', {})
  }

  // ========================================================================
  // TEST SESSION MANAGEMENT
  // ========================================================================

  function startTestSession(startedBy: string = 'user', metadata?: {
    testId?: string
    description?: string
    operatorNotes?: string
    timeoutMinutes?: number
  }): void {
    publish('nisystem/test-session/start', {
      started_by: startedBy,
      test_id: metadata?.testId || '',
      description: metadata?.description || '',
      operator_notes: metadata?.operatorNotes || '',
      timeout_minutes: metadata?.timeoutMinutes || 0,
    })
  }

  function stopTestSession(): void {
    publish('nisystem/test-session/stop', {})
  }

  function updateSessionConfig(config: Partial<TestSessionConfig> & { enableTriggerIds?: string[], enableScheduleIds?: string[] }): void {
    // Convert camelCase to snake_case for backend
    const payload: Record<string, any> = {}
    if (config.enableScheduler !== undefined) payload.enable_scheduler = config.enableScheduler
    if (config.startRecording !== undefined) payload.start_recording = config.startRecording
    if (config.enableTriggers !== undefined) payload.enable_triggers = config.enableTriggers
    if (config.resetVariables !== undefined) payload.reset_variables = config.resetVariables
    if (config.runSequenceId !== undefined) payload.run_sequence_id = config.runSequenceId || null
    if (config.stopSequenceId !== undefined) payload.stop_sequence_id = config.stopSequenceId || null
    if (config.enableTriggerIds !== undefined) payload.enable_trigger_ids = config.enableTriggerIds
    if (config.enableScheduleIds !== undefined) payload.enable_schedule_ids = config.enableScheduleIds

    publish('nisystem/test-session/config', payload)
  }

  function refreshSessionStatus(): void {
    publish('nisystem/test-session/status', {})
  }

  // ========================================================================
  // FORMULA BLOCK MANAGEMENT
  // ========================================================================

  function createFormulaBlock(block: FormulaBlock): void {
    // Optimistic update: add to local state immediately so UI shows the block
    formulaBlocks.value[block.id] = {
      id: block.id,
      name: block.name,
      description: block.description || '',
      code: block.code || '',
      enabled: block.enabled ?? true,
      outputs: block.outputs || {},
      lastError: undefined,
      lastValidated: undefined,
    }

    // Convert camelCase to snake_case for backend
    const payload = {
      id: block.id,
      name: block.name,
      description: block.description,
      code: block.code,
      enabled: block.enabled,
      outputs: block.outputs,
    }
    publish('nisystem/formulas/create', payload)
  }

  function updateFormulaBlock(blockId: string, updates: Partial<FormulaBlock>): void {
    const payload: Record<string, any> = { id: blockId }
    if (updates.name !== undefined) payload.name = updates.name
    if (updates.description !== undefined) payload.description = updates.description
    if (updates.code !== undefined) payload.code = updates.code
    if (updates.enabled !== undefined) payload.enabled = updates.enabled
    if (updates.outputs !== undefined) payload.outputs = updates.outputs
    publish('nisystem/formulas/update', payload)
  }

  function deleteFormulaBlock(blockId: string): void {
    // Optimistic update: remove from local state immediately
    delete formulaBlocks.value[blockId]
    publish('nisystem/formulas/delete', { id: blockId })
  }

  function refreshFormulaBlocks(): void {
    publish('nisystem/formulas/list', {})
  }

  // ========================================================================
  // MQTT MESSAGE HANDLERS (called by useMqtt)
  // ========================================================================

  function handleVariablesConfig(payload: Record<string, any>): void {
    // Convert snake_case to camelCase for frontend
    const converted: Record<string, UserVariable> = {}
    for (const [id, data] of Object.entries(payload)) {
      converted[id] = {
        id: data.id,
        name: data.name,
        displayName: data.display_name || data.name,
        variableType: data.variable_type,
        value: data.value,
        units: data.units || '',
        persistent: data.persistent ?? true,
        sourceChannel: data.source_channel,
        edgeType: data.edge_type,
        scaleFactor: data.scale_factor,
        resetMode: data.reset_mode || 'manual',
        resetTime: data.reset_time,
        resetElapsedS: data.reset_elapsed_s,
        lastReset: data.last_reset,
        timerRunning: data.timer_running,
        sampleCount: data.sample_count,
        formula: data.formula,
      }
    }
    variables.value = converted
  }

  function handleVariablesValues(payload: Record<string, UserVariableValue>): void {
    variableValues.value = payload

    // Also update the main variables object with current values
    for (const [id, data] of Object.entries(payload)) {
      if (variables.value[id]) {
        // Handle both numeric and string values
        if (typeof data.value === 'number') {
          variables.value[id].value = data.value
        } else if (typeof data.value === 'string') {
          variables.value[id].stringValue = data.value
        }
        variables.value[id].timerRunning = data.timer_running
        variables.value[id].formatted = data.formatted
        variables.value[id].lastUpdated = data.last_update
      }
    }
  }

  function handleTestSessionStatus(payload: any): void {
    testSession.value = {
      active: payload.active,
      startedAt: payload.started_at,
      startedBy: payload.started_by,
      elapsedSeconds: payload.elapsed_seconds,
      elapsedFormatted: payload.elapsed_formatted,
      config: {
        enableScheduler: payload.config?.enable_scheduler ?? true,
        startRecording: payload.config?.start_recording ?? true,
        enableTriggers: payload.config?.enable_triggers ?? true,
        resetVariables: payload.config?.reset_variables || [],
        runSequenceId: payload.config?.run_sequence_id,
        stopSequenceId: payload.config?.stop_sequence_id,
        enableTriggerIds: payload.config?.enable_trigger_ids || [],
        enableScheduleIds: payload.config?.enable_schedule_ids || [],
      },
      testId: payload.test_id,
      description: payload.description,
      operatorNotes: payload.operator_notes,
      timeoutMinutes: payload.config?.timeout_minutes || 0,
    }
  }

  function handleFormulaBlocksConfig(payload: Record<string, any>): void {
    // Convert snake_case to camelCase for frontend
    const converted: Record<string, FormulaBlock> = {}
    for (const [id, data] of Object.entries(payload)) {
      converted[id] = {
        id: data.id,
        name: data.name,
        description: data.description || '',
        code: data.code || '',
        enabled: data.enabled ?? true,
        outputs: data.outputs || {},
        lastError: data.last_error,
        lastValidated: data.last_validated,
      }
    }
    formulaBlocks.value = converted
  }

  function handleFormulaBlocksValues(payload: Record<string, FormulaBlockValues>): void {
    formulaValues.value = payload
  }

  // ========================================================================
  // COMPUTED PROPERTIES
  // ========================================================================

  const variablesList = computed(() => Object.values(variables.value))

  const variablesByType = computed(() => {
    const grouped: Record<UserVariableType, UserVariable[]> = {
      constant: [],
      manual: [],
      accumulator: [],
      counter: [],
      timer: [],
      sum: [],
      average: [],
      min: [],
      max: [],
      stddev: [],
      rms: [],
      median: [],
      peak_to_peak: [],
      rolling: [],
      expression: [],
      rate: [],
      runtime: [],
      dwell: [],
      conditional_average: [],
      cross_channel: [],
      string: []
    }

    for (const variable of variablesList.value) {
      if (grouped[variable.variableType]) {
        grouped[variable.variableType].push(variable)
      }
    }

    return grouped
  })

  const isSessionActive = computed(() => testSession.value.active)

  const sessionElapsed = computed(() => testSession.value.elapsedFormatted || '00:00:00')

  const formulaBlocksList = computed(() => Object.values(formulaBlocks.value))

  const formulaBlocksEnabled = computed(() =>
    formulaBlocksList.value.filter(b => b.enabled)
  )

  // Get all formula output values flattened for display
  const allFormulaOutputs = computed(() => {
    const outputs: Record<string, { blockId: string; blockName: string; value: number; units: string; description: string }> = {}
    for (const block of formulaBlocksList.value) {
      const blockValues = formulaValues.value[block.id] || {}
      for (const [outName, metadata] of Object.entries(block.outputs)) {
        outputs[outName] = {
          blockId: block.id,
          blockName: block.name,
          value: blockValues[outName] ?? NaN,
          units: metadata.units,
          description: metadata.description
        }
      }
    }
    return outputs
  })

  // ========================================================================
  // VARIABLE TYPE HELPERS
  // ========================================================================

  const VARIABLE_TYPE_INFO: Record<UserVariableType, {
    label: string
    description: string
    icon: string
    requiresSource: boolean
    supportsFormula: boolean
  }> = {
    constant: {
      label: 'Constant',
      description: 'Fixed value for use in formulas (e.g., calibration factor, setpoint)',
      icon: '🔒',
      requiresSource: false,
      supportsFormula: false
    },
    manual: {
      label: 'Manual',
      description: 'User sets value directly',
      icon: '✏️',
      requiresSource: false,
      supportsFormula: false
    },
    accumulator: {
      label: 'Accumulator',
      description: 'Totalize counter increments (survives counter resets)',
      icon: '📊',
      requiresSource: true,
      supportsFormula: false
    },
    counter: {
      label: 'Counter',
      description: 'Count edge transitions',
      icon: '🔢',
      requiresSource: true,
      supportsFormula: false
    },
    timer: {
      label: 'Timer',
      description: 'Elapsed time counter',
      icon: '⏱️',
      requiresSource: false,
      supportsFormula: false
    },
    sum: {
      label: 'Sum',
      description: 'Running sum of channel values',
      icon: '➕',
      requiresSource: true,
      supportsFormula: false
    },
    average: {
      label: 'Average',
      description: 'Running average of channel values',
      icon: '📈',
      requiresSource: true,
      supportsFormula: false
    },
    min: {
      label: 'Minimum',
      description: 'Minimum value seen since reset',
      icon: '⬇️',
      requiresSource: true,
      supportsFormula: false
    },
    max: {
      label: 'Maximum',
      description: 'Maximum value seen since reset',
      icon: '⬆️',
      requiresSource: true,
      supportsFormula: false
    },
    stddev: {
      label: 'Std Deviation',
      description: 'Running standard deviation (Welford\'s algorithm)',
      icon: 'σ',
      requiresSource: true,
      supportsFormula: false
    },
    rms: {
      label: 'RMS',
      description: 'Root mean square (for AC signals, vibration analysis)',
      icon: '∿',
      requiresSource: true,
      supportsFormula: false
    },
    median: {
      label: 'Median',
      description: 'Running median (reservoir sampling, approximate for large datasets)',
      icon: '⊳',
      requiresSource: true,
      supportsFormula: false
    },
    peak_to_peak: {
      label: 'Peak-to-Peak',
      description: 'Difference between maximum and minimum values',
      icon: '↕️',
      requiresSource: true,
      supportsFormula: false
    },
    rolling: {
      label: 'Rolling (24hr)',
      description: 'Sliding window accumulator (e.g., last 24 hours)',
      icon: '🔄',
      requiresSource: true,
      supportsFormula: false
    },
    expression: {
      label: 'Expression',
      description: 'Calculated from formula',
      icon: '🧮',
      requiresSource: false,
      supportsFormula: true
    },
    rate: {
      label: 'Rate of Change',
      description: 'Derivative / rate of change',
      icon: '📉',
      requiresSource: true,
      supportsFormula: false
    },
    runtime: {
      label: 'Runtime',
      description: 'Time above/below threshold',
      icon: '⏲️',
      requiresSource: true,
      supportsFormula: false
    },
    dwell: {
      label: 'Dwell Time',
      description: 'Time spent in a condition',
      icon: '⏳',
      requiresSource: false,
      supportsFormula: true
    },
    conditional_average: {
      label: 'Conditional Average',
      description: 'Average only when condition is true',
      icon: '📊',
      requiresSource: true,
      supportsFormula: false
    },
    cross_channel: {
      label: 'Cross-Channel',
      description: 'Min/max/delta across multiple channels',
      icon: '🔀',
      requiresSource: true,
      supportsFormula: false
    },
    string: {
      label: 'String',
      description: 'Text value (notes, batch ID, operator input)',
      icon: '📝',
      requiresSource: false,
      supportsFormula: false
    }
  }

  const RESET_MODE_INFO: Record<ResetMode, { label: string; description: string }> = {
    manual: { label: 'Manual', description: 'Only reset when user clicks reset' },
    time_of_day: { label: 'Daily', description: 'Reset at specific time each day' },
    elapsed: { label: 'Elapsed', description: 'Reset after a time interval' },
    test_session: { label: 'Session', description: 'Reset when test session starts' },
    never: { label: 'Never', description: 'Never reset (accumulate forever)' }
  }

  const EDGE_TYPE_INFO: Record<EdgeType, { label: string; description: string }> = {
    increment: { label: 'Increment', description: 'Any increase in value' },
    rising: { label: 'Rising Edge', description: '0 → 1 transition' },
    falling: { label: 'Falling Edge', description: '1 → 0 transition' },
    both: { label: 'Any Edge', description: 'Any transition' },
    rate: { label: 'Rate', description: 'Rate signal (4-20mA, voltage) - integrate over time' }
  }

  // ========================================================================
  // FORMATTING HELPERS
  // ========================================================================

  function formatValue(variable: UserVariable): string {
    if (variable.variableType === 'timer' && variable.formatted) {
      return variable.formatted
    }

    const value = variable.value
    if (value === undefined || value === null) return '--'

    // Format based on magnitude
    if (Math.abs(value) >= 1000000) {
      return value.toExponential(2)
    } else if (Math.abs(value) >= 1000) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 1 })
    } else if (Math.abs(value) >= 1) {
      return value.toFixed(2)
    } else if (Math.abs(value) >= 0.01) {
      return value.toFixed(3)
    } else if (value === 0) {
      return '0'
    } else {
      return value.toExponential(2)
    }
  }

  function formatElapsedTime(seconds: number): string {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = Math.floor(seconds % 60)
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  // ========================================================================
  // RETURN
  // ========================================================================

  return {
    // State
    variables,
    variableValues,
    testSession,
    formulaBlocks,
    formulaValues,

    // Computed
    variablesList,
    variablesByType,
    isSessionActive,
    sessionElapsed,
    formulaBlocksList,
    formulaBlocksEnabled,
    allFormulaOutputs,

    // Variable operations
    createVariable,
    updateVariable,
    deleteVariable,
    setVariableValue,
    resetVariable,
    resetAllVariables,
    startTimer,
    stopTimer,
    refreshVariables,

    // Session operations
    startTestSession,
    stopTestSession,
    updateSessionConfig,
    refreshSessionStatus,

    // Formula block operations
    createFormulaBlock,
    updateFormulaBlock,
    deleteFormulaBlock,
    refreshFormulaBlocks,

    // MQTT handlers
    setMqttHandlers,
    handleVariablesConfig,
    handleVariablesValues,
    handleTestSessionStatus,
    handleFormulaBlocksConfig,
    handleFormulaBlocksValues,

    // Constants
    VARIABLE_TYPE_INFO,
    RESET_MODE_INFO,
    EDGE_TYPE_INFO,

    // Helpers
    formatValue,
    formatElapsedTime
  }
}
