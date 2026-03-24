<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  channel: string
  label?: string
  historyLength?: number
  showValue?: boolean
  showMinMax?: boolean
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
const channelValue = computed(() => store.getChannelRef(props.channel).value)

// Check if data is stale — trust server-side quality flag (handles clock skew)
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  if (channelValue.value.quality === 'stale') return true
  return (Date.now() - channelValue.value.timestamp) > 15000
})

// History buffer for sparkline
const history = ref<{ value: number; time: number }[]>([])
const maxPoints = computed(() => props.historyLength ?? 60)

// Track min/max
const minValue = computed(() => {
  if (history.value.length === 0) return null
  return Math.min(...history.value.map(h => h.value))
})

const maxValue = computed(() => {
  if (history.value.length === 0) return null
  return Math.max(...history.value.map(h => h.value))
})

const displayLabel = computed(() =>
  (props.label || props.channel || '').replace(/^py\./, '')
)

const unit = computed(() => formatUnit(channelConfig.value?.unit))

const currentValue = computed(() => {
  if (!channelValue.value || isStale.value) return '--'
  return channelValue.value.value.toFixed(2)
})

// Generate SVG path for sparkline
const sparklinePath = computed(() => {
  if (history.value.length < 2) return ''

  const width = 100
  const height = 30
  const padding = 2

  const values = history.value.map(h => h.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  const points = history.value.map((point, i) => {
    const x = padding + (i / (history.value.length - 1)) * (width - padding * 2)
    const y = height - padding - ((point.value - min) / range) * (height - padding * 2)
    return `${x},${y}`
  })

  return `M ${points.join(' L ')}`
})

// Status class based on alarm state
const statusClass = computed(() => {
  if (!channelValue.value) return ''
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  return 'normal'
})

// Line color based on status
const lineColor = computed(() => {
  if (!channelValue.value) return '#60a5fa'
  if (channelValue.value.alarm) return 'var(--color-error)'
  if (channelValue.value.warning) return 'var(--color-warning)'
  return 'var(--color-success-light)'
})

// Update history when value changes
watch(channelValue, (newVal) => {
  if (newVal) {
    history.value.push({
      value: newVal.value,
      time: Date.now()
    })
    // Keep only last N points
    if (history.value.length > maxPoints.value) {
      history.value.shift()
    }
  }
}, { immediate: true })

// Cleanup old points periodically
let cleanupInterval: number | null = null
onMounted(() => {
  cleanupInterval = window.setInterval(() => {
    const cutoff = Date.now() - maxPoints.value * 1000
    history.value = history.value.filter(h => h.time > cutoff)
  }, 5000)
})

onUnmounted(() => {
  if (cleanupInterval) clearInterval(cleanupInterval)
})
</script>

<template>
  <div class="sparkline-widget" :class="statusClass" :style="containerStyle">
    <div class="header">
      <span class="label">{{ displayLabel }}</span>
      <span v-if="showValue !== false" class="value">{{ currentValue }} <span class="unit">{{ unit }}</span></span>
    </div>

    <div class="sparkline-container">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" class="sparkline">
        <path
          :d="sparklinePath"
          fill="none"
          :stroke="lineColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </div>

    <div v-if="showMinMax && minValue !== null && maxValue !== null" class="min-max">
      <span class="min">L: {{ minValue.toFixed(1) }}</span>
      <span class="max">H: {{ maxValue.toFixed(1) }}</span>
    </div>
  </div>
</template>

<style scoped>
.sparkline-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 6px 8px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  gap: 4px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.label {
  font-size: 0.65rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.value {
  font-size: 0.85rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--value-color, #fff);
  white-space: nowrap;
}

.unit {
  font-size: 0.65rem;
  color: var(--text-secondary);
  font-weight: 400;
}

.sparkline-container {
  flex: 1;
  min-height: 24px;
}

.sparkline {
  width: 100%;
  height: 100%;
}

.min-max {
  display: flex;
  justify-content: space-between;
  font-size: 0.6rem;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.min {
  color: #60a5fa;
}

.max {
  color: #f472b6;
}

/* Status styles */
.normal .value {
  color: var(--color-success-light);
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
</style>
