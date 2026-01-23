<script setup lang="ts">
/**
 * PidFaceplate - Runtime Popup for P&ID Symbols
 *
 * Similar to FactoryTalk View faceplates, this component shows a popup
 * when clicking a P&ID symbol in runtime mode (not edit mode).
 *
 * Features:
 * - Symbol info header (name, type, status)
 * - Current value with unit and status indicator
 * - Control section (toggle for DO, setpoint for AO)
 * - Mini trend chart (last N minutes)
 * - Active alarms for this channel
 * - Diagnostics info (quality, timestamps)
 */

import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { PidSymbol, ChannelConfig } from '../types'

const props = defineProps<{
  symbol: PidSymbol
  position: { x: number; y: number }
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'control', action: { type: string; value: any }): void
}>()

const store = useDashboardStore()

// Get channel config and value
const channelConfig = computed((): ChannelConfig | null => {
  if (!props.symbol.channel) return null
  return store.channels[props.symbol.channel] || null
})

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.values[props.symbol.channel] || null
})

// Format value display
const formattedValue = computed(() => {
  if (!channelValue.value) return '--'
  const val = channelValue.value.value
  if (typeof val !== 'number') return String(val)
  const decimals = props.symbol.decimals ?? channelConfig.value?.decimals ?? 2
  return val.toFixed(decimals)
})

const unit = computed(() => channelConfig.value?.unit || '')

// Status/quality indicator
const status = computed(() => {
  if (!channelValue.value) return 'disconnected'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  if (channelValue.value.disconnected) return 'disconnected'
  return 'normal'
})

// Control type based on channel type
const controlType = computed(() => {
  if (!channelConfig.value) return null
  switch (channelConfig.value.channel_type) {
    case 'digital_output':
      return 'toggle'
    case 'analog_output':
      return 'setpoint'
    default:
      return null
  }
})

// Engineering unit limits for setpoint control
// Priority: scaling config (engineering units) > raw hardware range
const setpointMin = computed(() => {
  const config = channelConfig.value
  if (!config) return 0

  // 4-20mA scaling: use eng_units_min
  if (config.four_twenty_scaling && config.eng_units_min !== undefined) {
    return config.eng_units_min
  }

  // Map scaling: use scaled_min
  if (config.scale_type === 'map' && config.scaled_min !== undefined) {
    return config.scaled_min
  }

  // Linear scaling: calculate from slope/offset
  if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
    const rawMin = config.pre_scaled_min ?? 0
    return rawMin * config.scale_slope + (config.scale_offset ?? 0)
  }

  // Fallback to raw range
  return 0
})

const setpointMax = computed(() => {
  const config = channelConfig.value
  if (!config) return 100

  // 4-20mA scaling: use eng_units_max
  if (config.four_twenty_scaling && config.eng_units_max !== undefined) {
    return config.eng_units_max
  }

  // Map scaling: use scaled_max
  if (config.scale_type === 'map' && config.scaled_max !== undefined) {
    return config.scaled_max
  }

  // Linear scaling: calculate from slope/offset
  if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
    const rawMax = Number(config.pre_scaled_max ?? config.voltage_range ?? 10)
    return rawMax * config.scale_slope + (config.scale_offset ?? 0)
  }

  // Fallback to raw range
  const range = config.voltage_range
  if (typeof range === 'number') return range
  return 10
})

// Setpoint control state
const setpointValue = ref(0)
const isEditing = ref(false)

// Initialize setpoint from current value
watch(() => channelValue.value?.value, (val) => {
  if (typeof val === 'number' && !isEditing.value) {
    setpointValue.value = val
  }
}, { immediate: true })

// Mini trend data (last 60 data points)
const trendData = ref<{ time: number; value: number }[]>([])
const MAX_TREND_POINTS = 60

// Update trend data
function updateTrend() {
  if (!channelValue.value || typeof channelValue.value.value !== 'number') return

  trendData.value.push({
    time: Date.now(),
    value: channelValue.value.value
  })

  // Keep only last N points
  if (trendData.value.length > MAX_TREND_POINTS) {
    trendData.value.shift()
  }
}

// Watch for value changes to update trend
watch(() => channelValue.value?.value, updateTrend, { immediate: true })

// Trend SVG path
const trendPath = computed(() => {
  if (trendData.value.length < 2) return ''

  const width = 200
  const height = 60
  const padding = 5

  // Find min/max for scaling
  const values = trendData.value.map(d => d.value)
  let minVal = Math.min(...values)
  let maxVal = Math.max(...values)

  // Add some padding to range
  const range = maxVal - minVal || 1
  minVal -= range * 0.1
  maxVal += range * 0.1

  // Build path
  const points = trendData.value.map((d, i) => {
    const x = padding + (i / (MAX_TREND_POINTS - 1)) * (width - 2 * padding)
    const y = height - padding - ((d.value - minVal) / (maxVal - minVal)) * (height - 2 * padding)
    return `${x},${y}`
  })

  return `M ${points.join(' L ')}`
})

// Control actions
function toggleOutput() {
  if (!props.symbol.channel) return
  const currentVal = channelValue.value?.value
  const newVal = currentVal === 1 ? 0 : 1
  emit('control', {
    type: 'set_digital_output',
    value: { channel: props.symbol.channel, value: newVal }
  })
}

function setAnalogOutput() {
  if (!props.symbol.channel) return
  // Clamp value to valid engineering unit range
  const clampedValue = Math.max(setpointMin.value, Math.min(setpointMax.value, setpointValue.value))
  emit('control', {
    type: 'set_analog_output',
    value: { channel: props.symbol.channel, value: clampedValue }
  })
  setpointValue.value = clampedValue
  isEditing.value = false
}

// Position style
const positionStyle = computed(() => ({
  left: `${props.position.x}px`,
  top: `${props.position.y}px`
}))

// Close on escape
function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="faceplate-overlay" @click.self="emit('close')">
    <div class="faceplate" :style="positionStyle">
      <!-- Header -->
      <div class="faceplate-header">
        <div class="header-info">
          <span class="symbol-label">{{ symbol.label || symbol.type }}</span>
          <span class="channel-name" v-if="symbol.channel">{{ symbol.channel }}</span>
        </div>
        <button class="close-btn" @click="emit('close')" title="Close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <!-- Value Display -->
      <div class="value-section" v-if="symbol.channel">
        <div class="value-display" :class="status">
          <span class="value">{{ formattedValue }}</span>
          <span class="unit">{{ unit }}</span>
        </div>
        <div class="status-indicator" :class="status">
          <span class="status-dot"></span>
          <span class="status-text">{{ status }}</span>
        </div>
      </div>

      <!-- No Channel Bound Message -->
      <div class="no-channel" v-else>
        <span>No channel bound to this symbol</span>
      </div>

      <!-- Mini Trend -->
      <div class="trend-section" v-if="symbol.channel && trendData.length > 1">
        <div class="section-label">Trend (Last {{ trendData.length }} samples)</div>
        <svg class="mini-trend" viewBox="0 0 200 60">
          <path :d="trendPath" class="trend-line" />
        </svg>
      </div>

      <!-- Control Section -->
      <div class="control-section" v-if="controlType">
        <div class="section-label">Control</div>

        <!-- Toggle for Digital Output -->
        <div v-if="controlType === 'toggle'" class="toggle-control">
          <button
            class="toggle-btn"
            :class="{ on: channelValue?.value === 1 }"
            @click="toggleOutput"
          >
            {{ channelValue?.value === 1 ? 'ON' : 'OFF' }}
          </button>
        </div>

        <!-- Setpoint for Analog Output -->
        <div v-if="controlType === 'setpoint'" class="setpoint-control">
          <input
            type="number"
            v-model.number="setpointValue"
            class="setpoint-input"
            :min="setpointMin"
            :max="setpointMax"
            :step="channelConfig?.step || 0.1"
            @focus="isEditing = true"
          />
          <span class="setpoint-unit">{{ unit }}</span>
          <button class="apply-btn" @click="setAnalogOutput" :disabled="!isEditing">
            Apply
          </button>
        </div>
        <div v-if="controlType === 'setpoint'" class="setpoint-range">
          {{ setpointMin.toFixed(1) }} - {{ setpointMax.toFixed(1) }} {{ unit }}
        </div>
      </div>

      <!-- Diagnostics -->
      <div class="diagnostics-section" v-if="channelValue">
        <div class="section-label">Diagnostics</div>
        <div class="diag-row">
          <span class="diag-label">Quality:</span>
          <span class="diag-value" :class="channelValue.quality || 'good'">
            {{ channelValue.quality || 'good' }}
          </span>
        </div>
        <div class="diag-row" v-if="channelValue.raw_value !== undefined">
          <span class="diag-label">Raw:</span>
          <span class="diag-value">{{ channelValue.raw_value?.toFixed(4) }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-label">Updated:</span>
          <span class="diag-value">{{ new Date(channelValue.timestamp).toLocaleTimeString() }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.faceplate-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 9999;
}

.faceplate {
  position: absolute;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border: 1px solid #3b5998;
  border-radius: 8px;
  min-width: 280px;
  max-width: 350px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  transform: translate(-50%, 10px);
}

.faceplate-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(59, 130, 246, 0.1);
  border-bottom: 1px solid #3b5998;
  border-radius: 8px 8px 0 0;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.symbol-label {
  font-weight: 600;
  color: #fff;
  font-size: 14px;
}

.channel-name {
  font-size: 11px;
  color: #60a5fa;
  font-family: 'JetBrains Mono', monospace;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

/* Value Section */
.value-section {
  padding: 16px;
  text-align: center;
  border-bottom: 1px solid #2a2a4a;
}

.value-display {
  font-family: 'JetBrains Mono', monospace;
  font-size: 32px;
  font-weight: 700;
  color: #fff;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
}

.value-display.alarm {
  color: #ef4444;
}

.value-display.warning {
  color: #f59e0b;
}

.value-display.disconnected {
  color: #6b7280;
}

.unit {
  font-size: 14px;
  font-weight: 400;
  color: #888;
}

.status-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 11px;
  text-transform: uppercase;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}

.status-indicator.alarm .status-dot { background: #ef4444; }
.status-indicator.warning .status-dot { background: #f59e0b; }
.status-indicator.disconnected .status-dot { background: #6b7280; }

.status-text {
  color: #888;
}

.status-indicator.alarm .status-text { color: #ef4444; }
.status-indicator.warning .status-text { color: #f59e0b; }

.no-channel {
  padding: 24px 16px;
  text-align: center;
  color: #666;
  font-style: italic;
  border-bottom: 1px solid #2a2a4a;
}

/* Section Labels */
.section-label {
  font-size: 10px;
  text-transform: uppercase;
  color: #666;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

/* Trend Section */
.trend-section {
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.mini-trend {
  width: 100%;
  height: 60px;
  background: #0f0f1a;
  border-radius: 4px;
}

.trend-line {
  fill: none;
  stroke: #60a5fa;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Control Section */
.control-section {
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.toggle-control {
  display: flex;
  justify-content: center;
}

.toggle-btn {
  padding: 10px 32px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  background: #374151;
  color: #fff;
}

.toggle-btn:hover {
  background: #4b5563;
}

.toggle-btn.on {
  background: #22c55e;
}

.toggle-btn.on:hover {
  background: #16a34a;
}

.setpoint-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.setpoint-input {
  flex: 1;
  padding: 8px 12px;
  background: #0f0f1a;
  border: 1px solid #3b5998;
  border-radius: 4px;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
}

.setpoint-input:focus {
  outline: none;
  border-color: #60a5fa;
}

.setpoint-unit {
  color: #888;
  font-size: 12px;
}

.apply-btn {
  padding: 8px 16px;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.apply-btn:hover:not(:disabled) {
  background: #2563eb;
}

.apply-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.setpoint-range {
  font-size: 10px;
  color: #666;
  text-align: center;
  margin-top: 6px;
}

/* Diagnostics Section */
.diagnostics-section {
  padding: 12px 16px;
}

.diag-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  padding: 2px 0;
}

.diag-label {
  color: #666;
}

.diag-value {
  color: #aaa;
  font-family: 'JetBrains Mono', monospace;
}

.diag-value.good { color: #22c55e; }
.diag-value.bad { color: #ef4444; }
.diag-value.uncertain { color: #f59e0b; }
</style>
