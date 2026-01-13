<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { ChartUpdateMode, ChartToolMode, ChartPlotStyle, ChartYAxis, ChartCursor } from '../types'

const props = defineProps<{
  widgetId: string
  channels: string[]
  timeRange?: number        // seconds (X-axis range)
  label?: string            // Custom title (defaults to "Trend")
  // LabVIEW-style features
  historySize?: number      // Max points to keep (default 1024)
  updateMode?: ChartUpdateMode  // strip, scope, sweep
  // Y-axis settings
  yAxisAuto?: boolean       // Auto-scale Y axis (default true)
  yAxisMin?: number         // Manual Y min
  yAxisMax?: number         // Manual Y max
  yAxes?: ChartYAxis[]      // Multiple Y-axis config
  // Display options
  showGrid?: boolean        // Show grid lines (default true)
  showLegend?: boolean      // Show legend (default true)
  showScrollbar?: boolean   // Show X-axis scrollbar
  showDigitalDisplay?: boolean  // Show current values in header
  stackPlots?: boolean      // Stack vs overlay
  // Plot styling
  plotStyles?: ChartPlotStyle[]
  // Cursors
  cursors?: ChartCursor[]
}>()

const emit = defineEmits<{
  (e: 'configure'): void
  (e: 'update:yAxisMin', value: number): void
  (e: 'update:yAxisMax', value: number): void
  (e: 'update:yAxisAuto', value: boolean): void
  (e: 'update:timeRange', value: number): void
}>()

const store = useDashboardStore()

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: uPlot | null = null

// Tool mode state
const toolMode = ref<ChartToolMode>('none')
const isPaused = ref(false)
const scrollPosition = ref(1)  // 0-1, where 1 = live (rightmost)

// View range for zoom/pan (in seconds from now)
const viewStart = ref(0)
const viewEnd = ref(props.timeRange || 300)

// Cursor state
const activeCursors = ref<{ id: string; x: number; values: { channel: string; value: number | null }[] }[]>([])

// Y-axis editing state (direct editing without config menu)
const showYAxisEditor = ref(false)
const editingYMin = ref<number | null>(null)
const editingYMax = ref<number | null>(null)
const yAxisEditorRef = ref<HTMLDivElement | null>(null)
const yMinInputRef = ref<HTMLInputElement | null>(null)

// Local Y-axis state for direct manipulation
const localYAxisAuto = ref(props.yAxisAuto !== false)
const localYMin = ref(props.yAxisMin ?? 0)
const localYMax = ref(props.yAxisMax ?? 100)

// Quick time ranges (in seconds)
const timeRangeOptions = [
  { label: '1m', value: 60 },
  { label: '5m', value: 300 },
  { label: '15m', value: 900 },
  { label: '1h', value: 3600 },
  { label: '4h', value: 14400 },
]
const activeTimeRange = ref(props.timeRange || 300)

// Data buffer: [timestamps, ...channelData]
const dataBuffer = ref<(number | null)[][]>([[]])
const maxPoints = computed(() => props.historySize || 1024)

// Sweep mode position tracking
const sweepPosition = ref(0)

// Default channel colors
const defaultColors = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
  '#a855f7', '#14b8a6', '#f97316', '#6366f1'
]

// Get color for a channel
function getChannelColor(channel: string, index: number): string {
  const style = props.plotStyles?.find(s => s.channel === channel)
  if (style?.color) return style.color
  return defaultColors[index % defaultColors.length] ?? '#22c55e'
}

// Get line width for a channel
function getChannelLineWidth(channel: string): number {
  const style = props.plotStyles?.find(s => s.channel === channel)
  return style?.lineWidth || 1.5
}

// Check if channel is visible
function isChannelVisible(channel: string): boolean {
  const style = props.plotStyles?.find(s => s.channel === channel)
  return style?.visible !== false
}

// Computed current values for legend
const currentValues = computed(() => {
  return props.channels.map((ch, idx) => {
    const data = store.values[ch]
    const config = store.channels[ch]
    return {
      channel: ch,
      name: ch,  // TAG is the only identifier
      value: data?.value,
      unit: config?.unit || '',
      color: getChannelColor(ch, idx),
      visible: isChannelVisible(ch)
    }
  })
})

// Digital display values (for header)
const digitalDisplayValues = computed(() => {
  if (!props.showDigitalDisplay) return []
  return currentValues.value.filter(v => v.visible).slice(0, 4)  // Max 4 in header
})

function initChart() {
  if (!chartContainer.value) return

  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return

  // Initialize data with empty arrays
  dataBuffer.value = [[], ...props.channels.map(() => [])]
  sweepPosition.value = 0

  const series: uPlot.Series[] = [
    { label: 'Time' },
    ...props.channels.map((ch, i) => {
      const visible = isChannelVisible(ch)
      return {
        label: ch,  // TAG is the only identifier
        stroke: getChannelColor(ch, i),
        width: getChannelLineWidth(ch),
        show: visible,
        spanGaps: true,
        value: (_self: uPlot, rawValue: number | null) => {
          if (rawValue === null || rawValue === undefined) return '--'
          return rawValue.toFixed(2)
        }
      }
    })
  ]

  const showGrid = props.showGrid !== false
  const gridStyle = showGrid ? { stroke: '#333', width: 1 } : { show: false }

  // Build Y-axis config (use local values for direct editing)
  const yAxisAuto = localYAxisAuto.value

  // Support for multiple Y-axes
  const axes: uPlot.Axis[] = [
    // X-axis
    {
      stroke: '#666',
      grid: gridStyle as any,
      ticks: { stroke: '#444', width: 1 },
      font: '10px sans-serif',
      labelFont: '10px sans-serif',
      values: (_self: uPlot, splits: number[]) => {
        return splits.map(v => {
          const d = new Date(v * 1000)
          return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        })
      }
    },
    // Primary Y-axis (left)
    {
      stroke: '#666',
      grid: gridStyle as any,
      ticks: { stroke: '#444', width: 1 },
      font: '10px sans-serif',
      labelFont: '10px sans-serif',
      size: 50,
      side: 3,  // left
    }
  ]

  // Add secondary Y-axis if configured
  if (props.yAxes && props.yAxes.length > 1) {
    const rightAxis = props.yAxes.find(a => a.position === 'right')
    if (rightAxis) {
      axes.push({
        stroke: rightAxis.color || '#666',
        grid: { show: false },
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        size: 50,
        side: 1,  // right
        scale: 'y2'
      })
    }
  }

  // Build scales
  const scales: uPlot.Scales = {
    x: { time: true }
  }

  if (yAxisAuto) {
    scales.y = { auto: true }
  } else {
    scales.y = {
      auto: false,
      range: [localYMin.value, localYMax.value]
    }
  }

  // Secondary Y scale if needed
  if (props.yAxes && props.yAxes.length > 1) {
    const rightAxis = props.yAxes.find(a => a.position === 'right')
    if (rightAxis) {
      scales.y2 = rightAxis.auto
        ? { auto: true }
        : { auto: false, range: [rightAxis.min, rightAxis.max] }
    }
  }

  const opts: uPlot.Options = {
    width: rect.width,
    height: Math.max(50, rect.height),
    class: 'trend-chart',
    cursor: {
      show: true,
      drag: {
        x: toolMode.value === 'zoom',
        y: false
      },
      sync: {
        key: props.widgetId,
      }
    },
    hooks: {
      setSelect: [
        (u) => {
          if (toolMode.value === 'zoom' && u.select.width > 0) {
            const left = u.posToVal(u.select.left, 'x')
            const right = u.posToVal(u.select.left + u.select.width, 'x')
            viewStart.value = left
            viewEnd.value = right
            isPaused.value = true
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false)
          }
        }
      ],
      setCursor: [
        (u) => {
          if (toolMode.value === 'cursor' && u.cursor.idx !== null && u.cursor.idx !== undefined) {
            updateCursorValues(u)
          }
        }
      ]
    },
    scales,
    axes,
    series,
    legend: { show: false }
  }

  chart = new uPlot(opts, dataBuffer.value as AlignedData, chartContainer.value)
}

function updateCursorValues(u: uPlot) {
  if (!u.cursor.idx) return

  const idx = u.cursor.idx
  const timestamp = dataBuffer.value[0]?.[idx]
  if (!timestamp) return

  const values = props.channels.map((ch, i) => ({
    channel: ch,
    value: dataBuffer.value[i + 1]?.[idx] ?? null
  }))

  // Update or create cursor
  if (activeCursors.value.length === 0) {
    activeCursors.value.push({ id: 'main', x: timestamp, values })
  } else {
    activeCursors.value[0] = { id: 'main', x: timestamp, values }
  }
}

function updateData() {
  if (isPaused.value) return

  const now = Date.now() / 1000
  const buffer = dataBuffer.value
  const mode = props.updateMode || 'strip'
  const timeRange = props.timeRange || 300

  if (props.channels.length === 0) return

  // Add new point
  buffer[0]?.push(now)
  props.channels.forEach((ch, i) => {
    const value = store.values[ch]?.value ?? null
    buffer[i + 1]?.push(value)
  })

  // Handle different update modes
  if (mode === 'strip') {
    // Strip chart: scroll continuously, trim old data
    const cutoff = now - timeRange
    while (buffer[0] && buffer[0].length > 0 && (buffer[0][0] ?? 0) < cutoff) {
      buffer.forEach(arr => arr?.shift())
    }
  } else if (mode === 'scope') {
    // Scope chart: clear when reaching end, restart from left
    if (buffer[0] && buffer[0].length > 0) {
      const elapsed = now - (buffer[0][0] ?? now)
      if (elapsed >= timeRange) {
        // Clear and restart
        const firstChannel = props.channels[0]
        const firstValue = firstChannel ? store.values[firstChannel]?.value ?? null : null
        dataBuffer.value = [[now], ...props.channels.map(() => [firstValue])]
        return
      }
    }
  } else if (mode === 'sweep') {
    // Sweep chart: overwrite old data with sweep line
    const pointsPerRange = Math.floor(timeRange * 10)  // ~10 points per second
    if (buffer[0] && buffer[0].length >= pointsPerRange) {
      // Wrap around
      const sweepIdx = sweepPosition.value % pointsPerRange
      buffer[0][sweepIdx] = now
      props.channels.forEach((ch, i) => {
        const arr = buffer[i + 1]
        if (arr) {
          arr[sweepIdx] = store.values[ch]?.value ?? null
        }
      })
      sweepPosition.value++

      // Sort for proper display
      const timestamps = buffer[0]
      if (timestamps && timestamps.length > 0) {
        const indices = timestamps.map((_, i) => i)
        indices.sort((a, b) => (timestamps[a] ?? 0) - (timestamps[b] ?? 0))

        buffer[0] = indices.map(i => timestamps[i] ?? null)
        props.channels.forEach((_, ci) => {
          const channelData = buffer[ci + 1]
          if (channelData) {
            buffer[ci + 1] = indices.map(i => channelData[i] ?? null)
          }
        })
      }
    }
  }

  // Limit max points
  while (buffer[0] && buffer[0].length > maxPoints.value) {
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
  if (rect.width > 0 && rect.height > 0) {
    chart.setSize({ width: rect.width, height: Math.max(50, rect.height) })
  }
}

// Tool actions
function setToolMode(mode: ChartToolMode) {
  toolMode.value = toolMode.value === mode ? 'none' : mode
  if (chart) {
    chart.cursor.drag!.x = mode === 'zoom'
  }
}

function togglePause() {
  isPaused.value = !isPaused.value
  if (!isPaused.value) {
    // Reset to live view
    viewStart.value = 0
    viewEnd.value = props.timeRange || 300
    scrollPosition.value = 1
  }
}

function zoomIn() {
  const range = viewEnd.value - viewStart.value
  const center = (viewStart.value + viewEnd.value) / 2
  const newRange = range * 0.5
  viewStart.value = center - newRange / 2
  viewEnd.value = center + newRange / 2
  isPaused.value = true
}

function zoomOut() {
  const range = viewEnd.value - viewStart.value
  const center = (viewStart.value + viewEnd.value) / 2
  const newRange = Math.min(range * 2, props.timeRange || 300)
  viewStart.value = center - newRange / 2
  viewEnd.value = center + newRange / 2
}

function resetZoom() {
  viewStart.value = 0
  viewEnd.value = props.timeRange || 300
  isPaused.value = false
  scrollPosition.value = 1
}

// ========== DIRECT Y-AXIS EDITING (no config menu needed) ==========

// Open Y-axis editor popup when clicking on the Y-axis area
function openYAxisEditor() {
  editingYMin.value = localYMin.value
  editingYMax.value = localYMax.value
  showYAxisEditor.value = true
  nextTick(() => {
    yMinInputRef.value?.focus()
    yMinInputRef.value?.select()
  })
}

// Apply Y-axis changes
function applyYAxisChanges() {
  if (editingYMin.value !== null && editingYMax.value !== null) {
    const min = Math.min(editingYMin.value, editingYMax.value)
    const max = Math.max(editingYMin.value, editingYMax.value)
    localYMin.value = min
    localYMax.value = max
    localYAxisAuto.value = false
    emit('update:yAxisMin', min)
    emit('update:yAxisMax', max)
    emit('update:yAxisAuto', false)
    reinitChart()
  }
  showYAxisEditor.value = false
}

// Cancel Y-axis editing
function cancelYAxisEditor() {
  showYAxisEditor.value = false
}

// Handle Enter/Escape in Y-axis inputs
function handleYAxisKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    applyYAxisChanges()
  } else if (e.key === 'Escape') {
    cancelYAxisEditor()
  }
}

// Double-click Y-axis to auto-scale
function autoScaleYAxis() {
  localYAxisAuto.value = true
  emit('update:yAxisAuto', true)
  reinitChart()
}

// Mouse wheel on Y-axis to zoom
function handleYAxisWheel(e: WheelEvent) {
  e.preventDefault()
  if (localYAxisAuto.value) {
    // First, turn off auto-scale and use current visible range
    const range = localYMax.value - localYMin.value
    localYAxisAuto.value = false
    emit('update:yAxisAuto', false)
  }

  const zoomFactor = e.deltaY > 0 ? 1.2 : 0.8  // scroll down = zoom out
  const range = localYMax.value - localYMin.value
  const center = (localYMin.value + localYMax.value) / 2
  const newRange = range * zoomFactor

  localYMin.value = center - newRange / 2
  localYMax.value = center + newRange / 2

  emit('update:yAxisMin', localYMin.value)
  emit('update:yAxisMax', localYMax.value)
  reinitChart()
}

// ========== QUICK TIME RANGE BUTTONS ==========

function setTimeRange(seconds: number) {
  activeTimeRange.value = seconds
  viewStart.value = 0
  viewEnd.value = seconds
  emit('update:timeRange', seconds)
  isPaused.value = false
  scrollPosition.value = 1
}

function goLive() {
  isPaused.value = false
  scrollPosition.value = 1
  viewEnd.value = activeTimeRange.value
}

// ========== CSV EXPORT ==========

function exportToCSV() {
  if (dataBuffer.value[0]?.length === 0) return

  const headers = ['Timestamp', ...props.channels]
  const rows = dataBuffer.value[0]!.map((timestamp, i) => {
    const date = new Date((timestamp ?? 0) * 1000).toISOString()
    const values = props.channels.map((_, chIdx) => {
      const val = dataBuffer.value[chIdx + 1]?.[i]
      return val !== null && val !== undefined ? val.toFixed(4) : ''
    })
    return [date, ...values].join(',')
  })

  const csv = [headers.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `trend_${props.label || 'data'}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// Reinit chart helper
function reinitChart() {
  if (chart) {
    chart.destroy()
    nextTick(() => initChart())
  }
}

// Scrollbar handling
function onScroll(e: Event) {
  const target = e.target as HTMLInputElement
  scrollPosition.value = parseFloat(target.value)
  if (scrollPosition.value < 1) {
    isPaused.value = true
  }
}

let updateInterval: number | null = null
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(() => {
    initChart()
  })

  updateInterval = window.setInterval(updateData, 100)

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

// Reinit chart when config changes
watch(() => [props.channels, props.plotStyles], () => {
  if (chart) {
    chart.destroy()
    nextTick(() => initChart())
  }
}, { deep: true })

watch(
  () => [props.yAxisAuto, props.yAxisMin, props.yAxisMax, props.showGrid, props.updateMode, props.yAxes],
  () => {
    if (chart) {
      chart.destroy()
      nextTick(() => initChart())
    }
  },
  { deep: true }
)

// Clear chart data when acquisition stops
watch(() => Object.keys(store.values).length, (newLen, oldLen) => {
  if (oldLen > 0 && newLen === 0) {
    dataBuffer.value = [[], ...props.channels.map(() => [])]
    sweepPosition.value = 0
    if (chart) {
      chart.setData(dataBuffer.value as AlignedData)
    }
  }
})

// Sync props to local state when props change (e.g., from config modal)
watch(() => props.yAxisAuto, (val) => { localYAxisAuto.value = val !== false })
watch(() => props.yAxisMin, (val) => { if (val !== undefined) localYMin.value = val })
watch(() => props.yAxisMax, (val) => { if (val !== undefined) localYMax.value = val })
watch(() => props.timeRange, (val) => { if (val !== undefined) activeTimeRange.value = val })

// Toggle channel visibility
function toggleChannelVisibility(channel: string) {
  // This would update plotStyles - for now just re-render
  if (chart) {
    const seriesIdx = props.channels.indexOf(channel) + 1
    if (seriesIdx > 0 && chart.series[seriesIdx]) {
      chart.setSeries(seriesIdx, { show: !chart.series[seriesIdx].show })
    }
  }
}
</script>

<template>
  <div class="trend-chart-widget" :class="{ 'stacked': stackPlots }">
    <!-- Chart Header with Title and Tools -->
    <div class="chart-header">
      <div class="header-left">
        <span class="title">{{ label || 'Trend' }}</span>
        <span v-if="updateMode && updateMode !== 'strip'" class="mode-badge">{{ updateMode.toUpperCase() }}</span>
      </div>

      <!-- Digital Display (current values in header) -->
      <div v-if="showDigitalDisplay && digitalDisplayValues.length > 0" class="digital-display">
        <div v-for="ch in digitalDisplayValues" :key="ch.channel" class="digital-value" :style="{ color: ch.color }">
          <span class="dv-name">{{ ch.name }}:</span>
          <span class="dv-val">{{ ch.value?.toFixed(2) ?? '--' }}</span>
          <span v-if="ch.unit" class="dv-unit">{{ ch.unit }}</span>
        </div>
      </div>

      <!-- Graph Palette (LabVIEW-style tool buttons) -->
      <div class="graph-palette">
        <button
          class="tool-btn"
          :class="{ active: toolMode === 'cursor' }"
          @click="setToolMode('cursor')"
          title="Cursor Tool"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="2" x2="12" y2="22"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
          </svg>
        </button>
        <button
          class="tool-btn"
          :class="{ active: toolMode === 'zoom' }"
          @click="setToolMode('zoom')"
          title="Zoom Tool (drag to zoom)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            <line x1="11" y1="8" x2="11" y2="14"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
        <button
          class="tool-btn"
          :class="{ active: toolMode === 'pan' }"
          @click="setToolMode('pan')"
          title="Pan Tool"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M5 9l-3 3 3 3M9 5l3-3 3 3M15 19l-3 3-3-3M19 9l3 3-3 3M2 12h20M12 2v20"/>
          </svg>
        </button>
        <div class="tool-separator"></div>
        <button class="tool-btn" @click="zoomIn" title="Zoom In">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="11" y1="8" x2="11" y2="14"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
        <button class="tool-btn" @click="zoomOut" title="Zoom Out">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
        <button class="tool-btn" @click="resetZoom" title="Reset Zoom">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
        </button>
        <div class="tool-separator"></div>
        <button
          class="tool-btn"
          :class="{ active: isPaused }"
          @click="togglePause"
          :title="isPaused ? 'Resume' : 'Pause'"
        >
          <svg v-if="!isPaused" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16"/>
            <rect x="14" y="4" width="4" height="16"/>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,3 19,12 5,21"/>
          </svg>
        </button>
        <button class="tool-btn config-btn" @click="emit('configure')" title="Configure Chart">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Quick Time Range Buttons -->
    <div class="time-range-bar">
      <button
        v-for="tr in timeRangeOptions"
        :key="tr.value"
        class="time-range-btn"
        :class="{ active: activeTimeRange === tr.value && !isPaused }"
        @click="setTimeRange(tr.value)"
      >
        {{ tr.label }}
      </button>
      <button
        class="time-range-btn live-btn"
        :class="{ active: !isPaused }"
        @click="goLive"
      >
        LIVE
      </button>
      <div class="time-range-spacer"></div>
      <button class="time-range-btn export-btn" @click="exportToCSV" title="Export to CSV">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </button>
    </div>

    <!-- Chart Container with Y-Axis Click Zone -->
    <div class="chart-wrapper">
      <!-- Y-Axis Click Zone (for direct editing) -->
      <div
        class="y-axis-zone"
        @click="openYAxisEditor"
        @dblclick.prevent="autoScaleYAxis"
        @wheel.prevent="handleYAxisWheel"
        :title="localYAxisAuto ? 'Click: Edit range • Wheel: Zoom • Mode: AUTO' : `Click: Edit range • Wheel: Zoom • Range: ${localYMin.toFixed(1)} - ${localYMax.toFixed(1)}`"
      >
        <div class="y-axis-label">
          <span v-if="localYAxisAuto" class="auto-badge">AUTO</span>
          <span v-else class="range-display">
            <span class="range-max">{{ localYMax.toFixed(1) }}</span>
            <span class="range-min">{{ localYMin.toFixed(1) }}</span>
          </span>
        </div>
      </div>

      <!-- Chart Container -->
      <div ref="chartContainer" class="chart-container"></div>

      <!-- Y-Axis Editor Popup -->
      <div v-if="showYAxisEditor" ref="yAxisEditorRef" class="y-axis-editor">
        <div class="y-axis-editor-title">Y-Axis Range</div>
        <div class="y-axis-editor-row">
          <label>Max:</label>
          <input
            type="number"
            v-model.number="editingYMax"
            @keydown="handleYAxisKeydown"
            step="any"
          />
        </div>
        <div class="y-axis-editor-row">
          <label>Min:</label>
          <input
            ref="yMinInputRef"
            type="number"
            v-model.number="editingYMin"
            @keydown="handleYAxisKeydown"
            step="any"
          />
        </div>
        <div class="y-axis-editor-actions">
          <button class="y-axis-btn auto" @click="autoScaleYAxis">Auto</button>
          <button class="y-axis-btn cancel" @click="cancelYAxisEditor">Cancel</button>
          <button class="y-axis-btn apply" @click="applyYAxisChanges">Apply</button>
        </div>
        <div class="y-axis-editor-hint">Enter to apply • Esc to cancel</div>
      </div>
    </div>

    <!-- X-Axis Scrollbar (for history navigation) -->
    <div v-if="showScrollbar" class="scrollbar-container">
      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        :value="scrollPosition"
        @input="onScroll"
        class="history-scrollbar"
      />
      <span class="scroll-label">{{ isPaused ? 'PAUSED' : 'LIVE' }}</span>
    </div>

    <!-- Cursor Values Display -->
    <div v-if="toolMode === 'cursor' && activeCursors.length > 0" class="cursor-display">
      <div v-for="cursor in activeCursors" :key="cursor.id" class="cursor-values">
        <span class="cursor-time">
          {{ new Date(cursor.x * 1000).toLocaleTimeString() }}
        </span>
        <div class="cursor-readings">
          <span
            v-for="(cv, idx) in cursor.values"
            :key="cv.channel"
            class="cursor-reading"
            :style="{ color: getChannelColor(cv.channel, idx) }"
          >
            {{ cv.channel }}:
            {{ cv.value?.toFixed(2) ?? '--' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Custom Legend with visibility toggles -->
    <div class="custom-legend" v-if="showLegend !== false && currentValues.length > 0">
      <div
        v-for="ch in currentValues"
        :key="ch.channel"
        class="legend-item"
        :class="{ hidden: !ch.visible }"
        @click="toggleChannelVisibility(ch.channel)"
      >
        <span class="legend-color" :style="{ background: ch.visible ? ch.color : '#444' }"></span>
        <span class="legend-name">{{ ch.name }}</span>
        <span class="legend-value" :class="{ 'no-data': ch.value === undefined || ch.value === null }">
          {{ ch.value !== undefined && ch.value !== null ? ch.value.toFixed(2) : '--' }}
          <span v-if="ch.unit && ch.value !== undefined && ch.value !== null" class="legend-unit">{{ ch.unit }}</span>
        </span>
      </div>
    </div>

    <div v-else-if="currentValues.length === 0" class="no-channels">
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
  gap: 8px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--label-color, #888);
  text-transform: uppercase;
}

.mode-badge {
  font-size: 0.6rem;
  padding: 1px 4px;
  border-radius: 2px;
  background: #3b82f6;
  color: #fff;
}

/* Digital Display */
.digital-display {
  display: flex;
  gap: 12px;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
}

.digital-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.dv-name {
  opacity: 0.7;
}

.dv-val {
  font-weight: 600;
}

.dv-unit {
  font-size: 0.6rem;
  opacity: 0.6;
}

/* Graph Palette (LabVIEW-style toolbar) */
.graph-palette {
  display: flex;
  align-items: center;
  gap: 2px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 2px;
}

.tool-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
  transition: all 0.15s;
}

.tool-btn:hover {
  color: #fff;
  background: #333;
}

.tool-btn.active {
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.2);
}

.tool-separator {
  width: 1px;
  height: 16px;
  background: #2a2a4a;
  margin: 0 2px;
}

/* Quick Time Range Bar */
.time-range-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
}

.time-range-btn {
  background: transparent;
  border: 1px solid #333;
  color: #888;
  font-size: 0.6rem;
  padding: 2px 6px;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: 'JetBrains Mono', monospace;
}

.time-range-btn:hover {
  background: #333;
  color: #fff;
}

.time-range-btn.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #fff;
}

.time-range-btn.live-btn.active {
  background: #22c55e;
  border-color: #22c55e;
}

.time-range-spacer {
  flex: 1;
}

.time-range-btn.export-btn {
  padding: 3px 6px;
}

/* Chart Wrapper with Y-Axis Zone */
.chart-wrapper {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
}

.y-axis-zone {
  width: 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  background: rgba(59, 130, 246, 0.05);
  border-right: 1px solid var(--border-color, #2a2a4a);
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}

.y-axis-zone:hover {
  background: rgba(59, 130, 246, 0.15);
}

.y-axis-label {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
  font-size: 0.6rem;
  color: #888;
}

.auto-badge {
  background: #3b82f6;
  color: #fff;
  padding: 2px 4px;
  border-radius: 2px;
  font-size: 0.55rem;
  font-weight: 600;
}

.range-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
}

.range-max {
  color: #f472b6;
}

.range-min {
  color: #60a5fa;
}

/* Y-Axis Editor Popup */
.y-axis-editor {
  position: absolute;
  top: 50%;
  left: 50px;
  transform: translateY(-50%);
  background: #1a1a2e;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  padding: 10px;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  min-width: 160px;
}

.y-axis-editor-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #3b82f6;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.y-axis-editor-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.y-axis-editor-row label {
  font-size: 0.65rem;
  color: #888;
  width: 30px;
}

.y-axis-editor-row input {
  flex: 1;
  background: #0f0f1a;
  border: 1px solid #333;
  border-radius: 3px;
  color: #fff;
  padding: 4px 6px;
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
  width: 80px;
}

.y-axis-editor-row input:focus {
  outline: none;
  border-color: #3b82f6;
}

.y-axis-editor-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}

.y-axis-btn {
  flex: 1;
  padding: 4px 8px;
  border: none;
  border-radius: 3px;
  font-size: 0.65rem;
  cursor: pointer;
  transition: all 0.15s;
}

.y-axis-btn.auto {
  background: #1e3a5f;
  color: #60a5fa;
}

.y-axis-btn.auto:hover {
  background: #2563eb;
  color: #fff;
}

.y-axis-btn.cancel {
  background: #333;
  color: #888;
}

.y-axis-btn.cancel:hover {
  background: #444;
  color: #fff;
}

.y-axis-btn.apply {
  background: #22c55e;
  color: #fff;
}

.y-axis-btn.apply:hover {
  background: #16a34a;
}

.y-axis-editor-hint {
  font-size: 0.55rem;
  color: #666;
  margin-top: 6px;
  text-align: center;
}

.chart-container {
  flex: 1;
  min-height: 0;
}

/* Scrollbar */
.scrollbar-container {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-top: 1px solid var(--border-color, #2a2a4a);
  background: rgba(0, 0, 0, 0.2);
}

.history-scrollbar {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: #1a1a2e;
  border-radius: 3px;
  cursor: pointer;
}

.history-scrollbar::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: #3b82f6;
  border-radius: 50%;
  cursor: pointer;
}

.scroll-label {
  font-size: 0.6rem;
  font-weight: 600;
  color: #666;
  min-width: 45px;
  text-align: right;
}

/* Cursor Display */
.cursor-display {
  padding: 4px 8px;
  background: rgba(251, 191, 36, 0.1);
  border-top: 1px solid #78350f;
  font-size: 0.7rem;
}

.cursor-values {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.cursor-time {
  font-family: 'JetBrains Mono', monospace;
  color: #fbbf24;
}

.cursor-readings {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.cursor-reading {
  font-family: 'JetBrains Mono', monospace;
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
  cursor: pointer;
  transition: opacity 0.15s;
}

.legend-item:hover {
  opacity: 0.8;
}

.legend-item.hidden {
  opacity: 0.4;
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
