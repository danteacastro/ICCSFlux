<script setup lang="ts">
/**
 * GcChromatogramWidget - Gas Chromatograph Chromatogram Display
 *
 * Displays a GC chromatogram using uPlot with component result table,
 * SST (System Suitability Test) status bar, and run history navigation.
 *
 * Data flow:
 *   GC node publishes chromatogram data and analysis results over MQTT.
 *   This widget subscribes via useGcAnalysis() composable and renders
 *   the signal trace, baseline, peak labels, and component table.
 *
 * MQTT topics consumed (via useGcAnalysis):
 *   nisystem/gc/{nodeId}/chromatogram  - Raw chromatogram data points
 *   nisystem/gc/{nodeId}/result        - Analysis result with peaks
 *   nisystem/gc/{nodeId}/progress      - Run progress updates
 *   nisystem/gc/{nodeId}/status        - Node online/offline status
 */

import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import type {
  WidgetConfig,
  GCChromatogramData,
  GCAnalysisResult,
  GCPeakResult,
  GCRunProgress
} from '../types'

// MQTT topic prefix — must match gc_node's topic_base structure
const SYSTEM_PREFIX = 'nisystem'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

const props = defineProps<{ widget: WidgetConfig }>()

// ---------------------------------------------------------------------------
// Composables & Store
// ---------------------------------------------------------------------------

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')

// ---------------------------------------------------------------------------
// GC State (inline, since useGcAnalysis composable does not yet exist)
// ---------------------------------------------------------------------------

/** All configured GC node IDs from the project config (channels with source_type 'gc') */
const availableGcNodeIds = computed<string[]>(() => {
  const nodeIds = new Set<string>()
  for (const ch of Object.values(store.channels)) {
    if (ch.source_type === 'gc' && ch.node_id) {
      nodeIds.add(ch.node_id)
    }
  }
  return Array.from(nodeIds)
})

const effectiveNodeId = computed(() => {
  if (props.widget.gcNodeId) return props.widget.gcNodeId
  if (availableGcNodeIds.value.length > 0) return availableGcNodeIds.value[0]!
  return null
})

// Run history: most recent runs keyed by run_number
interface StoredRun {
  chromatogram: GCChromatogramData | null
  result: GCAnalysisResult | null
  progress: GCRunProgress | null
}

const historyDepth = computed(() => props.widget.gcHistoryDepth ?? 10)
const runHistory = ref<StoredRun[]>([])
const selectedRunIndex = ref(0)
const isRunning = ref(false)
const runElapsedS = ref(0)
const nodeOnline = ref(false)

// Current run progress
const currentProgress = ref<GCRunProgress | null>(null)

// Derived: selected run data
const selectedRun = computed<StoredRun | null>(() => {
  if (runHistory.value.length === 0) return null
  return runHistory.value[selectedRunIndex.value] ?? null
})

const latestChromatogram = computed(() => selectedRun.value?.chromatogram ?? null)
const latestResult = computed(() => selectedRun.value?.result ?? null)

// Peaks sorted by retention time
const sortedPeaks = computed<GCPeakResult[]>(() => {
  const result = latestResult.value
  if (!result) return []

  const peaks: GCPeakResult[] = []

  // Identified components from result.components
  if (result.components) {
    for (const [name, comp] of Object.entries(result.components)) {
      peaks.push({
        name,
        rt: comp.rt ?? 0,
        area: comp.area ?? 0,
        area_pct: comp.area_pct ?? 0,
        height: 0,
        width_s: 0,
        concentration: comp.concentration,
        unit: comp.unit,
        identified: true
      })
    }
  }

  // Unidentified peaks
  if (result.unidentified_peaks) {
    for (const peak of result.unidentified_peaks) {
      peaks.push({ ...peak, identified: false })
    }
  }

  peaks.sort((a, b) => a.rt - b.rt)
  return peaks
})

// SST data (from identified peaks that have SST fields)
const sstData = computed(() => {
  const items: Array<{ name: string; plates?: number; resolution?: number; tailing?: number }> = []
  for (const peak of sortedPeaks.value) {
    if (peak.plates !== undefined || peak.resolution !== undefined || peak.tailing !== undefined) {
      items.push({
        name: peak.name,
        plates: peak.plates,
        resolution: peak.resolution,
        tailing: peak.tailing
      })
    }
  }
  return items
})

const hasSstData = computed(() => sstData.value.length > 0)

// SST pass/fail criteria (typical defaults)
const SST_LIMITS = {
  plates: 2000,       // Minimum theoretical plates
  resolution: 1.5,    // Minimum resolution
  tailingMax: 2.0     // Maximum tailing factor
}

function sstPasses(field: 'plates' | 'resolution' | 'tailing', value?: number): boolean | null {
  if (value === undefined || value === null) return null
  switch (field) {
    case 'plates': return value >= SST_LIMITS.plates
    case 'resolution': return value >= SST_LIMITS.resolution
    case 'tailing': return value <= SST_LIMITS.tailingMax
  }
}

// Component table rows
interface ComponentRow {
  name: string
  rt: number
  areaPct: number
  concentration: number | undefined
  unit: string
  identified: boolean
}

const componentRows = computed<ComponentRow[]>(() => {
  return sortedPeaks.value.map(p => ({
    name: p.identified ? p.name : `Unknown (RT ${p.rt.toFixed(1)}s)`,
    rt: p.rt,
    areaPct: p.area_pct,
    concentration: p.concentration,
    unit: p.unit ?? '',
    identified: p.identified
  }))
})

// ---------------------------------------------------------------------------
// MQTT subscription for GC data
// ---------------------------------------------------------------------------

let mqttUnsubscribers: Array<() => void> = []

function subscribeToGcNode(nodeId: string) {
  // Clean up previous subscriptions
  unsubscribeGc()

  // Full MQTT topic paths matching gc_node's publish structure:
  // gc_node publishes to: nisystem/nodes/{node_id}/gc/{subtopic}
  const topicBase = `${SYSTEM_PREFIX}/nodes/${nodeId}/gc`

  // Chromatogram data (published on run finish)
  const unsubChromatogram = mqtt.subscribe<GCChromatogramData>(
    `${topicBase}/chromatogram`,
    (data) => {
      if (!data || !data.times || !data.values) return

      // Find or create run entry
      let run = runHistory.value.find(r =>
        r.chromatogram?.run_number === data.run_number ||
        r.result?.run_number === data.run_number
      )
      if (!run) {
        run = { chromatogram: null, result: null, progress: null }
        runHistory.value.unshift(run)
        // Trim history
        while (runHistory.value.length > historyDepth.value) {
          runHistory.value.pop()
        }
        // Auto-select newest run
        selectedRunIndex.value = 0
      }
      run.chromatogram = data
      updateChartData()
    }
  )

  // Analysis result (published on run finish — gc_node uses "analysis" not "result")
  const unsubAnalysis = mqtt.subscribe<GCAnalysisResult>(
    `${topicBase}/analysis`,
    (data) => {
      if (!data) return

      let run = runHistory.value.find(r =>
        r.chromatogram?.run_number === data.run_number ||
        r.result?.run_number === data.run_number
      )
      if (!run) {
        run = { chromatogram: null, result: null, progress: null }
        runHistory.value.unshift(run)
        while (runHistory.value.length > historyDepth.value) {
          runHistory.value.pop()
        }
        selectedRunIndex.value = 0
      }
      run.result = data
      isRunning.value = false
      updateChartData()
    }
  )

  // Run started (published when inject trigger fires)
  const unsubRunStarted = mqtt.subscribe<{ run_number: number }>(
    `${topicBase}/run_started`,
    (data) => {
      if (!data) return
      isRunning.value = true
      runElapsedS.value = 0
      lastProgressReceivedAt = Date.now()
      currentProgress.value = {
        run_number: data.run_number,
        elapsed_s: 0,
        points: 0,
        max_voltage: 0,
        last_voltage: 0
      }
    }
  )

  // Run progress (published every N seconds during active run)
  const unsubProgress = mqtt.subscribe<GCRunProgress>(
    `${topicBase}/run_progress`,
    (data) => {
      if (!data) return
      currentProgress.value = data
      isRunning.value = true
      runElapsedS.value = data.elapsed_s
      lastProgressReceivedAt = Date.now()
    }
  )

  // Node heartbeat — detect online/offline
  const unsubHeartbeat = mqtt.subscribe<{ node_type?: string; state?: string }>(
    `${SYSTEM_PREFIX}/nodes/${nodeId}/heartbeat`,
    (data) => {
      nodeOnline.value = true
      lastNodeHeartbeat = Date.now()
    }
  )

  mqttUnsubscribers = [unsubChromatogram, unsubAnalysis, unsubRunStarted, unsubProgress, unsubHeartbeat]
}

function unsubscribeGc() {
  for (const unsub of mqttUnsubscribers) {
    try { unsub() } catch { /* ignore */ }
  }
  mqttUnsubscribers = []
}

// Watch for node ID changes and resubscribe
watch(effectiveNodeId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    subscribeToGcNode(newId)
  } else if (!newId) {
    unsubscribeGc()
  }
}, { immediate: true })

// ---------------------------------------------------------------------------
// uPlot Chart
// ---------------------------------------------------------------------------

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: uPlot | null = null
let resizeObserver: ResizeObserver | null = null

const showPeakLabels = computed(() => props.widget.showPeakLabels !== false)
const showComponentTable = computed(() => props.widget.showComponentTable !== false)
const showSstBar = computed(() => props.widget.showSstBar !== false)

function initChart() {
  if (!chartContainer.value) return

  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return

  // Destroy existing chart
  if (chart) {
    chart.destroy()
    chart = null
  }

  const hasChromatogram = !!latestChromatogram.value
  const hasBaseline = !!latestResult.value && sortedPeaks.value.length > 0

  // Build series
  const series: uPlot.Series[] = [
    {
      label: 'Time (s)',
      value: (_self: uPlot, rawValue: number | null) => {
        if (rawValue === null || rawValue === undefined) return '--'
        return rawValue.toFixed(2) + ' s'
      }
    },
    {
      label: 'Signal',
      stroke: '#3b82f6',
      width: 1.5,
      show: true,
      spanGaps: true,
      value: (_self: uPlot, rawValue: number | null) => {
        if (rawValue === null || rawValue === undefined) return '--'
        return rawValue.toFixed(4)
      }
    }
  ]

  // Baseline series (if available)
  if (hasBaseline) {
    series.push({
      label: 'Baseline',
      stroke: '#6b7280',
      width: 1,
      show: true,
      dash: [6, 4],
      spanGaps: true,
      value: (_self: uPlot, rawValue: number | null) => {
        if (rawValue === null || rawValue === undefined) return '--'
        return rawValue.toFixed(4)
      }
    })
  }

  const opts: uPlot.Options = {
    width: rect.width,
    height: Math.max(50, rect.height),
    class: 'gc-chart',
    cursor: {
      show: true,
      drag: { x: false, y: false }
    },
    legend: { show: false },
    scales: {
      x: {
        time: false,
        auto: true,
        range: (u: uPlot, dataMin: number | null, dataMax: number | null): [number, number] => {
          if (dataMin === null || dataMax === null) return [0, 60]
          const pad = (dataMax - dataMin) * 0.02 || 1
          return [Math.max(0, dataMin - pad), dataMax + pad]
        }
      },
      y: {
        auto: true,
        range: (u: uPlot, dataMin: number | null, dataMax: number | null): [number, number] => {
          if (dataMin === null || dataMax === null || dataMin === dataMax) return [0, 1]
          const range = dataMax - dataMin
          const pad = range * 0.1 || 0.1
          return [dataMin - pad, dataMax + pad]
        }
      }
    },
    axes: [
      {
        stroke: '#666',
        grid: { stroke: '#2a2a4a', width: 1 },
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '11px sans-serif',
        label: 'Time (s)',
        labelSize: 18,
        size: 36,
        values: (_self: uPlot, splits: number[]) => splits.map(v => v.toFixed(0))
      },
      {
        stroke: '#666',
        grid: { stroke: '#2a2a4a', width: 1 },
        ticks: { stroke: '#444', width: 1 },
        font: '10px sans-serif',
        labelFont: '11px sans-serif',
        label: 'Signal',
        labelSize: 18,
        size: 55,
        side: 3
      }
    ],
    series,
    hooks: {
      draw: [drawPeakLabels]
    }
  }

  // Build initial data
  const data = buildChartData(hasBaseline)
  chart = new uPlot(opts, data, chartContainer.value)
}

function buildChartData(includeBaseline: boolean): AlignedData {
  const chromData = latestChromatogram.value
  if (!chromData || !chromData.times || chromData.times.length === 0) {
    const empty: AlignedData = [[], []]
    if (includeBaseline) empty.push([])
    return empty
  }

  const times = chromData.times as number[]
  const values = chromData.values as number[]

  if (includeBaseline) {
    // Generate a simple baseline (linear interpolation between start and end)
    const baseline = generateBaseline(times, values)
    return [times, values, baseline]
  }

  return [times, values]
}

/** Simple baseline estimation: linear interpolation from first to last value */
function generateBaseline(times: number[], values: number[]): (number | null)[] {
  if (times.length < 2) return times.map(() => null)
  const startVal = values[0] ?? 0
  const endVal = values[values.length - 1] ?? 0
  const startTime = times[0] ?? 0
  const endTime = times[times.length - 1] ?? 1
  const duration = endTime - startTime || 1
  return times.map(t => {
    const frac = (t - startTime) / duration
    return startVal + frac * (endVal - startVal)
  })
}

function updateChartData() {
  if (!chart) {
    nextTick(() => initChart())
    return
  }

  const hasBaseline = sortedPeaks.value.length > 0
  const currentSeriesCount = chart.series.length
  const expectedSeriesCount = hasBaseline ? 3 : 2

  // If series count changed, reinit chart
  if (currentSeriesCount !== expectedSeriesCount) {
    chart.destroy()
    chart = null
    nextTick(() => initChart())
    return
  }

  try {
    const data = buildChartData(hasBaseline)
    chart.setData(data)
  } catch {
    // Chart may have been destroyed between check and call
  }
}

/** Draw peak name labels above peak apex points using uPlot draw hook */
function drawPeakLabels(u: uPlot) {
  if (!showPeakLabels.value || sortedPeaks.value.length === 0) return
  if (!latestChromatogram.value) return

  const ctx = u.ctx
  const { left, top, width, height } = u.bbox

  ctx.save()
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'

  const chromTimes = latestChromatogram.value.times
  const chromValues = latestChromatogram.value.values

  for (const peak of sortedPeaks.value) {
    // Find the data index closest to this peak's retention time
    let closestIdx = 0
    let closestDist = Infinity
    for (let i = 0; i < chromTimes.length; i++) {
      const dist = Math.abs((chromTimes[i] ?? 0) - peak.rt)
      if (dist < closestDist) {
        closestDist = dist
        closestIdx = i
      }
    }

    const peakTime = chromTimes[closestIdx]
    const peakValue = chromValues[closestIdx]
    if (peakTime === undefined || peakValue === undefined) continue

    // Convert data coords to pixel positions
    const xPx = u.valToPos(peakTime, 'x', true)
    const yPx = u.valToPos(peakValue, 'y', true)

    // Skip if outside visible area
    if (xPx < left || xPx > left + width || yPx < top || yPx > top + height) continue

    // Draw label text above peak
    const labelText = peak.identified ? peak.name : '?'
    const labelY = yPx - 6

    // Background for readability
    const textWidth = ctx.measureText(labelText).width
    ctx.fillStyle = 'rgba(13, 13, 26, 0.85)'
    ctx.fillRect(xPx - textWidth / 2 - 3, labelY - 12, textWidth + 6, 14)

    // Text color: blue for identified, gray for unknown
    ctx.fillStyle = peak.identified ? '#60a5fa' : '#6b7280'
    ctx.fillText(labelText, xPx, labelY)

    // Small vertical marker line from label to peak apex
    ctx.strokeStyle = peak.identified ? 'rgba(96, 165, 250, 0.4)' : 'rgba(107, 114, 128, 0.4)'
    ctx.lineWidth = 1
    ctx.setLineDash([2, 2])
    ctx.beginPath()
    ctx.moveTo(xPx, labelY + 2)
    ctx.lineTo(xPx, yPx)
    ctx.stroke()
    ctx.setLineDash([])
  }

  ctx.restore()
}

function handleResize() {
  if (!chart || !chartContainer.value) return
  const rect = chartContainer.value.getBoundingClientRect()
  if (rect.width > 0 && rect.height > 0) {
    chart.setSize({ width: rect.width, height: Math.max(50, rect.height) })
  }
}

// ---------------------------------------------------------------------------
// Run Selector
// ---------------------------------------------------------------------------

const hasMultipleRuns = computed(() => runHistory.value.length > 1)

function selectPreviousRun() {
  if (selectedRunIndex.value < runHistory.value.length - 1) {
    selectedRunIndex.value++
    updateChartData()
  }
}

function selectNextRun() {
  if (selectedRunIndex.value > 0) {
    selectedRunIndex.value--
    updateChartData()
  }
}

function selectLatestRun() {
  selectedRunIndex.value = 0
  updateChartData()
}

const selectedRunLabel = computed(() => {
  const run = selectedRun.value
  if (!run) return 'No data'
  const num = run.chromatogram?.run_number ?? run.result?.run_number ?? '?'
  return `Run #${num}`
})

// ---------------------------------------------------------------------------
// Run Controls (Start / Stop)
// ---------------------------------------------------------------------------

function startRun() {
  if (!effectiveNodeId.value) return
  // gc_node subscribes to: nisystem/nodes/{node_id}/commands/#
  // Expects payload: { command: 'start_run' }
  mqtt.sendNodeCommand('commands/gc', { command: 'start_run' }, effectiveNodeId.value)
}

function stopRun() {
  if (!effectiveNodeId.value) return
  mqtt.sendNodeCommand('commands/gc', { command: 'stop_run' }, effectiveNodeId.value)
}

// ---------------------------------------------------------------------------
// Elapsed Time Formatter
// ---------------------------------------------------------------------------

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Elapsed timer interval (updates display while running)
// ---------------------------------------------------------------------------

let elapsedTimer: number | null = null
let lastProgressReceivedAt = 0
let lastNodeHeartbeat = 0

function startElapsedTimer() {
  stopElapsedTimer()
  elapsedTimer = window.setInterval(() => {
    if (isRunning.value && currentProgress.value && lastProgressReceivedAt > 0) {
      // Estimate elapsed based on last progress + wall-clock time since
      const timeSinceProgress = (Date.now() - lastProgressReceivedAt) / 1000
      runElapsedS.value = currentProgress.value.elapsed_s + timeSinceProgress
    }
    // Check node offline (no heartbeat for 15s)
    if (lastNodeHeartbeat > 0 && Date.now() - lastNodeHeartbeat > 15000) {
      nodeOnline.value = false
    }
  }, 1000)
}

function stopElapsedTimer() {
  if (elapsedTimer !== null) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  nextTick(() => {
    initChart()
  })

  if (chartContainer.value) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(chartContainer.value)
  }

  startElapsedTimer()
})

onUnmounted(() => {
  stopElapsedTimer()
  unsubscribeGc()
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) { chart.destroy(); chart = null }
})

// Reinit chart when chromatogram data changes (structural change)
watch(latestChromatogram, () => {
  if (chart) {
    updateChartData()
  } else {
    nextTick(() => initChart())
  }
})

// Reinit chart when result arrives (may add baseline series)
watch(latestResult, () => {
  updateChartData()
})
</script>

<template>
  <div class="gc-widget">
    <!-- No GC node configured -->
    <div v-if="!effectiveNodeId" class="gc-no-node">
      <div class="gc-no-node-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 3h6v4H9zM12 7v4M7 11h10v2H7zM9 13v3M15 13v3M6 16h12v2H6zM8 18v3M16 18v3" />
        </svg>
      </div>
      <span class="gc-no-node-text">Select a GC node</span>
      <span class="gc-no-node-hint">
        Configure a GC node in the Configuration tab, then set gcNodeId on this widget.
      </span>
    </div>

    <!-- Main GC display -->
    <template v-else>
      <!-- Header bar -->
      <div class="gc-header">
        <div class="gc-header-left">
          <span class="gc-node-name">{{ effectiveNodeId }}</span>
          <span
            class="gc-status-dot"
            :class="{ online: nodeOnline, offline: !nodeOnline }"
            :title="nodeOnline ? 'Online' : 'Offline'"
          ></span>
          <span v-if="selectedRun" class="gc-run-number">{{ selectedRunLabel }}</span>
        </div>

        <div class="gc-header-center">
          <span v-if="isRunning" class="gc-run-status running">
            <span class="gc-run-pulse"></span>
            Running {{ formatElapsed(runElapsedS) }}
          </span>
          <span v-else class="gc-run-status idle">Idle</span>
        </div>

        <div class="gc-header-right">
          <button
            class="gc-btn gc-btn-start"
            :disabled="isRunning"
            @click="startRun"
            title="Start GC run"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5,3 19,12 5,21" />
            </svg>
            Start
          </button>
          <button
            class="gc-btn gc-btn-stop"
            :disabled="!isRunning"
            @click="stopRun"
            title="Stop GC run"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <rect x="4" y="4" width="16" height="16" />
            </svg>
            Stop
          </button>
        </div>
      </div>

      <!-- Run Selector (when multiple runs exist) -->
      <div v-if="hasMultipleRuns" class="gc-run-selector">
        <button
          class="gc-nav-btn"
          :disabled="selectedRunIndex >= runHistory.length - 1"
          @click="selectPreviousRun"
          title="Older run"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span class="gc-run-selector-label">
          {{ selectedRunLabel }}
          <span v-if="selectedRunIndex > 0" class="gc-run-selector-age">
            ({{ runHistory.length - selectedRunIndex }} of {{ runHistory.length }})
          </span>
          <span v-else class="gc-run-selector-latest">Latest</span>
        </span>
        <button
          class="gc-nav-btn"
          :disabled="selectedRunIndex <= 0"
          @click="selectNextRun"
          title="Newer run"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
        <button
          v-if="selectedRunIndex > 0"
          class="gc-nav-btn gc-nav-latest"
          @click="selectLatestRun"
          title="Jump to latest run"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="13 17 18 12 13 7" />
            <polyline points="6 17 11 12 6 7" />
          </svg>
        </button>
      </div>

      <!-- Chromatogram Chart -->
      <div class="gc-chart-wrapper">
        <div
          ref="chartContainer"
          class="gc-chart-container"
        ></div>
        <div v-if="!latestChromatogram" class="gc-chart-placeholder">
          <span>Waiting for chromatogram data...</span>
        </div>
      </div>

      <!-- Component Results Table -->
      <div v-if="showComponentTable && componentRows.length > 0" class="gc-table-wrapper">
        <table class="gc-table">
          <thead>
            <tr>
              <th class="gc-th-component">Component</th>
              <th class="gc-th-rt">RT (s)</th>
              <th class="gc-th-area">Area%</th>
              <th class="gc-th-conc">Conc</th>
              <th class="gc-th-unit">Unit</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in componentRows"
              :key="row.name + row.rt"
              :class="{ 'gc-row-unidentified': !row.identified }"
            >
              <td class="gc-td-component">{{ row.name }}</td>
              <td class="gc-td-rt">{{ row.rt.toFixed(2) }}</td>
              <td class="gc-td-area">{{ row.areaPct.toFixed(2) }}</td>
              <td class="gc-td-conc">
                {{ row.concentration !== undefined ? row.concentration.toFixed(4) : '--' }}
              </td>
              <td class="gc-td-unit">{{ row.unit }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Empty table placeholder -->
      <div
        v-else-if="showComponentTable && componentRows.length === 0 && latestChromatogram"
        class="gc-table-empty"
      >
        No analysis results for this run.
      </div>

      <!-- SST Status Bar -->
      <div v-if="showSstBar && hasSstData" class="gc-sst-bar">
        <span class="gc-sst-label">SST</span>
        <div v-for="item in sstData" :key="item.name" class="gc-sst-item">
          <span class="gc-sst-name">{{ item.name }}</span>
          <!-- Plates -->
          <span
            v-if="item.plates !== undefined"
            class="gc-sst-check"
            :class="{
              pass: sstPasses('plates', item.plates) === true,
              fail: sstPasses('plates', item.plates) === false
            }"
            :title="`N=${item.plates?.toFixed(0)} (min ${SST_LIMITS.plates})`"
          >
            <template v-if="sstPasses('plates', item.plates) === true">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </template>
            <template v-else-if="sstPasses('plates', item.plates) === false">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </template>
            N
          </span>
          <!-- Resolution -->
          <span
            v-if="item.resolution !== undefined"
            class="gc-sst-check"
            :class="{
              pass: sstPasses('resolution', item.resolution) === true,
              fail: sstPasses('resolution', item.resolution) === false
            }"
            :title="`R=${item.resolution?.toFixed(2)} (min ${SST_LIMITS.resolution})`"
          >
            <template v-if="sstPasses('resolution', item.resolution) === true">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </template>
            <template v-else-if="sstPasses('resolution', item.resolution) === false">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </template>
            Rs
          </span>
          <!-- Tailing -->
          <span
            v-if="item.tailing !== undefined"
            class="gc-sst-check"
            :class="{
              pass: sstPasses('tailing', item.tailing) === true,
              fail: sstPasses('tailing', item.tailing) === false
            }"
            :title="`T=${item.tailing?.toFixed(2)} (max ${SST_LIMITS.tailingMax})`"
          >
            <template v-if="sstPasses('tailing', item.tailing) === true">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </template>
            <template v-else-if="sstPasses('tailing', item.tailing) === false">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </template>
            Tf
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ======================================================================
   GC Chromatogram Widget - Scoped Styles
   ====================================================================== */

.gc-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-widget, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  overflow: hidden;
  color: var(--text-bright, #e2e8f0);
  font-family: 'Inter', sans-serif;
}

/* ---- No-node placeholder ---- */

.gc-no-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.gc-no-node-icon {
  color: var(--text-muted, #666680);
  opacity: 0.6;
}

.gc-no-node-text {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-secondary, #a0a0b0);
}

.gc-no-node-hint {
  font-size: 0.7rem;
  color: var(--text-muted, #666680);
  max-width: 220px;
  line-height: 1.4;
}

/* ---- Header ---- */

.gc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
  gap: 6px;
  flex-wrap: wrap;
  background: rgba(0, 0, 0, 0.15);
}

.gc-header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.gc-node-name {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-secondary, #a0a0b0);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.gc-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.gc-status-dot.online {
  background: var(--color-success, #22c55e);
  box-shadow: 0 0 4px var(--color-success, #22c55e);
}

.gc-status-dot.offline {
  background: var(--text-muted, #666680);
}

.gc-run-number {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
  font-family: 'JetBrains Mono', monospace;
}

.gc-header-center {
  display: flex;
  align-items: center;
}

.gc-run-status {
  font-size: 0.65rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 3px;
}

.gc-run-status.idle {
  color: var(--text-muted, #666680);
  background: rgba(0, 0, 0, 0.2);
}

.gc-run-status.running {
  color: var(--color-success-light, #4ade80);
  background: rgba(34, 197, 94, 0.1);
}

.gc-run-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success, #22c55e);
  animation: gc-pulse 1.2s ease-in-out infinite;
}

@keyframes gc-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

.gc-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ---- Buttons ---- */

.gc-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 3px;
  border: 1px solid var(--border-color, #2a2a4a);
  font-size: 0.62rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--bg-secondary, #0f0f1a);
  color: var(--text-secondary, #a0a0b0);
}

.gc-btn:hover:not(:disabled) {
  background: var(--bg-hover, #334155);
  color: var(--text-primary, #fff);
}

.gc-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.gc-btn-start:hover:not(:disabled) {
  border-color: var(--color-success, #22c55e);
  color: var(--color-success-light, #4ade80);
}

.gc-btn-stop:hover:not(:disabled) {
  border-color: var(--color-error, #ef4444);
  color: var(--color-error-light, #f87171);
}

/* ---- Run Selector ---- */

.gc-run-selector {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 3px 8px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  background: rgba(59, 130, 246, 0.04);
  flex-shrink: 0;
}

.gc-nav-btn {
  background: transparent;
  border: 1px solid var(--border-color, #2a2a4a);
  color: var(--text-secondary, #a0a0b0);
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.gc-nav-btn:hover:not(:disabled) {
  background: var(--bg-hover, #334155);
  color: var(--text-primary, #fff);
  border-color: var(--color-accent, #3b82f6);
}

.gc-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.gc-nav-latest {
  margin-left: 4px;
}

.gc-run-selector-label {
  font-size: 0.65rem;
  color: var(--text-secondary, #a0a0b0);
  font-family: 'JetBrains Mono', monospace;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.gc-run-selector-age {
  font-size: 0.58rem;
  color: var(--text-muted, #666680);
}

.gc-run-selector-latest {
  font-size: 0.58rem;
  color: var(--color-success, #22c55e);
  font-weight: 600;
}

/* ---- Chart ---- */

.gc-chart-wrapper {
  flex: 1;
  min-height: 0;
  position: relative;
}

.gc-chart-container {
  width: 100%;
  height: 100%;
  cursor: crosshair;
}

.gc-chart-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #666680);
  font-size: 0.75rem;
  pointer-events: none;
}

/* uPlot overrides */
:deep(.gc-chart) {
  font-family: inherit;
}

:deep(.gc-chart .u-over) {
  cursor: crosshair !important;
}

/* ---- Component Results Table ---- */

.gc-table-wrapper {
  flex-shrink: 0;
  max-height: 140px;
  overflow-y: auto;
  border-top: 1px solid var(--border-color, #2a2a4a);
}

.gc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.65rem;
  table-layout: fixed;
}

.gc-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
}

.gc-table th {
  padding: 4px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary, #a0a0b0);
  background: var(--bg-secondary, #0f0f1a);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  white-space: nowrap;
  text-transform: uppercase;
  font-size: 0.58rem;
  letter-spacing: 0.04em;
}

.gc-th-component { width: 34%; }
.gc-th-rt { width: 14%; text-align: right; }
.gc-th-area { width: 16%; text-align: right; }
.gc-th-conc { width: 22%; text-align: right; }
.gc-th-unit { width: 14%; text-align: left; }

.gc-table td {
  padding: 3px 6px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.3);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.63rem;
}

.gc-td-component {
  font-family: 'Inter', sans-serif;
  color: var(--text-bright, #e2e8f0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-td-rt,
.gc-td-area,
.gc-td-conc {
  text-align: right;
  color: var(--text-primary, #fff);
}

.gc-td-unit {
  text-align: left;
  color: var(--text-muted, #666680);
  font-size: 0.58rem;
}

.gc-row-unidentified .gc-td-component {
  font-style: italic;
  color: var(--text-muted, #666680);
}

.gc-row-unidentified td {
  color: var(--text-dim, #64748b);
}

.gc-table tbody tr:hover {
  background: rgba(59, 130, 246, 0.06);
}

.gc-table-empty {
  padding: 10px;
  text-align: center;
  font-size: 0.68rem;
  color: var(--text-muted, #666680);
  border-top: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
}

/* ---- SST Status Bar ---- */

.gc-sst-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-top: 1px solid var(--border-color, #2a2a4a);
  background: rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
  flex-wrap: wrap;
  min-height: 24px;
}

.gc-sst-label {
  font-size: 0.6rem;
  font-weight: 700;
  color: var(--text-secondary, #a0a0b0);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  flex-shrink: 0;
}

.gc-sst-item {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 1px 5px;
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.2);
}

.gc-sst-name {
  font-size: 0.58rem;
  color: var(--text-secondary, #a0a0b0);
  font-weight: 500;
  max-width: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-sst-check {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 0.55rem;
  font-weight: 600;
  padding: 1px 3px;
  border-radius: 2px;
  font-family: 'JetBrains Mono', monospace;
}

.gc-sst-check.pass {
  color: var(--color-success, #22c55e);
  background: rgba(34, 197, 94, 0.1);
}

.gc-sst-check.pass svg {
  stroke: var(--color-success, #22c55e);
}

.gc-sst-check.fail {
  color: var(--color-error, #ef4444);
  background: rgba(239, 68, 68, 0.1);
}

.gc-sst-check.fail svg {
  stroke: var(--color-error, #ef4444);
}

/* ---- Dark mode support (already default, but ensure .dark class compat) ---- */

:root .dark .gc-widget,
.gc-widget {
  /* Dark mode is the default in this app */
}

/* Light mode override (when .light class is on document) */
:root.light .gc-widget {
  --bg-widget: #ffffff;
  --border-color: #e2e8f0;
  --text-bright: #1e293b;
  --text-secondary: #64748b;
  --text-muted: #94a3b8;
  --text-dim: #cbd5e1;
  --text-primary: #0f172a;
  --bg-secondary: #f8fafc;
  --bg-hover: #e2e8f0;
  --color-success: #16a34a;
  --color-error: #dc2626;
}

/* ---- Scrollbar styling for table ---- */

.gc-table-wrapper::-webkit-scrollbar {
  width: 4px;
}

.gc-table-wrapper::-webkit-scrollbar-track {
  background: transparent;
}

.gc-table-wrapper::-webkit-scrollbar-thumb {
  background: var(--border-color, #2a2a4a);
  border-radius: 2px;
}

.gc-table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted, #666680);
}
</style>
