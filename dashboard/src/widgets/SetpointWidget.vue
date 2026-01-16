<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'
import { formatUnit } from '../utils/formatUnit'

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
  props.label || props.channel
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return formatUnit(channelConfig.value?.unit)
})

// Determine if this is a valid channel type for setpoint control
const isValidSetpointChannel = computed(() => {
  const type = channelConfig.value?.channel_type
  // Setpoint makes sense for: analog outputs, Python values
  // Digital outputs should use a toggle switch instead
  return type === 'analog_output' || props.channel.startsWith('py.')
})

const isDigitalOutput = computed(() => {
  return channelConfig.value?.channel_type === 'digital_output'
})

const isInputChannel = computed(() => {
  const type = channelConfig.value?.channel_type
  return type && !type.includes('output') && !props.channel.startsWith('py.')
})

// Get min/max from props or channel config based on output type
const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue

  const config = channelConfig.value
  if (!config) return 0

  // For digital outputs, min is always 0
  if (config.channel_type === 'digital_output') return 0

  // For analog outputs, check ao_range or voltage_range
  if (config.channel_type === 'analog_output') {
    // ao_range can be: '5V', '10V', 'pm10V' (plus/minus), '0-20mA', '4-20mA'
    const aoRange = config.ao_range?.toLowerCase() || ''
    if (aoRange.includes('pm') || aoRange.includes('+-') || aoRange.includes('±')) {
      // Bipolar output (e.g., pm10V = -10 to +10)
      const voltage = config.voltage_range ?? 10
      return -voltage
    }
    if (aoRange.includes('4-20')) {
      return 4 // 4-20mA starts at 4
    }
    // Unipolar - starts at 0
    return 0
  }

  // Fallback to alarm limits (legacy behavior)
  return config.low_limit ?? 0
})

const maxVal = computed(() => {
  if (props.maxValue !== undefined) return props.maxValue

  const config = channelConfig.value
  if (!config) return 100

  // For digital outputs, max is always 1
  if (config.channel_type === 'digital_output') return 1

  // For analog outputs, check ao_range or voltage_range
  if (config.channel_type === 'analog_output') {
    const aoRange = config.ao_range?.toLowerCase() || ''
    if (aoRange.includes('20ma') || aoRange.includes('20 ma')) {
      return 20 // 0-20mA or 4-20mA ends at 20
    }
    // Use voltage_range if available
    return config.voltage_range ?? 10
  }

  // Fallback to alarm limits (legacy behavior)
  return config.high_limit ?? 100
})

// Step size: props > config > smart default based on range
const stepVal = computed(() => {
  if (props.step !== undefined) return props.step
  if (channelConfig.value?.step !== undefined) return channelConfig.value.step

  // Smart default: calculate from range
  const range = maxVal.value - minVal.value
  if (range <= 1) return 0.1      // 0-1V or digital: 0.1 step
  if (range <= 10) return 0.1     // 0-10V: 0.1 step
  if (range <= 20) return 0.5     // 4-20mA: 0.5 step
  if (range <= 100) return 1      // 0-100: 1 step
  return range / 100              // Large ranges: 1% step
})

// Decimals: props > smart default based on step
const decimalsVal = computed(() => {
  if (props.decimals !== undefined) return props.decimals

  // Calculate decimals from step size
  const step = stepVal.value
  if (step >= 1) return 0
  if (step >= 0.1) return 1
  if (step >= 0.01) return 2
  return 3
})

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
  if (!channelConfig.value && !props.channel.startsWith('py.')) return true
  // Disable for input channels - can't set inputs
  if (isInputChannel.value) return true
  return false
})

// Warning message for misconfigured widgets
const warningMessage = computed(() => {
  if (isInputChannel.value) return 'Input channel - use display widget'
  if (isDigitalOutput.value) return 'Digital output - use toggle widget'
  return null
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
  <div class="setpoint-widget" :class="{ disabled: isDisabled, blocked: isBlocked, warning: warningMessage }">
    <div class="label">{{ displayLabel }}</div>

    <!-- Warning for misconfigured widget -->
    <div v-if="warningMessage" class="warning-message">{{ warningMessage }}</div>

    <div v-else class="setpoint-controls">
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

    <div v-if="!warningMessage" class="range-info">
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
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
  gap: 2px;
}

.label {
  font-size: 0.55rem;
  color: #888;
  text-transform: uppercase;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  line-height: 1.1;
}

.setpoint-controls {
  display: flex;
  align-items: center;
  gap: 2px;
}

.step-btn {
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 2px;
  background: #3b82f6;
  color: #fff;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
  padding: 0;
  line-height: 1;
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
  min-width: 36px;
  padding: 2px 4px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 2px;
  cursor: pointer;
  text-align: center;
}

.value {
  font-size: 0.8rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
}

.unit {
  font-size: 0.6rem;
  color: #888;
  margin-left: 2px;
}

.value-input {
  width: 40px;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 0.8rem;
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
  font-size: 0.5rem;
  color: #555;
  margin-top: 2px;
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

/* Warning state - wrong channel type */
.warning {
  border-color: #854d0e;
  background: rgba(120, 53, 15, 0.2);
}

.warning-message {
  font-size: 0.55rem;
  color: #fbbf24;
  text-align: center;
  padding: 4px;
  line-height: 1.3;
}
</style>
