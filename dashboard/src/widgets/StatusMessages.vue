<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'

export interface StatusMessage {
  id: string
  timestamp: Date
  type: 'info' | 'success' | 'warning' | 'error'
  source: string
  message: string
}

defineProps<{
  maxMessages?: number
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()
const messages = ref<StatusMessage[]>([])
const isMinimized = ref(false)
const unsubscribeFns: (() => void)[] = []

// Track previous state for change detection
let prevAcquisitionState = 'stopped'
let prevRecording = false
let prevConnected = false
let prevSchedulerEnabled = false

// Track previous alarm/warning state per channel to only log TRANSITIONS
// Key: channel name, Value: { alarm: boolean, warning: boolean, seen: boolean }
// 'seen' flag prevents logging on first observation (initial state after page load)
const prevAlarmState = new Map<string, { alarm: boolean; warning: boolean; seen: boolean }>()

function addMessage(type: StatusMessage['type'], source: string, message: string) {
  const newMessage: StatusMessage = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    timestamp: new Date(),
    type,
    source,
    message
  }

  messages.value.unshift(newMessage)

  // Limit to max messages
  if (messages.value.length > 100) {
    messages.value = messages.value.slice(0, 100)
  }
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function clearMessages() {
  messages.value = []
  addMessage('info', 'System', 'Log cleared')
}

function toggleMinimize() {
  isMinimized.value = !isMinimized.value
}

// Watch for status changes
watch(() => store.status, (status) => {
  if (!status) return

  // Connection status
  const connected = status.status === 'online'
  if (connected !== prevConnected) {
    if (connected) {
      addMessage('success', 'MQTT', 'Connected to broker')
    } else {
      addMessage('error', 'MQTT', 'Disconnected from broker')
    }
    prevConnected = connected
  }

  // Acquisition status - track detailed state transitions
  const acquisitionState = status.acquisition_state || (status.acquiring ? 'running' : 'stopped')
  if (acquisitionState !== prevAcquisitionState) {
    if (acquisitionState === 'initializing') {
      addMessage('info', 'DAQ', 'Initializing acquisition...')
    } else if (acquisitionState === 'running') {
      addMessage('success', 'DAQ', 'Acquisition running')
    } else if (acquisitionState === 'stopped') {
      // Only show stopped message if we were previously running or initializing
      if (prevAcquisitionState === 'running' || prevAcquisitionState === 'initializing') {
        addMessage('info', 'DAQ', 'Acquisition stopped')
      }
    }
    prevAcquisitionState = acquisitionState
  }
  // Recording status
  if (status.recording !== prevRecording) {
    if (status.recording) {
      addMessage('success', 'Recording', `Started recording: ${status.recording_filename || 'data file'}`)
    } else {
      addMessage('info', 'Recording', 'Recording stopped')
    }
    prevRecording = status.recording
  }

  // Scheduler status
  if (status.scheduler_enabled !== prevSchedulerEnabled) {
    if (status.scheduler_enabled) {
      addMessage('info', 'Scheduler', 'Scheduler enabled')
    } else {
      addMessage('info', 'Scheduler', 'Scheduler disabled')
    }
    prevSchedulerEnabled = status.scheduler_enabled
  }
}, { deep: true })

// Watch for channel alarms - only log TRANSITIONS (not initial state on page load)
// IMPORTANT: We must wait for channel config to be loaded before tracking alarm state.
// Otherwise, the first values arrive with alarm=false (no config), then when config loads,
// the next update shows alarm=true, which appears as a false "transition".
watch(() => store.values, (values) => {
  Object.entries(values).forEach(([name, value]) => {
    const prev = prevAlarmState.get(name)
    const currentAlarm = !!value.alarm
    const currentWarning = !!value.warning

    // Check if this channel has alarm config (limits defined)
    // Use != null to check both undefined AND null
    const config = store.channels[name]
    const hasAlarmConfig = config && (
      config.low_limit != null ||
      config.high_limit != null ||
      config.low_warning != null ||
      config.high_warning != null ||
      config.hihi_limit != null ||
      config.lolo_limit != null ||
      config.hi_limit != null ||
      config.lo_limit != null
    )

    if (!prev) {
      // First observation of this channel
      if (!hasAlarmConfig) {
        // Channel has no alarm config yet - don't record state
        // This prevents false transitions when config loads later
        return
      }
      // Channel has config - record initial state without logging
      prevAlarmState.set(name, { alarm: currentAlarm, warning: currentWarning, seen: true })
      return
    }

    // If we previously recorded state without config, but now have config,
    // update our baseline without logging (avoid false transition)
    if (!prev.seen && hasAlarmConfig) {
      prevAlarmState.set(name, { alarm: currentAlarm, warning: currentWarning, seen: true })
      return
    }

    // Skip all alarm notifications if no limits are configured
    // This is a safeguard in case value.alarm is incorrectly set
    if (!hasAlarmConfig) {
      prevAlarmState.set(name, { alarm: false, warning: false, seen: true })
      return
    }

    // Only log when transitioning TO alarm (was false, now true)
    if (currentAlarm && !prev.alarm) {
      addMessage('error', name, `Alarm: ${value.value.toFixed(2)} ${config?.unit || ''}`)
    }
    // Only log when transitioning TO warning (was false, now true, and not in alarm)
    else if (currentWarning && !prev.warning && !currentAlarm) {
      addMessage('warning', name, `Warning: ${value.value.toFixed(2)} ${config?.unit || ''}`)
    }
    // Log when alarm clears (was in alarm, now not)
    else if (!currentAlarm && prev.alarm) {
      addMessage('success', name, 'Alarm cleared')
    }

    // Update previous state
    prevAlarmState.set(name, { alarm: currentAlarm, warning: currentWarning, seen: true })
  })
}, { deep: true })

// Watch for channel config changes (new project loaded)
// When channels change, reset our alarm tracking to avoid false transitions
watch(() => Object.keys(store.channels).length, (newCount, oldCount) => {
  if (newCount !== oldCount) {
    // Channel set has changed - reset alarm state
    // This handles project load/close without relying solely on MQTT messages
    prevAlarmState.clear()
  }
})

onMounted(() => {
  addMessage('info', 'System', 'Dashboard initialized')

  // Set initial states
  if (store.status) {
    prevAcquisitionState = store.status.acquisition_state || (store.status.acquiring ? 'running' : 'stopped')
    prevRecording = store.status.recording
    prevConnected = store.status.status === 'online'
    prevSchedulerEnabled = store.status.scheduler_enabled
  }

  // Subscribe to alarms/cleared to clear stale alarm messages
  unsubscribeFns.push(mqtt.subscribe('nisystem/nodes/+/alarms/cleared', () => {
    // Clear all error and warning messages (alarms) from the log
    messages.value = messages.value.filter(m => m.type !== 'error' && m.type !== 'warning')
    // Reset alarm state tracking so new alarms can be logged
    prevAlarmState.clear()
    addMessage('info', 'System', 'Alarms cleared')
  }))

  // Also subscribe to project/loaded to clear the log when a new project loads
  unsubscribeFns.push(mqtt.subscribe('nisystem/nodes/+/project/loaded', () => {
    messages.value = []
    // Reset alarm state tracking for the new project
    prevAlarmState.clear()
    addMessage('info', 'System', 'Project loaded')
  }))
})

onUnmounted(() => {
  unsubscribeFns.forEach(fn => fn())
})

const messageTypeIcon = {
  info: 'ℹ',
  success: '✓',
  warning: '⚠',
  error: '✕'
}

const unreadCount = computed(() => {
  if (!isMinimized.value) return 0
  // Count messages from last 30 seconds when minimized
  const thirtySecondsAgo = Date.now() - 30000
  return messages.value.filter(m => m.timestamp.getTime() > thirtySecondsAgo).length
})

const hasError = computed(() => {
  const fiveSecondsAgo = Date.now() - 5000
  return messages.value.some(m => m.type === 'error' && m.timestamp.getTime() > fiveSecondsAgo)
})
</script>

<template>
  <div class="status-messages" :class="{ minimized: isMinimized, 'has-error': hasError }">
    <div class="header" @click="toggleMinimize">
      <div class="title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
        <span v-if="!isMinimized">Status Log</span>
        <span v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</span>
      </div>

      <!-- Status Indicators (hidden when minimized) -->
      <div v-if="!isMinimized" class="status-group" @click.stop>
        <!-- Safety Status -->
        <div
          v-if="safety.hasLatchedAlarms.value"
          class="safety-indicator latched"
          @click="safety.resetAllLatched()"
          title="Click to reset all latched alarms"
        >
          {{ safety.latchedAlarmCount.value }} LATCHED
        </div>
        <div
          v-if="safety.interlockStatuses.value.some(s => !s.satisfied && s.enabled && !s.bypassed)"
          class="safety-indicator blocked"
          title="Some interlocks are blocking actions"
        >
          {{ safety.interlockStatuses.value.filter(s => !s.satisfied && s.enabled && !s.bypassed).length }} BLOCKED
        </div>
        <div
          v-if="safety.hasActiveAlarms.value"
          class="safety-indicator alarm"
        >
          {{ safety.alarmCounts.value.active }} ALARM
        </div>
        <div
          v-if="!safety.hasLatchedAlarms.value &&
                !safety.hasActiveAlarms.value &&
                !safety.interlockStatuses.value.some(s => !s.satisfied && s.enabled && !s.bypassed)"
          class="safety-indicator clear"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M9 12l2 2 4-4"/>
          </svg>
          OK
        </div>

        <!-- Service Status -->
        <div class="status-item" :class="{ active: mqtt.connected.value, error: !mqtt.connected.value }" title="MQTT Connection">
          <span class="dot"></span><span class="label">MQ</span>
        </div>
        <div class="status-item" :class="{ active: store.isConnected, error: !store.isConnected }" title="DAQ Service">
          <span class="dot"></span><span class="label">DAQ</span>
        </div>
        <div class="status-item" :class="{ active: store.isAcquiring, inactive: !store.isAcquiring }" title="Acquisition">
          <span class="dot"></span><span class="label">ACQ</span>
        </div>
        <div v-if="store.status?.simulation_mode" class="status-badge sim" title="Simulation Mode">SIM</div>
      </div>

      <div class="header-actions">
        <button v-if="!isMinimized" class="action-btn" @click.stop="clearMessages" title="Clear log">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
          </svg>
        </button>
        <button class="action-btn minimize-btn" :title="isMinimized ? 'Expand' : 'Minimize'">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline v-if="isMinimized" points="18 15 12 9 6 15"/>
            <polyline v-else points="6 9 12 15 18 9"/>
          </svg>
        </button>
      </div>
    </div>

    <div v-if="!isMinimized" class="messages-container">
      <TransitionGroup name="message">
        <div
          v-for="msg in messages.slice(0, maxMessages || 50)"
          :key="msg.id"
          class="message"
          :class="msg.type"
        >
          <span class="icon">{{ messageTypeIcon[msg.type] }}</span>
          <span class="time">{{ formatTime(msg.timestamp) }}</span>
          <span class="source">{{ msg.source }}</span>
          <span class="text">{{ msg.message }}</span>
        </div>
      </TransitionGroup>

      <div v-if="messages.length === 0" class="empty-state">
        No messages yet
      </div>
    </div>
  </div>
</template>

<style scoped>
.status-messages {
  position: fixed;
  bottom: 16px;
  right: 16px;
  width: 380px;
  max-height: 280px;
  background: var(--bg-panel);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  transition: all 0.2s ease;
}

.status-messages.minimized {
  max-height: 36px;
  width: auto;
}

.status-messages.has-error {
  border-color: var(--color-error);
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  user-select: none;
}

.minimized .header {
  border-bottom: none;
}

.title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.title svg {
  color: var(--color-accent-light);
}

.unread-badge {
  background: var(--color-error);
  color: var(--text-primary);
  font-size: 0.65rem;
  padding: 1px 5px;
  border-radius: 8px;
  font-weight: 700;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.action-btn:hover {
  background: var(--border-color);
  color: var(--text-primary);
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.messages-container::-webkit-scrollbar {
  width: 4px;
}

.messages-container::-webkit-scrollbar-track {
  background: transparent;
}

.messages-container::-webkit-scrollbar-thumb {
  background: var(--border-light);
  border-radius: 2px;
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: var(--bg-panel-row);
  border-left: 2px solid transparent;
}

.message.info {
  border-left-color: var(--color-accent-light);
}

.message.success {
  border-left-color: var(--color-success);
}

.message.warning {
  border-left-color: var(--color-warning);
  background: var(--color-warning-bg);
}

.message.error {
  border-left-color: var(--color-error);
  background: var(--color-error-bg);
}

.message .icon {
  font-size: 0.7rem;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}

.message.info .icon { color: var(--color-accent-light); }
.message.success .icon { color: var(--color-success); }
.message.warning .icon { color: var(--color-warning); }
.message.error .icon { color: var(--color-error); }

.message .time {
  color: var(--text-dim);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.65rem;
  flex-shrink: 0;
}

.message .source {
  color: var(--text-secondary);
  font-weight: 600;
  flex-shrink: 0;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message .text {
  color: var(--text-bright);
  flex: 1;
  word-break: break-word;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60px;
  color: var(--text-dim);
  font-size: 0.8rem;
}

/* Transition animations */
.message-enter-active {
  transition: all 0.2s ease-out;
}

.message-leave-active {
  transition: all 0.15s ease-in;
}

.message-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.message-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.message-move {
  transition: transform 0.2s ease;
}

/* Service Status Indicators */
.status-group {
  display: flex;
  gap: 4px;
  margin-left: auto;
  margin-right: 8px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 0.55rem;
  font-weight: 600;
  color: var(--text-muted);
  padding: 2px 4px;
  background: var(--bg-status-pill);
  border-radius: 3px;
}

.status-item .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-dim);
}

.status-item.active {
  color: var(--indicator-success-text);
}
.status-item.active .dot {
  background: var(--color-success);
  box-shadow: 0 0 4px var(--color-success);
}

.status-item.error {
  color: var(--indicator-danger-text);
}
.status-item.error .dot {
  background: var(--color-error);
}

.status-item.inactive {
  color: var(--text-dim);
}
.status-item.inactive .dot {
  background: var(--text-disabled);
}

.status-item .label {
  text-transform: uppercase;
}

.status-badge {
  font-size: 0.5rem;
  font-weight: 700;
  padding: 2px 4px;
  border-radius: 2px;
}

.status-badge.sim {
  color: var(--color-warning);
  background: var(--indicator-sim-bg);
}

/* Safety Status Indicators */
.safety-indicator {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 5px;
  border-radius: 3px;
  font-size: 0.5rem;
  font-weight: 700;
}

.safety-indicator.latched {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
  cursor: pointer;
  animation: pulse-safety 1s infinite;
}

.safety-indicator.latched:hover {
  background: var(--indicator-danger-bg); filter: brightness(1.2);
}

.safety-indicator.blocked {
  background: var(--indicator-warning-bg);
  color: var(--color-warning);
}

.safety-indicator.alarm {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
  animation: pulse-safety 1s infinite;
}

.safety-indicator.clear {
  background: var(--indicator-success-bg);
  color: var(--indicator-success-text);
}

@keyframes pulse-safety {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
