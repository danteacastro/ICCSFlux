<script setup lang="ts">
/**
 * DataViewerChart.vue — uPlot chart for pre-fetched historical data.
 *
 * Receives data from props (not from store.values like TrendChart).
 * Features: smooth interpolation, fill opacity, shared crosshair sync,
 * always-on tooltip, drag-to-zoom emitting events, double-click reset,
 * Grafana-style legend (click=isolate, Ctrl+click=toggle, dblclick=show all).
 */
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { HistorianQueryResult } from '../types'

const props = defineProps<{
  panelId: string
  data: HistorianQueryResult | null
  channels: string[]
  isLoading?: boolean
  syncGroup?: string
}>()

const emit = defineEmits<{
  (e: 'zoom', start: number, end: number): void
}>()

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: uPlot | null = null

// Tooltip state
const tooltipVisible = ref(false)
const tooltipX = ref(0)
const tooltipY = ref(0)
const tooltipTime = ref('')
const tooltipValues = ref<{ name: string; value: string; color: string }[]>([])

// Legend isolation
const isolatedSeriesIdx = ref<number | null>(null)

// Default colors
const defaultColors = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
  '#a855f7', '#14b8a6', '#f97316', '#6366f1'
]

function getColor(idx: number): string {
  return defaultColors[idx % defaultColors.length] ?? '#22c55e'
}

// Legend stats
const legendStats = computed(() => {
  if (!props.data || !props.data.success || !props.data.timestamps.length) return null
  const result: { channel: string; min: number | null; max: number | null; avg: number | null; last: number | null; delta: number | null; color: string }[] = []

  for (let i = 0; i < props.channels.length; i++) {
    const ch = props.channels[i]!
    const arr = props.data.series[ch]
    if (!arr || arr.length === 0) {
      result.push({ channel: ch, min: null, max: null, avg: null, last: null, delta: null, color: getColor(i) })
      continue
    }
    let min = Infinity, max = -Infinity, sum = 0, count = 0, last: number | null = null
    for (const v of arr) {
      if (v !== null && v !== undefined && isFinite(v)) {
        if (v < min) min = v
        if (v > max) max = v
        sum += v
        count++
        last = v
      }
    }
    if (count === 0) {
      result.push({ channel: ch, min: null, max: null, avg: null, last: null, delta: null, color: getColor(i) })
    } else {
      result.push({ channel: ch, min, max, avg: sum / count, last, delta: max - min, color: getColor(i) })
    }
  }
  return result
})

function getCSSVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function initChart() {
  if (!chartContainer.value) return
  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return

  // Read CSS variables at init time for theme-aware colors
  const gridColor = getCSSVar('--chart-grid', '#2a2a4a')
  const textColor = getCSSVar('--chart-text', '#a0a0b0')
  const borderColor = getCSSVar('--border-color', '#333')

  const series: uPlot.Series[] = [
    { label: 'Time' },
    ...props.channels.map((ch, i) => {
      const color = getColor(i)
      const alpha = Math.round(0.1 * 255).toString(16).padStart(2, '0')
      return {
        label: ch,
        stroke: color,
        width: 1.5,
        show: true,
        spanGaps: true,
        paths: uPlot.paths.spline!(),
        fill: `${color}${alpha}`,
        value: (_self: uPlot, rawValue: number | null) => {
          if (rawValue === null || rawValue === undefined) return '--'
          return rawValue.toFixed(2)
        }
      }
    })
  ]

  const opts: uPlot.Options = {
    width: rect.width,
    height: Math.max(100, rect.height),
    class: 'historian-chart',
    cursor: {
      show: true,
      drag: { x: true, y: false },
      sync: { key: props.syncGroup || 'historian' }
    },
    scales: {
      x: { time: true },
      y: {
        auto: true,
        range: (_u: uPlot, dataMin: number | null, dataMax: number | null) => {
          if (dataMin === null || dataMax === null || dataMin === dataMax) return [0, 100]
          const range = dataMax - dataMin
          const padding = range * 0.1 || 1
          return [dataMin - padding, dataMax + padding]
        }
      }
    },
    axes: [
      {
        stroke: textColor,
        grid: { stroke: gridColor, width: 1 },
        ticks: { stroke: borderColor, width: 1 },
        font: '10px sans-serif',
        values: (_self: uPlot, splits: number[]) => {
          return splits.map(v => {
            const d = new Date(v * 1000)
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          })
        }
      },
      {
        stroke: textColor,
        grid: { stroke: gridColor, width: 1 },
        ticks: { stroke: borderColor, width: 1 },
        font: '10px sans-serif',
        size: 50,
        side: 3
      }
    ],
    hooks: {
      init: [
        (u) => {
          u.over.addEventListener('dblclick', () => {
            // Reset: re-query with original time range
            emit('zoom', 0, 0)
          })
        }
      ],
      setSelect: [
        (u) => {
          if (u.select.width > 0) {
            const left = u.posToVal(u.select.left, 'x')
            const right = u.posToVal(u.select.left + u.select.width, 'x')
            // Emit zoom in seconds, converted to ms by parent
            emit('zoom', left * 1000, right * 1000)
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false)
          }
        }
      ],
      setCursor: [
        (u) => {
          if (u.cursor.idx !== null && u.cursor.idx !== undefined) {
            updateTooltip(u)
          } else {
            tooltipVisible.value = false
          }
        }
      ]
    },
    series,
    legend: { show: false }
  }

  chart = new uPlot(opts, buildData(), chartContainer.value)
}

function buildData(): AlignedData {
  if (!props.data || !props.data.success || !props.data.timestamps.length) {
    return [new Float64Array(0)] as unknown as AlignedData
  }

  const timestamps = props.data.timestamps // already in seconds from historian
  const result: (number | null)[][] = [timestamps]

  for (const ch of props.channels) {
    result.push(props.data.series[ch] || new Array(timestamps.length).fill(null))
  }

  return result as AlignedData
}

function updateTooltip(u: uPlot) {
  const idx = u.cursor.idx!
  const left = u.cursor.left!
  const top = u.cursor.top!

  tooltipX.value = left + 16
  tooltipY.value = top - 10

  const ts = props.data?.timestamps[idx]
  if (ts) {
    const d = new Date(ts * 1000)
    tooltipTime.value = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const vals: typeof tooltipValues.value = []
  for (let i = 0; i < props.channels.length; i++) {
    const ch = props.channels[i]!
    const v = props.data?.series[ch]?.[idx]
    vals.push({
      name: ch.replace(/^py\./, ''),
      value: v !== null && v !== undefined ? v.toFixed(2) : '--',
      color: getColor(i)
    })
  }
  tooltipValues.value = vals
  tooltipVisible.value = vals.length > 0
}

function handleResize() {
  if (!chart || !chartContainer.value) return
  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width > 0 && rect.height > 0) {
    chart.setSize({ width: rect.width, height: Math.max(100, rect.height) })
  }
}

// Legend click: isolate
function handleLegendClick(channel: string, event: MouseEvent) {
  if (!chart) return
  const idx = props.channels.indexOf(channel) + 1
  if (idx <= 0) return

  if (event.ctrlKey || event.metaKey) {
    chart.setSeries(idx, { show: !chart.series[idx]?.show })
    isolatedSeriesIdx.value = null
  } else {
    if (isolatedSeriesIdx.value === idx) {
      for (let i = 1; i < chart.series.length; i++) chart.setSeries(i, { show: true })
      isolatedSeriesIdx.value = null
    } else {
      for (let i = 1; i < chart.series.length; i++) chart.setSeries(i, { show: i === idx })
      isolatedSeriesIdx.value = idx
    }
  }
}

function handleLegendDblClick() {
  if (!chart) return
  for (let i = 1; i < chart.series.length; i++) chart.setSeries(i, { show: true })
  isolatedSeriesIdx.value = null
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(() => initChart())
  if (chartContainer.value) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.destroy()
})

// Re-render when data changes
watch(() => props.data, () => {
  if (chart) {
    chart.setData(buildData())
  } else {
    nextTick(() => initChart())
  }
}, { deep: true })

// Re-init when channels change
watch(() => props.channels, () => {
  if (chart) chart.destroy()
  nextTick(() => initChart())
}, { deep: true })
</script>

<template>
  <div class="historian-chart-wrapper">
    <!-- Loading overlay -->
    <div v-if="isLoading" class="chart-loading">
      <div class="spinner"></div>
      <span>Loading...</span>
    </div>

    <!-- Empty state -->
    <div v-if="!data || !data.success || channels.length === 0" class="chart-empty">
      <span v-if="channels.length === 0">Select channels to view data</span>
      <span v-else-if="data && !data.success">{{ data.error || 'Query failed' }}</span>
      <span v-else>No data available</span>
    </div>

    <!-- Chart -->
    <div ref="chartContainer" class="chart-area"></div>

    <!-- Floating Tooltip -->
    <div
      v-if="tooltipVisible"
      class="chart-tooltip"
      :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
    >
      <div class="tooltip-time">{{ tooltipTime }}</div>
      <div v-for="tv in tooltipValues" :key="tv.name" class="tooltip-row">
        <span class="tooltip-dot" :style="{ background: tv.color }"></span>
        <span class="tooltip-name">{{ tv.name }}</span>
        <span class="tooltip-val">{{ tv.value }}</span>
      </div>
    </div>

    <!-- Legend -->
    <div v-if="channels.length > 0" class="chart-legend">
      <div
        v-for="(ch, i) in channels"
        :key="ch"
        class="legend-item"
        @click="handleLegendClick(ch, $event)"
        @dblclick.prevent="handleLegendDblClick"
        title="Click: isolate | Ctrl+Click: toggle | DblClick: show all"
      >
        <span class="legend-dot" :style="{ background: getColor(i) }"></span>
        <span class="legend-name">{{ ch.replace(/^py\./, '') }}</span>
        <span v-if="legendStats" class="legend-last">
          {{ legendStats[i]?.last !== null ? legendStats[i]?.last?.toFixed(2) : '--' }}
        </span>
      </div>

      <!-- Stats row -->
      <div v-if="legendStats && legendStats.length > 0" class="legend-stats-row">
        <span v-for="st in legendStats" :key="st.channel" class="legend-stat" :style="{ color: st.color }">
          Min:{{ st.min !== null ? st.min.toFixed(1) : '--' }}
          <span class="stat-sep">|</span>
          Max:{{ st.max !== null ? st.max.toFixed(1) : '--' }}
          <span class="stat-sep">|</span>
          Avg:{{ st.avg !== null ? st.avg.toFixed(1) : '--' }}
          <span class="stat-sep">|</span>
          &#916;:{{ st.delta !== null ? st.delta.toFixed(1) : '--' }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.historian-chart-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  min-height: 150px;
}

.chart-area {
  flex: 1;
  min-height: 0;
  cursor: crosshair;
}

.chart-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--bg-overlay-light, rgba(0, 0, 0, 0.4));
  z-index: 10;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(59, 130, 246, 0.3);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 0.75rem;
  pointer-events: none;
}

/* Tooltip */
.chart-tooltip {
  position: absolute;
  z-index: 150;
  background: var(--bg-widget, #1a1a2e);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 6px 8px;
  box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.5));
  pointer-events: none;
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  min-width: 120px;
}

.tooltip-time {
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-size: 0.6rem;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 3px;
}

.tooltip-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 1px 0;
}

.tooltip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.tooltip-name {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tooltip-val {
  color: var(--text-primary);
  font-weight: 600;
}

/* Legend */
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 6px 8px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
  font-size: 0.7rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity 0.15s;
}

.legend-item:hover { opacity: 0.8; }

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-name {
  color: var(--text-secondary);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.legend-last {
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-primary);
  font-weight: 500;
}

.legend-stats-row {
  width: 100%;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--border-color);
  font-size: 0.6rem;
  font-family: 'JetBrains Mono', monospace;
}

.legend-stat {
  white-space: nowrap;
}

.stat-sep {
  color: var(--text-muted);
  opacity: 0.3;
  margin: 0 2px;
}

:deep(.uplot) { font-family: inherit; }
</style>
