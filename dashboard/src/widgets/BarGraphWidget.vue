<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  channel: string
  label?: string
  minValue?: number
  maxValue?: number
  orientation?: 'horizontal' | 'vertical'
  showValue?: boolean
  showUnit?: boolean
  decimals?: number
}>()

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return channelConfig.value?.unit || ''
})

const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue
  return channelConfig.value?.low_limit ?? 0
})

const maxVal = computed(() => {
  if (props.maxValue !== undefined) return props.maxValue
  return channelConfig.value?.high_limit ?? 100
})

const currentValue = computed(() => {
  if (!channelValue.value || isStale.value) return null
  return channelValue.value.value
})

const displayValue = computed(() => {
  if (currentValue.value === null) return '--'
  const dec = props.decimals ?? 1
  return currentValue.value.toFixed(dec)
})

// Calculate percentage for bar fill
const percentage = computed(() => {
  if (currentValue.value === null) return 0
  const range = maxVal.value - minVal.value
  if (range <= 0) return 0
  const pct = ((currentValue.value - minVal.value) / range) * 100
  return Math.max(0, Math.min(100, pct))
})

const isVertical = computed(() => props.orientation === 'vertical')

// Color based on status
const barColor = computed(() => {
  if (isStale.value) return '#666'
  if (channelValue.value?.alarm) return '#ef4444'
  if (channelValue.value?.warning) return '#fbbf24'
  return '#4ade80'
})

const statusClass = computed(() => {
  if (isStale.value) return 'stale'
  if (channelValue.value?.alarm) return 'alarm'
  if (channelValue.value?.warning) return 'warning'
  return 'normal'
})
</script>

<template>
  <div class="bar-graph-widget" :class="[statusClass, { vertical: isVertical }]">
    <div class="label">{{ displayLabel }}</div>

    <div class="bar-container" :class="{ vertical: isVertical }">
      <div class="bar-track">
        <div
          class="bar-fill"
          :style="{
            [isVertical ? 'height' : 'width']: `${percentage}%`,
            backgroundColor: barColor
          }"
        />
      </div>

      <div v-if="showValue !== false" class="value-display">
        <span class="value">{{ displayValue }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>
    </div>

    <div class="range-labels">
      <span>{{ minVal }}</span>
      <span>{{ maxVal }}</span>
    </div>
  </div>
</template>

<style scoped>
.bar-graph-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 6px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.label {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  text-align: center;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
}

.bar-container.vertical {
  flex-direction: row;
  align-items: stretch;
}

.bar-track {
  flex: 1;
  background: #0f0f1a;
  border-radius: 4px;
  overflow: hidden;
  position: relative;
  min-height: 12px;
}

.bar-container.vertical .bar-track {
  min-width: 16px;
  min-height: unset;
}

.bar-fill {
  position: absolute;
  transition: all 0.3s ease-out;
  border-radius: 4px;
}

/* Horizontal fill - from left */
.bar-container:not(.vertical) .bar-fill {
  left: 0;
  top: 0;
  height: 100%;
}

/* Vertical fill - from bottom */
.bar-container.vertical .bar-fill {
  left: 0;
  bottom: 0;
  width: 100%;
}

.value-display {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 2px;
}

.bar-container.vertical .value-display {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
}

.value {
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.unit {
  font-size: 0.6rem;
  color: #888;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.5rem;
  color: #666;
  margin-top: 2px;
}

.bar-container.vertical + .range-labels {
  flex-direction: column-reverse;
  align-items: center;
  margin-top: 0;
  margin-left: 4px;
}

/* Status styling */
.warning {
  border-color: #fbbf24;
}

.alarm {
  border-color: #ef4444;
  animation: pulse-alarm 1s infinite;
}

.normal .value {
  color: #4ade80;
}

.warning .value {
  color: #fbbf24;
}

.alarm .value {
  color: #ef4444;
}

.stale .value {
  color: #666;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: #1a1a2e; }
  50% { background-color: #3f1515; }
}
</style>
