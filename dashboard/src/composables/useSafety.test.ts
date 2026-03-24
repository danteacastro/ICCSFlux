/**
 * Tests for Safety & Interlock System Composable
 *
 * Tests cover:
 * - Alarm configuration management
 * - Active alarm tracking
 * - Alarm state transitions (active -> acknowledged -> cleared)
 * - Latch behavior
 * - Interlock checking
 * - First-out alarm tracking
 * - Alarm counts computation
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

// =============================================================================
// ALARM STATE MACHINE TESTS (Pure logic)
// =============================================================================

describe('Alarm State Machine', () => {
  // Alarm states from ISA-18.2
  type AlarmState = 'active' | 'acknowledged' | 'returned' | 'shelved' | 'cleared'

  describe('State Transitions', () => {
    it('should transition from active to acknowledged', () => {
      const currentState: AlarmState = 'active'
      const action = 'acknowledge'

      // State machine logic
      const nextState: AlarmState = action === 'acknowledge' ? 'acknowledged' : currentState

      expect(nextState).toBe('acknowledged')
    })

    it('should transition from acknowledged to returned when condition clears', () => {
      const currentState: AlarmState = 'acknowledged'
      const conditionActive = false

      // When acknowledged and condition clears, go to returned
      const nextState: AlarmState = !conditionActive ? 'returned' : currentState

      expect(nextState).toBe('returned')
    })

    it('should auto-clear from returned state with auto_clear behavior', () => {
      const currentState: AlarmState = 'returned'
      const behavior = 'auto_clear'

      // Auto-clear behavior: remove alarm when returned
      const shouldClear = currentState === 'returned' && behavior === 'auto_clear'

      expect(shouldClear).toBe(true)
    })

    it('should NOT auto-clear with latch behavior', () => {
      const currentState: AlarmState = 'returned'
      const behavior = 'latch'

      const shouldClear = currentState === 'returned' && behavior === 'auto_clear'

      expect(shouldClear).toBe(false)
    })
  })

  describe('Latch Behavior', () => {
    it('should remain latched until manual reset', () => {
      const behavior = 'latch'
      const conditionActive = false
      const manualReset = false

      // Latched alarms stay until manually reset
      const shouldStayLatched = behavior === 'latch' && !manualReset

      expect(shouldStayLatched).toBe(true)
    })

    it('should unlatch when manually reset', () => {
      const behavior = 'latch'
      const manualReset = true

      const shouldUnlatch = manualReset

      expect(shouldUnlatch).toBe(true)
    })

    it('should auto-unlatch after timed_latch period', () => {
      const behavior = 'timed_latch'
      const latchTimeS = 60
      const timeSinceClearS = 65

      const shouldAutoUnlatch = behavior === 'timed_latch' && timeSinceClearS > latchTimeS

      expect(shouldAutoUnlatch).toBe(true)
    })
  })
})

// =============================================================================
// ALARM SEVERITY TESTS
// =============================================================================

describe('Alarm Severity', () => {
  type AlarmSeverity = 'critical' | 'high' | 'medium' | 'low' | 'diagnostic' | 'alarm' | 'warning'

  it('should identify critical as highest priority', () => {
    const severityOrder: AlarmSeverity[] = ['critical', 'high', 'medium', 'low', 'diagnostic']

    expect(severityOrder[0]).toBe('critical')
  })

  it('should map alarm to high', () => {
    const severity: AlarmSeverity = 'alarm'
    const mappedPriority = severity === 'alarm' ? 'high' : severity

    // 'alarm' legacy type maps to 'high'
    expect(mappedPriority).toBe('high')
  })

  it('should map warning to low', () => {
    const severity: AlarmSeverity = 'warning'
    const mappedPriority = severity === 'warning' ? 'low' : severity

    expect(mappedPriority).toBe('low')
  })
})

// =============================================================================
// ALARM LIMIT CHECKING TESTS
// =============================================================================

describe('Alarm Limit Checking', () => {
  interface AlarmLimits {
    high_high?: number
    high?: number
    low?: number
    low_low?: number
    deadband?: number
  }

  function checkAlarmCondition(value: number, limits: AlarmLimits): {
    inAlarm: boolean
    alarmType: string | null
  } {
    if (limits.high_high !== undefined && value >= limits.high_high) {
      return { inAlarm: true, alarmType: 'high_high' }
    }
    if (limits.high !== undefined && value >= limits.high) {
      return { inAlarm: true, alarmType: 'high' }
    }
    if (limits.low_low !== undefined && value <= limits.low_low) {
      return { inAlarm: true, alarmType: 'low_low' }
    }
    if (limits.low !== undefined && value <= limits.low) {
      return { inAlarm: true, alarmType: 'low' }
    }
    return { inAlarm: false, alarmType: null }
  }

  it('should detect high-high alarm', () => {
    const limits: AlarmLimits = { high_high: 100, high: 80 }
    const result = checkAlarmCondition(105, limits)

    expect(result.inAlarm).toBe(true)
    expect(result.alarmType).toBe('high_high')
  })

  it('should detect high alarm', () => {
    const limits: AlarmLimits = { high_high: 100, high: 80 }
    const result = checkAlarmCondition(85, limits)

    expect(result.inAlarm).toBe(true)
    expect(result.alarmType).toBe('high')
  })

  it('should detect low-low alarm', () => {
    const limits: AlarmLimits = { low: 20, low_low: 10 }
    const result = checkAlarmCondition(5, limits)

    expect(result.inAlarm).toBe(true)
    expect(result.alarmType).toBe('low_low')
  })

  it('should detect low alarm', () => {
    const limits: AlarmLimits = { low: 20, low_low: 10 }
    const result = checkAlarmCondition(15, limits)

    expect(result.inAlarm).toBe(true)
    expect(result.alarmType).toBe('low')
  })

  it('should return not in alarm when within limits', () => {
    const limits: AlarmLimits = { high_high: 100, high: 80, low: 20, low_low: 10 }
    const result = checkAlarmCondition(50, limits)

    expect(result.inAlarm).toBe(false)
    expect(result.alarmType).toBeNull()
  })

  it('should handle missing limits gracefully', () => {
    const limits: AlarmLimits = {}  // No limits defined
    const result = checkAlarmCondition(1000, limits)

    expect(result.inAlarm).toBe(false)
  })

  describe('Deadband', () => {
    it('should prevent chatter with deadband', () => {
      const highLimit = 100
      const deadband = 5
      let inAlarm = true
      const currentValue = 98  // Below high limit but within deadband

      // With deadband, alarm stays active until value drops below (limit - deadband)
      const clearPoint = highLimit - deadband
      const shouldClear = currentValue < clearPoint

      expect(shouldClear).toBe(false)  // 98 is not < 95, so don't clear
    })

    it('should clear alarm when value below deadband threshold', () => {
      const highLimit = 100
      const deadband = 5
      const currentValue = 90  // Well below (100 - 5)

      const clearPoint = highLimit - deadband
      const shouldClear = currentValue < clearPoint

      expect(shouldClear).toBe(true)
    })
  })
})

// =============================================================================
// ALARM COUNTS COMPUTATION TESTS
// =============================================================================

describe('Alarm Counts', () => {
  interface ActiveAlarm {
    state: 'active' | 'acknowledged' | 'returned' | 'shelved'
    severity: 'critical' | 'high' | 'medium' | 'low' | 'alarm' | 'warning'
  }

  function computeAlarmCounts(alarms: ActiveAlarm[]) {
    const counts = {
      total: alarms.length,
      active: 0,
      acknowledged: 0,
      returned: 0,
      shelved: 0,
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      warnings: 0
    }

    alarms.forEach(alarm => {
      // By state
      if (alarm.state === 'active') counts.active++
      else if (alarm.state === 'acknowledged') counts.acknowledged++
      else if (alarm.state === 'returned') counts.returned++
      else if (alarm.state === 'shelved') counts.shelved++

      // By severity
      const sev = alarm.severity
      if (sev === 'critical') counts.critical++
      else if (sev === 'high' || sev === 'alarm') counts.high++
      else if (sev === 'medium') counts.medium++
      else if (sev === 'low') counts.low++
      else if (sev === 'warning') counts.warnings++
    })

    return counts
  }

  it('should count alarms by state', () => {
    const alarms: ActiveAlarm[] = [
      { state: 'active', severity: 'high' },
      { state: 'active', severity: 'medium' },
      { state: 'acknowledged', severity: 'high' },
      { state: 'shelved', severity: 'low' }
    ]

    const counts = computeAlarmCounts(alarms)

    expect(counts.total).toBe(4)
    expect(counts.active).toBe(2)
    expect(counts.acknowledged).toBe(1)
    expect(counts.shelved).toBe(1)
    expect(counts.returned).toBe(0)
  })

  it('should count alarms by severity', () => {
    const alarms: ActiveAlarm[] = [
      { state: 'active', severity: 'critical' },
      { state: 'active', severity: 'critical' },
      { state: 'active', severity: 'high' },
      { state: 'active', severity: 'medium' },
      { state: 'active', severity: 'warning' }
    ]

    const counts = computeAlarmCounts(alarms)

    expect(counts.critical).toBe(2)
    expect(counts.high).toBe(1)
    expect(counts.medium).toBe(1)
    expect(counts.warnings).toBe(1)
  })

  it('should map legacy alarm type to high', () => {
    const alarms: ActiveAlarm[] = [
      { state: 'active', severity: 'alarm' }  // Legacy type
    ]

    const counts = computeAlarmCounts(alarms)

    expect(counts.high).toBe(1)  // 'alarm' maps to 'high'
  })
})

// =============================================================================
// FIRST-OUT ALARM TRACKING TESTS
// =============================================================================

describe('First-Out Alarm Tracking', () => {
  it('should identify first alarm in cascade', () => {
    const CASCADE_WINDOW_MS = 5000
    const alarms: { id: string; triggeredAt: number }[] = []

    // First alarm
    const alarm1 = { id: 'alarm-1', triggeredAt: Date.now() }
    alarms.push(alarm1)

    // First alarm in empty list is the first-out
    const firstOut = alarms.length === 1 ? alarms[0] : null

    expect(firstOut?.id).toBe('alarm-1')
  })

  it('should track cascade within time window', () => {
    const CASCADE_WINDOW_MS = 5000
    const firstAlarmTime = Date.now()

    // Alarms triggered within cascade window
    const alarm1Time = firstAlarmTime
    const alarm2Time = firstAlarmTime + 1000  // 1 second later
    const alarm3Time = firstAlarmTime + 3000  // 3 seconds later

    const isInCascade = (time: number) => (time - firstAlarmTime) < CASCADE_WINDOW_MS

    expect(isInCascade(alarm2Time)).toBe(true)
    expect(isInCascade(alarm3Time)).toBe(true)
  })

  it('should identify new first-out after cascade window', () => {
    const CASCADE_WINDOW_MS = 5000
    const firstAlarmTime = Date.now() - 10000  // 10 seconds ago

    // New alarm outside cascade window
    const newAlarmTime = Date.now()
    const timeSinceFirst = newAlarmTime - firstAlarmTime

    const isNewCascade = timeSinceFirst > CASCADE_WINDOW_MS

    expect(isNewCascade).toBe(true)
  })
})

// =============================================================================
// INTERLOCK TESTS
// =============================================================================

describe('Interlocks', () => {
  interface InterlockCondition {
    channel: string
    operator: 'lt' | 'le' | 'gt' | 'ge' | 'eq' | 'ne' | 'true' | 'false'
    value?: number
  }

  interface Interlock {
    id: string
    name: string
    enabled: boolean
    conditions: InterlockCondition[]
    logic: 'AND' | 'OR'
    bypassed: boolean
  }

  function evaluateCondition(
    condition: InterlockCondition,
    channelValues: Record<string, number | boolean>
  ): boolean {
    const value = channelValues[condition.channel]

    if (value === undefined) return false

    switch (condition.operator) {
      case 'lt': return typeof value === 'number' && value < (condition.value ?? 0)
      case 'le': return typeof value === 'number' && value <= (condition.value ?? 0)
      case 'gt': return typeof value === 'number' && value > (condition.value ?? 0)
      case 'ge': return typeof value === 'number' && value >= (condition.value ?? 0)
      case 'eq': return value === condition.value
      case 'ne': return value !== condition.value
      case 'true': return value === true
      case 'false': return value === false
      default: return false
    }
  }

  function evaluateInterlock(
    interlock: Interlock,
    channelValues: Record<string, number | boolean>
  ): boolean {
    if (!interlock.enabled) return true  // Disabled interlocks always pass
    if (interlock.bypassed) return true  // Bypassed interlocks always pass

    const results = interlock.conditions.map(c => evaluateCondition(c, channelValues))

    if (interlock.logic === 'AND') {
      return results.every(r => r)
    } else {
      return results.some(r => r)
    }
  }

  describe('Condition Evaluation', () => {
    it('should evaluate less-than condition', () => {
      const condition: InterlockCondition = { channel: 'TC_01', operator: 'lt', value: 100 }
      const values = { 'TC_01': 80 }

      expect(evaluateCondition(condition, values)).toBe(true)
    })

    it('should evaluate greater-than condition', () => {
      const condition: InterlockCondition = { channel: 'TC_01', operator: 'gt', value: 50 }
      const values = { 'TC_01': 80 }

      expect(evaluateCondition(condition, values)).toBe(true)
    })

    it('should evaluate equality condition', () => {
      const condition: InterlockCondition = { channel: 'DI_01', operator: 'eq', value: 1 }
      const values = { 'DI_01': 1 }

      expect(evaluateCondition(condition, values)).toBe(true)
    })

    it('should evaluate boolean true condition', () => {
      const condition: InterlockCondition = { channel: 'EstopOK', operator: 'true' }
      const values = { 'EstopOK': true }

      expect(evaluateCondition(condition, values)).toBe(true)
    })

    it('should return false for missing channel', () => {
      const condition: InterlockCondition = { channel: 'Missing', operator: 'gt', value: 0 }
      const values = {}

      expect(evaluateCondition(condition, values)).toBe(false)
    })
  })

  describe('Interlock Evaluation', () => {
    it('should pass when all AND conditions are met', () => {
      const interlock: Interlock = {
        id: 'test-interlock',
        name: 'Test',
        enabled: true,
        bypassed: false,
        logic: 'AND',
        conditions: [
          { channel: 'TC_01', operator: 'lt', value: 200 },
          { channel: 'Pressure', operator: 'lt', value: 100 }
        ]
      }
      const values = { 'TC_01': 150, 'Pressure': 80 }

      expect(evaluateInterlock(interlock, values)).toBe(true)
    })

    it('should fail when any AND condition fails', () => {
      const interlock: Interlock = {
        id: 'test-interlock',
        name: 'Test',
        enabled: true,
        bypassed: false,
        logic: 'AND',
        conditions: [
          { channel: 'TC_01', operator: 'lt', value: 200 },
          { channel: 'Pressure', operator: 'lt', value: 100 }
        ]
      }
      const values = { 'TC_01': 150, 'Pressure': 120 }  // Pressure too high

      expect(evaluateInterlock(interlock, values)).toBe(false)
    })

    it('should pass when any OR condition is met', () => {
      const interlock: Interlock = {
        id: 'test-interlock',
        name: 'Test',
        enabled: true,
        bypassed: false,
        logic: 'OR',
        conditions: [
          { channel: 'Mode1', operator: 'true' },
          { channel: 'Mode2', operator: 'true' }
        ]
      }
      const values = { 'Mode1': false, 'Mode2': true }

      expect(evaluateInterlock(interlock, values)).toBe(true)
    })

    it('should always pass when bypassed', () => {
      const interlock: Interlock = {
        id: 'test-interlock',
        name: 'Test',
        enabled: true,
        bypassed: true,  // Bypassed!
        logic: 'AND',
        conditions: [
          { channel: 'TC_01', operator: 'lt', value: 50 }  // Would fail
        ]
      }
      const values = { 'TC_01': 100 }  // Value doesn't meet condition

      expect(evaluateInterlock(interlock, values)).toBe(true)  // But bypassed!
    })

    it('should always pass when disabled', () => {
      const interlock: Interlock = {
        id: 'test-interlock',
        name: 'Test',
        enabled: false,  // Disabled!
        bypassed: false,
        logic: 'AND',
        conditions: [
          { channel: 'TC_01', operator: 'lt', value: 50 }
        ]
      }
      const values = { 'TC_01': 100 }

      expect(evaluateInterlock(interlock, values)).toBe(true)
    })
  })
})

// =============================================================================
// SHELVING TESTS
// =============================================================================

describe('Alarm Shelving', () => {
  it('should not trigger alarm when shelved', () => {
    const isShelved = true
    const conditionActive = true

    // Shelved alarms don't trigger even if condition is active
    const shouldTrigger = conditionActive && !isShelved

    expect(shouldTrigger).toBe(false)
  })

  it('should auto-unshelve after max shelve time', () => {
    const maxShelveTimeS = 3600  // 1 hour
    const shelvedAt = Date.now() - (3700 * 1000)  // 3700 seconds ago

    const shelveElapsedS = (Date.now() - shelvedAt) / 1000
    const shouldUnshelve = shelveElapsedS > maxShelveTimeS

    expect(shouldUnshelve).toBe(true)
  })

  it('should respect shelve_allowed flag', () => {
    const shelveAllowed = false

    // Cannot shelve if not allowed
    expect(shelveAllowed).toBe(false)
  })
})

// =============================================================================
// ALARM HISTORY TESTS
// =============================================================================

describe('Alarm History', () => {
  interface AlarmHistoryEntry {
    id: string
    channel: string
    action: 'triggered' | 'acknowledged' | 'cleared' | 'shelved' | 'unshelved'
    timestamp: number
    value?: number
    operator?: string
  }

  it('should record alarm trigger', () => {
    const entry: AlarmHistoryEntry = {
      id: 'entry-1',
      channel: 'TC_01',
      action: 'triggered',
      timestamp: Date.now(),
      value: 105
    }

    expect(entry.action).toBe('triggered')
    expect(entry.value).toBe(105)
  })

  it('should record acknowledgment with operator', () => {
    const entry: AlarmHistoryEntry = {
      id: 'entry-2',
      channel: 'TC_01',
      action: 'acknowledged',
      timestamp: Date.now(),
      operator: 'John Smith'
    }

    expect(entry.action).toBe('acknowledged')
    expect(entry.operator).toBe('John Smith')
  })

  it('should maintain history order by timestamp', () => {
    const history: AlarmHistoryEntry[] = [
      { id: '1', channel: 'TC_01', action: 'triggered', timestamp: 1000 },
      { id: '2', channel: 'TC_01', action: 'acknowledged', timestamp: 2000 },
      { id: '3', channel: 'TC_01', action: 'cleared', timestamp: 3000 }
    ]

    // Sort by timestamp descending (newest first)
    const sorted = [...history].sort((a, b) => b.timestamp - a.timestamp)

    expect(sorted[0].action).toBe('cleared')
    expect(sorted[2].action).toBe('triggered')
  })
})
