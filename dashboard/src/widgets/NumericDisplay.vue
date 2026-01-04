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

// Check if data is stale (no update in last 5 seconds) or system not acquiring
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

// Check if channel is disconnected (hardware not connected)
const isDisconnected = computed(() => {
  if (!channelValue.value) return false
  // Check for NaN value or disconnected flag
  return channelValue.value.disconnected ||
         channelValue.value.quality === 'bad' ||
         (typeof channelValue.value.value === 'number' && Number.isNaN(channelValue.value.value))
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  if (isDisconnected.value) return 'NaN'  // Show NaN when disconnected
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
const displayLabel = computed(() =>
  props.label || props.channel
)

const statusClass = computed(() => {
  if (isDisconnected.value) return 'disconnected'
  if (!channelValue.value || isStale.value) return 'stale'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  return 'normal'
})

// Computed style classes
const modeClasses = computed(() => ({
  compact: props.compact,
  industrial: props.industrial
}))

// Custom styles - support both direct props and style object
const customStyles = computed(() => {
  const styles: Record<string, string> = {}
  const bgColor = props.style?.backgroundColor || props.backgroundColor
  if (bgColor) {
    styles['--widget-bg'] = bgColor
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
    <div class="label" v-if="showLabel">{{ displayLabel }}</div>
    <div class="value-container">
      <span class="value">{{ displayValue }}</span>
      <span class="unit" v-if="showUnit && unit">{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.numeric-display {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 100%;
  padding: 4px 6px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  box-sizing: border-box;
}

.label {
  font-size: 0.6rem;
  color: #aaa;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  line-height: 1.2;
  margin-bottom: 2px;
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
  color: #888;
}

.normal .value {
  color: #4ade80;
}

.stale .value {
  color: #666;
}

/* Disconnected - hardware not connected (amber/orange) */
.disconnected {
  border-color: #f97316;
}
.disconnected .value {
  color: #f97316;
  font-style: italic;
}

.warning {
  border-color: #fbbf24;
}
.warning .value {
  color: #fbbf24;
}

.alarm {
  border-color: #ef4444;
  animation: pulse-alarm 1s infinite;
}
.alarm .value {
  color: #ef4444;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: var(--widget-bg, #1a1a2e); }
  50% { background-color: #3f1515; }
}

/* ========================================
   COMPACT MODE - horizontal layout
   ======================================== */
.compact {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  padding: 2px 8px;
  gap: 8px;
}

.compact .label {
  margin-bottom: 0;
  font-size: 0.6rem;
}

.compact .value {
  font-size: 0.95rem;
}

.compact .unit {
  font-size: 0.5rem;
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
  background: linear-gradient(180deg, #2d4a2d 0%, #1a2e1a 100%);
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

.industrial.warning {
  background: linear-gradient(180deg, #4a4a2d 0%, #2e2e1a 100%);
  border-color: #5a5a3a;
}

.industrial.alarm {
  background: linear-gradient(180deg, #4a2d2d 0%, #2e1a1a 100%);
  border-color: #5a3a3a;
}

/* Compact + Industrial combo */
.compact.industrial {
  padding: 2px 6px;
}

.compact.industrial .value {
  font-size: 0.85rem;
}

/* Custom value color override */
.numeric-display[style*="--custom-value-color"] .value {
  color: var(--custom-value-color) !important;
}
</style>
