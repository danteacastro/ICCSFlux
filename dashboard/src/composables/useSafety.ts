/**
 * Safety & Interlock System Composable
 *
 * Provides centralized management of:
 * - Alarm configurations and active alarms
 * - Interlock definitions and status checking
 * - Latch state tracking
 *
 * This composable uses a singleton pattern so state is shared across all components.
 */

import { ref, computed, watch, readonly } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'
import type {
  AlarmConfig,
  ActiveAlarm,
  AlarmHistoryEntry,
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

// Delay tracking for alarm triggering
const delayTimers = ref<Record<string, { type: string; startTime: number }>>({})

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
      channel,
      enabled: false,
      low_alarm: channelConfig?.low_limit,
      high_alarm: channelConfig?.high_limit,
      low_warning: channelConfig?.low_warning,
      high_warning: channelConfig?.high_warning,
      behavior: 'auto_clear',
      deadband: 0,
      delay_seconds: 0,
      log_to_file: true,
      play_sound: true,
      start_recording: false,
      run_script: undefined
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

  const alarmCounts = computed(() => ({
    active: activeAlarms.value.filter(a => a.state === 'active' && a.severity === 'alarm').length,
    warnings: activeAlarms.value.filter(a => a.state === 'active' && a.severity === 'warning').length,
    acknowledged: activeAlarms.value.filter(a => a.state === 'acknowledged').length,
    total: activeAlarms.value.length
  }))

  const hasActiveAlarms = computed(() => alarmCounts.value.active > 0)
  const hasActiveWarnings = computed(() => alarmCounts.value.warnings > 0)

  // Count of latched alarms that are still active (not cleared)
  const latchedAlarmCount = computed(() => {
    return activeAlarms.value.filter(alarm => {
      const config = alarmConfigs.value[alarm.channel]
      return config?.behavior === 'latch'
    }).length
  })

  const hasLatchedAlarms = computed(() => latchedAlarmCount.value > 0)

  // ============================================
  // Alarm Actions
  // ============================================

  function acknowledgeAlarm(alarmId: string) {
    const alarm = activeAlarms.value.find(a => a.id === alarmId)
    if (alarm) {
      alarm.state = 'acknowledged'
      alarm.acknowledged_at = new Date().toISOString()
      alarm.acknowledged_by = 'User'
    }
  }

  function acknowledgeAll() {
    activeAlarms.value.forEach(alarm => {
      if (alarm.state === 'active') {
        alarm.state = 'acknowledged'
        alarm.acknowledged_at = new Date().toISOString()
        alarm.acknowledged_by = 'User'
      }
    })
  }

  function clearAlarm(alarmId: string) {
    const alarmIndex = activeAlarms.value.findIndex(a => a.id === alarmId)
    if (alarmIndex >= 0) {
      const alarm = activeAlarms.value[alarmIndex]
      if (!alarm) return

      // Add to history
      const historyEntry: AlarmHistoryEntry = {
        id: alarm.id,
        channel: alarm.channel,
        severity: alarm.severity,
        value: alarm.value,
        threshold: alarm.threshold,
        threshold_type: alarm.threshold_type,
        triggered_at: alarm.triggered_at,
        cleared_at: new Date().toISOString(),
        duration_seconds: alarm.duration_seconds,
        acknowledged_by: alarm.acknowledged_by,
        message: alarm.message
      }
      alarmHistory.value.unshift(historyEntry)

      // Keep history limited
      if (alarmHistory.value.length > 500) {
        alarmHistory.value = alarmHistory.value.slice(0, 500)
      }

      // Remove from active
      activeAlarms.value.splice(alarmIndex, 1)
    }
  }

  function resetAlarm(alarmId: string) {
    clearAlarm(alarmId)
  }

  function resetAllLatched() {
    const latchedAlarms = activeAlarms.value.filter(alarm => {
      const config = alarmConfigs.value[alarm.channel]
      return config?.behavior === 'latch'
    })
    latchedAlarms.forEach(alarm => clearAlarm(alarm.id))
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

  function bypassInterlock(id: string, bypass: boolean) {
    const interlock = interlocks.value.find(i => i.id === id)
    if (interlock && interlock.bypassAllowed) {
      interlock.bypassed = bypass
      if (bypass) {
        interlock.bypassedAt = new Date().toISOString()
        interlock.bypassedBy = 'User'
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

  function evaluateCondition(condition: InterlockCondition): { satisfied: boolean; currentValue?: any; reason: string } {
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
    localStorage.setItem('nisystem-alarm-configs', JSON.stringify(alarmConfigs.value))
  }

  function loadAlarmConfigs() {
    const saved = localStorage.getItem('nisystem-alarm-configs')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        Object.assign(alarmConfigs.value, parsed)
      } catch {}
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
      } catch {}
    }
  }

  // ============================================
  // Initialization
  // ============================================

  function initialize() {
    if (initialized) return

    // Load saved configs
    loadAlarmConfigs()
    loadInterlocks()

    // Watch for channel changes to add new configs
    watch(() => store.channels, () => {
      initializeAlarmConfigs()
    }, { immediate: true, deep: true })

    // Auto-save alarm configs on change
    watch(alarmConfigs, saveAlarmConfigs, { deep: true })

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

    // Alarm config mutation (for SafetyTab)
    updateAlarmConfig: (channel: string, config: Partial<AlarmConfig>) => {
      if (alarmConfigs.value[channel]) {
        Object.assign(alarmConfigs.value[channel], config)
      }
    },
    getAlarmConfig: (channel: string) => alarmConfigs.value[channel],

    // Alarm actions
    acknowledgeAlarm,
    acknowledgeAll,
    clearAlarm,
    resetAlarm,
    resetAllLatched,

    // For alarm processing (used by SafetyTab)
    triggerAlarm: (alarm: ActiveAlarm) => activeAlarms.value.push(alarm),
    delayTimers,

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
