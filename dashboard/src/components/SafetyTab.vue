<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'
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
const soe = mqtt.soe  // SOE & Correlation composable

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

// Sync back to safety composable on changes
watch(alarmConfigs, (configs) => {
  Object.entries(configs).forEach(([channel, config]) => {
    safety.updateAlarmConfig(channel, config)
  })
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
})

// ============================================
// Alarm Actions (delegate to composable)
// ============================================

function acknowledgeAlarm(alarmId: string) {
  safety.acknowledgeAlarm(alarmId)
}

function acknowledgeAll() {
  safety.acknowledgeAll()
}

function clearAlarm(alarmId: string) {
  safety.clearAlarm(alarmId)
}

function clearAllAlarms() {
  safety.clearAllAlarms(true)  // Add to history when manually clearing
}

function resetAlarm(alarmId: string) {
  safety.resetAlarm(alarmId)
}

function resetAllLatched() {
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

function scrollToAlarm(alarmId: string | undefined) {
  if (!alarmId) return
  const el = document.getElementById(`alarm-${alarmId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('highlight')
    setTimeout(() => el.classList.remove('highlight'), 2000)
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
  if (!shelveTarget.value) return
  safety.shelveAlarm(shelveTarget.value.id, 'User', shelveReason.value, shelveDuration.value)
  showShelveModal.value = false
  shelveTarget.value = null
}

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
    daq_connected: store.status?.status === 'online',
    last_data_received: firstValue?.timestamp
      ? new Date(firstValue.timestamp).toISOString()
      : undefined,
    data_timeout: false // TODO: implement timeout detection
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
    })
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
  conditions: [] as InterlockCondition[],
  controls: [] as InterlockControl[]
})

// Condition types for dropdown
const conditionTypes: { value: InterlockConditionType; label: string; needsChannel: boolean; needsOperator: boolean }[] = [
  { value: 'mqtt_connected', label: 'MQTT Connected', needsChannel: false, needsOperator: false },
  { value: 'daq_connected', label: 'DAQ Online', needsChannel: false, needsOperator: false },
  { value: 'acquiring', label: 'System Acquiring', needsChannel: false, needsOperator: false },
  { value: 'not_recording', label: 'Not Recording', needsChannel: false, needsOperator: false },
  { value: 'no_active_alarms', label: 'No Active Alarms', needsChannel: false, needsOperator: false },
  { value: 'no_latched_alarms', label: 'No Latched Alarms', needsChannel: false, needsOperator: false },
  { value: 'channel_value', label: 'Channel Value', needsChannel: true, needsOperator: true },
  { value: 'digital_input', label: 'Digital Input', needsChannel: true, needsOperator: false }
]

const controlTypes: { value: InterlockControlType; label: string; needsChannel: boolean }[] = [
  { value: 'schedule_enable', label: 'Block Schedule Enable', needsChannel: false },
  { value: 'recording_start', label: 'Block Recording Start', needsChannel: false },
  { value: 'acquisition_start', label: 'Block Acquisition Start', needsChannel: false },
  { value: 'digital_output', label: 'Block Digital Output', needsChannel: true }
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

function openNewInterlockModal() {
  editingInterlock.value = null
  newInterlock.value = {
    name: '',
    description: '',
    bypassAllowed: true,
    conditions: [],
    controls: []
  }
  showInterlockModal.value = true
}

function openEditInterlockModal(interlockId: string) {
  const interlock = safety.interlocks.value.find(i => i.id === interlockId)
  if (!interlock) return

  // Store just the ID for reference
  editingInterlock.value = { id: interlockId } as Interlock
  newInterlock.value = {
    name: interlock.name,
    description: interlock.description || '',
    bypassAllowed: interlock.bypassAllowed,
    conditions: interlock.conditions.map(c => ({ ...c })),
    controls: interlock.controls.map(c => ({ ...c }))
  }
  showInterlockModal.value = true
}

function addCondition() {
  newInterlock.value.conditions.push({
    id: `cond-${Date.now()}`,
    type: 'mqtt_connected'
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

function saveInterlock() {
  if (!newInterlock.value.name.trim()) return
  if (newInterlock.value.conditions.length === 0) return
  if (newInterlock.value.controls.length === 0) return

  if (editingInterlock.value) {
    // Update existing
    safety.updateInterlock(editingInterlock.value.id, {
      name: newInterlock.value.name,
      description: newInterlock.value.description,
      bypassAllowed: newInterlock.value.bypassAllowed,
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
      bypassed: false,
      conditions: newInterlock.value.conditions,
      controls: newInterlock.value.controls
    })
  }

  showInterlockModal.value = false
}

function deleteInterlock(id: string) {
  if (confirm('Delete this interlock?')) {
    safety.removeInterlock(id)
  }
}

function toggleInterlockEnabled(id: string) {
  const interlock = safety.interlocks.value.find(i => i.id === id)
  if (interlock) {
    safety.updateInterlock(id, { enabled: !interlock.enabled })
  }
}

function toggleInterlockBypass(id: string) {
  const interlock = safety.interlocks.value.find(i => i.id === id)
  if (interlock) {
    safety.bypassInterlock(id, !interlock.bypassed)
  }
}

// Get human-readable condition description
function getConditionDescription(cond: InterlockCondition): string {
  const typeInfo = conditionTypes.find(t => t.value === cond.type)
  if (!typeInfo) return 'Unknown condition'

  if (cond.type === 'channel_value' && cond.channel) {
    return `${cond.channel} ${cond.operator} ${cond.value}`
  }

  if (cond.type === 'digital_input' && cond.channel) {
    return `${cond.channel} = ${cond.value ? 'ON' : 'OFF'}`
  }

  return typeInfo.label
}

// Get human-readable control description
function getControlDescription(ctrl: InterlockControl): string {
  const typeInfo = controlTypes.find(t => t.value === ctrl.type)
  if (!typeInfo) return 'Unknown control'

  if (ctrl.type === 'digital_output' && ctrl.channel) {
    return `Block ${ctrl.channel}`
  }

  return typeInfo.label
}
</script>

<template>
  <div class="safety-tab">
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
              v-if="activeAlarms.length > 0"
              class="btn btn-sm btn-secondary"
              @click="acknowledgeAll"
            >
              Acknowledge All
            </button>
            <button
              v-if="activeAlarms.length > 0"
              class="btn btn-sm btn-danger"
              @click="clearAllAlarms"
              title="Clear all alarms (use when project changes or to reset alarm state)"
            >
              Clear All
            </button>
          </div>
        </div>

        <div v-if="activeAlarms.length === 0" class="no-alarms">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <p>No active alarms</p>
        </div>

        <div v-else class="alarm-list">
          <div
            v-for="alarm in activeAlarms"
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
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="ch in channelList"
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
          <button class="btn btn-sm btn-primary" @click="showNewRuleModal = true">
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

          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="newInterlock.bypassAllowed" />
              Allow operator bypass
            </label>
          </div>

          <!-- Conditions -->
          <div class="conditions-section">
            <div class="section-header">
              <h4>Conditions (ALL must be true)</h4>
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

              <!-- Channel select for digital_output -->
              <select
                v-if="ctrl.type === 'digital_output'"
                v-model="ctrl.channel"
                class="control-channel-select"
              >
                <option value="">Select output...</option>
                <option v-for="ch in digitalOutputChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }}
                </option>
              </select>

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
  </div>
</template>

<style scoped>
.safety-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0a0a14;
  color: #fff;
}

.safety-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
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
  background: #1a1a2e;
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
  border: 1px solid #ef4444;
}
.summary-item.alarm .count {
  color: #ef4444;
}
.summary-item.alarm.pulse {
  animation: pulse-alarm 1s infinite;
}

.summary-item.warning {
  border: 1px solid #fbbf24;
}
.summary-item.warning .count {
  color: #fbbf24;
}
.summary-item.warning.pulse {
  animation: pulse-warning 1s infinite;
}

.summary-item.acknowledged {
  border: 1px solid #3b82f6;
}
.summary-item.acknowledged .count {
  color: #3b82f6;
}

@keyframes pulse-alarm {
  0%, 100% { background: #1a1a2e; }
  50% { background: #3f1515; }
}

@keyframes pulse-warning {
  0%, 100% { background: #1a1a2e; }
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
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  border-bottom: 1px solid #2a2a4a;
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
  color: #4ade80;
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
  background: #1a1a2e;
  border-radius: 6px;
  margin-bottom: 8px;
  border-left: 3px solid;
}

.alarm-item.alarm {
  border-left-color: #ef4444;
}
.alarm-item.alarm.active {
  background: linear-gradient(90deg, #3f1515 0%, #1a1a2e 50%);
}

.alarm-item.warning {
  border-left-color: #fbbf24;
}
.alarm-item.warning.active {
  background: linear-gradient(90deg, #3f3515 0%, #1a1a2e 50%);
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
  color: #ef4444;
}
.alarm-item.warning .alarm-icon {
  color: #fbbf24;
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
  color: #60a5fa;
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
  background: #ef4444;
  color: #fff;
}

.alarm-badge.warning {
  background: #fbbf24;
  color: #000;
}

.alarm-badge.ack {
  background: #3b82f6;
  color: #fff;
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

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover {
  background: #4b5563;
}

.btn-ack {
  background: #3b82f6;
  color: #fff;
}

.btn-ack:hover {
  background: #2563eb;
}

.btn-reset {
  background: #dc2626;
  color: #fff;
  font-weight: 700;
}

.btn-reset:hover {
  background: #b91c1c;
}

.btn-clear {
  background: #6b7280;
  color: #fff;
}

.btn-clear:hover {
  background: #4b5563;
}

/* Config Panel */
.config-panel {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  background: #1a1a2e;
  padding: 10px 8px;
  text-align: left;
  font-weight: 600;
  color: #888;
  font-size: 0.7rem;
  text-transform: uppercase;
  border-bottom: 1px solid #2a2a4a;
}

.config-table td {
  padding: 8px;
  border-bottom: 1px solid #1a1a2e;
}

.config-table tr:hover {
  background: #1a1a2e;
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
  color: #60a5fa;
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
  background: #374151;
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
  background: #22c55e;
}

.toggle-switch input:checked + .slider:before {
  transform: translateX(16px);
}

.threshold-input {
  width: 70px;
  padding: 4px 6px;
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
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
  border-color: #ef4444;
  outline: none;
}

.threshold-input.warning {
  border-color: #78350f;
}

.threshold-input.warning:focus {
  border-color: #fbbf24;
  outline: none;
}

.behavior-select {
  padding: 4px 6px;
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.75rem;
}

.behavior-select:disabled {
  opacity: 0.4;
}

.small-input {
  width: 50px;
  padding: 4px 6px;
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
  text-align: right;
}

.small-input:disabled {
  opacity: 0.4;
}

.channel-actions {
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
  background: #1a1a2e;
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
  accent-color: #3b82f6;
}

/* Right Panel */
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
}

.health-panel {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  background: #22c55e;
  box-shadow: 0 0 6px #22c55e;
}

.health-item.warning .health-indicator {
  background: #fbbf24;
  box-shadow: 0 0 6px #fbbf24;
}

.health-item.error .health-indicator {
  background: #ef4444;
  box-shadow: 0 0 6px #ef4444;
}

.history-panel {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.7rem;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.history-item {
  padding: 8px;
  background: #1a1a2e;
  border-radius: 4px;
  margin-bottom: 4px;
  border-left: 2px solid;
  font-size: 0.75rem;
}

.history-item.alarm {
  border-left-color: #ef4444;
}

.history-item.warning {
  border-left-color: #fbbf24;
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
  color: #60a5fa;
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
  background: #1a1a2e;
  color: #ccc;
}

.section-tab.active {
  background: #1e3a5f;
  color: #60a5fa;
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
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}

.interlock-card.satisfied {
  border-left: 3px solid #22c55e;
}

.interlock-card.blocked {
  border-left: 3px solid #ef4444;
  background: linear-gradient(90deg, #3f1515 0%, #1a1a2e 30%);
}

.interlock-card.bypassed {
  border-left: 3px solid #fbbf24;
  background: linear-gradient(90deg, #3f3515 0%, #1a1a2e 30%);
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
  color: #22c55e;
}

.interlock-card.blocked .interlock-status-icon {
  color: #ef4444;
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
  background: #fbbf24;
  color: #000;
  border-radius: 3px;
  font-weight: 700;
}

.disabled-badge {
  font-size: 0.6rem;
  padding: 2px 6px;
  background: #666;
  color: #fff;
  border-radius: 3px;
  font-weight: 600;
}

.interlock-actions {
  display: flex;
  gap: 4px;
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
  border-top: 1px solid #2a2a4a;
}

.control-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.control-tag {
  font-size: 0.7rem;
  padding: 3px 8px;
  background: #374151;
  border-radius: 3px;
  color: #ccc;
}

/* Blocked Actions Panel */
.blocked-actions-panel {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
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
  color: #4ade80;
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.no-blocked p {
  margin: 0;
  font-size: 0.9rem;
}

/* ============================================
   Interlock Modal
   ============================================ */

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.modal {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 20px;
}

.modal h3 {
  margin: 0 0 16px;
  font-size: 1.1rem;
  color: #fff;
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
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
}

.form-group input:focus {
  outline: none;
  border-color: #3b82f6;
}

.conditions-section,
.controls-section {
  margin: 16px 0;
  padding: 12px;
  background: #0a0a14;
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
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
}

.condition-channel-select,
.control-channel-select,
.condition-operator-select,
.condition-bool-select {
  padding: 6px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
}

.condition-channel-select,
.control-channel-select {
  min-width: 120px;
}

.condition-value-input {
  width: 80px;
  padding: 6px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
  text-align: right;
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
  border-top: 1px solid #2a2a4a;
}

.modal-actions-right {
  display: flex;
  gap: 8px;
}

.btn-danger {
  background: #dc2626;
  color: #fff;
}

.btn-danger:hover {
  background: #b91c1c;
}

.btn-warning {
  background: #d97706;
  color: #fff;
}

.btn-warning:hover {
  background: #b45309;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
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
  border: 1px solid #ef4444;
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
  color: #ef4444;
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
  border: 2px solid #dc2626;
  background: linear-gradient(135deg, #7f1d1d 0%, #1a1a2e 100%);
}
.summary-item.critical .count {
  color: #f87171;
}
.summary-item.critical.pulse {
  animation: pulse-critical 0.5s infinite;
}

@keyframes pulse-critical {
  0%, 100% { background: linear-gradient(135deg, #7f1d1d 0%, #1a1a2e 100%); }
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
  background: #dc2626;
  color: #fff;
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
  0%, 100% { background: #1a1a2e; }
  50% { background: #2a3a5e; }
}

/* Severity-specific alarm items */
.alarm-item.critical {
  border-left-color: #dc2626;
  background: linear-gradient(90deg, #450a0a 0%, #1a1a2e 40%);
}
.alarm-item.critical.active {
  animation: pulse-critical-item 1s infinite;
}

@keyframes pulse-critical-item {
  0%, 100% { background: linear-gradient(90deg, #450a0a 0%, #1a1a2e 40%); }
  50% { background: linear-gradient(90deg, #7f1d1d 0%, #1a1a2e 40%); }
}

.alarm-item.critical .alarm-icon {
  color: #f87171;
}

.alarm-item.medium {
  border-left-color: #f59e0b;
}
.alarm-item.medium.active {
  background: linear-gradient(90deg, #451a03 0%, #1a1a2e 40%);
}

/* Severity badges */
.alarm-badge.critical {
  background: #dc2626;
  color: #fff;
}

.alarm-badge.medium {
  background: #f59e0b;
  color: #000;
}

/* State badges */
.alarm-badge.returned {
  background: #6366f1;
  color: #fff;
}

.alarm-badge.shelved {
  background: #6b7280;
  color: #fff;
}

/* Shelve expiry text */
.shelve-expiry {
  color: #9ca3af;
  font-style: italic;
}

/* Button styles for shelve/unshelve */
.btn-shelve {
  background: #6b7280;
  color: #fff;
}
.btn-shelve:hover {
  background: #4b5563;
}

.btn-unshelve {
  background: #6366f1;
  color: #fff;
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
  color: #fbbf24;
  margin: 0 0 16px;
  padding: 8px 12px;
  background: #1a1a2e;
  border-radius: 4px;
  border-left: 3px solid #fbbf24;
}

.form-select,
.form-input {
  width: 100%;
  padding: 10px;
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.9rem;
}

.form-select:focus,
.form-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.shelve-warning {
  margin: 16px 0;
  padding: 10px 12px;
  background: #451a03;
  border: 1px solid #d97706;
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
  background: #3b82f6;
  border-radius: 9px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #fff;
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
  border: 1px solid #374151;
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
  border-bottom: 1px solid #374151;
}

.count-badge {
  background: #4b5563;
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
  border: 1px solid #374151;
  border-radius: 6px;
  margin-bottom: 8px;
  padding: 12px;
}

.correlation-card:hover,
.rule-card:hover {
  border-color: #4b5563;
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
  background: #dc2626;
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: monospace;
}

.alarm-tag.secondary {
  background: #4b5563;
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
  border-top: 1px solid #374151;
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
  background: #374151;
  color: #e5e7eb;
}

.btn-icon.active {
  color: #22c55e;
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
  border: 1px solid #374151;
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
  border: 1px solid #374151;
  border-radius: 8px;
  overflow: hidden;
}

.soe-events-panel .panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #374151;
}

.soe-filters {
  display: flex;
  gap: 8px;
}

.filter-select {
  background: #1f2937;
  border: 1px solid #374151;
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
  border-bottom: 1px solid #374151;
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
  background: rgba(220, 38, 38, 0.1);
}

.soe-table tr.row-cleared {
  background: rgba(34, 197, 94, 0.1);
}

.soe-table tr.row-ack {
  background: rgba(59, 130, 246, 0.1);
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
  color: #60a5fa;
}

.prev-value {
  font-size: 0.7rem;
  color: #6b7280;
}

.correlation-link {
  font-family: monospace;
  color: #3b82f6;
  cursor: pointer;
  text-decoration: underline;
}

.correlation-link:hover {
  color: #60a5fa;
}

.no-correlation {
  color: #4b5563;
}

.soe-footer {
  padding: 10px 16px;
  text-align: center;
  font-size: 0.8rem;
  color: #6b7280;
  border-top: 1px solid #374151;
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
