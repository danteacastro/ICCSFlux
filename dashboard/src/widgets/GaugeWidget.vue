<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  channel: string
  label?: string
  decimals?: number
  showUnit?: boolean
  minValue?: number
  maxValue?: number
  style?: WidgetStyle
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const displayLabel = computed(() =>
  (props.label || props.channel || '').replace(/^py\./, '')
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return formatUnit(channelConfig.value?.unit)
})

// Get min/max from props or channel config
const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue
  if (channelConfig.value?.low_limit !== undefined) return channelConfig.value.low_limit
  return 0
})

const maxVal = computed(() => {
  if (props.maxValue !== undefined) return props.maxValue
  if (channelConfig.value?.high_limit !== undefined) return channelConfig.value.high_limit
  return 100
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

// Calculate gauge percentage (0-100)
const percentage = computed(() => {
  if (currentValue.value === null) return 0
  const range = maxVal.value - minVal.value
  if (range <= 0) return 0
  const pct = ((currentValue.value - minVal.value) / range) * 100
  return Math.max(0, Math.min(100, pct))
})

// SVG arc calculation - 270 degree sweep
const arcPath = computed(() => {
  const pct = percentage.value
  // Gauge goes from 135deg to 405deg (270deg sweep)
  const startAngle = 135
  const sweepAngle = 270
  const angle = startAngle + (pct / 100) * sweepAngle

  const cx = 50, cy = 50, r = 40
  const startRad = (startAngle * Math.PI) / 180
  const endRad = (angle * Math.PI) / 180

  const x1 = cx + r * Math.cos(startRad)
  const y1 = cy + r * Math.sin(startRad)
  const x2 = cx + r * Math.cos(endRad)
  const y2 = cy + r * Math.sin(endRad)

  const largeArc = (angle - startAngle) > 180 ? 1 : 0

  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`
})

// Background arc (full 270 degrees)
const bgArcPath = computed(() => {
  const cx = 50, cy = 50, r = 40
  const startAngle = 135
  const endAngle = 405

  const startRad = (startAngle * Math.PI) / 180
  const endRad = (endAngle * Math.PI) / 180

  const x1 = cx + r * Math.cos(startRad)
  const y1 = cy + r * Math.sin(startRad)
  const x2 = cx + r * Math.cos(endRad)
  const y2 = cy + r * Math.sin(endRad)

  return `M ${x1} ${y1} A ${r} ${r} 0 1 1 ${x2} ${y2}`
})

// Color based on alarm/warning state
const gaugeColor = computed(() => {
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
  <div class="gauge-widget" :class="statusClass" :style="containerStyle">
    <div class="label">{{ displayLabel }}</div>

    <svg class="gauge-svg" viewBox="0 0 100 100">
      <!-- Background arc -->
      <path
        :d="bgArcPath"
        fill="none"
        stroke="#2a2a4a"
        stroke-width="8"
        stroke-linecap="round"
      />

      <!-- Value arc -->
      <path
        v-if="percentage > 0"
        :d="arcPath"
        fill="none"
        :stroke="gaugeColor"
        stroke-width="8"
        stroke-linecap="round"
        class="value-arc"
      />

      <!-- Center value -->
      <text x="50" y="52" text-anchor="middle" class="value-text" :fill="gaugeColor">
        {{ displayValue }}
      </text>

      <!-- Unit -->
      <text v-if="unit" x="50" y="64" text-anchor="middle" class="unit-text">
        {{ unit }}
      </text>

      <!-- Min/Max labels -->
      <text x="18" y="82" text-anchor="middle" class="range-text">{{ minVal }}</text>
      <text x="82" y="82" text-anchor="middle" class="range-text">{{ maxVal }}</text>
    </svg>
  </div>
</template>

<style scoped>
.gauge-widget {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.label {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.gauge-svg {
  flex: 1;
  width: 100%;
  max-height: calc(100% - 16px);
}

.value-arc {
  transition: d 0.3s ease-out;
}

.value-text {
  font-size: 14px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.unit-text {
  font-size: 6px;
  fill: #888;
}

.range-text {
  font-size: 5px;
  fill: #666;
}

/* Status-based styling */
.warning {
  border-color: #fbbf24;
}

.alarm {
  border-color: #ef4444;
  animation: pulse-alarm 1s infinite;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: #1a1a2e; }
  50% { background-color: #3f1515; }
}
</style>
