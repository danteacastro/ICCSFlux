<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'

const safety = useSafety()

defineProps<{
  showEditControls?: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'stop'): void
  (e: 'record-start'): void
  (e: 'record-stop'): void
  (e: 'schedule-enable'): void
  (e: 'schedule-disable'): void
  (e: 'add-widget'): void
}>()

const store = useDashboardStore()

// Recording timer display
const recordingTime = computed(() => {
  // Use recording_duration_seconds if available, otherwise try to parse recording_duration string
  if (store.status?.recording_duration_seconds !== undefined) {
    const secs = Math.floor(store.status.recording_duration_seconds)
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    const s = secs % 60
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  // Fallback to string format if already formatted
  if (store.status?.recording_duration) {
    return store.status.recording_duration
  }
  return '00:00:00'
})
</script>

<template>
  <div class="control-bar">
    <div class="control-group">
      <!-- Start/Stop -->
      <button
        v-if="!store.isAcquiring"
        class="btn btn-start"
        @click="emit('start')"
        :disabled="!store.isConnected"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5,3 19,12 5,21"/>
        </svg>
        START
      </button>
      <button
        v-else
        class="btn btn-stop"
        @click="emit('stop')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <rect x="4" y="4" width="16" height="16"/>
        </svg>
        STOP
      </button>

      <!-- Record -->
      <button
        v-if="!store.isRecording"
        class="btn btn-record"
        @click="emit('record-start')"
        :disabled="!store.isAcquiring"
        :class="{ disabled: !store.isAcquiring }"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="8"/>
        </svg>
        RECORD
      </button>
      <button
        v-else
        class="btn btn-record recording"
        @click="emit('record-stop')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="8"/>
        </svg>
        {{ recordingTime }}
      </button>
    </div>


    <!-- Scheduler toggle - only show when scheduler is enabled -->
    <div v-if="store.isSchedulerEnabled" class="control-group">
      <div class="scheduler-toggle">
        <span class="label">SCHEDULE</span>
        <button
          class="toggle-btn on"
          @click="emit('schedule-disable')"
        >
          <span class="slider"></span>
        </button>
      </div>
    </div>

    <div v-if="showEditControls" class="control-group edit-group">
      <!-- Add Widget (only in edit mode) -->
      <button
        v-if="store.editMode"
        class="btn btn-add"
        @click="emit('add-widget')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        ADD WIDGET
      </button>

      <!-- Edit mode toggle -->
      <button
        class="btn btn-edit"
        :class="{ active: store.editMode }"
        @click="store.toggleEditMode()"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        {{ store.editMode ? 'DONE' : 'EDIT' }}
      </button>
    </div>

    <!-- Safety Status Indicators -->
    <div class="safety-status-group">
      <!-- Latch Status -->
      <div
        v-if="safety.hasLatchedAlarms.value"
        class="safety-indicator latched"
        @click="safety.resetAllLatched()"
        title="Click to reset all latched alarms"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 17a2 2 0 002-2V9a2 2 0 00-4 0v6a2 2 0 002 2zm6-9v6a6 6 0 11-12 0V8h2v6a4 4 0 008 0V8h2z"/>
        </svg>
        {{ safety.latchedAlarmCount.value }} LATCHED
      </div>

      <!-- Interlock Status -->
      <div
        v-if="safety.interlockStatuses.value.some(s => !s.satisfied && s.enabled && !s.bypassed)"
        class="safety-indicator blocked"
        title="Some interlocks are blocking actions"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        {{ safety.interlockStatuses.value.filter(s => !s.satisfied && s.enabled && !s.bypassed).length }} BLOCKED
      </div>

      <!-- Active Alarms -->
      <div
        v-if="safety.hasActiveAlarms.value"
        class="safety-indicator alarm"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
        </svg>
        {{ safety.alarmCounts.value.active }}
      </div>

      <!-- All Clear -->
      <div
        v-if="!safety.hasLatchedAlarms.value &&
              !safety.hasActiveAlarms.value &&
              !safety.interlockStatuses.value.some(s => !s.satisfied && s.enabled && !s.bypassed)"
        class="safety-indicator clear"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M9 12l2 2 4-4"/>
        </svg>
        OK
      </div>
    </div>

    <!-- Status indicators -->
    <div class="status-group">
      <div class="status-item" :class="{ active: store.isConnected }">
        <span class="dot"></span>
        {{ store.isConnected ? 'ONLINE' : 'OFFLINE' }}
      </div>
      <div v-if="store.status" class="status-item info">
        {{ store.status.channel_count }} CH
      </div>
      <div v-if="store.status?.simulation_mode" class="status-item sim">
        SIM
      </div>
    </div>

  </div>
</template>

<style scoped>
.control-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  background: transparent;
  position: relative;
  z-index: 10;
}

.control-group {
  display: flex;
  gap: 8px;
}

.btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:disabled,
.btn.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-start {
  background: #22c55e;
  color: #fff;
}
.btn-start:hover:not(:disabled) {
  background: #16a34a;
}

.btn-stop {
  background: #ef4444;
  color: #fff;
}
.btn-stop:hover {
  background: #dc2626;
}

.btn-record {
  background: #1a1a2e;
  color: #ef4444;
  border: 1px solid #ef4444;
}
.btn-record:hover:not(:disabled) {
  background: #2a1515;
}
.btn-record.recording {
  background: #7f1d1d;
  animation: pulse-record 1s infinite;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}
.btn-secondary:hover {
  background: #4b5563;
}

.btn-edit {
  background: #1a1a2e;
  color: #60a5fa;
  border: 1px solid #60a5fa;
}
.btn-edit:hover {
  background: #1e3a5f;
}
.btn-edit.active {
  background: #1e40af;
  color: #fff;
}

.btn-add {
  background: #059669;
  color: #fff;
}
.btn-add:hover {
  background: #047857;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}
.btn-primary:hover {
  background: #2563eb;
}

.scheduler-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scheduler-toggle .label {
  font-size: 0.7rem;
  color: #888;
  font-weight: 600;
}

.toggle-btn {
  position: relative;
  width: 40px;
  height: 20px;
  background: #4b5563;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  padding: 2px;
  transition: background 0.2s;
}

.toggle-btn.on {
  background: #22c55e;
}

.toggle-btn .slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle-btn.on .slider {
  transform: translateX(20px);
}

.status-group {
  display: flex;
  gap: 10px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
}

.status-item .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6b7280;
}

.status-item.active {
  color: #22c55e;
}
.status-item.active .dot {
  background: #22c55e;
  box-shadow: 0 0 6px #22c55e;
}

.status-item.info {
  color: #60a5fa;
}

.status-item.sim {
  color: #fbbf24;
  background: #451a03;
  padding: 2px 6px;
  border-radius: 2px;
}

@keyframes pulse-record {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Safety Status Indicators */
.safety-status-group {
  display: flex;
  gap: 6px;
}

.safety-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
}

.safety-indicator.latched {
  background: #7f1d1d;
  color: #fca5a5;
  cursor: pointer;
  animation: pulse-safety 1s infinite;
}

.safety-indicator.latched:hover {
  background: #991b1b;
}

.safety-indicator.blocked {
  background: #78350f;
  color: #fbbf24;
}

.safety-indicator.alarm {
  background: #7f1d1d;
  color: #fca5a5;
  animation: pulse-safety 1s infinite;
}

.safety-indicator.clear {
  background: #14532d;
  color: #86efac;
}

@keyframes pulse-safety {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
