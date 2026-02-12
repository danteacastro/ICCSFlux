<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, inject } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'
import { usePlayground } from '../composables/usePlayground'
import { useAuth } from '../composables/useAuth'
import AlarmConfigModal from './AlarmConfigModal.vue'
import SafetyActionsPanel from './SafetyActionsPanel.vue'
import CorrelationRuleModal from './CorrelationRuleModal.vue'
import type {
  AlarmConfig,
  ActiveAlarm,
  Interlock,
  InterlockCondition,
  InterlockControl,
  InterlockConditionType,
  InterlockControlType,
  InterlockOperator,
  CorrelationRule,
  EventCorrelation,
  SOEEvent,
  SOEEventType
} from '../types'

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()
const playground = usePlayground()
const soe = mqtt.soe  // SOE & Correlation composable

// Permission-based edit control (injected from App.vue)
const hasEditPermission = inject<{ value: boolean }>('canEditSafety', ref(true))
const showLoginDialogFn = inject<() => void>('showLoginDialog', () => {})
const auth = useAuth()
// Operator+ can perform operational actions (ACK, shelve, reset, bypass)
const canOperate = computed(() => auth.isOperator.value)

// Check permission before allowing config edits (Supervisor+)
function requireEditPermission(): boolean {
  if (!hasEditPermission.value) {
    showLoginDialogFn()
    return false
  }
  return true
}

// Check permission before allowing operational actions (Operator+)
function requireOperatePermission(): boolean {
  if (!canOperate.value) {
    showLoginDialogFn()
    return false
  }
  return true
}

// ============================================
// Alarm Configuration State (from composable)
// ============================================

// Local writable refs that sync with composable
const alarmConfigs = ref<Record<string, AlarmConfig>>({})

// Sync from safety composable
watch(() => safety.alarmConfigs.value, (configs) => {
  // Deep clone to break readonly constraint
  alarmConfigs.value = JSON.parse(JSON.stringify(configs))
}, { immediate: true, deep: true })

// Sync back to safety composable on changes (with validation, debounced)
let alarmConfigDebounceTimer: ReturnType<typeof setTimeout> | null = null

watch(alarmConfigs, (configs) => {
  if (alarmConfigDebounceTimer) clearTimeout(alarmConfigDebounceTimer)
  alarmConfigDebounceTimer = setTimeout(() => {
    Object.entries(configs).forEach(([channel, config]) => {
      // Validate threshold order before saving
      const la = config.low_alarm
      const lw = config.low_warning
      const hw = config.high_warning
      const ha = config.high_alarm

      // Check order (only for set values)
      let valid = true
      if (la != null && lw != null && la >= lw) valid = false
      if (lw != null && hw != null && lw >= hw) valid = false
      if (hw != null && ha != null && hw >= ha) valid = false

      // Only save if valid (prevents invalid configurations from being applied)
      if (valid) {
        safety.updateAlarmConfig(channel, config)
      }
    })
  }, 500)
}, { deep: true })

// ============================================
// Active Alarms State (from composable)
// ============================================

const activeAlarms = computed(() => [...safety.activeAlarms.value])
const alarmHistory = computed(() => [...safety.alarmHistory.value])
const alarmCounts = safety.alarmCounts

// Sound for alarms
let alarmSound: HTMLAudioElement | null = null
onMounted(() => {
  // Create alarm sound (simple beep using Web Audio API fallback)
  try {
    alarmSound = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YU')
  } catch {
    // Audio not available
  }
})

// ============================================
// Alarm Checking Logic
// ============================================

// Local delay timers for alarm triggering
const delayTimers = ref<Record<string, { type: string; startTime: number }>>({})

type AlarmSeverity = 'alarm' | 'warning'

function checkThreshold(
  value: number,
  threshold: number | undefined,
  type: 'high' | 'low'
): boolean {
  if (threshold === undefined) return false

  if (type === 'high') {
    return value >= threshold
  } else {
    return value <= threshold
  }
}

function shouldClearAlarm(
  value: number,
  threshold: number,
  type: 'high' | 'low',
  deadband: number
): boolean {
  if (type === 'high') {
    return value < (threshold - deadband)
  } else {
    return value > (threshold + deadband)
  }
}

function processAlarms() {
  const now = new Date()
  const nowIso = now.toISOString()

  Object.entries(store.values).forEach(([channel, channelValue]) => {
    const config = alarmConfigs.value[channel]
    if (!config || !config.enabled) return

    const value = channelValue.value
    const channelConfig = store.channels[channel]

    // Check each threshold type
    const thresholdChecks: Array<{
      threshold: number | undefined
      type: 'high_alarm' | 'low_alarm' | 'high_warning' | 'low_warning'
      severity: AlarmSeverity
      direction: 'high' | 'low'
    }> = [
      { threshold: config.high_alarm, type: 'high_alarm', severity: 'alarm', direction: 'high' },
      { threshold: config.low_alarm, type: 'low_alarm', severity: 'alarm', direction: 'low' },
      { threshold: config.high_warning, type: 'high_warning', severity: 'warning', direction: 'high' },
      { threshold: config.low_warning, type: 'low_warning', severity: 'warning', direction: 'low' }
    ]

    thresholdChecks.forEach(check => {
      if (check.threshold === undefined) return

      const alarmKey = `${channel}:${check.type}`
      const existingAlarm = activeAlarms.value.find(
        a => a.channel === channel && a.threshold_type === check.type
      )

      const isExceeded = checkThreshold(value, check.threshold, check.direction)

      if (isExceeded && !existingAlarm) {
        // Check delay
        const delaySeconds = config.delay_seconds ?? 0
        if (delaySeconds > 0) {
          if (!delayTimers.value[alarmKey]) {
            delayTimers.value[alarmKey] = { type: check.type, startTime: Date.now() }
            return
          }
          const elapsed = (Date.now() - delayTimers.value[alarmKey].startTime) / 1000
          if (elapsed < delaySeconds) return
        }

        // Trigger new alarm
        const alarm: ActiveAlarm = {
          id: `${channel}-${check.type}-${Date.now()}`,
          channel,
          severity: check.severity,
          state: 'active',
          value,
          threshold: check.threshold,
          threshold_type: check.type,
          triggered_at: nowIso,
          duration_seconds: 0,
          message: `${channel} ${check.direction === 'high' ? 'exceeded' : 'fell below'} ${check.severity} threshold: ${value.toFixed(2)} ${channelConfig?.unit || ''} (limit: ${check.threshold})`
        }

        safety.triggerAlarm(alarm)
        delete delayTimers.value[alarmKey]

        // Play sound if enabled
        if (config.play_sound && alarmSound && check.severity === 'alarm') {
          try { alarmSound.play() } catch {}
        }

        // Start recording if enabled
        if (config.start_recording && !store.status?.recording) {
          mqtt.startRecording()
        }

      } else if (!isExceeded && existingAlarm) {
        // Check if we should clear
        const canClear = shouldClearAlarm(value, check.threshold, check.direction, config.deadband)

        if (canClear) {
          delete delayTimers.value[alarmKey]

          if (config.behavior === 'auto_clear' || existingAlarm.state === 'acknowledged') {
            // Clear the alarm
            clearAlarm(existingAlarm.id)
          }
        }
      } else if (!isExceeded) {
        // Clear delay timer if value returned to normal before delay elapsed
        delete delayTimers.value[alarmKey]
      }
    })
  })
}

// Watch for value changes
let alarmCheckInterval: number | null = null
onMounted(() => {
  alarmCheckInterval = window.setInterval(processAlarms, 1000)
})
onUnmounted(() => {
  if (alarmCheckInterval) clearInterval(alarmCheckInterval)
  if (alarmConfigDebounceTimer) clearTimeout(alarmConfigDebounceTimer)
  if (highlightTimer) clearTimeout(highlightTimer)
})

// ============================================
// Alarm Actions (delegate to composable)
// ============================================

function acknowledgeAlarm(alarmId: string) {
  if (!requireOperatePermission()) return
  safety.acknowledgeAlarm(alarmId)
}

function acknowledgeAll() {
  if (!requireOperatePermission()) return
  safety.acknowledgeAll()
}

function clearAlarm(alarmId: string) {
  safety.clearAlarm(alarmId)
}

function clearAllAlarms() {
  if (!requireOperatePermission()) return
  const count = safety.activeAlarms.value.length
  if (count > 0 && !confirm(`Clear all ${count} active alarm(s)? This cannot be undone.`)) {
    return
  }
  safety.clearAllAlarms(true)  // Add to history when manually clearing
}

function resetAlarm(alarmId: string) {
  if (!requireOperatePermission()) return
  safety.resetAlarm(alarmId)
}

function resetAllLatched() {
  if (!requireOperatePermission()) return
  safety.resetAllLatched()
}

// ============================================
// Severity Helpers
// ============================================

function getSeverityClass(severity: string): string {
  switch (severity) {
    case 'critical': return 'critical'
    case 'high':
    case 'alarm': return 'alarm'
    case 'medium': return 'medium'
    case 'low':
    case 'warning': return 'warning'
    default: return 'warning'
  }
}

function getSeverityLabel(severity: string): string {
  switch (severity) {
    case 'critical': return 'CRITICAL'
    case 'high':
    case 'alarm': return 'HIGH'
    case 'medium': return 'MEDIUM'
    case 'low':
    case 'warning': return 'LOW'
    default: return severity.toUpperCase()
  }
}

let highlightTimer: ReturnType<typeof setTimeout> | null = null

function scrollToAlarm(alarmId: string | undefined) {
  if (!alarmId) return
  const el = document.getElementById(`alarm-${alarmId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('highlight')
    if (highlightTimer) clearTimeout(highlightTimer)
    highlightTimer = setTimeout(() => {
      const target = document.getElementById(`alarm-${alarmId}`)
      if (target) target.classList.remove('highlight')
      highlightTimer = null
    }, 2000)
  }
}

// ============================================
// Shelve Modal State
// ============================================

const showShelveModal = ref(false)
const shelveTarget = ref<{ id: string; channel: string; name: string } | null>(null)
const shelveReason = ref('')
const shelveDuration = ref(3600)

const shelveDurationOptions = [
  { value: 900, label: '15 minutes' },
  { value: 1800, label: '30 minutes' },
  { value: 3600, label: '1 hour' },
  { value: 7200, label: '2 hours' },
  { value: 14400, label: '4 hours' },
  { value: 28800, label: '8 hours' }
]

function openShelveModal(alarm: { id: string; channel: string; name?: string }) {
  shelveTarget.value = {
    id: alarm.id,
    channel: alarm.channel,
    name: alarm.name || alarm.channel
  }
  shelveReason.value = ''
  shelveDuration.value = 3600
  showShelveModal.value = true
}

function confirmShelve() {
  if (!requireOperatePermission()) return
  if (!shelveTarget.value) return
  safety.shelveAlarm(shelveTarget.value.id, 'User', shelveReason.value, shelveDuration.value)
  showShelveModal.value = false
  shelveTarget.value = null
}

// ============================================
// Alarm Config Modal State
// ============================================

const showAlarmConfigModal = ref(false)
const alarmConfigChannel = ref<string | null>(null)

function openAlarmConfigModal(channel: string) {
  alarmConfigChannel.value = channel
  showAlarmConfigModal.value = true
}

function closeAlarmConfigModal() {
  showAlarmConfigModal.value = false
  alarmConfigChannel.value = null
}

function validateAlarmThresholds(config: AlarmConfig): string | null {
  // Validate that alarm thresholds are in correct order
  // Expected order: low_alarm < low_warning < high_warning < high_alarm
  const la = config.low_alarm
  const lw = config.low_warning
  const hw = config.high_warning
  const ha = config.high_alarm

  // Only validate if values are set (null/undefined values are allowed)
  const errors: string[] = []

  if (la !== null && la !== undefined && lw !== null && lw !== undefined && la >= lw) {
    errors.push('Low Alarm must be less than Low Warning')
  }
  if (lw !== null && lw !== undefined && hw !== null && hw !== undefined && lw >= hw) {
    errors.push('Low Warning must be less than High Warning')
  }
  if (hw !== null && hw !== undefined && ha !== null && ha !== undefined && hw >= ha) {
    errors.push('High Warning must be less than High Alarm')
  }

  return errors.length > 0 ? errors.join('. ') : null
}

function saveAlarmConfig(config: AlarmConfig) {
  if (!requireEditPermission()) return
  // Validate threshold order before saving
  const validationError = validateAlarmThresholds(config)
  if (validationError) {
    alert(`Invalid alarm configuration: ${validationError}`)
    return
  }
  safety.updateAlarmConfig(config.channel, config)
}

// ============================================
// Alarm History CSV Export
// ============================================

function exportAlarmHistoryCsv() {
  const headers = ['Timestamp', 'Channel', 'Event', 'Severity', 'Value', 'Threshold', 'Duration (s)', 'User', 'Message']
  const rows = filteredHistory.value.map(entry => [
    entry.triggered_at || '',
    entry.channel || '',
    entry.event_type || '',
    entry.severity || '',
    entry.value?.toString() || '',
    entry.threshold?.toString() || '',
    entry.duration_seconds?.toString() || '',
    entry.user || entry.acknowledged_by || '',
    (entry.message || '').replace(/"/g, '""')
  ])

  const csv = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
  ].join('\n')

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `alarm_history_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ============================================
// Correlation Rule Modal State
// ============================================

const showCorrelationRuleModal = ref(false)
const editingCorrelationRule = ref<CorrelationRule | null>(null)

function openNewCorrelationRuleModal() {
  if (!requireEditPermission()) return
  editingCorrelationRule.value = null
  showCorrelationRuleModal.value = true
}

function openEditCorrelationRuleModal(rule: CorrelationRule) {
  editingCorrelationRule.value = rule
  showCorrelationRuleModal.value = true
}

function closeCorrelationRuleModal() {
  showCorrelationRuleModal.value = false
  editingCorrelationRule.value = null
}

function saveCorrelationRule(ruleData: Omit<CorrelationRule, 'id'>) {
  if (!requireEditPermission()) return
  if (editingCorrelationRule.value) {
    // Update existing rule - would need to add update method to soe
    soe.removeCorrelationRule(editingCorrelationRule.value.id)
  }
  // Generate an id for the new rule
  const ruleWithId: CorrelationRule = {
    ...ruleData,
    id: `corr_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`
  }
  soe.addCorrelationRule(ruleWithId)
}

// ============================================
// Multi-Node Alarm Filtering
// ============================================

const selectedNodeFilter = ref<string>('all')

// Get available nodes from MQTT
const availableNodes = computed(() => {
  const nodes: { id: string; name: string }[] = [
    { id: 'all', name: 'All Nodes' },
    { id: 'pc', name: 'PC (local)' }
  ]

  // Add discovered cRIO nodes from MQTT
  const knownNodesList = mqtt.getNodeList()
  for (const nodeInfo of knownNodesList) {
    if (nodeInfo.nodeId !== 'pc' && nodeInfo.nodeId !== 'node-001') {
      nodes.push({
        id: nodeInfo.nodeId,
        name: nodeInfo.nodeName || nodeInfo.nodeId
      })
    }
  }

  return nodes
})

// Filtered active alarms by node
const filteredActiveAlarms = computed(() => {
  if (selectedNodeFilter.value === 'all') {
    return activeAlarms.value
  }
  return activeAlarms.value.filter(alarm => {
    const nodeId = alarm.nodeId || 'pc'
    return nodeId === selectedNodeFilter.value
  })
})

// Filtered alarm configs by node
const filteredChannelList = computed(() => {
  if (selectedNodeFilter.value === 'all') {
    return channelList.value
  }
  return channelList.value.filter(ch => {
    // Check if channel value has nodeId, or infer from channel name prefix
    const channelValue = store.values[ch.name]
    const nodeId = channelValue?.nodeId || 'pc'
    return nodeId === selectedNodeFilter.value
  })
})

// ============================================
// UI State
// ============================================

const selectedChannel = ref<string | null>(null)
const selectedAlarmConfig = computed(() => {
  if (selectedChannel.value && alarmConfigs.value[selectedChannel.value]) {
    return alarmConfigs.value[selectedChannel.value]
  }
  return null
})
const historyFilter = ref({
  channel: '',
  severity: '' as '' | 'alarm' | 'warning',
  dateRange: 'all' as 'all' | 'today' | 'week'
})

const filteredHistory = computed(() => {
  let result = [...alarmHistory.value]

  if (historyFilter.value.channel) {
    result = result.filter(h => h.channel === historyFilter.value.channel)
  }
  if (historyFilter.value.severity) {
    result = result.filter(h => h.severity === historyFilter.value.severity)
  }
  if (historyFilter.value.dateRange === 'today') {
    const today = new Date().toISOString().split('T')[0] as string
    result = result.filter(h => h.triggered_at?.startsWith(today))
  } else if (historyFilter.value.dateRange === 'week') {
    const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
    result = result.filter(h => h.triggered_at && h.triggered_at >= weekAgo)
  }

  return result
})

// System health
const systemHealth = computed(() => {
  const firstValue = Object.values(store.values)[0]
  return {
    mqtt_connected: mqtt.connected.value,
    daq_connected: mqtt.systemStatus.value?.status === 'online' || store.status?.status === 'online',
    last_data_received: firstValue?.timestamp
      ? new Date(firstValue.timestamp).toISOString()
      : undefined,
    data_timeout: mqtt.dataIsStale.value
  }
})

// Channel list for config - only include channels with valid alarm configs
const channelList = computed(() => {
  return Object.entries(store.channels)
    .filter(([name]) => alarmConfigs.value[name] !== undefined)
    .map(([name, config]) => ({
      name,  // TAG is the only identifier
      unit: config.unit,
      type: config.channel_type,
      group: config.group,
      alarmConfig: alarmConfigs.value[name]!
    }))
})

// alarmCounts comes from safety composable (already assigned above)

// Format duration
function formatDuration(seconds: number | undefined): string {
  if (seconds === undefined || seconds === null) return '--'
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

// Format timestamp
function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString()
}

function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString()
}

// Format interlock event type for display
function formatInterlockEvent(event: string): string {
  const eventLabels: Record<string, string> = {
    'created': 'Created',
    'modified': 'Modified',
    'enabled': 'Enabled',
    'disabled': 'Disabled',
    'bypassed': 'Bypassed',
    'bypass_removed': 'Bypass Removed',
    'bypass_expired': 'Bypass Expired',
    'tripped': 'TRIPPED',
    'cleared': 'Cleared',
    'demand': 'Demand',
    'proof_test': 'Proof Test'
  }
  return eventLabels[event] || event
}

// Get current value for a channel
function getCurrentValue(channel: string): string {
  const val = store.values[channel]
  if (!val) return '--'
  const config = store.channels[channel]
  return `${val.value.toFixed(2)} ${config?.unit || ''}`
}

// Config persistence is handled by the safety composable

// ============================================
// Interlock UI State
// ============================================

const activeSection = ref<'alarms' | 'interlocks' | 'correlation' | 'soe'>('alarms')

// ============================================
// SOE & Correlation UI State
// ============================================

const soeTypeFilter = ref<SOEEventType | ''>('')
const showNewRuleModal = ref(false)

// Filtered SOE events based on type filter
const filteredSoeEvents = computed(() => {
  if (!soeTypeFilter.value) {
    return soe.soeEvents.value
  }
  return soe.soeEvents.value.filter(e => e.eventType === soeTypeFilter.value)
})

// Format event type for display
function formatEventType(type: SOEEventType | string): string {
  const labels: Record<string, string> = {
    'alarm_triggered': 'Alarm',
    'alarm_cleared': 'Cleared',
    'alarm_acknowledged': 'Ack',
    'state_change': 'State',
    'digital_edge': 'Edge',
    'setpoint_change': 'Setpoint'
  }
  return labels[type] || type
}

// Format timestamp for display
function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return iso
  }
}

// Format ISO time for SOE table
function formatIsoTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3
    } as Intl.DateTimeFormatOptions)
  } catch {
    return iso
  }
}

// Get row class based on event type
function getEventRowClass(event: SOEEvent): string {
  switch (event.eventType) {
    case 'alarm_triggered': return 'row-alarm'
    case 'alarm_cleared': return 'row-cleared'
    case 'alarm_acknowledged': return 'row-ack'
    default: return ''
  }
}

// Navigate to correlation tab and highlight
function goToCorrelation(correlationId: string) {
  activeSection.value = 'correlation'
  // Could add highlighting logic here
}

// Export SOE to CSV file
function exportSoe() {
  const csv = soe.exportSoeToCsv()
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `soe_export_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
const showInterlockModal = ref(false)
const editingInterlock = ref<Interlock | null>(null)

// New interlock form state
const newInterlock = ref({
  name: '',
  description: '',
  bypassAllowed: true,
  maxBypassDuration: 0,  // 0 = unlimited
  conditionLogic: 'AND' as 'AND' | 'OR',
  silRating: undefined as 'SIL1' | 'SIL2' | 'SIL3' | 'SIL4' | undefined,
  priority: 'medium' as 'critical' | 'high' | 'medium' | 'low',
  requiresAcknowledgment: false,
  proofTestInterval: undefined as number | undefined,
  conditions: [] as InterlockCondition[],
  controls: [] as InterlockControl[]
})

// Condition types for dropdown (IEC 61511 compliant)
const conditionTypes: { value: InterlockConditionType; label: string; needsChannel: boolean; needsOperator: boolean; needsAlarm?: boolean; needsVariable?: boolean; needsExpression?: boolean }[] = [
  { value: 'mqtt_connected', label: 'MQTT Connected', needsChannel: false, needsOperator: false },
  { value: 'daq_connected', label: 'DAQ Online', needsChannel: false, needsOperator: false },
  { value: 'acquiring', label: 'System Acquiring', needsChannel: false, needsOperator: false },
  { value: 'not_recording', label: 'Not Recording', needsChannel: false, needsOperator: false },
  { value: 'no_active_alarms', label: 'No Active Alarms', needsChannel: false, needsOperator: false },
  { value: 'no_latched_alarms', label: 'No Latched Alarms', needsChannel: false, needsOperator: false },
  { value: 'channel_value', label: 'Channel Value', needsChannel: true, needsOperator: true },
  { value: 'digital_input', label: 'Digital Input', needsChannel: true, needsOperator: false },
  { value: 'alarm_active', label: 'Alarm NOT Active', needsChannel: false, needsOperator: false, needsAlarm: true },
  { value: 'alarm_state', label: 'Alarm State', needsChannel: false, needsOperator: false, needsAlarm: true },
  { value: 'variable_value', label: 'Variable Value', needsChannel: false, needsOperator: true, needsVariable: true },
  { value: 'expression', label: 'Expression', needsChannel: false, needsOperator: false, needsExpression: true }
]

// Alarm state options for alarm_state condition
const alarmStateOptions = [
  { value: 'active', label: 'Active' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'shelved', label: 'Shelved' },
  { value: 'returned', label: 'Returned (Latched)' }
]

// SIL rating options (IEC 61508)
const silRatingOptions = [
  { value: undefined, label: 'Not Rated' },
  { value: 'SIL1', label: 'SIL 1' },
  { value: 'SIL2', label: 'SIL 2' },
  { value: 'SIL3', label: 'SIL 3' },
  { value: 'SIL4', label: 'SIL 4' }
]

const controlTypes: { value: InterlockControlType; label: string; needsChannel: boolean; needsValue?: boolean; channelType?: 'do' | 'ao' }[] = [
  // BLOCKING actions
  { value: 'digital_output', label: 'Block Digital Output', needsChannel: true, channelType: 'do' },
  { value: 'analog_output', label: 'Block Analog Output', needsChannel: true, channelType: 'ao' },
  { value: 'schedule_enable', label: 'Block Schedule Enable', needsChannel: false },
  { value: 'recording_start', label: 'Block Recording Start', needsChannel: false },
  { value: 'acquisition_start', label: 'Block Acquisition Start', needsChannel: false },
  { value: 'session_start', label: 'Block Session Start', needsChannel: false },
  { value: 'script_start', label: 'Block Script Start', needsChannel: false },
  // ACTIVE actions (execute when interlock conditions FAIL)
  { value: 'set_digital_output', label: 'Set Digital Output To', needsChannel: true, needsValue: true, channelType: 'do' },
  { value: 'set_analog_output', label: 'Set Analog Output To', needsChannel: true, needsValue: true, channelType: 'ao' },
  { value: 'stop_session', label: 'Stop Session', needsChannel: false },
  { value: 'stop_acquisition', label: 'Stop Acquisition', needsChannel: false }
]

const operators: { value: InterlockOperator; label: string }[] = [
  { value: '<', label: '< (less than)' },
  { value: '<=', label: '<= (less or equal)' },
  { value: '>', label: '> (greater than)' },
  { value: '>=', label: '>= (greater or equal)' },
  { value: '=', label: '= (equal)' },
  { value: '!=', label: '!= (not equal)' }
]

// Get digital output channels
const digitalOutputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'digital_output')
    .map(([name]) => ({ name }))  // TAG only
})

// Get all numeric channels for value conditions
const numericChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => !['digital_input', 'digital_output'].includes(cfg.channel_type))
    .map(([name, cfg]) => ({ name, unit: cfg.unit }))  // TAG + unit only
})

// Get digital input channels
const digitalInputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'digital_input')
    .map(([name]) => ({ name }))  // TAG only
})

// Get analog output channels
const analogOutputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'analog_output')
    .map(([name, cfg]) => ({ name, unit: cfg.unit }))
})

function openNewInterlockModal() {
  if (!requireEditPermission()) return
  editingInterlock.value = null
  newInterlock.value = {
    name: '',
    description: '',
    bypassAllowed: true,
    maxBypassDuration: 0,
    conditionLogic: 'AND',
    silRating: undefined,
    priority: 'medium',
    requiresAcknowledgment: false,
    proofTestInterval: undefined,
    conditions: [],
    controls: []
  }
  showInterlockModal.value = true
}

function openEditInterlockModal(interlockId: string) {
  if (!requireEditPermission()) return
  const interlock = safety.interlocks.value.find(i => i.id === interlockId)
  if (!interlock) return

  // Store just the ID for reference
  editingInterlock.value = { id: interlockId } as Interlock
  newInterlock.value = {
    name: interlock.name,
    description: interlock.description || '',
    bypassAllowed: interlock.bypassAllowed,
    maxBypassDuration: interlock.maxBypassDuration || 0,
    conditionLogic: interlock.conditionLogic || 'AND',
    silRating: interlock.silRating,
    priority: interlock.priority || 'medium',
    requiresAcknowledgment: interlock.requiresAcknowledgment || false,
    proofTestInterval: interlock.proofTestInterval,
    conditions: interlock.conditions.map(c => ({ ...c })),
    controls: interlock.controls.map(c => ({ ...c }))
  }
  showInterlockModal.value = true
}

function addCondition() {
  newInterlock.value.conditions.push({
    id: `cond-${Date.now()}`,
    type: 'mqtt_connected',
    delay_s: 0  // Timer delay in seconds (0 = immediate)
  })
}

function removeCondition(index: number) {
  newInterlock.value.conditions.splice(index, 1)
}

function addControl() {
  newInterlock.value.controls.push({
    type: 'schedule_enable'
  })
}

function removeControl(index: number) {
  newInterlock.value.controls.splice(index, 1)
}

const isSavingInterlock = ref(false)

function saveInterlock() {
  if (isSavingInterlock.value) return
  if (!requireEditPermission()) return
  if (!newInterlock.value.name.trim()) return
  if (newInterlock.value.conditions.length === 0) return
  if (newInterlock.value.controls.length === 0) return

  isSavingInterlock.value = true

  if (editingInterlock.value) {
    // Update existing
    safety.updateInterlock(editingInterlock.value.id, {
      name: newInterlock.value.name,
      description: newInterlock.value.description,
      bypassAllowed: newInterlock.value.bypassAllowed,
      maxBypassDuration: newInterlock.value.maxBypassDuration || undefined,
      conditionLogic: newInterlock.value.conditionLogic,
      silRating: newInterlock.value.silRating,
      priority: newInterlock.value.priority,
      requiresAcknowledgment: newInterlock.value.requiresAcknowledgment,
      proofTestInterval: newInterlock.value.proofTestInterval,
      conditions: newInterlock.value.conditions,
      controls: newInterlock.value.controls
    })
  } else {
    // Create new
    safety.addInterlock({
      name: newInterlock.value.name,
      description: newInterlock.value.description,
      enabled: true,
      bypassAllowed: newInterlock.value.bypassAllowed,
      maxBypassDuration: newInterlock.value.maxBypassDuration || undefined,
      conditionLogic: newInterlock.value.conditionLogic,
      silRating: newInterlock.value.silRating,
      priority: newInterlock.value.priority,
      requiresAcknowledgment: newInterlock.value.requiresAcknowledgment,
      proofTestInterval: newInterlock.value.proofTestInterval,
      bypassed: false,
      conditions: newInterlock.value.conditions,
      controls: newInterlock.value.controls
    })
  }

  showInterlockModal.value = false
  isSavingInterlock.value = false
}

function deleteInterlock(id: string) {
  if (!requireEditPermission()) return
  if (confirm('Delete this interlock?')) {
    safety.removeInterlock(id)
  }
}

function toggleInterlockEnabled(id: string) {
  if (!requireEditPermission()) return
  const interlock = safety.interlocks.value.find(i => i.id === id)
  if (interlock) {
    safety.updateInterlock(id, { enabled: !interlock.enabled })
  }
}

function toggleInterlockBypass(id: string) {
  if (!requireOperatePermission()) return
  const interlock = safety.interlocks.value.find(i => i.id === id)
  if (interlock) {
    safety.bypassInterlock(id, !interlock.bypassed)
  }
}

// Check which channels referenced by an interlock's conditions are not configured
function getInterlockMissingChannels(interlockId: string): string[] {
  const interlock = safety.interlocks.value.find(i => i.id === interlockId)
  if (!interlock) return []
  const missing: string[] = []
  for (const cond of interlock.conditions) {
    if ((cond.type === 'channel_value' || cond.type === 'digital_input') && cond.channel) {
      if (!store.channels[cond.channel]) {
        missing.push(cond.channel)
      }
    }
  }
  return [...new Set(missing)]
}

// Get human-readable condition description
function getConditionDescription(cond: InterlockCondition): string {
  const typeInfo = conditionTypes.find(t => t.value === cond.type)
  if (!typeInfo) return 'Unknown condition'

  // Add delay suffix if applicable
  const delaySuffix = cond.delay_s && cond.delay_s > 0 ? ` (${cond.delay_s}s delay)` : ''

  if (cond.type === 'channel_value' && cond.channel) {
    const opText: Record<string, string> = { '>': 'above', '>=': 'at or above', '<': 'below', '<=': 'at or below', '==': 'equal to', '!=': 'not equal to' }
    const readable = opText[cond.operator || ''] || cond.operator
    return `${cond.channel} must be ${readable} ${cond.value}${delaySuffix}`
  }

  if (cond.type === 'digital_input' && cond.channel) {
    return `${cond.channel} must be ${cond.value ? 'ON' : 'OFF'}${delaySuffix}`
  }

  if (cond.type === 'alarm_active' && cond.alarmId) {
    return `Alarm "${cond.alarmId}" must not be active${delaySuffix}`
  }

  if (cond.type === 'alarm_state' && cond.alarmId) {
    const stateLabel = alarmStateOptions.find(o => o.value === cond.alarmState)?.label || cond.alarmState
    return `Alarm "${cond.alarmId}" must be in ${stateLabel} state${delaySuffix}`
  }

  if (cond.type === 'variable_value' && cond.variableId) {
    const opText: Record<string, string> = { '>': 'above', '>=': 'at or above', '<': 'below', '<=': 'at or below', '==': 'equal to', '!=': 'not equal to' }
    const readable = opText[cond.operator || ''] || cond.operator
    return `Variable "${cond.variableId}" must be ${readable} ${cond.value}${delaySuffix}`
  }

  if (cond.type === 'expression' && cond.expression) {
    const shortExpr = cond.expression.length > 40
      ? cond.expression.substring(0, 37) + '...'
      : cond.expression
    return `Expression must be true: ${shortExpr}`
  }

  if (cond.type === 'mqtt_connected') return `MQTT broker must be connected${delaySuffix}`
  if (cond.type === 'daq_connected') return `DAQ service must be online${delaySuffix}`
  if (cond.type === 'acquiring') return `System must be acquiring data${delaySuffix}`
  if (cond.type === 'not_recording') return `Recording must not be active${delaySuffix}`
  if (cond.type === 'no_active_alarms') return `No alarms may be active${delaySuffix}`
  if (cond.type === 'no_latched_alarms') return `No alarms may be latched${delaySuffix}`

  return typeInfo.label + delaySuffix
}

// Get human-readable control description
function getControlDescription(ctrl: InterlockControl): string {
  const typeInfo = controlTypes.find(t => t.value === ctrl.type)
  if (!typeInfo) return 'Unknown control'

  if (ctrl.type === 'digital_output' && ctrl.channel) {
    return `Blocks ${ctrl.channel} output`
  }
  if (ctrl.type === 'analog_output' && ctrl.channel) {
    return `Blocks ${ctrl.channel} output`
  }
  if (ctrl.type === 'set_digital_output' && ctrl.channel) {
    return `Forces ${ctrl.channel} to ${ctrl.setValue ? 'ON' : 'OFF'}`
  }
  if (ctrl.type === 'set_analog_output' && ctrl.channel) {
    return `Forces ${ctrl.channel} to ${ctrl.setValue}`
  }
  if (ctrl.type === 'stop_session') return 'Stops active session'
  if (ctrl.type === 'stop_acquisition') return 'Stops data acquisition'
  if (ctrl.type === 'schedule_enable') return 'Blocks schedule from starting'
  if (ctrl.type === 'recording_start') return 'Blocks recording from starting'
  if (ctrl.type === 'acquisition_start') return 'Blocks acquisition from starting'
  if (ctrl.type === 'session_start') return 'Blocks session from starting'
  if (ctrl.type === 'script_start') return 'Blocks scripts from starting'

  return typeInfo.label
}
</script>

<template>
  <div class="safety-tab">
    <div v-if="!canOperate" class="view-only-notice">
      <span class="lock-icon">🔒</span>
      <span>View Only - Operator access required for safety actions</span>
      <button class="login-link" @click="showLoginDialogFn">Login</button>
    </div>

    <!-- Header with section tabs and summary -->
    <div class="safety-header">
      <div class="header-left">
        <h2>Safety System</h2>
        <div class="section-tabs">
          <button
            class="section-tab"
            :class="{ active: activeSection === 'alarms' }"
            @click="activeSection = 'alarms'"
          >
            Alarms
          </button>
          <button
            class="section-tab"
            :class="{ active: activeSection === 'interlocks' }"
            @click="activeSection = 'interlocks'"
          >
            Interlocks
          </button>
          <button
            class="section-tab"
            :class="{ active: activeSection === 'correlation' }"
            @click="activeSection = 'correlation'"
          >
            Correlation
            <span v-if="soe.activeCorrelationCount.value > 0" class="tab-badge">
              {{ soe.activeCorrelationCount.value }}
            </span>
          </button>
          <button
            class="section-tab"
            :class="{ active: activeSection === 'soe' }"
            @click="activeSection = 'soe'"
          >
            SOE
            <span v-if="soe.soeEventCount.value > 0" class="tab-badge">
              {{ soe.soeEventCount.value }}
            </span>
          </button>
        </div>
      </div>

      <div class="header-right">
        <!-- Node Filter (for multi-node setups) -->
        <div v-if="availableNodes.length > 2" class="node-filter">
          <select v-model="selectedNodeFilter" class="node-select">
            <option v-for="node in availableNodes" :key="node.id" :value="node.id">
              {{ node.name }}
            </option>
          </select>
        </div>

        <!-- Latch Status (prominent when latches active) -->
        <div v-if="safety.hasLatchedAlarms.value" class="latch-status active" @click="resetAllLatched">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 17a2 2 0 002-2V9a2 2 0 00-4 0v6a2 2 0 002 2zm6-9v6a6 6 0 11-12 0V8h2v6a4 4 0 008 0V8h2z"/>
          </svg>
          <span>{{ safety.latchedAlarmCount.value }} LATCHED</span>
          <span class="reset-hint">Click to reset all</span>
        </div>
        <div v-else class="latch-status clear">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 12l2 2 4-4"/>
          </svg>
          <span>CLEAR</span>
        </div>

        <!-- First-Out Indicator (root cause) -->
        <div v-if="safety.firstOutAlarm.value" class="first-out-indicator" @click="scrollToAlarm(safety.firstOutAlarm.value?.id)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
          </svg>
          <span class="first-out-label">FIRST-OUT:</span>
          <span class="first-out-name">{{ safety.firstOutAlarm.value?.channel }}</span>
        </div>

        <!-- Alarm summary counts by severity -->
        <div class="alarm-summary">
          <div class="summary-item critical" :class="{ pulse: alarmCounts.critical > 0 }">
            <span class="count">{{ alarmCounts.critical }}</span>
            <span class="label">Critical</span>
          </div>
          <div class="summary-item alarm" :class="{ pulse: ((alarmCounts.high ?? 0) || (alarmCounts.active ?? 0)) > 0 }">
            <span class="count">{{ alarmCounts.high || alarmCounts.active || 0 }}</span>
            <span class="label">High</span>
          </div>
          <div class="summary-item warning" :class="{ pulse: ((alarmCounts.medium ?? 0) || (alarmCounts.warnings ?? 0)) > 0 }">
            <span class="count">{{ alarmCounts.medium || alarmCounts.warnings || 0 }}</span>
            <span class="label">Medium</span>
          </div>
          <div class="summary-item shelved" v-if="alarmCounts.shelved > 0">
            <span class="count">{{ alarmCounts.shelved }}</span>
            <span class="label">Shelved</span>
          </div>
          <div class="summary-item acknowledged">
            <span class="count">{{ alarmCounts.acknowledged }}</span>
            <span class="label">Ack'd</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ALARMS SECTION -->
    <div v-if="activeSection === 'alarms'" class="safety-content">
      <!-- Left: Active Alarms -->
      <div class="active-alarms-panel">
        <div class="panel-header">
          <h3>Active Alarms</h3>
          <div class="panel-header-actions">
            <button
              v-if="filteredActiveAlarms.length > 0"
              class="btn btn-sm btn-secondary"
              @click="acknowledgeAll"
            >
              Acknowledge All
            </button>
            <button
              v-if="filteredActiveAlarms.length > 0"
              class="btn btn-sm btn-danger"
              @click="clearAllAlarms"
              title="Clear all alarms (use when project changes or to reset alarm state)"
            >
              Clear All
            </button>
          </div>
        </div>

        <div v-if="filteredActiveAlarms.length === 0" class="no-alarms">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <p>No active alarms</p>
        </div>

        <div v-else class="alarm-list">
          <div
            v-for="alarm in filteredActiveAlarms"
            :key="alarm.id"
            :id="`alarm-${alarm.id}`"
            class="alarm-item"
            :class="[
              getSeverityClass(alarm.severity),
              alarm.state,
              { 'first-out': alarm.is_first_out }
            ]"
          >
            <div class="alarm-icon">
              <svg v-if="alarm.severity === 'critical' || alarm.severity === 'alarm'" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
              </svg>
              <svg v-else-if="alarm.state === 'shelved'" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
              </svg>
              <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h2v2h-2v-2zm0-10h2v8h-2V7z"/>
              </svg>
            </div>

            <div class="alarm-content">
              <div class="alarm-title">
                <span v-if="alarm.is_first_out" class="first-out-badge">1ST</span>
                <span class="alarm-tag">{{ alarm.channel }}</span>
                <span class="alarm-badge" :class="getSeverityClass(alarm.severity)">
                  {{ getSeverityLabel(alarm.severity) }}
                </span>
                <span v-if="alarm.state === 'acknowledged'" class="alarm-badge ack">ACK</span>
                <span v-if="alarm.state === 'returned'" class="alarm-badge returned">RTN</span>
                <span v-if="alarm.state === 'shelved'" class="alarm-badge shelved">SHELVED</span>
              </div>
              <div class="alarm-message">{{ alarm.message }}</div>
              <div class="alarm-meta">
                <span>Current: {{ getCurrentValue(alarm.channel) }}</span>
                <span>Duration: {{ formatDuration(alarm.duration_seconds) }}</span>
                <span>Since: {{ formatTime(alarm.triggered_at) }}</span>
                <span v-if="alarm.shelve_expires_at" class="shelve-expiry">
                  Unshelves: {{ formatTime(alarm.shelve_expires_at) }}
                </span>
              </div>
            </div>

            <div class="alarm-actions">
              <!-- ACK button for active/returned alarms -->
              <button
                v-if="alarm.state === 'active' || alarm.state === 'returned'"
                class="btn btn-sm btn-ack"
                @click="acknowledgeAlarm(alarm.id)"
                title="Acknowledge - silence alert"
              >
                ACK
              </button>

              <!-- SHELVE button (not for shelved alarms) -->
              <button
                v-if="alarm.state !== 'shelved' && alarmConfigs[alarm.channel]?.shelve_allowed !== false"
                class="btn btn-sm btn-shelve"
                @click="openShelveModal(alarm)"
                title="Shelve - temporarily suppress this alarm"
              >
                SHELVE
              </button>

              <!-- UNSHELVE button for shelved alarms -->
              <button
                v-if="alarm.state === 'shelved'"
                class="btn btn-sm btn-unshelve"
                @click="safety.unshelveAlarm(alarm.id)"
                title="Unshelve - re-enable this alarm"
              >
                UNSHELVE
              </button>

              <!-- RESET for latched/timed-latch alarms -->
              <button
                v-if="alarmConfigs[alarm.channel]?.behavior === 'latch' || alarmConfigs[alarm.channel]?.behavior === 'timed_latch'"
                class="btn btn-sm btn-reset"
                @click="resetAlarm(alarm.id)"
                title="Reset - force clear this latched alarm"
              >
                RESET
              </button>

              <!-- CLEAR for auto-clear alarms that are acknowledged -->
              <button
                v-else-if="alarm.state === 'acknowledged'"
                class="btn btn-sm btn-clear"
                @click="resetAlarm(alarm.id)"
                title="Force clear this alarm"
              >
                CLEAR
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Center: Alarm Configuration -->
      <div class="config-panel">
        <div class="panel-header">
          <h3>Alarm Configuration</h3>
          <button class="btn btn-sm btn-secondary" @click="safety.syncAlarmConfigsToBackend()" title="Push alarm configs to backend service">
            Sync to Backend
          </button>
        </div>

        <div class="config-table-container">
          <table class="config-table">
            <thead>
              <tr>
                <th>TAG</th>
                <th>Enabled</th>
                <th>Low Alarm</th>
                <th>Low Warn</th>
                <th>High Warn</th>
                <th>High Alarm</th>
                <th>Behavior</th>
                <th>Deadband</th>
                <th>Delay</th>
                <th>Edit</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="ch in filteredChannelList"
                :key="ch.name"
                :class="{ selected: selectedChannel === ch.name }"
                @click="selectedChannel = ch.name"
              >
                <td class="channel-name">
                  <span class="tag">{{ ch.name }}</span>
                  <span class="unit">{{ ch.unit }}</span>
                </td>
                <td>
                  <label class="toggle-switch">
                    <input
                      type="checkbox"
                      v-model="ch.alarmConfig.enabled"
                      @click.stop
                    />
                    <span class="slider"></span>
                  </label>
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.low_alarm"
                    class="threshold-input alarm"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.low_warning"
                    class="threshold-input warning"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.high_warning"
                    class="threshold-input warning"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.high_alarm"
                    class="threshold-input alarm"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <select
                    v-model="ch.alarmConfig.behavior"
                    class="behavior-select"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  >
                    <option value="auto_clear">Auto</option>
                    <option value="latch">Latch</option>
                    <option value="timed_latch">Timed Latch</option>
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.deadband"
                    class="small-input"
                    min="0"
                    step="0.1"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <input
                    type="number"
                    v-model.number="ch.alarmConfig.delay_seconds"
                    class="small-input"
                    min="0"
                    step="1"
                    :disabled="!ch.alarmConfig.enabled"
                    @click.stop
                  />
                </td>
                <td>
                  <button
                    class="btn btn-xs btn-edit"
                    @click.stop="openAlarmConfigModal(ch.name)"
                    title="Edit full alarm configuration"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Selected channel actions -->
        <div v-if="selectedChannel && selectedAlarmConfig" class="channel-actions">
          <h4>{{ selectedChannel }} - Actions</h4>
          <div class="action-options">
            <label class="checkbox-label">
              <input type="checkbox" v-model="selectedAlarmConfig.log_to_file" />
              Log to file
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="selectedAlarmConfig.play_sound" />
              Play sound
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="selectedAlarmConfig.start_recording" />
              Start recording on alarm
            </label>
          </div>
        </div>
      </div>

      <!-- Right: History & System Health -->
      <div class="right-panel">
        <!-- System Health -->
        <div class="health-panel">
          <h3>System Health</h3>
          <div class="health-items">
            <div class="health-item" :class="{ ok: systemHealth.mqtt_connected, error: !systemHealth.mqtt_connected }">
              <span class="health-indicator"></span>
              <span>MQTT Connection</span>
            </div>
            <div class="health-item" :class="{ ok: systemHealth.daq_connected, error: !systemHealth.daq_connected }">
              <span class="health-indicator"></span>
              <span>DAQ Status</span>
            </div>
            <div class="health-item" :class="{ ok: !systemHealth.data_timeout, warning: systemHealth.data_timeout }">
              <span class="health-indicator"></span>
              <span>Data Flow</span>
            </div>
          </div>
        </div>

        <!-- Alarm History -->
        <div class="history-panel">
          <div class="panel-header">
            <h3>Alarm History</h3>
            <div class="history-filters">
              <select v-model="historyFilter.severity" class="filter-select">
                <option value="">All Types</option>
                <option value="alarm">Alarms</option>
                <option value="warning">Warnings</option>
              </select>
              <select v-model="historyFilter.dateRange" class="filter-select">
                <option value="all">All Time</option>
                <option value="today">Today</option>
                <option value="week">This Week</option>
              </select>
              <button
                class="btn btn-sm btn-secondary export-btn"
                @click="exportAlarmHistoryCsv"
                :disabled="filteredHistory.length === 0"
                title="Export to CSV"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                CSV
              </button>
            </div>
          </div>

          <div class="history-list">
            <div
              v-for="entry in filteredHistory.slice(0, 50)"
              :key="entry.id"
              class="history-item"
              :class="entry.severity"
            >
              <div class="history-time">{{ formatDateTime(entry.triggered_at) }}</div>
              <div class="history-channel">
                <span class="history-tag">{{ entry.channel }}</span>
              </div>
              <div class="history-message">{{ entry.message }}</div>
              <div class="history-duration">{{ formatDuration(entry.duration_seconds) }}</div>
            </div>
            <div v-if="filteredHistory.length === 0" class="no-history">
              No alarm history
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- INTERLOCKS SECTION -->
    <div v-else-if="activeSection === 'interlocks'" class="interlocks-content">
      <!-- Left: Interlock Status -->
      <div class="interlocks-status-panel">
        <div class="panel-header">
          <h3>Interlock Status</h3>
          <button
            v-if="safety.interlocks.value.length > 0"
            class="btn btn-sm btn-primary"
            @click="openNewInterlockModal"
          >
            + Add Interlock
          </button>
        </div>

        <div v-if="safety.interlocks.value.length === 0" class="no-interlocks">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          <p>No interlocks configured</p>
          <button class="btn btn-primary" @click="openNewInterlockModal">Create First Interlock</button>
        </div>

        <div v-else class="interlock-list">
          <div
            v-for="status in safety.interlockStatuses.value"
            :key="status.id"
            class="interlock-card"
            :class="{
              satisfied: status.satisfied,
              blocked: !status.satisfied && !status.bypassed,
              bypassed: status.bypassed,
              disabled: !status.enabled
            }"
          >
            <div class="interlock-header">
              <div class="interlock-status-icon">
                <svg v-if="status.satisfied || status.bypassed" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/>
                </svg>
              </div>
              <div class="interlock-name">
                {{ status.name }}
                <span v-if="status.bypassed" class="bypass-badge">BYPASSED</span>
                <span v-if="!status.enabled" class="disabled-badge">DISABLED</span>
              </div>
              <div class="interlock-actions">
                <button
                  v-if="safety.interlocks.value.find(i => i.id === status.id)?.bypassAllowed"
                  class="btn btn-sm"
                  :class="status.bypassed ? 'btn-warning' : 'btn-secondary'"
                  @click="toggleInterlockBypass(status.id)"
                  :title="status.bypassed ? 'Remove bypass' : 'Bypass interlock'"
                >
                  {{ status.bypassed ? 'REMOVE BYPASS' : 'BYPASS' }}
                </button>
                <button
                  class="btn btn-sm btn-secondary"
                  @click="toggleInterlockEnabled(status.id)"
                >
                  {{ status.enabled ? 'DISABLE' : 'ENABLE' }}
                </button>
                <button
                  class="btn btn-sm btn-secondary"
                  @click="openEditInterlockModal(status.id)"
                >
                  EDIT
                </button>
              </div>
            </div>

            <!-- Description -->
            <div
              v-if="safety.interlocks.value.find(i => i.id === status.id)?.description"
              class="interlock-description"
            >
              {{ safety.interlocks.value.find(i => i.id === status.id)?.description }}
            </div>

            <!-- Channel not configured warning -->
            <div
              v-if="getInterlockMissingChannels(status.id).length > 0"
              class="interlock-warning"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
              </svg>
              <span>
                Channel{{ getInterlockMissingChannels(status.id).length > 1 ? 's' : '' }}
                not configured: {{ getInterlockMissingChannels(status.id).join(', ') }}
              </span>
            </div>

            <!-- Show conditions -->
            <div class="interlock-conditions">
              <div class="conditions-label">Requires:</div>
              <div
                v-for="(cond, idx) in safety.interlocks.value.find(i => i.id === status.id)?.conditions || []"
                :key="idx"
                class="condition-item"
                :class="{
                  ok: !status.failedConditions.find(f => f.condition.id === cond.id),
                  failed: status.failedConditions.find(f => f.condition.id === cond.id)
                }"
              >
                <span class="condition-icon">
                  <svg v-if="!status.failedConditions.find(f => f.condition.id === cond.id)" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                  </svg>
                  <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                  </svg>
                </span>
                <span class="condition-text">{{ getConditionDescription(cond) }}</span>
                <span v-if="status.failedConditions.find(f => f.condition.id === cond.id)" class="condition-reason">
                  {{ status.failedConditions.find(f => f.condition.id === cond.id)?.reason }}
                </span>
              </div>
            </div>

            <!-- Show what it controls -->
            <div class="interlock-controls">
              <div class="controls-label">Controls:</div>
              <div class="control-tags">
                <span
                  v-for="(ctrl, idx) in status.controls"
                  :key="idx"
                  class="control-tag"
                >
                  {{ getControlDescription(ctrl) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Blocked Actions Summary -->
      <div class="blocked-actions-panel">
        <div class="panel-header">
          <h3>Blocked Actions</h3>
        </div>

        <div class="blocked-list">
          <div
            v-if="safety.isScheduleBlocked.value.blocked"
            class="blocked-item"
          >
            <div class="blocked-action">Schedule Enable</div>
            <div class="blocked-by">
              Blocked by:
              <span v-for="(s, i) in safety.isScheduleBlocked.value.blockedBy" :key="s.id">
                {{ s.name }}<span v-if="i < safety.isScheduleBlocked.value.blockedBy.length - 1">, </span>
              </span>
            </div>
          </div>

          <div
            v-if="safety.isRecordingBlocked.value.blocked"
            class="blocked-item"
          >
            <div class="blocked-action">Recording Start</div>
            <div class="blocked-by">
              Blocked by:
              <span v-for="(s, i) in safety.isRecordingBlocked.value.blockedBy" :key="s.id">
                {{ s.name }}<span v-if="i < safety.isRecordingBlocked.value.blockedBy.length - 1">, </span>
              </span>
            </div>
          </div>

          <div
            v-if="safety.isAcquisitionBlocked.value.blocked"
            class="blocked-item"
          >
            <div class="blocked-action">Acquisition Start</div>
            <div class="blocked-by">
              Blocked by:
              <span v-for="(s, i) in safety.isAcquisitionBlocked.value.blockedBy" :key="s.id">
                {{ s.name }}<span v-if="i < safety.isAcquisitionBlocked.value.blockedBy.length - 1">, </span>
              </span>
            </div>
          </div>

          <div
            v-if="!safety.isScheduleBlocked.value.blocked &&
                  !safety.isRecordingBlocked.value.blocked &&
                  !safety.isAcquisitionBlocked.value.blocked"
            class="no-blocked"
          >
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            <p>All interlocks satisfied</p>
          </div>
        </div>

        <!-- Safety Actions Panel -->
        <SafetyActionsPanel />

        <!-- Interlock History Panel -->
        <div class="interlock-history-panel">
          <div class="panel-header">
            <h3>Interlock History</h3>
            <span class="count-badge">{{ safety.interlockHistory.value.length }}</span>
          </div>

          <div v-if="safety.interlockHistory.value.length === 0" class="no-history">
            <p>No interlock events recorded</p>
          </div>

          <div v-else class="interlock-history-list">
            <div
              v-for="entry in safety.interlockHistory.value.slice(0, 20)"
              :key="entry.id"
              class="interlock-history-item"
              :class="entry.event"
            >
              <div class="history-time">{{ formatDateTime(entry.timestamp) }}</div>
              <div class="history-event">
                <span class="event-badge" :class="entry.event">{{ formatInterlockEvent(entry.event) }}</span>
                <span class="interlock-name">{{ entry.interlockName }}</span>
              </div>
              <div v-if="entry.reason" class="history-reason">{{ entry.reason }}</div>
              <div v-if="entry.user" class="history-user">by {{ entry.user }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- CORRELATION SECTION -->
    <div v-if="activeSection === 'correlation'" class="safety-content correlation-section">
      <!-- Left: Active Correlations -->
      <div class="correlation-panel">
        <div class="panel-header">
          <h3>Active Correlations</h3>
          <span class="count-badge">{{ soe.activeCorrelationCount.value }}</span>
        </div>

        <div v-if="soe.activeCorrelations.value.length === 0" class="no-correlations">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
          </svg>
          <p>No active correlations</p>
          <p class="subtitle">Correlations are detected when related alarms trigger together</p>
        </div>

        <div v-else class="correlation-list">
          <div
            v-for="corr in soe.activeCorrelations.value"
            :key="corr.correlationId"
            class="correlation-card"
          >
            <div class="correlation-header">
              <span class="correlation-id">{{ corr.correlationId.slice(0, 8) }}</span>
              <span class="correlation-time">{{ formatTimestamp(corr.timestamp) }}</span>
            </div>
            <div class="correlation-body">
              <div class="root-cause">
                <span class="label">Root Cause:</span>
                <span class="alarm-tag">{{ corr.rootCauseAlarmId }}</span>
              </div>
              <div class="related-alarms">
                <span class="label">Related ({{ corr.relatedAlarmIds.length }}):</span>
                <div class="alarm-tags">
                  <span v-for="alarmId in corr.relatedAlarmIds" :key="alarmId" class="alarm-tag secondary">
                    {{ alarmId }}
                  </span>
                </div>
              </div>
            </div>
            <div class="correlation-footer">
              <span class="rule-id">Rule: {{ corr.ruleId }}</span>
              <button class="btn-icon" @click="soe.clearCorrelation(corr.correlationId)" title="Dismiss">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Correlation Rules -->
      <div class="rules-panel">
        <div class="panel-header">
          <h3>Correlation Rules</h3>
          <button class="btn btn-sm btn-primary" @click="openNewCorrelationRuleModal">
            + Add Rule
          </button>
        </div>

        <div v-if="soe.correlationRules.value.length === 0" class="no-rules">
          <p>No correlation rules defined</p>
          <p class="subtitle">Rules define how alarms should be grouped for root cause analysis</p>
        </div>

        <div v-else class="rules-list">
          <div
            v-for="rule in soe.correlationRules.value"
            :key="rule.id"
            class="rule-card"
            :class="{ disabled: !rule.enabled }"
          >
            <div class="rule-header">
              <span class="rule-name">{{ rule.name }}</span>
              <div class="rule-actions">
                <button
                  class="btn-icon"
                  :class="{ active: rule.enabled }"
                  @click="soe.toggleCorrelationRule(rule.id)"
                  :title="rule.enabled ? 'Disable' : 'Enable'"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path v-if="rule.enabled" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm0-2a8 8 0 100-16 8 8 0 000 16z"/>
                    <circle v-else cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
                  </svg>
                </button>
                <button class="btn-icon danger" @click="soe.removeCorrelationRule(rule.id)" title="Delete">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                  </svg>
                </button>
              </div>
            </div>
            <div class="rule-body">
              <div class="rule-trigger">
                <span class="label">Trigger:</span>
                <span class="alarm-tag">{{ rule.triggerAlarm }}</span>
              </div>
              <div class="rule-related">
                <span class="label">Related:</span>
                <span v-for="alarm in rule.relatedAlarms" :key="alarm" class="alarm-tag secondary">
                  {{ alarm }}
                </span>
              </div>
              <div class="rule-meta">
                <span>Window: {{ rule.timeWindowMs }}ms</span>
                <span v-if="rule.rootCauseHint">Root cause hint: {{ rule.rootCauseHint }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- SOE SECTION -->
    <div v-if="activeSection === 'soe'" class="safety-content soe-section">
      <!-- SOE Header with filters and actions -->
      <div class="soe-header">
        <div class="soe-stats">
          <div class="stat-item">
            <span class="stat-value">{{ soe.soeEventCount.value }}</span>
            <span class="stat-label">Total Events</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ soe.recentEvents.value.length }}</span>
            <span class="stat-label">Last 5 min</span>
          </div>
          <div class="stat-item" v-for="(count, type) in soe.soeEventCounts.value" :key="type" v-show="count > 0">
            <span class="stat-value">{{ count }}</span>
            <span class="stat-label">{{ formatEventType(type) }}</span>
          </div>
        </div>
        <div class="soe-actions">
          <button class="btn btn-sm btn-secondary" @click="exportSoe">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>
            </svg>
            Export CSV
          </button>
          <button class="btn btn-sm btn-danger" @click="soe.clearSoeBuffer()">
            Clear Buffer
          </button>
        </div>
      </div>

      <!-- SOE Event List -->
      <div class="soe-events-panel">
        <div class="panel-header">
          <h3>Sequence of Events</h3>
          <div class="soe-filters">
            <select v-model="soeTypeFilter" class="filter-select">
              <option value="">All Types</option>
              <option value="alarm_triggered">Alarm Triggered</option>
              <option value="alarm_cleared">Alarm Cleared</option>
              <option value="alarm_acknowledged">Acknowledged</option>
              <option value="state_change">State Change</option>
              <option value="digital_edge">Digital Edge</option>
              <option value="setpoint_change">Setpoint Change</option>
            </select>
          </div>
        </div>

        <div v-if="filteredSoeEvents.length === 0" class="no-events">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <p>No events recorded</p>
          <p class="subtitle">Events will appear here as they occur</p>
        </div>

        <div v-else class="soe-table-wrapper">
          <table class="soe-table">
            <thead>
              <tr>
                <th>Timestamp (μs)</th>
                <th>Time</th>
                <th>Type</th>
                <th>Channel</th>
                <th>Value</th>
                <th>Message</th>
                <th>Correlation</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="event in filteredSoeEvents.slice(0, 100)"
                :key="event.eventId"
                :class="getEventRowClass(event)"
              >
                <td class="timestamp-us">{{ event.timestampUs }}</td>
                <td class="timestamp-iso">{{ formatIsoTime(event.timestampIso) }}</td>
                <td class="event-type">
                  <span :class="'type-badge ' + event.eventType">
                    {{ formatEventType(event.eventType) }}
                  </span>
                </td>
                <td class="channel">{{ event.sourceChannel }}</td>
                <td class="value">
                  {{ event.value }}
                  <span v-if="event.previousValue !== undefined" class="prev-value">
                    (was {{ event.previousValue }})
                  </span>
                </td>
                <td class="message">{{ event.message }}</td>
                <td class="correlation">
                  <span v-if="event.correlationId" class="correlation-link" @click="goToCorrelation(event.correlationId)">
                    {{ event.correlationId.slice(0, 8) }}
                  </span>
                  <span v-else class="no-correlation">-</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="filteredSoeEvents.length > 100" class="soe-footer">
          Showing 100 of {{ filteredSoeEvents.length }} events. Export to CSV for full data.
        </div>
      </div>
    </div>

    <!-- Interlock Edit/Create Modal -->
    <Teleport to="body">
      <div v-if="showInterlockModal" class="modal-overlay" @click.self="showInterlockModal = false">
        <div class="modal interlock-modal">
          <h3>{{ editingInterlock ? 'Edit Interlock' : 'Create Interlock' }}</h3>

          <div class="form-group">
            <label>Name</label>
            <input type="text" v-model="newInterlock.name" placeholder="e.g., Allow Heater Control" />
          </div>

          <div class="form-group">
            <label>Description (optional)</label>
            <input type="text" v-model="newInterlock.description" placeholder="What does this interlock protect?" />
          </div>

          <div class="form-row-group">
            <div class="form-group half">
              <label class="checkbox-label">
                <input type="checkbox" v-model="newInterlock.bypassAllowed" />
                Allow operator bypass
              </label>
            </div>
            <div class="form-group half" v-if="newInterlock.bypassAllowed">
              <label>Max Bypass Duration (seconds)</label>
              <input type="number" v-model.number="newInterlock.maxBypassDuration" min="0" placeholder="0 = unlimited" />
            </div>
          </div>

          <!-- IEC 61508 SIL Rating -->
          <div class="form-row-group">
            <div class="form-group half">
              <label>SIL Rating (IEC 61508)</label>
              <select v-model="newInterlock.silRating">
                <option v-for="opt in silRatingOptions" :key="opt.label" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>
            <div class="form-group half">
              <label>Proof Test Interval (days)</label>
              <input type="number" v-model.number="newInterlock.proofTestInterval" min="0" placeholder="Optional" />
            </div>
          </div>

          <!-- Priority & Trip Acknowledgment -->
          <div class="form-row-group">
            <div class="form-group half">
              <label>Priority</label>
              <select v-model="newInterlock.priority">
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div class="form-group half">
              <label class="checkbox-label">
                <input type="checkbox" v-model="newInterlock.requiresAcknowledgment" />
                Require trip acknowledgment
              </label>
            </div>
          </div>

          <!-- Conditions -->
          <div class="conditions-section">
            <div class="section-header">
              <h4>Conditions</h4>
              <div class="logic-toggle">
                <label>
                  <input type="radio" v-model="newInterlock.conditionLogic" value="AND" /> ALL (AND)
                </label>
                <label>
                  <input type="radio" v-model="newInterlock.conditionLogic" value="OR" /> ANY (OR)
                </label>
              </div>
              <button class="btn btn-sm btn-secondary" @click="addCondition">+ Add</button>
            </div>

            <div v-for="(cond, idx) in newInterlock.conditions" :key="cond.id" class="condition-row">
              <select v-model="cond.type" class="condition-type-select">
                <option v-for="ct in conditionTypes" :key="ct.value" :value="ct.value">
                  {{ ct.label }}
                </option>
              </select>

              <!-- Channel select for channel_value -->
              <select
                v-if="conditionTypes.find(t => t.value === cond.type)?.needsChannel && cond.type === 'channel_value'"
                v-model="cond.channel"
                class="condition-channel-select"
              >
                <option value="">Select channel...</option>
                <option v-for="ch in numericChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }} ({{ ch.unit }})
                </option>
              </select>

              <!-- Channel select for digital_input -->
              <select
                v-if="cond.type === 'digital_input'"
                v-model="cond.channel"
                class="condition-channel-select"
              >
                <option value="">Select input...</option>
                <option v-for="ch in digitalInputChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }}
                </option>
              </select>

              <!-- Operator for channel_value -->
              <select
                v-if="conditionTypes.find(t => t.value === cond.type)?.needsOperator"
                v-model="cond.operator"
                class="condition-operator-select"
              >
                <option v-for="op in operators" :key="op.value" :value="op.value">
                  {{ op.label }}
                </option>
              </select>

              <!-- Value for channel_value -->
              <input
                v-if="conditionTypes.find(t => t.value === cond.type)?.needsOperator"
                type="number"
                v-model.number="cond.value"
                class="condition-value-input"
                placeholder="Value"
              />

              <!-- Value (ON/OFF) for digital_input -->
              <select
                v-if="cond.type === 'digital_input'"
                v-model="cond.value"
                class="condition-bool-select"
              >
                <option :value="false">OFF</option>
                <option :value="true">ON</option>
              </select>

              <!-- Alarm selection for alarm_active / alarm_state -->
              <select
                v-if="cond.type === 'alarm_active' || cond.type === 'alarm_state'"
                v-model="cond.alarmId"
                class="condition-channel-select"
              >
                <option value="">Select alarm...</option>
                <option v-for="ch in Object.keys(store.channels)" :key="ch" :value="ch">
                  {{ ch }}
                </option>
              </select>

              <!-- State selection for alarm_state -->
              <select
                v-if="cond.type === 'alarm_state'"
                v-model="cond.alarmState"
                class="condition-bool-select"
              >
                <option v-for="opt in alarmStateOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>

              <!-- Variable selection for variable_value -->
              <select
                v-if="cond.type === 'variable_value'"
                v-model="cond.variableId"
                class="condition-channel-select"
              >
                <option value="">Select variable...</option>
                <option v-for="(v, id) in playground.variables.value" :key="id" :value="id">
                  {{ v.name || id }}
                </option>
              </select>

              <!-- Expression input -->
              <input
                v-if="cond.type === 'expression'"
                type="text"
                v-model="cond.expression"
                class="condition-expression-input"
                placeholder="e.g., temp1 > 100 AND temp2 < 50"
              />

              <!-- Timer delay (for all condition types) -->
              <div class="delay-input" v-if="cond.type !== 'expression'">
                <label title="Condition must be TRUE for this duration before triggering">Delay:</label>
                <input
                  type="number"
                  v-model.number="cond.delay_s"
                  min="0"
                  step="0.1"
                  class="delay-value"
                  placeholder="0"
                />
                <span class="unit">s</span>
              </div>

              <button class="btn btn-sm btn-danger" @click="removeCondition(idx)">X</button>
            </div>

            <p v-if="newInterlock.conditions.length === 0" class="empty-hint">
              Add at least one condition
            </p>
          </div>

          <!-- Controls -->
          <div class="controls-section">
            <div class="section-header">
              <h4>What this controls</h4>
              <button class="btn btn-sm btn-secondary" @click="addControl">+ Add</button>
            </div>

            <div v-for="(ctrl, idx) in newInterlock.controls" :key="idx" class="control-row">
              <select v-model="ctrl.type" class="control-type-select">
                <option v-for="ct in controlTypes" :key="ct.value" :value="ct.value">
                  {{ ct.label }}
                </option>
              </select>

              <!-- Channel select for digital_output / set_digital_output -->
              <select
                v-if="ctrl.type === 'digital_output' || ctrl.type === 'set_digital_output'"
                v-model="ctrl.channel"
                class="control-channel-select"
              >
                <option value="">Select DO...</option>
                <option v-for="ch in digitalOutputChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }}
                </option>
              </select>

              <!-- Channel select for set_analog_output -->
              <select
                v-if="ctrl.type === 'set_analog_output'"
                v-model="ctrl.channel"
                class="control-channel-select"
              >
                <option value="">Select AO...</option>
                <option v-for="ch in analogOutputChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }}
                </option>
              </select>

              <!-- Value select for set_digital_output (ON/OFF) -->
              <select
                v-if="ctrl.type === 'set_digital_output'"
                v-model="ctrl.setValue"
                class="control-value-select"
              >
                <option :value="0">OFF (0)</option>
                <option :value="1">ON (1)</option>
              </select>

              <!-- Value input for set_analog_output (voltage) -->
              <input
                v-if="ctrl.type === 'set_analog_output'"
                v-model.number="ctrl.setValue"
                type="number"
                step="0.1"
                placeholder="Value"
                class="control-value-input"
              />

              <button class="btn btn-sm btn-danger" @click="removeControl(idx)">X</button>
            </div>

            <p v-if="newInterlock.controls.length === 0" class="empty-hint">
              Add at least one control
            </p>
          </div>

          <div class="modal-actions">
            <button v-if="editingInterlock" class="btn btn-danger" @click="deleteInterlock(editingInterlock.id); showInterlockModal = false">
              Delete
            </button>
            <div class="modal-actions-right">
              <button class="btn btn-secondary" @click="showInterlockModal = false">Cancel</button>
              <button
                class="btn btn-primary"
                @click="saveInterlock"
                :disabled="!newInterlock.name || newInterlock.conditions.length === 0 || newInterlock.controls.length === 0"
              >
                {{ editingInterlock ? 'Save' : 'Create' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Shelve Alarm Modal -->
    <Teleport to="body">
      <div v-if="showShelveModal" class="modal-overlay" @click.self="showShelveModal = false">
        <div class="modal shelve-modal">
          <h3>Shelve Alarm</h3>
          <p class="shelve-target">{{ shelveTarget?.name }}</p>

          <div class="form-group">
            <label>Duration</label>
            <select v-model.number="shelveDuration" class="form-select">
              <option v-for="opt in shelveDurationOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label>Reason (required for audit)</label>
            <input
              type="text"
              v-model="shelveReason"
              placeholder="e.g., Sensor maintenance, Known issue"
              class="form-input"
            />
          </div>

          <div class="shelve-warning">
            Shelved alarms are temporarily suppressed but remain active.
            The alarm will automatically unshelve after the selected duration.
          </div>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showShelveModal = false">Cancel</button>
            <button
              class="btn btn-warning"
              @click="confirmShelve"
              :disabled="!shelveReason.trim()"
            >
              Shelve Alarm
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Alarm Configuration Modal -->
    <AlarmConfigModal
      :visible="showAlarmConfigModal"
      :channel="alarmConfigChannel"
      @close="closeAlarmConfigModal"
      @save="saveAlarmConfig"
    />

    <!-- Correlation Rule Modal -->
    <CorrelationRuleModal
      :visible="showCorrelationRuleModal"
      :rule="editingCorrelationRule"
      @close="closeCorrelationRuleModal"
      @save="saveCorrelationRule"
    />
  </div>
</template>

<style scoped>
.safety-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* View-only notice banner */
.view-only-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: linear-gradient(90deg, #7f1d1d 0%, #451a03 100%);
  color: #fca5a5;
  font-size: 0.85rem;
  border-bottom: 1px solid #991b1b;
}

.view-only-notice .lock-icon {
  font-size: 0.9rem;
}

.view-only-notice .login-link {
  margin-left: auto;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid #f59e0b;
  border-radius: 4px;
  color: #f59e0b;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.view-only-notice .login-link:hover {
  background: #f59e0b;
  color: #000;
}

.safety-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.safety-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.alarm-summary {
  display: flex;
  gap: 16px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  border-radius: 6px;
  background: var(--bg-widget);
  min-width: 80px;
}

.summary-item .count {
  font-size: 1.5rem;
  font-weight: 700;
}

.summary-item .label {
  font-size: 0.7rem;
  color: #888;
  text-transform: uppercase;
}

.summary-item.alarm {
  border: 1px solid var(--color-error);
}
.summary-item.alarm .count {
  color: var(--color-error);
}
.summary-item.alarm.pulse {
  animation: pulse-alarm 1s infinite;
}

.summary-item.warning {
  border: 1px solid var(--color-warning);
}
.summary-item.warning .count {
  color: var(--color-warning);
}
.summary-item.warning.pulse {
  animation: pulse-warning 1s infinite;
}

.summary-item.acknowledged {
  border: 1px solid var(--color-accent);
}
.summary-item.acknowledged .count {
  color: var(--color-accent);
}

@keyframes pulse-alarm {
  0%, 100% { background: var(--bg-widget); }
  50% { background: #3f1515; }
}

@keyframes pulse-warning {
  0%, 100% { background: var(--bg-widget); }
  50% { background: #3f3515; }
}

.safety-content {
  display: grid;
  grid-template-columns: 350px 1fr 320px;
  gap: 16px;
  padding: 16px;
  flex: 1;
  overflow: hidden;
}

/* Active Alarms Panel */
.active-alarms-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.panel-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.no-alarms {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-success-light);
  gap: 8px;
}

.no-alarms p {
  margin: 0;
  font-size: 0.9rem;
}

.alarm-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.alarm-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--bg-widget);
  border-radius: 6px;
  margin-bottom: 8px;
  border-left: 3px solid;
}

.alarm-item.alarm {
  border-left-color: var(--color-error);
}
.alarm-item.alarm.active {
  background: linear-gradient(90deg, #3f1515 0%, var(--bg-widget) 50%);
}

.alarm-item.warning {
  border-left-color: var(--color-warning);
}
.alarm-item.warning.active {
  background: linear-gradient(90deg, #3f3515 0%, var(--bg-widget) 50%);
}

.alarm-item.acknowledged {
  opacity: 0.7;
}

.alarm-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.alarm-item.alarm .alarm-icon {
  color: var(--color-error);
}
.alarm-item.warning .alarm-icon {
  color: var(--color-warning);
}

.alarm-content {
  flex: 1;
  min-width: 0;
}

.alarm-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 0.85rem;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.alarm-tag {
  font-family: monospace;
  color: var(--color-accent-light);
  font-weight: 700;
}

.alarm-badge {
  font-size: 0.6rem;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  font-weight: 600;
}

.alarm-badge.alarm {
  background: var(--color-error);
  color: var(--text-primary);
}

.alarm-badge.warning {
  background: var(--color-warning);
  color: #000;
}

.alarm-badge.ack {
  background: var(--color-accent);
  color: var(--text-primary);
}

.alarm-message {
  font-size: 0.75rem;
  color: #aaa;
  margin-bottom: 6px;
}

.alarm-meta {
  display: flex;
  gap: 12px;
  font-size: 0.7rem;
  color: #666;
}

.alarm-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.btn {
  padding: 6px 12px;
  border: none;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-sm {
  padding: 4px 8px;
  font-size: 0.7rem;
}

.btn-xs {
  padding: 3px 6px;
  font-size: 0.65rem;
}

.btn-edit {
  background: var(--color-accent);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 3px;
}

.btn-edit:hover {
  background: var(--color-accent-dark);
}

.export-btn {
  display: flex;
  align-items: center;
  gap: 4px;
}

.export-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: var(--btn-secondary-hover);
}

.btn-ack {
  background: var(--color-accent);
  color: var(--text-primary);
}

.btn-ack:hover {
  background: var(--color-accent-dark);
}

.btn-reset {
  background: var(--color-error-dark);
  color: var(--text-primary);
  font-weight: 700;
}

.btn-reset:hover {
  background: #b91c1c;
}

.btn-clear {
  background: #6b7280;
  color: var(--text-primary);
}

.btn-clear:hover {
  background: var(--btn-secondary-hover);
}

/* Config Panel */
.config-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.config-table-container {
  flex: 1;
  overflow: auto;
}

.config-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.config-table th {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-widget);
  padding: 10px 8px;
  text-align: left;
  font-weight: 600;
  color: #888;
  font-size: 0.7rem;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border-color);
}

.config-table td {
  padding: 8px;
  border-bottom: 1px solid var(--bg-widget);
}

.config-table tr:hover {
  background: var(--bg-widget);
}

.config-table tr.selected {
  background: #1e3a5f;
}

.channel-name {
  display: flex;
  flex-direction: column;
}

.channel-name .tag {
  font-weight: 600;
  font-family: monospace;
  color: var(--color-accent-light);
}

.channel-name .unit {
  font-size: 0.65rem;
  color: #666;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch .slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--btn-secondary-bg);
  border-radius: 20px;
  transition: 0.2s;
}

.toggle-switch .slider:before {
  content: '';
  position: absolute;
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background: #fff;
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .slider {
  background: var(--color-success);
}

.toggle-switch input:checked + .slider:before {
  transform: translateX(16px);
}

.threshold-input {
  width: 70px;
  padding: 4px 6px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  text-align: right;
}

.threshold-input:disabled {
  opacity: 0.4;
}

.threshold-input.alarm {
  border-color: #7f1d1d;
}

.threshold-input.alarm:focus {
  border-color: var(--color-error);
  outline: none;
}

.threshold-input.warning {
  border-color: #78350f;
}

.threshold-input.warning:focus {
  border-color: var(--color-warning);
  outline: none;
}

.behavior-select {
  padding: 4px 6px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.75rem;
}

.behavior-select:disabled {
  opacity: 0.4;
}

.small-input {
  width: 50px;
  padding: 4px 6px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  text-align: right;
}

.small-input:disabled {
  opacity: 0.4;
}

.channel-actions {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-widget);
}

.channel-actions h4 {
  margin: 0 0 12px;
  font-size: 0.85rem;
  font-weight: 600;
}

.action-options {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: #ccc;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  accent-color: var(--color-accent);
}

/* Right Panel */
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
}

.health-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
}

.health-panel h3 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
}

.health-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
}

.health-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.health-item.ok .health-indicator {
  background: var(--color-success);
  box-shadow: 0 0 6px var(--color-success);
}

.health-item.warning .health-indicator {
  background: var(--color-warning);
  box-shadow: 0 0 6px var(--color-warning);
}

.health-item.error .health-indicator {
  background: var(--color-error);
  box-shadow: 0 0 6px var(--color-error);
}

.history-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.history-filters {
  display: flex;
  gap: 8px;
}

.filter-select {
  padding: 4px 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.7rem;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.history-item {
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 4px;
  margin-bottom: 4px;
  border-left: 2px solid;
  font-size: 0.75rem;
}

.history-item.alarm {
  border-left-color: var(--color-error);
}

.history-item.warning {
  border-left-color: var(--color-warning);
}

.history-time {
  color: #666;
  font-size: 0.65rem;
}

.history-channel {
  font-weight: 600;
  margin: 2px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}

.history-tag {
  font-family: monospace;
  color: var(--color-accent-light);
}

.history-message {
  color: #aaa;
  font-size: 0.7rem;
}

.history-duration {
  color: #888;
  font-size: 0.65rem;
  margin-top: 4px;
}

.no-history {
  text-align: center;
  color: #666;
  padding: 24px;
  font-size: 0.85rem;
}

/* ============================================
   Header Updates
   ============================================ */

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.node-filter {
  display: flex;
  align-items: center;
}

.node-select {
  background: var(--bg-widget);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 6px 10px;
  color: #ddd;
  font-size: 0.8rem;
  cursor: pointer;
}

.node-select:focus {
  outline: none;
  border-color: var(--color-accent);
}

.section-tabs {
  display: flex;
  gap: 4px;
}

.section-tab {
  padding: 8px 16px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #888;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.section-tab:hover {
  background: var(--bg-widget);
  color: #ccc;
}

.section-tab.active {
  background: #1e3a5f;
  color: var(--color-accent-light);
}

.latch-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

.latch-status.active {
  background: #7f1d1d;
  color: #fca5a5;
  cursor: pointer;
  animation: pulse-latch 1s infinite;
}

.latch-status.active:hover {
  background: #991b1b;
}

.latch-status .reset-hint {
  font-size: 0.65rem;
  opacity: 0.7;
  font-weight: 400;
}

.latch-status.clear {
  background: #14532d;
  color: #86efac;
}

@keyframes pulse-latch {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* ============================================
   Interlocks Section
   ============================================ */

.interlocks-content {
  display: grid;
  grid-template-columns: 1fr 350px;
  gap: 16px;
  padding: 16px;
  flex: 1;
  overflow: hidden;
}

.interlocks-status-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.no-interlocks {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #666;
  gap: 12px;
  padding: 40px;
}

.no-interlocks p {
  margin: 0;
}

.interlock-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.interlock-card {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}

.interlock-card.satisfied {
  border-left: 3px solid var(--color-success);
}

.interlock-card.blocked {
  border-left: 3px solid var(--color-error);
  background: linear-gradient(90deg, #3f1515 0%, var(--bg-widget) 30%);
}

.interlock-card.bypassed {
  border-left: 3px solid var(--color-warning);
  background: linear-gradient(90deg, #3f3515 0%, var(--bg-widget) 30%);
}

.interlock-card.disabled {
  opacity: 0.5;
  border-left: 3px solid #666;
}

.interlock-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.interlock-status-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.interlock-card.satisfied .interlock-status-icon,
.interlock-card.bypassed .interlock-status-icon {
  color: var(--color-success);
}

.interlock-card.blocked .interlock-status-icon {
  color: var(--color-error);
}

.interlock-name {
  flex: 1;
  font-weight: 600;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

.bypass-badge {
  font-size: 0.6rem;
  padding: 2px 6px;
  background: var(--color-warning);
  color: #000;
  border-radius: 3px;
  font-weight: 700;
}

.disabled-badge {
  font-size: 0.6rem;
  padding: 2px 6px;
  background: #666;
  color: var(--text-primary);
  border-radius: 3px;
  font-weight: 600;
}

.interlock-actions {
  display: flex;
  gap: 4px;
}

.interlock-description {
  font-size: 0.8rem;
  color: #9ca3af;
  margin-bottom: 10px;
  line-height: 1.4;
}

.interlock-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--color-warning);
  background: var(--color-warning-bg);
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 10px;
}

.interlock-conditions {
  margin-bottom: 8px;
}

.conditions-label,
.controls-label {
  font-size: 0.65rem;
  color: #666;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.condition-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  padding: 4px 0;
}

.condition-item.ok {
  color: #86efac;
}

.condition-item.failed {
  color: #fca5a5;
}

.condition-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.condition-text {
  flex: 1;
}

.condition-reason {
  font-size: 0.7rem;
  color: #888;
  font-style: italic;
}

.interlock-controls {
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.control-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.control-tag {
  font-size: 0.7rem;
  padding: 3px 8px;
  background: var(--btn-secondary-bg);
  border-radius: 3px;
  color: #ccc;
}

/* Blocked Actions Panel */
.blocked-actions-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.blocked-list {
  padding: 12px;
  flex: 1;
}

.blocked-item {
  padding: 12px;
  background: #3f1515;
  border: 1px solid #7f1d1d;
  border-radius: 6px;
  margin-bottom: 8px;
}

.blocked-action {
  font-weight: 600;
  font-size: 0.9rem;
  color: #fca5a5;
  margin-bottom: 4px;
}

.blocked-by {
  font-size: 0.75rem;
  color: #888;
}

.no-blocked {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-success-light);
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.no-blocked p {
  margin: 0;
  font-size: 0.9rem;
}

/* ============================================
   Interlock History Panel
   ============================================ */

.interlock-history-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  margin-top: 12px;
  max-height: 300px;
  display: flex;
  flex-direction: column;
}

.interlock-history-panel .panel-header {
  border-bottom: 1px solid var(--border-color);
}

.interlock-history-list {
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.interlock-history-item {
  padding: 8px 10px;
  background: var(--bg-widget);
  border-radius: 4px;
  margin-bottom: 6px;
  border-left: 3px solid #666;
}

.interlock-history-item.tripped {
  border-left-color: var(--color-error);
  background: linear-gradient(90deg, #3f1515 0%, var(--bg-widget) 30%);
}

.interlock-history-item.bypassed {
  border-left-color: var(--color-warning);
  background: linear-gradient(90deg, #3f3515 0%, var(--bg-widget) 30%);
}

.interlock-history-item.cleared,
.interlock-history-item.enabled {
  border-left-color: var(--color-success);
}

.interlock-history-item.disabled {
  border-left-color: #888;
}

.interlock-history-item.proof_test {
  border-left-color: var(--color-accent);
}

.interlock-history-item .history-time {
  font-size: 0.7rem;
  color: #666;
  margin-bottom: 4px;
}

.interlock-history-item .history-event {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
}

.interlock-history-item .event-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

.event-badge.tripped {
  background: #7f1d1d;
  color: #fca5a5;
}

.event-badge.bypassed {
  background: #78350f;
  color: #fcd34d;
}

.event-badge.bypass_removed,
.event-badge.bypass_expired {
  background: #3f3f46;
  color: #a1a1aa;
}

.event-badge.cleared,
.event-badge.enabled {
  background: #14532d;
  color: #86efac;
}

.event-badge.disabled {
  background: #3f3f46;
  color: #a1a1aa;
}

.event-badge.created,
.event-badge.modified {
  background: #1e3a5f;
  color: #93c5fd;
}

.event-badge.demand {
  background: #581c87;
  color: #d8b4fe;
}

.event-badge.proof_test {
  background: #1e40af;
  color: #93c5fd;
}

.interlock-history-item .interlock-name {
  color: var(--text-primary);
}

.interlock-history-item .history-reason {
  font-size: 0.75rem;
  color: #888;
  margin-top: 4px;
}

.interlock-history-item .history-user {
  font-size: 0.7rem;
  color: #666;
  margin-top: 2px;
}

.interlock-history-panel .no-history {
  padding: 20px;
  text-align: center;
  color: #666;
  font-size: 0.85rem;
}

/* ============================================
   Interlock Modal
   ============================================ */

.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay-light);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.modal {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
}

.modal h3 {
  margin: 0 0 16px;
  font-size: 1.1rem;
  color: var(--text-primary);
}

.interlock-modal {
  min-width: 550px;
  max-width: 650px;
  max-height: 85vh;
  overflow-y: auto;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 4px;
}

.form-group input[type="text"],
.form-group input[type="number"] {
  width: 100%;
  padding: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.85rem;
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.conditions-section,
.controls-section {
  margin: 16px 0;
  padding: 12px;
  background: var(--bg-primary);
  border-radius: 6px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-header h4 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
}

.condition-row,
.control-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.condition-type-select,
.control-type-select {
  flex: 1;
  min-width: 140px;
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
}

.condition-channel-select,
.control-channel-select,
.condition-operator-select,
.condition-bool-select {
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
}

.condition-channel-select,
.control-channel-select {
  min-width: 120px;
}

.condition-value-input {
  width: 80px;
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  text-align: right;
}

.control-value-select {
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  min-width: 80px;
}

.control-value-input {
  width: 80px;
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  text-align: right;
}

/* Expression input for custom condition logic */
.condition-expression-input {
  flex: 1;
  min-width: 200px;
  padding: 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
  font-family: 'Consolas', 'Monaco', monospace;
}

.condition-expression-input::placeholder {
  color: #666;
  font-style: italic;
}

/* Timer delay input styling */
.delay-input {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 0.75rem;
}

.delay-input label {
  color: #888;
  white-space: nowrap;
}

.delay-input .delay-value {
  width: 50px;
  padding: 4px 6px;
  background: var(--bg-input);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  color: var(--text-primary);
  font-size: 0.8rem;
  text-align: right;
}

.delay-input .delay-value:focus {
  border-color: var(--color-accent);
  outline: none;
}

.delay-input .unit {
  color: #666;
  font-size: 0.75rem;
}

/* Logic toggle (AND/OR) styling */
.logic-toggle {
  display: flex;
  gap: 12px;
  margin-left: auto;
}

.logic-toggle label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #ccc;
  font-size: 0.8rem;
  cursor: pointer;
}

.logic-toggle input[type="radio"] {
  accent-color: var(--color-accent);
}

/* SIL rating and proof test styles */
.form-group.half {
  flex: 1;
  min-width: 120px;
}

.form-group select,
.form-group input[type="number"] {
  width: 100%;
}

.empty-hint {
  color: #666;
  font-size: 0.8rem;
  font-style: italic;
  margin: 8px 0 0;
}

.modal-actions {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.modal-actions-right {
  display: flex;
  gap: 8px;
}

.btn-danger {
  background: var(--color-error-dark);
  color: var(--text-primary);
}

.btn-danger:hover {
  background: #b91c1c;
}

.btn-warning {
  background: var(--color-warning-dark);
  color: var(--text-primary);
}

.btn-warning:hover {
  background: #b45309;
}

.btn-primary {
  background: var(--color-accent);
  color: var(--text-primary);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ============================================
   Enhanced Safety System Styles
   ============================================ */

/* First-Out Indicator */
.first-out-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #7f1d1d;
  border: 1px solid var(--color-error);
  border-radius: 6px;
  color: #fca5a5;
  cursor: pointer;
  animation: pulse-first-out 1.5s infinite;
}

.first-out-indicator:hover {
  background: #991b1b;
}

.first-out-label {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--color-error);
}

.first-out-name {
  font-size: 0.8rem;
  font-weight: 600;
}

@keyframes pulse-first-out {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Critical severity */
.summary-item.critical {
  border: 2px solid var(--color-error-dark);
  background: linear-gradient(135deg, #7f1d1d 0%, var(--bg-widget) 100%);
}
.summary-item.critical .count {
  color: var(--color-error-light);
}
.summary-item.critical.pulse {
  animation: pulse-critical 0.5s infinite;
}

@keyframes pulse-critical {
  0%, 100% { background: linear-gradient(135deg, #7f1d1d 0%, var(--bg-widget) 100%); }
  50% { background: linear-gradient(135deg, #991b1b 0%, #2a1a2e 100%); }
}

/* Medium severity */
.summary-item.medium {
  border: 1px solid #f59e0b;
}
.summary-item.medium .count {
  color: #f59e0b;
}

/* Shelved summary */
.summary-item.shelved {
  border: 1px solid #6b7280;
}
.summary-item.shelved .count {
  color: #9ca3af;
}

/* First-out badge */
.first-out-badge {
  display: inline-block;
  padding: 2px 6px;
  background: var(--color-error-dark);
  color: var(--text-primary);
  font-size: 0.6rem;
  font-weight: 700;
  border-radius: 3px;
  animation: pulse-badge 1s infinite;
  margin-right: 4px;
}

@keyframes pulse-badge {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

/* Alarm item first-out highlight */
.alarm-item.first-out {
  border-left-width: 5px;
  box-shadow: 0 0 10px rgba(220, 38, 38, 0.3);
}

/* Alarm item highlight when scrolled to */
.alarm-item.highlight {
  animation: highlight-flash 0.5s ease-out 3;
}

@keyframes highlight-flash {
  0%, 100% { background: var(--bg-widget); }
  50% { background: #2a3a5e; }
}

/* Severity-specific alarm items */
.alarm-item.critical {
  border-left-color: var(--color-error-dark);
  background: linear-gradient(90deg, #450a0a 0%, var(--bg-widget) 40%);
}
.alarm-item.critical.active {
  animation: pulse-critical-item 1s infinite;
}

@keyframes pulse-critical-item {
  0%, 100% { background: linear-gradient(90deg, #450a0a 0%, var(--bg-widget) 40%); }
  50% { background: linear-gradient(90deg, #7f1d1d 0%, var(--bg-widget) 40%); }
}

.alarm-item.critical .alarm-icon {
  color: var(--color-error-light);
}

.alarm-item.medium {
  border-left-color: #f59e0b;
}
.alarm-item.medium.active {
  background: linear-gradient(90deg, #451a03 0%, var(--bg-widget) 40%);
}

/* Severity badges */
.alarm-badge.critical {
  background: var(--color-error-dark);
  color: var(--text-primary);
}

.alarm-badge.medium {
  background: #f59e0b;
  color: #000;
}

/* State badges */
.alarm-badge.returned {
  background: #6366f1;
  color: var(--text-primary);
}

.alarm-badge.shelved {
  background: #6b7280;
  color: var(--text-primary);
}

/* Shelve expiry text */
.shelve-expiry {
  color: #9ca3af;
  font-style: italic;
}

/* Button styles for shelve/unshelve */
.btn-shelve {
  background: #6b7280;
  color: var(--text-primary);
}
.btn-shelve:hover {
  background: var(--btn-secondary-hover);
}

.btn-unshelve {
  background: #6366f1;
  color: var(--text-primary);
}
.btn-unshelve:hover {
  background: #4f46e5;
}

/* Shelve Modal */
.shelve-modal {
  min-width: 400px;
  max-width: 450px;
}

.shelve-target {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-warning);
  margin: 0 0 16px;
  padding: 8px 12px;
  background: var(--bg-widget);
  border-radius: 4px;
  border-left: 3px solid var(--color-warning);
}

.form-select,
.form-input {
  width: 100%;
  padding: 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.form-select:focus,
.form-input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.shelve-warning {
  margin: 16px 0;
  padding: 10px 12px;
  background: #451a03;
  border: 1px solid var(--color-warning-dark);
  border-radius: 4px;
  font-size: 0.8rem;
  color: #fcd34d;
}

/* ============================================
   Tab Badge
   ============================================ */

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  margin-left: 6px;
  background: var(--color-accent);
  border-radius: 9px;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* ============================================
   Correlation Section
   ============================================ */

.correlation-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 16px;
  overflow: auto;
}

.correlation-panel,
.rules-panel {
  background: #111827;
  border: 1px solid var(--btn-secondary-bg);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.correlation-panel .panel-header,
.rules-panel .panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--btn-secondary-bg);
}

.count-badge {
  background: var(--btn-secondary-hover);
  color: #e5e7eb;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.75rem;
}

.no-correlations,
.no-rules {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #6b7280;
  text-align: center;
}

.no-correlations svg,
.no-rules svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.subtitle {
  font-size: 0.8rem;
  margin-top: 4px;
  color: #4b5563;
}

.correlation-list,
.rules-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.correlation-card,
.rule-card {
  background: #1f2937;
  border: 1px solid var(--btn-secondary-bg);
  border-radius: 6px;
  margin-bottom: 8px;
  padding: 12px;
}

.correlation-card:hover,
.rule-card:hover {
  border-color: var(--btn-secondary-hover);
}

.rule-card.disabled {
  opacity: 0.5;
}

.correlation-header,
.rule-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.correlation-id,
.rule-name {
  font-weight: 600;
  color: #e5e7eb;
}

.correlation-time {
  font-size: 0.75rem;
  color: #6b7280;
}

.rule-actions {
  display: flex;
  gap: 4px;
}

.correlation-body,
.rule-body {
  font-size: 0.85rem;
}

.root-cause,
.rule-trigger,
.related-alarms,
.rule-related {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}

.root-cause .label,
.rule-trigger .label,
.related-alarms .label,
.rule-related .label {
  color: #6b7280;
  min-width: 70px;
}

.alarm-tag {
  display: inline-block;
  background: var(--color-error-dark);
  color: var(--text-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: monospace;
}

.alarm-tag.secondary {
  background: var(--btn-secondary-hover);
  margin-right: 4px;
  margin-bottom: 4px;
}

.alarm-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.rule-meta {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 0.75rem;
  color: #6b7280;
}

.correlation-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--btn-secondary-bg);
}

.rule-id {
  font-size: 0.7rem;
  color: #4b5563;
  font-family: monospace;
}

.btn-icon {
  background: transparent;
  border: none;
  color: #6b7280;
  padding: 4px;
  cursor: pointer;
  border-radius: 4px;
}

.btn-icon:hover {
  background: var(--btn-secondary-bg);
  color: #e5e7eb;
}

.btn-icon.active {
  color: var(--color-success);
}

.btn-icon.danger:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

/* ============================================
   SOE Section
   ============================================ */

.soe-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  overflow: hidden;
}

.soe-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #111827;
  border: 1px solid var(--btn-secondary-bg);
  border-radius: 8px;
  padding: 12px 16px;
}

.soe-stats {
  display: flex;
  gap: 24px;
}

.stat-item {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: 600;
  color: #e5e7eb;
}

.stat-label {
  font-size: 0.7rem;
  color: #6b7280;
  text-transform: uppercase;
}

.soe-actions {
  display: flex;
  gap: 8px;
}

.soe-events-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #111827;
  border: 1px solid var(--btn-secondary-bg);
  border-radius: 8px;
  overflow: hidden;
}

.soe-events-panel .panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--btn-secondary-bg);
}

.soe-filters {
  display: flex;
  gap: 8px;
}

.filter-select {
  background: #1f2937;
  border: 1px solid var(--btn-secondary-bg);
  border-radius: 4px;
  padding: 6px 10px;
  color: #e5e7eb;
  font-size: 0.85rem;
}

.no-events {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: #6b7280;
  text-align: center;
}

.no-events svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.soe-table-wrapper {
  flex: 1;
  overflow: auto;
}

.soe-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.soe-table th {
  position: sticky;
  top: 0;
  background: #1f2937;
  padding: 10px 12px;
  text-align: left;
  font-weight: 500;
  color: #9ca3af;
  border-bottom: 1px solid var(--btn-secondary-bg);
}

.soe-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #1f2937;
  color: #e5e7eb;
}

.soe-table tr:hover {
  background: #1f2937;
}

.soe-table tr.row-alarm {
  background: var(--color-error-bg);
}

.soe-table tr.row-cleared {
  background: var(--color-success-bg);
}

.soe-table tr.row-ack {
  background: var(--color-accent-bg);
}

.timestamp-us {
  font-family: monospace;
  font-size: 0.7rem;
  color: #6b7280;
}

.timestamp-iso {
  font-family: monospace;
  white-space: nowrap;
}

.type-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 500;
}

.type-badge.alarm_triggered {
  background: #7f1d1d;
  color: #fca5a5;
}

.type-badge.alarm_cleared {
  background: #14532d;
  color: #86efac;
}

.type-badge.alarm_acknowledged {
  background: #1e3a8a;
  color: #93c5fd;
}

.type-badge.state_change {
  background: #4c1d95;
  color: #c4b5fd;
}

.type-badge.digital_edge {
  background: #164e63;
  color: #67e8f9;
}

.type-badge.setpoint_change {
  background: #713f12;
  color: #fde68a;
}

.channel {
  font-family: monospace;
  color: var(--color-accent-light);
}

.prev-value {
  font-size: 0.7rem;
  color: #6b7280;
}

.correlation-link {
  font-family: monospace;
  color: var(--color-accent);
  cursor: pointer;
  text-decoration: underline;
}

.correlation-link:hover {
  color: var(--color-accent-light);
}

.no-correlation {
  color: #4b5563;
}

.soe-footer {
  padding: 10px 16px;
  text-align: center;
  font-size: 0.8rem;
  color: #6b7280;
  border-top: 1px solid var(--btn-secondary-bg);
  background: #1f2937;
}

.btn-danger {
  background: #7f1d1d;
  color: #fca5a5;
  border: none;
}

.btn-danger:hover {
  background: #991b1b;
}
</style>
