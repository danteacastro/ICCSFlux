/**
 * cRIO Service Composable
 *
 * Provides integration with cRIO controllers running on NI Linux RT.
 * Handles:
 * - Connection status monitoring
 * - Digital I/O state management
 * - Safety state tracking
 * - Remote control of digital outputs
 *
 * This composable uses a singleton pattern so state is shared across all components.
 */

import { ref, computed, watch, readonly } from 'vue'
import { useMqtt } from './useMqtt'

// ============================================
// Types
// ============================================

export interface CrioStatus {
  crio_id: string
  crio_name: string
  online: boolean
  simulation_mode: boolean
  state: 'normal' | 'warning' | 'tripped' | 'emergency'
  pc_watchdog_ok: boolean
  uptime_sec: number
  scan_count: number
  tripped_inputs: string[]
  requires_reset: boolean
  active_alarms: string[]
  input_states: Record<string, boolean>
  output_states: Record<string, boolean>
  timestamp: string
}

export interface CrioHeartbeat {
  crio_id: string
  state: string
  timestamp: string
}

export interface CrioEvent {
  type: 'input_triggered' | 'input_cleared' | 'safety_action' | 'pc_watchdog_timeout'
  input?: string
  description?: string
  action?: string
  source?: string
  outputs_affected?: string[]
  requires_reset?: boolean
  timestamp: string
}

export interface CrioAlarm {
  id: string
  source: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  message: string
  state: 'active' | 'cleared'
  timestamp: string
}

export interface DigitalInputInfo {
  name: string
  description: string
  active: boolean
  tripped: boolean
}

export interface DigitalOutputInfo {
  name: string
  description: string
  state: boolean
  allow_remote: boolean
}

// ============================================
// Singleton State
// ============================================

const crioStatus = ref<CrioStatus | null>(null)
const crioConnected = ref(false)
const crioHeartbeats = ref<CrioHeartbeat[]>([])
const crioEvents = ref<CrioEvent[]>([])
const crioAlarms = ref<Record<string, CrioAlarm>>({})

// Last heartbeat tracking
const lastHeartbeatTime = ref<number>(0)
const heartbeatTimeoutMs = 5000  // Consider offline after 5s without heartbeat

// Initialization flag
let initialized = false
let heartbeatIntervalId: number | null = null

// ============================================
// Composable Factory
// ============================================

export function useCrio() {
  const mqtt = useMqtt('nisystem')

  // ============================================
  // Computed Properties
  // ============================================

  const isOnline = computed(() => crioConnected.value && crioStatus.value?.online === true)

  const safetyState = computed(() => crioStatus.value?.state || 'unknown')

  const isEmergency = computed(() => safetyState.value === 'emergency')
  const isTripped = computed(() => safetyState.value === 'tripped' || safetyState.value === 'emergency')
  const isWarning = computed(() => safetyState.value === 'warning')
  const isNormal = computed(() => safetyState.value === 'normal')

  const requiresReset = computed(() => crioStatus.value?.requires_reset === true)

  const trippedInputs = computed(() => crioStatus.value?.tripped_inputs || [])

  const activeAlarmCount = computed(() => crioStatus.value?.active_alarms?.length || 0)

  const inputStates = computed(() => crioStatus.value?.input_states || {})
  const outputStates = computed(() => crioStatus.value?.output_states || {})

  const uptime = computed(() => {
    const secs = crioStatus.value?.uptime_sec || 0
    const hours = Math.floor(secs / 3600)
    const mins = Math.floor((secs % 3600) / 60)
    return `${hours}h ${mins}m`
  })

  // ============================================
  // MQTT Message Handlers
  // ============================================

  function handleStatusMessage(payload: any) {
    try {
      const parsed = typeof payload === 'string' ? JSON.parse(payload) : payload
      if (!parsed || typeof parsed !== 'object' || typeof parsed.online !== 'boolean') {
        console.warn('[cRIO] Status payload missing expected fields:', parsed)
        return
      }
      const status = parsed as CrioStatus
      crioStatus.value = status
      crioConnected.value = status.online

      if (status.online) {
        lastHeartbeatTime.value = Date.now()
      }
    } catch (e) {
      console.warn('[cRIO] Error parsing cRIO status:', e)
    }
  }

  function handleHeartbeatMessage(payload: any) {
    try {
      const parsed = typeof payload === 'string' ? JSON.parse(payload) : payload
      if (!parsed || typeof parsed !== 'object' || typeof parsed.state !== 'string') {
        console.warn('[cRIO] Heartbeat payload missing expected fields:', parsed)
        return
      }
      const heartbeat = parsed as CrioHeartbeat
      lastHeartbeatTime.value = Date.now()
      crioConnected.value = true

      // Keep last 10 heartbeats
      crioHeartbeats.value.unshift(heartbeat)
      if (crioHeartbeats.value.length > 10) {
        crioHeartbeats.value = crioHeartbeats.value.slice(0, 10)
      }

      // Update state from heartbeat
      if (crioStatus.value) {
        crioStatus.value.state = heartbeat.state as CrioStatus['state']
      }
    } catch (e) {
      console.warn('[cRIO] Error parsing cRIO heartbeat:', e)
    }
  }

  // ============================================
  // Actions
  // ============================================

  /**
   * Set a digital output on the cRIO
   */
  function setOutput(name: string, value: boolean): Promise<boolean> {
    return new Promise((resolve) => {
      const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

      const payload = {
        request_id: requestId,
        [name]: value,
        timestamp: new Date().toISOString()
      }

      mqtt.sendCommand('crio/do/set', payload)

      // Do NOT optimistically update — wait for cRIO status message to confirm.
      // If the cRIO rejects the write (safety interlock blocking), the dashboard
      // would show wrong output state until the next status message.

      resolve(true)
    })
  }

  /**
   * Set multiple digital outputs at once
   */
  function setOutputs(values: Record<string, boolean>): Promise<boolean> {
    return new Promise((resolve) => {
      const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

      const payload = {
        request_id: requestId,
        ...values,
        timestamp: new Date().toISOString()
      }

      mqtt.sendCommand('crio/do/set', payload)

      // Do NOT optimistically update — wait for cRIO status confirmation.

      resolve(true)
    })
  }

  /**
   * Request a safety system reset
   */
  function resetSafety(): Promise<boolean> {
    return new Promise((resolve) => {
      const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

      const payload = {
        request_id: requestId,
        timestamp: new Date().toISOString()
      }

      mqtt.sendCommand('crio/reset', payload)
      resolve(true)
    })
  }

  /**
   * Request current status from cRIO
   */
  function requestStatus() {
    mqtt.sendCommand('crio/status/request', {
      timestamp: new Date().toISOString()
    })
  }

  /**
   * Simulate an input (for testing)
   */
  function simulateInput(name: string, value: boolean) {
    const payload = {
      request_id: `${Date.now()}`,
      input: name,
      value
    }
    mqtt.sendCommand('crio/commands/simulate_input', payload)
  }

  // ============================================
  // Heartbeat Monitoring
  // ============================================

  function checkHeartbeat() {
    const elapsed = Date.now() - lastHeartbeatTime.value
    if (elapsed > heartbeatTimeoutMs && crioConnected.value) {
      crioConnected.value = false
      if (crioStatus.value) {
        crioStatus.value.online = false
      }
    }
  }

  // ============================================
  // Initialization
  // ============================================

  function initialize() {
    if (initialized) return

    // Subscribe to cRIO topics when MQTT connects
    watch(() => mqtt.connected.value, (connected) => {
      if (connected) {
        // Subscribe to cRIO status
        mqtt.subscribe('nisystem/crio/status', handleStatusMessage)
        mqtt.subscribe('nisystem/crio/heartbeat', handleHeartbeatMessage)

        // For wildcard subscriptions, we need individual handlers
        // Events and alarms would be published to specific subtopics

        // Request initial status
        setTimeout(requestStatus, 500)
      }
    }, { immediate: true })

    // Start heartbeat check interval (store ID for cleanup)
    if (heartbeatIntervalId !== null) {
      clearInterval(heartbeatIntervalId)
    }
    heartbeatIntervalId = window.setInterval(checkHeartbeat, 1000)

    initialized = true
  }

  // Initialize on first use
  initialize()

  // ============================================
  // Return Public API
  // ============================================

  return {
    // Status (readonly)
    status: readonly(crioStatus),
    connected: readonly(crioConnected),
    heartbeats: readonly(crioHeartbeats),
    events: readonly(crioEvents),
    alarms: readonly(crioAlarms),

    // Computed state
    isOnline,
    safetyState,
    isEmergency,
    isTripped,
    isWarning,
    isNormal,
    requiresReset,
    trippedInputs,
    activeAlarmCount,
    inputStates,
    outputStates,
    uptime,

    // Actions
    setOutput,
    setOutputs,
    resetSafety,
    requestStatus,
    simulateInput
  }
}
