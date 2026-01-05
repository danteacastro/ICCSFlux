<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'

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
const messages = ref<StatusMessage[]>([])
const isMinimized = ref(false)

// Track previous state for change detection
let prevAcquiring = false
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

  // Acquisition status
  if (status.acquiring !== prevAcquiring) {
    if (status.acquiring) {
      addMessage('success', 'DAQ', 'Acquisition started')
    } else {
      addMessage('info', 'DAQ', 'Acquisition stopped')
    }
    prevAcquiring = status.acquiring
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
watch(() => store.values, (values) => {
  Object.entries(values).forEach(([name, value]) => {
    const prev = prevAlarmState.get(name)
    const currentAlarm = !!value.alarm
    const currentWarning = !!value.warning

    if (!prev) {
      // First observation of this channel - just record state, don't log
      // This prevents logging alarms that were already active before page load
      prevAlarmState.set(name, { alarm: currentAlarm, warning: currentWarning, seen: true })
      return
    }

    // Only log when transitioning TO alarm (was false, now true)
    if (currentAlarm && !prev.alarm) {
      const config = store.channels[name]
      addMessage('error', name, `Alarm: ${value.value.toFixed(2)} ${config?.unit || ''}`)
    }
    // Only log when transitioning TO warning (was false, now true, and not in alarm)
    else if (currentWarning && !prev.warning && !currentAlarm) {
      const config = store.channels[name]
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

onMounted(() => {
  addMessage('info', 'System', 'Dashboard initialized')

  // Set initial states
  if (store.status) {
    prevAcquiring = store.status.acquiring
    prevRecording = store.status.recording
    prevConnected = store.status.status === 'online'
    prevSchedulerEnabled = store.status.scheduler_enabled
  }

  // Subscribe to alarms/cleared to clear stale alarm messages
  mqtt.subscribe('nisystem/nodes/+/alarms/cleared', () => {
    // Clear all error and warning messages (alarms) from the log
    messages.value = messages.value.filter(m => m.type !== 'error' && m.type !== 'warning')
    // Reset alarm state tracking so new alarms can be logged
    prevAlarmState.clear()
    addMessage('info', 'System', 'Alarms cleared')
  })

  // Also subscribe to project/loaded to clear the log when a new project loads
  mqtt.subscribe('nisystem/nodes/+/project/loaded', () => {
    messages.value = []
    // Reset alarm state tracking for the new project
    prevAlarmState.clear()
    addMessage('info', 'System', 'Project loaded')
  })
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
        <span>Status Log</span>
        <span v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</span>
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
  background: rgba(15, 15, 26, 0.95);
  backdrop-filter: blur(8px);
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  transition: all 0.2s ease;
}

.status-messages.minimized {
  max-height: 36px;
  width: 160px;
}

.status-messages.has-error {
  border-color: #ef4444;
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #2a2a4a;
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
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.title svg {
  color: #60a5fa;
}

.unread-badge {
  background: #ef4444;
  color: #fff;
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
  color: #666;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.action-btn:hover {
  background: #2a2a4a;
  color: #fff;
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
  background: #3a3a5a;
  border-radius: 2px;
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: rgba(30, 30, 50, 0.5);
  border-left: 2px solid transparent;
}

.message.info {
  border-left-color: #60a5fa;
}

.message.success {
  border-left-color: #22c55e;
}

.message.warning {
  border-left-color: #fbbf24;
  background: rgba(251, 191, 36, 0.1);
}

.message.error {
  border-left-color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.message .icon {
  font-size: 0.7rem;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}

.message.info .icon { color: #60a5fa; }
.message.success .icon { color: #22c55e; }
.message.warning .icon { color: #fbbf24; }
.message.error .icon { color: #ef4444; }

.message .time {
  color: #555;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.65rem;
  flex-shrink: 0;
}

.message .source {
  color: #888;
  font-weight: 600;
  flex-shrink: 0;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message .text {
  color: #ccc;
  flex: 1;
  word-break: break-word;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60px;
  color: #555;
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
</style>
