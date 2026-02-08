<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'
import InterlockBlockOverlay from '../components/InterlockBlockOverlay.vue'
import { formatUnit } from '../utils/formatUnit'
import type { WidgetStyle } from '../types'

export type SetpointStyle = 'standard' | 'knob'

const props = defineProps<{
  widgetId: string
  channel: string
  label?: string
  minValue?: number
  maxValue?: number
  step?: number
  decimals?: number
  showUnit?: boolean
  style?: WidgetStyle
  visualStyle?: SetpointStyle
  h?: number  // Grid height - auto-compact when h=1
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Local input value
const inputValue = ref<string>('')
const isEditing = ref(false)

// Knob interaction state
const isDragging = ref(false)
const knobElement = ref<HTMLElement | null>(null)

// Check if output is blocked by interlocks
const blockStatus = computed(() => safety.isOutputBlocked(props.channel))
const isBlocked = computed(() => blockStatus.value.blocked)

const displayLabel = computed(() =>
  (props.label || props.channel || '').replace(/^py\./, '')
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return formatUnit(channelConfig.value?.unit)
})

// Determine if this is a valid channel type for setpoint control
const isValidSetpointChannel = computed(() => {
  const type = channelConfig.value?.channel_type
  // Setpoint makes sense for: analog outputs (voltage_output, current_output), Python values
  // Digital outputs should use a toggle switch instead
  // Also support legacy 'analog_output' for backwards compatibility
  return type === 'voltage_output' || type === 'current_output' || type === 'analog_output' || props.channel.startsWith('py.')
})

const isDigitalOutput = computed(() => {
  return channelConfig.value?.channel_type === 'digital_output'
})

const isInputChannel = computed(() => {
  const type = channelConfig.value?.channel_type
  return type && !type.includes('output') && !props.channel.startsWith('py.')
})

// Get min/max from props or channel config based on output type
// Priority: props > scaling config (engineering units) > raw hardware range > alarm limits
const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue

  const config = channelConfig.value
  if (!config) return 0

  // For digital outputs, min is always 0
  if (config.channel_type === 'digital_output') return 0

  // For analog outputs (voltage_output, current_output), check scaling configuration first (engineering units)
  const isAnalogOutputMin = config.channel_type === 'voltage_output' || config.channel_type === 'current_output' || config.channel_type === 'analog_output'
  if (isAnalogOutputMin) {
    // 4-20mA scaling: use eng_units_min (e.g., 0 PSI at 4mA)
    if (config.four_twenty_scaling && config.eng_units_min !== undefined) {
      return config.eng_units_min
    }

    // Map scaling: use scaled_min (e.g., 0% at 0V)
    if (config.scale_type === 'map' && config.scaled_min !== undefined) {
      return config.scaled_min
    }

    // Linear scaling: calculate from slope/offset and raw min
    if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
      const rawMin = config.pre_scaled_min ?? 0
      return rawMin * config.scale_slope + (config.scale_offset ?? 0)
    }

    // Fallback to raw hardware range if no scaling configured
    const aoRange = config.ao_range?.toLowerCase() || ''
    if (aoRange.includes('pm') || aoRange.includes('+-') || aoRange.includes('±')) {
      const voltage = config.voltage_range ?? 10
      return -voltage
    }
    if (aoRange.includes('4-20')) {
      return 4
    }
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

  // For analog outputs (voltage_output, current_output), check scaling configuration first (engineering units)
  const isAnalogOutputMax = config.channel_type === 'voltage_output' || config.channel_type === 'current_output' || config.channel_type === 'analog_output'
  if (isAnalogOutputMax) {
    // 4-20mA scaling: use eng_units_max (e.g., 100 PSI at 20mA)
    if (config.four_twenty_scaling && config.eng_units_max !== undefined) {
      return config.eng_units_max
    }

    // Map scaling: use scaled_max (e.g., 100% at 10V)
    if (config.scale_type === 'map' && config.scaled_max !== undefined) {
      return config.scaled_max
    }

    // Linear scaling: calculate from slope/offset and raw max
    if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
      const rawMax = Number(config.pre_scaled_max ?? config.voltage_range ?? 10)
      return rawMax * config.scale_slope + (config.scale_offset ?? 0)
    }

    // Fallback to raw hardware range if no scaling configured
    const aoRange = config.ao_range?.toLowerCase() || ''
    if (aoRange.includes('20ma') || aoRange.includes('20 ma')) {
      return 20
    }
    const range = config.voltage_range
    if (typeof range === 'number') return range
    return 10
  }

  // Fallback to alarm limits (legacy behavior)
  return config.high_limit ?? 100
})

// Step size: props > config > smart default based on range
const stepVal = computed(() => {
  if (props.step !== undefined) return props.step
  const configStep = channelConfig.value?.step
  if (typeof configStep === 'number') return configStep

  // Smart default: calculate from range
  const range = Number(maxVal.value) - Number(minVal.value)
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
  if (!store.isAcquiring) return true
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
  const clampedVal = Math.max(Number(minVal.value), Math.min(Number(maxVal.value), val))

  // Send to MQTT
  mqtt.setOutput(props.channel, clampedVal)

  isEditing.value = false
}

function increment() {
  if (isDisabled.value) return
  const val = (currentValue.value ?? 0) + stepVal.value
  const clampedVal = Math.min(Number(maxVal.value), val)
  mqtt.setOutput(props.channel, clampedVal)
}

function decrement() {
  if (isDisabled.value) return
  const val = (currentValue.value ?? 0) - stepVal.value
  const clampedVal = Math.max(Number(minVal.value), val)
  mqtt.setOutput(props.channel, clampedVal)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    applyValue()
  } else if (e.key === 'Escape') {
    cancelEdit()
  }
}

// Knob rotation angle (0-270 degrees, starting from 225deg)
const knobAngle = computed(() => {
  if (currentValue.value === null) return 0
  const range = Number(maxVal.value) - Number(minVal.value)
  if (range <= 0) return 0
  const pct = (currentValue.value - Number(minVal.value)) / range
  return Math.max(0, Math.min(1, pct)) * 270  // 270 degree sweep
})

function onKnobMouseDown(e: MouseEvent) {
  if (isDisabled.value) return
  e.preventDefault()
  isDragging.value = true
  document.addEventListener('mousemove', onKnobMouseMove)
  document.addEventListener('mouseup', onKnobMouseUp)
}

function onKnobMouseMove(e: MouseEvent) {
  if (!isDragging.value || !knobElement.value) return

  const rect = knobElement.value.getBoundingClientRect()
  const centerX = rect.left + rect.width / 2
  const centerY = rect.top + rect.height / 2

  // Calculate angle from center (0 = right, counterclockwise positive)
  let angle = Math.atan2(centerY - e.clientY, e.clientX - centerX) * (180 / Math.PI)

  // Convert to our rotation system (start at 225deg = min, 270deg sweep clockwise)
  // Normalize angle to 0-360
  angle = (angle + 360) % 360

  // Map: 225deg = 0%, going clockwise to 315deg (through 0) = 100%
  // Remap so 225deg = 0, 315deg = 270 (full sweep)
  let mapped = angle - 225
  if (mapped < -45) mapped += 360  // Handle wrap around

  // Clamp to valid range
  const pct = Math.max(0, Math.min(1, mapped / 270))

  // Calculate and apply new value
  const range = Number(maxVal.value) - Number(minVal.value)
  const newVal = Number(minVal.value) + pct * range

  // Round to step
  const stepped = Math.round(newVal / stepVal.value) * stepVal.value
  const clamped = Math.max(Number(minVal.value), Math.min(Number(maxVal.value), stepped))

  mqtt.setOutput(props.channel, clamped)
}

function onKnobMouseUp() {
  isDragging.value = false
  document.removeEventListener('mousemove', onKnobMouseMove)
  document.removeEventListener('mouseup', onKnobMouseUp)
}
</script>

<template>
  <div class="setpoint-widget" :class="[visualStyle || 'standard', { disabled: isDisabled, blocked: isBlocked, warning: warningMessage }]" :style="containerStyle">
    <!-- Warning for misconfigured widget -->
    <div v-if="warningMessage" class="warning-message">{{ warningMessage }}</div>

    <!-- Standard style: +/- buttons -->
    <template v-else-if="!visualStyle || visualStyle === 'standard'">
      <!-- Compact horizontal layout (shown when short) -->
      <div class="layout-horizontal">
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
      </div>

      <!-- Vertical layout (shown when tall enough) -->
      <div class="layout-vertical">
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
      </div>
    </template>

    <!-- Knob style: rotary dial -->
    <template v-else-if="visualStyle === 'knob'">
      <div class="knob-container">
        <div
          ref="knobElement"
          class="knob"
          :class="{ dragging: isDragging }"
          @mousedown="onKnobMouseDown"
        >
          <div class="knob-body">
            <div class="knob-indicator" :style="{ transform: `rotate(${knobAngle - 135}deg)` }" />
            <div class="knob-cap" />
          </div>
          <div class="knob-scale">
            <div v-for="n in 11" :key="n" class="tick" :class="{ major: (n - 1) % 5 === 0 }" :style="{ transform: `rotate(${(n - 1) * 27 - 135}deg)` }" />
          </div>
        </div>
        <div class="knob-value" @click="startEdit">
          <template v-if="!isEditing">
            <span class="value">{{ displayValue }}</span>
            <span v-if="unit" class="unit">{{ unit }}</span>
          </template>
          <input
            v-else
            type="number"
            v-model="inputValue"
            :min="minVal"
            :max="maxVal"
            :step="stepVal"
            @blur="applyValue"
            @keydown="onKeydown"
            autofocus
            class="knob-input"
          />
        </div>
        <div class="knob-range">
          <span>{{ minVal }}</span>
          <span>{{ maxVal }}</span>
        </div>
      </div>
    </template>

    <InterlockBlockOverlay v-if="isBlocked" :blocked-by="blockStatus.blockedBy" />
  </div>
</template>

<style scoped>
.setpoint-widget {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
  gap: 2px;
  container-type: size;
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

.layout-horizontal .step-btn {
  width: 18px;
  height: 18px;
}

.layout-horizontal .value {
  font-size: 0.85rem;
}

.layout-vertical {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
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
  color: #aaa;
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
  border: 2px solid #dc2626;
  animation: pulse-blocked 2s ease-in-out infinite;
}

@keyframes pulse-blocked {
  0%, 100% { box-shadow: 0 0 4px rgba(220, 38, 38, 0.3); }
  50% { box-shadow: 0 0 12px rgba(220, 38, 38, 0.6); }
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

/* ========== KNOB STYLE ========== */
.knob-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 1;
  justify-content: center;
}

.knob {
  position: relative;
  width: 56px;
  height: 56px;
  cursor: grab;
}

.knob.dragging {
  cursor: grabbing;
}

.knob-body {
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3a3a5a 0%, #1a1a2e 50%, #2a2a4a 100%);
  border: 2px solid #4a4a6a;
  box-shadow:
    inset 0 2px 4px rgba(255,255,255,0.1),
    inset 0 -2px 4px rgba(0,0,0,0.3),
    0 2px 8px rgba(0,0,0,0.4);
}

.knob-indicator {
  position: absolute;
  top: 4px;
  left: 50%;
  width: 3px;
  height: 10px;
  margin-left: -1.5px;
  background: #60a5fa;
  border-radius: 1px;
  transform-origin: center calc(100% + 6px);
  box-shadow: 0 0 4px #60a5fa;
}

.knob-cap {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 12px;
  height: 12px;
  margin: -6px 0 0 -6px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4a4a6a 0%, #2a2a4a 100%);
  border: 1px solid #5a5a7a;
}

.knob-scale {
  position: absolute;
  inset: 0;
}

.knob-scale .tick {
  position: absolute;
  top: 0;
  left: 50%;
  width: 1px;
  height: 4px;
  margin-left: -0.5px;
  background: #555;
  transform-origin: center 28px;
}

.knob-scale .tick.major {
  height: 6px;
  width: 2px;
  margin-left: -1px;
  background: #777;
}

.knob-value {
  display: flex;
  align-items: baseline;
  gap: 2px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(255,255,255,0.03);
}

.knob-value:hover {
  background: rgba(255,255,255,0.08);
}

.knob-value .value {
  font-size: 0.85rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
}

.knob-value .unit {
  font-size: 0.55rem;
  color: #888;
}

.knob-input {
  width: 50px;
  background: transparent;
  border: 1px solid #3b82f6;
  border-radius: 2px;
  color: #fff;
  font-size: 0.8rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  text-align: center;
  outline: none;
  padding: 2px;
}

.knob-input::-webkit-inner-spin-button,
.knob-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.knob-range {
  display: flex;
  justify-content: space-between;
  width: 100%;
  font-size: 0.45rem;
  color: #555;
  padding: 0 4px;
}

/* Knob disabled state */
.setpoint-widget.knob.disabled .knob {
  cursor: not-allowed;
  opacity: 0.5;
}

.setpoint-widget.knob.disabled .knob-indicator {
  background: #666;
  box-shadow: none;
}

.setpoint-widget.knob.disabled .knob-value .value {
  color: #666;
}
</style>
