/**
 * useAzureIot - Composable for Azure IoT Hub integration
 *
 * Provides reactive state and methods for configuring Azure IoT Hub telemetry streaming.
 */

import { ref, computed } from 'vue'
import { useMqtt } from './useMqtt'

export interface AzureIotConfig {
  enabled: boolean
  channels: string[]
  batch_size: number
  batch_interval_ms: number
  has_connection_string: boolean
}

export interface AzureIotStats {
  messages_sent: number
  messages_failed: number
  samples_sent: number
  samples_dropped: number
  last_send_time: string | null
  last_error: string | null
  connected: boolean
}

// Singleton state
const config = ref<AzureIotConfig>({
  enabled: false,
  channels: [],
  batch_size: 10,
  batch_interval_ms: 1000,
  has_connection_string: false,
})

const stats = ref<AzureIotStats>({
  messages_sent: 0,
  messages_failed: 0,
  samples_sent: 0,
  samples_dropped: 0,
  last_send_time: null,
  last_error: null,
  connected: false,
})

const available = ref(false)
const isLoading = ref(false)
const lastResponse = ref<{ success: boolean; message?: string; error?: string } | null>(null)

// Track subscription
let subscribed = false

export function useAzureIot() {
  const mqtt = useMqtt('nisystem')

  // Subscribe to Azure status updates
  function initSubscriptions() {
    if (subscribed) return
    subscribed = true

    // Listen for config/status updates
    mqtt.subscribe('nisystem/azure/config/current', (payload: any) => {
      if (payload) {
        if (payload.config) {
          config.value = payload.config
        }
        if (payload.stats) {
          stats.value = payload.stats
        }
        if (typeof payload.available === 'boolean') {
          available.value = payload.available
        }
      }
      isLoading.value = false
    })

    // Listen for status updates (periodic)
    mqtt.subscribe('nisystem/azure/status', (payload: any) => {
      if (payload) {
        stats.value = payload
      }
    })

    // Listen for command responses
    mqtt.subscribe('nisystem/azure/response', (payload: any) => {
      if (payload) {
        lastResponse.value = {
          success: payload.success,
          message: payload.message,
          error: payload.error,
        }
        isLoading.value = false
      }
    })
  }

  // Request current config from backend
  function refreshConfig() {
    isLoading.value = true
    mqtt.sendCommand('azure/config/get', {})
  }

  // Update Azure IoT configuration
  function updateConfig(newConfig: {
    connection_string?: string
    channels?: string[]
    batch_size?: number
    batch_interval_ms?: number
    enabled?: boolean
  }) {
    isLoading.value = true
    lastResponse.value = null
    mqtt.sendCommand('azure/config', newConfig)
  }

  // Start Azure IoT streaming
  function start() {
    isLoading.value = true
    lastResponse.value = null
    mqtt.sendCommand('azure/start', {})
  }

  // Stop Azure IoT streaming
  function stop() {
    isLoading.value = true
    lastResponse.value = null
    mqtt.sendCommand('azure/stop', {})
  }

  // Computed properties
  const isEnabled = computed(() => config.value.enabled)
  const isConnected = computed(() => stats.value.connected)
  const hasConnectionString = computed(() => config.value.has_connection_string)

  // Initialize subscriptions on first use
  initSubscriptions()

  return {
    // State
    config,
    stats,
    available,
    isLoading,
    lastResponse,

    // Computed
    isEnabled,
    isConnected,
    hasConnectionString,

    // Methods
    refreshConfig,
    updateConfig,
    start,
    stop,
  }
}
