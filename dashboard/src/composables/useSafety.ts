/**
 * Enhanced Safety & Interlock System Composable
 *
 * Provides centralized management of:
 * - Alarm configurations with ISA-18.2 severity levels
 * - Active alarms with first-out tracking
 * - Latch behavior (auto-clear, latch, timed-latch)
 * - Shelving/suppression support
 * - Interlock definitions and status checking
 * - Alarm history and audit logging
 *
 * This composable uses a singleton pattern so state is shared across all components.
 */

import { ref, computed, watch, readonly } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'
import type {
  AlarmConfig,
  AlarmSeverityLevel,
  ActiveAlarm,
  AlarmHistoryEntry,
  AlarmCounts,
  Interlock,
  InterlockCondition,
  InterlockStatus,
  InterlockControlType
} from '../types'

// ============================================
// Singleton State (shared across all instances)
// ============================================

const alarmConfigs = ref<Record<string, AlarmConfig>>({})
const activeAlarms = ref<ActiveAlarm[]>([])
const alarmHistory = ref<AlarmHistoryEntry[]>([])
const interlocks = ref<Interlock[]>([])

// First-out tracking
const firstOutAlarmId = ref<string | null>(null)
const alarmSequence = ref(0)
const cascadeStartTime = ref<number | null>(null)
const CASCADE_WINDOW_MS = 5000  // 5 seconds

// Track if already initialized
let initialized = false

// ============================================
// Composable Factory
// ============================================

export function useSafety() {
  const store = useDashboardStore()
  const mqtt = useMqtt('nisystem')

  // ============================================
  // Alarm Configuration
  // ============================================

  function createDefaultAlarmConfig(channel: string): AlarmConfig {
    const channelConfig = store.channels[channel]
    return {
      id: `alarm-${channel}`,
      channel,
      name: channelConfig?.display_name || channel,
      description: '',
      enabled: false,
      severity: 'medium' as AlarmSeverityLevel,
      // ISA-18.2 style thresholds
      high_high: channelConfig?.high_limit,
      high: channelConfig?.high_warning,
      low: channelConfig?.low_warning,
      low_low: channelConfig?.low_limit,
      // Legacy mappings
      high_alarm: channelConfig?.high_limit,
      low_alarm: channelConfig?.low_limit,
      high_warning: channelConfig?.high_warning,
      low_warning: channelConfig?.low_warning,
      // Filtering
      deadband: 0,
      on_delay_s: 0,
      off_delay_s: 0,
      delay_seconds: 0,
      // Behavior
      behavior: 'auto_clear',
      timed_latch_s: 60,
      // Actions
      log_to_file: true,
      play_sound: true,
      start_recording: false,
      run_script: undefined,
      // Grouping
      group: channelConfig?.group || '',
      priority: 0,
      // Shelving
      max_shelve_time_s: 3600,
      shelve_allowed: true
    }
  }

  // Initialize configs from channel configs
  function initializeAlarmConfigs() {
    Object.keys(store.channels).forEach(name => {
      if (!alarmConfigs.value[name]) {
        alarmConfigs.value[name] = createDefaultAlarmConfig(name)
      }
    })
  }

  // ============================================
  // Computed Alarm Stats
  // ============================================

  const alarmCounts = computed((): AlarmCounts => {
    const counts: AlarmCounts = {
      total: activeAlarms.value.length,
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

    activeAlarms.value.forEach(alarm => {
      // Count by state
      if (alarm.state === 'active') counts.active++
      else if (alarm.state === 'acknowledged') counts.acknowledged++
      else if (alarm.state === 'returned') counts.returned++
      else if (alarm.state === 'shelved') counts.shelved++

      // Count by severity
      const sev = alarm.severity
      if (sev === 'critical') counts.critical++
      else if (sev === 'high' || sev === 'alarm') counts.high++
      else if (sev === 'medium') counts.medium++
      else if (sev === 'low' || sev === 'warning') {
        counts.low++
        counts.warnings = (counts.warnings || 0) + 1
      }
    })

    return counts
  })

  const hasActiveAlarms = computed(() =>
    activeAlarms.value.some(a => a.state === 'active' && (a.severity === 'critical' || a.severity === 'high' || a.severity === 'alarm'))
  )

  const hasActiveWarnings = computed(() =>
    activeAlarms.value.some(a => a.state === 'active' && (a.severity === 'medium' || a.severity === 'low' || a.severity === 'warning'))
  )

  const latchedAlarmCount = computed(() => {
    return activeAlarms.value.filter(alarm => {
      const config = alarmConfigs.value[alarm.channel]
      return config?.behavior === 'latch' || config?.behavior === 'timed_latch'
    }).length
  })

  const hasLatchedAlarms = computed(() => latchedAlarmCount.value > 0)

  // Get first-out alarm (root cause indicator)
  const firstOutAlarm = computed(() => {
    if (firstOutAlarmId.value) {
      return activeAlarms.value.find(a => a.id === firstOutAlarmId.value || a.alarm_id === firstOutAlarmId.value)
    }
    return activeAlarms.value.find(a => a.is_first_out)
  })

  // Get alarms grouped by severity
  const alarmsBySeverity = computed(() => {
    const groups: Record<string, ActiveAlarm[]> = {
      critical: [],
      high: [],
      medium: [],
      low: []
    }

    activeAlarms.value.forEach(alarm => {
      const sev = alarm.severity === 'alarm' ? 'high' : alarm.severity === 'warning' ? 'medium' : alarm.severity
      if (groups[sev]) {
        groups[sev].push(alarm)
      }
    })

    // Sort each group by sequence (first-out first)
    Object.values(groups).forEach(g => g.sort((a, b) => (a.sequence_number || 0) - (b.sequence_number || 0)))

    return groups
  })

  // Get shelved alarms
  const shelvedAlarms = computed(() =>
    activeAlarms.value.filter(a => a.state === 'shelved')
  )

  // ============================================
  // Alarm Actions
  // ============================================

  function acknowledgeAlarm(alarmId: string, user: string = 'User') {
    const alarm = activeAlarms.value.find(a => a.id === alarmId)
    if (alarm && (alarm.state === 'active' || alarm.state === 'returned')) {
      alarm.state = 'acknowledged'
      alarm.acknowledged_at = new Date().toISOString()
      alarm.acknowledged_by = user

      // Notify backend
      mqtt.sendCommand('alarm/acknowledge', {
        alarm_id: alarmId,
        user
      })

      // Log to history
      addHistoryEntry({
        id: `${alarmId}-ack-${Date.now()}`,
        alarm_id: alarmId,
        channel: alarm.channel,
        event_type: 'acknowledged',
        severity: alarm.severity,
        value: alarm.current_value || alarm.value,
        triggered_at: alarm.triggered_at,
        user,
        message: `Acknowledged by ${user}`
      })
    }
  }

  function acknowledgeAll(user: string = 'User', severityFilter?: AlarmSeverityLevel) {
    activeAlarms.value.forEach(alarm => {
      if (alarm.state === 'active' || alarm.state === 'returned') {
        if (!severityFilter || alarm.severity === severityFilter) {
          acknowledgeAlarm(alarm.id, user)
        }
      }
    })
  }

  function clearAlarm(alarmId: string) {
    const alarmIndex = activeAlarms.value.findIndex(a => a.id === alarmId)
    if (alarmIndex >= 0) {
      const alarm = activeAlarms.value[alarmIndex]
      if (!alarm) return

      // Add to history
      addHistoryEntry({
        id: `${alarmId}-cleared-${Date.now()}`,
        alarm_id: alarm.alarm_id || alarmId,
        channel: alarm.channel,
        event_type: 'cleared',
        severity: alarm.severity,
        value: alarm.current_value || alarm.value,
        threshold: alarm.threshold,
        threshold_type: alarm.threshold_type,
        triggered_at: alarm.triggered_at,
        cleared_at: new Date().toISOString(),
        duration_seconds: alarm.duration_seconds,
        message: alarm.message
      })

      // Remove from active
      activeAlarms.value.splice(alarmIndex, 1)

      // Clear first-out if this was it
      if (firstOutAlarmId.value === alarmId) {
        firstOutAlarmId.value = null
        cascadeStartTime.value = null
      }
    }
  }

  function resetAlarm(alarmId: string, user: string = 'User') {
    const alarm = activeAlarms.value.find(a => a.id === alarmId)
    if (!alarm) return

    // Notify backend
    mqtt.sendCommand('alarm/reset', {
      alarm_id: alarmId,
      user
    })

    // Log reset event
    addHistoryEntry({
      id: `${alarmId}-reset-${Date.now()}`,
      alarm_id: alarmId,
      channel: alarm.channel,
      event_type: 'reset',
      severity: alarm.severity,
      value: alarm.current_value || alarm.value,
      triggered_at: alarm.triggered_at,
      user,
      message: `Reset by ${user}`
    })

    clearAlarm(alarmId)
  }

  function resetAllLatched(user: string = 'User') {
    const latchedAlarms = activeAlarms.value.filter(alarm => {
      const config = alarmConfigs.value[alarm.channel]
      return config?.behavior === 'latch' || config?.behavior === 'timed_latch'
    })
    latchedAlarms.forEach(alarm => resetAlarm(alarm.id, user))
  }

  function shelveAlarm(alarmId: string, user: string, reason: string = '', durationS: number = 3600) {
    const alarm = activeAlarms.value.find(a => a.id === alarmId)
    if (!alarm) return false

    const config = alarmConfigs.value[alarm.channel]
    if (config && config.shelve_allowed === false) {
      console.warn(`Shelving not allowed for alarm ${alarmId}`)
      return false
    }

    // Limit duration
    const maxDuration = config?.max_shelve_time_s || 3600
    durationS = Math.min(durationS, maxDuration)

    alarm.state = 'shelved'
    alarm.shelved_at = new Date().toISOString()
    alarm.shelved_by = user
    alarm.shelve_expires_at = new Date(Date.now() + durationS * 1000).toISOString()
    alarm.shelve_reason = reason

    // Notify backend
    mqtt.sendCommand('alarm/shelve', {
      alarm_id: alarmId,
      user,
      reason,
      duration_s: durationS
    })

    // Log
    addHistoryEntry({
      id: `${alarmId}-shelved-${Date.now()}`,
      alarm_id: alarmId,
      channel: alarm.channel,
      event_type: 'shelved',
      severity: alarm.severity,
      value: alarm.current_value || alarm.value,
      triggered_at: alarm.triggered_at,
      user,
      message: `Shelved by ${user} for ${durationS}s: ${reason}`
    })

    return true
  }

  function unshelveAlarm(alarmId: string, user: string = 'User') {
    const alarm = activeAlarms.value.find(a => a.id === alarmId)
    if (!alarm || alarm.state !== 'shelved') return false

    // Revert to previous state
    alarm.state = alarm.acknowledged_at ? 'acknowledged' : 'active'
    alarm.shelved_at = undefined
    alarm.shelved_by = undefined
    alarm.shelve_expires_at = undefined
    alarm.shelve_reason = undefined

    // Notify backend
    mqtt.sendCommand('alarm/unshelve', {
      alarm_id: alarmId,
      user
    })

    // Log
    addHistoryEntry({
      id: `${alarmId}-unshelved-${Date.now()}`,
      alarm_id: alarmId,
      channel: alarm.channel,
      event_type: 'unshelved',
      severity: alarm.severity,
      value: alarm.current_value || alarm.value,
      triggered_at: alarm.triggered_at,
      user,
      message: `Unshelved by ${user}`
    })

    return true
  }

  // ============================================
  // Alarm Triggering (for frontend-based checking)
  // ============================================

  function triggerAlarm(alarm: ActiveAlarm) {
    // Determine first-out
    const now = Date.now()
    if (!firstOutAlarmId.value || (cascadeStartTime.value && now - cascadeStartTime.value > CASCADE_WINDOW_MS)) {
      // New cascade
      alarmSequence.value++
      firstOutAlarmId.value = alarm.id
      cascadeStartTime.value = now
      alarm.is_first_out = true
    }

    alarmSequence.value++
    alarm.sequence_number = alarmSequence.value

    activeAlarms.value.push(alarm)

    // Log to history
    addHistoryEntry({
      id: `${alarm.id}-triggered-${Date.now()}`,
      alarm_id: alarm.alarm_id || alarm.id,
      channel: alarm.channel,
      event_type: 'triggered',
      severity: alarm.severity,
      value: alarm.value,
      threshold: alarm.threshold,
      threshold_type: alarm.threshold_type,
      triggered_at: alarm.triggered_at,
      message: alarm.message
    })
  }

  // ============================================
  // History Management
  // ============================================

  function addHistoryEntry(entry: Partial<AlarmHistoryEntry>) {
    const fullEntry: AlarmHistoryEntry = {
      id: entry.id || `history-${Date.now()}`,
      alarm_id: entry.alarm_id,
      channel: entry.channel || '',
      event_type: entry.event_type || 'triggered',
      severity: entry.severity || 'medium',
      value: entry.value,
      threshold: entry.threshold,
      threshold_type: entry.threshold_type,
      triggered_at: entry.triggered_at || new Date().toISOString(),
      cleared_at: entry.cleared_at,
      duration_seconds: entry.duration_seconds,
      user: entry.user,
      acknowledged_by: entry.acknowledged_by || entry.user,
      message: entry.message || ''
    }

    alarmHistory.value.unshift(fullEntry)

    // Keep history limited
    if (alarmHistory.value.length > 1000) {
      alarmHistory.value = alarmHistory.value.slice(0, 1000)
    }
  }

  // ============================================
  // Interlock Management
  // ============================================

  function addInterlock(interlock: Omit<Interlock, 'id'>) {
    const newInterlock: Interlock = {
      ...interlock,
      id: `interlock-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    }
    interlocks.value.push(newInterlock)
    saveInterlocks()
    return newInterlock.id
  }

  function updateInterlock(id: string, updates: Partial<Interlock>) {
    const index = interlocks.value.findIndex(i => i.id === id)
    if (index >= 0) {
      const existing = interlocks.value[index]
      if (existing) {
        interlocks.value[index] = { ...existing, ...updates } as Interlock
        saveInterlocks()
      }
    }
  }

  function removeInterlock(id: string) {
    const index = interlocks.value.findIndex(i => i.id === id)
    if (index >= 0) {
      interlocks.value.splice(index, 1)
      saveInterlocks()
    }
  }

  function bypassInterlock(id: string, bypass: boolean, user: string = 'User') {
    const interlock = interlocks.value.find(i => i.id === id)
    if (interlock && interlock.bypassAllowed) {
      interlock.bypassed = bypass
      if (bypass) {
        interlock.bypassedAt = new Date().toISOString()
        interlock.bypassedBy = user
      } else {
        interlock.bypassedAt = undefined
        interlock.bypassedBy = undefined
      }
      saveInterlocks()
    }
  }

  // ============================================
  // Interlock Condition Evaluation
  // ============================================

  function evaluateCondition(condition: InterlockCondition): { satisfied: boolean; currentValue?: unknown; reason: string } {
    switch (condition.type) {
      case 'mqtt_connected':
        return {
          satisfied: mqtt.connected.value,
          currentValue: mqtt.connected.value,
          reason: mqtt.connected.value ? 'MQTT connected' : 'MQTT disconnected'
        }

      case 'daq_connected':
        const daqConnected = store.status?.status === 'online'
        return {
          satisfied: daqConnected,
          currentValue: daqConnected,
          reason: daqConnected ? 'DAQ online' : 'DAQ offline'
        }

      case 'acquiring':
        const isAcquiring = store.status?.acquiring ?? false
        return {
          satisfied: isAcquiring,
          currentValue: isAcquiring,
          reason: isAcquiring ? 'System acquiring' : 'System not acquiring'
        }

      case 'not_recording':
        const isRecording = store.status?.recording ?? false
        return {
          satisfied: !isRecording,
          currentValue: !isRecording,
          reason: !isRecording ? 'Not recording' : 'Currently recording'
        }

      case 'no_active_alarms':
        const noAlarms = !hasActiveAlarms.value
        return {
          satisfied: noAlarms,
          currentValue: alarmCounts.value.active,
          reason: noAlarms ? 'No active alarms' : `${alarmCounts.value.active} active alarm(s)`
        }

      case 'no_latched_alarms':
        const noLatched = !hasLatchedAlarms.value
        return {
          satisfied: noLatched,
          currentValue: latchedAlarmCount.value,
          reason: noLatched ? 'No latched alarms' : `${latchedAlarmCount.value} latched alarm(s) require reset`
        }

      case 'channel_value':
        if (!condition.channel || condition.operator === undefined || condition.value === undefined) {
          return { satisfied: false, reason: 'Invalid channel condition' }
        }
        const channelValue = store.values[condition.channel]?.value
        if (channelValue === undefined) {
          return { satisfied: false, currentValue: undefined, reason: `Channel ${condition.channel} has no value` }
        }
        const numValue = condition.value as number
        let satisfied = false
        switch (condition.operator) {
          case '<': satisfied = channelValue < numValue; break
          case '<=': satisfied = channelValue <= numValue; break
          case '>': satisfied = channelValue > numValue; break
          case '>=': satisfied = channelValue >= numValue; break
          case '=': satisfied = channelValue === numValue; break
          case '!=': satisfied = channelValue !== numValue; break
        }
        const channelName = store.channels[condition.channel]?.display_name || condition.channel
        return {
          satisfied,
          currentValue: channelValue,
          reason: satisfied
            ? `${channelName} = ${channelValue.toFixed(2)} (OK)`
            : `${channelName} = ${channelValue.toFixed(2)} (requires ${condition.operator} ${numValue})`
        }

      case 'digital_input':
        if (!condition.channel) {
          return { satisfied: false, reason: 'Invalid digital input condition' }
        }
        const diValue = store.values[condition.channel]?.value
        const expectedValue = condition.value === true || condition.value === 1
        const actualDiState = diValue === 1
        const diSatisfied = actualDiState === expectedValue
        const diName = store.channels[condition.channel]?.display_name || condition.channel
        return {
          satisfied: diSatisfied,
          currentValue: diValue,
          reason: diSatisfied
            ? `${diName} = ${actualDiState ? 'ON' : 'OFF'} (OK)`
            : `${diName} = ${actualDiState ? 'ON' : 'OFF'} (requires ${expectedValue ? 'ON' : 'OFF'})`
        }

      default:
        return { satisfied: false, reason: 'Unknown condition type' }
    }
  }

  function evaluateInterlock(interlock: Interlock): InterlockStatus {
    if (!interlock.enabled) {
      return {
        id: interlock.id,
        name: interlock.name,
        satisfied: true,
        bypassed: false,
        enabled: false,
        failedConditions: [],
        controls: interlock.controls
      }
    }

    if (interlock.bypassed) {
      return {
        id: interlock.id,
        name: interlock.name,
        satisfied: true,
        bypassed: true,
        enabled: true,
        failedConditions: [],
        controls: interlock.controls
      }
    }

    const failedConditions: InterlockStatus['failedConditions'] = []

    for (const condition of interlock.conditions) {
      const result = evaluateCondition(condition)
      if (!result.satisfied) {
        failedConditions.push({
          condition,
          currentValue: result.currentValue,
          reason: result.reason
        })
      }
    }

    return {
      id: interlock.id,
      name: interlock.name,
      satisfied: failedConditions.length === 0,
      bypassed: false,
      enabled: true,
      failedConditions,
      controls: interlock.controls
    }
  }

  // Get all interlock statuses
  const interlockStatuses = computed((): InterlockStatus[] => {
    return interlocks.value.map(evaluateInterlock)
  })

  // Check if a specific control type is blocked
  function isControlBlocked(controlType: InterlockControlType, identifier?: string): { blocked: boolean; blockedBy: InterlockStatus[] } {
    const blockedBy: InterlockStatus[] = []

    for (const status of interlockStatuses.value) {
      if (!status.satisfied && !status.bypassed && status.enabled) {
        for (const control of status.controls) {
          if (control.type === controlType) {
            if (controlType === 'digital_output' && identifier) {
              if (control.channel === identifier) {
                blockedBy.push(status)
              }
            } else if (controlType === 'button_action' && identifier) {
              if (control.buttonId === identifier) {
                blockedBy.push(status)
              }
            } else if (controlType !== 'digital_output' && controlType !== 'button_action') {
              blockedBy.push(status)
            }
          }
        }
      }
    }

    return { blocked: blockedBy.length > 0, blockedBy }
  }

  // Convenience methods for common checks
  const isScheduleBlocked = computed(() => isControlBlocked('schedule_enable'))
  const isRecordingBlocked = computed(() => isControlBlocked('recording_start'))
  const isAcquisitionBlocked = computed(() => isControlBlocked('acquisition_start'))

  function isOutputBlocked(channel: string) {
    return isControlBlocked('digital_output', channel)
  }

  function isButtonBlocked(buttonId: string) {
    return isControlBlocked('button_action', buttonId)
  }

  // ============================================
  // Persistence
  // ============================================

  function saveAlarmConfigs() {
    localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify(alarmConfigs.value))
  }

  function loadAlarmConfigs() {
    // Try v2 first, then fall back to v1
    let saved = localStorage.getItem('nisystem-alarm-configs-v2')
    if (!saved) {
      saved = localStorage.getItem('nisystem-alarm-configs')
    }
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        // Migrate old format if needed
        Object.entries(parsed).forEach(([channel, config]: [string, any]) => {
          if (!config.id) config.id = `alarm-${channel}`
          if (!config.name) config.name = channel
          if (!config.severity) config.severity = 'medium'
          if (config.on_delay_s === undefined) config.on_delay_s = config.delay_seconds || 0
          if (config.off_delay_s === undefined) config.off_delay_s = 0
        })
        Object.assign(alarmConfigs.value, parsed)
      } catch { /* ignore */ }
    }
  }

  function saveInterlocks() {
    localStorage.setItem('nisystem-interlocks', JSON.stringify(interlocks.value))
  }

  function loadInterlocks() {
    const saved = localStorage.getItem('nisystem-interlocks')
    if (saved) {
      try {
        interlocks.value = JSON.parse(saved)
      } catch { /* ignore */ }
    }
  }

  function saveHistory() {
    // Save last 500 entries
    const entries = alarmHistory.value.slice(0, 500)
    localStorage.setItem('nisystem-alarm-history', JSON.stringify(entries))
  }

  function loadHistory() {
    const saved = localStorage.getItem('nisystem-alarm-history')
    if (saved) {
      try {
        alarmHistory.value = JSON.parse(saved)
      } catch { /* ignore */ }
    }
  }

  // ============================================
  // Shelve Expiry Check
  // ============================================

  function checkShelveExpiry() {
    const now = new Date()
    activeAlarms.value.forEach(alarm => {
      if (alarm.state === 'shelved' && alarm.shelve_expires_at) {
        if (new Date(alarm.shelve_expires_at) <= now) {
          unshelveAlarm(alarm.id, 'System')
        }
      }
    })
  }

  // ============================================
  // Initialization
  // ============================================

  function initialize() {
    if (initialized) return

    // Load saved configs
    loadAlarmConfigs()
    loadInterlocks()
    loadHistory()

    // Watch for channel changes to add new configs
    watch(() => store.channels, () => {
      initializeAlarmConfigs()
    }, { immediate: true, deep: true })

    // Auto-save alarm configs on change
    watch(alarmConfigs, saveAlarmConfigs, { deep: true })

    // Auto-save history periodically
    watch(alarmHistory, () => {
      if (alarmHistory.value.length % 10 === 0) {
        saveHistory()
      }
    }, { deep: true })

    // Check shelve expiry every minute
    setInterval(checkShelveExpiry, 60000)

    initialized = true
  }

  // Initialize on first use
  initialize()

  // ============================================
  // Return Public API
  // ============================================

  return {
    // Alarm state (readonly to prevent direct mutation)
    alarmConfigs: readonly(alarmConfigs),
    activeAlarms: readonly(activeAlarms),
    alarmHistory: readonly(alarmHistory),
    alarmCounts,
    hasActiveAlarms,
    hasActiveWarnings,
    latchedAlarmCount,
    hasLatchedAlarms,
    firstOutAlarm,
    alarmsBySeverity,
    shelvedAlarms,

    // Alarm config mutation (for SafetyTab)
    updateAlarmConfig: (channel: string, config: Partial<AlarmConfig>) => {
      if (alarmConfigs.value[channel]) {
        Object.assign(alarmConfigs.value[channel], config)
      }
    },
    getAlarmConfig: (channel: string) => alarmConfigs.value[channel],

    // Alarm actions
    triggerAlarm,
    acknowledgeAlarm,
    acknowledgeAll,
    clearAlarm,
    resetAlarm,
    resetAllLatched,
    shelveAlarm,
    unshelveAlarm,

    // For alarm processing (used by SafetyTab)
    delayTimers: ref<Record<string, { type: string; startTime: number }>>({}),

    // Interlock state
    interlocks: readonly(interlocks),
    interlockStatuses,

    // Interlock management
    addInterlock,
    updateInterlock,
    removeInterlock,
    bypassInterlock,

    // Interlock checking
    isControlBlocked,
    isScheduleBlocked,
    isRecordingBlocked,
    isAcquisitionBlocked,
    isOutputBlocked,
    isButtonBlocked,
    evaluateCondition
  }
}
