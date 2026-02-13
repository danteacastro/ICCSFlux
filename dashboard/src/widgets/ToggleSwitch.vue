<script setup lang="ts">
import { computed, ref, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import InterlockBlockOverlay from '../components/InterlockBlockOverlay.vue'

const props = defineProps<{
  widgetId?: string
  channel: string
  label?: string
  disabled?: boolean
  onLabel?: string      // Label when ON
  offLabel?: string     // Label when OFF
  confirmOn?: boolean   // Require confirmation to turn ON
  confirmOff?: boolean  // Require confirmation to turn OFF
  globalConfirmOutputs?: boolean  // ISA-101 global output confirmation
  style?: { onColor?: string; offColor?: string }
}>()

const emit = defineEmits<{
  (e: 'change', value: boolean): void
}>()

const store = useDashboardStore()
const safety = useSafety()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if output is blocked by interlocks (e.g., latched alarms)
const blockStatus = computed(() => safety.isOutputBlocked(props.channel))
const isBlocked = computed(() => blockStatus.value.blocked)
const blockedBy = computed(() => blockStatus.value.blockedBy.map(s => s.name).join(', '))

// Check if data is stale
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const isOn = computed(() => {
  if (!channelValue.value || isStale.value) return false
  return channelValue.value.value !== 0
})

// Display label - use onLabel/offLabel if provided, otherwise fallback to label or channel
const displayLabel = computed(() => {
  if (isOn.value && props.onLabel) return props.onLabel
  if (!isOn.value && props.offLabel) return props.offLabel
  return (props.label || channelConfig.value?.name || props.channel || '').replace(/^py\./, '')
})

// Custom colors from style prop
const onColor = computed(() => props.style?.onColor || '#22c55e')
const offColor = computed(() => props.style?.offColor || '#4b5563')

// Block toggle if: disabled, not acquiring, OR blocked by interlocks
const canToggle = computed(() => !props.disabled && store.isAcquiring && !isBlocked.value)

const statusText = computed(() => {
  if (isBlocked.value) return `Blocked: ${blockedBy.value}`
  if (!store.isAcquiring) return 'Not acquiring'
  return ''
})

// Confirmation state
const showConfirm = ref(false)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

function clearConfirmTimer() {
  if (confirmTimer) {
    clearTimeout(confirmTimer)
    confirmTimer = null
  }
}

function toggle() {
  if (!canToggle.value) return
  const newValue = !isOn.value

  // Check if confirmation is needed
  const needsConfirm = newValue
    ? (props.confirmOn || props.globalConfirmOutputs)
    : props.confirmOff

  if (needsConfirm && !showConfirm.value) {
    showConfirm.value = true
    clearConfirmTimer()
    confirmTimer = setTimeout(() => { showConfirm.value = false }, 3000)
    return
  }

  showConfirm.value = false
  clearConfirmTimer()
  emit('change', newValue)
}

function confirmAction() {
  clearConfirmTimer()
  showConfirm.value = false
  emit('change', !isOn.value)
}

function cancelConfirm() {
  clearConfirmTimer()
  showConfirm.value = false
}

onUnmounted(() => clearConfirmTimer())
</script>

<template>
  <div class="toggle-switch" :class="{ disabled: !canToggle, blocked: isBlocked }" :title="statusText">
    <!-- Compact horizontal layout (shown when short) -->
    <div class="layout-horizontal">
      <div class="label">{{ displayLabel }}</div>
      <button
        v-if="!showConfirm"
        class="switch"
        :class="{ on: isOn }"
        :style="{ backgroundColor: isOn ? onColor : offColor }"
        @click="toggle"
        :disabled="!canToggle"
      >
        <span class="slider"></span>
      </button>
      <div v-else class="confirm-panel">
        <span class="confirm-text">Confirm?</span>
        <button class="confirm-btn yes" @click="confirmAction">✓</button>
        <button class="confirm-btn no" @click="cancelConfirm">✕</button>
      </div>
    </div>

    <!-- Vertical layout (shown when tall enough) -->
    <div class="layout-vertical">
      <div class="label">{{ displayLabel }}</div>
      <button
        v-if="!showConfirm"
        class="switch"
        :class="{ on: isOn }"
        :style="{ backgroundColor: isOn ? onColor : offColor }"
        @click="toggle"
        :disabled="!canToggle"
      >
        <span class="slider"></span>
      </button>
      <div v-else class="confirm-panel">
        <span class="confirm-text">Confirm?</span>
        <button class="confirm-btn yes" @click="confirmAction">✓</button>
        <button class="confirm-btn no" @click="cancelConfirm">✕</button>
      </div>
    </div>

    <InterlockBlockOverlay v-if="isBlocked" :blocked-by="blockStatus.blockedBy" />
  </div>
</template>

<style scoped>
.toggle-switch {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  container-type: size;
}

.toggle-switch.disabled {
  opacity: 0.5;
}

/* ========================================
   LAYOUT SWITCHING VIA CONTAINER QUERIES
   ======================================== */

/* Default: show horizontal (compact), hide vertical */
.layout-horizontal {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 0 4px;
}

.layout-horizontal .label {
  flex: 1;
  text-align: left;
  min-width: 30px;
}

.layout-vertical {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.layout-vertical .label {
  margin-bottom: 4px;
}

/* When tall enough (2+ rows ~55px), switch to vertical layout */
@container (min-height: 55px) {
  .layout-horizontal {
    display: none;
  }
  .layout-vertical {
    display: flex;
  }
}

.label {
  font-size: 0.65rem;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.switch {
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

.switch.on {
  background: #22c55e;
}

.switch:disabled {
  cursor: not-allowed;
}

.slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.switch.on .slider {
  transform: translateX(20px);
}

.toggle-switch.blocked {
  border: 2px solid var(--color-error-dark);
  animation: pulse-blocked 2s ease-in-out infinite;
}

.toggle-switch.blocked .switch {
  background: var(--indicator-danger-bg);
}

@keyframes pulse-blocked {
  0%, 100% { box-shadow: 0 0 4px rgba(220, 38, 38, 0.3); }
  50% { box-shadow: 0 0 12px rgba(220, 38, 38, 0.6); }
}

/* ISA-101 confirmation panel */
.confirm-panel {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confirm-text {
  font-size: 0.7rem;
  color: #fbbf24;
  font-weight: bold;
}

.confirm-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  transition: opacity 0.15s;
}

.confirm-btn:hover {
  opacity: 0.85;
}

.confirm-btn.yes {
  background: var(--color-success);
}

.confirm-btn.no {
  background: #6b7280;
}
</style>
