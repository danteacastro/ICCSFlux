<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useHistoricalData, type RecordingFile, type HistoricalData } from '../composables/useHistoricalData'
import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { ChartUpdateMode, ChartToolMode, ChartPlotStyle, ChartYAxis, ChartCursor, ChartThreshold } from '../types'

export type ChartMode = 'time' | 'xy'

const props = defineProps<{
  widgetId: string
  channels: string[]
  timeRange?: number        // seconds (X-axis range)
  label?: string            // Custom title (defaults to "Trend")
  // XY mode: plot channels[0] vs channels[1] instead of time vs channels
  chartMode?: ChartMode     // 'time' (default) or 'xy'
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
  // Threshold/reference lines
  thresholds?: ChartThreshold[]
  // Historical mode
  historicalMode?: boolean  // If true, show historical data instead of live
  historicalFile?: string   // Selected recording file
  // Grafana-inspired enhancements
  interpolation?: 'linear' | 'smooth' | 'stepBefore' | 'stepAfter'
  fillOpacity?: number           // 0-100, default 0
  tooltipMode?: 'single' | 'all' | 'hidden'  // default 'single'
  connectNulls?: 'never' | 'always' | 'threshold'
  connectNullsThreshold?: number // seconds
  cursorSyncGroup?: string       // shared sync key for cross-chart crosshair
}>()

const emit = defineEmits<{
  (e: 'configure'): void
  (e: 'update:yAxisMin', value: number): void
  (e: 'update:yAxisMax', value: number): void
  (e: 'update:yAxisAuto', value: boolean): void
  (e: 'update:timeRange', value: number): void
}>()

const store = useDashboardStore()
const historical = useHistoricalData()

// Historical mode state
const isHistoricalMode = ref(props.historicalMode ?? false)
const showRecordingSelector = ref(false)
const selectedRecordingFile = ref<string | null>(props.historicalFile ?? null)
const historicalDataLoaded = ref<HistoricalData | null>(null)
const isLoadingHistorical = ref(false)
const historicalScrubPosition = ref(0) // 0-1 scrubber position

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
  { label: '12h', value: 43200 },
  { label: '24h', value: 86400 },
]
const activeTimeRange = ref(props.timeRange || 300)

// Custom time range input
const showCustomTimeInput = ref(false)
const customTimeInput = ref('')
const customTimeInputRef = ref<HTMLInputElement | null>(null)

// Context menu state
const showContextMenu = ref(false)
const contextMenuX = ref(0)
const contextMenuY = ref(0)

// Tooltip state (Grafana-style floating tooltip)
const tooltipVisible = ref(false)
const tooltipX = ref(0)
const tooltipY = ref(0)
const tooltipTime = ref('')
const tooltipValues = ref<{ name: string; value: string; color: string; unit: string }[]>([])

// Legend isolation state (Grafana-style click=isolate)
const isolatedSeriesIdx = ref<number | null>(null)

// Data buffer: [timestamps, ...channelData]
const dataBuffer = ref<(number | null)[][]>([[]])
const maxPoints = computed(() => props.historySize || 86400)

// Sweep mode position tracking
const sweepPosition = ref(0)

// XY mode computed properties
const isXYMode = computed(() => props.chartMode === 'xy')
const xChannel = computed(() => isXYMode.value ? props.channels[0] : null)
const yChannel = computed(() => isXYMode.value ? props.channels[1] : null)

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
      name: ch.replace(/^py\./, ''),  // Strip py. prefix for display
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

// Legend stats: Min / Max / Avg / Last / Delta across visible data
const legendStats = computed(() => {
  if (!props.showLegend) return null
  const buffer = dataBuffer.value
  if (!buffer[0] || buffer[0].length === 0) return null

  const stats: { channel: string; min: number | null; max: number | null; avg: number | null; last: number | null; delta: number | null; color: string }[] = []

  for (let i = 0; i < props.channels.length; i++) {
    const arr = buffer[i + 1]
    if (!arr || arr.length === 0) {
      stats.push({ channel: props.channels[i]!, min: null, max: null, avg: null, last: null, delta: null, color: getChannelColor(props.channels[i]!, i) })
      continue
    }

    let min = Infinity, max = -Infinity, sum = 0, count = 0, last: number | null = null
    for (let j = 0; j < arr.length; j++) {
      const v = arr[j]
      if (v !== null && v !== undefined && isFinite(v)) {
        if (v < min) min = v
        if (v > max) max = v
        sum += v
        count++
        last = v
      }
    }

    if (count === 0) {
      stats.push({ channel: props.channels[i]!, min: null, max: null, avg: null, last: null, delta: null, color: getChannelColor(props.channels[i]!, i) })
    } else {
      stats.push({
        channel: props.channels[i]!,
        min, max,
        avg: sum / count,
        last,
        delta: max - min,
        color: getChannelColor(props.channels[i]!, i)
      })
    }
  }
  return stats
})

// Check if channel type should use stepped (staircase) visualization
function isSteppedChannel(channelName: string): boolean {
  const config = store.channels[channelName]
  if (!config) return false
  return ['digital_input', 'digital_output', 'counter', 'counter_input', 'counter_output', 'frequency_input', 'modbus_coil'].includes(config.channel_type)
}

function initChart() {
  if (!chartContainer.value) return

  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return

  // Initialize data with empty arrays
  if (isXYMode.value) {
    // XY mode: [x_values, y_values]
    dataBuffer.value = [[], []]
  } else {
    dataBuffer.value = [[], ...props.channels.map(() => [])]
  }
  sweepPosition.value = 0

  // Build series based on mode
  let series: uPlot.Series[]

  if (isXYMode.value) {
    // XY mode: X channel vs Y channel
    series = [
      {
        label: xChannel.value || 'X',
        value: (_self: uPlot, rawValue: number | null) => {
          if (rawValue === null || rawValue === undefined) return '--'
          return rawValue.toFixed(2)
        }
      },
      {
        label: yChannel.value || 'Y',
        stroke: getChannelColor(yChannel.value || '', 0),
        width: 1.5,
        show: true,
        spanGaps: false,  // Don't connect discontinuous points in XY
        value: (_self: uPlot, rawValue: number | null) => {
          if (rawValue === null || rawValue === undefined) return '--'
          return rawValue.toFixed(2)
        },
        points: {
          show: true,
          size: 4,
          fill: getChannelColor(yChannel.value || '', 0)
        }
      }
    ]
  } else {
    // Time mode: Time vs all channels
    series = [
      { label: 'Time' },
      ...props.channels.map((ch, i) => {
        const visible = isChannelVisible(ch)
        const stepped = isSteppedChannel(ch)
        const color = getChannelColor(ch, i)

        // Determine paths (interpolation)
        let paths: uPlot.Series.PathBuilder | undefined
        if (stepped) {
          paths = uPlot.paths.stepped!({ align: 1 })
        } else if (props.interpolation === 'smooth') {
          paths = uPlot.paths.spline!()
        } else if (props.interpolation === 'stepBefore') {
          paths = uPlot.paths.stepped!({ align: -1 })
        } else if (props.interpolation === 'stepAfter') {
          paths = uPlot.paths.stepped!({ align: 1 })
        }

        // Determine spanGaps (connect nulls)
        let spanGaps: boolean | number = !stepped
        if (props.connectNulls === 'never') spanGaps = false
        else if (props.connectNulls === 'always') spanGaps = true

        // Fill opacity — hex alpha appended to color
        let fill: string | undefined
        if (props.fillOpacity && props.fillOpacity > 0 && !stepped) {
          const alpha = Math.round((props.fillOpacity / 100) * 255).toString(16).padStart(2, '0')
          fill = `${color}${alpha}`
        }

        return {
          label: ch,  // TAG is the only identifier
          stroke: color,
          width: getChannelLineWidth(ch),
          show: visible,
          spanGaps,
          paths,
          fill,
          value: (_self: uPlot, rawValue: number | null) => {
            if (rawValue === null || rawValue === undefined) return '--'
            return rawValue.toFixed(2)
          }
        }
      })
    ]
  }

  const showGrid = props.showGrid !== false
  const gridStyle = showGrid ? { stroke: '#333', width: 1 } : { show: false }

  // Build Y-axis config (use local values for direct editing)
  const yAxisAuto = localYAxisAuto.value

  // Support for multiple Y-axes
  let axes: uPlot.Axis[]

  if (isXYMode.value) {
    // XY mode: both axes are value axes
    axes = [
      // X-axis (channel values, not time)
      {
        stroke: '#666',
        grid: gridStyle as uPlot.Axis.Grid,
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        label: xChannel.value || 'X',
        labelSize: 16,
        values: (_self: uPlot, splits: number[]) => {
          return splits.map(v => v.toFixed(1))
        }
      },
      // Y-axis (channel values)
      {
        stroke: '#666',
        grid: gridStyle as uPlot.Axis.Grid,
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        label: yChannel.value || 'Y',
        labelSize: 16,
        size: 50,
        side: 3,  // left
      }
    ]
  } else {
    // Time mode: standard axes
    axes = [
      // X-axis
      {
        stroke: '#666',
        grid: gridStyle as uPlot.Axis.Grid,
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
        grid: gridStyle as uPlot.Axis.Grid,
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '10px sans-serif',
        size: 50,
        side: 3,  // left
      }
    ]
  }

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
  const scales: uPlot.Scales = {}

  if (isXYMode.value) {
    // XY mode: both axes are value scales (not time)
    scales.x = {
      auto: true,
      time: false,
      range: (u: uPlot, dataMin: number | null, dataMax: number | null) => {
        if (dataMin === null || dataMax === null || dataMin === dataMax) {
          return [0, 100]
        }
        const range = dataMax - dataMin
        const padding = range * 0.1 || 1
        return [dataMin - padding, dataMax + padding]
      }
    }
  } else {
    scales.x = {
      time: true,
      auto: false,
      range: (_u: uPlot, _dataMin: number | null, _dataMax: number | null): [number, number] => {
        if (isPaused.value && viewStart.value !== 0) {
          return [viewStart.value, viewEnd.value]
        }
        const now = Date.now() / 1000
        const range = activeTimeRange.value || 300
        return [now - range, now]
      }
    }
  }

  if (yAxisAuto) {
    // Auto-scale with sensible default range when no data
    scales.y = {
      auto: true,
      range: (u: uPlot, dataMin: number | null, dataMax: number | null) => {
        // If no data, use default range 0-100
        if (dataMin === null || dataMax === null || dataMin === dataMax) {
          return [0, 100]
        }
        // Add 10% padding to auto range
        const range = dataMax - dataMin
        const padding = range * 0.1 || 1
        return [dataMin - padding, dataMax + padding]
      }
    }
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
        key: props.cursorSyncGroup || props.widgetId,
      }
    },
    hooks: {
      init: [
        (u) => {
          // Double-click on chart overlay resets zoom
          u.over.addEventListener('dblclick', () => { resetZoom() })
        }
      ],
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
          // Cursor tool: update values panel
          if (toolMode.value === 'cursor' && u.cursor.idx !== null && u.cursor.idx !== undefined) {
            updateCursorValues(u)
          }
          // Floating tooltip (Grafana-style): show all series values at cursor
          if (props.tooltipMode !== 'hidden' && u.cursor.idx !== null && u.cursor.idx !== undefined) {
            updateTooltip(u)
          } else {
            tooltipVisible.value = false
          }
        }
      ],
      draw: [
        (u) => {
          drawThresholdLines(u)
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

// ========== FLOATING TOOLTIP ==========

function updateTooltip(u: uPlot) {
  const idx = u.cursor.idx!
  const left = u.cursor.left!
  const top = u.cursor.top!

  // Position tooltip near cursor but offset to avoid covering data
  tooltipX.value = left + 16
  tooltipY.value = top - 10

  // Timestamp
  const ts = dataBuffer.value[0]?.[idx]
  if (ts) {
    const d = new Date(ts * 1000)
    tooltipTime.value = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 1 } as Intl.DateTimeFormatOptions)
  }

  // Series values
  const vals: typeof tooltipValues.value = []
  for (let i = 0; i < props.channels.length; i++) {
    const ch = props.channels[i]!
    const v = dataBuffer.value[i + 1]?.[idx]
    const config = store.channels[ch]
    // In 'single' mode, only show the closest series (first with data)
    // In 'all' mode, show all series
    if (props.tooltipMode === 'single' && vals.length > 0 && v === null) continue
    vals.push({
      name: ch.replace(/^py\./, ''),
      value: v !== null && v !== undefined ? v.toFixed(2) : '--',
      color: getChannelColor(ch, i),
      unit: config?.unit || ''
    })
  }
  tooltipValues.value = vals
  tooltipVisible.value = vals.length > 0
}

// ========== THRESHOLD/REFERENCE LINES ==========

function drawThresholdLines(u: uPlot) {
  if (!props.thresholds || props.thresholds.length === 0) return

  const ctx = u.ctx
  const { left, top, width, height } = u.bbox

  ctx.save()

  for (const threshold of props.thresholds) {
    // Convert Y value to pixel position
    const yPos = u.valToPos(threshold.value, 'y', true)

    // Skip if outside visible area
    if (yPos < top || yPos > top + height) continue

    // Set line style
    ctx.strokeStyle = threshold.color || '#ef4444'
    ctx.lineWidth = 1

    // Set dash pattern
    if (threshold.style === 'dotted') {
      ctx.setLineDash([2, 4])
    } else if (threshold.style === 'dashed' || !threshold.style) {
      ctx.setLineDash([6, 4])
    } else {
      ctx.setLineDash([])
    }

    // Draw the line
    ctx.beginPath()
    ctx.moveTo(left, yPos)
    ctx.lineTo(left + width, yPos)
    ctx.stroke()

    // Draw label if provided
    if (threshold.label) {
      ctx.setLineDash([])
      ctx.font = '10px sans-serif'
      ctx.fillStyle = threshold.color || '#ef4444'

      // Position label at right edge with padding
      const labelWidth = ctx.measureText(threshold.label).width
      const labelX = left + width - labelWidth - 4
      const labelY = yPos - 3

      // Draw background for readability
      ctx.fillStyle = 'rgba(13, 13, 26, 0.8)'
      ctx.fillRect(labelX - 2, labelY - 10, labelWidth + 4, 12)

      // Draw label text
      ctx.fillStyle = threshold.color || '#ef4444'
      ctx.fillText(threshold.label, labelX, labelY)
    }
  }

  ctx.restore()
}

function updateData() {
  if (isPaused.value) return

  const now = Date.now() / 1000
  const buffer = dataBuffer.value
  const mode = props.updateMode || 'strip'
  const timeRange = props.timeRange || 300

  if (props.channels.length === 0) return

  // XY mode: plot channel[0] vs channel[1]
  if (isXYMode.value) {
    if (props.channels.length < 2) return

    const xChannel = props.channels[0]!
    const yChannel = props.channels[1]!
    const xVal = store.values[xChannel]?.value ?? null
    const yVal = store.values[yChannel]?.value ?? null

    // Only add point if both values are valid
    if (xVal !== null && yVal !== null) {
      buffer[0]?.push(xVal)
      buffer[1]?.push(yVal)

      // Limit max points (XY mode keeps more history for patterns)
      const xyMaxPoints = maxPoints.value * 2
      while (buffer[0] && buffer[0].length > xyMaxPoints) {
        buffer[0].shift()
        buffer[1]?.shift()
      }

      // Update chart
      if (chart && buffer[0] && buffer[0].length > 0) {
        // For XY charts, sort by X value for proper line drawing
        const combined = buffer[0].map((x, i) => ({ x, y: buffer[1]?.[i] ?? null }))
        combined.sort((a, b) => (a.x ?? 0) - (b.x ?? 0))
        buffer[0] = combined.map(p => p.x)
        buffer[1] = combined.map(p => p.y)
        chart.setData(buffer as AlignedData)
      }
    }
    return
  }

  // Time mode: standard behavior

  // Adaptive thinning: once buffer exceeds the visible window, store at ~1 Hz
  // to keep full resolution in the viewport while enabling 24h scrollback
  const visibleWindowPoints = (timeRange || 300) * 10  // 10 Hz for visible window
  if (buffer[0] && buffer[0].length > visibleWindowPoints) {
    const lastTs = buffer[0][buffer[0].length - 1] ?? 0
    if (now - lastTs < 1.0) return  // Skip — less than 1s since last stored point
  }

  // Add new point
  buffer[0]?.push(now)
  props.channels.forEach((ch, i) => {
    const value = store.values[ch]?.value ?? null
    buffer[i + 1]?.push(value)
  })

  // Handle different update modes
  if (mode === 'strip') {
    // Strip mode: keep all data for scrollback history.
    // Viewport is managed by the X-axis scale range function.
    // Only the maxPoints hard cap below limits retention.
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

  // Limit max points — slice instead of O(n) shift() calls
  if (buffer[0] && buffer[0].length > maxPoints.value) {
    const excess = buffer[0].length - maxPoints.value
    for (let i = 0; i < buffer.length; i++) {
      if (buffer[i]) buffer[i] = buffer[i]!.slice(excess)
    }
  }

  // Update chart (guard against destroyed instance)
  try {
    if (chart && buffer[0] && buffer[0].length > 0) {
      chart.setData(buffer as AlignedData)
    }
  } catch {
    // Chart may have been destroyed between check and call
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

// ========== CUSTOM TIME RANGE INPUT ==========

function openCustomTimeInput() {
  showCustomTimeInput.value = true
  // Pre-fill with current range in friendly format
  customTimeInput.value = formatSecondsToInput(activeTimeRange.value)
  nextTick(() => {
    customTimeInputRef.value?.focus()
    customTimeInputRef.value?.select()
  })
}

function formatSecondsToInput(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

function parseTimeInput(input: string): number | null {
  const trimmed = input.trim().toLowerCase()
  if (!trimmed) return null

  // Match number with optional unit (s, m, h)
  const match = trimmed.match(/^(\d+(?:\.\d+)?)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours)?$/)
  if (!match) return null

  const value = parseFloat(match[1]!)
  const unit = match[2] || 's'  // Default to seconds

  if (isNaN(value) || value <= 0) return null

  // Convert to seconds
  if (unit.startsWith('h')) {
    return Math.round(value * 3600)
  } else if (unit.startsWith('m')) {
    return Math.round(value * 60)
  } else {
    return Math.round(value)
  }
}

function applyCustomTimeRange() {
  const seconds = parseTimeInput(customTimeInput.value)
  if (seconds && seconds >= 5 && seconds <= 86400) {  // 5 seconds to 24 hours
    setTimeRange(seconds)
    showCustomTimeInput.value = false
  } else {
    // Flash error - invalid input
    customTimeInputRef.value?.classList.add('error')
    setTimeout(() => {
      customTimeInputRef.value?.classList.remove('error')
    }, 300)
  }
}

function handleCustomTimeKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    applyCustomTimeRange()
  } else if (e.key === 'Escape') {
    showCustomTimeInput.value = false
  }
}

function cancelCustomTimeInput() {
  showCustomTimeInput.value = false
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

// ========== PNG SNAPSHOT ==========

function exportToPNG() {
  if (!chart || !chartContainer.value) return

  // Get the uPlot canvas
  const canvas = chartContainer.value.querySelector('canvas')
  if (!canvas) return

  // Create a new canvas with white/dark background
  const exportCanvas = document.createElement('canvas')
  exportCanvas.width = canvas.width
  exportCanvas.height = canvas.height
  const ctx = exportCanvas.getContext('2d')
  if (!ctx) return

  // Fill background
  const style = getComputedStyle(document.documentElement)
  ctx.fillStyle = style.getPropertyValue('--bg-widget').trim() || '#1a1a2e'
  ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height)

  // Draw the chart
  ctx.drawImage(canvas, 0, 0)

  // Add title overlay
  ctx.fillStyle = '#fff'
  ctx.font = 'bold 14px sans-serif'
  ctx.fillText(props.label || 'Trend', 10, 20)

  // Add timestamp
  ctx.font = '10px sans-serif'
  ctx.fillStyle = style.getPropertyValue('--text-secondary').trim() || '#888'
  ctx.fillText(new Date().toLocaleString(), 10, exportCanvas.height - 10)

  // Download
  const link = document.createElement('a')
  link.download = `chart_${props.label || 'trend'}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.png`
  link.href = exportCanvas.toDataURL('image/png')
  link.click()
}

// ========== MOUSE WHEEL ZOOM ==========

function handleChartWheel(e: WheelEvent) {
  e.preventDefault()

  // Zoom factor: scroll down = zoom out, scroll up = zoom in
  const zoomFactor = e.deltaY > 0 ? 1.25 : 0.8

  // Get current time range
  const currentRange = activeTimeRange.value

  // Calculate new range (clamped between 5 seconds and 24 hours)
  const newRange = Math.max(5, Math.min(86400, Math.round(currentRange * zoomFactor)))

  if (newRange !== currentRange) {
    activeTimeRange.value = newRange
    viewStart.value = 0
    viewEnd.value = newRange
    emit('update:timeRange', newRange)

    // If significantly changed, pause to show the zoom effect
    if (Math.abs(newRange - currentRange) > 10) {
      // Stay live but update the range
    }
  }
}

// ========== CONTEXT MENU ==========

function handleContextMenu(e: MouseEvent) {
  e.preventDefault()

  // Position menu at mouse location
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  contextMenuX.value = e.clientX - rect.left
  contextMenuY.value = e.clientY - rect.top
  showContextMenu.value = true
}

function closeContextMenu() {
  showContextMenu.value = false
}

function contextMenuAction(action: string) {
  closeContextMenu()

  switch (action) {
    case 'pause':
      togglePause()
      break
    case 'reset':
      resetZoom()
      break
    case 'export-csv':
      exportToCSV()
      break
    case 'export-png':
      exportToPNG()
      break
    case 'configure':
      emit('configure')
      break
    case 'auto-y':
      autoScaleYAxis()
      break
  }
}

// Reinit chart helper
function reinitChart() {
  if (chart) {
    chart.destroy()
    nextTick(() => initChart())
  }
}

// ========== HISTORICAL MODE ==========

// Toggle between live and historical mode
function toggleHistoricalMode() {
  isHistoricalMode.value = !isHistoricalMode.value
  if (isHistoricalMode.value) {
    isPaused.value = true
    // Load recording list
    loadRecordingsList()
  } else {
    // Switch back to live
    historicalDataLoaded.value = null
    isPaused.value = false
    dataBuffer.value = [[], ...props.channels.map(() => [])]
    reinitChart()
  }
}

// Load available recordings
async function loadRecordingsList() {
  isLoadingHistorical.value = true
  await historical.loadRecordings()
  isLoadingHistorical.value = false
  showRecordingSelector.value = true
}

// Select a recording file
async function selectRecording(filename: string) {
  selectedRecordingFile.value = filename
  showRecordingSelector.value = false
  await loadHistoricalData(filename)
}

// Load historical data from selected file
async function loadHistoricalData(filename: string) {
  isLoadingHistorical.value = true

  // Get file info first
  const fileInfo = await historical.getFileInfo(filename)
  if (!fileInfo || !fileInfo.success) {
    isLoadingHistorical.value = false
    return
  }

  // Calculate decimation based on file size to limit points
  const decimation = historical.calculateDecimation(fileInfo.sample_count, 2000)

  // Load data with decimation and channel filter
  const data = await historical.loadFileData(filename, {
    channels: props.channels.length > 0 ? props.channels : undefined,
    decimation,
    max_samples: 5000
  })

  isLoadingHistorical.value = false

  if (data && data.success) {
    historicalDataLoaded.value = data
    displayHistoricalData(data)
  }
}

// Display loaded historical data in chart
function displayHistoricalData(data: HistoricalData) {
  if (!data.data || data.data.length === 0) return

  // Build data buffer from historical data
  const timestamps: (number | null)[] = []
  const channelArrays: (number | null)[][] = props.channels.map(() => [])

  for (const point of data.data) {
    // Convert ISO timestamp to epoch seconds
    const ts = new Date(point.timestamp).getTime() / 1000
    timestamps.push(ts)

    props.channels.forEach((ch, idx) => {
      channelArrays[idx]?.push(point.values[ch] ?? null)
    })
  }

  dataBuffer.value = [timestamps, ...channelArrays]

  // Update chart
  if (chart) {
    chart.setData(dataBuffer.value as AlignedData)
  }

  // Set scrubber to end
  historicalScrubPosition.value = 1
}

// Scrub through historical data
function handleHistoricalScrub(e: Event) {
  const target = e.target as HTMLInputElement
  historicalScrubPosition.value = parseFloat(target.value)

  // Calculate visible window based on scrub position
  if (!historicalDataLoaded.value || !chart) return

  const totalPoints = historicalDataLoaded.value.sample_count
  const viewPoints = Math.min(500, totalPoints)
  const startIdx = Math.floor((totalPoints - viewPoints) * historicalScrubPosition.value)

  // For now, just update the view scale
  // Full implementation would reload data range
}

// Format file size for display
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Format duration for display
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
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

// Derive chart update interval from the actual publish rate (default 4 Hz = 250ms)
const chartUpdateMs = computed(() => {
  const hz = store.status?.publish_rate_hz || store.status?.scan_rate_hz || 4
  return Math.round(1000 / hz)
})

function restartUpdateInterval() {
  if (updateInterval) clearInterval(updateInterval)
  updateInterval = window.setInterval(updateData, chartUpdateMs.value)
}

// Re-sync interval when scan/publish rate changes
watch(chartUpdateMs, () => restartUpdateInterval())

onMounted(() => {
  nextTick(() => {
    initChart()
  })

  restartUpdateInterval()

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

// Reinit chart when channels change — preserve existing data for kept channels
watch(() => props.channels, (newChannels, oldChannels) => {
  if (!chart || !oldChannels) {
    if (chart) chart.destroy()
    nextTick(() => initChart())
    return
  }

  if (isXYMode.value) {
    chart.destroy()
    nextTick(() => initChart())
    return
  }

  // Compute channel diff
  const oldSet = new Set(oldChannels)
  const keptChannels = newChannels.filter(ch => oldSet.has(ch))

  if (keptChannels.length === 0 && oldChannels.length > 0) {
    chart.destroy()
    nextTick(() => initChart())
    return
  }

  // Build new data buffer preserving existing channel data
  const timestamps = dataBuffer.value[0] || []
  const newBuffer: (number | null)[][] = [timestamps]

  for (const ch of newChannels) {
    const oldIdx = oldChannels.indexOf(ch)
    if (oldIdx >= 0) {
      newBuffer.push(dataBuffer.value[oldIdx + 1] || [])
    } else {
      newBuffer.push(new Array(timestamps.length).fill(null))
    }
  }

  dataBuffer.value = newBuffer

  // Recreate uPlot with new series config, then restore preserved data
  chart.destroy()
  nextTick(() => {
    const preservedBuffer = dataBuffer.value
    initChart()
    dataBuffer.value = preservedBuffer
    if (chart) {
      chart.setData(preservedBuffer as AlignedData)
    }
  })
}, { deep: true })

// Reinit chart when plot styles change (no data preservation needed)
watch(() => props.plotStyles, () => {
  if (chart) {
    chart.destroy()
    nextTick(() => initChart())
  }
}, { deep: true })

watch(
  () => [props.yAxisAuto, props.yAxisMin, props.yAxisMax, props.showGrid, props.updateMode, props.yAxes, props.thresholds],
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

// Grafana-style legend click behavior
function handleLegendClick(channel: string, event: MouseEvent) {
  if (!chart) return
  const seriesIdx = props.channels.indexOf(channel) + 1
  if (seriesIdx <= 0) return

  if (event.ctrlKey || event.metaKey) {
    // Ctrl/Cmd+Click: toggle this series
    chart.setSeries(seriesIdx, { show: !chart.series[seriesIdx]?.show })
    isolatedSeriesIdx.value = null
  } else {
    // Click: isolate (solo) this series — hide all others
    if (isolatedSeriesIdx.value === seriesIdx) {
      // Already isolated — show all
      for (let i = 1; i < chart.series.length; i++) {
        chart.setSeries(i, { show: true })
      }
      isolatedSeriesIdx.value = null
    } else {
      // Isolate: show only clicked, hide others
      for (let i = 1; i < chart.series.length; i++) {
        chart.setSeries(i, { show: i === seriesIdx })
      }
      isolatedSeriesIdx.value = seriesIdx
    }
  }
}

// Double-click legend: show all series
function handleLegendDblClick() {
  if (!chart) return
  for (let i = 1; i < chart.series.length; i++) {
    chart.setSeries(i, { show: true })
  }
  isolatedSeriesIdx.value = null
}
</script>

<template>
  <div class="trend-chart-widget" :class="{ 'stacked': stackPlots }">
    <!-- Chart Header with Title and Tools -->
    <div class="chart-header">
      <div class="header-left">
        <span class="title">{{ label || (isXYMode ? 'XY Graph' : 'Trend') }}</span>
        <span v-if="isXYMode" class="mode-badge xy">XY</span>
        <span v-else-if="updateMode && updateMode !== 'strip'" class="mode-badge">{{ updateMode.toUpperCase() }}</span>
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

    <!-- Quick Time Range Buttons (hidden in XY mode) -->
    <div v-if="!isXYMode" class="time-range-bar">
      <button
        v-for="tr in timeRangeOptions"
        :key="tr.value"
        class="time-range-btn"
        :class="{ active: activeTimeRange === tr.value && !isPaused && !showCustomTimeInput }"
        @click="setTimeRange(tr.value)"
      >
        {{ tr.label }}
      </button>

      <!-- Custom Time Range Input -->
      <div class="custom-time-container">
        <button
          v-if="!showCustomTimeInput"
          class="time-range-btn custom-btn"
          :class="{ active: !timeRangeOptions.some(t => t.value === activeTimeRange) }"
          @click="openCustomTimeInput"
          title="Custom time range (e.g., 30s, 2m, 45m)"
        >
          {{ timeRangeOptions.some(t => t.value === activeTimeRange) ? '...' : formatSecondsToInput(activeTimeRange) }}
        </button>
        <div v-else class="custom-time-input-wrapper">
          <input
            ref="customTimeInputRef"
            v-model="customTimeInput"
            type="text"
            class="custom-time-input"
            placeholder="30s, 2m, 1h"
            @keydown="handleCustomTimeKeydown"
            @blur="cancelCustomTimeInput"
          />
          <button class="custom-time-apply" @mousedown.prevent="applyCustomTimeRange" title="Apply">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </button>
        </div>
      </div>

      <button
        class="time-range-btn live-btn"
        :class="{ active: !isPaused }"
        @click="goLive"
      >
        LIVE
      </button>
      <div class="time-range-spacer"></div>
      <button class="time-range-btn export-btn" @click="exportToPNG" title="Save as PNG">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <polyline points="21 15 16 10 5 21"/>
        </svg>
      </button>
      <button class="time-range-btn export-btn" @click="exportToCSV" title="Export to CSV">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </button>
      <div class="tool-separator"></div>
      <button
        class="time-range-btn history-btn"
        :class="{ active: isHistoricalMode }"
        @click="toggleHistoricalMode"
        title="Toggle Historical Mode"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
        {{ isHistoricalMode ? 'HIST' : 'HIST' }}
      </button>
    </div>

    <!-- Historical Mode Bar -->
    <div v-if="isHistoricalMode" class="historical-bar">
      <button
        class="hist-file-btn"
        @click="showRecordingSelector = !showRecordingSelector"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        {{ selectedRecordingFile || 'Select Recording...' }}
      </button>

      <div v-if="historicalDataLoaded" class="hist-info">
        <span class="hist-samples">{{ historicalDataLoaded.sample_count }} pts</span>
        <span class="hist-range" v-if="historicalDataLoaded.start_time">
          {{ new Date(historicalDataLoaded.start_time).toLocaleString() }}
        </span>
      </div>

      <div v-if="isLoadingHistorical" class="hist-loading">
        <div class="spinner"></div>
        Loading...
      </div>

      <div class="hist-spacer"></div>

      <button class="hist-action-btn" @click="loadHistoricalData(selectedRecordingFile!)" v-if="selectedRecordingFile" title="Reload">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
          <path d="M3 3v5h5"/>
        </svg>
      </button>
    </div>

    <!-- Recording Selector Panel -->
    <div v-if="showRecordingSelector && isHistoricalMode" class="recording-selector">
      <div class="recording-selector-header">
        <span>Select Recording</span>
        <button class="close-selector" @click="showRecordingSelector = false">&times;</button>
      </div>
      <div v-if="historical.isLoadingList.value" class="recording-loading">
        <div class="spinner"></div>
        Loading recordings...
      </div>
      <div v-else-if="historical.recordings.value.length === 0" class="no-recordings">
        No recordings found
      </div>
      <div v-else class="recording-list">
        <button
          v-for="rec in historical.recordings.value"
          :key="rec.name"
          class="recording-item"
          :class="{ selected: rec.name === selectedRecordingFile }"
          @click="selectRecording(rec.name)"
        >
          <div class="rec-name">{{ rec.name }}</div>
          <div class="rec-meta">
            <span>{{ formatFileSize(rec.size) }}</span>
            <span v-if="rec.duration">{{ formatDuration(rec.duration) }}</span>
            <span>{{ rec.sample_count }} samples</span>
          </div>
        </button>
      </div>
    </div>

    <!-- Chart Container with Y-Axis Click Zone -->
    <div class="chart-wrapper" @contextmenu="handleContextMenu" @click="closeContextMenu">
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
      <div
        ref="chartContainer"
        class="chart-container"
        @wheel.prevent="handleChartWheel"
      ></div>

      <!-- Context Menu -->
      <div
        v-if="showContextMenu"
        class="context-menu"
        :style="{ left: contextMenuX + 'px', top: contextMenuY + 'px' }"
        @click.stop
      >
        <button class="context-menu-item" @click="contextMenuAction('pause')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <template v-if="isPaused">
              <polygon points="5,3 19,12 5,21"/>
            </template>
            <template v-else>
              <rect x="6" y="4" width="4" height="16"/>
              <rect x="14" y="4" width="4" height="16"/>
            </template>
          </svg>
          {{ isPaused ? 'Resume' : 'Pause' }}
        </button>
        <button class="context-menu-item" @click="contextMenuAction('reset')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
          Reset View
        </button>
        <button class="context-menu-item" @click="contextMenuAction('auto-y')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20V4M5 11l7-7 7 7"/>
          </svg>
          Auto-Scale Y
        </button>
        <div class="context-menu-divider"></div>
        <button class="context-menu-item" @click="contextMenuAction('export-png')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
          </svg>
          Save as PNG
        </button>
        <button class="context-menu-item" @click="contextMenuAction('export-csv')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Export CSV
        </button>
        <div class="context-menu-divider"></div>
        <button class="context-menu-item" @click="contextMenuAction('configure')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4"/>
          </svg>
          Configure...
        </button>
      </div>

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

      <!-- Floating Tooltip (Grafana-style) -->
      <div
        v-if="tooltipVisible && tooltipMode !== 'hidden'"
        class="chart-tooltip"
        :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
      >
        <div class="tooltip-time">{{ tooltipTime }}</div>
        <div v-for="tv in tooltipValues" :key="tv.name" class="tooltip-row">
          <span class="tooltip-dot" :style="{ background: tv.color }"></span>
          <span class="tooltip-name">{{ tv.name }}</span>
          <span class="tooltip-val">{{ tv.value }}</span>
          <span v-if="tv.unit" class="tooltip-unit">{{ tv.unit }}</span>
        </div>
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

    <!-- Custom Legend with Grafana-style click behavior -->
    <div class="custom-legend" v-if="showLegend !== false && currentValues.length > 0">
      <div
        v-for="ch in currentValues"
        :key="ch.channel"
        class="legend-item"
        :class="{ hidden: !ch.visible }"
        @click="handleLegendClick(ch.channel, $event)"
        @dblclick.prevent="handleLegendDblClick"
        title="Click: isolate | Ctrl+Click: toggle | DblClick: show all"
      >
        <span class="legend-color" :style="{ background: ch.visible ? ch.color : '#444' }"></span>
        <span class="legend-name">{{ ch.name }}</span>
        <span class="legend-value" :class="{ 'no-data': ch.value === undefined || ch.value === null }">
          {{ ch.value !== undefined && ch.value !== null ? ch.value.toFixed(2) : '--' }}
          <span v-if="ch.unit && ch.value !== undefined && ch.value !== null" class="legend-unit">{{ ch.unit }}</span>
        </span>
      </div>
      <!-- Legend Stats Row -->
      <div v-if="legendStats && legendStats.length > 0" class="legend-stats-row">
        <template v-for="st in legendStats" :key="st.channel">
          <span class="legend-stat" :style="{ color: st.color }">
            <span class="stat-label">Min:</span>{{ st.min !== null ? st.min.toFixed(1) : '--' }}
            <span class="stat-sep">|</span>
            <span class="stat-label">Max:</span>{{ st.max !== null ? st.max.toFixed(1) : '--' }}
            <span class="stat-sep">|</span>
            <span class="stat-label">Avg:</span>{{ st.avg !== null ? st.avg.toFixed(1) : '--' }}
            <span class="stat-sep">|</span>
            <span class="stat-label">Last:</span>{{ st.last !== null ? st.last.toFixed(2) : '--' }}
            <span class="stat-sep">|</span>
            <span class="stat-label delta">&#916;:</span>{{ st.delta !== null ? st.delta.toFixed(1) : '--' }}
          </span>
        </template>
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
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-color);
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
  background: var(--color-accent);
  color: var(--text-primary);
}

.mode-badge.xy {
  background: #8b5cf6;
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
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 2px;
}

.tool-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
  transition: all 0.15s;
}

.tool-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.tool-btn.active {
  color: var(--color-accent);
  background: var(--color-accent-bg);
}

.tool-separator {
  width: 1px;
  height: 16px;
  background: var(--border-color);
  margin: 0 2px;
}

/* Quick Time Range Bar */
.time-range-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.time-range-btn {
  background: transparent;
  border: 1px solid var(--bg-hover);
  color: var(--text-secondary);
  font-size: 0.6rem;
  padding: 2px 6px;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: 'JetBrains Mono', monospace;
}

.time-range-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.time-range-btn.active {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.time-range-btn.live-btn.active {
  background: var(--color-success);
  border-color: var(--color-success);
}

.time-range-spacer {
  flex: 1;
}

.time-range-btn.export-btn {
  padding: 3px 6px;
}

/* Custom Time Range Input */
.custom-time-container {
  position: relative;
}

.time-range-btn.custom-btn {
  min-width: 32px;
  text-align: center;
}

.custom-time-input-wrapper {
  display: flex;
  align-items: center;
  gap: 2px;
}

.custom-time-input {
  width: 60px;
  background: var(--bg-input);
  border: 1px solid var(--color-accent);
  border-radius: 2px;
  color: var(--text-primary);
  font-size: 0.6rem;
  font-family: 'JetBrains Mono', monospace;
  padding: 2px 4px;
  outline: none;
  text-align: center;
}

.custom-time-input::placeholder {
  color: var(--text-dim);
}

.custom-time-input.error {
  border-color: var(--color-error);
  animation: shake 0.3s ease-in-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}

.custom-time-apply {
  background: var(--color-success);
  border: none;
  border-radius: 2px;
  color: var(--text-primary);
  cursor: pointer;
  padding: 3px 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.custom-time-apply:hover {
  background: var(--color-success-dark);
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
  border-right: 1px solid var(--border-color);
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
  color: var(--text-secondary);
}

.auto-badge {
  background: var(--color-accent);
  color: var(--text-primary);
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
  background: var(--bg-widget);
  border: 1px solid var(--color-accent);
  border-radius: 6px;
  padding: 10px;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  min-width: 160px;
}

.y-axis-editor-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-accent);
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
  color: var(--text-secondary);
  width: 30px;
}

.y-axis-editor-row input {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--bg-hover);
  border-radius: 3px;
  color: var(--text-primary);
  padding: 4px 6px;
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
  width: 80px;
}

.y-axis-editor-row input:focus {
  outline: none;
  border-color: var(--color-accent);
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
  background: var(--color-accent-bg);
  color: var(--color-accent-light);
}

.y-axis-btn.auto:hover {
  background: var(--color-accent-dark);
  color: var(--text-primary);
}

.y-axis-btn.cancel {
  background: var(--bg-hover);
  color: var(--text-secondary);
}

.y-axis-btn.cancel:hover {
  background: var(--bg-active);
  color: var(--text-primary);
}

.y-axis-btn.apply {
  background: var(--color-success);
  color: var(--text-primary);
}

.y-axis-btn.apply:hover {
  background: var(--color-success-dark);
}

.y-axis-editor-hint {
  font-size: 0.55rem;
  color: var(--text-muted);
  margin-top: 6px;
  text-align: center;
}

/* Context Menu */
.context-menu {
  position: absolute;
  background: var(--bg-widget);
  border: 1px solid var(--color-accent);
  border-radius: 6px;
  padding: 4px 0;
  z-index: 200;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  min-width: 150px;
}

.context-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: none;
  border: none;
  color: var(--text-bright);
  font-size: 0.75rem;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.context-menu-item:hover {
  background: var(--color-accent-bg);
}

.context-menu-item svg {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.context-menu-item:hover svg {
  color: var(--color-accent);
}

.context-menu-divider {
  height: 1px;
  background: var(--border-color);
  margin: 4px 0;
}

.chart-container {
  flex: 1;
  min-height: 0;
  cursor: crosshair;
}

/* Scrollbar */
.scrollbar-container {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-top: 1px solid var(--border-color);
  background: rgba(0, 0, 0, 0.2);
}

.history-scrollbar {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--bg-widget);
  border-radius: 3px;
  cursor: pointer;
}

.history-scrollbar::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: var(--color-accent);
  border-radius: 50%;
  cursor: pointer;
}

.scroll-label {
  font-size: 0.6rem;
  font-weight: 600;
  color: var(--text-muted);
  min-width: 45px;
  text-align: right;
}

/* Cursor Display */
.cursor-display {
  padding: 4px 8px;
  background: rgba(251, 191, 36, 0.1);
  border-top: 1px solid var(--indicator-warning-bg);
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
  border-top: 1px solid var(--border-color);
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
  color: var(--text-secondary);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.legend-value {
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-primary);
  font-weight: 500;
}

.legend-value.no-data {
  color: var(--text-muted);
}

.legend-unit {
  font-size: 0.6rem;
  color: var(--text-muted);
  margin-left: 2px;
}

.no-channels {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-muted);
  font-size: 0.8rem;
  text-align: center;
  padding: 16px;
}

:deep(.uplot) {
  font-family: inherit;
}

/* ========== HISTORICAL MODE STYLES ========== */

.history-btn {
  display: flex;
  align-items: center;
  gap: 4px;
}

.history-btn.active {
  background: #7c3aed;
  border-color: #7c3aed;
}

.historical-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: linear-gradient(to right, rgba(124, 58, 237, 0.1), rgba(124, 58, 237, 0.05));
  border-bottom: 1px solid #5b21b6;
  flex-shrink: 0;
}

.hist-file-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #1e1b4b;
  border: 1px solid #5b21b6;
  border-radius: 4px;
  color: #c4b5fd;
  font-size: 0.7rem;
  cursor: pointer;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hist-file-btn:hover {
  background: #2e2963;
  border-color: #7c3aed;
}

.hist-info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.65rem;
  color: #a78bfa;
}

.hist-samples {
  font-family: 'JetBrains Mono', monospace;
  background: rgba(124, 58, 237, 0.2);
  padding: 2px 6px;
  border-radius: 3px;
}

.hist-range {
  color: #8b5cf6;
}

.hist-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.65rem;
  color: #a78bfa;
}

.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(139, 92, 246, 0.3);
  border-top-color: #8b5cf6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.hist-spacer {
  flex: 1;
}

.hist-action-btn {
  padding: 4px 8px;
  background: transparent;
  border: 1px solid #5b21b6;
  border-radius: 3px;
  color: #a78bfa;
  cursor: pointer;
}

.hist-action-btn:hover {
  background: #5b21b6;
  color: var(--text-primary);
}

/* Recording Selector Panel */
.recording-selector {
  position: absolute;
  top: 80px;
  left: 8px;
  width: 320px;
  max-height: 300px;
  background: var(--bg-widget);
  border: 1px solid #5b21b6;
  border-radius: 8px;
  z-index: 300;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
}

.recording-selector-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: rgba(124, 58, 237, 0.1);
  border-bottom: 1px solid #5b21b6;
  font-size: 0.75rem;
  font-weight: 600;
  color: #c4b5fd;
}

.close-selector {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 4px;
}

.close-selector:hover {
  color: var(--text-primary);
}

.recording-loading,
.no-recordings {
  padding: 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.75rem;
}

.recording-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.recording-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.recording-item {
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}

.recording-item:hover {
  background: rgba(124, 58, 237, 0.1);
  border-color: #5b21b6;
}

.recording-item.selected {
  background: rgba(124, 58, 237, 0.2);
  border-color: #7c3aed;
}

.rec-name {
  font-size: 0.75rem;
  color: var(--text-bright);
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-meta {
  display: flex;
  gap: 12px;
  font-size: 0.65rem;
  color: var(--text-secondary);
}

.rec-meta span {
  white-space: nowrap;
}

/* Historical scrubber */
.hist-scrubber {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: rgba(124, 58, 237, 0.05);
  border-top: 1px solid var(--border-color);
}

.hist-scrubber input[type="range"] {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--bg-widget);
  border-radius: 2px;
}

.hist-scrubber input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  background: #8b5cf6;
  border-radius: 50%;
  cursor: pointer;
}

.hist-time-display {
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  color: #a78bfa;
  min-width: 150px;
  text-align: right;
}

/* ========== FLOATING TOOLTIP (Grafana-style) ========== */

.chart-tooltip {
  position: absolute;
  z-index: 150;
  background: var(--bg-widget, #1a1a2e);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 6px 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
  pointer-events: none;
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  min-width: 120px;
  max-width: 250px;
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

.tooltip-unit {
  color: var(--text-muted);
  font-size: 0.55rem;
}

/* ========== LEGEND STATS ROW ========== */

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
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}

.stat-label {
  opacity: 0.6;
  font-size: 0.55rem;
  margin-right: 1px;
}

.stat-label.delta {
  font-weight: 700;
}

.stat-sep {
  color: var(--text-muted);
  opacity: 0.3;
  margin: 0 2px;
}
</style>
