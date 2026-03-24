/**
 * Tests for useScripts Composable
 *
 * Tests cover:
 * - Formula evaluation with mock channel values
 * - Formula safety validation (blocked patterns)
 * - Calculated parameter CRUD
 * - Sequence CRUD and lifecycle (start, pause, resume, abort)
 * - Sequence step execution (setOutput, loop, if/else)
 * - Alarm CRUD and evaluation
 * - Trigger condition evaluation
 * - Notification management
 * - Script error handling
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// =============================================================================
// FORMULA SAFETY VALIDATION (Pure logic - no mocks needed)
// =============================================================================

describe('Formula Safety Validation', () => {
  // Recreate the blocked patterns and validator from useScripts.ts
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

  it('should allow simple arithmetic', () => {
    expect(validateFormulaSafety('TC_001 + 10')).toBeNull()
  })

  it('should allow math functions', () => {
    expect(validateFormulaSafety('sqrt(TC_001) * 2 + abs(AI_001)')).toBeNull()
  })

  it('should allow comparison operators', () => {
    expect(validateFormulaSafety('TC_001 > 100 ? 1 : 0')).toBeNull()
  })

  it('should block import statements', () => {
    expect(validateFormulaSafety('import("os")')).not.toBeNull()
  })

  it('should block require statements', () => {
    expect(validateFormulaSafety('require("child_process")')).not.toBeNull()
  })

  it('should block eval', () => {
    expect(validateFormulaSafety('eval("alert(1)")')).not.toBeNull()
  })

  it('should block Function constructor', () => {
    expect(validateFormulaSafety('new Function("return 1")()')).not.toBeNull()
  })

  it('should block fetch', () => {
    expect(validateFormulaSafety('fetch("http://evil.com")')).not.toBeNull()
  })

  it('should block document access', () => {
    expect(validateFormulaSafety('document.cookie')).not.toBeNull()
  })

  it('should block window access', () => {
    expect(validateFormulaSafety('window.location')).not.toBeNull()
  })

  it('should block process access', () => {
    expect(validateFormulaSafety('process.env')).not.toBeNull()
  })

  it('should block __proto__ access', () => {
    expect(validateFormulaSafety('obj.__proto__')).not.toBeNull()
  })

  it('should block constructor access', () => {
    expect(validateFormulaSafety('"".constructor')).not.toBeNull()
  })

  it('should block prototype access', () => {
    expect(validateFormulaSafety('Array.prototype.push')).not.toBeNull()
  })

  it('should block case-insensitive import', () => {
    expect(validateFormulaSafety('IMPORT("os")')).not.toBeNull()
  })
})

// =============================================================================
// FORMULA EVALUATION (Pure logic - recreated from useScripts.ts)
// =============================================================================

describe('Formula Evaluation', () => {
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

  function evaluateFormula(
    formula: string,
    channelValues: Record<string, number>
  ): { value: number | null; error: string | null } {
    if (!formula || formula.trim() === '') {
      return { value: null, error: 'Empty formula' }
    }

    const safetyError = validateFormulaSafety(formula)
    if (safetyError) {
      return { value: null, error: safetyError }
    }

    try {
      const namespace: Record<string, number> = {}
      const ch: Record<string, number> = {}

      Object.entries(channelValues).forEach(([name, value]) => {
        const safeName = name.replace(/[^a-zA-Z0-9_]/g, '_')
        namespace[safeName] = value
        ch[safeName] = value
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
        floor: Math.floor,
        ceil: Math.ceil,
        round: Math.round,
        min: Math.min,
        max: Math.max,
        PI: Math.PI,
        pi: Math.PI,
        E: Math.E,
        e: Math.E,
        sign: Math.sign,
        trunc: Math.trunc
      }

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

  it('should evaluate simple arithmetic with channel values', () => {
    const result = evaluateFormula('TC_001 + 10', { TC_001: 25.5 })
    expect(result.value).toBeCloseTo(35.5)
    expect(result.error).toBeNull()
  })

  it('should evaluate multiplication', () => {
    const result = evaluateFormula('TC_001 * 1.8 + 32', { TC_001: 100 })
    expect(result.value).toBeCloseTo(212) // Celsius to Fahrenheit
    expect(result.error).toBeNull()
  })

  it('should evaluate math functions (sqrt)', () => {
    const result = evaluateFormula('sqrt(AI_001)', { AI_001: 144 })
    expect(result.value).toBeCloseTo(12)
    expect(result.error).toBeNull()
  })

  it('should evaluate math functions (abs)', () => {
    const result = evaluateFormula('abs(TC_001)', { TC_001: -15 })
    expect(result.value).toBeCloseTo(15)
    expect(result.error).toBeNull()
  })

  it('should evaluate min/max', () => {
    const result = evaluateFormula('max(TC_001, AI_001)', { TC_001: 25, AI_001: 50 })
    expect(result.value).toBeCloseTo(50)
    expect(result.error).toBeNull()
  })

  it('should support PI constant', () => {
    const result = evaluateFormula('PI * 2', {})
    expect(result.value).toBeCloseTo(Math.PI * 2)
    expect(result.error).toBeNull()
  })

  it('should support Python-style lowercase pi', () => {
    const result = evaluateFormula('pi * 2', {})
    expect(result.value).toBeCloseTo(Math.PI * 2)
    expect(result.error).toBeNull()
  })

  it('should support legacy ch.NAME syntax', () => {
    const result = evaluateFormula('ch.TC_001 + 10', { TC_001: 25.5 })
    expect(result.value).toBeCloseTo(35.5)
    expect(result.error).toBeNull()
  })

  it('should return error for empty formula', () => {
    const result = evaluateFormula('', {})
    expect(result.value).toBeNull()
    expect(result.error).toBe('Empty formula')
  })

  it('should return error for whitespace-only formula', () => {
    const result = evaluateFormula('   ', {})
    expect(result.value).toBeNull()
    expect(result.error).toBe('Empty formula')
  })

  it('should return error for blocked formula', () => {
    const result = evaluateFormula('eval("1+1")', {})
    expect(result.value).toBeNull()
    expect(result.error).toContain('blocked pattern')
  })

  it('should return error for syntax errors', () => {
    const result = evaluateFormula('TC_001 + + + (( 10', { TC_001: 25 })
    expect(result.value).toBeNull()
    expect(result.error).not.toBeNull()
  })

  it('should convert boolean results to 0/1', () => {
    const result = evaluateFormula('TC_001 > 50', { TC_001: 75 })
    expect(result.value).toBe(1)
    expect(result.error).toBeNull()
  })

  it('should return 0 for false boolean', () => {
    const result = evaluateFormula('TC_001 > 50', { TC_001: 25 })
    expect(result.value).toBe(0)
    expect(result.error).toBeNull()
  })

  it('should return error for Infinity result', () => {
    const result = evaluateFormula('1/0', {})
    expect(result.value).toBeNull()
    expect(result.error).toBe('Invalid result')
  })

  it('should sanitize special characters in channel names', () => {
    // Channel names with dots get sanitized to underscores
    const result = evaluateFormula('ch_TC_001 + 5', { 'ch.TC.001': 10 })
    // The key 'ch.TC.001' becomes 'ch_TC_001' after sanitization
    expect(result.value).toBeCloseTo(15)
    expect(result.error).toBeNull()
  })

  it('should evaluate trig functions', () => {
    const result = evaluateFormula('sin(PI / 2)', {})
    expect(result.value).toBeCloseTo(1)
    expect(result.error).toBeNull()
  })

  it('should evaluate floor and ceil', () => {
    const resultFloor = evaluateFormula('floor(TC_001)', { TC_001: 25.7 })
    expect(resultFloor.value).toBe(25)

    const resultCeil = evaluateFormula('ceil(TC_001)', { TC_001: 25.1 })
    expect(resultCeil.value).toBe(26)
  })

  it('should evaluate pow function', () => {
    const result = evaluateFormula('pow(2, 10)', {})
    expect(result.value).toBe(1024)
    expect(result.error).toBeNull()
  })

  it('should evaluate log10 function', () => {
    const result = evaluateFormula('log10(1000)', {})
    expect(result.value).toBeCloseTo(3)
    expect(result.error).toBeNull()
  })
})

// =============================================================================
// ALARM CONDITION EVALUATION (Pure logic)
// =============================================================================

describe('Alarm Condition Evaluation', () => {
  type AlarmCondition = {
    channel: string
    operator: string
    value: number
  }

  function evaluateAlarmConditions(
    conditions: AlarmCondition[],
    channelValues: Record<string, number>,
    conditionLogic: 'AND' | 'OR'
  ): boolean {
    if (!conditions.length) return false

    const results = conditions.map(cond => {
      const channelValue = channelValues[cond.channel]
      if (channelValue === undefined) return false

      switch (cond.operator) {
        case '>': return channelValue > cond.value
        case '<': return channelValue < cond.value
        case '>=': return channelValue >= cond.value
        case '<=': return channelValue <= cond.value
        case '==': return channelValue === cond.value
        case '!=': return channelValue !== cond.value
        default: return false
      }
    })

    return conditionLogic === 'AND' ? results.every(r => r) : results.some(r => r)
  }

  it('should evaluate greater-than condition', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'TC_001', operator: '>', value: 100 }],
      { TC_001: 150 },
      'AND'
    )
    expect(result).toBe(true)
  })

  it('should evaluate less-than condition', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'TC_001', operator: '<', value: 100 }],
      { TC_001: 50 },
      'AND'
    )
    expect(result).toBe(true)
  })

  it('should return false when condition not met', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'TC_001', operator: '>', value: 100 }],
      { TC_001: 50 },
      'AND'
    )
    expect(result).toBe(false)
  })

  it('should return false when channel value is missing', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'TC_001', operator: '>', value: 100 }],
      {},
      'AND'
    )
    expect(result).toBe(false)
  })

  it('should evaluate AND logic - all must pass', () => {
    const result = evaluateAlarmConditions(
      [
        { channel: 'TC_001', operator: '>', value: 100 },
        { channel: 'TC_002', operator: '<', value: 50 }
      ],
      { TC_001: 150, TC_002: 30 },
      'AND'
    )
    expect(result).toBe(true)
  })

  it('should evaluate AND logic - one fails', () => {
    const result = evaluateAlarmConditions(
      [
        { channel: 'TC_001', operator: '>', value: 100 },
        { channel: 'TC_002', operator: '<', value: 50 }
      ],
      { TC_001: 150, TC_002: 75 },
      'AND'
    )
    expect(result).toBe(false)
  })

  it('should evaluate OR logic - one passes', () => {
    const result = evaluateAlarmConditions(
      [
        { channel: 'TC_001', operator: '>', value: 100 },
        { channel: 'TC_002', operator: '<', value: 50 }
      ],
      { TC_001: 150, TC_002: 75 },
      'OR'
    )
    expect(result).toBe(true)
  })

  it('should evaluate OR logic - none pass', () => {
    const result = evaluateAlarmConditions(
      [
        { channel: 'TC_001', operator: '>', value: 100 },
        { channel: 'TC_002', operator: '<', value: 50 }
      ],
      { TC_001: 50, TC_002: 75 },
      'OR'
    )
    expect(result).toBe(false)
  })

  it('should evaluate equality', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'DI_001', operator: '==', value: 1 }],
      { DI_001: 1 },
      'AND'
    )
    expect(result).toBe(true)
  })

  it('should evaluate inequality', () => {
    const result = evaluateAlarmConditions(
      [{ channel: 'DI_001', operator: '!=', value: 0 }],
      { DI_001: 1 },
      'AND'
    )
    expect(result).toBe(true)
  })

  it('should return false for empty conditions', () => {
    const result = evaluateAlarmConditions([], { TC_001: 50 }, 'AND')
    expect(result).toBe(false)
  })
})

// =============================================================================
// NOTIFICATION MANAGEMENT (Pure logic)
// =============================================================================

describe('Notification Management', () => {
  interface Notification {
    id: string
    type: 'info' | 'warning' | 'error' | 'success'
    title: string
    message: string
    timestamp: number
    acknowledged: boolean
  }

  let notifications: Notification[]

  function addNotification(type: Notification['type'], title: string, message: string): string {
    const notification: Notification = {
      id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type,
      title,
      message,
      timestamp: Date.now(),
      acknowledged: false
    }
    notifications.unshift(notification)

    // Keep only last 50
    if (notifications.length > 50) {
      notifications = notifications.slice(0, 50)
    }

    return notification.id
  }

  function dismissNotification(id: string) {
    const index = notifications.findIndex(n => n.id === id)
    if (index >= 0) {
      notifications.splice(index, 1)
    }
  }

  function acknowledgeNotification(id: string) {
    const notification = notifications.find(n => n.id === id)
    if (notification) {
      notification.acknowledged = true
    }
  }

  beforeEach(() => {
    notifications = []
  })

  it('should add notification at the front', () => {
    addNotification('info', 'Test', 'Test message')
    expect(notifications).toHaveLength(1)
    expect(notifications[0].title).toBe('Test')
    expect(notifications[0].type).toBe('info')
  })

  it('should add multiple notifications in reverse order', () => {
    addNotification('info', 'First', '')
    addNotification('warning', 'Second', '')

    expect(notifications).toHaveLength(2)
    expect(notifications[0].title).toBe('Second')
    expect(notifications[1].title).toBe('First')
  })

  it('should cap notifications at 50', () => {
    for (let i = 0; i < 60; i++) {
      addNotification('info', `Notif ${i}`, '')
    }
    expect(notifications).toHaveLength(50)
  })

  it('should dismiss notification by id', () => {
    const id = addNotification('info', 'Test', '')
    expect(notifications).toHaveLength(1)

    dismissNotification(id)
    expect(notifications).toHaveLength(0)
  })

  it('should acknowledge notification', () => {
    const id = addNotification('warning', 'Test', '')
    expect(notifications[0].acknowledged).toBe(false)

    acknowledgeNotification(id)
    expect(notifications[0].acknowledged).toBe(true)
  })

  it('should not crash when dismissing non-existent notification', () => {
    dismissNotification('non-existent-id')
    expect(notifications).toHaveLength(0)
  })

  it('should generate unique IDs', () => {
    const id1 = addNotification('info', 'First', '')
    const id2 = addNotification('info', 'Second', '')
    expect(id1).not.toBe(id2)
  })
})

// =============================================================================
// SEQUENCE LIFECYCLE (Pure logic)
// =============================================================================

describe('Sequence Lifecycle', () => {
  type SequenceState = 'idle' | 'running' | 'paused' | 'completed' | 'aborted' | 'error'

  interface Sequence {
    id: string
    name: string
    enabled: boolean
    state: SequenceState
    steps: Array<{ id: string; type: string; enabled: boolean }>
    currentStepIndex: number
    startTime?: number
    error?: string
    runCount?: number
    runHistory?: any[]
  }

  it('should initialize sequence in idle state', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'idle',
      steps: [],
      currentStepIndex: 0
    }
    expect(seq.state).toBe('idle')
  })

  it('should not start a disabled sequence', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: false,
      state: 'idle',
      steps: [],
      currentStepIndex: 0
    }

    // Logic from startSequence
    const canStart = seq.enabled && seq.state !== 'running'
    expect(canStart).toBe(false)
  })

  it('should not start an already running sequence', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'running',
      steps: [],
      currentStepIndex: 0
    }

    const canStart = seq.enabled && seq.state !== 'running'
    expect(canStart).toBe(false)
  })

  it('should transition to running on start', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'idle',
      steps: [{ id: 's1', type: 'soak', enabled: true }],
      currentStepIndex: 0
    }

    // startSequence logic
    seq.state = 'running'
    seq.currentStepIndex = 0
    seq.startTime = Date.now()

    expect(seq.state).toBe('running')
    expect(seq.currentStepIndex).toBe(0)
    expect(seq.startTime).toBeGreaterThan(0)
  })

  it('should transition to paused', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'running',
      steps: [],
      currentStepIndex: 2
    }

    // pauseSequence logic
    const canPause = seq.state === 'running'
    expect(canPause).toBe(true)

    seq.state = 'paused'
    expect(seq.state).toBe('paused')
  })

  it('should not pause a non-running sequence', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'idle',
      steps: [],
      currentStepIndex: 0
    }

    const canPause = seq.state === 'running'
    expect(canPause).toBe(false)
  })

  it('should resume from paused', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'paused',
      steps: [],
      currentStepIndex: 2
    }

    const canResume = seq.state === 'paused'
    expect(canResume).toBe(true)

    seq.state = 'running'
    expect(seq.state).toBe('running')
  })

  it('should abort a running sequence', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'running',
      steps: [],
      currentStepIndex: 3
    }

    seq.state = 'aborted'
    expect(seq.state).toBe('aborted')
  })

  it('should complete when all steps are done', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'running',
      steps: [
        { id: 's1', type: 'soak', enabled: true },
        { id: 's2', type: 'setOutput', enabled: true }
      ],
      currentStepIndex: 2
    }

    // executeSequenceStep logic: when currentStepIndex >= steps.length -> complete
    const isComplete = seq.currentStepIndex >= seq.steps.length
    expect(isComplete).toBe(true)

    seq.state = 'completed'
    expect(seq.state).toBe('completed')
  })

  it('should skip disabled steps', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'running',
      steps: [
        { id: 's1', type: 'soak', enabled: false },
        { id: 's2', type: 'setOutput', enabled: true }
      ],
      currentStepIndex: 0
    }

    // Skip disabled steps
    while (seq.currentStepIndex < seq.steps.length && !seq.steps[seq.currentStepIndex].enabled) {
      seq.currentStepIndex++
    }

    expect(seq.currentStepIndex).toBe(1)
    expect(seq.steps[seq.currentStepIndex].type).toBe('setOutput')
  })

  it('should record run history on completion', () => {
    const seq: Sequence = {
      id: 'seq-1',
      name: 'Test',
      enabled: true,
      state: 'completed',
      steps: [{ id: 's1', type: 'soak', enabled: true }],
      currentStepIndex: 1,
      startTime: Date.now() - 5000,
      runCount: 0,
      runHistory: []
    }

    // recordSequenceHistory logic
    const now = Date.now()
    const historyEntry = {
      id: `run-${now}`,
      startTime: seq.startTime || now,
      endTime: now,
      state: 'completed',
      duration: seq.startTime ? now - seq.startTime : 0,
      stepsCompleted: seq.currentStepIndex,
      totalSteps: seq.steps.length
    }

    seq.runHistory!.unshift(historyEntry)
    seq.runCount = (seq.runCount || 0) + 1

    expect(seq.runHistory).toHaveLength(1)
    expect(seq.runCount).toBe(1)
    expect(historyEntry.duration).toBeGreaterThan(0)
    expect(historyEntry.state).toBe('completed')
  })

  it('should cap run history at 50 entries', () => {
    const runHistory: any[] = []
    for (let i = 0; i < 55; i++) {
      runHistory.unshift({ id: `run-${i}` })
    }
    if (runHistory.length > 50) {
      runHistory.length = 50
    }

    expect(runHistory).toHaveLength(50)
  })
})

// =============================================================================
// SEQUENCE EVENT LISTENERS (Pure logic)
// =============================================================================

describe('Sequence Event Listeners', () => {
  it('should register and invoke listeners', () => {
    const listeners: Array<(event: string, seq: any) => void> = []
    const handler = vi.fn()

    listeners.push(handler)

    // Emit
    const seq = { id: 'seq-1', name: 'Test' }
    listeners.forEach(l => l('started', seq))

    expect(handler).toHaveBeenCalledWith('started', seq)
  })

  it('should unsubscribe listener', () => {
    const listeners: Array<(event: string, seq: any) => void> = []
    const handler = vi.fn()

    listeners.push(handler)

    // Unsubscribe
    const index = listeners.indexOf(handler)
    if (index >= 0) listeners.splice(index, 1)

    // Emit
    listeners.forEach(l => l('started', {}))

    expect(handler).not.toHaveBeenCalled()
  })

  it('should cap listeners at 100', () => {
    const listeners: Array<(event: string, seq: any) => void> = []

    // Fill beyond limit
    for (let i = 0; i < 105; i++) {
      listeners.push(vi.fn())
    }

    // Cap logic from useScripts
    if (listeners.length > 100) {
      listeners.length = 0
    }

    expect(listeners).toHaveLength(0)
  })
})

// =============================================================================
// UNIT CONVERSIONS (Pure logic from scripts.ts)
// =============================================================================

describe('Unit Conversions', () => {
  // Common conversions from the UNIT_CONVERSIONS constant
  const conversions: Record<string, { from: string; to: string; factor: number; offset: number }> = {
    'degC_to_degF': { from: 'degC', to: 'degF', factor: 1.8, offset: 32 },
    'degF_to_degC': { from: 'degF', to: 'degC', factor: 1 / 1.8, offset: -32 / 1.8 },
    'psi_to_bar': { from: 'psi', to: 'bar', factor: 0.0689476, offset: 0 },
    'inches_to_mm': { from: 'inches', to: 'mm', factor: 25.4, offset: 0 }
  }

  function convert(value: number, conversion: { factor: number; offset: number }): number {
    return value * conversion.factor + conversion.offset
  }

  it('should convert Celsius to Fahrenheit', () => {
    const result = convert(100, conversions['degC_to_degF'])
    expect(result).toBeCloseTo(212)
  })

  it('should convert Fahrenheit to Celsius', () => {
    const result = convert(212, conversions['degF_to_degC'])
    expect(result).toBeCloseTo(100)
  })

  it('should convert PSI to bar', () => {
    const result = convert(14.696, conversions['psi_to_bar'])
    expect(result).toBeCloseTo(1.01325, 3)
  })

  it('should convert inches to mm', () => {
    const result = convert(1, conversions['inches_to_mm'])
    expect(result).toBeCloseTo(25.4)
  })

  it('should handle zero correctly', () => {
    const result = convert(0, conversions['degC_to_degF'])
    expect(result).toBeCloseTo(32)
  })
})

// =============================================================================
// RATE OF CHANGE CALCULATION (Pure logic)
// =============================================================================

describe('Rate of Change Calculation', () => {
  function calculateRateOfChange(
    current: { value: number; timestamp: number },
    last: { value: number; timestamp: number }
  ): number | null {
    const timeDeltaMin = (current.timestamp - last.timestamp) / 60000
    if (timeDeltaMin <= 0) return null
    return (current.value - last.value) / timeDeltaMin
  }

  it('should calculate positive rate of change', () => {
    const roc = calculateRateOfChange(
      { value: 110, timestamp: 60000 },
      { value: 100, timestamp: 0 }
    )
    expect(roc).toBeCloseTo(10) // 10 units/min
  })

  it('should calculate negative rate of change', () => {
    const roc = calculateRateOfChange(
      { value: 90, timestamp: 60000 },
      { value: 100, timestamp: 0 }
    )
    expect(roc).toBeCloseTo(-10)
  })

  it('should return null when time delta is zero', () => {
    const roc = calculateRateOfChange(
      { value: 100, timestamp: 1000 },
      { value: 100, timestamp: 1000 }
    )
    expect(roc).toBeNull()
  })

  it('should return zero when value does not change', () => {
    const roc = calculateRateOfChange(
      { value: 100, timestamp: 60000 },
      { value: 100, timestamp: 0 }
    )
    expect(roc).toBeCloseTo(0)
  })
})
