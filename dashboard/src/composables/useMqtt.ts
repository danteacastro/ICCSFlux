import { ref, computed, watch } from 'vue'
import mqtt, { type MqttClient, type IClientOptions } from 'mqtt'
import type { ChannelValue, SystemStatus, ChannelConfig, ChannelType, BackendRecordingConfig, RecordedFile, NodeInfo, DiscoveryCallbackPayload, ConfigUpdateCallbackPayload, RecordingCallbackPayload, AlarmCallbackPayload, SystemUpdateCallbackPayload, CrioCallbackPayload } from '../types'
import { usePlayground } from './usePlayground'
import { usePythonScripts } from './usePythonScripts'
import { useSOE } from './useSOE'

// Stale data threshold in milliseconds
const STALE_DATA_THRESHOLD_MS = 10000 // 10 seconds
const NODE_OFFLINE_THRESHOLD_MS = 15000 // 15 seconds without message = offline
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

// ============================================================================
// H2: Typed MQTT payload interfaces (replaces `any` in handlers)
// ============================================================================

/** Channel value payload from backend (individual or within batch) */
interface MqttChannelValuePayload {
  value: number | null
  timestamp?: string | number
  node_id?: string
  quality?: string
  status?: string
  value_string?: string | null
  acquisition_ts_us?: number
}

/** Batch channel values from cRIO nodes */
type MqttBatchChannelPayload = Record<string, { value: number; timestamp: number }>

/** System status payload from backend — partial SystemStatus with extra node fields */
type MqttStatusPayload = Partial<SystemStatus> & {
  node_id?: string
  config_version?: string
  node_name?: string
  node_type?: string
  project_mode?: string
  channel_count?: number
  safety_state?: string
}

/** Channel config payload from backend — dynamic fields, typed at point of use */
interface MqttChannelConfigPayload {
  channels: Record<string, Record<string, any>>
}

/** Alarm payload from backend */
interface MqttAlarmPayload {
  alarm_id?: string
  channel?: string
  name?: string
  severity?: string
  state?: string
  active?: boolean
  threshold_type?: string
  threshold_value?: number
  triggered_value?: number
  current_value?: number
  value?: number
  triggered_at?: string
  acknowledged_at?: string
  acknowledged_by?: string
  cleared_at?: string
  sequence_number?: number
  is_first_out?: boolean
  shelved_at?: string
  shelved_by?: string
  shelve_expires_at?: string
  shelve_reason?: string
  message?: string
  duration_seconds?: number
  safety_action?: string
}

/** Discovery result payload from backend */
interface MqttDiscoveryResultPayload {
  chassis?: Array<Record<string, unknown>>
  total_channels?: number
  [key: string]: unknown
}

/** Config response payload (ACK from backend) */
interface MqttConfigResponsePayload {
  node_id?: string
  config_version?: string
  success?: boolean
  [key: string]: unknown
}

/** Recording config payload */
interface MqttRecordingConfigPayload {
  config?: Partial<BackendRecordingConfig>
}

/** Recording list payload */
interface MqttRecordingListPayload {
  files?: RecordedFile[]
}

/** Watchdog status payload */
interface MqttWatchdogPayload {
  status?: string
  daq_online?: boolean
  failsafe_triggered?: boolean
  failsafe_trigger_time?: string | null
  last_heartbeat?: string | null
  timeout_sec?: number
  timestamp?: string | null
  event?: string
  message?: string
}

/** Command ACK payload */
interface MqttCommandAckPayload {
  command?: string
  request_id?: string
  success?: boolean
  error?: string
}

/** Heartbeat payload */
interface MqttHeartbeatPayload {
  [key: string]: unknown
}

/** Script values payload from backend */
interface MqttScriptValuesPayload {
  _timestamp?: number
  [key: string]: number | undefined
}

/** Channel deleted notification */
interface MqttChannelDeletedPayload {
  channel?: string
}

/** Bulk create response */
interface MqttBulkCreatePayload {
  created?: string[]
  [key: string]: unknown
}

/** cRIO discovered payload */
interface MqttCrioDiscoveredPayload {
  node_id?: string
  [key: string]: unknown
}

/** cRIO channel discovery response */
interface MqttCrioChannelDiscoveryPayload {
  node_id?: string
  channels?: Array<Record<string, unknown>>
}

// ============================================================================
// SINGLETON STATE - Shared across all useMqtt() calls
// ============================================================================
const client = ref<MqttClient | null>(null)
const connected = ref(false)
const error = ref<string | null>(null)
const reconnectAttempts = ref(0)
const lastMessageTime = ref<number>(0)

// Reactive data (shared)
const channelValues = ref<Record<string, ChannelValue>>({})
const systemStatus = ref<SystemStatus | null>(null)
const channelConfigs = ref<Record<string, ChannelConfig>>({})

// Channel ownership tracking - prevents value collision between nodes
// Maps channel name -> nodeId that owns/updates this channel
const channelOwners = new Map<string, string>()

// Discovery state (shared)
const discoveryResult = ref<any>(null)
const discoveryChannels = ref<any[]>([])
const crioDiscoveryChannels = ref<Record<string, any[]>>({}) // nodeId -> channels
const cfpDiscoveryResult = ref<any>(null) // CFP slot probe results
const isScanning = ref(false)
let scanTimeoutId: ReturnType<typeof setTimeout> | null = null
let crioRescanTimeoutId: ReturnType<typeof setTimeout> | null = null
const SCAN_TIMEOUT_MS = 30000 // 30 second timeout for device scan

// Auth state - set by useAuth to gate permission-sensitive commands (avoids circular import)
const userAuthenticated = ref(false)

// Output rate limiting - prevents MQTT flooding from rapid UI changes (e.g., sliders)
const OUTPUT_RATE_LIMIT_MS = 50
const lastOutputSendTime = new Map<string, number>()
const pendingOutputTimers = new Map<string, ReturnType<typeof setTimeout>>()

// Channel lifecycle callbacks (shared)
const channelDeletedCallbacks: ((channelName: string) => void)[] = []
const channelCreatedCallbacks: ((channels: string[]) => void)[] = []

// Recording state (shared)
const recordingConfig = ref<Partial<BackendRecordingConfig>>({})
const recordedFiles = ref<RecordedFile[]>([])

// Full config callbacks (shared) - payload is raw config object from backend
const fullConfigCallbacks: ((config: Record<string, unknown>) => void)[] = []

// Heartbeat state (shared)
const lastHeartbeat = ref<Record<string, unknown> | null>(null)
const lastHeartbeatTime = ref<number>(0)

// Pending commands for acknowledgment (shared) - NOT a ref, just a Map
const pendingCommands = new Map<string, PendingCommand>()

// Track if MQTT handlers are initialized
let handlersInitialized = false

// System prefix (shared)
let systemPrefix = 'nisystem'

// Stale data detection
const dataIsStale = computed(() => {
  if (!connected.value) return true
  if (lastMessageTime.value === 0) return false
  return Date.now() - lastMessageTime.value > STALE_DATA_THRESHOLD_MS
})

// Watchdog state (shared)
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

// Multi-node support (shared)
const knownNodes = ref<Map<string, NodeInfo>>(new Map())
const activeNodeId = ref<string | null>(null)  // Currently focused node (null = all nodes)

// Per-node status map (full SystemStatus per node, not just NodeInfo)
const nodeStatuses = ref<Map<string, SystemStatus>>(new Map())

// H4: Per-node acquiring state to prevent race conditions
// isAcquiring is true if ANY node is acquiring, preventing flip-flop when
// multiple nodes publish status concurrently
const nodeAcquiringStates = ref<Map<string, boolean>>(new Map())
const isAnyNodeAcquiring = computed(() => {
  for (const acquiring of nodeAcquiringStates.value.values()) {
    if (acquiring) return true
  }
  return false
})

// Node staleness check — marks nodes offline when no message received for 15s
let _nodeStalenessInterval: ReturnType<typeof setInterval> | null = null
if (!_nodeStalenessInterval) {
  _nodeStalenessInterval = setInterval(() => {
    const now = Date.now()
    for (const [nodeId, node] of knownNodes.value) {
      if (node.status === 'online' && (now - node.lastSeen) > NODE_OFFLINE_THRESHOLD_MS) {
        knownNodes.value.set(nodeId, { ...node, status: 'offline' })
      }
    }
  }, 5000)
}

// cRIO config version tracking for sync indicator
// expected: hash sent with last push, reported: hash cRIO reports in status, local: hash of current dashboard config
const crioConfigVersions = ref<Map<string, { expected: string; reported: string; local: string }>>(new Map())

// Callbacks (shared)
const dataCallbacks: ((data: Record<string, number>) => void)[] = []
const statusCallbacks: ((status: SystemStatus) => void)[] = []
const discoveryCallbacks: ((result: DiscoveryCallbackPayload) => void)[] = []
const configUpdateCallbacks: ((result: ConfigUpdateCallbackPayload) => void)[] = []
const recordingCallbacks: ((result: RecordingCallbackPayload) => void)[] = []
const alarmCallbacks: ((alarm: AlarmCallbackPayload, event: 'triggered' | 'updated' | 'cleared') => void)[] = []
const systemUpdateCallbacks: ((result: SystemUpdateCallbackPayload) => void)[] = []
const logStreamCallbacks: ((entries: any[]) => void)[] = []
const logQueryCallbacks: ((result: { success: boolean; entries?: any[]; error?: string }) => void)[] = []
const recordingReadCallbacks: ((result: any) => void)[] = []

// Generic topic subscriptions (shared) - payload is intentionally `unknown` since topics vary
// Second arg (topic) is optional for backwards compatibility
const topicCallbacks: Map<string, ((payload: unknown, topic?: string) => void)[]> = new Map()

/**
 * Check if a topic matches an MQTT-style pattern with wildcards
 * Supports: + (single level wildcard), # (multi-level wildcard)
 * Examples:
 *   topicMatchesPattern('nisystem/nodes/node-001/project/loaded', 'nisystem/nodes/+/project/loaded') -> true
 *   topicMatchesPattern('nisystem/nodes/node-001/channels/TC001', 'nisystem/nodes/+/channels/#') -> true
 */
function topicMatchesPattern(topic: string, pattern: string): boolean {
  // Exact match - fast path
  if (topic === pattern) return true

  const topicParts = topic.split('/')
  const patternParts = pattern.split('/')

  let ti = 0
  let pi = 0

  while (pi < patternParts.length) {
    const pp = patternParts[pi]

    if (pp === '#') {
      // # matches everything from here to the end
      return true
    } else if (pp === '+') {
      // + matches exactly one level
      if (ti >= topicParts.length) return false
      ti++
      pi++
    } else {
      // Literal match required
      if (ti >= topicParts.length || topicParts[ti] !== pp) return false
      ti++
      pi++
    }
  }

  // Pattern fully consumed - topic must also be fully consumed
  return ti === topicParts.length
}

export function useMqtt(prefix: string = 'nisystem') {
  // Store the prefix (first caller wins)
  if (!handlersInitialized) {
    systemPrefix = prefix
  }

  // Calculate exponential backoff delay
  function getReconnectDelay(): number {
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectAttempts.value),
      RECONNECT_MAX_DELAY_MS
    )
    return delay
  }

  function connect(brokerUrl: string = 'ws://localhost:9002', username?: string, password?: string) {
    const mqttUser = username || import.meta.env.VITE_MQTT_USERNAME
    const mqttPass = password || import.meta.env.VITE_MQTT_PASSWORD

    const options: IClientOptions = {
      clientId: `nisystem-dashboard-${Math.random().toString(16).slice(2, 8)}`,
      clean: true, // Random client ID makes persistent sessions pointless; clean: false orphans sessions on the broker
      keepalive: 120, // Match mosquitto max_keepalive; tolerate browser tab throttling
      reconnectPeriod: getReconnectDelay(),
      connectTimeout: 30000,
      queueQoSZero: false,  // Don't queue QoS 0 messages while offline
    }

    // Only add auth if credentials are provided
    if (mqttUser && mqttPass) {
      options.username = mqttUser
      options.password = mqttPass
    }

    client.value = mqtt.connect(brokerUrl, options)

    client.value.on('connect', () => {
      error.value = null
      reconnectAttempts.value = 0 // Reset on successful connect
      console.log('MQTT connected')

      // Subscribe to node-prefixed topics with QoS 1 for reliable delivery
      // Uses '+' wildcard to receive from all nodes: nisystem/nodes/+/channels/#
      const nodePrefix = `${systemPrefix}/nodes/+`
      const topics = [
        `${nodePrefix}/channels/#`,
        `${nodePrefix}/status/#`,
        `${nodePrefix}/config/#`,
        `${nodePrefix}/alarms/#`,
        `${nodePrefix}/discovery/#`,
        `${nodePrefix}/recording/#`,
        `${nodePrefix}/watchdog/#`,
        `${nodePrefix}/project/#`,  // Project management topics
        `${nodePrefix}/variables/#`,  // User variables / Playground
        `${nodePrefix}/test-session/#`,  // Test session management
        `${nodePrefix}/formulas/#`,  // Formula blocks
        `${nodePrefix}/auth/#`,  // Authentication topics (login, logout, status)
        `${nodePrefix}/users/#`,  // User management (admin)
        `${nodePrefix}/audit/#`,  // Audit trail
        `${nodePrefix}/archive/#`,  // Archive management
        `${nodePrefix}/heartbeat`,  // Service heartbeat
        `${nodePrefix}/command/ack`,  // Command acknowledgments
        `${nodePrefix}/config/channel/deleted`,
        `${nodePrefix}/config/channel/bulk-create/response`,
        `${nodePrefix}/config/system/update/response`,  // System settings update response
        `${nodePrefix}/script/#`,  // Script published values and status
        `${nodePrefix}/crio/#`,  // cRIO node management
        `${nodePrefix}/gc/#`,  // GC node analysis data
        `${nodePrefix}/historian/#`,  // Historian query responses
        `${nodePrefix}/logs/#`,  // Log viewer streaming
        `${nodePrefix}/modbus/#`,  // Modbus connection status and write responses
        `${nodePrefix}/chassis/#`  // Chassis/device management responses
      ]

      topics.forEach(topic => {
        client.value?.subscribe(topic, { qos: 1 }, (err) => {
          if (err) console.error(`Subscribe error for ${topic}:`, err)
          else console.debug(`Subscribed to ${topic}`)
        })
      })

      // Mark connected AFTER subscriptions have been issued, so commands
      // sent by consumers won't be lost during the subscription window
      connected.value = true
    })

    client.value.on('reconnect', () => {
      reconnectAttempts.value++
      console.log(`MQTT reconnecting (attempt ${reconnectAttempts.value}, delay: ${getReconnectDelay()}ms)`)
    })

    client.value.on('message', (topic: string, message: Buffer) => {
      // Outer try-catch for JSON parsing - if this fails, nothing can proceed
      let payload: any
      try {
        // Update last message time for stale detection
        lastMessageTime.value = Date.now()
        payload = JSON.parse(message.toString())
      } catch (e) {
        console.error(`Error parsing MQTT message on topic ${topic}:`, e)
        return
      }

      // Parse node-prefixed topics: nisystem/nodes/{node_id}/{category}/...
      // Example: nisystem/nodes/node-001/channels/TC001
      const nodeMatch = topic.match(new RegExp(`^${systemPrefix}/nodes/([^/]+)/(.+)$`))

      if (nodeMatch) {
        const [, nodeId, restOfTopic] = nodeMatch as [string, string, string]

        // Update node registry when we receive any message from a node
        try {
          if (payload.node_id || nodeId) {
            const existingNode = knownNodes.value.get(nodeId)
            const reportedVersion = payload.config_version || existingNode?.configVersion

            // Track cRIO config versions for sync indicator
            if (nodeId.startsWith('crio') && reportedVersion) {
              const existing = crioConfigVersions.value.get(nodeId) || { expected: '', reported: '', local: '' }
              crioConfigVersions.value.set(nodeId, {
                ...existing,
                reported: reportedVersion
              })
            }

            // Calculate sync status
            const versionData = crioConfigVersions.value.get(nodeId)
            const isSynced = !versionData?.expected || versionData.expected === versionData.reported

            // Detect node type: prefer explicit payload, then existing, then prefix heuristic
            const detectedNodeType = payload.node_type
              || existingNode?.nodeType
              || (nodeId.startsWith('crio') ? 'crio' : nodeId.startsWith('opto22') ? 'opto22' : nodeId.startsWith('gc') ? 'gc' : 'daq')

            knownNodes.value.set(nodeId, {
              nodeId,
              nodeName: payload.node_name || existingNode?.nodeName || nodeId,
              status: 'online',
              lastSeen: Date.now(),
              simulationMode: payload.simulation_mode ?? existingNode?.simulationMode ?? false,
              configVersion: reportedVersion,
              expectedVersion: versionData?.expected || existingNode?.expectedVersion,
              configSynced: isSynced,
              // Enriched fields from status payloads
              nodeType: detectedNodeType,
              projectMode: payload.project_mode || existingNode?.projectMode,
              acquiring: payload.acquiring ?? existingNode?.acquiring,
              recording: payload.recording ?? existingNode?.recording,
              channelCount: payload.channel_count ?? existingNode?.channelCount,
              safetyState: payload.safety_state || existingNode?.safetyState,
            })
          }
        } catch (e) {
          console.error(`[MQTT] Error updating node registry for topic ${topic}:`, e)
        }

        // Route messages based on category - each branch has its own try-catch
        try {
          if (restOfTopic === 'channels/batch') {
            // Batched channel values from cRIO: { "chan1": {value, timestamp}, "chan2": {value, timestamp}, ... }
            handleBatchChannelValues(payload, nodeId)
          } else if (restOfTopic.startsWith('channels/')) {
            // Individual channel value: nisystem/nodes/{node}/channels/{channel_name}
            const channelName = restOfTopic.split('/').pop() || ''
            handleChannelValue(channelName, payload, nodeId)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling channel data on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'status/system') {
            handleStatus(payload, nodeId)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling status on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'config/channels') {
            handleChannelConfig(payload)
          } else if (restOfTopic === 'config/response') {
            handleConfigResponse(payload)
          } else if (restOfTopic === 'config/current') {
            handleFullConfig(payload)
          } else if (restOfTopic === 'config/channel/deleted') {
            handleChannelDeleted(payload)
          } else if (restOfTopic === 'config/channel/bulk-create/response') {
            handleBulkCreateResponse(payload)
          } else if (restOfTopic === 'config/system/update/response') {
            handleSystemUpdateResponse(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling config on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'discovery/result') {
            console.debug('[MQTT] Received discovery/result, calling handler')
            handleDiscoveryResult(payload)
          } else if (restOfTopic === 'discovery/cfp/result') {
            console.debug('[MQTT] Received CFP discovery result')
            cfpDiscoveryResult.value = payload
            isScanning.value = false
            if (scanTimeoutId) { clearTimeout(scanTimeoutId); scanTimeoutId = null }
          } else if (restOfTopic === 'discovery/channels') {
            handleDiscoveryChannels(payload)
          } else if (restOfTopic === 'discovery/crio-found') {
            handleCrioDiscovered(payload)
          } else if (restOfTopic === 'discovery/channels/response') {
            handleCrioChannelDiscovery(nodeId, payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling discovery on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic.startsWith('alarms/')) {
            handleAlarm(topic, payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling alarm on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'recording/config/current') {
            handleRecordingConfig(payload)
          } else if (restOfTopic === 'recording/list/response') {
            handleRecordingList(payload)
          } else if (restOfTopic === 'recording/read/response') {
            recordingReadCallbacks.forEach(cb => cb(payload))
          } else if (restOfTopic === 'recording/response') {
            handleRecordingResponse(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling recording on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic.startsWith('watchdog/')) {
            handleWatchdogMessage(topic, payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling watchdog on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'variables/config') {
            handleVariablesConfig(payload)
          } else if (restOfTopic === 'variables/values') {
            handleVariablesValues(payload)
          } else if (restOfTopic === 'test-session/status') {
            handleTestSessionStatus(payload)
          } else if (restOfTopic === 'formulas/config') {
            handleFormulaBlocksConfig(payload)
          } else if (restOfTopic === 'formulas/values') {
            handleFormulaBlocksValues(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling playground/variables on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'heartbeat') {
            handleHeartbeat(payload)
          } else if (restOfTopic === 'command/ack') {
            handleCommandAck(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling heartbeat/ack on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'soe/event') {
            // SOE event from backend
            soeComposable.handleSoeEvent(payload)
          } else if (restOfTopic === 'correlations/detected') {
            // Correlation detected by backend
            soeComposable.handleCorrelationDetected(payload)
          } else if (restOfTopic === 'correlation/rules/list/response') {
            // Correlation rules sync from backend
            soeComposable.handleCorrelationRulesSync(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling SOE/correlation on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'script/values') {
            // Script-published values from backend (py.* channels)
            handleScriptValues(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling script values on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'crio/response') {
            // cRIO operation response (push config, etc.)
            handleCrioResponse(payload)
          } else if (restOfTopic === 'crio/list/response') {
            // cRIO list response
            handleCrioListResponse(payload)
          }
        } catch (e) {
          console.error(`[MQTT] Error handling cRIO response on topic ${topic}:`, e)
        }

        try {
          if (restOfTopic === 'logs/stream') {
            if (Array.isArray(payload)) {
              logStreamCallbacks.forEach(cb => cb(payload))
            }
          } else if (restOfTopic === 'logs/query/response') {
            logQueryCallbacks.forEach(cb => cb(payload))
          }
        } catch (e) {
          console.error(`[MQTT] Error handling log stream on topic ${topic}:`, e)
        }
      }

      // Handle generic topic subscriptions (supports MQTT-style wildcards: + for single level)
      try {
        for (const [pattern, callbacks] of topicCallbacks.entries()) {
          if (topicMatchesPattern(topic, pattern)) {
            callbacks.forEach(cb => cb(payload, topic))
          }
        }
      } catch (e) {
        console.error(`[MQTT] Error handling generic topic subscription for ${topic}:`, e)
      }
    })

    client.value.on('error', (err) => {
      error.value = err.message
      console.error('MQTT error:', err)
    })

    client.value.on('close', () => {
      connected.value = false

      // Clear stale data on disconnect - prevents showing outdated values
      channelValues.value = {}
      systemStatus.value = null

      // H4: Clear per-node acquiring states on disconnect
      nodeAcquiringStates.value.clear()

      // Clear channel ownership tracking to prevent unbounded growth
      channelOwners.clear()

      // Clear all pending command timers to prevent orphaned handlers
      for (const [requestId, pending] of pendingCommands.entries()) {
        pending.resolve({ success: false, error: 'MQTT disconnected' })
      }
      pendingCommands.clear()
    })
  }

  function handleChannelValue(channelName: string, payload: MqttChannelValuePayload, nodeId?: string) {
    const effectiveNodeId = nodeId || payload.node_id || 'node-001'

    // Filter by active node — when a specific node is selected, ignore data from other nodes
    // This prevents cross-node contamination in the dashboard
    if (activeNodeId.value && effectiveNodeId !== activeNodeId.value) return

    // Check if THIS node is acquiring (per-node check, not global systemStatus)
    // This allows data from multiple acquiring nodes simultaneously
    const nodeInfo = knownNodes.value.get(effectiveNodeId)
    const nodeAcquiring = nodeInfo?.acquiring ?? systemStatus.value?.acquiring
    if (!nodeAcquiring) return

    // Check channel ownership - prevent value collision between nodes
    // If a channel is owned by a different node, don't overwrite it
    // (handles redundancy: same channel name from two PCs reading same hardware)
    const owner = channelOwners.get(channelName)
    if (owner && owner !== effectiveNodeId) {
      // This channel is owned by a different node, skip update
      return
    }

    // Set ownership if not already set
    if (!owner) {
      channelOwners.set(channelName, effectiveNodeId)
    }

    const config = channelConfigs.value?.[channelName] ?? undefined
    const timestamp = payload.timestamp ? new Date(payload.timestamp).getTime() : Date.now()

    // Handle NaN values - backend sends value: null with value_string for specific errors
    // value_string can be: "NaN", "Open TC", "Inf"
    // status can be: "disconnected", "open_thermocouple", "overflow"
    const isNaN = payload.value === null || payload.value_string
    const isDisconnected = payload.status === 'disconnected' || payload.quality === 'bad'
    const isOpenTC = payload.status === 'open_thermocouple'
    const isOverflow = payload.status === 'overflow'
    const value = isNaN ? NaN : (payload.value ?? NaN)

    // Only check alarms if explicitly enabled and limits are set
    // This prevents false alarms on channels without configured limits
    // Use != null to check both undefined AND null
    const hasAlarmLimits = config != null && (
      config.hihi_limit != null ||
      config.lolo_limit != null ||
      config.high_limit != null ||
      config.low_limit != null
    )
    const alarmEnabled = config?.alarm_enabled !== false && hasAlarmLimits

    channelValues.value[channelName] = {
      name: channelName,
      value,
      timestamp,
      alarm: payload.quality === 'alarm' || (alarmEnabled && config && !isNaN ? isAlarm(value, config) : false),
      warning: payload.quality === 'warning' || (alarmEnabled && config && !isNaN ? isWarning(value, config) : false),
      // Additional quality indicators
      quality: (payload.quality || 'good') as ChannelValue['quality'],
      disconnected: isDisconnected,
      // Specific error states for better UI feedback
      openThermocouple: isOpenTC,
      overflow: isOverflow,
      valueString: payload.value_string || null,  // Human-readable error: "NaN", "Open TC", "Inf"
      status: (payload.status || 'normal') as ChannelValue['status'],
      // Multi-node: store source node ID
      nodeId: effectiveNodeId,
      // SOE: Store high-precision acquisition timestamp (microseconds since epoch)
      acquisitionTsUs: payload.acquisition_ts_us
    }

    // Call data callbacks with aggregated format for compatibility
    // Use NaN for disconnected values so charts can handle gaps
    const data: Record<string, number> = { [channelName]: value }
    dataCallbacks.forEach(cb => cb(data))

    // Notify Python scripts that new scan data is available
    // This triggers any awaiting next_scan() calls
    pythonScripts.onScanData()
  }

  function handleBatchChannelValues(payload: MqttBatchChannelPayload, nodeId?: string) {
    // Handle batched channel values from cRIO nodes
    // cRIO publishes with physical channel names (e.g., "Mod5/ai0") when no config is pushed
    // Dashboard needs to map these back to TAG names using channelConfigs
    const effectiveNodeId = nodeId || 'crio-001'

    // Filter by active node — when a specific node is selected, ignore data from other nodes
    if (activeNodeId.value && effectiveNodeId !== activeNodeId.value) return

    // Check if THIS node is acquiring (per-node check, not global systemStatus)
    const nodeInfo = knownNodes.value.get(effectiveNodeId)
    const nodeAcquiring = nodeInfo?.acquiring ?? systemStatus.value?.acquiring
    if (!nodeAcquiring) return

    const aggregatedData: Record<string, number> = {}

    // Build reverse lookup: physical_channel -> TAG name
    // The cRIO sends "Mod5/ai0" but configs might have "cRIO1Mod5/ai0" or similar
    const physicalToTag: Record<string, string> = {}
    for (const [tagName, config] of Object.entries(channelConfigs.value)) {
      if (config.physical_channel) {
        // Exact match
        physicalToTag[config.physical_channel] = tagName
        // Also try with just the module part (e.g., "Mod5/ai0" from "cRIO1Mod5/ai0")
        // Extract module path pattern from the physical_channel
        // Handles: Mod5/ai0 (analog), Mod4/port0/line0 (digital), Mod3/ctr0 (counter)
        const match = config.physical_channel.match(/(Mod\d+\/.+)$/i)
        if (match && match[1]) {
          physicalToTag[match[1]] = tagName
        }
      }
    }

    for (const [physicalChannel, data] of Object.entries(payload)) {
      const timestamp = data.timestamp ? new Date(data.timestamp * 1000).getTime() : Date.now()
      let value = data.value

      // Look up TAG name from physical channel
      const tagName = physicalToTag[physicalChannel]
      if (!tagName) {
        console.warn(`[MQTT] No TAG mapping found for physical channel "${physicalChannel}" from node ${effectiveNodeId}, using physical name as fallback`)
      }
      const effectiveName = tagName || physicalChannel  // Fall back to physical name if no mapping
      const config = channelConfigs.value?.[effectiveName] ?? undefined

      // Set channel ownership - this cRIO owns these channels
      // This prevents main DAQ from overwriting values
      channelOwners.set(effectiveName, effectiveNodeId)

      // Apply scaling if configured
      if (config) {
        value = applyScaling(value, config)
      }

      // Only check alarms if explicitly enabled and limits are set
      // Use != null to check both undefined AND null
      const hasAlarmLimits = config != null && (
        config.hihi_limit != null ||
        config.lolo_limit != null ||
        config.high_limit != null ||
        config.low_limit != null
      )
      const alarmEnabled = config?.alarm_enabled !== false && hasAlarmLimits

      // Detect null/NaN/disconnected values (open TC, broken sensor, etc.)
      const isDisconnected = value === null || value === undefined ||
        (typeof value === 'number' && isNaN(value))
      const safeValue = isDisconnected ? NaN : value

      channelValues.value[effectiveName] = {
        name: effectiveName,
        value: safeValue,
        timestamp,
        alarm: !isDisconnected && alarmEnabled && config ? isAlarm(safeValue, config) : false,
        warning: !isDisconnected && alarmEnabled && config ? isWarning(safeValue, config) : false,
        quality: isDisconnected ? 'bad' as const : 'good' as const,
        disconnected: isDisconnected,
        nodeId: effectiveNodeId
      }

      aggregatedData[effectiveName] = value
    }

    // Call data callbacks with all values at once
    if (Object.keys(aggregatedData).length > 0) {
      dataCallbacks.forEach(cb => cb(aggregatedData))
    }

    // Notify Python scripts
    pythonScripts.onScanData()
  }

  /**
   * Apply scaling transformation to a raw value based on channel config.
   * Supports: linear scaling (slope/offset), 4-20mA scaling, and map scaling.
   */
  function applyScaling(rawValue: number, config: ChannelConfig): number {
    // Handle NaN/null values
    if (rawValue === null || rawValue === undefined || Number.isNaN(rawValue)) {
      return NaN
    }

    // 4-20mA scaling: Convert current (4-20mA) to engineering units
    if (config.four_twenty_scaling && config.eng_units_min !== undefined && config.eng_units_max !== undefined) {
      // Assume rawValue is in mA (4-20 range)
      const minCurrent = 4.0
      const maxCurrent = 20.0
      const normalized = (rawValue - minCurrent) / (maxCurrent - minCurrent)
      return config.eng_units_min + normalized * (config.eng_units_max - config.eng_units_min)
    }

    // Map scaling: Linear interpolation between pre-scaled and scaled ranges
    if (config.scale_type === 'map' &&
        config.pre_scaled_min !== undefined && config.pre_scaled_max !== undefined &&
        config.scaled_min !== undefined && config.scaled_max !== undefined) {
      const preRange = config.pre_scaled_max - config.pre_scaled_min
      if (preRange !== 0) {
        const normalized = (rawValue - config.pre_scaled_min) / preRange
        return config.scaled_min + normalized * (config.scaled_max - config.scaled_min)
      }
    }

    // Linear scaling: y = mx + b
    if (config.scale_slope !== undefined || config.scale_offset !== undefined) {
      const slope = config.scale_slope ?? 1.0
      const offset = config.scale_offset ?? 0.0
      return rawValue * slope + offset
    }

    // No scaling - return raw value
    return rawValue
  }

  function handleStatus(status: MqttStatusPayload, nodeId?: string) {
    // Calculate message latency for diagnostics
    const latencyMs = status.timestamp
      ? Date.now() - new Date(status.timestamp).getTime()
      : null
    console.debug('[MQTT] Status received:', {
      nodeId,
      acquiring: status.acquiring,
      recording: status.recording,
      acquisition_state: status.acquisition_state,
      latency_ms: latencyMs
    })

    // Add node info to status
    if (nodeId || status.node_id) {
      status.node_id = nodeId || status.node_id
    }

    // Store per-node status — normalize optional fields to required defaults
    const effectiveNodeId = nodeId || status.node_id || 'node-001'
    const normalizedStatus = {
      ...status,
      status: status.status ?? 'online',
      timestamp: status.timestamp ?? new Date().toISOString(),
      simulation_mode: status.simulation_mode ?? false,
      acquiring: status.acquiring ?? false,
      recording: status.recording ?? false,
    } as SystemStatus
    nodeStatuses.value.set(effectiveNodeId, normalizedStatus)

    // H4: Track per-node acquiring state to prevent race conditions
    nodeAcquiringStates.value.set(effectiveNodeId, normalizedStatus.acquiring ?? false)

    // Update global systemStatus from the active node, or from the default DAQ node
    const targetNodeId = activeNodeId.value || 'node-001'
    if (effectiveNodeId === targetNodeId) {
      // H4: Merge acquiring state — system is acquiring if ANY node is acquiring.
      // This prevents race conditions where concurrent node status updates
      // cause isAcquiring to flip-flop in the dashboard store.
      const mergedStatus: SystemStatus = {
        ...normalizedStatus,
        acquiring: isAnyNodeAcquiring.value
      }
      systemStatus.value = mergedStatus
      statusCallbacks.forEach(cb => cb(mergedStatus))
    }
  }

  function handleScriptValues(payload: MqttScriptValuesPayload) {
    // Handle script-published values from backend (py.* channels)
    // Payload format: { "DrawNumber": 1, "DrawTarget": 10.0, "_timestamp": 1234567890.123 }
    const timestamp = payload._timestamp ? payload._timestamp * 1000 : Date.now()

    Object.entries(payload).forEach(([name, value]) => {
      if (name === '_timestamp') return  // Skip metadata

      // Store as py.{name} channel value so widgets can bind to it
      const channelName = `py.${name}`
      channelValues.value[channelName] = {
        name: channelName,
        value: typeof value === 'number' ? value : 0,
        timestamp,
        alarm: false,
        warning: false,
        quality: 'good',
        disconnected: false
      }
    })

    // Notify data callbacks
    const numericValues: Record<string, number> = {}
    Object.entries(payload).forEach(([name, value]) => {
      if (name !== '_timestamp' && typeof value === 'number') {
        numericValues[`py.${name}`] = value
      }
    })
    if (Object.keys(numericValues).length > 0) {
      dataCallbacks.forEach(cb => cb(numericValues))
    }
  }

  function handleChannelConfig(payload: MqttChannelConfigPayload) {
    // Transform backend format to frontend format
    const configs: Record<string, ChannelConfig> = {}

    if (payload.channels) {
      Object.entries(payload.channels).forEach(([name, ch]) => {
        configs[name] = {
          name: ch.name || name,  // TAG is the only identifier
          physical_channel: ch.physical_channel || '',  // NI-DAQmx address (e.g., cDAQ1Mod1/ai0)
          // display_name removed - use name (TAG) everywhere
          channel_type: (ch.channel_type || ch.type) as ChannelType,
          unit: ch.units || '',
          group: ch.group || ch.module || 'Ungrouped',
          description: ch.description,  // Description is for tooltips/docs
          visible: ch.visible !== false, // Default to true if not specified
          // Legacy limits (backward compatibility)
          low_limit: ch.low_limit,
          high_limit: ch.high_limit,
          low_warning: ch.low_warning,
          high_warning: ch.high_warning,
          // ISA-18.2 Alarm Configuration
          alarm_enabled: ch.alarm_enabled,
          hihi_limit: ch.hihi_limit,
          hi_limit: ch.hi_limit,
          lo_limit: ch.lo_limit,
          lolo_limit: ch.lolo_limit,
          alarm_priority: ch.alarm_priority,
          alarm_deadband: ch.alarm_deadband,
          alarm_delay_sec: ch.alarm_delay_sec,
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
          cjc_value: ch.cjc_value,
          // RTD-specific
          rtd_type: ch.rtd_type,
          rtd_wiring: ch.rtd_wiring,
          rtd_current: ch.rtd_current,
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
          // Multi-node / cRIO support
          // Backend sends: source_node_id, is_crio, hardware_source, hardware_source_display
          // Frontend type expects: node_id, source_type, chassis_name
          source_type: ch.is_crio ? 'crio' : (ch.is_local_daq ? 'cdaq' : (ch.source_type || 'local')),
          node_id: ch.source_node_id || ch.node_id,
          chassis_name: ch.hardware_source_display || ch.chassis_name || '',
        }
      })
    }

    channelConfigs.value = configs
    console.debug('Channel configs loaded:', Object.keys(configs).length)
  }

  function handleAlarm(topic: string, payload: MqttAlarmPayload) {
    // Parse topic: nisystem/alarms/active/{alarm_id}
    const topicParts = topic.split('/')
    const alarmId = topicParts[topicParts.length - 1] ?? ''

    // Check if this is a cleared alarm
    if (payload.active === false || payload.state === 'cleared') {
      console.debug('ALARM CLEARED:', alarmId)
      const clearedAlarm: AlarmCallbackPayload = {
        id: alarmId,
        alarm_id: payload.alarm_id || alarmId,
        channel: payload.channel || '',
        name: payload.name || payload.channel || alarmId,
        severity: (payload.severity || 'medium').toLowerCase(),
        state: 'cleared',
        value: payload.triggered_value ?? payload.current_value ?? 0,
        triggered_at: payload.triggered_at || new Date().toISOString(),
        sequence_number: payload.sequence_number || 0,
        is_first_out: payload.is_first_out || false,
        message: payload.message || ''
      }
      alarmCallbacks.forEach(cb => {
        try {
          cb(clearedAlarm, 'cleared')
        } catch (e) {
          console.warn('[MQTT] Error in alarm callback (cleared):', e)
        }
      })
      return
    }

    // Normalize backend alarm format to frontend format
    const alarm: AlarmCallbackPayload = {
      id: alarmId,
      alarm_id: payload.alarm_id || alarmId,
      channel: payload.channel || '',
      name: payload.name || payload.channel || alarmId,
      severity: (payload.severity || 'medium').toLowerCase(),
      state: payload.state || 'active',
      threshold_type: payload.threshold_type,
      threshold: payload.threshold_value,
      value: payload.triggered_value ?? payload.current_value ?? 0,
      current_value: payload.current_value,
      triggered_at: payload.triggered_at || new Date().toISOString(),
      acknowledged_at: payload.acknowledged_at,
      acknowledged_by: payload.acknowledged_by,
      cleared_at: payload.cleared_at,
      sequence_number: payload.sequence_number || 0,
      is_first_out: payload.is_first_out || false,
      shelved_at: payload.shelved_at,
      shelved_by: payload.shelved_by,
      shelve_expires_at: payload.shelve_expires_at,
      shelve_reason: payload.shelve_reason,
      message: payload.message || '',
      duration_seconds: payload.duration_seconds
    }

    // Determine event type
    const eventType = payload.acknowledged_at && !payload.cleared_at
      ? 'updated'
      : 'triggered'

    console.warn('ALARM:', eventType.toUpperCase(), alarm.name, '-', alarm.message)
    alarmCallbacks.forEach(cb => {
      try {
        cb(alarm, eventType)
      } catch (e) {
        console.warn('[MQTT] Error in alarm callback:', e)
      }
    })
  }

  function handleDiscoveryResult(payload: MqttDiscoveryResultPayload) {
    // Clear timeout since we got a response
    if (scanTimeoutId) {
      clearTimeout(scanTimeoutId)
      scanTimeoutId = null
    }
    // Normalize to DiscoveryCallbackPayload — backend omits `success` on success
    const result = {
      success: true,
      total_channels: payload.total_channels ?? 0,
      ...payload
    } as DiscoveryCallbackPayload
    discoveryResult.value = result
    isScanning.value = false
    console.debug('[MQTT] handleDiscoveryResult - chassis count:', result.chassis?.length, 'total channels:', result.total_channels)
    console.debug('[MQTT] discoveryResult.value now set, callbacks:', discoveryCallbacks.length)
    discoveryCallbacks.forEach(cb => cb(result))
  }

  function handleDiscoveryChannels(payload: { channels?: unknown[] }) {
    discoveryChannels.value = payload.channels || []
    console.debug('Discovery channels:', discoveryChannels.value.length)
  }

  function handleCrioDiscovered(payload: MqttCrioDiscoveredPayload) {
    // A new cRIO node was discovered - automatically refresh discovery
    console.debug('[MQTT] New cRIO node discovered:', payload.node_id, '- auto-refreshing discovery')
    // Small delay to ensure cRIO is fully registered before re-scanning
    // Store the timeout so cancelScan() can clear it
    if (crioRescanTimeoutId) {
      clearTimeout(crioRescanTimeoutId)
    }
    crioRescanTimeoutId = setTimeout(() => {
      crioRescanTimeoutId = null
      if (!isScanning.value) {
        console.debug('[MQTT] Auto-triggering discovery scan for new cRIO')
        scanDevices()
      }
    }, 500)
  }

  function handleCrioChannelDiscovery(nodeId: string, payload: MqttCrioChannelDiscoveryPayload) {
    // Handle channel discovery response from a specific cRIO node
    const effectiveNodeId = payload.node_id || nodeId
    console.debug(`[MQTT] Received cRIO channel discovery from ${effectiveNodeId}:`, payload.channels?.length || 0, 'channels')

    // Store the channels keyed by node ID
    crioDiscoveryChannels.value = {
      ...crioDiscoveryChannels.value,
      [effectiveNodeId]: payload.channels || []
    }
  }

  function handleConfigResponse(payload: MqttConfigResponsePayload) {
    console.debug('Config response:', payload)

    // Track expected config version when cRIO ACK is received
    if (payload.node_id && payload.config_version && payload.success) {
      const nodeId = payload.node_id
      const existing = crioConfigVersions.value.get(nodeId) || { expected: '', reported: '', local: '' }
      crioConfigVersions.value.set(nodeId, {
        ...existing,
        expected: payload.config_version,
        // Sync local to acknowledged version — handles server-initiated pushes
        // (project load, node registration) where the hash was computed server-side.
        // The next local edit will update local via the watcher, triggering out-of-sync.
        local: payload.config_version
      })

      // Update knownNodes sync status
      const nodeInfo = knownNodes.value.get(nodeId)
      if (nodeInfo) {
        knownNodes.value.set(nodeId, {
          ...nodeInfo,
          expectedVersion: payload.config_version,
          configSynced: nodeInfo.configVersion === payload.config_version
        })
      }

      console.debug(`[MQTT] cRIO ${nodeId} config confirmed, version: ${payload.config_version}`)
    }

    configUpdateCallbacks.forEach(cb => cb(payload))
  }

  function handleRecordingConfig(payload: MqttRecordingConfigPayload) {
    if (payload.config) {
      recordingConfig.value = payload.config
    }
    console.debug('Recording config received:', payload)
  }

  function handleRecordingList(payload: MqttRecordingListPayload) {
    if (payload.files) {
      recordedFiles.value = payload.files
    }
    console.debug('Recorded files list received:', payload.files?.length || 0, 'files')
  }

  function handleRecordingResponse(payload: RecordingCallbackPayload) {
    console.debug('Recording response:', payload)
    recordingCallbacks.forEach(cb => cb(payload))
  }

  function handleFullConfig(payload: Record<string, unknown>) {
    console.debug('Full config received:', payload)
    fullConfigCallbacks.forEach(cb => cb(payload))
  }

  function handleChannelDeleted(payload: MqttChannelDeletedPayload) {
    const channelName = payload.channel
    if (channelName) {
      // Remove from local configs
      if (channelConfigs.value[channelName]) {
        delete channelConfigs.value[channelName]
      }
      if (channelValues.value[channelName]) {
        delete channelValues.value[channelName]
      }
      console.debug('Channel deleted:', channelName)
      channelDeletedCallbacks.forEach(cb => cb(channelName))
    }
  }

  function handleBulkCreateResponse(payload: MqttBulkCreatePayload) {
    console.debug('Bulk create response:', payload)
    if (payload.created && payload.created.length > 0) {
      channelCreatedCallbacks.forEach(cb => cb(payload.created!))
    }
    configUpdateCallbacks.forEach(cb => cb({ success: true, ...payload } as ConfigUpdateCallbackPayload))
  }

  function handleSystemUpdateResponse(payload: SystemUpdateCallbackPayload) {
    console.debug('System update response:', payload)
    systemUpdateCallbacks.forEach(cb => cb(payload))
  }

  function handleWatchdogMessage(topic: string, payload: MqttWatchdogPayload) {
    const subtopic = topic.split('/').pop()

    if (subtopic === 'status') {
      // Update watchdog status
      watchdogStatus.value = {
        status: (payload.status || 'unknown') as 'online' | 'offline' | 'unknown',
        daqOnline: payload.daq_online ?? false,
        failsafeTriggered: payload.failsafe_triggered ?? false,
        failsafeTriggerTime: payload.failsafe_trigger_time || null,
        lastHeartbeat: payload.last_heartbeat || null,
        timeoutSec: payload.timeout_sec ?? 10,
        timestamp: payload.timestamp || null
      }
      console.debug('Watchdog status updated:', watchdogStatus.value.status,
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

  // Wire up playground MQTT handlers - convert topics to node-prefixed
  playground.setMqttHandlers({
    publish: (topic: string, payload: any) => {
      if (client.value && connected.value) {
        // Convert nisystem/xxx to nisystem/nodes/{nodeId}/xxx
        let actualTopic = topic
        if (topic.startsWith('nisystem/') && !topic.startsWith('nisystem/nodes/')) {
          const targetNodeId = activeNodeId.value || knownNodes.value.keys().next().value || 'node-001'
          actualTopic = topic.replace('nisystem/', `nisystem/nodes/${targetNodeId}/`)
        }
        console.debug('[MQTT] Playground publish:', actualTopic, payload)
        client.value.publish(actualTopic, JSON.stringify(payload))
      } else {
        console.warn('MQTT not connected, cannot publish:', topic)
      }
    }
  })

  // ========================================================================
  // Python Scripts Integration
  // ========================================================================

  // Get Python scripts composable instance (singleton)
  const pythonScripts = usePythonScripts()

  // Wire up Python scripts MQTT handlers - convert topics to node-prefixed
  pythonScripts.setMqttHandlers({
    publish: (topic: string, payload: any) => {
      if (client.value && connected.value) {
        // Convert nisystem/xxx to nisystem/nodes/{nodeId}/xxx
        let actualTopic = topic
        if (topic.startsWith('nisystem/') && !topic.startsWith('nisystem/nodes/')) {
          const targetNodeId = activeNodeId.value || knownNodes.value.keys().next().value || 'node-001'
          actualTopic = topic.replace('nisystem/', `nisystem/nodes/${targetNodeId}/`)
        }
        console.debug('[MQTT] PythonScripts publish:', actualTopic, payload)
        client.value.publish(actualTopic, JSON.stringify(payload))
      } else {
        console.warn('MQTT not connected, cannot publish:', topic)
      }
    },
    setOutput: (channel: string, value: number | boolean) => {
      setOutput(channel, value)
    },
    getChannelValues: () => {
      // Return all current channel values as a simple Record<string, number>
      const values: Record<string, number> = {}
      for (const [name, cv] of Object.entries(channelValues.value)) {
        values[name] = cv.value
      }
      return values
    },
    getChannelTimestamps: () => {
      // Return all channel timestamps (backend acquisition time in ms)
      const timestamps: Record<string, number> = {}
      for (const [name, cv] of Object.entries(channelValues.value)) {
        timestamps[name] = cv.timestamp
      }
      return timestamps
    },
    getChannelUnits: () => {
      // Return all channel units
      const units: Record<string, string> = {}
      for (const [name, cfg] of Object.entries(channelConfigs.value)) {
        units[name] = cfg.unit || ''
      }
      return units
    },
    getSessionActive: () => {
      // Session is active if system status shows acquiring
      return systemStatus.value?.acquiring || systemStatus.value?.acquisition_state === 'running'
    },
    getSessionElapsed: () => {
      // Return elapsed time if available from system status
      return systemStatus.value?.recording_duration_seconds ?? 0
    },
    sendScriptValues: (values: Record<string, number>) => {
      sendScriptValues(values)
    },
    // Session/Acquisition control - allow Python scripts to control DAQ
    startAcquisition: () => {
      console.debug('[Python Script] Starting acquisition')
      startAcquisition()
    },
    stopAcquisition: () => {
      console.debug('[Python Script] Stopping acquisition')
      stopAcquisition()
    },
    startRecording: (filename?: string) => {
      console.debug('[Python Script] Starting recording', filename ? `(${filename})` : '')
      startRecording(filename)
    },
    stopRecording: () => {
      console.debug('[Python Script] Stopping recording')
      stopRecording()
    },
    isRecording: () => {
      return systemStatus.value?.recording ?? false
    }
  })

  // ========================================================================
  // SOE & Event Correlation Integration
  // ========================================================================

  // Get SOE composable instance (singleton)
  const soeComposable = useSOE()

  // Wire up SOE MQTT publish handler
  soeComposable.setMqttPublish((topic: string, payload: any) => {
    if (client.value && connected.value) {
      // Use active node or first known node or default
      const nodeId = activeNodeId.value || knownNodes.value.keys().next().value || 'node-001'
      client.value.publish(`${systemPrefix}/nodes/${nodeId}/${topic}`, JSON.stringify(payload))
    } else {
      console.warn('MQTT not connected, cannot publish:', topic)
    }
  })

  // Initialize SOE (requests rules from backend)
  soeComposable.initialize()

  // ========================================================================
  // Python Script Lifecycle - Watch for state changes
  // ========================================================================

  // Track previous state for edge detection
  let previousAcquisitionState: boolean = false

  // Watch for acquisition state changes to trigger Python scripts
  watch(
    () => systemStatus.value?.acquiring,
    (isAcquiring, wasAcquiring) => {

      // Acquisition started
      if (isAcquiring && !wasAcquiring) {
        console.debug('[Python Scripts] Acquisition started - triggering onAcquisitionStart')
        pythonScripts.onAcquisitionStart()
      }

      // Acquisition stopped
      if (!isAcquiring && wasAcquiring) {
        console.debug('[Python Scripts] Acquisition stopped - triggering onAcquisitionStop')
        pythonScripts.onAcquisitionStop()
      }
    }
  )

  // Watch for test session state changes to trigger Python scripts
  watch(
    () => playground.testSession.value.active,
    (isActive, wasActive) => {
      // Session started
      if (isActive && !wasActive) {
        console.debug('[Python Scripts] Test session started - triggering onSessionStart')
        pythonScripts.onSessionStart()
      }

      // Session stopped
      if (!isActive && wasActive) {
        console.debug('[Python Scripts] Test session ended - triggering onSessionEnd')
        pythonScripts.onSessionEnd()

        // Clear script-published channels (py.*) when session stops
        // This prevents stale values from being displayed after scripts stop running
        const pyChannels = Object.keys(channelValues.value).filter(name => name.startsWith('py.'))
        if (pyChannels.length > 0) {
          console.debug(`[Python Scripts] Clearing ${pyChannels.length} script-published channels:`, pyChannels)
          for (const name of pyChannels) {
            delete channelValues.value[name]
          }
        }
      }
    }
  )

  function handleVariablesConfig(payload: any) {
    // console.debug('MQTT: Received variables config:', payload)
    playground.handleVariablesConfig(payload)
  }

  function handleVariablesValues(payload: any) {
    // Muted - floods console during debug
    playground.handleVariablesValues(payload)
  }

  function handleTestSessionStatus(payload: any) {
    // Muted - too noisy, floods console
    playground.handleTestSessionStatus(payload)
  }

  function handleFormulaBlocksConfig(payload: any) {
    // Muted - floods console during debug
    playground.handleFormulaBlocksConfig(payload)
  }

  function handleFormulaBlocksValues(payload: any) {
    // Muted - floods console during debug
    playground.handleFormulaBlocksValues(payload)
  }

  function handleHeartbeat(payload: MqttHeartbeatPayload) {
    lastHeartbeat.value = payload
    lastHeartbeatTime.value = Date.now()
  }

  function handleCommandAck(payload: MqttCommandAckPayload) {
    if (!payload || typeof payload !== 'object') {
      console.warn('[MQTT] Command ack received with invalid payload:', payload)
      return
    }
    if (payload.request_id === undefined && payload.success === undefined) {
      console.warn('[MQTT] Command ack missing expected fields (request_id, success):', payload)
      return
    }
    const { command, request_id, success, error: errorMsg } = payload
    console.debug('[MQTT] Command ack received:', { command, success, request_id })

    // Optimistic UI update for acquire commands - faster than waiting for full status
    if (success && command && systemStatus.value) {
      if (command === 'acquire/start') {
        console.debug('[MQTT] Optimistic update: acquiring=true')
        systemStatus.value = { ...systemStatus.value, acquiring: true, acquisition_state: 'running' }
        statusCallbacks.forEach(cb => cb(systemStatus.value!))
      } else if (command === 'acquire/stop') {
        console.debug('[MQTT] Optimistic update: acquiring=false')
        systemStatus.value = { ...systemStatus.value, acquiring: false, acquisition_state: 'stopped' }
        statusCallbacks.forEach(cb => cb(systemStatus.value!))
      }
    }

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
    const nodeId = activeNodeId.value || 'node-001'
    const topic = `${systemPrefix}/nodes/${nodeId}/${command}`
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
    // Check ISA-18.2 alarm_enabled flag first
    if (config.alarm_enabled === false) return false

    // ISA-18.2 critical limits (HiHi/LoLo)
    // Use != null to check both undefined AND null
    if (config.hihi_limit != null && value >= config.hihi_limit) return true
    if (config.lolo_limit != null && value <= config.lolo_limit) return true

    // Legacy limits (backward compatibility)
    if (config.low_limit != null && value < config.low_limit) return true
    if (config.high_limit != null && value > config.high_limit) return true
    return false
  }

  function isWarning(value: number, config: ChannelConfig): boolean {
    // Check ISA-18.2 alarm_enabled flag first
    if (config.alarm_enabled === false) return false

    // ISA-18.2 warning limits (Hi/Lo)
    // Use != null to check both undefined AND null
    if (config.hi_limit != null && value >= config.hi_limit) return true
    if (config.lo_limit != null && value <= config.lo_limit) return true

    // Legacy limits (backward compatibility)
    if (config.low_warning != null && value < config.low_warning) return true
    if (config.high_warning != null && value > config.high_warning) return true
    return false
  }

  // Commands - using backend's node-prefixed topic structure
  function sendSystemCommand(command: string, payload?: any) {
    // Use sendNodeCommand to ensure correct node-prefixed topic
    // Backend subscribes to: nisystem/nodes/{node_id}/system/{command}
    sendNodeCommand(`system/${command}`, payload)
  }

  function sendCommand(command: string, payload?: any) {
    // Route through sendNodeCommand for correct node-prefixed topic
    // Backend subscribes to: nisystem/nodes/{node_id}/{command}
    sendNodeCommand(command, payload)
  }

  /**
   * Send a command to the DAQ service or a specific node.
   * Uses node-prefixed topic: nisystem/nodes/{node_id}/{command}
   *
   * Default: Goes to the main DAQ service (node-001)
   * Pass nodeId to target a specific remote node (e.g., cRIO)
   */
  function sendNodeCommand(command: string, payload?: any, nodeId: string = activeNodeId.value || 'node-001') {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    const topic = `${systemPrefix}/nodes/${nodeId}/${command}`
    const message = payload !== undefined ? JSON.stringify(payload) : '{}'

    console.debug('[MQTT] sendNodeCommand:', topic, message)
    client.value.publish(topic, message)
  }

  /**
   * Send a command to a remote node (cRIO, etc).
   * Uses the active node or first known remote node.
   * For explicit node targeting, use sendNodeCommand with nodeId.
   */
  function sendRemoteNodeCommand(command: string, payload?: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    const targetNodeId = activeNodeId.value || knownNodes.value.keys().next().value
    if (!targetNodeId || targetNodeId === 'node-001') {
      console.warn('No remote node available for command:', command)
      return
    }

    const topic = `${systemPrefix}/nodes/${targetNodeId}/${command}`
    const message = payload !== undefined ? JSON.stringify(payload) : '{}'

    console.debug('[MQTT] sendRemoteNodeCommand:', topic, message)
    client.value.publish(topic, message)
  }

  // Alias for backwards compatibility
  const sendLocalCommand = sendNodeCommand

  /**
   * Subscribe to a specific topic with a callback
   * Returns an unsubscribe function
   */
  function subscribe<T = unknown>(topic: string, callback: (payload: T, topic?: string) => void): () => void {
    if (!topicCallbacks.has(topic)) {
      topicCallbacks.set(topic, [])
    }
    topicCallbacks.get(topic)!.push(callback as (payload: unknown, topic?: string) => void)

    // Return unsubscribe function
    return () => {
      const callbacks = topicCallbacks.get(topic)
      if (callbacks) {
        const idx = callbacks.indexOf(callback as (payload: unknown, topic?: string) => void)
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
    console.debug('[MQTT] startAcquisition called, connected:', connected.value)
    sendSystemCommand('acquire/start')
  }

  function stopAcquisition() {
    console.debug('[MQTT] stopAcquisition called, connected:', connected.value)
    sendSystemCommand('acquire/stop')
  }

  function startRecording(filename?: string) {
    console.debug('[MQTT] startRecording called, connected:', connected.value)
    sendSystemCommand('recording/start', filename ? { filename } : undefined)
  }

  function stopRecording() {
    console.debug('[MQTT] stopRecording called, connected:', connected.value)
    sendSystemCommand('recording/stop')
  }

  function enableScheduler() {
    sendLocalCommand('schedule/enable')
  }

  function disableScheduler() {
    sendLocalCommand('schedule/disable')
  }

  function loadConfig(configName: string) {
    sendLocalCommand('config/load', { config: configName })
  }

  function saveConfig(configName: string) {
    sendLocalCommand('config/save', { config: configName })
  }

  function setOutput(channelName: string, value: number | boolean) {
    // Output commands go through DAQ service for safety checks (interlocks, session lockout)
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    // Defense-in-depth validation (backend is authority, but catch obvious errors early)
    const config = channelConfigs.value[channelName]
    if (config && typeof value === 'number') {
      if (!Number.isFinite(value)) {
        console.error(`[MQTT] setOutput rejected: non-finite value for ${channelName}`)
        return
      }
      if (config.channel_type === 'digital_output' && value !== 0 && value !== 1) {
        console.error(`[MQTT] setOutput rejected: digital channel ${channelName} requires 0 or 1, got ${value}`)
        return
      }
      if (config.high_limit != null && value > config.high_limit) {
        console.warn(`[MQTT] setOutput: ${channelName} value ${value} exceeds high_limit ${config.high_limit}`)
      }
      if (config.low_limit != null && value < config.low_limit) {
        console.warn(`[MQTT] setOutput: ${channelName} value ${value} below low_limit ${config.low_limit}`)
      }
    }

    // Rate limiting: coalesce rapid changes, always send latest value
    const now = Date.now()
    const lastSend = lastOutputSendTime.get(channelName) || 0

    // Clear any pending send for this channel (superseded by new value)
    const pending = pendingOutputTimers.get(channelName)
    if (pending) clearTimeout(pending)

    if (now - lastSend >= OUTPUT_RATE_LIMIT_MS) {
      // Enough time passed, send immediately
      lastOutputSendTime.set(channelName, now)
      sendNodeCommand(`commands/${channelName}`, { value })
    } else {
      // Schedule send for end of throttle window with latest value
      const delay = OUTPUT_RATE_LIMIT_MS - (now - lastSend)
      pendingOutputTimers.set(channelName, setTimeout(() => {
        pendingOutputTimers.delete(channelName)
        lastOutputSendTime.set(channelName, Date.now())
        sendNodeCommand(`commands/${channelName}`, { value })
      }, delay))
    }
  }

  function resetCounter(channelName: string) {
    // Reset counter channel to zero
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendNodeCommand('channel/reset', { channel: channelName })
  }

  /**
   * Set all outputs to safe state (DO=0, AO=0)
   * - Sends safe-state command to local DAQ service (node-001)
   * - Sends safe-state command to all known remote nodes (cRIO)
   */
  function setAllOutputsSafe(reason: string = 'project_load') {
    if (!client.value || !connected.value) {
      console.warn('[MQTT] Not connected - cannot set safe state')
      return
    }
    if (!userAuthenticated.value) {
      console.debug('[MQTT] Not authenticated - skipping safe state command')
      return
    }

    console.debug(`[MQTT] Setting ALL outputs to safe state - reason: ${reason}`)

    // Send to local DAQ service
    sendNodeCommand('system/safe-state', { reason }, 'node-001')

    // Send to all known remote nodes (cRIO)
    for (const nodeId of knownNodes.value.keys()) {
      if (nodeId !== 'node-001') {
        console.debug(`[MQTT] Sending safe-state to remote node: ${nodeId}`)
        sendNodeCommand('system/safe-state', { reason }, nodeId)
      }
    }
  }

  /** Set auth state (called by useAuth to avoid circular imports) */
  function setUserAuthenticated(isAuth: boolean) {
    userAuthenticated.value = isAuth
  }

  // Discovery functions
  // mode: 'cdaq' | 'crio' | 'opto22' | 'cfp' | 'all' - limits which device types to discover
  // params: optional extra parameters (e.g., CFP connection details for slot probing)
  function scanDevices(mode: 'cdaq' | 'crio' | 'opto22' | 'cfp' | 'all' = 'all', params?: Record<string, any>) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    // Clear any existing timeout
    if (scanTimeoutId) {
      clearTimeout(scanTimeoutId)
    }

    isScanning.value = true
    if (mode === 'cfp') {
      cfpDiscoveryResult.value = null
    } else {
      discoveryResult.value = null
      discoveryChannels.value = []
    }
    // Discovery scan is always handled by local DAQ service
    // Pass mode and any extra params (e.g., CFP ip_address, port, slave_id)
    sendLocalCommand('discovery/scan', { mode, ...params })

    // Set timeout to automatically reset scanning state if no response
    scanTimeoutId = setTimeout(() => {
      if (isScanning.value) {
        console.warn('Discovery scan timed out after', SCAN_TIMEOUT_MS / 1000, 'seconds')
        isScanning.value = false
        scanTimeoutId = null
      }
    }, SCAN_TIMEOUT_MS)
  }

  function cancelScan() {
    // Cancel any pending scan and reset state
    if (scanTimeoutId) {
      clearTimeout(scanTimeoutId)
      scanTimeoutId = null
    }
    // Also cancel any pending cRIO auto-rescan
    if (crioRescanTimeoutId) {
      clearTimeout(crioRescanTimeoutId)
      crioRescanTimeoutId = null
    }
    isScanning.value = false
    console.debug('Discovery scan cancelled')
  }

  function requestCrioChannelDiscovery(nodeId: string) {
    // Request available channels from a specific cRIO node
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }

    console.debug(`[MQTT] Requesting channel discovery from cRIO: ${nodeId}`)
    const topic = `${systemPrefix}/nodes/${nodeId}/discovery/channels`
    client.value.publish(topic, JSON.stringify({}))
  }

  function getCrioAvailableChannels(nodeId: string): any[] {
    // Get cached available channels for a cRIO node
    return crioDiscoveryChannels.value[nodeId] || []
  }

  function onDiscovery(callback: (result: DiscoveryCallbackPayload) => void): () => void {
    discoveryCallbacks.push(callback)
    return () => {
      const idx = discoveryCallbacks.indexOf(callback)
      if (idx > -1) discoveryCallbacks.splice(idx, 1)
    }
  }

  // Config update functions - always go to local DAQ service
  function updateChannelConfig(channelName: string, config: any) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = {
      channel: channelName,
      config: config
    }
    sendLocalCommand('config/channel/update', payload)
    console.debug('Channel config update sent:', channelName)
  }

  function saveSystemConfig(configName?: string) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = configName ? { config: configName } : {}
    sendLocalCommand('config/save', payload)
    console.debug('Config save requested')
  }

  function onConfigUpdate(callback: (result: ConfigUpdateCallbackPayload) => void): () => void {
    configUpdateCallbacks.push(callback)
    return () => {
      const idx = configUpdateCallbacks.indexOf(callback)
      if (idx > -1) configUpdateCallbacks.splice(idx, 1)
    }
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
    sendLocalCommand('config/channel/create', payload)
    console.debug('Channel create sent:', name)
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
    sendLocalCommand('config/channel/delete', payload)
    console.debug('Channel delete sent:', name)
  }

  function bulkCreateChannels(channels: any[]) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    const payload = { channels }
    sendLocalCommand('config/channel/bulk-create', payload)
    console.debug('Bulk create sent:', channels.length, 'channels')
  }

  function onChannelDeleted(callback: (channelName: string) => void): () => void {
    channelDeletedCallbacks.push(callback)
    return () => {
      const idx = channelDeletedCallbacks.indexOf(callback)
      if (idx > -1) channelDeletedCallbacks.splice(idx, 1)
    }
  }

  function onChannelCreated(callback: (channels: string[]) => void): () => void {
    channelCreatedCallbacks.push(callback)
    return () => {
      const idx = channelCreatedCallbacks.indexOf(callback)
      if (idx > -1) channelCreatedCallbacks.splice(idx, 1)
    }
  }

  function onConfigCurrent(callback: (config: Record<string, unknown>) => void): () => void {
    fullConfigCallbacks.push(callback)
    // Return unsubscribe function
    return () => {
      const index = fullConfigCallbacks.indexOf(callback)
      if (index > -1) {
        fullConfigCallbacks.splice(index, 1)
      }
    }
  }

  // Recording management functions - always go to local DAQ service
  function updateRecordingConfig(config: Partial<BackendRecordingConfig>) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/config', config)
    console.debug('Recording config update sent')
  }

  function getRecordingConfig() {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/config/get', {})
  }

  function listRecordedFiles() {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/list', {})
  }

  function deleteRecordedFile(filename: string) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/delete', { filename })
  }

  function readRecordingFile(filename: string, options?: { decimation?: number; max_samples?: number }) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/read', {
      filename,
      decimation: options?.decimation ?? 1,
      max_samples: options?.max_samples ?? 500000,
    })
  }

  function onRecordingRead(callback: (result: any) => void): () => void {
    recordingReadCallbacks.push(callback)
    return () => {
      const idx = recordingReadCallbacks.indexOf(callback)
      if (idx > -1) recordingReadCallbacks.splice(idx, 1)
    }
  }

  function sendScriptValues(values: Record<string, number>) {
    if (!client.value || !connected.value) {
      return
    }
    sendLocalCommand('recording/script-values', { values })
  }

  function testDbConnection(config: { host: string, port: number, dbname: string, user: string, password: string }) {
    if (!client.value || !connected.value) {
      console.error('MQTT not connected')
      return
    }
    sendLocalCommand('recording/db-test', config)
  }

  function onRecordingResponse(callback: (result: RecordingCallbackPayload) => void): () => void {
    recordingCallbacks.push(callback)
    return () => {
      const idx = recordingCallbacks.indexOf(callback)
      if (idx > -1) recordingCallbacks.splice(idx, 1)
    }
  }

  function onSystemUpdate(callback: (result: SystemUpdateCallbackPayload) => void): () => void {
    systemUpdateCallbacks.push(callback)
    return () => {
      const idx = systemUpdateCallbacks.indexOf(callback)
      if (idx > -1) systemUpdateCallbacks.splice(idx, 1)
    }
  }

  // =========================================================================
  // LOG VIEWER
  // =========================================================================

  function onLogStream(callback: (entries: any[]) => void): () => void {
    logStreamCallbacks.push(callback)
    return () => {
      const idx = logStreamCallbacks.indexOf(callback)
      if (idx > -1) logStreamCallbacks.splice(idx, 1)
    }
  }

  function onLogQuery(callback: (result: { success: boolean; entries?: any[]; error?: string }) => void): () => void {
    logQueryCallbacks.push(callback)
    return () => {
      const idx = logQueryCallbacks.indexOf(callback)
      if (idx > -1) logQueryCallbacks.splice(idx, 1)
    }
  }

  function queryLogs(count: number = 200, level?: string) {
    const payload: any = { count }
    if (level) payload.level = level
    sendNodeCommand('logs/query', payload)
  }

  // =========================================================================
  // CRIO NODE MANAGEMENT
  // =========================================================================

  const crioCallbacks: Array<(result: CrioCallbackPayload) => void> = []
  const crioListCallbacks: Array<(result: CrioCallbackPayload) => void> = []

  /**
   * Simple deterministic hash (djb2) for config comparison.
   * Not crypto-grade — just for detecting config drift.
   */
  function hashConfig(obj: any): string {
    const str = JSON.stringify(obj, Object.keys(obj).sort())
    let hash = 5381
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) + hash + str.charCodeAt(i)) & 0x7fffffff
    }
    return hash.toString(36)
  }

  /**
   * Update the local config hash for a cRIO node.
   * Called by ConfigurationTab when channel config changes.
   */
  function updateLocalCrioHash(nodeId: string, hash: string) {
    const existing = crioConfigVersions.value.get(nodeId) || { expected: '', reported: '', local: '' }
    crioConfigVersions.value.set(nodeId, {
      ...existing,
      local: hash
    })
  }

  /**
   * Push configuration to a cRIO node.
   * Includes a content hash as config_version so cRIO can report it back for sync detection.
   * @param nodeId - Target cRIO node ID
   * @param config - Configuration to push (channels, scripts, safe_state_outputs)
   */
  function pushCrioConfig(nodeId: string, config: {
    channels?: any[],
    scripts?: any[],
    safe_state_outputs?: string[],
    scan_rate_hz?: number,
    publish_rate_hz?: number
  }) {
    if (!client.value || !connected.value) {
      console.warn('[MQTT] Cannot push cRIO config: not connected')
      return
    }

    // Compute content hash and include as config_version
    const configHash = hashConfig(config)

    // Update local hash to match what we're pushing
    updateLocalCrioHash(nodeId, configHash)

    // cRIO push is orchestrated by the local DAQ service
    sendLocalCommand('crio/push-config', {
      node_id: nodeId,
      config_version: configHash,
      ...config
    })
  }

  /**
   * Request list of all known cRIO nodes.
   */
  function listCrioNodes() {
    if (!client.value || !connected.value) {
      console.warn('[MQTT] Cannot list cRIO nodes: not connected')
      return
    }
    sendLocalCommand('crio/list', {})
  }

  /**
   * Register callback for cRIO operation responses.
   * Returns unsubscribe function to prevent memory leaks.
   */
  function onCrioResponse(callback: (result: CrioCallbackPayload) => void): () => void {
    crioCallbacks.push(callback)
    return () => {
      const idx = crioCallbacks.indexOf(callback)
      if (idx > -1) crioCallbacks.splice(idx, 1)
    }
  }

  /**
   * Register callback for cRIO list responses.
   * Returns unsubscribe function to prevent memory leaks.
   */
  function onCrioList(callback: (result: CrioCallbackPayload) => void): () => void {
    crioListCallbacks.push(callback)
    return () => {
      const idx = crioListCallbacks.indexOf(callback)
      if (idx > -1) crioListCallbacks.splice(idx, 1)
    }
  }

  /**
   * Handle cRIO response messages.
   * Called from message handler when crio/response topic is received.
   */
  function handleCrioResponse(payload: CrioCallbackPayload) {
    crioCallbacks.forEach(cb => cb(payload))
  }

  /**
   * Handle cRIO list response messages.
   * Called from message handler when crio/list/response topic is received.
   */
  function handleCrioListResponse(payload: CrioCallbackPayload) {
    crioListCallbacks.forEach(cb => cb(payload))
  }

  // Event subscription - all functions return unsubscribe function to prevent memory leaks
  function onData(callback: (data: Record<string, number>) => void): () => void {
    dataCallbacks.push(callback)
    return () => {
      const idx = dataCallbacks.indexOf(callback)
      if (idx > -1) dataCallbacks.splice(idx, 1)
    }
  }

  function onStatus(callback: (status: SystemStatus) => void): () => void {
    statusCallbacks.push(callback)
    return () => {
      const idx = statusCallbacks.indexOf(callback)
      if (idx > -1) statusCallbacks.splice(idx, 1)
    }
  }

  function onAlarm(callback: (alarm: AlarmCallbackPayload, event: 'triggered' | 'updated' | 'cleared') => void): () => void {
    alarmCallbacks.push(callback)
    return () => {
      const idx = alarmCallbacks.indexOf(callback)
      if (idx > -1) alarmCallbacks.splice(idx, 1)
    }
  }

  function disconnect() {
    // Clear pending commands before closing (prevents orphaned timers)
    for (const [, pending] of pendingCommands.entries()) {
      pending.resolve({ success: false, error: 'MQTT disconnected' })
    }
    pendingCommands.clear()

    // H3: Clear all pending output rate-limit timers
    for (const [, timer] of pendingOutputTimers.entries()) {
      clearTimeout(timer)
    }
    pendingOutputTimers.clear()
    lastOutputSendTime.clear()

    // H3: Clear node staleness interval
    if (_nodeStalenessInterval) {
      clearInterval(_nodeStalenessInterval)
      _nodeStalenessInterval = null
    }

    // H3: Clear scan timeouts
    if (scanTimeoutId) {
      clearTimeout(scanTimeoutId)
      scanTimeoutId = null
    }
    if (crioRescanTimeoutId) {
      clearTimeout(crioRescanTimeoutId)
      crioRescanTimeoutId = null
    }

    // Clear stale data and ownership tracking
    channelValues.value = {}
    systemStatus.value = null
    channelOwners.clear()

    if (client.value) {
      client.value.end()
      client.value = null
    }
    connected.value = false
  }

  // NOTE: Removed onUnmounted hook - with singleton pattern, we don't want
  // individual components to disconnect the shared MQTT connection when they unmount.
  // The connection should persist for the lifetime of the app.

  // Computed for cRIO sync status - true means in sync, false means out of sync
  const crioSyncStatus = computed(() => {
    const result: Record<string, boolean> = {}
    for (const [nodeId, versions] of crioConfigVersions.value) {
      // Out of sync if local config hash differs from what the cRIO reports
      if (versions.local && versions.reported) {
        result[nodeId] = versions.local === versions.reported
      } else if (versions.expected && versions.reported) {
        // Fallback: compare expected (last push) vs reported
        result[nodeId] = versions.expected === versions.reported
      } else {
        // No data yet — assume in sync until we know otherwise
        result[nodeId] = true
      }
    }
    return result
  })

  // Get channel owner info for collision detection
  function getChannelOwner(channelName: string): string | null {
    return channelOwners.get(channelName) || null
  }

  // Check if a channel name would collide with another node
  function checkChannelCollision(channelName: string, excludeNode?: string): { collides: boolean, owner?: string } {
    const owner = channelOwners.get(channelName)
    if (!owner) {
      return { collides: false }
    }
    // If owner matches excludeNode, no collision (it's the same node)
    if (excludeNode && owner === excludeNode) {
      return { collides: false }
    }
    return { collides: true, owner }
  }

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
    cfpDiscoveryResult,
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
    setAllOutputsSafe,
    setUserAuthenticated,
    resetCounter,
    sendCommand,
    sendNodeCommand,
    sendLocalCommand,  // Alias for sendNodeCommand (backwards compat)
    sendRemoteNodeCommand,  // For targeting cRIO/remote nodes
    subscribe,

    // Discovery
    scanDevices,
    cancelScan,
    onDiscovery,

    // cRIO Channel Discovery
    crioDiscoveryChannels,
    requestCrioChannelDiscovery,
    getCrioAvailableChannels,

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
    readRecordingFile,
    onRecordingRead,
    sendScriptValues,
    testDbConnection,
    onRecordingResponse,
    onSystemUpdate,

    // cRIO node management
    pushCrioConfig,
    listCrioNodes,
    onCrioResponse,
    onCrioList,

    // Log viewer
    onLogStream,
    onLogQuery,
    queryLogs,

    // Events
    onData,
    onStatus,
    onAlarm,

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
    sendSystemCommandWithAck,

    // Multi-node support
    knownNodes,
    activeNodeId,
    nodeStatuses,
    setActiveNode: (nodeId: string | null) => {
      const previousNodeId = activeNodeId.value
      activeNodeId.value = nodeId

      // Clear channel values and ownership on node switch to prevent cross-node data
      if (previousNodeId !== nodeId) {
        channelValues.value = {}
        channelOwners.clear()
      }

      // When switching active node, update systemStatus from stored per-node status
      const targetId = nodeId || 'node-001'
      const cached = nodeStatuses.value.get(targetId)
      if (cached) {
        systemStatus.value = cached
        statusCallbacks.forEach(cb => cb(cached))
      }
    },
    getNodeList: () => Array.from(knownNodes.value.values()),

    // H4: Per-node acquiring state (prevents race condition)
    isAnyNodeAcquiring,
    nodeAcquiringStates,

    // cRIO sync status
    crioSyncStatus,
    crioConfigVersions,
    updateLocalCrioHash,
    hashConfig,

    // Channel collision detection (multi-node)
    getChannelOwner,
    checkChannelCollision,

    // SOE & Event Correlation
    soe: soeComposable
  }
}
