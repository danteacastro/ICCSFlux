<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'

const props = withDefaults(defineProps<{
  channel: string
  label?: string
  decimals?: number
  compact?: boolean
  industrial?: boolean
  showLabel?: boolean      // Show label - defaults to true
  showUnit?: boolean       // Show unit - defaults to true
  valueColor?: string
  backgroundColor?: string
  h?: number               // Grid height - auto-compact when h=1
  style?: {
    backgroundColor?: string
    textColor?: string
    [key: string]: any
  }
}>(), {
  showLabel: true,
  showUnit: true
})

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale — trust server-side quality flag (handles clock skew)
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  if (channelValue.value.quality === 'stale') return true
  return (Date.now() - channelValue.value.timestamp) > 15000
})

// Check if channel is disconnected (hardware not connected)
const isDisconnected = computed(() => {
  if (!channelValue.value) return false
  // Check for NaN value or disconnected flag
  return channelValue.value.disconnected ||
         channelValue.value.quality === 'bad' ||
         (typeof channelValue.value.value === 'number' && Number.isNaN(channelValue.value.value))
})

// Check for specific error types for better status indication
const isOpenTC = computed(() => channelValue.value?.openThermocouple || channelValue.value?.status === 'open_thermocouple')
const isOverflow = computed(() => channelValue.value?.overflow || channelValue.value?.status === 'overflow')

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  // Show specific error messages when available
  if (isDisconnected.value) {
    // Use human-readable error string if available
    if (channelValue.value.valueString) {
      return channelValue.value.valueString  // "Open TC", "Inf", "NaN"
    }
    return 'NaN'
  }
  if (isStale.value) return '--'
  const val = channelValue.value.value
  if (typeof val !== 'number' || Number.isNaN(val)) return 'NaN'
  const dec = props.decimals ?? 2
  return val.toFixed(dec)
})

const unit = computed(() => {
  return formatUnit(channelConfig.value?.unit)
})

// Label: use explicit label prop, or fall back to channel name (TAG)
// Strip "py." prefix for display — Python script outputs show as plain names
const displayLabel = computed(() =>
  (props.label || props.channel || '').replace(/^py\./, '')
)

const statusClass = computed(() => {
  // Specific error types first (more specific status)
  if (isOpenTC.value) return 'open-tc'
  if (isOverflow.value) return 'overflow'
  if (isDisconnected.value) return 'disconnected'
  if (!channelValue.value || isStale.value) return 'stale'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  return 'normal'
})

// Computed style classes (compact is automatic via CSS container queries)
const modeClasses = computed(() => ({
  industrial: props.industrial
}))

// Custom styles - support both direct props and style object
const customStyles = computed(() => {
  const styles: Record<string, string> = {}
  const bgColor = props.style?.backgroundColor || props.backgroundColor
  if (bgColor) {
    styles['--bg-widget'] = bgColor
  }
  const textColor = props.style?.textColor || props.valueColor
  if (textColor) {
    styles['--custom-value-color'] = textColor
  }
  return styles
})
</script>

<template>
  <div class="numeric-display" :class="[statusClass, modeClasses]" :style="customStyles">
    <!-- Compact horizontal layout (shown when short) -->
    <div class="layout-horizontal">
      <div class="label" v-if="showLabel">{{ displayLabel }}</div>
      <div class="value-container">
        <span class="value">{{ displayValue }}</span>
        <span class="unit" v-if="showUnit && unit">{{ unit }}</span>
      </div>
    </div>

    <!-- Vertical layout (shown when tall enough) -->
    <div class="layout-vertical">
      <div class="label" v-if="showLabel">{{ displayLabel }}</div>
      <div class="value-container">
        <span class="value">{{ displayValue }}</span>
        <span class="unit" v-if="showUnit && unit">{{ unit }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.numeric-display {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px 6px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  box-sizing: border-box;
  container-type: size;
}

/* ========================================
   LAYOUT SWITCHING VIA CONTAINER QUERIES
   ======================================== */

/* Default: show horizontal (compact), hide vertical */
.layout-horizontal {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.layout-horizontal .label {
  flex: 1 1 auto;
  min-width: 30px;
  text-align: left;
}

.layout-horizontal .value {
  font-size: 0.95rem;
}

.layout-horizontal .unit {
  font-size: 0.5rem;
}

.layout-vertical {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.layout-vertical .label {
  margin-bottom: 2px;
}

/* When tall enough (2+ rows ~60px), switch to vertical layout */
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
  line-height: 1.2;
}

.value-container {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.value {
  font-size: 1.1rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--value-color, #fff);
  line-height: 1;
}

.unit {
  font-size: 0.55rem;
  color: var(--text-secondary);
}

.normal .value {
  color: var(--color-success-light);
}

.stale .value {
  color: var(--text-muted);
}

/* Disconnected - hardware not connected (amber/orange) */
.disconnected {
  border-color: #f97316;
}
.disconnected .value {
  color: #f97316;
  font-style: italic;
}

/* Open Thermocouple - broken sensor (red with dashed border) */
.open-tc {
  border-color: #dc2626;
  border-style: dashed;
}
.open-tc .value {
  color: #dc2626;
  font-style: italic;
}

/* Overflow - value out of measurement range (purple) */
.overflow {
  border-color: #a855f7;
}
.overflow .value {
  color: #a855f7;
  font-style: italic;
}

.warning {
  border-color: var(--color-warning);
}
.warning .value {
  color: var(--color-warning);
}

.alarm {
  border-color: var(--color-error);
  animation: pulse-alarm 1s infinite;
}
.alarm .value {
  color: var(--color-error);
}

@keyframes pulse-alarm {
  0%, 100% { background-color: var(--bg-widget); }
  50% { background-color: var(--bg-alarm-pulse); }
}

/* ========================================
   INDUSTRIAL MODE - LabVIEW style
   ======================================== */
.industrial {
  border-radius: 0;
  border: 1px solid #444;
  background: #2a2a2a;
}

.industrial .label {
  color: #999;
  letter-spacing: 0.5px;
}

.industrial .value {
  font-family: 'Consolas', 'Courier New', monospace;
  font-weight: 700;
}

.industrial.normal {
  background: linear-gradient(180deg, var(--bg-armed) 0%, var(--bg-armed) 100%);
  border-color: #3a5a3a;
}

.industrial.normal .value {
  color: #7fff7f;
  text-shadow: 0 0 4px rgba(127, 255, 127, 0.3);
}

.industrial.stale {
  background: #2a2a2a;
  border-color: #444;
}

.industrial.disconnected {
  background: linear-gradient(180deg, #4a3a2d 0%, #2e251a 100%);
  border-color: #5a4a3a;
}

.industrial.disconnected .value {
  color: #f97316;
  font-style: italic;
}

.industrial.open-tc {
  background: linear-gradient(180deg, var(--bg-tripped) 0%, var(--bg-tripped) 100%);
  border-color: #dc2626;
  border-style: dashed;
}

.industrial.open-tc .value {
  color: #dc2626;
  font-style: italic;
}

.industrial.overflow {
  background: linear-gradient(180deg, #3d2d4a 0%, #251a2e 100%);
  border-color: #a855f7;
}

.industrial.overflow .value {
  color: #a855f7;
  font-style: italic;
}

.industrial.warning {
  background: linear-gradient(180deg, #4a4a2d 0%, #2e2e1a 100%);
  border-color: #5a5a3a;
}

.industrial.alarm {
  background: linear-gradient(180deg, var(--bg-tripped) 0%, var(--bg-tripped) 100%);
  border-color: #5a3a3a;
}

/* Industrial compact mode adjustments */
.industrial .layout-horizontal {
  padding: 0 2px;
}

.industrial .layout-horizontal .value {
  font-size: 0.85rem;
}

/* Custom value color override */
.numeric-display[style*="--custom-value-color"] .value {
  color: var(--custom-value-color) !important;
}
</style>
