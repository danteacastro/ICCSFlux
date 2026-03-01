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
import { useAuth } from './useAuth'
import { usePlayground } from './usePlayground'
import type {
  AlarmConfig,
  AlarmSeverityLevel,
  ActiveAlarm,
  AlarmHistoryEntry,
  AlarmCounts,
  Interlock,
  InterlockCondition,
  InterlockConditionGroup,
  InterlockStatus,
  InterlockControlType,
  InterlockHistoryEntry,
  InterlockEventType,
  ConditionLogic,
  VotingLogic,
  SafetyAction,
  SafetyActionType,
  AlarmState,
  AlarmSeverity,
  ThresholdType
} from '../types'

// ============================================
// H2: Typed MQTT payload interfaces for safety handlers
// ============================================

/** Project loaded notification payload */
interface SafetyProjectLoadedPayload {
  project_name?: string
  filename?: string
}

/** Safety action request from backend AlarmManager */
interface SafetyActionRequestPayload {
  action_id: string
  alarm_id?: string
  channel?: string
}

/** Alarms cleared signal from backend */
interface AlarmsClearedPayload {
  reason?: string
}

/** Backend safety status payload (backend-authoritative) */
interface BackendSafetyStatusPayload {
  latchState?: string
  isTripped?: boolean
  lastTripTime?: string | null
  lastTripReason?: string | null
  interlockStatuses?: Array<{
    id: string
    satisfied: boolean
    failedConditions?: Array<{
      condition: InterlockCondition
      currentValue?: unknown
      reason: string
      delayRemaining?: number
    }>
  }>
}

/** Backend latch state change payload */
interface BackendLatchStatePayload {
  state?: string
  armed?: boolean
  tripped?: boolean
  timestamp?: string
  tripReason?: string
}

/** Backend trip event payload */
interface BackendTripEventPayload {
  reason?: string
  timestamp?: string
}

/** Backend interlock list response */
interface BackendInterlockListPayload {
  interlocks?: Array<Record<string, unknown>>
}

/** Backend interlock update payload */
interface BackendInterlockUpdatePayload {
  id?: string
  name?: string
  [key: string]: unknown
}

/** Backend interlock error payload */
interface BackendInterlockErrorPayload {
  error?: string
  message?: string
}

/** Backend alarm payload (received via onAlarm callback) */
interface BackendAlarmPayload {
  alarm_id?: string
  id?: string
  channel?: string
  name?: string
  severity?: string
  state?: string
  threshold_type?: string
  threshold?: number
  value?: number
  current_value?: number
  triggered_at?: string
  acknowledged_at?: string
  acknowledged_by?: string
  shelved_at?: string
  shelved_by?: string
  shelve_expires_at?: string
  shelve_reason?: string
  sequence_number?: number
  is_first_out?: boolean
  message?: string
  duration_seconds?: number
  safety_action?: string
}

// ============================================
// Singleton State (shared across all instances)
// ============================================

const alarmConfigs = ref<Record<string, AlarmConfig>>({})
const activeAlarms = ref<ActiveAlarm[]>([])
const alarmHistory = ref<AlarmHistoryEntry[]>([])
const interlocks = ref<Interlock[]>([])

// Interlock History (IEC 61511 audit trail)
const interlockHistory = ref<InterlockHistoryEntry[]>([])

// Condition delay tracking (runtime state for timer conditions)
const conditionDelayState = ref<Record<string, { startTime: number; met: boolean }>>({})

// Previous interlock states for demand tracking
const previousInterlockStates = ref<Record<string, boolean>>({})

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

// H3: Track interval/timeout IDs for cleanup
let shelveExpiryIntervalId: ReturnType<typeof setInterval> | null = null

// ============================================
// Composable Factory
// ============================================

export function useSafety() {
  const store = useDashboardStore()
  const mqtt = useMqtt('nisystem')
  const playground = usePlayground()

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

  // Initialize configs from channel configs and propagate limit changes
  function initializeAlarmConfigs() {
    Object.keys(store.channels).forEach(name => {
      if (!alarmConfigs.value[name]) {
        alarmConfigs.value[name] = createDefaultAlarmConfig(name)
      } else {
        // Propagate updated channel limits to existing alarm config
        const channelConfig = store.channels[name]
        const cfg = alarmConfigs.value[name]
        if (channelConfig?.high_limit !== undefined) cfg.high_high = channelConfig.high_limit
        if (channelConfig?.high_warning !== undefined) cfg.high = channelConfig.high_warning
        if (channelConfig?.low_warning !== undefined) cfg.low = channelConfig.low_warning
        if (channelConfig?.low_limit !== undefined) cfg.low_low = channelConfig.low_limit
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
    console.debug(`[SAFETY] Clearing all ${activeAlarms.value.length} active alarms`)

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
    console.debug(`[SAFETY] Clearing ALL safety state, reason: ${reason}`)

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

    // Reset condition delay tracking (prevents stale delay timers across projects)
    conditionDelayState.value = {}

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
      resetAnalogOutputs: true,
      stopSession: true,
      digitalOutputChannels: [],
      analogOutputChannels: [],
      analogSafeValue: 0
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
      console.debug('[SAFETY] Cleared all localStorage safety/alarm data')
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
      console.debug(`[SAFETY] Clearing ${orphanedAlarms.length} orphaned alarms for removed channels`)

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

  function addInterlock(interlock: Omit<Interlock, 'id'>, user: string = 'User', reason?: string) {
    const newInterlock: Interlock = {
      ...interlock,
      id: `interlock-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      demandCount: 0
    }
    interlocks.value.push(newInterlock)
    recordInterlockEvent(newInterlock, 'created', user, reason)
    saveInterlocks()
    syncInterlockToBackend(newInterlock, reason)
    return newInterlock.id
  }

  function updateInterlock(id: string, updates: Partial<Interlock>, user: string = 'User', reason?: string) {
    const index = interlocks.value.findIndex(i => i.id === id)
    if (index >= 0) {
      const existing = interlocks.value[index]
      if (existing) {
        // Critical interlocks require Admin role to modify
        if (existing.isCritical) {
          const auth = useAuth()
          if (!auth.isAdmin.value) {
            console.warn(`[SAFETY] Update critical interlock denied: requires Admin role`)
            return
          }
        }
        const wasEnabled = existing.enabled
        interlocks.value[index] = { ...existing, ...updates } as Interlock
        const updated = interlocks.value[index]

        // Track enable/disable events
        if (wasEnabled !== updated.enabled) {
          recordInterlockEvent(updated, updated.enabled ? 'enabled' : 'disabled', user, reason)
        } else {
          recordInterlockEvent(updated, 'modified', user, reason)
        }

        saveInterlocks()
        syncInterlockToBackend(updated, reason)
      }
    }
  }

  function removeInterlock(id: string, user: string = 'User', reason?: string) {
    const auth = useAuth()
    const interlock = interlocks.value.find(i => i.id === id)

    // Critical interlocks require Admin role (elevated from Supervisor)
    if (interlock?.isCritical && !auth.isAdmin.value) {
      console.warn(`[SAFETY] Remove critical interlock denied: requires Admin role`)
      return
    }
    if (!auth.isSupervisor.value) {
      console.warn(`[SAFETY] Remove interlock denied: user ${user} lacks supervisor role`)
      return
    }
    const index = interlocks.value.findIndex(i => i.id === id)
    if (index >= 0) {
      const removed = interlocks.value[index]!
      recordInterlockEvent(removed, 'removed', user, reason || `Interlock removed: ${removed.name}`)
      interlocks.value.splice(index, 1)
      saveInterlocks()

      // Remove from backend (include reason for audit trail)
      if (mqtt.connected.value) {
        mqtt.sendCommand(`interlocks/remove`, { id, user, reason: reason || '' })
      }
    }
  }

  function bypassInterlock(id: string, bypass: boolean, user: string = 'User', reason?: string) {
    const auth = useAuth()
    if (!auth.isSupervisor.value) {
      console.warn(`[SAFETY] Bypass interlock denied: user ${user} lacks supervisor role`)
      return
    }
    const interlock = interlocks.value.find(i => i.id === id)
    if (interlock && interlock.bypassAllowed) {
      const wasBypassed = interlock.bypassed
      interlock.bypassed = bypass
      if (bypass) {
        interlock.bypassedAt = new Date().toISOString()
        interlock.bypassedBy = user
        interlock.bypassReason = reason
        if (!wasBypassed) {
          recordInterlockEvent(interlock, 'bypassed', user, reason, {
            bypassDuration: interlock.maxBypassDuration
          })
        }
      } else {
        interlock.bypassedAt = undefined
        interlock.bypassedBy = undefined
        interlock.bypassReason = undefined
        if (wasBypassed) {
          recordInterlockEvent(interlock, 'bypass_removed', user, reason)
        }
      }
      saveInterlocks()
      syncInterlockToBackend(interlock)
    }
  }

  // ============================================
  // Backend Sync (MQTT)
  // ============================================

  function syncInterlockToBackend(interlock: Interlock, reason?: string) {
    if (!mqtt.connected.value) return

    // Publish interlock state to backend
    const payload = {
      id: interlock.id,
      name: interlock.name,
      enabled: interlock.enabled,
      bypassed: interlock.bypassed,
      bypassedBy: interlock.bypassedBy,
      bypassReason: interlock.bypassReason,
      isCritical: interlock.isCritical ?? false,
      conditions: interlock.conditions.map(c => ({
        type: c.type,
        channel: c.channel,
        operator: c.operator,
        value: c.value,
        invert: c.invert,
        delay_s: c.delay_s,
        alarmId: c.alarmId,
        alarmState: c.alarmState,
        variableId: c.variableId,
        expression: c.expression
      })),
      controls: interlock.controls,
      reason: reason || ''
    }

    mqtt.sendCommand('interlocks/sync', payload)
  }

  function syncAllInterlocksToBackend() {
    interlocks.value.forEach(i => syncInterlockToBackend(i))
  }

  function syncAlarmConfigsToBackend() {
    if (!mqtt.connected.value) return
    const configs = Object.values(alarmConfigs.value).map(cfg => ({
      id: cfg.id,
      channel: cfg.channel,
      name: cfg.name,
      enabled: cfg.enabled,
      severity: cfg.severity,
      high_high: cfg.high_high,
      high: cfg.high,
      low: cfg.low,
      low_low: cfg.low_low,
      deadband: cfg.deadband,
      on_delay_s: cfg.on_delay_s,
      off_delay_s: cfg.off_delay_s,
      behavior: cfg.behavior,
      group: cfg.group,
    }))
    mqtt.sendCommand('alarms/config/sync', { configs })
  }

  function acknowledgeTrip(interlockId: string, reason: string = '') {
    if (!mqtt.connected.value) return
    const auth = useAuth()
    const user = auth.currentUser.value?.username || 'operator'
    mqtt.sendCommand('interlocks/acknowledge_trip', {
      id: interlockId,
      user,
      reason
    })
    // Record in local history
    const interlock = interlocks.value.find(i => i.id === interlockId)
    if (interlock) {
      recordInterlockEvent(interlock, 'trip_acknowledged', user, reason)
    }
  }

  // ============================================
  // Interlock Condition Evaluation (IEC 61511)
  // ============================================

  /**
   * Evaluate a single condition without timer/delay logic
   */
  function evaluateConditionRaw(condition: InterlockCondition): { satisfied: boolean; currentValue?: unknown; reason: string } {
    // FE-H4: Guard against null/undefined/malformed condition objects
    if (!condition || typeof condition !== 'object') {
      console.warn('[SAFETY] evaluateConditionRaw called with invalid condition:', condition)
      return { satisfied: false, reason: 'Invalid condition object (null or not an object)' }
    }

    if (!condition.type) {
      console.warn('[SAFETY] evaluateConditionRaw called with missing condition type:', condition)
      return { satisfied: false, reason: 'Condition has no type specified' }
    }

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

      case 'alarm_active':
        // Check if specific alarm is currently active
        if (!condition.alarmId) {
          return { satisfied: false, reason: 'No alarm ID specified' }
        }
        const alarmActive = activeAlarms.value.some(a =>
          a.id === condition.alarmId || a.channel === condition.alarmId
        )
        return {
          satisfied: !alarmActive,  // Satisfied when alarm is NOT active
          currentValue: alarmActive,
          reason: alarmActive ? `Alarm ${condition.alarmId} is active` : `Alarm ${condition.alarmId} is clear`
        }

      case 'alarm_state':
        // Check if alarm is in specific state
        if (!condition.alarmId || !condition.alarmState) {
          return { satisfied: false, reason: 'Invalid alarm state condition' }
        }
        const alarm = activeAlarms.value.find(a =>
          a.id === condition.alarmId || a.channel === condition.alarmId
        )
        const inState = alarm?.state === condition.alarmState
        return {
          satisfied: inState,
          currentValue: alarm?.state || 'none',
          reason: inState
            ? `Alarm ${condition.alarmId} is ${condition.alarmState}`
            : `Alarm ${condition.alarmId} is ${alarm?.state || 'not active'} (requires ${condition.alarmState})`
        }

      case 'variable_value':
        // Check user variable value
        if (!condition.variableId || condition.operator === undefined || condition.value === undefined) {
          return { satisfied: false, reason: 'Invalid variable condition' }
        }
        const varValue = playground.variables.value[condition.variableId]?.value
        if (varValue === undefined) {
          return { satisfied: false, currentValue: undefined, reason: `Variable ${condition.variableId} not found` }
        }
        const varNumValue = condition.value as number
        let varSatisfied = false
        switch (condition.operator) {
          case '<': varSatisfied = varValue < varNumValue; break
          case '<=': varSatisfied = varValue <= varNumValue; break
          case '>': varSatisfied = varValue > varNumValue; break
          case '>=': varSatisfied = varValue >= varNumValue; break
          case '=': varSatisfied = varValue === varNumValue; break
          case '!=': varSatisfied = varValue !== varNumValue; break
        }
        return {
          satisfied: varSatisfied,
          currentValue: varValue,
          reason: varSatisfied
            ? `Variable ${condition.variableId} = ${varValue} (OK)`
            : `Variable ${condition.variableId} = ${varValue} (requires ${condition.operator} ${varNumValue})`
        }

      case 'expression':
        // Evaluate simple expression (channel math)
        if (!condition.expression) {
          return { satisfied: false, reason: 'No expression specified' }
        }
        try {
          // Simple expression parser for channel values
          // Supports: channelName, +, -, *, /, >, <, >=, <=, ==, !=, AND, OR
          const result = evaluateSimpleExpression(condition.expression)
          return {
            satisfied: Boolean(result),
            currentValue: result,
            reason: result ? `Expression satisfied: ${condition.expression}` : `Expression failed: ${condition.expression}`
          }
        } catch (e) {
          return { satisfied: false, reason: `Expression error: ${e}` }
        }

      case 'channel_value':
        if (!condition.channel || condition.operator === undefined || condition.value === undefined) {
          return { satisfied: false, reason: 'Invalid channel condition' }
        }
        // FE-H4: Safe channel lookup - channel may not exist in store
        if (!store.values || !(condition.channel in store.values)) {
          console.warn(`[SAFETY] Channel "${condition.channel}" not found in store values`)
          return { satisfied: false, currentValue: undefined, reason: `Channel ${condition.channel} not found` }
        }
        const channelValue = store.values[condition.channel]?.value
        if (channelValue === undefined || channelValue === null) {
          return { satisfied: false, currentValue: undefined, reason: `Channel ${condition.channel} has no value` }
        }
        // FE-H4: Ensure channelValue is numeric before comparison
        if (typeof channelValue !== 'number' || isNaN(channelValue)) {
          console.warn(`[SAFETY] Channel "${condition.channel}" has non-numeric value: ${channelValue}`)
          return { satisfied: false, currentValue: channelValue, reason: `Channel ${condition.channel} value is not numeric (${channelValue})` }
        }
        const numValue = Number(condition.value)
        if (isNaN(numValue)) {
          console.warn(`[SAFETY] Condition value is not numeric: ${condition.value}`)
          return { satisfied: false, currentValue: channelValue, reason: `Condition threshold is not numeric (${condition.value})` }
        }
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
        // FE-H4: Safe channel lookup for digital input
        if (!store.values || !(condition.channel in store.values)) {
          console.warn(`[SAFETY] Digital input channel "${condition.channel}" not found in store values`)
          return { satisfied: false, currentValue: undefined, reason: `Digital input ${condition.channel} not found` }
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

  /**
   * Evaluate simple expression for channel values
   * Supports: TAG names, numbers, +, -, *, /, >, <, >=, <=, ==, !=, AND, OR, NOT
   */
  function evaluateSimpleExpression(expr: string): number | boolean {
    // Replace channel names with values
    let processed = expr
    const channelPattern = /\b([A-Za-z_][A-Za-z0-9_]*)\b/g
    const matches = expr.match(channelPattern) || []

    for (const match of matches) {
      // Skip operators and keywords
      if (['AND', 'OR', 'NOT', 'true', 'false'].includes(match.toUpperCase())) continue

      const value = store.values[match]?.value
      if (value !== undefined) {
        processed = processed.replace(new RegExp(`\\b${match}\\b`, 'g'), String(value))
      }
    }

    // Replace operators
    processed = processed.replace(/\bAND\b/gi, '&&')
    processed = processed.replace(/\bOR\b/gi, '||')
    processed = processed.replace(/\bNOT\b/gi, '!')
    processed = processed.replace(/==/g, '===')

    // Safe evaluation: only allow numbers, operators, and parenthesized sub-expressions.
    // Block property access (dot followed by identifier) and empty parens (function calls).
    if (!/^[0-9\s+\-*/<>=!&|.()]+$/.test(processed)) {
      throw new Error('Invalid expression characters')
    }
    // Block property access patterns: 1.constructor, value.toString, etc.
    if (/\.\s*[a-zA-Z_]/.test(processed)) {
      throw new Error('Property access not allowed in expressions')
    }
    // Block empty function call patterns: ()  or (  )
    if (/\(\s*\)/.test(processed)) {
      throw new Error('Function calls not allowed in expressions')
    }

    // eslint-disable-next-line no-new-func
    return new Function(`return ${processed}`)()
  }

  /**
   * Evaluate condition with timer/delay logic
   * Returns { satisfied, delayRemaining } where delayRemaining is seconds until delay met
   */
  function evaluateCondition(condition: InterlockCondition): {
    satisfied: boolean
    currentValue?: unknown
    reason: string
    delayRemaining?: number
  } {
    const rawResult = evaluateConditionRaw(condition)

    // If no delay configured, return raw result
    if (!condition.delay_s || condition.delay_s <= 0) {
      return rawResult
    }

    const now = Date.now() / 1000
    const delayKey = condition.id
    const delayState = conditionDelayState.value[delayKey]

    if (rawResult.satisfied) {
      // Condition is satisfied - check if delay has elapsed
      if (!delayState || !delayState.met) {
        // Start or continue timing
        const startTime = delayState?.startTime || now
        const elapsed = now - startTime

        if (elapsed >= condition.delay_s) {
          // Delay met
          conditionDelayState.value[delayKey] = { startTime, met: true }
          return { ...rawResult, satisfied: true }
        } else {
          // Still waiting
          conditionDelayState.value[delayKey] = { startTime, met: false }
          return {
            ...rawResult,
            satisfied: false,
            delayRemaining: condition.delay_s - elapsed,
            reason: `${rawResult.reason} (waiting ${(condition.delay_s - elapsed).toFixed(1)}s)`
          }
        }
      }
      // Delay already met
      return rawResult
    } else {
      // Condition not satisfied - reset delay timer
      delete conditionDelayState.value[delayKey]
      return rawResult
    }
  }

  /**
   * Evaluate voting logic (2oo3, 1oo2, etc.)
   */
  function evaluateVoting(voting: VotingLogic, channels: string[], operator: string, threshold: number): {
    satisfied: boolean
    votes: { channel: string; value: number; vote: boolean }[]
    reason: string
  } {
    const votes = channels.map(channel => {
      const value = store.values[channel]?.value ?? 0
      let vote = false
      switch (operator) {
        case '<': vote = value < threshold; break
        case '<=': vote = value <= threshold; break
        case '>': vote = value > threshold; break
        case '>=': vote = value >= threshold; break
        case '=': vote = value === threshold; break
        case '!=': vote = value !== threshold; break
        default: vote = value < threshold
      }
      return { channel, value, vote }
    })

    const trueCount = votes.filter(v => v.vote).length
    const total = votes.length

    let required: number
    switch (voting) {
      case '1oo1': required = 1; break
      case '1oo2': required = 1; break
      case '2oo2': required = 2; break
      case '1oo3': required = 1; break
      case '2oo3': required = 2; break
      default: required = total
    }

    const satisfied = trueCount >= required
    return {
      satisfied,
      votes,
      reason: satisfied
        ? `Voting ${voting}: ${trueCount}/${total} (requires ${required})`
        : `Voting ${voting} FAILED: ${trueCount}/${total} (requires ${required})`
    }
  }

  /**
   * Evaluate a condition group with nested AND/OR logic
   */
  function evaluateConditionGroup(group: InterlockConditionGroup): {
    satisfied: boolean
    failedConditions: InterlockStatus['failedConditions']
  } {
    const results: { satisfied: boolean; condition?: InterlockCondition; result?: ReturnType<typeof evaluateCondition> }[] = []
    const failedConditions: InterlockStatus['failedConditions'] = []

    for (const item of group.conditions) {
      if ('conditions' in item) {
        // Nested group
        const nestedResult = evaluateConditionGroup(item as InterlockConditionGroup)
        results.push({ satisfied: nestedResult.satisfied })
        failedConditions.push(...nestedResult.failedConditions)
      } else {
        // Single condition
        const condition = item as InterlockCondition
        const result = evaluateCondition(condition)
        results.push({ satisfied: result.satisfied, condition, result })
        if (!result.satisfied) {
          failedConditions.push({
            condition,
            currentValue: result.currentValue,
            reason: result.reason,
            delayRemaining: result.delayRemaining
          })
        }
      }
    }

    // Apply logic
    let satisfied: boolean
    if (group.logic === 'OR') {
      satisfied = results.some(r => r.satisfied)
    } else {
      // AND logic (default)
      satisfied = results.every(r => r.satisfied)
    }

    return { satisfied, failedConditions: satisfied ? [] : failedConditions }
  }

  // C3: This function is a FALLBACK only. Backend safety_manager.py is authoritative.
  // Local evaluation runs only when the backend hasn't sent status yet (initial load,
  // MQTT disconnected). Once backend publishes to safety/status, _backendSatisfied
  // takes precedence in interlockStatuses computed above.
  function evaluateInterlock(interlock: Interlock): InterlockStatus {
    if (!interlock.enabled) {
      return {
        id: interlock.id,
        name: interlock.name,
        satisfied: true,
        bypassed: false,
        enabled: false,
        failedConditions: [],
        controls: interlock.controls,
        conditionsWithDelay: [],
        priority: interlock.priority,
        silRating: interlock.silRating,
        requiresAcknowledgment: interlock.requiresAcknowledgment,
      }
    }

    // Check bypass expiration
    if (interlock.bypassed && interlock.maxBypassDuration && interlock.bypassedAt) {
      const bypassTime = new Date(interlock.bypassedAt).getTime()
      const elapsed = (Date.now() - bypassTime) / 1000
      if (elapsed >= interlock.maxBypassDuration) {
        // Bypass expired - remove it
        removeBypass(interlock.id, 'system', 'Bypass time expired')
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
        controls: interlock.controls,
        conditionsWithDelay: [],
        priority: interlock.priority,
        silRating: interlock.silRating,
        requiresAcknowledgment: interlock.requiresAcknowledgment,
      }
    }

    let failedConditions: InterlockStatus['failedConditions'] = []
    let satisfied: boolean
    const conditionsWithDelay: InterlockStatus['conditionsWithDelay'] = []

    // Use condition group if available (supports nested AND/OR)
    if (interlock.conditionGroup) {
      const groupResult = evaluateConditionGroup(interlock.conditionGroup)
      satisfied = groupResult.satisfied
      failedConditions = groupResult.failedConditions
    } else {
      // Legacy flat conditions with configurable logic
      const logic = interlock.conditionLogic || 'AND'
      const results: { satisfied: boolean; condition: InterlockCondition; result: ReturnType<typeof evaluateCondition> }[] = []

      for (const condition of interlock.conditions) {
        const result = evaluateCondition(condition)
        results.push({ satisfied: result.satisfied, condition, result })

        // Track delay status
        if (condition.delay_s && condition.delay_s > 0) {
          const delayState = conditionDelayState.value[condition.id]
          conditionsWithDelay.push({
            conditionId: condition.id,
            delayTotal: condition.delay_s,
            delayElapsed: delayState ? (Date.now() / 1000 - delayState.startTime) : 0,
            delayMet: delayState?.met ?? false
          })
        }

        if (!result.satisfied) {
          failedConditions.push({
            condition,
            currentValue: result.currentValue,
            reason: result.reason,
            delayRemaining: result.delayRemaining
          })
        }
      }

      // Apply logic
      if (logic === 'OR') {
        satisfied = results.some(r => r.satisfied)
        // For OR logic, only report failed conditions if ALL failed
        if (satisfied) {
          failedConditions = []
        }
      } else {
        satisfied = results.every(r => r.satisfied)
      }
    }

    // Track demand (IEC 61511)
    const wasSatisfied = previousInterlockStates.value[interlock.id] ?? true
    if (wasSatisfied && !satisfied) {
      // Interlock just tripped - record demand
      recordInterlockEvent(interlock, 'demand', 'system', undefined, {
        failedConditions: failedConditions.map(f => f.reason)
      })
      // Increment demand count
      interlock.demandCount = (interlock.demandCount || 0) + 1
      interlock.lastDemandTime = new Date().toISOString()
    } else if (!wasSatisfied && satisfied) {
      // Interlock cleared
      recordInterlockEvent(interlock, 'cleared', 'system')
    }
    previousInterlockStates.value[interlock.id] = satisfied

    return {
      id: interlock.id,
      name: interlock.name,
      satisfied,
      bypassed: false,
      enabled: true,
      failedConditions,
      controls: interlock.controls,
      conditionsWithDelay,
      priority: interlock.priority,
      silRating: interlock.silRating,
      requiresAcknowledgment: interlock.requiresAcknowledgment,
    }
  }

  // ============================================
  // Interlock History & Audit (IEC 61511)
  // ============================================

  function recordInterlockEvent(
    interlock: Interlock,
    event: InterlockEventType,
    user?: string,
    reason?: string,
    details?: InterlockHistoryEntry['details']
  ) {
    const entry: InterlockHistoryEntry = {
      id: `ilh-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toISOString(),
      interlockId: interlock.id,
      interlockName: interlock.name,
      event,
      user,
      reason,
      details
    }
    interlockHistory.value.unshift(entry)

    // Keep last 1000 entries
    if (interlockHistory.value.length > 1000) {
      interlockHistory.value = interlockHistory.value.slice(0, 1000)
    }

    // Persist to localStorage
    saveInterlockHistory()

    console.debug(`[Interlock] ${event}: ${interlock.name}${reason ? ` - ${reason}` : ''}`)
  }

  function saveInterlockHistory() {
    try {
      const systemId = store.systemId || 'default'
      const key = `nisystem-interlock-history-${systemId}`
      saveWithTimestamp(key, JSON.stringify(interlockHistory.value.slice(0, 500)))
    } catch (e) {
      console.error('Failed to save interlock history:', e)
    }
  }

  function loadInterlockHistory() {
    try {
      const systemId = store.systemId || 'default'
      const key = `nisystem-interlock-history-${systemId}`
      const saved = localStorage.getItem(key)
      if (saved) {
        // M2: Skip stale interlock history
        if (isLocalStorageStale(key)) {
          console.debug('[SAFETY] Skipping stale interlock history from localStorage')
          return
        }
        interlockHistory.value = JSON.parse(saved)
      }
    } catch (e) {
      console.error('Failed to load interlock history:', e)
    }
  }

  function removeBypass(interlockId: string, user: string, reason?: string) {
    const interlock = interlocks.value.find(i => i.id === interlockId)
    if (interlock && interlock.bypassed) {
      interlock.bypassed = false
      interlock.bypassedAt = undefined
      interlock.bypassedBy = undefined
      interlock.bypassReason = undefined
      recordInterlockEvent(interlock, reason?.includes('expired') ? 'bypass_expired' : 'bypass_removed', user, reason)
      saveInterlocks()
    }
  }

  function recordProofTest(interlockId: string, user: string, notes?: string) {
    const interlock = interlocks.value.find(i => i.id === interlockId)
    if (interlock) {
      interlock.lastProofTest = new Date().toISOString()
      recordInterlockEvent(interlock, 'proof_test', user, notes)
      saveInterlocks()
    }
  }

  // Get all interlock statuses
  // C3: Backend is authoritative for interlock evaluation. The frontend displays
  // backend-evaluated status when available (_backendSatisfied). Local evaluation
  // is only used as a fallback when the backend hasn't sent status yet (e.g., during
  // initial connection or when MQTT is disconnected). This prevents the frontend from
  // independently tripping or clearing interlocks.
  const interlockStatuses = computed((): InterlockStatus[] => {
    return interlocks.value.map(interlock => {
      // If backend has sent evaluated status, use it (display-only)
      if (interlock._backendSatisfied !== undefined) {
        return {
          id: interlock.id,
          name: interlock.name,
          satisfied: interlock._backendSatisfied,
          bypassed: interlock.bypassed,
          enabled: interlock.enabled,
          failedConditions: interlock._backendFailedConditions || [],
          controls: interlock.controls,
          conditionsWithDelay: [],
          priority: interlock.priority,
          silRating: interlock.silRating,
          requiresAcknowledgment: interlock.requiresAcknowledgment,
        } as InterlockStatus
      }
      // Fallback: local evaluation only when backend hasn't reported yet
      return evaluateInterlock(interlock)
    })
  })

  // Check if a specific control type is blocked
  function isControlBlocked(controlType: InterlockControlType, identifier?: string): { blocked: boolean; blockedBy: InterlockStatus[] } {
    const blockedBy: InterlockStatus[] = []

    for (const status of interlockStatuses.value) {
      if (!status.satisfied && !status.bypassed && status.enabled) {
        for (const control of status.controls) {
          if (control.type === controlType) {
            // Channel-specific blocking (DO, AO)
            if ((controlType === 'digital_output' || controlType === 'analog_output') && identifier) {
              if (control.channel === identifier) {
                blockedBy.push(status)
              }
            } else if (controlType === 'button_action' && identifier) {
              if (control.buttonId === identifier) {
                blockedBy.push(status)
              }
            } else if (controlType !== 'digital_output' && controlType !== 'analog_output' && controlType !== 'button_action') {
              // Global blocking (schedule, recording, acquisition, session, script)
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
  const isSessionBlocked = computed(() => isControlBlocked('session_start'))
  const isScriptBlocked = computed(() => isControlBlocked('script_start'))

  // Check if a specific output channel is blocked (works for both DO and AO)
  function isOutputBlocked(channel: string) {
    // Check both digital and analog output blocking for this channel
    const doBlocked = isControlBlocked('digital_output', channel)
    const aoBlocked = isControlBlocked('analog_output', channel)

    // Merge the results
    const allBlockedBy = [...doBlocked.blockedBy, ...aoBlocked.blockedBy]
    return {
      blocked: allBlockedBy.length > 0,
      blockedBy: allBlockedBy
    }
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

    console.debug(`[SAFETY] Executing actions for failed interlock: ${interlock.name}`)

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
            console.debug(`[SAFETY] Setting DO ${control.channel} to ${value}`)
            mqtt.setOutput(control.channel, value)
            executedInterlockActions.value.add(actionKey)
          }
          break

        case 'set_analog_output':
          if (control.channel) {
            const value = control.setValue ?? 0
            console.debug(`[SAFETY] Setting AO ${control.channel} to ${value}`)
            mqtt.setOutput(control.channel, value)
            executedInterlockActions.value.add(actionKey)
          }
          break

        case 'stop_session':
          console.debug(`[SAFETY] Stopping session`)
          mqtt.sendCommand('test-session/stop', {})
          executedInterlockActions.value.add(actionKey)
          break

        case 'stop_acquisition':
          console.debug(`[SAFETY] Stopping acquisition`)
          mqtt.sendCommand('acquisition/stop', {})
          executedInterlockActions.value.add(actionKey)
          break

        // BLOCKING actions don't need execution - they just prevent user actions
        case 'digital_output':
        case 'analog_output':
        case 'schedule_enable':
        case 'recording_start':
        case 'acquisition_start':
        case 'session_start':
        case 'script_start':
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
      // M2: Skip stale safe state config
      if (isLocalStorageStale('nisystem-safe-state-config')) {
        console.debug('[SAFETY] Skipping stale safe state config from localStorage')
        return
      }
      try {
        Object.assign(safeStateConfig.value, JSON.parse(saved))
      } catch { /* ignore */ }
    }
  }

  // Save safe state config
  function saveSafeStateConfig() {
    saveWithTimestamp('nisystem-safe-state-config', JSON.stringify(safeStateConfig.value))
  }

  // Update safe state config
  function updateSafeStateConfig(config: Partial<typeof safeStateConfig.value>) {
    Object.assign(safeStateConfig.value, config)
    saveSafeStateConfig()
  }

  /**
   * Trip the system - send command to backend
   * Backend handles the actual trip logic (stop session, reset outputs)
   * This ensures safety logic runs even if browser closes
   */
  function tripSystem(reason: string) {
    console.debug(`[SAFETY] Requesting system trip: ${reason}`)

    // Optimistically update local state (will be confirmed by backend)
    isTripped.value = true
    lastTripTime.value = new Date().toISOString()
    lastTripReason.value = reason

    // Send trip command to backend (backend handles the actual trip logic)
    mqtt.sendCommand('safety/trip', {
      reason,
      timestamp: lastTripTime.value,
      safeStateConfig: safeStateConfig.value
    })
  }

  /**
   * Reset the trip state - send command to backend
   */
  function resetTrip() {
    // Send reset command to backend
    mqtt.sendCommand('safety/trip/reset', {
      user: 'dashboard',
      timestamp: new Date().toISOString()
    })

    // Note: Backend will verify interlocks are clear before allowing reset
    // The actual state change will come from the backend status update
    console.debug('[SAFETY] Sent trip reset request to backend')
    return true  // Return true to indicate request was sent
  }

  /**
   * Arm the safety latch - send command to backend
   * Backend is authoritative for latch state
   */
  function armLatch(user: string = 'dashboard'): boolean {
    mqtt.sendCommand('safety/latch/arm', {
      user,
      timestamp: new Date().toISOString()
    })
    console.debug(`[SAFETY] Sent latch arm request to backend (user: ${user})`)
    return true  // Request sent, backend will confirm
  }

  /**
   * Disarm the safety latch - send command to backend
   */
  function disarmLatch(user: string = 'dashboard') {
    mqtt.sendCommand('safety/latch/disarm', {
      user,
      timestamp: new Date().toISOString()
    })
    console.debug(`[SAFETY] Sent latch disarm request to backend (user: ${user})`)
  }

  // Load safe state config on init
  loadSafeStateConfig()

  // ============================================
  // Safety Action Management (ISA-18.2)
  // ============================================

  function addSafetyAction(action: Omit<SafetyAction, 'id'>): string {
    const auth = useAuth()
    if (!auth.isSupervisor.value) {
      console.warn('[SAFETY] addSafetyAction denied: requires supervisor or admin role')
      return ''
    }
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
    saveWithTimestamp('nisystem-safety-actions', JSON.stringify(safetyActions.value))
  }

  function loadSafetyActions() {
    const saved = localStorage.getItem('nisystem-safety-actions')
    if (saved) {
      // M2: Skip stale safety actions
      if (isLocalStorageStale('nisystem-safety-actions')) {
        console.debug('[SAFETY] Skipping stale safety actions from localStorage')
        return
      }
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
  // M2: localStorage is used as a fallback when backend hasn't responded yet.
  // Backend state always wins when available. Each saved entry includes a
  // timestamp so stale data (>24 hours) is discarded on load.
  // ============================================

  // M2: Staleness threshold for localStorage data (24 hours)
  const LOCALSTORAGE_MAX_AGE_MS = 24 * 60 * 60 * 1000

  /** M2: Check if a localStorage timestamp is too old to trust */
  function isLocalStorageStale(key: string): boolean {
    try {
      const tsStr = localStorage.getItem(`${key}:timestamp`)
      if (!tsStr) return true // No timestamp = unknown age = stale
      const savedAt = parseInt(tsStr, 10)
      return isNaN(savedAt) || (Date.now() - savedAt) > LOCALSTORAGE_MAX_AGE_MS
    } catch {
      return true
    }
  }

  /** M2: Save a localStorage entry with a timestamp */
  function saveWithTimestamp(key: string, value: string) {
    localStorage.setItem(key, value)
    localStorage.setItem(`${key}:timestamp`, String(Date.now()))
  }

  function saveAlarmConfigs() {
    saveWithTimestamp('nisystem-alarm-configs-v2', JSON.stringify(alarmConfigs.value))
  }

  function loadAlarmConfigs() {
    // Try v2 first, then fall back to v1
    let saved = localStorage.getItem('nisystem-alarm-configs-v2')
    let key = 'nisystem-alarm-configs-v2'
    if (!saved) {
      saved = localStorage.getItem('nisystem-alarm-configs')
      key = 'nisystem-alarm-configs'
    }
    if (saved) {
      // M2: Skip stale data — backend will send fresh configs when it connects
      if (isLocalStorageStale(key)) {
        console.debug('[SAFETY] Skipping stale alarm configs from localStorage')
        return
      }
      try {
        const parsed = JSON.parse(saved)
        // Migrate old format if needed
        Object.entries(parsed as Record<string, Record<string, any>>).forEach(([channel, config]) => {
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
    saveWithTimestamp('nisystem-interlocks', JSON.stringify(interlocks.value))
  }

  function loadInterlocks() {
    const saved = localStorage.getItem('nisystem-interlocks')
    if (saved) {
      // M2: Skip stale interlock data
      if (isLocalStorageStale('nisystem-interlocks')) {
        console.debug('[SAFETY] Skipping stale interlocks from localStorage')
        return
      }
      try {
        interlocks.value = JSON.parse(saved)
      } catch { /* ignore */ }
    }
  }

  function saveHistory() {
    // Save last 500 entries
    const entries = alarmHistory.value.slice(0, 500)
    saveWithTimestamp('nisystem-alarm-history', JSON.stringify(entries))
  }

  function loadHistory() {
    const saved = localStorage.getItem('nisystem-alarm-history')
    if (saved) {
      // M2: Skip stale history (history is informational, not critical)
      if (isLocalStorageStale('nisystem-alarm-history')) {
        console.debug('[SAFETY] Skipping stale alarm history from localStorage')
        return
      }
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
    mqtt.subscribe('nisystem/nodes/+/project/loaded', (payload: SafetyProjectLoadedPayload) => {
      const newProjectName = payload?.project_name || payload?.filename || 'unknown'
      console.debug(`[SAFETY] Project loaded: ${newProjectName}, previous: ${currentProjectId}`)

      // If project changed, clear ALL state
      if (currentProjectId !== null && currentProjectId !== newProjectName) {
        console.debug('[SAFETY] Project changed, clearing all safety state')
        clearAllSafetyState('project_changed')
      }

      currentProjectId = newProjectName
      // Initialize alarm configs for new project's channels
      initializeAlarmConfigs()
    })

    // Subscribe to project/closed to clear state
    mqtt.subscribe('nisystem/nodes/+/project/closed', () => {
      console.debug('[SAFETY] Project closed, clearing all safety state')
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
    loadInterlockHistory()
    loadSafetyActions()
    loadAutoExecuteSetting()

    // Watch for channel changes to add new configs and clear orphaned alarms
    watch(() => store.channels, (newChannels, oldChannels) => {
      const newCount = Object.keys(newChannels).length
      const oldCount = oldChannels ? Object.keys(oldChannels).length : 0

      // If no channels (no project loaded), clear all stale safety state
      if (newCount === 0) {
        if (activeAlarms.value.length > 0 || alarmHistory.value.length > 0 ||
            Object.keys(alarmConfigs.value).length > 0 || interlocks.value.length > 0) {
          console.debug('[SAFETY] No channels (no project loaded), clearing all safety state')
          clearAllSafetyState('no_channels')
        }
      } else {
        // Has channels - initialize configs for any new channels
        initializeAlarmConfigs()

        if (oldCount === 0 && newCount > 0) {
          // Project just loaded (went from no channels to having channels)
          // Reload all safety settings from localStorage (useProjectFiles may have updated them)
          console.debug('[SAFETY] Project loaded - reloading safety settings from localStorage')
          loadAlarmConfigs()
          loadInterlocks()
          loadSafetyActions()
          loadAutoExecuteSetting()
          loadHistory()
        } else if (oldCount > 0 && newCount > 0) {
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

    // Debounced auto-sync alarm configs to backend when changed
    let alarmSyncTimer: ReturnType<typeof setTimeout> | null = null
    watch(alarmConfigs, () => {
      if (alarmSyncTimer) clearTimeout(alarmSyncTimer)
      alarmSyncTimer = setTimeout(() => {
        syncAlarmConfigsToBackend()
      }, 2000)  // 2 second debounce
    }, { deep: true })

    // Auto-save history periodically
    watch(alarmHistory, () => {
      if (alarmHistory.value.length % 10 === 0) {
        saveHistory()
      }
    }, { deep: true })

    // H3: Check shelve expiry every minute (store ID for cleanup)
    if (shelveExpiryIntervalId) clearInterval(shelveExpiryIntervalId)
    shelveExpiryIntervalId = setInterval(checkShelveExpiry, 60000)

    // Subscribe to backend alarm events via MQTT
    mqtt.onAlarm((alarm, event) => {
      handleBackendAlarm(alarm, event)
    })

    // Subscribe to backend safety_action events via MQTT
    // Backend AlarmManager publishes these when alarms with safety_action trigger
    mqtt.subscribe('nisystem/safety/action', (payload: SafetyActionRequestPayload) => {
      handleBackendSafetyAction(payload)
    })

    // Subscribe to alarms/cleared signal from backend
    // Backend publishes this when project changes, closes, or at startup with no project
    // This ensures frontend clears stale alarm data and localStorage
    mqtt.subscribe('nisystem/nodes/+/alarms/cleared', (payload: AlarmsClearedPayload) => {
      const reason = payload?.reason || 'backend_signal'
      console.debug(`[SAFETY] Received alarms/cleared from backend, reason: ${reason}`)
      clearAllSafetyState(reason)
    })

    // Subscribe to backend safety status (backend-authoritative safety logic)
    mqtt.subscribe('nisystem/nodes/+/safety/status', (payload: BackendSafetyStatusPayload) => {
      handleBackendSafetyStatus(payload)
    })

    // Subscribe to backend latch state changes
    mqtt.subscribe('nisystem/nodes/+/safety/latch/state', (payload: BackendLatchStatePayload) => {
      handleBackendLatchState(payload)
    })

    // Subscribe to backend trip events
    mqtt.subscribe('nisystem/nodes/+/safety/trip', (payload: BackendTripEventPayload) => {
      handleBackendTripEvent(payload)
    })

    // Subscribe to interlock list response from backend
    mqtt.subscribe('nisystem/nodes/+/interlocks/list/response', (payload: BackendInterlockListPayload) => {
      handleBackendInterlockList(payload)
    })

    // Subscribe to interlock updates from backend
    mqtt.subscribe('nisystem/nodes/+/interlocks/updated', (payload: BackendInterlockUpdatePayload) => {
      handleBackendInterlockUpdate(payload)
    })

    // Subscribe to interlock error responses (blocked operations on critical interlocks)
    mqtt.subscribe('nisystem/nodes/+/interlocks/error', (payload: BackendInterlockErrorPayload) => {
      if (payload?.error === 'blocked') {
        console.error(`[SAFETY] Backend blocked interlock operation: ${payload.message}`)
        alert(`Safety guard: ${payload.message || 'Operation blocked by backend safety system'}`)
      }
    })

    // M3: Request initial safety status from backend, but only when connected.
    // If MQTT isn't connected yet, watch for connection and send then.
    if (mqtt.connected.value) {
      mqtt.sendCommand('safety/status/request', {})
    } else {
      const stopWatching = watch(() => mqtt.connected.value, (isConnected) => {
        if (isConnected) {
          mqtt.sendCommand('safety/status/request', {})
          stopWatching()
        }
      })
    }

    initialized = true
  }

  /**
   * Handle safety action requests from backend (AlarmManager)
   * This allows backend-initiated safety actions to be executed by frontend
   */
  function handleBackendSafetyAction(payload: SafetyActionRequestPayload) {
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
   * Handle safety status updates from backend (backend-authoritative)
   * The backend evaluates all interlocks and latch state - frontend is display-only
   */
  function handleBackendSafetyStatus(payload: BackendSafetyStatusPayload) {
    if (!payload) return

    // Update latch state from backend
    if (payload.latchState) {
      // Store for reference (frontend doesn't change this directly)
      console.debug(`[SAFETY] Backend latch state: ${payload.latchState}`)
    }

    // Update trip state from backend
    if (payload.isTripped !== undefined) {
      isTripped.value = payload.isTripped
      lastTripTime.value = payload.lastTripTime || null
      lastTripReason.value = payload.lastTripReason || null
    }

    // Update interlock statuses from backend (replace local evaluation)
    if (payload.interlockStatuses && Array.isArray(payload.interlockStatuses)) {
      // Update local interlocks with backend-evaluated status
      for (const status of payload.interlockStatuses) {
        const local = interlocks.value.find(i => i.id === status.id)
        if (local) {
          // Store the backend-evaluated status
          local._backendSatisfied = status.satisfied
          local._backendFailedConditions = status.failedConditions
        }
      }
    }
  }

  /**
   * Handle latch state changes from backend
   */
  function handleBackendLatchState(payload: BackendLatchStatePayload) {
    if (!payload) return

    console.debug(`[SAFETY] Backend latch state change: ${payload.state} (armed: ${payload.armed}, tripped: ${payload.tripped})`)

    // Update trip state if tripped
    if (payload.tripped) {
      isTripped.value = true
      lastTripTime.value = payload.timestamp || new Date().toISOString()
      lastTripReason.value = payload.tripReason || 'Interlock failed'
    }
  }

  /**
   * Handle trip events from backend
   */
  function handleBackendTripEvent(payload: BackendTripEventPayload) {
    if (!payload) return

    console.warn(`[SAFETY] Backend trip event: ${payload.reason}`)
    isTripped.value = true
    lastTripTime.value = payload.timestamp || new Date().toISOString()
    lastTripReason.value = payload.reason || 'System trip'
  }

  /**
   * Handle interlock list from backend (for syncing)
   */
  function handleBackendInterlockList(payload: BackendInterlockListPayload) {
    if (!payload?.interlocks) return

    console.debug(`[SAFETY] Received ${payload.interlocks.length} interlocks from backend`)

    // Merge backend interlocks with local (backend is authoritative)
    for (const backendInterlock of payload.interlocks) {
      const existing = interlocks.value.find(i => i.id === backendInterlock.id)
      if (existing) {
        // Update existing
        Object.assign(existing, backendInterlock)
      } else {
        // Add new (convert from backend format)
        interlocks.value.push({
          id: backendInterlock.id,
          name: backendInterlock.name,
          description: backendInterlock.description || '',
          enabled: backendInterlock.enabled,
          conditions: backendInterlock.conditions || [],
          conditionLogic: backendInterlock.conditionLogic || 'AND',
          controls: backendInterlock.controls || [],
          bypassAllowed: backendInterlock.bypassAllowed || false,
          maxBypassDuration: backendInterlock.maxBypassDuration,
          bypassed: backendInterlock.bypassed || false,
          bypassedBy: backendInterlock.bypassedBy,
          bypassedAt: backendInterlock.bypassedAt,
          bypassReason: backendInterlock.bypassReason,
          isCritical: backendInterlock.isCritical || false,
          priority: backendInterlock.priority || 'medium',
          silRating: backendInterlock.silRating,
          requiresAcknowledgment: backendInterlock.requiresAcknowledgment || false,
          proofTestInterval: backendInterlock.proofTestInterval,
          demandCount: backendInterlock.demandCount || 0,
          lastDemandTime: backendInterlock.lastDemandTime,
          lastProofTest: backendInterlock.lastProofTest
        } as Interlock)
      }
    }
  }

  /**
   * Handle individual interlock updates from backend
   */
  function handleBackendInterlockUpdate(payload: BackendInterlockUpdatePayload) {
    if (!payload?.id) return

    const existing = interlocks.value.find(i => i.id === payload.id)
    if (existing) {
      Object.assign(existing, payload)
      console.debug(`[SAFETY] Updated interlock from backend: ${payload.name}`)
    }
  }

  /**
   * Handle alarms received from the backend via MQTT
   */
  function handleBackendAlarm(alarm: BackendAlarmPayload, event: 'triggered' | 'updated' | 'cleared') {
    try {
      _processBackendAlarm(alarm, event)
    } catch (e) {
      console.warn('[SAFETY] Error processing backend alarm:', e)
    }
  }

  function _processBackendAlarm(alarm: BackendAlarmPayload, event: 'triggered' | 'updated' | 'cleared') {
    const alarmId = alarm.alarm_id || alarm.id || `alarm-${Date.now()}`

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
        existing.state = (alarm.state || existing.state) as AlarmState
        existing.current_value = alarm.current_value
        existing.acknowledged_at = alarm.acknowledged_at
        existing.acknowledged_by = alarm.acknowledged_by
        existing.shelved_at = alarm.shelved_at
        existing.shelved_by = alarm.shelved_by
        existing.shelve_expires_at = alarm.shelve_expires_at
        existing.shelve_reason = alarm.shelve_reason
        existing.duration_seconds = alarm.duration_seconds ?? existing.duration_seconds
      }
    } else {
      // New alarm from backend
      const activeAlarm: ActiveAlarm = {
        id: alarmId,
        alarm_id: alarmId,
        channel: alarm.channel || '',
        name: alarm.name,
        severity: alarm.severity as AlarmSeverityLevel,
        state: (alarm.state || 'active') as AlarmState,
        threshold_type: (alarm.threshold_type || 'high') as ActiveAlarm['threshold_type'],
        threshold: alarm.threshold ?? 0,
        value: alarm.value ?? 0,
        current_value: alarm.current_value,
        triggered_at: alarm.triggered_at || new Date().toISOString(),
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
        channel: alarm.channel || '',
        event_type: 'triggered',
        severity: alarm.severity as AlarmSeverityLevel,
        value: alarm.value ?? 0,
        threshold: alarm.threshold ?? 0,
        threshold_type: (alarm.threshold_type || 'high') as ActiveAlarm['threshold_type'],
        triggered_at: alarm.triggered_at || new Date().toISOString(),
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
    interlockHistory: readonly(interlockHistory),

    // Interlock management
    addInterlock,
    updateInterlock,
    removeInterlock,
    bypassInterlock,
    removeBypass,
    recordProofTest,

    // Interlock checking
    isControlBlocked,
    isScheduleBlocked,
    isRecordingBlocked,
    isAcquisitionBlocked,
    isSessionBlocked,
    isScriptBlocked,
    isOutputBlocked,
    isButtonBlocked,
    evaluateCondition,
    evaluateConditionGroup,
    evaluateVoting,

    // Backend sync
    syncInterlockToBackend,
    syncAllInterlocksToBackend,
    syncAlarmConfigsToBackend,

    // Trip acknowledgment (IEC 61511)
    acknowledgeTrip,

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

    // Latch control (backend-authoritative)
    armLatch,
    disarmLatch,

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
