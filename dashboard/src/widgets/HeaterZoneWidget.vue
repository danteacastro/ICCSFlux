<script setup lang="ts">
/**
 * HeaterZoneWidget - SLM1-C Temperature Controller Faceplate
 *
 * Replicates a LabVIEW heater zone faceplate:
 * - Toggle on/off at top
 * - Title/label below
 * - Setpoint (editable) on left, PV (read-only) on right
 * - Optional output % bar
 * - Right-click for advanced SLM1-C parameters modal
 */

import { ref, computed, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useSafety } from '../composables/useSafety'
import InterlockBlockOverlay from '../components/InterlockBlockOverlay.vue'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  widgetId: string
  pvChannel?: string
  spChannel?: string
  enableChannel?: string
  outputChannel?: string
  label?: string
  decimals?: number
  spMin?: number
  spMax?: number
  temperatureUnit?: 'F' | 'C'
  advancedParams?: Array<{
    channel: string
    label: string
    readonly?: boolean
  }>
  h?: number
  style?: WidgetStyle
}>()

const emit = defineEmits<{
  (e: 'configure'): void
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()

// Channel data
const pvValue = computed(() => props.pvChannel ? store.getChannelRef(props.pvChannel).value : undefined)
const spValue = computed(() => props.spChannel ? store.getChannelRef(props.spChannel).value : undefined)
const enableValue = computed(() => props.enableChannel ? store.getChannelRef(props.enableChannel).value : undefined)
const outputValue = computed(() => props.outputChannel ? store.getChannelRef(props.outputChannel).value : undefined)

// State
const isEnabled = computed(() => {
  if (!enableValue.value) return false
  return enableValue.value.value !== 0
})

const hasAlarm = computed(() => {
  if (!pvValue.value) return false
  return pvValue.value.alarm === true || pvValue.value.warning === true
})

const hasWarning = computed(() => {
  if (!pvValue.value) return false
  return pvValue.value.warning === true && !pvValue.value.alarm
})

// Safety checks
const enableBlockStatus = computed(() =>
  props.enableChannel ? safety.isOutputBlocked(props.enableChannel) : { blocked: false, blockedBy: [] }
)
const spBlockStatus = computed(() =>
  props.spChannel ? safety.isOutputBlocked(props.spChannel) : { blocked: false, blockedBy: [] }
)
const isBlocked = computed(() => enableBlockStatus.value.blocked || spBlockStatus.value.blocked)
const isDisabled = computed(() => !store.isConnected || !store.isAcquiring || isBlocked.value)

// Display values
const dec = computed(() => props.decimals ?? 1)
const unitSymbol = computed(() => props.temperatureUnit === 'C' ? '°C' : '°F')

const displayLabel = computed(() => props.label || 'Heater Zone')

const displayPv = computed(() => {
  if (!pvValue.value) return '--'
  const v = pvValue.value.value
  return typeof v === 'number' ? v.toFixed(dec.value) : String(v)
})

const displaySp = computed(() => {
  if (!spValue.value) return '--'
  const v = spValue.value.value
  return typeof v === 'number' ? v.toFixed(dec.value) : String(v)
})

const outputPercent = computed(() => {
  if (!outputValue.value) return 0
  const v = outputValue.value.value
  return typeof v === 'number' ? Math.max(0, Math.min(100, v)) : 0
})

const displayOutput = computed(() => outputPercent.value.toFixed(0))

const pvColorClass = computed(() => {
  if (hasAlarm.value) return 'alarm'
  if (hasWarning.value) return 'warning'
  return ''
})

// Container style
const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

// --- Toggle logic ---
const showConfirm = ref(false)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

function clearConfirmTimer() {
  if (confirmTimer) {
    clearTimeout(confirmTimer)
    confirmTimer = null
  }
}

function toggleEnable() {
  if (isDisabled.value || !props.enableChannel) return
  const turningOn = !isEnabled.value

  // Require confirmation for turning ON (dangerous direction)
  if (turningOn && !showConfirm.value) {
    showConfirm.value = true
    clearConfirmTimer()
    confirmTimer = setTimeout(() => { showConfirm.value = false }, 3000)
    return
  }

  showConfirm.value = false
  clearConfirmTimer()
  mqtt.setOutput(props.enableChannel, turningOn ? 1 : 0)
}

function confirmOn() {
  if (!props.enableChannel) return
  clearConfirmTimer()
  showConfirm.value = false
  mqtt.setOutput(props.enableChannel, 1)
}

function cancelConfirm() {
  clearConfirmTimer()
  showConfirm.value = false
}

// --- Setpoint editing ---
const isEditingSp = ref(false)
const localSpValue = ref('')

function startEditSp() {
  if (isDisabled.value || !props.spChannel) return
  const current = spValue.value?.value
  localSpValue.value = typeof current === 'number' ? current.toFixed(dec.value) : '0'
  isEditingSp.value = true
}

function applySetpoint() {
  if (!props.spChannel) return
  let val = parseFloat(localSpValue.value)
  if (isNaN(val)) {
    isEditingSp.value = false
    return
  }
  const min = props.spMin ?? -Infinity
  const max = props.spMax ?? Infinity
  val = Math.max(min, Math.min(max, val))
  mqtt.setOutput(props.spChannel, val)
  isEditingSp.value = false
}

function cancelEditSp() {
  isEditingSp.value = false
}

function onSpKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') applySetpoint()
  if (e.key === 'Escape') cancelEditSp()
}

// --- Advanced parameters modal ---
const showAdvanced = ref(false)

function openAdvanced(e: MouseEvent) {
  e.preventDefault()
  if (props.advancedParams && props.advancedParams.length > 0) {
    showAdvanced.value = true
  }
}

function getParamValue(channel: string): string {
  const v = store.values[channel]
  if (!v) return '--'
  return typeof v.value === 'number' ? v.value.toFixed(dec.value) : String(v.value)
}

function setParamValue(channel: string, event: Event) {
  const input = event.target as HTMLInputElement
  const val = parseFloat(input.value)
  if (!isNaN(val)) {
    mqtt.setOutput(channel, val)
  }
}

onUnmounted(() => clearConfirmTimer())
</script>

<template>
  <div
    class="heater-zone-widget"
    :class="{ disabled: isDisabled, blocked: isBlocked, on: isEnabled, alarm: hasAlarm }"
    :style="containerStyle"
    @contextmenu="openAdvanced"
  >
    <!-- Header: Toggle + Label -->
    <div class="hz-header">
      <template v-if="!showConfirm">
        <button
          class="hz-toggle"
          :class="{ on: isEnabled }"
          @click="toggleEnable"
          :disabled="isDisabled"
          :title="isEnabled ? 'Turn OFF' : 'Turn ON'"
        >
          <span class="hz-toggle-track">
            <span class="hz-toggle-thumb"></span>
          </span>
        </button>
      </template>
      <template v-else>
        <div class="hz-confirm">
          <span class="hz-confirm-text">Turn ON?</span>
          <button class="hz-confirm-btn yes" @click="confirmOn">Yes</button>
          <button class="hz-confirm-btn no" @click="cancelConfirm">No</button>
        </div>
      </template>
      <span class="hz-label">{{ displayLabel }}</span>
    </div>

    <!-- Values: SP and PV side by side -->
    <div class="hz-values">
      <div class="hz-sp" @click="startEditSp" :title="isDisabled ? '' : 'Click to edit setpoint'">
        <span class="hz-value-label">SP</span>
        <template v-if="!isEditingSp">
          <span class="hz-value sp-value">{{ displaySp }}</span>
        </template>
        <input
          v-else
          type="number"
          v-model="localSpValue"
          @blur="applySetpoint"
          @keydown="onSpKeydown"
          class="hz-input"
          ref="spInput"
          autofocus
        />
        <span class="hz-unit">{{ unitSymbol }}</span>
      </div>
      <div class="hz-pv">
        <span class="hz-value-label">PV</span>
        <span class="hz-value pv-value" :class="pvColorClass">{{ displayPv }}</span>
        <span class="hz-unit">{{ unitSymbol }}</span>
      </div>
    </div>

    <!-- Optional: Output % bar -->
    <div v-if="outputChannel" class="hz-output-bar">
      <div class="hz-output-fill" :style="{ width: outputPercent + '%' }"></div>
      <span class="hz-output-text">{{ displayOutput }}%</span>
    </div>

    <!-- Interlock overlay -->
    <InterlockBlockOverlay v-if="isBlocked" :blocked-by="enableBlockStatus.blockedBy" />

    <!-- Advanced Parameters Modal -->
    <Teleport to="body">
      <div v-if="showAdvanced" class="hz-modal-overlay" @click.self="showAdvanced = false">
        <div class="hz-advanced-modal">
          <div class="hz-modal-header">
            <h3>{{ displayLabel }} - Advanced</h3>
            <button class="hz-modal-close" @click="showAdvanced = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          <div class="hz-modal-body">
            <div v-for="param in advancedParams" :key="param.channel" class="hz-param-row">
              <span class="hz-param-label">{{ param.label }}</span>
              <template v-if="param.readonly">
                <span class="hz-param-value">{{ getParamValue(param.channel) }}</span>
              </template>
              <template v-else>
                <input
                  type="number"
                  :value="getParamValue(param.channel)"
                  @change="setParamValue(param.channel, $event)"
                  class="hz-param-input"
                  :disabled="isDisabled"
                />
              </template>
            </div>
            <p v-if="!advancedParams?.length" class="hz-no-params">
              No advanced parameters configured. Add them in widget settings.
            </p>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.heater-zone-widget {
  container-type: size;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 8px;
  gap: 6px;
  border-radius: 6px;
  border: 2px solid var(--border-heavy);
  background: var(--bg-widget);
  transition: border-color 0.3s;
  position: relative;
  overflow: hidden;
  box-sizing: border-box;
}

.heater-zone-widget.on {
  border-color: var(--color-success);
}

.heater-zone-widget.alarm {
  border-color: var(--color-error);
}

.heater-zone-widget.disabled {
  opacity: 0.6;
}

/* Header */
.hz-header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}

.hz-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

/* Toggle switch */
.hz-toggle {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  flex-shrink: 0;
}

.hz-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.hz-toggle-track {
  display: flex;
  align-items: center;
  width: 36px;
  height: 20px;
  border-radius: 10px;
  background: var(--btn-secondary-hover);
  padding: 2px;
  transition: background 0.2s;
}

.hz-toggle.on .hz-toggle-track {
  background: var(--color-success);
}

.hz-toggle-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.hz-toggle.on .hz-toggle-thumb {
  transform: translateX(16px);
}

/* Confirmation */
.hz-confirm {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.hz-confirm-text {
  font-size: 11px;
  color: #fbbf24;
  font-weight: 600;
}

.hz-confirm-btn {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid;
  cursor: pointer;
  font-weight: 600;
}

.hz-confirm-btn.yes {
  background: var(--color-success);
  border-color: var(--color-success);
  color: #000;
}

.hz-confirm-btn.no {
  background: transparent;
  border-color: var(--text-muted);
  color: var(--text-bright);
}

/* Values */
.hz-values {
  display: flex;
  gap: 8px;
  flex: 1;
  align-items: center;
  justify-content: center;
}

.hz-sp, .hz-pv {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.hz-sp {
  cursor: pointer;
}

.heater-zone-widget.disabled .hz-sp {
  cursor: default;
}

.hz-value-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.hz-value {
  font-size: 20px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  line-height: 1.2;
}

.sp-value {
  color: #4ade80;
}

.pv-value {
  color: #60a5fa;
}

.pv-value.warning {
  color: #fbbf24;
}

.pv-value.alarm {
  color: #ef4444;
}

.hz-unit {
  font-size: 10px;
  color: var(--text-muted);
}

.hz-input {
  width: 70px;
  font-size: 18px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  background: var(--bg-input);
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  color: #4ade80;
  text-align: center;
  padding: 2px 4px;
  outline: none;
}

.hz-input:focus {
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);
}

/* Output bar */
.hz-output-bar {
  height: 14px;
  background: var(--bg-elevated);
  border-radius: 3px;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
}

.hz-output-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.hz-output-text {
  position: absolute;
  top: 0;
  right: 4px;
  font-size: 10px;
  color: var(--text-bright);
  line-height: 14px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Container queries for compact layout */
@container (max-height: 100px) {
  .hz-value {
    font-size: 16px;
  }
  .hz-output-bar {
    display: none;
  }
}

@container (max-height: 70px) {
  .hz-values {
    flex-direction: row;
  }
  .hz-value-label {
    display: none;
  }
  .hz-value {
    font-size: 14px;
  }
}

/* Advanced Modal */
.hz-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.hz-advanced-modal {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  width: 360px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.hz-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.hz-modal-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--color-accent-light);
  font-weight: 600;
}

.hz-modal-close {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.hz-modal-close:hover {
  color: var(--text-primary);
}

.hz-modal-body {
  padding: 12px 16px;
}

.hz-param-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--bg-elevated);
}

.hz-param-row:last-child {
  border-bottom: none;
}

.hz-param-label {
  font-size: 12px;
  color: var(--text-bright);
  flex: 1;
}

.hz-param-value {
  font-size: 13px;
  color: #60a5fa;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-weight: 600;
}

.hz-param-input {
  width: 80px;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: #4ade80;
  text-align: right;
  padding: 3px 6px;
  outline: none;
}

.hz-param-input:focus {
  border-color: var(--color-accent);
}

.hz-param-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hz-no-params {
  color: var(--text-dim);
  font-size: 12px;
  font-style: italic;
  text-align: center;
  padding: 12px 0;
  margin: 0;
}
</style>
