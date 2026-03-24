<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useAuth } from '../composables/useAuth'
import { useMqtt } from '../composables/useMqtt'
import { usePlayground } from '../composables/usePlayground'

const auth = useAuth()
const mqtt = useMqtt()
const playground = usePlayground()

defineProps<{
  showEditControls?: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'stop'): void
  (e: 'record-start'): void
  (e: 'record-stop'): void
  (e: 'session-start'): void
  (e: 'session-stop'): void
  (e: 'add-widget'): void
}>()

const store = useDashboardStore()

// Permission checks for control actions
// Use role-based computed refs directly for proper Vue reactivity
// (function calls like hasPermission() don't create reactive dependencies)
const canStartAcquisition = computed(() => auth.isOperator.value)
const canStartRecording = computed(() => auth.isOperator.value)
const canControlSession = computed(() => auth.isOperator.value)

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
        aria-label="Start acquisition"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <polygon points="5,3 19,12 5,21"/>
        </svg>
        START
        <span v-if="!canStartAcquisition" class="lock-icon" aria-label="Locked">🔒</span>
      </button>
      <button
        v-else
        class="btn btn-stop"
        @click="emit('stop')"
        aria-label="Stop acquisition"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
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
        aria-label="Start recording"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="8"/>
        </svg>
        RECORD
        <span v-if="!canStartRecording" class="lock-icon" aria-label="Locked">🔒</span>
      </button>
      <button
        v-else
        class="btn btn-record recording"
        @click="emit('record-stop')"
        aria-label="Stop recording"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="8"/>
        </svg>
        <span aria-live="polite">{{ recordingTime }}</span>
      </button>
    </div>

    <!-- Session toggle - controls test session (session scripts, sequences) -->
    <div class="control-group">
      <div class="session-toggle" :class="{ locked: !canControlSession, disabled: !store.isAcquiring }" role="group" aria-label="Session controls">
        <span class="label" id="session-label">SESSION</span>
        <button
          class="toggle-btn"
          :class="{ on: playground.isSessionActive.value, locked: !canControlSession, disabled: !store.isAcquiring }"
          @click="canControlSession && store.isAcquiring && (playground.isSessionActive.value ? emit('session-stop') : emit('session-start'))"
          :disabled="!canControlSession || !store.isAcquiring"
          :title="!store.isAcquiring ? 'Start acquisition first' : (canControlSession ? 'Toggle Test Session' : 'Requires Operator or higher')"
          role="switch"
          :aria-checked="playground.isSessionActive.value"
          aria-labelledby="session-label"
        >
          <span class="slider"></span>
        </button>
        <span v-if="!canControlSession" class="lock-icon" aria-label="Locked">🔒</span>
      </div>
    </div>

    <div v-if="showEditControls" class="control-group edit-group">
      <!-- Add Widget (only in edit mode) -->
      <button
        v-if="store.editMode"
        class="btn btn-add"
        @click="emit('add-widget')"
        aria-label="Add widget"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        ADD WIDGET
      </button>

      <!-- Edit mode toggle -->
      <button
        class="btn btn-edit"
        :class="{ active: store.editMode }"
        @click="store.toggleEditMode()"
        :aria-label="store.editMode ? 'Exit edit mode' : 'Enter edit mode'"
        :aria-pressed="store.editMode"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
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
        :aria-label="store.pidEditMode ? 'Exit P&ID drawing mode' : 'Enter P&ID drawing mode'"
        :aria-pressed="store.pidEditMode"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
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
  z-index: 100;
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
  background: var(--color-success);
  color: var(--text-primary);
}
.btn-start:hover:not(:disabled) {
  background: var(--color-success-dark);
}

.btn-stop {
  background: var(--color-error);
  color: var(--text-primary);
}
.btn-stop:hover {
  background: var(--color-error);
}

.btn-record {
  background: var(--bg-widget);
  color: var(--color-error);
  border: 1px solid var(--color-error);
}
.btn-record:hover:not(:disabled) {
  background: var(--color-error-dark);
}
.btn-record.recording {
  background: var(--color-error-bg);
  animation: pulse-record 1s infinite;
}

.btn-secondary {
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
}
.btn-secondary:hover {
  background: var(--btn-secondary-hover);
}

.btn-edit {
  background: var(--bg-widget);
  color: var(--color-accent-light);
  border: 1px solid var(--color-accent-light);
}
.btn-edit:hover {
  background: var(--color-accent-bg);
}
.btn-edit.active {
  background: var(--color-accent-dark);
  color: var(--text-primary);
}

.btn-pid {
  background: var(--bg-widget);
  color: var(--color-success);
  border: 1px solid var(--color-success);
}
.btn-pid:hover {
  background: var(--color-success-bg);
}
.btn-pid.active {
  background: var(--color-success-dark);
  color: var(--text-primary);
}

.btn-add {
  background: var(--color-success);
  color: var(--text-primary);
}
.btn-add:hover {
  background: var(--color-success-dark);
}

.btn-primary {
  background: var(--color-accent);
  color: var(--text-primary);
}
.btn-primary:hover {
  background: var(--color-accent-dark);
}

.session-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-toggle .label {
  font-size: 0.7rem;
  color: var(--text-secondary);
  font-weight: 600;
}

.toggle-btn {
  position: relative;
  width: 40px;
  height: 20px;
  background: var(--btn-secondary-hover);
  border-radius: 10px;
  border: none;
  cursor: pointer;
  padding: 2px;
  transition: background 0.2s;
}

.toggle-btn.on {
  background: var(--color-success);
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
  background: var(--bg-hover);
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

.session-toggle.disabled {
  opacity: 0.4;
}

.toggle-btn.disabled {
  cursor: not-allowed;
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
