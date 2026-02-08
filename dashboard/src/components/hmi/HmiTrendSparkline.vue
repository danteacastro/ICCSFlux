<script setup lang="ts">
/**
 * HmiTrendSparkline — ISA-101 Inline Mini Trend
 *
 * Shows last N samples as a simple line. No axes, no legend.
 * Lets operators see process direction at a glance.
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import type { PidSymbol } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const store = useDashboardStore()

const maxSamples = computed(() => props.symbol.hmiSparklineSamples ?? 60)

// Collect history
const history = ref<number[]>([])

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.values[props.symbol.channel] ?? null
})

// Track last timestamp to avoid duplicate entries
let lastTs = 0

watch(channelValue, (cv) => {
  if (!cv || typeof cv.value !== 'number') return
  if (cv.timestamp === lastTs) return
  lastTs = cv.timestamp
  history.value.push(cv.value)
  if (history.value.length > maxSamples.value) {
    history.value = history.value.slice(-maxSamples.value)
  }
}, { immediate: true })

onUnmounted(() => {
  history.value = []
})

const channelConfig = computed(() => {
  if (!props.symbol.channel) return null
  return store.channels[props.symbol.channel] ?? null
})

const unit = computed(() => {
  return props.symbol.hmiUnit || channelConfig.value?.unit || ''
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  const dec = props.symbol.decimals ?? 1
  return channelValue.value.value.toFixed(dec)
})

// Generate SVG polyline points
const svgWidth = 200
const svgHeight = 40

const polylinePoints = computed(() => {
  const data = history.value
  if (data.length < 2) return ''
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const step = svgWidth / (data.length - 1)
  return data.map((v, i) => {
    const x = i * step
    const y = svgHeight - ((v - min) / range) * (svgHeight - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

const alarmState = computed(() => {
  if (!channelValue.value) return 'disconnected'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  if (typeof channelValue.value.value === 'number') {
    const v = channelValue.value.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return 'normal'
})
</script>

<template>
  <div class="hmi-sparkline" :class="[alarmState]">
    <div v-if="symbol.label" class="hmi-spark-label">{{ symbol.label }}</div>
    <div class="hmi-spark-body">
      <svg class="hmi-spark-svg" :viewBox="`0 0 ${svgWidth} ${svgHeight}`" preserveAspectRatio="none">
        <polyline
          v-if="polylinePoints"
          :points="polylinePoints"
          fill="none"
          :stroke="alarmState === 'alarm' ? '#FF0000' : alarmState === 'warning' ? '#FF8C00' : '#1E3A8A'"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
        />
      </svg>
      <div class="hmi-spark-value">
        <span class="hmi-spark-num">{{ displayValue }}</span>
        <span v-if="unit" class="hmi-spark-unit">{{ unit }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hmi-sparkline {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #D4D4D4;
  border: 1px solid #A0A0A4;
  border-radius: 2px;
  overflow: hidden;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
}

.hmi-sparkline.alarm {
  border-color: #FF0000;
  border-width: 2px;
}

.hmi-sparkline.warning {
  border-color: #FFD700;
  border-width: 2px;
}

.hmi-spark-label {
  background: #C0C0C0;
  color: #333;
  font-size: clamp(6px, 18%, 9px);
  font-weight: 600;
  text-transform: uppercase;
  padding: 1px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-spark-body {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
}

.hmi-spark-svg {
  flex: 1;
  min-width: 0;
  padding: 2px;
}

.hmi-spark-value {
  position: absolute;
  bottom: 1px;
  right: 4px;
  display: flex;
  align-items: baseline;
  gap: 2px;
  background: rgba(212, 212, 212, 0.85);
  padding: 0 3px;
  border-radius: 1px;
}

.hmi-spark-num {
  color: #1E3A8A;
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(8px, 28%, 12px);
  font-weight: 700;
}

.alarm .hmi-spark-num {
  color: #FF0000;
}

.warning .hmi-spark-num {
  color: #FF8C00;
}

.hmi-spark-unit {
  color: #888;
  font-size: clamp(6px, 18%, 9px);
}
</style>
