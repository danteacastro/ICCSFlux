import { ref, onUnmounted, computed } from 'vue'
import mqtt, { type MqttClient, type IClientOptions } from 'mqtt'
import type { ChannelValue, SystemStatus, ChannelConfig, RecordingConfig, RecordedFile } from '../types'
import { usePlayground } from './usePlayground'

// Stale data threshold in milliseconds
const STALE_DATA_THRESHOLD_MS = 10000 // 10 seconds
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000
const COMMAND_ACK_TIMEOUT_MS = 5000

// Pending command interface
interface PendingCommand {
  requestId: string
  command: string
  timestamp: number
  resolve: (result: { success: boolean; error?: string }) => void
  reject: (error: Error) => void
}

export function useMqtt(systemPrefix: string = 'nisystem') {
  const client = ref<MqttClient | null>(null)
  const connected = ref(false)
  const error = ref<string | null>(null)
  const reconnectAttempts = ref(0)
  const lastMessageTime = ref<number>(0)

  // Stale data detection
  const dataIsStale = computed(() => {
    if (!connected.value) return true
    if (lastMessageTime.value === 0) return false
    return Date.now() - lastMessageTime.value > STALE_DATA_THRESHOLD_MS
  })

  // Reactive data
  const channelValues = ref<Record<string, ChannelValue>>({})
  const systemStatus = ref<SystemStatus | null>(null)
  const channelConfigs = ref<Record<string, ChannelConfig>>({})

  // Discovery state
  const discoveryResult = ref<any>(null)
  const discoveryChannels = ref<any[]>([])
  const isScanning = ref(false)

  // Channel lifecycle callbacks
  const channelDeletedCallbacks: ((channelName: string) => void)[] = []
  const channelCreatedCallbacks: ((channels: string[]) => void)[] = []

  // Recording state
  const recordingConfig = ref<Partial<RecordingConfig>>({})
  const recordedFiles = ref<RecordedFile[]>([])

  // Watchdog state
  const watchdogStatus = ref<{
    status: 'online' | 'offline' | 'unknown'
    daqOnline: boolean
    failsafeTriggered: boolean
    failsafeTriggerTime: string | null
    lastHeartbeat: string | null
    timeoutSec: number
    timestamp: string | null
  }>({
    status: 'unknown',
    daqOnline: false,
    failsafeTriggered: false,
    failsafeTriggerTime: null,
    lastHeartbeat: null,
    timeoutSec: 10,
    timestamp: null
  })

  // Heartbeat state
  const lastHeartbeat = ref<{
    sequence: number
    timestamp: string
    acquiring: boolean
    recording: boolean
    uptime_seconds: number
  } | null>(null)
  const lastHeartbeatTime = ref<number>(0)

  // Command acknowledgment tracking
  const pendingCommands = new Map<string, PendingCommand>()

  // Callbacks
  const dataCallbacks: ((data: Record<string, number>) => void)[] = []
  const statusCallbacks: ((status: SystemStatus) => void)[] = []
  const discoveryCallbacks: ((result: any) => void)[] = []
  const configUpdateCallbacks: ((result: any) => void)[] = []
  const recordingCallbacks: ((result: any) => void)[] = []
  const fullConfigCallbacks: ((config: any) => void)[] = []

  // Generic topic subscriptions
  const topicCallbacks: Map<string, ((payload: any) => void)[]> = new Map()

  // Calculate exponential backoff delay
  function getReconnectDelay(): number {
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectAttempts.value),
      RECONNECT_MAX_DELAY_MS
    )
    return delay
  }

  function connect(brokerUrl: string = 'ws://localhost:9001') {
    const options: IClientOptions = {
      clientId: `nisystem-dashboard-${Math.random().toString(16).slice(2, 8)}`,
      clean: false, // Changed to false to allow message queuing
      reconnectPeriod: getReconnectDelay(),
      connectTimeout: 30000,
    }

    client.value = mqtt.connect(brokerUrl, options)

    client.value.on('connect', () => {
      connected.value = true
      error.value = null
      reconnectAttempts.value = 0 // Reset on successful connect
      console.log('MQTT connected')

      // Subscribe to topics with QoS 1 for reliable delivery
      const topics = [
        `${systemPrefix}/channels/#`,
        `${systemPrefix}/status/#`,
        `${systemPrefix}/config/#`,
        `${systemPrefix}/alarms/#`,
        `${systemPrefix}/discovery/#`,
        `${systemPrefix}/recording/#`,
        `${systemPrefix}/watchdog/#`,
        `${systemPrefix}/project/#`,  // Project management topics
        `${systemPrefix}/variables/#`,  // User variables / Playground
        `${systemPrefix}/test-session/#`,  // Test session management
        `${systemPrefix}/formulas/#`,  // Formula blocks
        `${systemPrefix}/heartbeat`,  // Service heartbeat
        `${systemPrefix}/command/ack`,  // Command acknowledgments
        `${systemPrefix}/config/channel/deleted`,
        `${systemPrefix}/config/channel/bulk-create/response`
      ]

      topics.forEach(topic => {
        client.value?.subscribe(topic, { qos: 1 }, (err) => {
          if (err) console.error(`Subscribe error for ${topic}:`, err)
          else console.log(`Subscribed to ${topic}`)
        })
      })
    })

    client.value.on('reconnect', () => {
      reconnectAttempts.value++
      console.log(`MQTT reconnecting (attempt ${reconnectAttempts.value}, delay: ${getReconnectDelay()}ms)`)
    })

    client.value.on('message', (topic: string, message: Buffer) => {
      try {
        // Update last message time for stale detection
        lastMessageTime.value = Date.now()

        const payload = JSON.parse(message.toString())

        if (topic.startsWith(`${systemPrefix}/channels/`)) {
          // Individual channel value: nisystem/channels/<channel_name>
          const channelName = topic.split('/').pop() || ''
          handleChannelValue(channelName, payload)
        } else if (topic === `${systemPrefix}/status/system`) {
          handleStatus(payload)
        } else if (topic === `${systemPrefix}/config/channels`) {
          handleChannelConfig(payload)
        } else if (topic === `${systemPrefix}/config/response`) {
          handleConfigResponse(payload)
        } else if (topic === `${systemPrefix}/discovery/result`) {
          handleDiscoveryResult(payload)
        } else if (topic === `${systemPrefix}/discovery/channels`) {
          handleDiscoveryChannels(payload)
        } else if (topic.startsWith(`${systemPrefix}/alarms/`)) {
          handleAlarm(topic, payload)
        } else if (topic === `${systemPrefix}/config/current`) {
          handleFullConfig(payload)
        } else if (topic === `${systemPrefix}/recording/config/current`) {
          handleRecordingConfig(payload)
        } else if (topic === `${systemPrefix}/recording/list/response`) {
          handleRecordingList(payload)
        } else if (topic === `${systemPrefix}/recording/response`) {
          handleRecordingResponse(payload)
        } else if (topic === `${systemPrefix}/config/channel/deleted`) {
          handleChannelDeleted(payload)
        } else if (topic === `${systemPrefix}/config/channel/bulk-create/response`) {
          handleBulkCreateResponse(payload)
        } else if (topic.startsWith(`${systemPrefix}/watchdog/`)) {
          handleWatchdogMessage(topic, payload)
        } else if (topic === `${systemPrefix}/variables/config`) {
          handleVariablesConfig(payload)
        } else if (topic === `${systemPrefix}/variables/values`) {
          handleVariablesValues(payload)
        } else if (topic === `${systemPrefix}/test-session/status`) {
          handleTestSessionStatus(payload)
        } else if (topic === `${systemPrefix}/formulas/config`) {
          handleFormulaBlocksConfig(payload)
        } else if (topic === `${systemPrefix}/formulas/values`) {
          handleFormulaBlocksValues(payload)
        } else if (topic === `${systemPrefix}/heartbeat`) {
          handleHeartbeat(payload)
        } else if (topic === `${systemPrefix}/command/ack`) {
          handleCommandAck(payload)
        }

        // Handle generic topic subscriptions
        const callbacks = topicCallbacks.get(topic)
        if (callbacks) {
          callbacks.forEach(cb => cb(payload))
        }
      } catch (e) {
        console.error('Error parsing MQTT message:', e)
      }
    })

    client.value.on('error', (err) => {
      error.value = err.message
      console.error('MQTT error:', err)
    })

    client.value.on('close', () => {
      connected.value = false
    })
  }

  function handleChannelValue(channelName: string, payload: any) {
    const config = channelConfigs.value[channelName]
    const value = payload.value
    const timestamp = payload.timestamp ? new Date(payload.timestamp).getTime() : Date.now()

    channelValues.value[channelName] = {
      name: channelName,
      value,
      timestamp,
      alarm: payload.quality === 'alarm' || (config ? isAlarm(value, config) : false),
      warning: payload.quality === 'warning' || (config ? isWarning(value, config) : false)
    }

    // Call data callbacks with aggregated format for compatibility
    const data: Record<string, number> = { [channelName]: value }
    dataCallbacks.forEach(cb => cb(data))
  }

  function handleStatus(status: SystemStatus) {
    systemStatus.value = status
    statusCallbacks.forEach(cb => cb(status))
  }

  function handleChannelConfig(payload: { channels: Record<string, any> }) {
    // Transform backend format to frontend format
    const configs: Record<string, ChannelConfig> = {}

    if (payload.channels) {
      Object.entries(payload.channels).forEach(([name, ch]) => {
        configs[name] = {
          name: ch.name || name,
          display_name: ch.name || name,  // TAG = channel name/ID
          channel_type: ch.channel_type || ch.type as any,
          unit: ch.units || '',
          group: ch.group || ch.module || 'Ungrouped',
          description: ch.description,  // Description is separate documentation
          visible: ch.visible !== false, // Default to true if not specified
          low_limit: ch.low_limit,
          high_limit: ch.high_limit,
          low_warning: ch.low_warning,
          high_warning: ch.high_warning,
          chartable: ['thermocouple', 'voltage', 'current'].includes(ch.channel_type || ch.type),
          // Scaling parameters
          scale_slope: ch.scale_slope,
          scale_offset: ch.scale_offset,
          scale_type: ch.scale_type,
          // 4-20mA scaling
          four_twenty_scaling: ch.four_twenty_scaling,
          eng_units_min: ch.eng_units_min,
          eng_units_max: ch.eng_units_max,
          // Map scaling
          pre_scaled_min: ch.pre_scaled_min,
          pre_scaled_max: ch.pre_scaled_max,
          scaled_min: ch.scaled_min,
          scaled_max: ch.scaled_max,
          // Scaling info from backend
          scaling_info: ch.scaling_info,
          // Thermocouple-specific
          thermocouple_type: ch.thermocouple_type,
          cjc_source: ch.cjc_source,
          // Ranges
          voltage_range: ch.voltage_range,
          current_range_ma: ch.current_range_ma,
          // Digital I/O
          invert: ch.invert,
          default_state: ch.default_state,
          default_value: ch.default_value,
          // Safety
          safety_action: ch.safety_action,
          safety_interlock: ch.safety_interlock,
          // Logging
          log: ch.log,
          log_interval_ms: ch.log_interval_ms,
        }
      })
    }

    channelConfigs.value = configs
    console.log('Channel configs loaded:', Object.keys(configs).length)
  }

  function handleAlarm(topic: string, payload: any) {
    console.warn('ALARM:', topic, payload)
  }

  function handleDiscoveryResult(payload: any) {
    discoveryResult.value = payload
    isScanning.value = false
    console.log('Discovery result:', payload)
    discoveryCallbacks.forEach(cb => cb(payload))
  }

  function handleDiscoveryChannels(payload: any) {
    discoveryChannels.value = payload.channels || []
    console.log('Discovery channels:', discoveryChannels.value.length)
  }

  function handleConfigResponse(payload: any) {
    console.log('Config response:', payload)
    configUpdateCallbacks.forEach(cb => cb(payload))
  }

  function handleRecordingConfig(payload: any) {
    if (payload.config) {
      recordingConfig.value = payload.config
    }
    console.log('Recording config received:', payload)
  }

  function handleRecordingList(payload: any) {
    if (payload.files) {
      recordedFiles.value = payload.files
    }
    console.log('Recorded files list received:', payload.files?.length || 0, 'files')
  }

  function handleRecordingResponse(payload: any) {
    console.log('Recording response:', payload)
    recordingCallbacks.forEach(cb => cb(payload))
  }

  function handleFullConfig(payload: any) {
    console.log('Full config received:', payload)
    fullConfigCallbacks.forEach(cb => cb(payload))
  }

  function handleChannelDeleted(payload: any) {
    const channelName = payload.channel
    if (channelName) {
      // Remove from local configs
      if (channelConfigs.value[channelName]) {
        delete channelConfigs.value[channelName]
      }
      if (channelValues.value[channelName]) {
        delete channelValues.value[channelName]
      }
      console.log('Channel deleted:', channelName)
      channelDeletedCallbacks.forEach(cb => cb(channelName))
    }
  }

  function handleBulkCreateResponse(payload: any) {
    console.log('Bulk create response:', payload)
    if (payload.created && payload.created.length > 0) {
      channelCreatedCallbacks.forEach(cb => cb(payload.created))
    }
    configUpdateCallbacks.forEach(cb => cb(payload))
  }

  function handleWatchdogMessage(topic: string, payload: any) {
    const subtopic = topic.split('/').pop()

    if (subtopic === 'status') {
      // Update watchdog status
      watchdogStatus.value = {
        status: payload.status || 'unknown',
        daqOnline: payload.daq_online ?? false,
        failsafeTriggered: payload.failsafe_triggered ?? false,
        failsafeTriggerTime: payload.failsafe_trigger_time || null,
        lastHeartbeat: payload.last_heartbeat || null,
        timeoutSec: payload.timeout_sec ?? 10,
        timestamp: payload.timestamp || null
      }
      console.log('Watchdog status updated:', watchdogStatus.value.status,
        watchdogStatus.value.failsafeTriggered ? '(FAILSAFE ACTIVE)' : '')
    } else if (subtopic === 'event') {
      // Log watchdog events (failsafe triggered, daq recovered, etc.)
      console.warn('Watchdog event:', payload.event, '-', payload.message)
    }
  }

  // ========================================================================
  // User Variables / Playground Handlers
  // ========================================================================

  // Get playground composable instance (singleton)
  const playground = usePlayground()

  // Wire up playground MQTT handlers
  playground.setMqttHandlers({
    publish: (topic: string, payload: any) => {
      if (client.value && connected.value) {
        client.value.publish(topic, JSON.stringify(payload))
      } else {
        console.warn('MQTT not connected, cannot publish:', topic)
      }
    }
  })

  function handleVariablesConfig(payload: any) {
    console.log('MQTT: Received variables config:', payload)
    playground.handleVariablesConfig(payload)
  }

  function handleVariablesValues(payload: any) {
    console.log('MQTT: Received variables values:', Object.keys(payload).length, 'variables')
    playground.handleVariablesValues(payload)
  }

  function handleTestSessionStatus(payload: any) {
    console.log('MQTT: Received test session status:', payload)
    playground.handleTestSessionStatus(payload)
  }

  function handleFormulaBlocksConfig(payload: any) {
    console.log('MQTT: Received formula blocks config:', Object.keys(payload).length, 'blocks')
    playground.handleFormulaBlocksConfig(payload)
  }

  function handleFormulaBlocksValues(payload: any) {
    console.log('MQTT: Received formula blocks values')
    playground.handleFormulaBlocksValues(payload)
  }

  function handleHeartbeat(payload: any) {
    lastHeartbeat.value = payload
    lastHeartbeatTime.value = Date.now()
  }

  function handleCommandAck(payload: any) {
    const { request_id, success, error: errorMsg } = payload

    if (request_id && pendingCommands.has(request_id)) {
      const pending = pendingCommands.get(request_id)!
      pendingCommands.delete(request_id)

      if (success) {
        pending.resolve({ success: true })
      } else {
        pending.resolve({ success: false, error: errorMsg || 'Command failed' })
      }
    }
  }

  /**
   * Generate a unique request ID for command tracking
   */
  function generateRequestId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
  }

  /**
   * Send a command with acknowledgment tracking
   * Returns a Promise that resolves when the DAQ acknowledges the command
   * or rejects after timeout
   */
  async function sendCommandWithAck(
    command: string,
    payload?: any,
    timeoutMs: number = COMMAND_ACK_TIMEOUT_MS
  ): Promise<{ success: boolean; error?: string }> {
    if (!client.value || !connected.value) {
      return { success: false, error: 'MQTT not connected' }
    }

    const requestId = generateRequestId()
    const topic = `${systemPrefix}/${command}`
    const message = {
      ...(payload || {}),
      request_id: requestId
    }

    return new Promise((resolve, reject) => {
      // Set up timeout
      const timeoutId = setTimeout(() => {
        if (pendingCommands.has(requestId)) {
          pendingCommands.delete(requestId)
          resolve({ success: false, error: 'Command timed out waiting for acknowledgment' })
        }
      }, timeoutMs)

      // Track the pending command
      pendingCommands.set(requestId, {
        requestId,
        command,
        timestamp: Date.now(),
        resolve: (result) => {
          clearTimeout(timeoutId)
          resolve(result)
        },
        reject: (error) => {
          clearTimeout(timeoutId)
          reject(error)
        }
      })

      // Publish the command
      client.value!.publish(topic, JSON.stringify(message))
    })
  }

  /**
   * Send a system command with acknowledgment tracking
   */
  async function sendSystemCommandWithAck(
    command: string,
    payload?: any,
    timeoutMs: number = COMMAND_ACK_TIMEOUT_MS
  ): Promise<{ success: boolean; error?: string }> {
    return sendCommandWithAck(`system/${command}`, payload, timeoutMs)
  }

  function isAlarm(value: number, config: ChannelConfig): boolean {
    if (config.low_limit !== undefined && value < config.low_limit) return true
    if (config.high_limit !== undefined && value > config.high_limit) return true
    return false
  }

  function isWarning(value: number, config: ChannelConfig): boolean {
    if (config.low_warning !== undefined && value < config.low_warning) return true
    if (config.high_warning !== undefined && value > config.high_warning) return true
    return false
  }

  // Commands - using backend's topic structure
  function sendSystemCommand(command: string, payload?: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    const topic = `${systemPrefix}/system/${command}`
    const message = payload !== undefined ? JSON.stringify(payload) : '{}'

    client.value.publish(topic, message)
  }

  function sendCommand(command: string, payload?: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    const topic = `${systemPrefix}/${command}`
    const message = payload !== undefined ? JSON.stringify(payload) : '{}'

    client.value.publish(topic, message)
  }

  /**
   * Subscribe to a specific topic with a callback
   * Returns an unsubscribe function
   */
  function subscribe(topic: string, callback: (payload: any) => void): () => void {
    if (!topicCallbacks.has(topic)) {
      topicCallbacks.set(topic, [])
    }
    topicCallbacks.get(topic)!.push(callback)

    // Return unsubscribe function
    return () => {
      const callbacks = topicCallbacks.get(topic)
      if (callbacks) {
        const idx = callbacks.indexOf(callback)
        if (idx > -1) {
          callbacks.splice(idx, 1)
        }
        if (callbacks.length === 0) {
          topicCallbacks.delete(topic)
        }
      }
    }
  }

  function startAcquisition() {
    sendSystemCommand('acquire/start')
  }

  function stopAcquisition() {
    sendSystemCommand('acquire/stop')
  }

  function startRecording(filename?: string) {
    sendSystemCommand('recording/start', filename ? { filename } : undefined)
  }

  function stopRecording() {
    sendSystemCommand('recording/stop')
  }

  function enableScheduler() {
    sendCommand('schedule/enable')
  }

  function disableScheduler() {
    sendCommand('schedule/disable')
  }

  function loadConfig(configName: string) {
    sendCommand('config/load', { config: configName })
  }

  function saveConfig(configName: string) {
    sendCommand('config/save', { config: configName })
  }

  function setOutput(channelName: string, value: number | boolean) {
    // Output commands go to nisystem/commands/<channel_name>
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/commands/${channelName}`, JSON.stringify({ value }))
  }

  function resetCounter(channelName: string) {
    // Reset counter channel to zero
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/channel/reset`, JSON.stringify({ channel: channelName }))
  }

  // Discovery functions
  function scanDevices() {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    isScanning.value = true
    discoveryResult.value = null
    discoveryChannels.value = []
    client.value.publish(`${systemPrefix}/discovery/scan`, '')
    console.log('Discovery scan requested')
  }

  function onDiscovery(callback: (result: any) => void) {
    discoveryCallbacks.push(callback)
  }

  // Config update functions
  function updateChannelConfig(channelName: string, config: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = {
      channel: channelName,
      config: config
    }
    client.value.publish(`${systemPrefix}/config/channel/update`, JSON.stringify(payload))
    console.log('Channel config update sent:', channelName)
  }

  function saveSystemConfig(configName?: string) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = configName ? { config: configName } : {}
    client.value.publish(`${systemPrefix}/config/save`, JSON.stringify(payload))
    console.log('Config save requested')
  }

  function onConfigUpdate(callback: (result: any) => void) {
    configUpdateCallbacks.push(callback)
  }

  function createChannel(name: string, config: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = {
      name,
      config
    }
    client.value.publish(`${systemPrefix}/config/channel/create`, JSON.stringify(payload))
    console.log('Channel create sent:', name)
  }

  function deleteChannel(name: string, force: boolean = false) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = {
      name,
      force
    }
    client.value.publish(`${systemPrefix}/config/channel/delete`, JSON.stringify(payload))
    console.log('Channel delete sent:', name)
  }

  function bulkCreateChannels(channels: any[]) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = { channels }
    client.value.publish(`${systemPrefix}/config/channel/bulk-create`, JSON.stringify(payload))
    console.log('Bulk create sent:', channels.length, 'channels')
  }

  function onChannelDeleted(callback: (channelName: string) => void) {
    channelDeletedCallbacks.push(callback)
  }

  function onChannelCreated(callback: (channels: string[]) => void) {
    channelCreatedCallbacks.push(callback)
  }

  function onConfigCurrent(callback: (config: any) => void): () => void {
    fullConfigCallbacks.push(callback)
    // Return unsubscribe function
    return () => {
      const index = fullConfigCallbacks.indexOf(callback)
      if (index > -1) {
        fullConfigCallbacks.splice(index, 1)
      }
    }
  }

  // Recording management functions
  function updateRecordingConfig(config: Partial<RecordingConfig>) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/recording/config`, JSON.stringify(config))
    console.log('Recording config update sent')
  }

  function getRecordingConfig() {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/recording/config/get`, '')
  }

  function listRecordedFiles() {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/recording/list`, '')
  }

  function deleteRecordedFile(filename: string) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    client.value.publish(`${systemPrefix}/recording/delete`, JSON.stringify({ filename }))
  }

  function sendScriptValues(values: Record<string, number>) {
    if (!client.value || !connected.value) {
      return
    }
    client.value.publish(`${systemPrefix}/recording/script-values`, JSON.stringify({ values }))
  }

  function onRecordingResponse(callback: (result: any) => void) {
    recordingCallbacks.push(callback)
  }

  // Event subscription
  function onData(callback: (data: Record<string, number>) => void) {
    dataCallbacks.push(callback)
  }

  function onStatus(callback: (status: SystemStatus) => void) {
    statusCallbacks.push(callback)
  }

  function disconnect() {
    if (client.value) {
      client.value.end()
      client.value = null
    }
    connected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    // State
    connected,
    error,
    channelValues,
    systemStatus,
    channelConfigs,

    // Network health
    dataIsStale,
    reconnectAttempts,
    lastMessageTime,

    // Discovery state
    discoveryResult,
    discoveryChannels,
    isScanning,

    // Recording state
    recordingConfig,
    recordedFiles,

    // Watchdog state
    watchdogStatus,

    // Connection
    connect,
    disconnect,

    // Commands
    startAcquisition,
    stopAcquisition,
    startRecording,
    stopRecording,
    enableScheduler,
    disableScheduler,
    loadConfig,
    saveConfig,
    setOutput,
    resetCounter,
    sendCommand,
    subscribe,

    // Discovery
    scanDevices,
    onDiscovery,

    // Config updates
    updateChannelConfig,
    saveSystemConfig,
    onConfigUpdate,
    onConfigCurrent,

    // Channel lifecycle
    createChannel,
    deleteChannel,
    bulkCreateChannels,
    onChannelDeleted,
    onChannelCreated,

    // Recording management
    updateRecordingConfig,
    getRecordingConfig,
    listRecordedFiles,
    deleteRecordedFile,
    sendScriptValues,
    onRecordingResponse,

    // Events
    onData,
    onStatus,

    // Sequence control (for backend integration)
    startSequence: (sequenceId: string, steps: any[]) => {
      sendCommand('sequence/start', { sequenceId, steps })
    },
    pauseSequence: (sequenceId: string) => {
      sendCommand('sequence/pause', { sequenceId })
    },
    resumeSequence: (sequenceId: string) => {
      sendCommand('sequence/resume', { sequenceId })
    },
    abortSequence: (sequenceId: string) => {
      sendCommand('sequence/abort', { sequenceId })
    },

    // Alarm control
    triggerAlarm: (alarmId: string, alarm: any) => {
      sendCommand('alarm/trigger', { alarmId, ...alarm })
    },
    acknowledgeAlarm: (alarmId: string) => {
      sendCommand('alarm/acknowledge', { alarmId })
    },
    clearAlarm: (alarmId: string) => {
      sendCommand('alarm/clear', { alarmId })
    },
    resetAllLatched: () => {
      sendCommand('alarm/reset-latched', {})
    },

    // Heartbeat / health monitoring
    lastHeartbeat,
    lastHeartbeatTime,

    // Command acknowledgment
    sendCommandWithAck,
    sendSystemCommandWithAck
  }
}
