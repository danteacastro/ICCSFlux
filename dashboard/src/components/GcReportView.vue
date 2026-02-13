<script setup lang="ts">
/**
 * GcReportView — GC Analysis Report Viewer
 *
 * Renders a GC analysis report for screen viewing and printing.
 * Includes chromatogram display, component results table, SST summary,
 * and export controls. Supports dark/light themes with print-friendly output.
 */
import { computed, ref } from 'vue'
import type { GCAnalysisResult, GCChromatogramData, GCPeakResult } from '../types'
import { useGcReport } from '../composables/useGcReport'

const props = defineProps<{
  chromatogram: GCChromatogramData | null
  result: GCAnalysisResult | null
  labName?: string
  instrumentName?: string
  operatorName?: string
  methodName?: string
  sampleId?: string
  notes?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { isGenerating, generateReport, printReport, exportCsv, downloadFile } = useGcReport()

// --------------------------------------------------------------------------
// Computed data
// --------------------------------------------------------------------------

const runTimestamp = computed(() => {
  if (!props.result?.timestamp) return 'N/A'
  try {
    return new Date(props.result.timestamp).toLocaleString()
  } catch {
    return props.result.timestamp
  }
})

/** Combined, sorted peak list */
const allPeaks = computed<GCPeakResult[]>(() => {
  if (!props.result) return []
  const peaks: GCPeakResult[] = []

  for (const [name, comp] of Object.entries(props.result.components)) {
    peaks.push({
      name,
      rt: comp.rt ?? 0,
      area: comp.area ?? 0,
      area_pct: comp.area_pct ?? 0,
      height: 0,
      width_s: 0,
      concentration: comp.concentration,
      unit: comp.unit,
      identified: true,
    })
  }

  if (props.result.unidentified_peaks) {
    for (const p of props.result.unidentified_peaks) {
      peaks.push({ ...p })
    }
  }

  peaks.sort((a, b) => a.rt - b.rt)
  return peaks
})

const identifiedPeaks = computed(() => allPeaks.value.filter(p => p.identified))
const unidentifiedPeaks = computed(() => allPeaks.value.filter(p => !p.identified))

/** Peaks that have SST data */
const sstPeaks = computed(() =>
  allPeaks.value.filter(p => p.identified && (p.plates != null || p.tailing != null || p.resolution != null))
)

const totalArea = computed(() =>
  props.result?.total_area ?? allPeaks.value.reduce((s, p) => s + p.area, 0)
)

const totalAreaPct = computed(() =>
  allPeaks.value.reduce((s, p) => s + p.area_pct, 0)
)

// SST criteria (USP/EP defaults)
const SST_MIN_PLATES = 2000
const SST_MAX_TAILING = 2.0
const SST_MIN_RESOLUTION = 1.5

function sstStatus(peak: GCPeakResult): { plates: string; tailing: string; resolution: string } {
  return {
    plates: peak.plates != null ? (peak.plates >= SST_MIN_PLATES ? 'PASS' : 'FAIL') : 'N/A',
    tailing: peak.tailing != null ? (peak.tailing <= SST_MAX_TAILING ? 'PASS' : 'FAIL') : 'N/A',
    resolution: peak.resolution != null ? (peak.resolution >= SST_MIN_RESOLUTION ? 'PASS' : 'FAIL') : 'N/A',
  }
}

const sstOverallPass = computed(() => {
  if (sstPeaks.value.length === 0) return null
  return sstPeaks.value.every(p => {
    const s = sstStatus(p)
    return s.plates !== 'FAIL' && s.tailing !== 'FAIL' && s.resolution !== 'FAIL'
  })
})

// --------------------------------------------------------------------------
// SVG Chromatogram rendering
// --------------------------------------------------------------------------

const svgWidth = 720
const svgHeight = 280
const margin = { top: 30, right: 20, bottom: 45, left: 60 }
const plotW = svgWidth - margin.left - margin.right
const plotH = svgHeight - margin.top - margin.bottom

const timeRange = computed(() => {
  if (!props.chromatogram || props.chromatogram.times.length === 0) return { min: 0, max: 1 }
  const t = props.chromatogram.times
  return { min: t[0] ?? 0, max: t[t.length - 1] ?? 0 }
})

const valueRange = computed(() => {
  if (!props.chromatogram || props.chromatogram.values.length === 0) return { min: 0, max: 1 }
  const vals = props.chromatogram.values
  let vMin = Math.min(...vals.filter((v): v is number => v !== undefined))
  let vMax = Math.max(...vals.filter((v): v is number => v !== undefined))
  const span = (vMax - vMin) || 1
  vMax += span * 0.15
  vMin = Math.min(0, vMin)
  return { min: vMin, max: vMax }
})

function toX(t: number): number {
  const range = timeRange.value.max - timeRange.value.min || 1
  return margin.left + ((t - timeRange.value.min) / range) * plotW
}

function toY(v: number): number {
  const span = valueRange.value.max - valueRange.value.min || 1
  return margin.top + plotH - ((v - valueRange.value.min) / span) * plotH
}

/** Polyline points string for the chromatogram trace */
const polylinePoints = computed(() => {
  if (!props.chromatogram) return ''
  const { times, values } = props.chromatogram
  if (times.length === 0) return ''

  const maxPts = 2000
  const step = Math.max(1, Math.floor(times.length / maxPts))
  const pts: string[] = []
  for (let i = 0; i < times.length; i += step) {
    pts.push(`${toX(times[i] ?? 0).toFixed(1)},${toY(values[i] ?? 0).toFixed(1)}`)
  }
  if ((times.length - 1) % step !== 0) {
    const last = times.length - 1
    pts.push(`${toX(times[last] ?? 0).toFixed(1)},${toY(values[last] ?? 0).toFixed(1)}`)
  }
  return pts.join(' ')
})

/** Baseline y coordinate (at value = 0) */
const baselineY = computed(() => toY(0))
const showBaseline = computed(() =>
  baselineY.value >= margin.top && baselineY.value <= margin.top + plotH
)

/** Axis tick generation helper */
function niceStep(range: number, targetTicks: number): number {
  const rough = range / targetTicks
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const residual = rough / mag
  let nice: number
  if (residual <= 1.5) nice = 1
  else if (residual <= 3.5) nice = 2
  else if (residual <= 7.5) nice = 5
  else nice = 10
  return nice * mag
}

function formatTickValue(v: number): string {
  if (Math.abs(v) >= 10000) return v.toExponential(1)
  if (Math.abs(v) >= 100) return v.toFixed(0)
  if (Math.abs(v) >= 1) return v.toFixed(1)
  return v.toFixed(2)
}

const timeTicks = computed(() => {
  const r = timeRange.value
  const range = r.max - r.min || 1
  const step = niceStep(range, 8)
  const start = Math.ceil(r.min / step) * step
  const ticks: { x: number; label: string }[] = []
  for (let t = start; t <= r.max; t += step) {
    ticks.push({ x: toX(t), label: t.toFixed(1) })
  }
  return ticks
})

const valueTicks = computed(() => {
  const r = valueRange.value
  const span = r.max - r.min || 1
  const step = niceStep(span, 5)
  const start = Math.ceil(r.min / step) * step
  const ticks: { y: number; label: string }[] = []
  for (let v = start; v <= r.max; v += step) {
    ticks.push({ y: toY(v), label: formatTickValue(v) })
  }
  return ticks
})

/** Peak label positions for the chromatogram SVG */
const peakLabels = computed(() => {
  if (!props.chromatogram) return []
  const { times, values } = props.chromatogram
  const step = Math.max(1, Math.floor(times.length / 4000))

  return allPeaks.value
    .filter(p => p.rt >= timeRange.value.min && p.rt <= timeRange.value.max)
    .map(peak => {
      // Find closest data point
      let closestIdx = 0
      let closestDist = Infinity
      for (let i = 0; i < times.length; i += step) {
        const d = Math.abs((times[i] ?? 0) - peak.rt)
        if (d < closestDist) {
          closestDist = d
          closestIdx = i
        }
      }
      const px = toX(peak.rt)
      const py = toY(values[closestIdx] ?? 0)
      const labelY = Math.max(margin.top + 8, py - 10)
      return { name: peak.name, px, py, labelY }
    })
})

// --------------------------------------------------------------------------
// Actions
// --------------------------------------------------------------------------

function handlePrint() {
  if (!props.chromatogram || !props.result) return
  const html = generateReport({
    chromatogram: props.chromatogram,
    result: props.result,
    labName: props.labName,
    instrumentName: props.instrumentName,
    operatorName: props.operatorName,
    methodName: props.methodName,
    sampleId: props.sampleId,
    notes: props.notes,
  })
  printReport(html)
}

function handlePrintPage() {
  window.print()
}

function handleExportCsv() {
  if (!props.result) return
  const csv = exportCsv(props.result, props.chromatogram ?? undefined)
  const filename = `gc_run_${props.result.run_number}_${Date.now()}.csv`
  downloadFile(csv, filename, 'text/csv')
}

function handleExportJson() {
  if (!props.result) return
  const data = {
    result: props.result,
    chromatogram: props.chromatogram,
    metadata: {
      labName: props.labName,
      instrumentName: props.instrumentName,
      operatorName: props.operatorName,
      methodName: props.methodName,
      sampleId: props.sampleId,
      notes: props.notes,
      exportedAt: new Date().toISOString(),
    },
  }
  const json = JSON.stringify(data, null, 2)
  const filename = `gc_run_${props.result.run_number}_${Date.now()}.json`
  downloadFile(json, filename, 'application/json')
}

/** Show/hide sections */
const showUnidentified = ref(true)
const showSst = ref(true)
const showNotes = ref(true)
</script>

<template>
  <div class="gc-report-view" v-if="result">
    <!-- Toolbar (hidden when printing) -->
    <div class="report-toolbar no-print">
      <div class="toolbar-left">
        <button class="btn btn-primary" @click="handlePrint" :disabled="!chromatogram || isGenerating">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 6 2 18 2 18 9"/>
            <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/>
            <rect x="6" y="14" width="12" height="8"/>
          </svg>
          Print Report
        </button>
        <button class="btn btn-secondary" @click="handlePrintPage">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <path d="M3 9h18"/>
          </svg>
          Print Page
        </button>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-secondary" @click="handleExportCsv" :disabled="!result">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Export CSV
        </button>
        <button class="btn btn-secondary" @click="handleExportJson" :disabled="!result">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Export JSON
        </button>
      </div>
    </div>

    <!-- Report Header -->
    <div class="report-header">
      <h1 class="report-title">GC Analysis Report</h1>
      <div class="report-subtitle">
        Run #{{ result.run_number }}
        <span v-if="result.method"> | Method: {{ result.method }}</span>
      </div>
    </div>

    <!-- Metadata Grid -->
    <div class="meta-grid">
      <div class="meta-item">
        <span class="meta-label">Lab:</span>
        <span class="meta-value">{{ labName || '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Instrument:</span>
        <span class="meta-value">{{ instrumentName || '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Operator:</span>
        <span class="meta-value">{{ operatorName || '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Method:</span>
        <span class="meta-value">{{ methodName || result.method || '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Sample ID:</span>
        <span class="meta-value">{{ sampleId || '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Run Date:</span>
        <span class="meta-value">{{ runTimestamp }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Port:</span>
        <span class="meta-value">
          {{ result.port ?? '--' }}
          <span v-if="result.port_label"> ({{ result.port_label }})</span>
        </span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Duration:</span>
        <span class="meta-value">{{ result.run_duration_s != null ? result.run_duration_s.toFixed(1) + ' s' : '--' }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Finish:</span>
        <span class="meta-value">{{ result.finish_reason || '--' }}</span>
      </div>
    </div>

    <!-- Chromatogram SVG -->
    <div class="section" v-if="chromatogram && chromatogram.times.length > 0">
      <h2 class="section-title">Chromatogram</h2>
      <div class="chromatogram-container">
        <svg :width="svgWidth" :height="svgHeight" xmlns="http://www.w3.org/2000/svg" class="chromatogram-svg">
          <!-- Plot area background -->
          <rect :x="margin.left" :y="margin.top" :width="plotW" :height="plotH"
                class="plot-bg"/>

          <!-- Time axis grid lines and ticks -->
          <template v-for="tick in timeTicks" :key="'t-' + tick.label">
            <line :x1="tick.x" :y1="margin.top" :x2="tick.x" :y2="margin.top + plotH"
                  class="grid-line"/>
            <line :x1="tick.x" :y1="margin.top + plotH" :x2="tick.x" :y2="margin.top + plotH + 5"
                  class="tick-mark"/>
            <text :x="tick.x" :y="margin.top + plotH + 18"
                  text-anchor="middle" class="tick-label">{{ tick.label }}</text>
          </template>

          <!-- Value axis grid lines and ticks -->
          <template v-for="tick in valueTicks" :key="'v-' + tick.label">
            <line :x1="margin.left" :y1="tick.y" :x2="margin.left + plotW" :y2="tick.y"
                  class="grid-line"/>
            <line :x1="margin.left - 5" :y1="tick.y" :x2="margin.left" :y2="tick.y"
                  class="tick-mark"/>
            <text :x="margin.left - 8" :y="tick.y + 3"
                  text-anchor="end" class="tick-label">{{ tick.label }}</text>
          </template>

          <!-- Baseline dashed line -->
          <line v-if="showBaseline"
                :x1="margin.left" :y1="baselineY"
                :x2="margin.left + plotW" :y2="baselineY"
                class="baseline"/>

          <!-- Chromatogram trace -->
          <polyline :points="polylinePoints"
                    fill="none" class="trace-line"/>

          <!-- Peak labels -->
          <template v-for="label in peakLabels" :key="'pk-' + label.name">
            <line :x1="label.px" :y1="label.py" :x2="label.px" :y2="label.labelY + 3"
                  class="peak-leader"/>
            <text :x="label.px" :y="label.labelY"
                  text-anchor="middle" class="peak-label">{{ label.name }}</text>
          </template>

          <!-- Axis labels -->
          <text :x="margin.left + plotW / 2" :y="svgHeight - 4"
                text-anchor="middle" class="axis-label">Retention Time (s)</text>
          <text x="14" :y="margin.top + plotH / 2"
                text-anchor="middle" class="axis-label"
                :transform="`rotate(-90, 14, ${margin.top + plotH / 2})`">Response (mV)</text>

          <!-- Chart title -->
          <text :x="margin.left + plotW / 2" y="16"
                text-anchor="middle" class="chart-title">
            Chromatogram - Run #{{ chromatogram.run_number }}
          </text>
        </svg>
      </div>
    </div>

    <div class="section" v-else>
      <h2 class="section-title">Chromatogram</h2>
      <div class="empty-state">No chromatogram data available for this run.</div>
    </div>

    <!-- Component Results Table -->
    <div class="section">
      <h2 class="section-title">Component Results</h2>
      <table class="data-table" v-if="identifiedPeaks.length > 0">
        <thead>
          <tr>
            <th>Component</th>
            <th class="num">RT (s)</th>
            <th class="num">Area %</th>
            <th class="num">Concentration</th>
            <th>Unit</th>
            <th class="num">Area</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="peak in identifiedPeaks" :key="peak.name">
            <td class="name">{{ peak.name }}</td>
            <td class="num mono">{{ peak.rt.toFixed(2) }}</td>
            <td class="num mono">{{ peak.area_pct.toFixed(3) }}</td>
            <td class="num mono">{{ peak.concentration != null ? peak.concentration.toFixed(4) : '--' }}</td>
            <td>{{ peak.unit || '' }}</td>
            <td class="num mono">{{ peak.area.toFixed(0) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">No identified components in this run.</div>
    </div>

    <!-- Unidentified Peaks Table -->
    <div class="section" v-if="unidentifiedPeaks.length > 0 && showUnidentified">
      <h2 class="section-title">
        Unidentified Peaks
        <button class="toggle-btn no-print" @click="showUnidentified = false">Hide</button>
      </h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>Peak</th>
            <th class="num">RT (s)</th>
            <th class="num">Area %</th>
            <th class="num">Area</th>
            <th class="num">Height</th>
            <th class="num">Width (s)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="peak in unidentifiedPeaks" :key="peak.name + peak.rt">
            <td class="name">{{ peak.name }}</td>
            <td class="num mono">{{ peak.rt.toFixed(2) }}</td>
            <td class="num mono">{{ peak.area_pct.toFixed(3) }}</td>
            <td class="num mono">{{ peak.area.toFixed(0) }}</td>
            <td class="num mono">{{ peak.height.toFixed(0) }}</td>
            <td class="num mono">{{ peak.width_s.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="section" v-else-if="unidentifiedPeaks.length > 0 && !showUnidentified">
      <h2 class="section-title">
        Unidentified Peaks ({{ unidentifiedPeaks.length }})
        <button class="toggle-btn no-print" @click="showUnidentified = true">Show</button>
      </h2>
    </div>

    <!-- SST Summary -->
    <div class="section" v-if="showSst">
      <h2 class="section-title">
        System Suitability Test (SST)
        <button class="toggle-btn no-print" @click="showSst = false" v-if="sstPeaks.length > 0">Hide</button>
      </h2>

      <template v-if="sstPeaks.length > 0">
        <div class="sst-overall" :class="{
          pass: sstOverallPass === true,
          fail: sstOverallPass === false,
        }">
          Overall: {{ sstOverallPass === true ? 'PASS' : sstOverallPass === false ? 'FAIL' : 'N/A' }}
        </div>

        <table class="data-table">
          <thead>
            <tr>
              <th>Component</th>
              <th class="num">Plates (N)</th>
              <th>Status</th>
              <th class="num">Tailing (T)</th>
              <th>Status</th>
              <th class="num">Resolution (Rs)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="peak in sstPeaks" :key="'sst-' + peak.name">
              <td class="name">{{ peak.name }}</td>
              <td class="num mono">{{ peak.plates != null ? peak.plates.toFixed(0) : '--' }}</td>
              <td :class="['status-cell', sstStatus(peak).plates.toLowerCase()]">{{ sstStatus(peak).plates }}</td>
              <td class="num mono">{{ peak.tailing != null ? peak.tailing.toFixed(3) : '--' }}</td>
              <td :class="['status-cell', sstStatus(peak).tailing.toLowerCase()]">{{ sstStatus(peak).tailing }}</td>
              <td class="num mono">{{ peak.resolution != null ? peak.resolution.toFixed(2) : '--' }}</td>
              <td :class="['status-cell', sstStatus(peak).resolution.toLowerCase()]">{{ sstStatus(peak).resolution }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <div v-else class="empty-state">No SST data available for this run.</div>
    </div>
    <div class="section" v-else>
      <h2 class="section-title">
        System Suitability Test (SST)
        <button class="toggle-btn no-print" @click="showSst = true">Show</button>
      </h2>
    </div>

    <!-- QC Summary -->
    <div class="section">
      <h2 class="section-title">QC Summary</h2>
      <div class="qc-grid">
        <div class="qc-item">
          <div class="qc-label">Total Area</div>
          <div class="qc-value">{{ totalArea.toFixed(0) }}</div>
        </div>
        <div class="qc-item">
          <div class="qc-label">Area Sum %</div>
          <div class="qc-value">{{ totalAreaPct.toFixed(2) }}</div>
        </div>
        <div class="qc-item">
          <div class="qc-label">Components</div>
          <div class="qc-value">{{ identifiedPeaks.length }}</div>
        </div>
        <div class="qc-item">
          <div class="qc-label">Unidentified</div>
          <div class="qc-value">{{ unidentifiedPeaks.length }}</div>
        </div>
      </div>
    </div>

    <!-- Notes -->
    <div class="section" v-if="notes && showNotes">
      <h2 class="section-title">
        Notes
        <button class="toggle-btn no-print" @click="showNotes = false">Hide</button>
      </h2>
      <div class="notes-box">{{ notes }}</div>
    </div>
    <div class="section" v-else-if="notes && !showNotes">
      <h2 class="section-title">
        Notes
        <button class="toggle-btn no-print" @click="showNotes = true">Show</button>
      </h2>
    </div>

    <!-- Footer -->
    <div class="report-footer">
      <span>Generated: {{ new Date().toISOString().replace('T', ' ').slice(0, 19) }} | ICCSFlux GC Report</span>
    </div>
  </div>

  <!-- Empty state when no result -->
  <div class="gc-report-view gc-report-empty" v-else>
    <div class="empty-state-large">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      <p>No GC analysis result selected.</p>
      <p class="hint">Select a completed run to view the report.</p>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   Screen styles — dark theme (default)
   ============================================================ */

.gc-report-view {
  padding: 16px 20px;
  color: var(--text-primary);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  max-width: 900px;
  margin: 0 auto;
}

/* --- Toolbar --- */

.report-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  font-family: inherit;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent-dark);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

.btn-secondary {
  background: var(--btn-bg);
  color: var(--text-bright);
  border-color: var(--border-color);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--btn-hover);
  border-color: var(--border-light);
}

/* --- Report Header --- */

.report-header {
  border-bottom: 2px solid var(--color-accent);
  padding-bottom: 10px;
  margin-bottom: 14px;
}

.report-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.report-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* --- Metadata Grid --- */

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 4px 20px;
  margin-bottom: 16px;
  font-size: 12px;
}

.meta-item {
  display: flex;
  gap: 6px;
  align-items: baseline;
}

.meta-label {
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  min-width: 70px;
}

.meta-value {
  color: var(--text-bright);
}

/* --- Sections --- */

.section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-accent-light);
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 4px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.toggle-btn {
  font-size: 10px;
  padding: 1px 8px;
  border: 1px solid var(--border-color);
  border-radius: 3px;
  background: var(--btn-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
}

.toggle-btn:hover {
  background: var(--btn-hover);
  color: var(--text-bright);
}

/* --- Chromatogram SVG --- */

.chromatogram-container {
  text-align: center;
  overflow-x: auto;
}

.chromatogram-svg {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  max-width: 100%;
  height: auto;
}

.chromatogram-svg .plot-bg {
  fill: var(--bg-secondary);
  stroke: var(--border-color);
  stroke-width: 1;
}

.chromatogram-svg .grid-line {
  stroke: var(--border-color);
  stroke-width: 0.5;
  stroke-dasharray: 3,3;
}

.chromatogram-svg .tick-mark {
  stroke: var(--text-muted);
  stroke-width: 1;
}

.chromatogram-svg .tick-label {
  font-size: 10px;
  font-family: 'Inter', sans-serif;
  fill: var(--text-secondary);
}

.chromatogram-svg .baseline {
  stroke: var(--text-muted);
  stroke-width: 1;
  stroke-dasharray: 6,3;
}

.chromatogram-svg .trace-line {
  stroke: var(--color-accent-light);
  stroke-width: 1.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.chromatogram-svg .peak-leader {
  stroke: var(--text-muted);
  stroke-width: 0.5;
  stroke-dasharray: 2,2;
}

.chromatogram-svg .peak-label {
  font-size: 8px;
  font-family: 'Inter', sans-serif;
  fill: var(--text-secondary);
  font-weight: 500;
}

.chromatogram-svg .axis-label {
  font-size: 11px;
  font-family: 'Inter', sans-serif;
  fill: var(--text-secondary);
}

.chromatogram-svg .chart-title {
  font-size: 12px;
  font-family: 'Inter', sans-serif;
  fill: var(--text-bright);
  font-weight: 600;
}

/* --- Data Tables --- */

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  padding: 5px 8px;
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  color: var(--text-secondary);
}

.data-table th.num {
  text-align: right;
}

.data-table td {
  border: 1px solid var(--border-color);
  padding: 4px 8px;
  color: var(--text-bright);
}

.data-table td.num {
  text-align: right;
}

.data-table td.mono {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 11px;
}

.data-table td.name {
  font-weight: 500;
}

.data-table tbody tr:nth-child(even) {
  background: var(--bg-panel-row);
}

.data-table tbody tr:hover {
  background: var(--bg-hover);
}

/* --- SST Status Cells --- */

.status-cell {
  text-align: center;
  font-weight: 600;
  font-size: 11px;
}

.status-cell.pass {
  color: var(--color-success);
}

.status-cell.fail {
  color: var(--color-error);
  background: var(--color-error-bg);
}

.status-cell.n\/a {
  color: var(--text-muted);
}

.sst-overall {
  display: inline-block;
  padding: 3px 14px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 12px;
  margin-bottom: 8px;
}

.sst-overall.pass {
  background: var(--color-success-bg);
  color: var(--color-success);
  border: 1px solid var(--color-success-dark);
}

.sst-overall.fail {
  background: var(--color-error-bg);
  color: var(--color-error);
  border: 1px solid var(--color-error-dark);
}

/* --- QC Grid --- */

.qc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 8px;
}

.qc-item {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 8px 12px;
  text-align: center;
}

.qc-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.qc-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
}

/* --- Notes --- */

.notes-box {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 10px 14px;
  font-size: 12px;
  white-space: pre-wrap;
  color: var(--text-bright);
}

/* --- Footer --- */

.report-footer {
  margin-top: 20px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
  font-size: 10px;
  color: var(--text-muted);
}

/* --- Empty States --- */

.empty-state {
  text-align: center;
  padding: 16px;
  color: var(--text-muted);
  font-style: italic;
  font-size: 12px;
}

.gc-report-empty {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}

.empty-state-large {
  text-align: center;
  color: var(--text-muted);
}

.empty-state-large svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state-large p {
  font-size: 14px;
  margin-bottom: 4px;
}

.empty-state-large .hint {
  font-size: 12px;
  color: var(--text-dim);
}

/* ============================================================
   Light theme overrides
   ============================================================ */

[data-theme="light"] .chromatogram-svg .trace-line {
  stroke: #1a56db;
}

[data-theme="light"] .chromatogram-svg .chart-title {
  fill: #222;
}

[data-theme="light"] .chromatogram-svg .peak-label {
  fill: #333;
}

[data-theme="light"] .section-title {
  color: #1a56db;
}

/* ============================================================
   Print styles
   ============================================================ */

@media print {
  .gc-report-view {
    padding: 10px 15px;
    color: #1a1a1a;
    font-size: 11px;
    max-width: none;
  }

  .no-print {
    display: none !important;
  }

  .report-header {
    border-bottom-color: #1a56db;
  }

  .report-title {
    color: #1a1a1a;
    font-size: 18px;
  }

  .report-subtitle {
    color: #555;
  }

  .meta-label {
    color: #555;
  }

  .meta-value {
    color: #1a1a1a;
  }

  .section-title {
    color: #1a56db;
    border-bottom-color: #ddd;
  }

  .section {
    page-break-inside: avoid;
  }

  .chromatogram-svg {
    background: #fff;
    border-color: #ddd;
  }

  .chromatogram-svg .plot-bg {
    fill: #fafafa;
    stroke: #ccc;
  }

  .chromatogram-svg .grid-line {
    stroke: #e0e0e0;
  }

  .chromatogram-svg .tick-mark {
    stroke: #333;
  }

  .chromatogram-svg .tick-label {
    fill: #333;
  }

  .chromatogram-svg .baseline {
    stroke: #aaa;
  }

  .chromatogram-svg .trace-line {
    stroke: #1a56db;
  }

  .chromatogram-svg .peak-leader {
    stroke: #888;
  }

  .chromatogram-svg .peak-label {
    fill: #333;
  }

  .chromatogram-svg .axis-label {
    fill: #333;
  }

  .chromatogram-svg .chart-title {
    fill: #222;
  }

  .data-table th {
    background: #f0f4f8;
    border-color: #ccc;
    color: #333;
  }

  .data-table td {
    border-color: #ddd;
    color: #1a1a1a;
  }

  .data-table tbody tr:nth-child(even) {
    background: #fafafa;
  }

  .data-table tbody tr:hover {
    background: inherit;
  }

  .status-cell.pass {
    color: #16a34a;
  }

  .status-cell.fail {
    color: #dc2626;
    background: #fef2f2;
  }

  .sst-overall.pass {
    background: #dcfce7;
    color: #16a34a;
    border-color: #86efac;
  }

  .sst-overall.fail {
    background: #fef2f2;
    color: #dc2626;
    border-color: #fca5a5;
  }

  .qc-item {
    background: #f8fafc;
    border-color: #e2e8f0;
  }

  .qc-label {
    color: #666;
  }

  .qc-value {
    color: #1a1a1a;
  }

  .notes-box {
    background: #f8fafc;
    border-color: #e2e8f0;
    color: #333;
  }

  .report-footer {
    border-top-color: #ddd;
    color: #999;
  }

  .toggle-btn {
    display: none;
  }
}
</style>
