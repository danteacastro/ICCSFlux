import { ref, onUnmounted, computed } from 'vue'
import mqtt, { type MqttClient, type IClientOptions } from 'mqtt'
import type { ChannelValue, SystemStatus, ChannelConfig, RecordingConfig, RecordedFile } from '../types'

// Stale data threshold in milliseconds
const STALE_DATA_THRESHOLD_MS = 10000 // 10 seconds
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000

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

  // Recording state
  const recordingConfig = ref<Partial<RecordingConfig>>({})
  const recordedFiles = ref<RecordedFile[]>([])

  // Callbacks
  const dataCallbacks: ((data: Record<string, number>) => void)[] = []
  const statusCallbacks: ((status: SystemStatus) => void)[] = []
  const discoveryCallbacks: ((result: any) => void)[] = []
  const configUpdateCallbacks: ((result: any) => void)[] = []
  const recordingCallbacks: ((result: any) => void)[] = []
  const fullConfigCallbacks: ((config: any) => void)[] = []

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
        `${systemPrefix}/watchdog/#`  // Also subscribe to watchdog status
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
          display_name: ch.description || ch.name || name,
          channel_type: ch.channel_type || ch.type as any,
          unit: ch.units || '',
          group: ch.module || 'Ungrouped',
          description: ch.description,
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
    sendCommand,

    // Discovery
    scanDevices,
    onDiscovery,

    // Config updates
    updateChannelConfig,
    saveSystemConfig,
    onConfigUpdate,
    onConfigCurrent,

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
    }
  }
}
