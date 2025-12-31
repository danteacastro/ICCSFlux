<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'

const props = defineProps<{
  widgetId: string
  channel: string
  label?: string
  minValue?: number
  maxValue?: number
  step?: number
  decimals?: number
  showUnit?: boolean
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Local input value
const inputValue = ref<string>('')
const isEditing = ref(false)

// Check if output is blocked by interlocks
const blockStatus = computed(() => safety.isOutputBlocked(props.channel))
const isBlocked = computed(() => blockStatus.value.blocked)

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return channelConfig.value?.unit || ''
})

// Get min/max from props or channel config
const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue
  return channelConfig.value?.low_limit ?? 0
})

const maxVal = computed(() => {
  if (props.maxValue !== undefined) return props.maxValue
  return channelConfig.value?.high_limit ?? 100
})

const stepVal = computed(() => props.step ?? 1)
const decimalsVal = computed(() => props.decimals ?? 1)

// Current value from channel
const currentValue = computed(() => {
  if (!channelValue.value) return null
  return channelValue.value.value
})

const displayValue = computed(() => {
  if (currentValue.value === null) return '--'
  return currentValue.value.toFixed(decimalsVal.value)
})

// Initialize input when not editing
watch(currentValue, (val) => {
  if (!isEditing.value && val !== null) {
    inputValue.value = val.toFixed(decimalsVal.value)
  }
}, { immediate: true })

const isDisabled = computed(() => {
  if (isBlocked.value) return true
  if (!store.isConnected) return true
  if (!channelConfig.value) return true
  return false
})

function startEdit() {
  if (isDisabled.value) return
  isEditing.value = true
  inputValue.value = currentValue.value?.toFixed(decimalsVal.value) || '0'
}

function cancelEdit() {
  isEditing.value = false
  inputValue.value = currentValue.value?.toFixed(decimalsVal.value) || ''
}

function applyValue() {
  if (isDisabled.value) return

  const val = parseFloat(inputValue.value)
  if (isNaN(val)) {
    cancelEdit()
    return
  }

  // Clamp to limits
  const clampedVal = Math.max(minVal.value, Math.min(maxVal.value, val))

  // Send to MQTT
  mqtt.setOutput(props.channel, clampedVal)

  isEditing.value = false
}

function increment() {
  if (isDisabled.value) return
  const val = (currentValue.value ?? 0) + stepVal.value
  const clampedVal = Math.min(maxVal.value, val)
  mqtt.setOutput(props.channel, clampedVal)
}

function decrement() {
  if (isDisabled.value) return
  const val = (currentValue.value ?? 0) - stepVal.value
  const clampedVal = Math.max(minVal.value, val)
  mqtt.setOutput(props.channel, clampedVal)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    applyValue()
  } else if (e.key === 'Escape') {
    cancelEdit()
  }
}
</script>

<template>
  <div class="setpoint-widget" :class="{ disabled: isDisabled, blocked: isBlocked }">
    <div class="label">{{ displayLabel }}</div>

    <div class="setpoint-controls">
      <button class="step-btn" @click="decrement" :disabled="isDisabled">−</button>

      <div class="value-container" @click="startEdit">
        <template v-if="!isEditing">
          <span class="value">{{ displayValue }}</span>
          <span v-if="unit" class="unit">{{ unit }}</span>
        </template>
        <input
          v-else
          ref="inputRef"
          type="number"
          v-model="inputValue"
          :min="minVal"
          :max="maxVal"
          :step="stepVal"
          @blur="applyValue"
          @keydown="onKeydown"
          autofocus
          class="value-input"
        />
      </div>

      <button class="step-btn" @click="increment" :disabled="isDisabled">+</button>
    </div>

    <div class="range-info">
      {{ minVal }} - {{ maxVal }} {{ unit }}
    </div>

    <div v-if="isBlocked" class="blocked-indicator" :title="blockStatus.blockedBy.map(s => s.name).join(', ')">
      BLOCKED
    </div>
  </div>
</template>

<style scoped>
.setpoint-widget {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 6px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
}

.label {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.setpoint-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  background: #3b82f6;
  color: #fff;
  font-size: 1.2rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.step-btn:hover:not(:disabled) {
  background: #2563eb;
  transform: scale(1.05);
}

.step-btn:disabled {
  background: #374151;
  cursor: not-allowed;
  opacity: 0.5;
}

.value-container {
  min-width: 60px;
  padding: 4px 8px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  cursor: pointer;
  text-align: center;
}

.value {
  font-size: 1.1rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
}

.unit {
  font-size: 0.7rem;
  color: #888;
  margin-left: 2px;
}

.value-input {
  width: 60px;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 1.1rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  text-align: center;
  outline: none;
}

.value-input::-webkit-inner-spin-button,
.value-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.range-info {
  font-size: 0.55rem;
  color: #666;
  margin-top: 4px;
}

.disabled .value {
  color: #666;
}

.blocked {
  border-color: #78350f;
}

.blocked-indicator {
  position: absolute;
  top: 4px;
  right: 4px;
  font-size: 0.5rem;
  font-weight: 700;
  color: #fbbf24;
  background: #78350f;
  padding: 2px 4px;
  border-radius: 2px;
}
</style>
