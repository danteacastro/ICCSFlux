<script setup lang="ts">
/**
 * LatchSwitchWidget - Safety latch control for interlocks
 *
 * This widget provides a safety latch mechanism that must be "armed" before:
 * - Starting a test session
 * - Enabling solenoid valves (digital outputs)
 * - Setting analog outputs above zero
 *
 * When an interlock FAILS while the latch is ARMED:
 * - System TRIPS
 * - Latch disarms
 * - Session stops
 * - All outputs go to safe state (configurable)
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useMqtt } from '../composables/useMqtt'

const props = defineProps<{
  widgetId: string
  label?: string
  // Latch configuration
  latchId?: string                    // Unique ID for this latch
  requireAcquiring?: boolean          // Must be acquiring to arm (default: true)
  requireNoFailedInterlocks?: boolean // No failed interlocks to arm (default: true)
  confirmArm?: boolean                // Require confirmation to arm
  tripOnInterlockFail?: boolean       // Trip system when interlock fails while armed (default: true)
  // Visual options
  showStatus?: boolean                // Show status text
  compactMode?: boolean               // Smaller display
}>()

const store = useDashboardStore()
const safety = useSafety()
const mqtt = useMqtt('nisystem')

// Latch state
const isArmed = ref(false)
const showConfirm = ref(false)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

// Persistence key
const storageKey = computed(() => `latch_${props.latchId || props.widgetId}`)

// Load persisted state
onMounted(() => {
  const saved = localStorage.getItem(storageKey.value)
  if (saved === 'true') {
    // Only restore armed state if no interlocks are currently failed
    if (!safety.hasFailedInterlocks.value) {
      isArmed.value = true
    }
  }
})

// CRITICAL: Watch for interlock failures while armed → TRIP
watch(() => safety.hasFailedInterlocks.value, (hasFailed) => {
  if (hasFailed && isArmed.value && props.tripOnInterlockFail !== false) {
    // Get the failed interlock names for the trip reason
    const failedNames = safety.failedInterlocks.value.map(i => i.name).join(', ')
    const reason = `Interlock failed: ${failedNames}`

    console.log(`[LatchSwitch] TRIP - ${reason}`)

    // Disarm the latch
    isArmed.value = false
    localStorage.setItem(storageKey.value, 'false')

    // Trigger system trip (stops session, resets outputs)
    safety.tripSystem(reason)

    // Publish latch disarm due to trip
    mqtt.sendCommand('latch/state', {
      latchId: props.latchId || props.widgetId,
      armed: false,
      tripped: true,
      tripReason: reason,
      timestamp: new Date().toISOString()
    })
  }
})

// Check prerequisites for arming
const canArm = computed(() => {
  // Can always disarm when armed
  if (isArmed.value) return true

  // Can't arm while system is tripped
  if (safety.isTripped.value) {
    return false
  }

  // Check acquiring requirement
  if (props.requireAcquiring !== false && !store.isAcquiring) {
    return false
  }

  // Check for failed interlocks (default: required)
  if (props.requireNoFailedInterlocks !== false && safety.hasFailedInterlocks.value) {
    return false
  }

  return true
})

const blockReason = computed(() => {
  if (isArmed.value) return ''

  if (safety.isTripped.value) {
    return `TRIPPED: ${safety.lastTripReason.value || 'System trip'}`
  }
  if (props.requireAcquiring !== false && !store.isAcquiring) {
    return 'Acquisition required'
  }
  if (props.requireNoFailedInterlocks !== false && safety.hasFailedInterlocks.value) {
    const names = safety.failedInterlocks.value.map(i => i.name).join(', ')
    return `Interlock failed: ${names}`
  }
  return ''
})

const displayLabel = computed(() => props.label || 'Safety Latch')

const statusText = computed(() => {
  if (safety.isTripped.value) return 'TRIPPED'
  if (isArmed.value) return 'ARMED'
  if (!canArm.value) return 'BLOCKED'
  return 'SAFE'
})

const statusClass = computed(() => {
  if (safety.isTripped.value) return 'tripped'
  if (isArmed.value) return 'armed'
  if (!canArm.value) return 'blocked'
  return 'safe'
})

function handleClick() {
  // If tripped, clicking resets the trip (if interlocks are now OK)
  if (safety.isTripped.value) {
    if (safety.resetTrip()) {
      console.log('[LatchSwitch] Trip reset successful')
    }
    return
  }

  if (isArmed.value) {
    // Disarm - always allowed
    disarm()
  } else if (canArm.value) {
    // Arm - may require confirmation
    if (props.confirmArm && !showConfirm.value) {
      showConfirm.value = true
      if (confirmTimer) clearTimeout(confirmTimer)
      confirmTimer = setTimeout(() => { showConfirm.value = false; confirmTimer = null }, 3000)
    } else {
      arm()
    }
  }
}

function arm() {
  showConfirm.value = false
  isArmed.value = true
  localStorage.setItem(storageKey.value, 'true')

  // Publish latch state change
  mqtt.sendCommand('latch/state', {
    latchId: props.latchId || props.widgetId,
    armed: true,
    timestamp: new Date().toISOString()
  })
}

function disarm() {
  isArmed.value = false
  localStorage.setItem(storageKey.value, 'false')

  // Publish latch state change
  mqtt.sendCommand('latch/state', {
    latchId: props.latchId || props.widgetId,
    armed: false,
    timestamp: new Date().toISOString()
  })
}

function cancelConfirm() {
  showConfirm.value = false
}

onUnmounted(() => {
  if (confirmTimer) clearTimeout(confirmTimer)
})

// Expose armed state for parent components
defineExpose({
  isArmed,
  arm,
  disarm
})
</script>

<template>
  <div
    class="latch-switch-widget"
    :class="[statusClass, { compact: compactMode }]"
    :title="blockReason"
  >
    <div class="latch-label">{{ displayLabel }}</div>

    <!-- Tripped state - click to reset -->
    <button
      v-if="safety.isTripped.value"
      class="latch-button tripped"
      @click="handleClick"
    >
      <span class="latch-icon">⚠️</span>
      <span class="latch-status">TRIPPED</span>
      <span class="reset-hint">Click to reset</span>
    </button>

    <!-- Confirmation state -->
    <div v-else-if="showConfirm" class="confirm-panel">
      <span class="confirm-text">Arm latch?</span>
      <button class="confirm-btn yes" @click="arm">✓</button>
      <button class="confirm-btn no" @click="cancelConfirm">✕</button>
    </div>

    <!-- Normal state -->
    <button
      v-else
      class="latch-button"
      :class="statusClass"
      :disabled="!canArm && !isArmed"
      @click="handleClick"
    >
      <span class="latch-icon">{{ isArmed ? '🔓' : '🔒' }}</span>
      <span v-if="showStatus !== false" class="latch-status">{{ statusText }}</span>
    </button>

    <!-- Blocked indicator -->
    <div v-if="!canArm && !isArmed && !safety.isTripped.value" class="blocked-reason">
      {{ blockReason }}
    </div>

    <!-- Trip reason -->
    <div v-if="safety.isTripped.value" class="trip-reason">
      {{ safety.lastTripReason.value }}
    </div>
  </div>
</template>

<style scoped>
.latch-switch-widget {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 6px;
  border: 2px solid var(--btn-secondary-hover);
  transition: all 0.3s ease;
}

.latch-switch-widget.armed {
  border-color: var(--color-success);
  background: linear-gradient(135deg, #1a2e1a 0%, #1a1a2e 100%);
}

.latch-switch-widget.blocked {
  border-color: #f59e0b;
  opacity: 0.8;
}

.latch-switch-widget.tripped {
  border-color: var(--color-error-dark);
  background: linear-gradient(135deg, #2e1a1a 0%, #1a1a2e 100%);
  animation: pulse-red 1s infinite;
}

@keyframes pulse-red {
  0%, 100% { border-color: var(--color-error-dark); }
  50% { border-color: var(--color-error); box-shadow: 0 0 10px rgba(239, 68, 68, 0.5); }
}

.latch-switch-widget.compact {
  padding: 4px;
}

.latch-label {
  font-size: 0.7rem;
  color: var(--label-color, #888);
  text-transform: uppercase;
  margin-bottom: 6px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.compact .latch-label {
  font-size: 0.6rem;
  margin-bottom: 4px;
}

.latch-button {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  background: var(--btn-secondary-bg);
  cursor: pointer;
  transition: all 0.2s ease;
  min-width: 80px;
}

.latch-button:hover:not(:disabled) {
  background: var(--btn-secondary-hover);
  transform: scale(1.02);
}

.latch-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.latch-button.armed {
  background: linear-gradient(135deg, var(--color-success) 0%, var(--color-success-dark) 100%);
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.4);
}

.latch-button.tripped {
  background: linear-gradient(135deg, var(--color-error-dark) 0%, #b91c1c 100%);
  box-shadow: 0 0 12px rgba(220, 38, 38, 0.5);
  cursor: pointer;
}

.latch-button.tripped:hover {
  background: linear-gradient(135deg, var(--color-error) 0%, var(--color-error-dark) 100%);
}

.latch-icon {
  font-size: 1.5rem;
  margin-bottom: 4px;
}

.compact .latch-icon {
  font-size: 1.2rem;
  margin-bottom: 2px;
}

.latch-status {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #9ca3af;
}

.latch-button.armed .latch-status,
.latch-button.tripped .latch-status {
  color: var(--text-primary);
}

.reset-hint {
  font-size: 0.5rem;
  color: rgba(255,255,255,0.7);
  margin-top: 2px;
}

.blocked-reason {
  font-size: 0.55rem;
  color: #f59e0b;
  margin-top: 4px;
  text-align: center;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-reason {
  font-size: 0.55rem;
  color: var(--color-error);
  margin-top: 4px;
  text-align: center;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confirm-panel {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confirm-text {
  font-size: 0.7rem;
  color: var(--color-warning);
  font-weight: 600;
}

.confirm-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.confirm-btn.yes {
  background: var(--color-success);
  color: var(--text-primary);
}

.confirm-btn.yes:hover {
  background: var(--color-success-dark);
}

.confirm-btn.no {
  background: #6b7280;
  color: var(--text-primary);
}

.confirm-btn.no:hover {
  background: var(--btn-secondary-hover);
}
</style>
