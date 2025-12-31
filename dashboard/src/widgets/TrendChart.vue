<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'

const props = defineProps<{
  widgetId: string
  channels: string[]
  timeRange?: number  // seconds
}>()

const emit = defineEmits<{
  (e: 'configure'): void
}>()

const store = useDashboardStore()

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: uPlot | null = null

// Data buffer: [timestamps, ...channelData]
const dataBuffer = ref<(number | null)[][]>([[]])
const maxPoints = 500

// Channel colors
const colors = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'
]

// Computed current values for custom legend
const currentValues = computed(() => {
  return props.channels.map(ch => {
    const data = store.values[ch]
    const config = store.channels[ch]
    return {
      name: config?.display_name || ch,
      value: data?.value,
      unit: config?.unit || '',
      color: colors[props.channels.indexOf(ch) % colors.length]
    }
  })
})

function initChart() {
  if (!chartContainer.value) return

  const rect = chartContainer.value.getBoundingClientRect()

  // Initialize data with empty arrays
  dataBuffer.value = [[], ...props.channels.map(() => [])]

  const series: uPlot.Series[] = [
    { label: 'Time' },
    ...props.channels.map((ch, i) => ({
      label: store.channels[ch]?.display_name || ch,
      stroke: colors[i % colors.length],
      width: 1.5,
      // Custom value formatter for legend
      value: (_self: uPlot, rawValue: number | null) => {
        if (rawValue === null || rawValue === undefined) return '--'
        return rawValue.toFixed(2)
      }
    }))
  ]

  const opts: uPlot.Options = {
    width: rect.width,
    height: Math.max(50, rect.height),
    class: 'trend-chart',
    cursor: {
      show: true,
      drag: { x: true, y: false }
    },
    scales: {
      x: {
        time: true,
      },
      y: {
        auto: true,
      }
    },
    axes: [
      {
        stroke: '#666',
        grid: { stroke: '#333', width: 1 },
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        // Custom time formatter
        values: (_self: uPlot, splits: number[]) => {
          return splits.map(v => {
            const d = new Date(v * 1000)
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          })
        }
      },
      {
        stroke: '#666',
        grid: { stroke: '#333', width: 1 },
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        size: 50,
      }
    ],
    series,
    legend: {
      show: false,  // We'll use custom legend
    }
  }

  chart = new uPlot(opts, dataBuffer.value as AlignedData, chartContainer.value)
}

function updateData() {
  const now = Date.now() / 1000  // uPlot uses seconds
  const cutoff = now - (props.timeRange || 300)
  const buffer = dataBuffer.value

  // Only add data if we have valid channels
  if (props.channels.length === 0) return

  // Add new point
  buffer[0]?.push(now)

  props.channels.forEach((ch, i) => {
    const value = store.values[ch]?.value ?? null
    buffer[i + 1]?.push(value)
  })

  // Trim old data
  while (buffer[0] && buffer[0].length > 0 && (buffer[0][0] ?? 0) < cutoff) {
    buffer.forEach(arr => arr?.shift())
  }

  // Limit max points
  while (buffer[0] && buffer[0].length > maxPoints) {
    buffer.forEach(arr => arr?.shift())
  }

  // Update chart
  if (chart && buffer[0] && buffer[0].length > 0) {
    chart.setData(buffer as AlignedData)
  }
}

function handleResize() {
  if (!chart || !chartContainer.value) return
  const rect = chartContainer.value.getBoundingClientRect()
  // Use full container height since legend is outside the container now
  chart.setSize({ width: rect.width, height: Math.max(50, rect.height) })
}

let updateInterval: number | null = null
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  initChart()

  // Update every 100ms
  updateInterval = window.setInterval(updateData, 100)

  // Handle resize
  if (chartContainer.value) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  if (updateInterval) clearInterval(updateInterval)
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.destroy()
})

// Reinit chart when channels change
watch(() => props.channels, () => {
  if (chart) {
    chart.destroy()
    initChart()
  }
}, { deep: true })

// Clear chart data when store values are cleared (e.g., when acquisition stops)
watch(() => Object.keys(store.values).length, (newLen, oldLen) => {
  // If values were cleared (went from having values to having none)
  if (oldLen > 0 && newLen === 0) {
    // Clear the data buffer
    dataBuffer.value = [[], ...props.channels.map(() => [])]
    if (chart) {
      chart.setData(dataBuffer.value as AlignedData)
    }
  }
})
</script>

<template>
  <div class="trend-chart-widget">
    <div class="chart-header">
      <span class="title">Trend</span>
      <button class="config-btn" @click="emit('configure')" title="Configure channels">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
        </svg>
      </button>
    </div>
    <div ref="chartContainer" class="chart-container"></div>
    <!-- Custom legend that shows all channels -->
    <div class="custom-legend" v-if="currentValues.length > 0">
      <div
        v-for="(ch, idx) in currentValues"
        :key="idx"
        class="legend-item"
      >
        <span class="legend-color" :style="{ background: ch.color }"></span>
        <span class="legend-name">{{ ch.name }}</span>
        <span class="legend-value" :class="{ 'no-data': ch.value === undefined || ch.value === null }">
          {{ ch.value !== undefined && ch.value !== null ? ch.value.toFixed(2) : '--' }}
          <span v-if="ch.unit && ch.value !== undefined && ch.value !== null" class="legend-unit">{{ ch.unit }}</span>
        </span>
      </div>
    </div>
    <div v-else class="no-channels">
      No channels selected. Click configure to add channels.
    </div>
  </div>
</template>

<style scoped>
.trend-chart-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  overflow: hidden;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
}

.title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--label-color, #888);
  text-transform: uppercase;
}

.config-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
}

.config-btn:hover {
  color: #fff;
  background: #333;
}

.chart-container {
  flex: 1;
  min-height: 0;
}

/* Custom Legend */
.custom-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 6px 8px;
  border-top: 1px solid var(--border-color, #2a2a4a);
  background: rgba(0, 0, 0, 0.2);
  flex-shrink: 0;
  max-height: 80px;
  overflow-y: auto;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  white-space: nowrap;
}

.legend-color {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

.legend-name {
  color: #999;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.legend-value {
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
  font-weight: 500;
}

.legend-value.no-data {
  color: #666;
}

.legend-unit {
  font-size: 0.6rem;
  color: #666;
  margin-left: 2px;
}

.no-channels {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: #666;
  font-size: 0.8rem;
  text-align: center;
  padding: 16px;
}

:deep(.uplot) {
  font-family: inherit;
}
</style>
