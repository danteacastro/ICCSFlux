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
  InterlockControlType,
  SafetyAction,
  SafetyActionType
} from '../types'

// ============================================
// Singleton State (shared across all instances)
// ============================================

const alarmConfigs = ref<Record<string, AlarmConfig>>({})
const activeAlarms = ref<ActiveAlarm[]>([])
const alarmHistory = ref<AlarmHistoryEntry[]>([])
const interlocks = ref<Interlock[]>([])

// Safety Actions Registry (ISA-18.2 automatic responses)
const safetyActions = ref<Record<string, SafetyAction>>({})

// Auto-execute safety actions (configurable)
const autoExecuteSafetyActions = ref(true)

// First-out tracking
const firstOutAlarmId = ref<string | null>(null)
const alarmSequence = ref(0)
const cascadeStartTime = ref<number | null>(null)
const CASCADE_WINDOW_MS = 5000  // 5 seconds

// Track if already initialized
let initialized = false

// Track current project to detect changes
let currentProjectId: string | null = null

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
      name: channel,  // TAG is the only identifier
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

  /**
   * Clear ALL active alarms - used when project is unloaded or channels change significantly
   * @param addToHistory If true, add "cleared" entries to history for each alarm
   */
  function clearAllAlarms(addToHistory: boolean = false) {
    console.log(`[SAFETY] Clearing all ${activeAlarms.value.length} active alarms`)

    if (addToHistory) {
      // Log each alarm being cleared
      activeAlarms.value.forEach(alarm => {
        addHistoryEntry({
          id: `${alarm.id}-cleared-${Date.now()}`,
          alarm_id: alarm.alarm_id || alarm.id,
          channel: alarm.channel,
          event_type: 'cleared',
          severity: alarm.severity,
          value: alarm.current_value || alarm.value,
          triggered_at: alarm.triggered_at,
          cleared_at: new Date().toISOString(),
          message: 'Cleared due to project/channel change'
        })
      })
    }

    // Clear all active alarms
    activeAlarms.value = []

    // Reset first-out tracking
    firstOutAlarmId.value = null
    cascadeStartTime.value = null
    alarmSequence.value = 0
  }

  /**
   * Clear ALL safety state - alarms, configs, history, and localStorage
   * Called when project changes or is closed to ensure no ghost/stale state
   */
  function clearAllSafetyState(reason: string = 'project_change') {
    console.log(`[SAFETY] Clearing ALL safety state, reason: ${reason}`)

    // Clear active alarms (don't add to history since we're clearing history too)
    activeAlarms.value = []

    // Clear alarm configs (will be rebuilt from new project channels)
    alarmConfigs.value = {}

    // Clear history
    alarmHistory.value = []

    // Clear interlocks
    interlocks.value = []

    // Clear safety actions
    safetyActions.value = {}

    // Reset auto-execute flag to default
    autoExecuteSafetyActions.value = true

    // Reset first-out tracking
    firstOutAlarmId.value = null
    cascadeStartTime.value = null
    alarmSequence.value = 0

    // Reset trip state
    isTripped.value = false
    lastTripTime.value = null
    lastTripReason.value = null

    // Reset safe state config
    safeStateConfig.value = {
      resetDigitalOutputs: true,
      resetAnalogOutputs: false,
      safeDigitalState: false,
      safeAnalogState: 0.0,
      specificOutputs: []
    }

    // Clear localStorage to prevent reload of stale data
    try {
      localStorage.removeItem('nisystem-alarm-configs')
      localStorage.removeItem('nisystem-alarm-configs-v2')
      localStorage.removeItem('nisystem-alarm-history')
      localStorage.removeItem('nisystem-interlocks')
      localStorage.removeItem('nisystem-safety-actions')
      localStorage.removeItem('nisystem-safe-state-config')
      localStorage.removeItem('nisystem-auto-execute-safety-actions')
      console.log('[SAFETY] Cleared all localStorage safety/alarm data')
    } catch (e) {
      console.warn('[SAFETY] Failed to clear localStorage:', e)
    }
  }

  /**
   * Clear alarms for channels that no longer exist in the project
   */
  function clearOrphanedAlarms() {
    const validChannels = new Set(Object.keys(store.channels))
    const orphanedAlarms = activeAlarms.value.filter(a => !validChannels.has(a.channel))

    if (orphanedAlarms.length > 0) {
      console.log(`[SAFETY] Clearing ${orphanedAlarms.length} orphaned alarms for removed channels`)

      orphanedAlarms.forEach(alarm => {
        addHistoryEntry({
          id: `${alarm.id}-cleared-${Date.now()}`,
          alarm_id: alarm.alarm_id || alarm.id,
          channel: alarm.channel,
          event_type: 'cleared',
          severity: alarm.severity,
          value: alarm.current_value || alarm.value,
          triggered_at: alarm.triggered_at,
          cleared_at: new Date().toISOString(),
          message: 'Channel removed from project'
        })
      })

      // Remove orphaned alarms
      activeAlarms.value = activeAlarms.value.filter(a => validChannels.has(a.channel))

      // Clear first-out if it was orphaned
      if (firstOutAlarmId.value) {
        const firstOutExists = activeAlarms.value.some(
          a => a.id === firstOutAlarmId.value || a.alarm_id === firstOutAlarmId.value
        )
        if (!firstOutExists) {
          firstOutAlarmId.value = null
          cascadeStartTime.value = null
        }
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
        return {
          satisfied,
          currentValue: channelValue,
          reason: satisfied
            ? `${condition.channel} = ${channelValue.toFixed(2)} (OK)`
            : `${condition.channel} = ${channelValue.toFixed(2)} (requires ${condition.operator} ${numValue})`
        }

      case 'digital_input':
        if (!condition.channel) {
          return { satisfied: false, reason: 'Invalid digital input condition' }
        }
        const diValue = store.values[condition.channel]?.value
        const rawDiState = diValue === 1
        // Apply invert logic (for NC sensors: invert=true means ON when signal is LOW)
        const actualDiState = condition.invert ? !rawDiState : rawDiState
        const expectedValue = condition.value === true || condition.value === 1
        const diSatisfied = actualDiState === expectedValue
        const invertNote = condition.invert ? ' [inverted]' : ''
        return {
          satisfied: diSatisfied,
          currentValue: diValue,
          reason: diSatisfied
            ? `${condition.channel} = ${actualDiState ? 'ON' : 'OFF'}${invertNote} (OK)`
            : `${condition.channel} = ${actualDiState ? 'ON' : 'OFF'}${invertNote} (requires ${expectedValue ? 'ON' : 'OFF'})`
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
  // Interlock Trip System
  // ============================================

  // Check if any enabled interlock has failed (not satisfied and not bypassed)
  const hasFailedInterlocks = computed(() => {
    return interlockStatuses.value.some(s => s.enabled && !s.satisfied && !s.bypassed)
  })

  // Get all failed interlocks
  const failedInterlocks = computed(() => {
    return interlockStatuses.value.filter(s => s.enabled && !s.satisfied && !s.bypassed)
  })

  // Track which interlock actions have been executed (to avoid repeated execution)
  const executedInterlockActions = ref<Set<string>>(new Set())

  /**
   * Execute active control actions for a failed interlock
   * Called when an interlock transitions from satisfied to failed
   */
  function executeInterlockActions(interlockStatus: InterlockStatus) {
    const interlock = interlocks.value.find(i => i.id === interlockStatus.id)
    if (!interlock) return

    console.log(`[SAFETY] Executing actions for failed interlock: ${interlock.name}`)

    for (const control of interlock.controls) {
      // Create unique key for this action
      const actionKey = `${interlock.id}-${control.type}-${control.channel || ''}`

      // Skip if already executed (prevents repeated execution while interlock stays failed)
      if (executedInterlockActions.value.has(actionKey)) {
        continue
      }

      switch (control.type) {
        case 'set_digital_output':
          if (control.channel) {
            const value = control.setValue ?? 0
            console.log(`[SAFETY] Setting DO ${control.channel} to ${value}`)
            mqtt.setOutput(control.channel, value)
            executedInterlockActions.value.add(actionKey)
          }
          break

        case 'set_analog_output':
          if (control.channel) {
            const value = control.setValue ?? 0
            console.log(`[SAFETY] Setting AO ${control.channel} to ${value}`)
            mqtt.setOutput(control.channel, value)
            executedInterlockActions.value.add(actionKey)
          }
          break

        case 'stop_session':
          console.log(`[SAFETY] Stopping session`)
          mqtt.sendCommand('test-session/stop', {})
          executedInterlockActions.value.add(actionKey)
          break

        case 'stop_acquisition':
          console.log(`[SAFETY] Stopping acquisition`)
          mqtt.sendCommand('acquisition/stop', {})
          executedInterlockActions.value.add(actionKey)
          break

        // BLOCKING actions don't need execution - they just prevent user actions
        case 'digital_output':
        case 'schedule_enable':
        case 'recording_start':
        case 'acquisition_start':
        case 'button_action':
          // These are handled by isControlBlocked()
          break
      }
    }
  }

  /**
   * Clear executed action tracking when interlock becomes satisfied again
   */
  function clearInterlockActionTracking(interlockId: string) {
    const keysToRemove: string[] = []
    executedInterlockActions.value.forEach(key => {
      if (key.startsWith(interlockId + '-')) {
        keysToRemove.push(key)
      }
    })
    keysToRemove.forEach(key => executedInterlockActions.value.delete(key))
  }

  // Watch for interlock status changes and execute actions on failure
  watch(interlockStatuses, (newStatuses, oldStatuses) => {
    if (!oldStatuses) return

    for (const status of newStatuses) {
      const oldStatus = oldStatuses.find(s => s.id === status.id)

      // Interlock just failed (was satisfied, now not satisfied)
      if (oldStatus?.satisfied && !status.satisfied && status.enabled && !status.bypassed) {
        executeInterlockActions(status)
      }

      // Interlock just became satisfied again - clear tracking
      if (!oldStatus?.satisfied && status.satisfied) {
        clearInterlockActionTracking(status.id)
      }
    }
  }, { deep: true })

  // Trip state
  const isTripped = ref(false)
  const lastTripTime = ref<string | null>(null)
  const lastTripReason = ref<string | null>(null)

  // Safe state configuration (which outputs to reset on trip)
  const safeStateConfig = ref<{
    resetDigitalOutputs: boolean
    resetAnalogOutputs: boolean
    stopSession: boolean
    digitalOutputChannels: string[]  // Empty = all DO channels
    analogOutputChannels: string[]   // Empty = all AO channels
    analogSafeValue: number          // Default safe value for AO (usually 0)
  }>({
    resetDigitalOutputs: true,
    resetAnalogOutputs: true,
    stopSession: true,
    digitalOutputChannels: [],  // All by default
    analogOutputChannels: [],   // All by default
    analogSafeValue: 0
  })

  // Load safe state config from localStorage
  function loadSafeStateConfig() {
    const saved = localStorage.getItem('nisystem-safe-state-config')
    if (saved) {
      try {
        Object.assign(safeStateConfig.value, JSON.parse(saved))
      } catch { /* ignore */ }
    }
  }

  // Save safe state config
  function saveSafeStateConfig() {
    localStorage.setItem('nisystem-safe-state-config', JSON.stringify(safeStateConfig.value))
  }

  // Update safe state config
  function updateSafeStateConfig(config: Partial<typeof safeStateConfig.value>) {
    Object.assign(safeStateConfig.value, config)
    saveSafeStateConfig()
  }

  /**
   * Trip the system - set all outputs to safe state
   * Called when an interlock fails while latch is armed
   */
  function tripSystem(reason: string) {
    console.log(`[SAFETY] SYSTEM TRIP: ${reason}`)

    isTripped.value = true
    lastTripTime.value = new Date().toISOString()
    lastTripReason.value = reason

    const config = safeStateConfig.value

    // Stop session first
    if (config.stopSession) {
      mqtt.sendCommand('test-session/stop', {})
    }

    // Reset digital outputs to OFF
    if (config.resetDigitalOutputs) {
      const doChannels = config.digitalOutputChannels.length > 0
        ? config.digitalOutputChannels
        : Object.keys(store.channels).filter(ch => store.channels[ch]?.channel_type === 'digital_output')

      for (const channel of doChannels) {
        mqtt.setOutput(channel, 0)
      }
    }

    // Reset analog outputs to safe value
    if (config.resetAnalogOutputs) {
      const aoChannels = config.analogOutputChannels.length > 0
        ? config.analogOutputChannels
        : Object.keys(store.channels).filter(ch => store.channels[ch]?.channel_type === 'analog_output')

      for (const channel of aoChannels) {
        mqtt.setOutput(channel, config.analogSafeValue)
      }
    }

    // Publish trip event
    mqtt.sendCommand('safety/trip', {
      reason,
      timestamp: lastTripTime.value,
      resetDigitalOutputs: config.resetDigitalOutputs,
      resetAnalogOutputs: config.resetAnalogOutputs,
      stoppedSession: config.stopSession
    })
  }

  /**
   * Reset the trip state (after operator acknowledges and clears interlocks)
   */
  function resetTrip() {
    if (hasFailedInterlocks.value) {
      console.log('[SAFETY] Cannot reset trip - interlocks still failed')
      return false
    }
    isTripped.value = false
    lastTripReason.value = null
    console.log('[SAFETY] Trip state reset')
    return true
  }

  // Load safe state config on init
  loadSafeStateConfig()

  // ============================================
  // Safety Action Management (ISA-18.2)
  // ============================================

  function addSafetyAction(action: Omit<SafetyAction, 'id'>): string {
    const id = `safety-action-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    const newAction: SafetyAction = {
      ...action,
      id
    }
    safetyActions.value[id] = newAction
    saveSafetyActions()
    return id
  }

  function updateSafetyAction(id: string, updates: Partial<SafetyAction>) {
    if (safetyActions.value[id]) {
      Object.assign(safetyActions.value[id], updates)
      saveSafetyActions()
    }
  }

  function removeSafetyAction(id: string) {
    if (safetyActions.value[id]) {
      delete safetyActions.value[id]
      saveSafetyActions()
    }
  }

  function getSafetyAction(id: string): SafetyAction | undefined {
    return safetyActions.value[id]
  }

  /**
   * Execute a safety action (triggered by alarm or manually)
   * This is the frontend execution - backend publishes 'safety_action' via MQTT
   */
  function executeSafetyAction(actionId: string, triggeredBy?: string) {
    const action = safetyActions.value[actionId]
    if (!action || !action.enabled) {
      console.warn(`[SAFETY] Cannot execute safety action ${actionId}: not found or disabled`)
      return false
    }

    console.warn(`[SAFETY] EXECUTING SAFETY ACTION: ${action.name} (${action.type})`)

    // Update last triggered info
    action.lastTriggeredAt = new Date().toISOString()
    action.lastTriggeredBy = triggeredBy

    switch (action.type) {
      case 'trip_system':
        // Full system trip - set all outputs to safe state
        tripSystem(`Safety action: ${action.name}`)
        break

      case 'stop_session':
        // Stop test session only
        mqtt.sendCommand('test-session/stop', {})
        break

      case 'stop_recording':
        // Stop recording only
        mqtt.sendCommand('recording/stop', {})
        break

      case 'set_output_safe':
        // Set specific outputs to safe state
        if (action.outputChannels) {
          for (const channel of action.outputChannels) {
            const channelConfig = store.channels[channel]
            if (channelConfig?.channel_type === 'digital_output') {
              mqtt.setOutput(channel, action.safeValue ?? 0)
            } else if (channelConfig?.channel_type === 'analog_output') {
              mqtt.setOutput(channel, action.analogSafeValue ?? 0)
            }
          }
        }
        break

      case 'run_sequence':
        // Run a safety sequence
        if (action.sequenceId) {
          mqtt.sendCommand('sequence/start', { sequenceId: action.sequenceId })
        }
        break

      case 'custom':
        // Custom MQTT action
        if (action.mqttTopic) {
          mqtt.sendCommand(action.mqttTopic, action.mqttPayload || {})
        }
        break
    }

    saveSafetyActions()
    return true
  }

  function saveSafetyActions() {
    localStorage.setItem('nisystem-safety-actions', JSON.stringify(safetyActions.value))
  }

  function loadSafetyActions() {
    const saved = localStorage.getItem('nisystem-safety-actions')
    if (saved) {
      try {
        safetyActions.value = JSON.parse(saved)
      } catch { /* ignore */ }
    }
  }

  // Toggle auto-execute mode
  function setAutoExecuteSafetyActions(enabled: boolean) {
    autoExecuteSafetyActions.value = enabled
    localStorage.setItem('nisystem-auto-execute-safety-actions', String(enabled))
  }

  function loadAutoExecuteSetting() {
    const saved = localStorage.getItem('nisystem-auto-execute-safety-actions')
    if (saved !== null) {
      autoExecuteSafetyActions.value = saved === 'true'
    }
  }

  // Load safety actions on init
  loadSafetyActions()
  loadAutoExecuteSetting()

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

    // Subscribe to project events FIRST (before loading localStorage)
    // This ensures we handle project changes before loading potentially stale data

    // Subscribe to project/loaded to clear state on project change
    mqtt.subscribe('nisystem/nodes/+/project/loaded', (payload: any) => {
      const newProjectName = payload?.project_name || payload?.filename || 'unknown'
      console.log(`[SAFETY] Project loaded: ${newProjectName}, previous: ${currentProjectId}`)

      // If project changed, clear ALL state
      if (currentProjectId !== null && currentProjectId !== newProjectName) {
        console.log('[SAFETY] Project changed, clearing all safety state')
        clearAllSafetyState('project_changed')
      }

      currentProjectId = newProjectName
      // Initialize alarm configs for new project's channels
      initializeAlarmConfigs()
    })

    // Subscribe to project/closed to clear state
    mqtt.subscribe('nisystem/nodes/+/project/closed', () => {
      console.log('[SAFETY] Project closed, clearing all safety state')
      clearAllSafetyState('project_closed')
      currentProjectId = null
    })

    // Load saved configs - but only if we have a project context
    // This prevents loading stale data on initial load before project is established
    const hasChannels = Object.keys(store.channels).length > 0
    if (hasChannels) {
      loadAlarmConfigs()
      loadHistory()
    }
    loadInterlocks()  // Interlocks are project-agnostic for now
    loadSafetyActions()
    loadAutoExecuteSetting()

    // Watch for channel changes to add new configs and clear orphaned alarms
    watch(() => store.channels, (newChannels, oldChannels) => {
      const newCount = Object.keys(newChannels).length
      const oldCount = oldChannels ? Object.keys(oldChannels).length : 0

      // If no channels (no project loaded), clear all stale alarms
      if (newCount === 0) {
        if (activeAlarms.value.length > 0 || alarmHistory.value.length > 0 || Object.keys(alarmConfigs.value).length > 0) {
          console.log('[SAFETY] No channels (no project loaded), clearing all safety state')
          clearAllSafetyState('no_channels')
        }
      } else {
        // Has channels - initialize configs for any new channels
        initializeAlarmConfigs()

        if (oldCount > 0 && newCount > 0) {
          // Both old and new have channels - check for orphaned alarms
          clearOrphanedAlarms()

          // Also clear alarm configs for channels that no longer exist
          const validChannels = new Set(Object.keys(newChannels))
          Object.keys(alarmConfigs.value).forEach(channel => {
            if (!validChannels.has(channel)) {
              delete alarmConfigs.value[channel]
            }
          })
        }
      }
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

    // Subscribe to backend alarm events via MQTT
    mqtt.onAlarm((alarm, event) => {
      handleBackendAlarm(alarm, event)
    })

    // Subscribe to backend safety_action events via MQTT
    // Backend AlarmManager publishes these when alarms with safety_action trigger
    mqtt.subscribe('nisystem/safety/action', (payload: any) => {
      handleBackendSafetyAction(payload)
    })

    // Subscribe to alarms/cleared signal from backend
    // Backend publishes this when project changes, closes, or at startup with no project
    // This ensures frontend clears stale alarm data and localStorage
    mqtt.subscribe('nisystem/nodes/+/alarms/cleared', (payload: any) => {
      const reason = payload?.reason || 'backend_signal'
      console.log(`[SAFETY] Received alarms/cleared from backend, reason: ${reason}`)
      clearAllSafetyState(reason)
    })

    initialized = true
  }

  /**
   * Handle safety action requests from backend (AlarmManager)
   * This allows backend-initiated safety actions to be executed by frontend
   */
  function handleBackendSafetyAction(payload: any) {
    const actionId = payload.action_id
    const alarmId = payload.alarm_id
    const channel = payload.channel

    console.warn(`[SAFETY] Backend requested safety action: ${actionId} (triggered by alarm ${alarmId} on ${channel})`)

    if (!autoExecuteSafetyActions.value) {
      console.warn(`[SAFETY] Auto-execute disabled, ignoring backend safety action request`)
      return
    }

    // Execute the safety action
    const success = executeSafetyAction(actionId, alarmId)
    if (success) {
      console.warn(`[SAFETY] Successfully executed safety action: ${actionId}`)
    } else {
      console.error(`[SAFETY] Failed to execute safety action: ${actionId}`)
    }
  }

  /**
   * Handle alarms received from the backend via MQTT
   */
  function handleBackendAlarm(alarm: any, event: 'triggered' | 'updated' | 'cleared') {
    const alarmId = alarm.alarm_id || alarm.id

    if (event === 'cleared') {
      // Remove from active alarms
      const index = activeAlarms.value.findIndex(a =>
        a.id === alarmId || a.alarm_id === alarmId
      )
      if (index >= 0) {
        const cleared = activeAlarms.value[index]
        if (cleared) {
          addHistoryEntry({
            id: `${alarmId}-cleared-${Date.now()}`,
            alarm_id: alarmId,
            channel: cleared.channel,
            event_type: 'cleared',
            severity: cleared.severity,
            value: cleared.current_value || cleared.value,
            triggered_at: cleared.triggered_at,
            cleared_at: new Date().toISOString(),
            duration_seconds: alarm.duration_seconds
          })
        }
        activeAlarms.value.splice(index, 1)

        // Clear first-out if this was it
        if (firstOutAlarmId.value === alarmId) {
          firstOutAlarmId.value = null
          cascadeStartTime.value = null
        }
      }
      return
    }

    // Find existing alarm
    const existingIndex = activeAlarms.value.findIndex(a =>
      a.id === alarmId || a.alarm_id === alarmId
    )

    if (existingIndex >= 0) {
      // Update existing alarm
      const existing = activeAlarms.value[existingIndex]
      if (existing) {
        existing.state = alarm.state || existing.state
        existing.current_value = alarm.current_value
        existing.acknowledged_at = alarm.acknowledged_at
        existing.acknowledged_by = alarm.acknowledged_by
        existing.shelved_at = alarm.shelved_at
        existing.shelved_by = alarm.shelved_by
        existing.shelve_expires_at = alarm.shelve_expires_at
        existing.shelve_reason = alarm.shelve_reason
        existing.duration_seconds = alarm.duration_seconds
      }
    } else {
      // New alarm from backend
      const activeAlarm: ActiveAlarm = {
        id: alarmId,
        alarm_id: alarmId,
        channel: alarm.channel,
        name: alarm.name,
        severity: alarm.severity as AlarmSeverityLevel,
        state: alarm.state || 'active',
        threshold_type: alarm.threshold_type,
        threshold: alarm.threshold,
        value: alarm.value,
        current_value: alarm.current_value,
        triggered_at: alarm.triggered_at,
        acknowledged_at: alarm.acknowledged_at,
        acknowledged_by: alarm.acknowledged_by,
        sequence_number: alarm.sequence_number || 0,
        is_first_out: alarm.is_first_out || false,
        message: alarm.message || '',
        safety_action: alarm.safety_action,
        duration_seconds: alarm.duration_seconds || 0
      }

      // Set first-out
      if (alarm.is_first_out) {
        firstOutAlarmId.value = alarmId
        cascadeStartTime.value = Date.now()
      }

      activeAlarms.value.push(activeAlarm)

      // Log to history
      addHistoryEntry({
        id: `${alarmId}-triggered-${Date.now()}`,
        alarm_id: alarmId,
        channel: alarm.channel,
        event_type: 'triggered',
        severity: alarm.severity,
        value: alarm.value,
        threshold: alarm.threshold,
        threshold_type: alarm.threshold_type,
        triggered_at: alarm.triggered_at,
        message: alarm.message
      })

      // Auto-execute safety action if configured (ISA-18.2 automatic response)
      if (autoExecuteSafetyActions.value && alarm.safety_action) {
        console.warn(`[SAFETY] Alarm ${alarmId} has safety_action: ${alarm.safety_action}`)
        executeSafetyAction(alarm.safety_action, alarmId)
      }
    }
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
    clearAllAlarms,
    clearAllSafetyState,
    clearOrphanedAlarms,
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
    evaluateCondition,

    // Interlock trip system
    hasFailedInterlocks,
    failedInterlocks,
    isTripped: readonly(isTripped),
    lastTripTime: readonly(lastTripTime),
    lastTripReason: readonly(lastTripReason),
    safeStateConfig: readonly(safeStateConfig),
    tripSystem,
    resetTrip,
    updateSafeStateConfig,

    // Safety Actions (ISA-18.2 automatic responses)
    safetyActions: readonly(safetyActions),
    autoExecuteSafetyActions: readonly(autoExecuteSafetyActions),
    addSafetyAction,
    updateSafetyAction,
    removeSafetyAction,
    getSafetyAction,
    executeSafetyAction,
    setAutoExecuteSafetyActions
  }
}
