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

import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useAuth } from '../composables/useAuth'
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
const safety = useSafety()
const auth = useAuth()

// Find interlocks explicitly bound to this symbol via interlockId
const channelInterlocks = computed(() => {
  if (!props.symbol.interlockId) return []
  const status = safety.interlockStatuses.value.find(s => s.id === props.symbol.interlockId)
  return status ? [status] : []
})

function bypassFromFaceplate(interlockId: string) {
  const interlock = safety.interlocks.value.find(i => i.id === interlockId)
  if (!interlock) return
  if (interlock.bypassed) {
    safety.bypassInterlock(interlockId, false, 'dashboard', 'Bypass removed from faceplate')
  } else {
    safety.bypassInterlock(interlockId, true, 'dashboard', 'Manual bypass from faceplate')
  }
}

function canBypassInterlock(interlockId: string): boolean {
  const interlock = safety.interlocks.value.find(i => i.id === interlockId)
  return !!(interlock?.bypassAllowed && auth.isSupervisor.value)
}

// Get channel config and value
const channelConfig = computed((): ChannelConfig | null => {
  if (!props.symbol.channel) return null
  return store.channels[props.symbol.channel] || null
})

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.getChannelRef(props.symbol.channel).value || null
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

// Navigate to widget showing same channel (#6.3)
const linkedWidget = computed(() => {
  if (!props.symbol.channel) return null
  for (const page of store.pages) {
    for (const widget of page.widgets || []) {
      if (widget.channel === props.symbol.channel || widget.channels?.includes(props.symbol.channel)) {
        return { pageId: page.id, pageName: page.name, widgetId: widget.id }
      }
    }
  }
  return null
})

function navigateToWidget() {
  if (!linkedWidget.value) return
  store.currentPageId = linkedWidget.value.pageId
  emit('close')
}

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

// Auxiliary channels — multi-register equipment display
const auxChannelValues = computed(() => {
  if (!props.symbol.auxiliaryChannels?.length) return []
  return props.symbol.auxiliaryChannels.map(aux => {
    const val = aux.channel ? store.getChannelRef(aux.channel).value : null
    const config = aux.channel ? store.channels[aux.channel] : null
    let formatted = '--'
    if (val && typeof val.value === 'number') {
      formatted = val.value.toFixed(aux.decimals ?? config?.decimals ?? 2)
    } else if (val) {
      formatted = String(val.value)
    }
    const displayUnit = aux.unit || config?.unit || ''
    return {
      ...aux,
      value: val,
      formatted,
      displayUnit,
      status: val?.alarm ? 'alarm' : val?.warning ? 'warning' : val?.disconnected ? 'disconnected' : 'normal',
    }
  })
})

// Write auxiliary channel value (for writable channels like setpoints)
function writeAuxChannel(channelName: string, value: number) {
  emit('control', {
    type: 'set_analog_output',
    value: { channel: channelName, value }
  })
}

function toggleAuxChannel(channelName: string, currentVal: number | undefined) {
  emit('control', {
    type: 'set_digital_output',
    value: { channel: channelName, value: currentVal === 1 ? 0 : 1 }
  })
}

// Position with viewport clamping
const faceplateRef = ref<HTMLElement | null>(null)
const clampedPosition = ref({ x: props.position.x, y: props.position.y })

const positionStyle = computed(() => ({
  left: `${clampedPosition.value.x}px`,
  top: `${clampedPosition.value.y}px`
}))

// Close on escape
function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)

  // Clamp faceplate position to stay within viewport after render
  nextTick(() => {
    if (!faceplateRef.value) return
    const rect = faceplateRef.value.getBoundingClientRect()
    const margin = 10
    let x = props.position.x
    let y = props.position.y

    // The faceplate uses transform: translate(-50%, 10px) so center is at x
    const halfW = rect.width / 2
    if (x - halfW < margin) x = halfW + margin
    if (x + halfW > window.innerWidth - margin) x = window.innerWidth - halfW - margin
    if (y + rect.height + 10 > window.innerHeight - margin) {
      // Flip above the click point
      y = y - rect.height - 20
    }
    if (y < margin) y = margin

    clampedPosition.value = { x, y }
  })
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="faceplate-overlay" @click.self="emit('close')">
    <div ref="faceplateRef" class="faceplate" :style="positionStyle">
      <!-- Header -->
      <div class="faceplate-header">
        <div class="header-info">
          <span class="symbol-label">{{ symbol.label || symbol.type }}</span>
          <span class="channel-name" v-if="symbol.channel">{{ symbol.channel }}</span>
        </div>
        <button v-if="linkedWidget" class="goto-widget-btn" @click="navigateToWidget" :title="'Go to widget on ' + linkedWidget.pageName">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
          </svg>
        </button>
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

      <!-- Auxiliary Channels (multi-register equipment) -->
      <div class="aux-section" v-if="auxChannelValues.length > 0">
        <div class="section-label">Channels</div>
        <div v-for="(aux, idx) in auxChannelValues" :key="idx" class="aux-row" :class="aux.status">
          <span class="aux-label">{{ aux.label }}</span>
          <span class="aux-value" :class="aux.status">{{ aux.formatted }}</span>
          <span class="aux-unit">{{ aux.displayUnit }}</span>
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

      <!-- Interlocks Section -->
      <div class="interlocks-section" v-if="channelInterlocks.length > 0">
        <div class="section-label">Interlocks</div>
        <div v-for="ilStatus in channelInterlocks" :key="ilStatus.id" class="interlock-row">
          <div class="il-header">
            <span class="il-status-dot" :class="{
              satisfied: ilStatus.satisfied && !ilStatus.bypassed,
              failed: !ilStatus.satisfied && !ilStatus.bypassed,
              bypassed: ilStatus.bypassed
            }"></span>
            <span class="il-name">{{ ilStatus.name }}</span>
            <span class="il-state" :class="{
              'state-ok': ilStatus.satisfied && !ilStatus.bypassed,
              'state-fail': !ilStatus.satisfied && !ilStatus.bypassed,
              'state-bypass': ilStatus.bypassed
            }">{{ ilStatus.bypassed ? 'BYPASSED' : ilStatus.satisfied ? 'OK' : 'FAILED' }}</span>
          </div>
          <div v-if="!ilStatus.satisfied && ilStatus.failedConditions.length > 0" class="il-failures">
            <div v-for="(fc, idx) in ilStatus.failedConditions" :key="idx" class="il-failure-row">
              {{ fc.reason }}
            </div>
          </div>
          <button
            v-if="canBypassInterlock(ilStatus.id)"
            class="il-bypass-btn"
            :class="{ active: ilStatus.bypassed }"
            @click.stop="bypassFromFaceplate(ilStatus.id)"
          >
            {{ ilStatus.bypassed ? 'Remove Bypass' : 'Bypass' }}
          </button>
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
  background: linear-gradient(135deg, var(--bg-widget) 0%, var(--bg-elevated) 100%);
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
  background: var(--color-accent-bg);
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
  color: var(--text-primary);
  font-size: 14px;
}

.channel-name {
  font-size: 11px;
  color: var(--color-accent-light);
  font-family: 'JetBrains Mono', monospace;
}

.goto-widget-btn {
  background: none;
  border: none;
  color: var(--color-accent-light);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.goto-widget-btn:hover {
  background: rgba(59, 130, 246, 0.15);
  color: #93c5fd;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

/* Value Section */
.value-section {
  padding: 16px;
  text-align: center;
  border-bottom: 1px solid var(--border-color);
}

.value-display {
  font-family: 'JetBrains Mono', monospace;
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
}

.value-display.alarm {
  color: var(--color-error);
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
  color: var(--text-secondary);
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
  background: var(--color-success);
}

.status-indicator.alarm .status-dot { background: var(--color-error); }
.status-indicator.warning .status-dot { background: #f59e0b; }
.status-indicator.disconnected .status-dot { background: #6b7280; }

.status-text {
  color: var(--text-secondary);
}

.status-indicator.alarm .status-text { color: var(--color-error); }
.status-indicator.warning .status-text { color: #f59e0b; }

.no-channel {
  padding: 24px 16px;
  text-align: center;
  color: var(--text-muted);
  font-style: italic;
  border-bottom: 1px solid var(--border-color);
}

/* Section Labels */
.section-label {
  font-size: 10px;
  text-transform: uppercase;
  color: var(--text-muted);
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

/* Trend Section */
.trend-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.mini-trend {
  width: 100%;
  height: 60px;
  background: var(--bg-secondary);
  border-radius: 4px;
}

.trend-line {
  fill: none;
  stroke: var(--color-accent-light);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Control Section */
.control-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
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
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
}

.toggle-btn:hover {
  background: var(--btn-secondary-hover);
}

.toggle-btn.on {
  background: var(--color-success);
  color: var(--text-primary);
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
  background: var(--bg-secondary);
  border: 1px solid #3b5998;
  border-radius: 4px;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
}

.setpoint-input:focus {
  outline: none;
  border-color: var(--color-accent-light);
}

.setpoint-unit {
  color: var(--text-secondary);
  font-size: 12px;
}

.apply-btn {
  padding: 8px 16px;
  background: var(--color-accent);
  color: var(--text-primary);
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.apply-btn:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

.apply-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.setpoint-range {
  font-size: 10px;
  color: var(--text-muted);
  text-align: center;
  margin-top: 6px;
}

/* Auxiliary Channels Section */
.aux-section {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.aux-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 0;
  font-size: 12px;
}
.aux-label {
  color: var(--text-secondary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aux-value {
  font-family: 'Fira Code', monospace;
  font-weight: 600;
  color: var(--text-bright);
}
.aux-value.alarm { color: var(--color-error); }
.aux-value.warning { color: #f59e0b; }
.aux-value.disconnected { color: var(--text-dim); }
.aux-unit {
  color: var(--text-dim);
  font-size: 10px;
  min-width: 24px;
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
  color: var(--text-muted);
}

.diag-value {
  color: #aaa;
  font-family: 'JetBrains Mono', monospace;
}

.diag-value.good { color: var(--color-success); }
.diag-value.bad { color: var(--color-error); }
.diag-value.uncertain { color: #f59e0b; }

/* Interlocks Section */
.interlocks-section {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.interlock-row {
  padding: 6px 0;
  border-bottom: 1px solid #1a1a3a;
}

.interlock-row:last-child {
  border-bottom: none;
}

.il-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.il-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #6b7280;
}

.il-status-dot.satisfied { background: var(--color-success); }
.il-status-dot.failed { background: var(--color-error); }
.il-status-dot.bypassed { background: #f59e0b; }

.il-name {
  color: #ddd;
  font-size: 12px;
  font-weight: 500;
  flex: 1;
}

.il-state {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.il-state.state-ok { color: var(--color-success); }
.il-state.state-fail { color: var(--color-error); }
.il-state.state-bypass { color: #f59e0b; }

.il-failures {
  margin-top: 4px;
  padding-left: 14px;
}

.il-failure-row {
  font-size: 10px;
  color: var(--color-error);
  padding: 1px 0;
}

.il-bypass-btn {
  margin-top: 4px;
  padding: 3px 8px;
  font-size: 10px;
  border: 1px solid #f59e0b;
  background: transparent;
  color: #f59e0b;
  border-radius: 3px;
  cursor: pointer;
}

.il-bypass-btn:hover {
  background: rgba(245, 158, 11, 0.1);
}

.il-bypass-btn.active {
  background: #f59e0b;
  color: #000;
}
</style>
