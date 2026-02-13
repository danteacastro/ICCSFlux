<script setup lang="ts">
/**
 * PidLoopWidget - PID Control Loop Faceplate
 *
 * Industrial-style PID loop display and control:
 * - PV (Process Variable) bar with setpoint indicator
 * - SP (Setpoint) entry
 * - CV (Control Variable) output display
 * - Auto/Manual mode toggle
 * - Tuning parameters display
 */

import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { WidgetStyle } from '../types'

interface PidLoopConfig {
  loopId: string
  loopName?: string
  pvMin?: number
  pvMax?: number
  showTuning?: boolean
}

const props = defineProps<{
  config?: PidLoopConfig
  style?: WidgetStyle
}>()

const mqtt = useMqtt('nisystem')

// PID loop state from backend
const loopStatus = ref<{
  id: string
  name: string
  enabled: boolean
  mode: 'auto' | 'manual'
  pv: number
  pv_channel: string
  setpoint: number
  output: number
  cv_channel: string | null
  error: number
  p_term: number
  i_term: number
  d_term: number
  output_saturated: boolean
  timestamp: string
} | null>(null)

// Local setpoint for editing
const localSetpoint = ref(0)
const isEditingSetpoint = ref(false)
const localOutput = ref(0)
const isEditingOutput = ref(false)

// Subscribe to loop status
const statusTopic = computed(() =>
  props.config?.loopId ? `nisystem/pid/loop/${props.config.loopId}/status` : null
)

// PV display range
const pvMin = computed(() => props.config?.pvMin ?? 0)
const pvMax = computed(() => props.config?.pvMax ?? 100)
const pvRange = computed(() => pvMax.value - pvMin.value)

// PV percentage for bar display
const pvPercent = computed(() => {
  if (!loopStatus.value || pvRange.value === 0) return 0
  return Math.max(0, Math.min(100,
    ((loopStatus.value.pv - pvMin.value) / pvRange.value) * 100
  ))
})

// Setpoint percentage for indicator
const spPercent = computed(() => {
  if (!loopStatus.value || pvRange.value === 0) return 0
  return Math.max(0, Math.min(100,
    ((loopStatus.value.setpoint - pvMin.value) / pvRange.value) * 100
  ))
})

// Mode display
const isAuto = computed(() => loopStatus.value?.mode === 'auto')

// Track unsubscribe function
let unsubscribe: (() => void) | null = null

// Handle incoming status messages
function handleStatus(payload: any) {
  if (payload) {
    loopStatus.value = payload
    // Update local values if not editing
    if (!isEditingSetpoint.value) {
      localSetpoint.value = payload.setpoint ?? 0
    }
    if (!isEditingOutput.value) {
      localOutput.value = payload.output ?? 0
    }
  }
}

// Subscribe to MQTT on mount
onMounted(() => {
  if (statusTopic.value) {
    unsubscribe = mqtt.subscribe(statusTopic.value, handleStatus)
  }
})

onUnmounted(() => {
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
})

// Watch for topic changes
watch(statusTopic, (newTopic, oldTopic) => {
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
  if (newTopic) {
    unsubscribe = mqtt.subscribe(newTopic, handleStatus)
  }
})

// Control actions
function toggleMode() {
  if (!props.config?.loopId) return
  const newMode = isAuto.value ? 'manual' : 'auto'
  mqtt.sendCommand(`pid/loop/${props.config.loopId}/mode`, { value: newMode })
}

function applySetpoint() {
  if (!props.config?.loopId) return
  mqtt.sendCommand(`pid/loop/${props.config.loopId}/setpoint`, { value: localSetpoint.value })
  isEditingSetpoint.value = false
}

function applyOutput() {
  if (!props.config?.loopId) return
  mqtt.sendCommand(`pid/loop/${props.config.loopId}/output`, { value: localOutput.value })
  isEditingOutput.value = false
}

function incrementSetpoint(delta: number) {
  localSetpoint.value = Math.round((localSetpoint.value + delta) * 10) / 10
  applySetpoint()
}

function incrementOutput(delta: number) {
  localOutput.value = Math.max(0, Math.min(100, localOutput.value + delta))
  applyOutput()
}

// Container style
const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})
</script>

<template>
  <div class="pid-loop-widget" :style="containerStyle">
    <!-- Header -->
    <div class="pid-header">
      <span class="loop-name">{{ loopStatus?.name || config?.loopName || 'PID Loop' }}</span>
      <button
        class="mode-btn"
        :class="{ auto: isAuto, manual: !isAuto }"
        @click="toggleMode"
        :title="isAuto ? 'Switch to Manual' : 'Switch to Auto'"
      >
        {{ isAuto ? 'AUTO' : 'MAN' }}
      </button>
    </div>

    <!-- PV Bar with SP indicator -->
    <div class="pv-section">
      <div class="pv-bar-container">
        <div class="pv-bar" :style="{ width: pvPercent + '%' }"></div>
        <div class="sp-indicator" :style="{ left: spPercent + '%' }"></div>
      </div>
      <div class="pv-labels">
        <span class="pv-value">PV: {{ loopStatus?.pv?.toFixed(1) ?? '--' }}</span>
        <span class="sp-value">SP: {{ loopStatus?.setpoint?.toFixed(1) ?? '--' }}</span>
      </div>
    </div>

    <!-- Setpoint Control -->
    <div class="control-row">
      <span class="control-label">Setpoint</span>
      <div class="control-input-group">
        <button class="adj-btn" @click="incrementSetpoint(-1)">-</button>
        <input
          type="number"
          v-model.number="localSetpoint"
          class="control-input"
          @focus="isEditingSetpoint = true"
          @blur="applySetpoint"
          @keyup.enter="applySetpoint"
        />
        <button class="adj-btn" @click="incrementSetpoint(1)">+</button>
      </div>
    </div>

    <!-- Output Display/Control -->
    <div class="control-row">
      <span class="control-label">Output</span>
      <div class="control-input-group" v-if="!isAuto">
        <button class="adj-btn" @click="incrementOutput(-5)">-</button>
        <input
          type="number"
          v-model.number="localOutput"
          class="control-input"
          @focus="isEditingOutput = true"
          @blur="applyOutput"
          @keyup.enter="applyOutput"
        />
        <button class="adj-btn" @click="incrementOutput(5)">+</button>
      </div>
      <div class="output-display" v-else>
        <div class="output-bar" :style="{ width: (loopStatus?.output ?? 0) + '%' }"></div>
        <span class="output-value">{{ loopStatus?.output?.toFixed(1) ?? '--' }}%</span>
      </div>
    </div>

    <!-- Tuning Info (optional) -->
    <div class="tuning-row" v-if="config?.showTuning && loopStatus">
      <span class="term">P: {{ loopStatus.p_term?.toFixed(2) }}</span>
      <span class="term">I: {{ loopStatus.i_term?.toFixed(2) }}</span>
      <span class="term">D: {{ loopStatus.d_term?.toFixed(2) }}</span>
    </div>

    <!-- Status indicators -->
    <div class="status-row">
      <span class="error-display" :class="{ negative: (loopStatus?.error ?? 0) < 0 }">
        Err: {{ loopStatus?.error?.toFixed(2) ?? '--' }}
      </span>
      <span class="saturated-indicator" v-if="loopStatus?.output_saturated" title="Output saturated">
        SAT
      </span>
    </div>
  </div>
</template>

<style scoped>
.pid-loop-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 6px;
  border: 1px solid var(--border-color);
  gap: 6px;
  font-size: 12px;
}

/* Header */
.pid-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.loop-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13px;
}

.mode-btn {
  padding: 3px 8px;
  border: none;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.mode-btn.auto {
  background: var(--color-success);
  color: var(--text-primary);
}

.mode-btn.manual {
  background: #f59e0b;
  color: #000;
}

.mode-btn:hover {
  opacity: 0.8;
}

/* PV Bar Section */
.pv-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pv-bar-container {
  position: relative;
  height: 20px;
  background: var(--bg-secondary);
  border-radius: 3px;
  overflow: hidden;
}

.pv-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--color-success), var(--color-accent));
  transition: width 0.3s ease;
}

.sp-indicator {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--color-error);
  transform: translateX(-50%);
  box-shadow: 0 0 4px var(--color-error);
}

.pv-labels {
  display: flex;
  justify-content: space-between;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.pv-value {
  color: var(--color-accent-light);
}

.sp-value {
  color: var(--color-error);
}

/* Control Rows */
.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.control-label {
  color: var(--text-secondary);
  font-size: 11px;
  min-width: 50px;
}

.control-input-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.adj-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 3px;
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.adj-btn:hover {
  background: var(--btn-secondary-hover);
}

.control-input {
  width: 60px;
  padding: 4px 6px;
  background: var(--bg-secondary);
  border: 1px solid #3b5998;
  border-radius: 3px;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  text-align: center;
}

.control-input:focus {
  outline: none;
  border-color: var(--color-accent-light);
}

/* Output Display (Auto mode) */
.output-display {
  position: relative;
  flex: 1;
  height: 24px;
  background: var(--bg-secondary);
  border-radius: 3px;
  overflow: hidden;
}

.output-bar {
  height: 100%;
  background: var(--color-accent);
  transition: width 0.3s ease;
}

.output-value {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-primary);
  text-shadow: 0 0 4px rgba(0,0,0,0.8);
}

/* Tuning Row */
.tuning-row {
  display: flex;
  justify-content: space-between;
  padding: 4px;
  background: var(--bg-secondary);
  border-radius: 3px;
}

.term {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-secondary);
}

/* Status Row */
.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.error-display {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-secondary);
}

.error-display.negative {
  color: #f59e0b;
}

.saturated-indicator {
  padding: 2px 6px;
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
}
</style>
