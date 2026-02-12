<script setup lang="ts">
import { computed, ref, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useMqtt } from '../composables/useMqtt'
import { useScripts } from '../composables/useScripts'
import { useBackendScripts } from '../composables/useBackendScripts'
import type { ButtonAction, ButtonBehavior, ButtonStyle } from '../types'

const props = defineProps<{
  widgetId: string
  label?: string
  buttonAction?: ButtonAction
  requireConfirmation?: boolean
  buttonColor?: string
  buttonBehavior?: ButtonBehavior    // 'momentary' | 'toggle' | 'latching' | 'one_shot'
  buttonVisualStyle?: ButtonStyle    // 'standard' | 'round' | 'square' | 'emergency' | 'flat'
  buttonActiveColor?: string         // Color when active/pressed
  buttonSize?: 'small' | 'medium' | 'large'
}>()

const store = useDashboardStore()
const safety = useSafety()
const mqtt = useMqtt('nisystem')
const scripts = useScripts()
const backendScripts = useBackendScripts()

// Check if this button is blocked by interlocks
const blockStatus = computed(() => safety.isButtonBlocked(props.widgetId))
const isBlocked = computed(() => blockStatus.value.blocked)
const blockedBy = computed(() => blockStatus.value.blockedBy.map(s => s.name).join(', '))

// Confirmation state
const showConfirm = ref(false)
const isExecuting = ref(false)

// Button behavior state
const isPressed = ref(false)           // Currently pressed (for momentary)
const isLatched = ref(false)           // Latched on (for toggle/latching)
let momentaryTimeout: ReturnType<typeof setTimeout> | null = null
let confirmTimeout: ReturnType<typeof setTimeout> | null = null
let pulseTimeout: ReturnType<typeof setTimeout> | null = null

const displayLabel = computed(() => props.label || 'Action')
const bgColor = computed(() => props.buttonColor || '#3b82f6')
const activeColor = computed(() => props.buttonActiveColor || '#22c55e')  // Green when active
const behavior = computed(() => props.buttonBehavior || 'one_shot')
const visualStyle = computed(() => props.buttonVisualStyle || 'standard')
const buttonSize = computed(() => props.buttonSize || 'medium')

// Is button currently "active" (lit up)?
const isActive = computed(() => {
  if (behavior.value === 'momentary') return isPressed.value
  if (behavior.value === 'toggle' || behavior.value === 'latching') return isLatched.value
  return isExecuting.value  // one_shot shows brief feedback
})

// Dynamic button color based on active state
const currentBgColor = computed(() => {
  if (isDisabled.value) return '#374151'
  if (isActive.value) return activeColor.value
  return bgColor.value
})

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

// Handle mouse/touch down
function handlePointerDown() {
  if (isDisabled.value) return

  if (behavior.value === 'momentary') {
    isPressed.value = true
    executeAction()  // Execute on press
  }
}

// Handle mouse/touch up
function handlePointerUp() {
  if (behavior.value === 'momentary') {
    isPressed.value = false
    // For digital outputs, turn off when released
    if (props.buttonAction?.type === 'digital_output' && props.buttonAction.channel) {
      const offValue = (props.buttonAction.setValue ?? 1) === 1 ? 0 : 1
      mqtt.setOutput(props.buttonAction.channel, offValue)
    }
  }
}

// Handle pointer leave (in case mouse leaves while pressed)
function handlePointerLeave() {
  if (behavior.value === 'momentary' && isPressed.value) {
    handlePointerUp()
  }
}

function handleClick() {
  if (isDisabled.value) return

  // Momentary behavior handles action in pointer down/up
  if (behavior.value === 'momentary') return

  if (props.requireConfirmation && !showConfirm.value) {
    showConfirm.value = true
    // Auto-cancel after 3 seconds
    if (confirmTimeout) clearTimeout(confirmTimeout)
    confirmTimeout = setTimeout(() => {
      showConfirm.value = false
      confirmTimeout = null
    }, 3000)
    return
  }

  // Handle toggle behavior
  if (behavior.value === 'toggle') {
    isLatched.value = !isLatched.value
    executeAction()
    return
  }

  // Handle latching behavior (sets on, requires external reset)
  if (behavior.value === 'latching') {
    if (!isLatched.value) {
      isLatched.value = true
      executeAction()
    }
    // Already latched - do nothing (need external reset)
    return
  }

  // Default one_shot behavior
  executeAction()
}

function cancelConfirm() {
  showConfirm.value = false
}

// External reset for latched buttons
function resetLatch() {
  if (behavior.value === 'latching') {
    isLatched.value = false
    // For digital outputs, turn off
    if (props.buttonAction?.type === 'digital_output' && props.buttonAction.channel) {
      const offValue = (props.buttonAction.setValue ?? 1) === 1 ? 0 : 1
      mqtt.setOutput(props.buttonAction.channel, offValue)
    }
  }
}

// Cleanup on unmount
onUnmounted(() => {
  if (momentaryTimeout) clearTimeout(momentaryTimeout)
  if (confirmTimeout) clearTimeout(confirmTimeout)
  if (pulseTimeout) clearTimeout(pulseTimeout)
})

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
            if (pulseTimeout) clearTimeout(pulseTimeout)
            pulseTimeout = setTimeout(() => {
              mqtt.setOutput(action.channel!, value === 1 ? 0 : 1)
              pulseTimeout = null
            }, action.pulseMs)
          }
        }
        break

      case 'script_run':
        if (action.sequenceId) {
          scripts.startSequence(action.sequenceId)
        }
        break

      case 'script_oneshot':
        // Run a script once (one-shot execution)
        if (action.scriptName) {
          backendScripts.startScript(action.scriptName)
        }
        break

      case 'variable_set':
        // Set a user variable to a specific value
        if (action.variableId && action.variableValue !== undefined) {
          mqtt.sendCommand('variables/set', {
            id: action.variableId,
            value: action.variableValue
          })
        }
        break

      case 'variable_reset':
        // Reset a user variable (counter, timer, etc.)
        if (action.variableId) {
          mqtt.sendCommand('variables/reset', { id: action.variableId })
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
  <div
    class="action-button-widget"
    :class="[
      `style-${visualStyle}`,
      `size-${buttonSize}`,
      {
        blocked: isBlocked,
        disabled: isDisabled,
        executing: isExecuting,
        active: isActive
      }
    ]"
  >
    <!-- Normal state -->
    <button
      v-if="!showConfirm"
      class="action-btn"
      :style="{ backgroundColor: currentBgColor }"
      :disabled="isDisabled"
      @click="handleClick"
      @pointerdown="handlePointerDown"
      @pointerup="handlePointerUp"
      @pointerleave="handlePointerLeave"
      :title="statusText"
    >
      <span class="label">{{ displayLabel }}</span>
      <span v-if="isBlocked" class="blocked-icon">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </span>
      <!-- Latched indicator -->
      <span v-if="behavior === 'latching' && isLatched" class="latch-indicator" title="Latched - click to reset">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
          <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>
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
  background: var(--bg-widget);
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
  color: var(--text-primary);
  font-weight: 600;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
  position: relative;
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

.latch-indicator {
  position: absolute;
  top: 4px;
  right: 4px;
  opacity: 0.8;
}

/* ==================== */
/* SIZE VARIANTS        */
/* ==================== */
.size-small .action-btn {
  font-size: 0.65rem;
  padding: 4px 8px;
}

.size-medium .action-btn {
  font-size: 0.8rem;
  padding: 6px 12px;
}

.size-large .action-btn {
  font-size: 1rem;
  padding: 10px 16px;
}

/* ==================== */
/* VISUAL STYLE VARIANTS */
/* ==================== */

/* Standard - default rectangular button */
.style-standard .action-btn {
  border-radius: 4px;
}

/* Round - circular button like indicator lamp */
.style-round {
  padding: 4px;
  aspect-ratio: 1;
}

.style-round .action-btn {
  border-radius: 50%;
  aspect-ratio: 1;
  min-width: 40px;
  min-height: 40px;
  box-shadow:
    0 2px 4px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

.style-round .action-btn::after {
  content: '';
  position: absolute;
  top: 15%;
  left: 25%;
  width: 30%;
  height: 20%;
  background: linear-gradient(180deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0) 100%);
  border-radius: 50%;
}

.style-round.active .action-btn {
  box-shadow:
    0 0 12px currentColor,
    0 2px 4px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

.style-round .label {
  font-size: 0.6rem;
}

/* Square - square button */
.style-square {
  padding: 4px;
  aspect-ratio: 1;
}

.style-square .action-btn {
  border-radius: 4px;
  aspect-ratio: 1;
  min-width: 40px;
  min-height: 40px;
}

/* Emergency - prominent red emergency style */
.style-emergency {
  padding: 4px;
  aspect-ratio: 1;
}

.style-emergency .action-btn {
  border-radius: 50%;
  aspect-ratio: 1;
  min-width: 60px;
  min-height: 60px;
  background: #dc2626 !important;
  border: 4px solid #fcd34d;
  box-shadow:
    0 4px 8px rgba(0, 0, 0, 0.4),
    inset 0 -4px 8px rgba(0, 0, 0, 0.3),
    inset 0 2px 0 rgba(255, 255, 255, 0.2);
  text-transform: uppercase;
  font-weight: 800;
  letter-spacing: 0.5px;
}

.style-emergency .action-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow:
    0 0 20px rgba(220, 38, 38, 0.6),
    0 4px 8px rgba(0, 0, 0, 0.4),
    inset 0 -4px 8px rgba(0, 0, 0, 0.3);
}

.style-emergency .action-btn:active:not(:disabled) {
  transform: scale(0.95);
  box-shadow:
    0 2px 4px rgba(0, 0, 0, 0.4),
    inset 0 2px 8px rgba(0, 0, 0, 0.4);
}

.style-emergency.active .action-btn {
  background: #991b1b !important;
  animation: emergency-pulse 0.5s infinite;
}

@keyframes emergency-pulse {
  0%, 100% { box-shadow: 0 0 10px rgba(220, 38, 38, 0.8), 0 4px 8px rgba(0, 0, 0, 0.4); }
  50% { box-shadow: 0 0 25px rgba(220, 38, 38, 1), 0 4px 8px rgba(0, 0, 0, 0.4); }
}

/* Flat - minimal flat style */
.style-flat .action-btn {
  border-radius: 4px;
  background: transparent !important;
  border: 2px solid currentColor;
  color: inherit;
}

.style-flat .action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1) !important;
}

.style-flat.active .action-btn {
  background: rgba(255, 255, 255, 0.2) !important;
}

/* ==================== */
/* STATE VARIANTS       */
/* ==================== */

/* Blocked state */
.blocked .action-btn {
  background: #374151 !important;
}

.blocked {
  border-color: #78350f;
}

/* Active state glow */
.active:not(.style-emergency):not(.style-flat) .action-btn {
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.5);
}

/* Executing state */
.executing .action-btn {
  animation: pulse-execute 0.5s infinite;
}

@keyframes pulse-execute {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* ==================== */
/* CONFIRMATION STATE   */
/* ==================== */
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
  background: var(--color-success);
  color: var(--text-primary);
}

.confirm-yes:hover {
  background: var(--color-success-dark);
}

.confirm-no {
  background: var(--text-dim);
  color: var(--text-primary);
}

.confirm-no:hover {
  background: var(--btn-secondary-hover);
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
