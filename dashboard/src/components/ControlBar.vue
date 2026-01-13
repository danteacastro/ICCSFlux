<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useAuth } from '../composables/useAuth'
import { useMqtt } from '../composables/useMqtt'

const auth = useAuth()
const mqtt = useMqtt()

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

// Permission checks for control actions
const canStartAcquisition = computed(() => auth.hasPermission('acquisition.start') || auth.isOperator.value)
const canStartRecording = computed(() => auth.hasPermission('recording.start') || auth.isOperator.value)
const canControlSession = computed(() => auth.hasPermission('acquisition.start') || auth.isOperator.value)

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
        :class="{ locked: !canStartAcquisition }"
        @click="canStartAcquisition && emit('start')"
        :disabled="!store.isConnected || !canStartAcquisition"
        :title="canStartAcquisition ? 'Start Acquisition' : 'Requires Operator or higher'"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5,3 19,12 5,21"/>
        </svg>
        START
        <span v-if="!canStartAcquisition" class="lock-icon">🔒</span>
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
        :class="{ disabled: !store.isAcquiring, locked: !canStartRecording }"
        @click="canStartRecording && store.isAcquiring && emit('record-start')"
        :disabled="!store.isAcquiring || !canStartRecording"
        :title="canStartRecording ? 'Start Recording' : 'Requires Operator or higher'"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="8"/>
        </svg>
        RECORD
        <span v-if="!canStartRecording" class="lock-icon">🔒</span>
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


    <!-- Session toggle - controls automation engine (scheduler, sequences, patterns) -->
    <div class="control-group">
      <div class="session-toggle" :class="{ locked: !canControlSession }">
        <span class="label">SESSION</span>
        <button
          class="toggle-btn"
          :class="{ on: store.isSchedulerEnabled, locked: !canControlSession }"
          @click="canControlSession && (store.isSchedulerEnabled ? emit('schedule-disable') : emit('schedule-enable'))"
          :disabled="!canControlSession"
          :title="canControlSession ? 'Toggle Session' : 'Requires Operator or higher'"
        >
          <span class="slider"></span>
        </button>
        <span v-if="!canControlSession" class="lock-icon">🔒</span>
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

      <!-- P&ID Edit Mode toggle -->
      <button
        class="btn btn-pid"
        :class="{ active: store.pidEditMode }"
        @click="store.setPidEditMode(!store.pidEditMode)"
        title="P&ID Drawing Mode - Free-form symbols and pipes"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="5" cy="12" r="3"/>
          <circle cx="19" cy="12" r="3"/>
          <line x1="8" y1="12" x2="16" y2="12"/>
          <path d="M12 8v8"/>
        </svg>
        {{ store.pidEditMode ? 'EXIT P&ID' : 'P&ID' }}
      </button>
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

.btn-pid {
  background: #1a1a2e;
  color: #22c55e;
  border: 1px solid #22c55e;
}
.btn-pid:hover {
  background: #14532d;
}
.btn-pid.active {
  background: #15803d;
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

.session-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-toggle .label {
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

/* Locked/Permission Denied Styles */
.btn.locked {
  opacity: 0.4;
  cursor: not-allowed;
  position: relative;
}

.btn.locked:hover {
  background: rgba(127, 29, 29, 0.4);
}

.lock-icon {
  font-size: 0.65rem;
  margin-left: 3px;
}

.session-toggle.locked {
  opacity: 0.4;
}

.toggle-btn.locked {
  cursor: not-allowed;
}

.toggle-btn.locked:hover {
  opacity: 0.7;
}


@keyframes pulse-record {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Theme toggle */
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.theme-toggle:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}
</style>
