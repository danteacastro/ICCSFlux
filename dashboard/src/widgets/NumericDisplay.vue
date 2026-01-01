<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  channel: string
  label?: string
  decimals?: number
  compact?: boolean        // Compact mode: horizontal layout, smaller
  industrial?: boolean     // Industrial theme: flat, square, dense
  showLabel?: boolean      // Show/hide label (default true)
  showUnit?: boolean       // Show/hide unit (default true)
  valueColor?: string      // Custom value color
  backgroundColor?: string // Custom background color
}>()

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale (no update in last 5 seconds) or system not acquiring
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  if (isStale.value) return '--'
  const val = channelValue.value.value
  const dec = props.decimals ?? 2
  return val.toFixed(dec)
})

const unit = computed(() => {
  // Channel config uses 'unit' (singular) - mapped from backend 'units' in useMqtt.ts
  return channelConfig.value?.unit || ''
})

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const statusClass = computed(() => {
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

// Custom styles
const customStyles = computed(() => {
  const styles: Record<string, string> = {}
  if (props.backgroundColor) {
    styles['--widget-bg'] = props.backgroundColor
  }
  if (props.valueColor) {
    styles['--custom-value-color'] = props.valueColor
  }
  return styles
})

</script>

<template>
  <div class="numeric-display" :class="[statusClass, modeClasses]" :style="customStyles">
    <div class="label">{{ displayLabel }}</div>
    <div class="value-container">
      <span class="value">{{ displayValue }}</span>
      <span class="unit" v-if="unit">{{ unit }}</span>
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
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.label {
  font-size: 0.7rem;
  color: var(--label-color, #888);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.value-container {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.value {
  font-size: 1.4rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--value-color, #fff);
}

.unit {
  font-size: 0.7rem;
  color: var(--unit-color, #888);
}

.normal .value {
  color: #4ade80;
}

.stale .value {
  color: #666;
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
  0%, 100% { background-color: #1a1a2e; }
  50% { background-color: #3f1515; }
}

/* ========================================
   COMPACT MODE
   Horizontal layout, smaller, denser
   ======================================== */
.compact {
  flex-direction: row;
  justify-content: space-between;
  padding: 2px 6px;
  gap: 4px;
}

.compact .label {
  font-size: 0.65rem;
  margin: 0;
  flex-shrink: 0;
}

.compact .value-container {
  flex-shrink: 0;
}

.compact .value {
  font-size: 0.9rem;
}

.compact .unit {
  font-size: 0.6rem;
}

/* ========================================
   INDUSTRIAL MODE
   Flat, square, LabVIEW-style
   ======================================== */
.industrial {
  border-radius: 0;
  border: 1px solid #444;
  background: #2a2a2a;
}

.industrial .label {
  font-size: 0.6rem;
  color: #aaa;
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
  padding: 1px 4px;
  border-width: 1px;
}

.compact.industrial .value {
  font-size: 0.85rem;
}

/* Custom value color override */
.numeric-display[style*="--custom-value-color"] .value {
  color: var(--custom-value-color) !important;
}
</style>
