<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useMqtt } from '../composables/useMqtt'
import { useScripts } from '../composables/useScripts'
import type { ButtonAction } from '../types'

const props = defineProps<{
  widgetId: string
  label?: string
  buttonAction?: ButtonAction
  requireConfirmation?: boolean
  buttonColor?: string
}>()

const store = useDashboardStore()
const safety = useSafety()
const mqtt = useMqtt('nisystem')
const scripts = useScripts()

// Check if this button is blocked by interlocks
const blockStatus = computed(() => safety.isButtonBlocked(props.widgetId))
const isBlocked = computed(() => blockStatus.value.blocked)
const blockedBy = computed(() => blockStatus.value.blockedBy.map(s => s.name).join(', '))

// Confirmation state
const showConfirm = ref(false)
const isExecuting = ref(false)

const displayLabel = computed(() => props.label || 'Action')
const bgColor = computed(() => props.buttonColor || '#3b82f6')

const isDisabled = computed(() => {
  if (isBlocked.value) return true
  if (!props.buttonAction) return true
  if (!store.isConnected) return true
  return false
})

const statusText = computed(() => {
  if (isBlocked.value) return `Blocked: ${blockedBy.value}`
  if (!props.buttonAction) return 'Not configured'
  if (!store.isConnected) return 'Offline'
  if (isExecuting.value) return 'Executing...'
  return ''
})

function handleClick() {
  if (isDisabled.value) return

  if (props.requireConfirmation && !showConfirm.value) {
    showConfirm.value = true
    // Auto-cancel after 3 seconds
    setTimeout(() => {
      showConfirm.value = false
    }, 3000)
    return
  }

  executeAction()
}

function cancelConfirm() {
  showConfirm.value = false
}

async function executeAction() {
  if (!props.buttonAction || isDisabled.value) return

  showConfirm.value = false
  isExecuting.value = true

  try {
    const action = props.buttonAction

    switch (action.type) {
      case 'mqtt_publish':
        if (action.topic && action.payload !== undefined) {
          // Use sendCommand which prepends the system prefix
          mqtt.sendCommand(action.topic, action.payload)
        }
        break

      case 'digital_output':
        if (action.channel) {
          const value = action.setValue ?? 1
          mqtt.setOutput(action.channel, value)

          // If pulse mode, reset after duration
          if (action.pulseMs && action.pulseMs > 0) {
            setTimeout(() => {
              mqtt.setOutput(action.channel!, value === 1 ? 0 : 1)
            }, action.pulseMs)
          }
        }
        break

      case 'script_run':
        if (action.sequenceId) {
          scripts.startSequence(action.sequenceId)
        }
        break

      case 'system_command':
        if (action.command) {
          switch (action.command) {
            case 'acquisition_start':
              mqtt.startAcquisition()
              break
            case 'acquisition_stop':
              mqtt.stopAcquisition()
              break
            case 'recording_start':
              mqtt.startRecording()
              break
            case 'recording_stop':
              mqtt.stopRecording()
              break
            case 'alarm_acknowledge_all':
              safety.acknowledgeAll()
              break
            case 'latch_reset_all':
              safety.resetAllLatched()
              break
          }
        }
        break
    }
  } catch (err) {
    console.error('Button action failed:', err)
  } finally {
    // Brief visual feedback
    setTimeout(() => {
      isExecuting.value = false
    }, 300)
  }
}
</script>

<template>
  <div class="action-button-widget" :class="{ blocked: isBlocked, disabled: isDisabled, executing: isExecuting }">
    <!-- Normal state -->
    <button
      v-if="!showConfirm"
      class="action-btn"
      :style="{ backgroundColor: isDisabled ? '#374151' : bgColor }"
      :disabled="isDisabled"
      @click="handleClick"
      :title="statusText"
    >
      <span class="label">{{ displayLabel }}</span>
      <span v-if="isBlocked" class="blocked-icon">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </span>
    </button>

    <!-- Confirmation state -->
    <div v-else class="confirm-state">
      <span class="confirm-text">Confirm?</span>
      <div class="confirm-buttons">
        <button class="confirm-yes" @click="executeAction">YES</button>
        <button class="confirm-no" @click="cancelConfirm">NO</button>
      </div>
    </div>

    <!-- Blocked tooltip -->
    <div v-if="isBlocked && blockedBy" class="blocked-tooltip">
      {{ blockedBy }}
    </div>
  </div>
</template>

<style scoped>
.action-button-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: none;
  border-radius: 4px;
  color: #fff;
  font-weight: 600;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
  text-transform: uppercase;
}

.action-btn:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: scale(1.02);
}

.action-btn:active:not(:disabled) {
  transform: scale(0.98);
}

.action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.blocked-icon {
  opacity: 0.8;
}

/* Blocked state */
.blocked .action-btn {
  background: #374151 !important;
}

.blocked {
  border-color: #78350f;
}

/* Executing state */
.executing .action-btn {
  animation: pulse-execute 0.5s infinite;
}

@keyframes pulse-execute {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Confirmation state */
.confirm-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.confirm-text {
  font-size: 0.7rem;
  color: #fbbf24;
  font-weight: 600;
}

.confirm-buttons {
  display: flex;
  gap: 4px;
}

.confirm-yes,
.confirm-no {
  padding: 4px 12px;
  border: none;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
  cursor: pointer;
}

.confirm-yes {
  background: #22c55e;
  color: #fff;
}

.confirm-yes:hover {
  background: #16a34a;
}

.confirm-no {
  background: #6b7280;
  color: #fff;
}

.confirm-no:hover {
  background: #4b5563;
}

/* Blocked tooltip */
.blocked-tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #78350f;
  color: #fbbf24;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.6rem;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
  z-index: 10;
}

.action-button-widget:hover .blocked-tooltip {
  opacity: 1;
}
</style>
