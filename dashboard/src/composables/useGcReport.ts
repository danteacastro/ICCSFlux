import { ref } from 'vue'
import type { GCAnalysisResult, GCChromatogramData, GCPeakResult } from '../types'

// ============================================================================
// GC Report Generator — printable HTML reports and CSV export for GC analysis
// ============================================================================

/** Options for report generation */
export interface GcReportOptions {
  chromatogram: GCChromatogramData
  result: GCAnalysisResult
  labName?: string
  instrumentName?: string
  operatorName?: string
  methodName?: string
  sampleId?: string
  notes?: string
}

/** SST criteria thresholds (USP/EP defaults) */
interface SstCriteria {
  minPlates: number
  maxTailing: number
  minResolution: number
}

const DEFAULT_SST: SstCriteria = {
  minPlates: 2000,
  maxTailing: 2.0,
  minResolution: 1.5,
}

export function useGcReport() {
  const isGenerating = ref(false)

  // --------------------------------------------------------------------------
  // Internal: build the combined peak list from result
  // --------------------------------------------------------------------------
  function _buildPeakList(result: GCAnalysisResult): GCPeakResult[] {
    const peaks: GCPeakResult[] = []

    // Identified components
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
        identified: true,
      })
    }

    // Unidentified peaks
    if (result.unidentified_peaks) {
      for (const p of result.unidentified_peaks) {
        peaks.push({ ...p })
      }
    }

    // Sort by retention time
    peaks.sort((a, b) => a.rt - b.rt)
    return peaks
  }

  // --------------------------------------------------------------------------
  // Internal: render SVG chromatogram from times/values
  // --------------------------------------------------------------------------
  function _renderChromatogramSvg(
    chromatogram: GCChromatogramData,
    peaks: GCPeakResult[],
    width: number = 700,
    height: number = 280
  ): string {
    const margin = { top: 30, right: 20, bottom: 45, left: 60 }
    const plotW = width - margin.left - margin.right
    const plotH = height - margin.top - margin.bottom

    const times = chromatogram.times
    const values = chromatogram.values
    if (times.length === 0 || values.length === 0) {
      return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
        <text x="${width / 2}" y="${height / 2}" text-anchor="middle"
              font-family="Inter, sans-serif" font-size="14" fill="#666">
          No chromatogram data available
        </text>
      </svg>`
    }

    const tMin = times[0]!
    const tMax = times[times.length - 1]!
    const tRange = tMax - tMin || 1

    let vMin = Math.min(...values)
    let vMax = Math.max(...values)
    // Add 10% headroom above
    const vRange = (vMax - vMin) || 1
    vMax = vMax + vRange * 0.15
    vMin = Math.min(0, vMin)
    const vSpan = vMax - vMin || 1

    // Convert data to SVG coordinates
    function toX(t: number): number {
      return margin.left + ((t - tMin) / tRange) * plotW
    }
    function toY(v: number): number {
      return margin.top + plotH - ((v - vMin) / vSpan) * plotH
    }

    // Build polyline points (downsample if too many points)
    const maxPoints = 2000
    const step = Math.max(1, Math.floor(times.length / maxPoints))
    const pointStrs: string[] = []
    for (let i = 0; i < times.length; i += step) {
      pointStrs.push(`${toX(times[i] ?? 0).toFixed(1)},${toY(values[i] ?? 0).toFixed(1)}`)
    }
    // Always include last point
    if ((times.length - 1) % step !== 0) {
      const last = times.length - 1
      pointStrs.push(`${toX(times[last] ?? 0).toFixed(1)},${toY(values[last] ?? 0).toFixed(1)}`)
    }

    // Generate time axis tick marks
    const numTimeTicks = 8
    const timeStep = _niceStep(tRange, numTimeTicks)
    const timeTickStart = Math.ceil(tMin / timeStep) * timeStep
    let timeTicks = ''
    for (let t = timeTickStart; t <= tMax; t += timeStep) {
      const x = toX(t)
      timeTicks += `<line x1="${x.toFixed(1)}" y1="${margin.top + plotH}"
                          x2="${x.toFixed(1)}" y2="${margin.top + plotH + 5}"
                          stroke="#333" stroke-width="1"/>`
      timeTicks += `<text x="${x.toFixed(1)}" y="${margin.top + plotH + 18}"
                         text-anchor="middle" font-size="10" font-family="Inter, sans-serif"
                         fill="#333">${t.toFixed(1)}</text>`
      // Grid line
      timeTicks += `<line x1="${x.toFixed(1)}" y1="${margin.top}"
                          x2="${x.toFixed(1)}" y2="${margin.top + plotH}"
                          stroke="#e0e0e0" stroke-width="0.5" stroke-dasharray="3,3"/>`
    }

    // Value axis ticks
    const numValTicks = 5
    const valStep = _niceStep(vSpan, numValTicks)
    const valTickStart = Math.ceil(vMin / valStep) * valStep
    let valTicks = ''
    for (let v = valTickStart; v <= vMax; v += valStep) {
      const y = toY(v)
      valTicks += `<line x1="${margin.left - 5}" y1="${y.toFixed(1)}"
                         x2="${margin.left}" y2="${y.toFixed(1)}"
                         stroke="#333" stroke-width="1"/>`
      valTicks += `<text x="${margin.left - 8}" y="${(y + 3).toFixed(1)}"
                        text-anchor="end" font-size="10" font-family="Inter, sans-serif"
                        fill="#333">${_formatTickValue(v)}</text>`
      // Grid line
      valTicks += `<line x1="${margin.left}" y1="${y.toFixed(1)}"
                         x2="${margin.left + plotW}" y2="${y.toFixed(1)}"
                         stroke="#e0e0e0" stroke-width="0.5" stroke-dasharray="3,3"/>`
    }

    // Peak labels at apex positions
    let peakLabels = ''
    for (const peak of peaks) {
      if (peak.rt >= tMin && peak.rt <= tMax) {
        // Find closest data point to determine y position
        let closestIdx = 0
        let closestDist = Infinity
        for (let i = 0; i < times.length; i += Math.max(1, Math.floor(step / 2))) {
          const d = Math.abs((times[i] ?? 0) - peak.rt)
          if (d < closestDist) {
            closestDist = d
            closestIdx = i
          }
        }
        const px = toX(peak.rt)
        const py = toY(values[closestIdx] ?? 0)
        const labelY = Math.max(margin.top + 8, py - 10)

        // Vertical tick from peak to label
        peakLabels += `<line x1="${px.toFixed(1)}" y1="${py.toFixed(1)}"
                             x2="${px.toFixed(1)}" y2="${(labelY + 3).toFixed(1)}"
                             stroke="#888" stroke-width="0.5" stroke-dasharray="2,2"/>`
        peakLabels += `<text x="${px.toFixed(1)}" y="${labelY.toFixed(1)}"
                            text-anchor="middle" font-size="8" font-family="Inter, sans-serif"
                            fill="#333" font-weight="500">${_escapeXml(peak.name)}</text>`
      }
    }

    // Baseline dashed line (at value=0 or min)
    const baselineY = toY(0)
    const baselineLine = baselineY >= margin.top && baselineY <= margin.top + plotH
      ? `<line x1="${margin.left}" y1="${baselineY.toFixed(1)}"
              x2="${margin.left + plotW}" y2="${baselineY.toFixed(1)}"
              stroke="#aaa" stroke-width="1" stroke-dasharray="6,3"/>`
      : ''

    return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg"
                 style="background: #fff; border: 1px solid #ddd; border-radius: 4px;">
      <!-- Plot area background -->
      <rect x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}"
            fill="#fafafa" stroke="#ccc" stroke-width="1"/>

      <!-- Grid and ticks -->
      ${timeTicks}
      ${valTicks}

      <!-- Baseline -->
      ${baselineLine}

      <!-- Chromatogram trace -->
      <polyline points="${pointStrs.join(' ')}"
                fill="none" stroke="#1a56db" stroke-width="1.5"
                stroke-linejoin="round" stroke-linecap="round"/>

      <!-- Peak labels -->
      ${peakLabels}

      <!-- Axis labels -->
      <text x="${margin.left + plotW / 2}" y="${height - 4}"
            text-anchor="middle" font-size="11" font-family="Inter, sans-serif"
            fill="#333">Retention Time (s)</text>
      <text x="14" y="${margin.top + plotH / 2}"
            text-anchor="middle" font-size="11" font-family="Inter, sans-serif"
            fill="#333" transform="rotate(-90, 14, ${margin.top + plotH / 2})">Response (mV)</text>

      <!-- Title -->
      <text x="${margin.left + plotW / 2}" y="16"
            text-anchor="middle" font-size="12" font-family="Inter, sans-serif"
            fill="#222" font-weight="600">Chromatogram - Run #${chromatogram.run_number}</text>
    </svg>`
  }

  // --------------------------------------------------------------------------
  // Internal: nice step calculator for axis ticks
  // --------------------------------------------------------------------------
  function _niceStep(range: number, targetTicks: number): number {
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

  function _formatTickValue(v: number): string {
    if (Math.abs(v) >= 10000) return v.toExponential(1)
    if (Math.abs(v) >= 100) return v.toFixed(0)
    if (Math.abs(v) >= 1) return v.toFixed(1)
    return v.toFixed(2)
  }

  function _escapeXml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  }

  // --------------------------------------------------------------------------
  // Internal: SST pass/fail evaluation
  // --------------------------------------------------------------------------
  function _evaluateSst(
    peak: GCPeakResult,
    criteria: SstCriteria = DEFAULT_SST
  ): { plates: string; tailing: string; resolution: string } {
    const plates = peak.plates != null
      ? (peak.plates >= criteria.minPlates ? 'PASS' : 'FAIL')
      : 'N/A'
    const tailing = peak.tailing != null
      ? (peak.tailing <= criteria.maxTailing ? 'PASS' : 'FAIL')
      : 'N/A'
    const resolution = peak.resolution != null
      ? (peak.resolution >= criteria.minResolution ? 'PASS' : 'FAIL')
      : 'N/A'
    return { plates, tailing, resolution }
  }

  // --------------------------------------------------------------------------
  // Generate a complete self-contained HTML report
  // --------------------------------------------------------------------------
  function generateReport(options: GcReportOptions): string {
    isGenerating.value = true
    try {
      const { chromatogram, result } = options
      const peaks = _buildPeakList(result)
      const svgContent = _renderChromatogramSvg(chromatogram, peaks)
      const now = new Date()
      const reportDate = now.toISOString().replace('T', ' ').slice(0, 19)
      const runTimestamp = result.timestamp
        ? new Date(result.timestamp).toLocaleString()
        : 'N/A'

      // Identified components table rows
      const identifiedPeaks = peaks.filter(p => p.identified)
      const unidentifiedPeaks = peaks.filter(p => !p.identified)

      let componentRows = ''
      for (const peak of identifiedPeaks) {
        componentRows += `<tr>
          <td>${_escapeXml(peak.name)}</td>
          <td class="num">${peak.rt.toFixed(2)}</td>
          <td class="num">${peak.area_pct.toFixed(3)}</td>
          <td class="num">${peak.concentration != null ? peak.concentration.toFixed(4) : '--'}</td>
          <td>${_escapeXml(peak.unit || '')}</td>
          <td class="num">${peak.area.toFixed(0)}</td>
        </tr>`
      }
      if (identifiedPeaks.length === 0) {
        componentRows = `<tr><td colspan="6" class="empty">No identified components</td></tr>`
      }

      // Unidentified peaks table rows
      let unidentifiedRows = ''
      for (const peak of unidentifiedPeaks) {
        unidentifiedRows += `<tr>
          <td>${_escapeXml(peak.name)}</td>
          <td class="num">${peak.rt.toFixed(2)}</td>
          <td class="num">${peak.area_pct.toFixed(3)}</td>
          <td class="num">${peak.area.toFixed(0)}</td>
          <td class="num">${peak.height.toFixed(0)}</td>
          <td class="num">${peak.width_s.toFixed(2)}</td>
        </tr>`
      }

      // SST summary table rows
      let sstRows = ''
      let sstOverallPass = true
      const sstPeaks = peaks.filter(p => p.identified && (p.plates != null || p.tailing != null || p.resolution != null))
      for (const peak of sstPeaks) {
        const sst = _evaluateSst(peak)
        const anyFail = sst.plates === 'FAIL' || sst.tailing === 'FAIL' || sst.resolution === 'FAIL'
        if (anyFail) sstOverallPass = false
        sstRows += `<tr>
          <td>${_escapeXml(peak.name)}</td>
          <td class="num">${peak.plates != null ? peak.plates.toFixed(0) : '--'}</td>
          <td class="${sst.plates === 'FAIL' ? 'fail' : sst.plates === 'PASS' ? 'pass' : ''}">${sst.plates}</td>
          <td class="num">${peak.tailing != null ? peak.tailing.toFixed(3) : '--'}</td>
          <td class="${sst.tailing === 'FAIL' ? 'fail' : sst.tailing === 'PASS' ? 'pass' : ''}">${sst.tailing}</td>
          <td class="num">${peak.resolution != null ? peak.resolution.toFixed(2) : '--'}</td>
          <td class="${sst.resolution === 'FAIL' ? 'fail' : sst.resolution === 'PASS' ? 'pass' : ''}">${sst.resolution}</td>
        </tr>`
      }

      // QC summary
      const totalArea = result.total_area ?? peaks.reduce((s, p) => s + p.area, 0)
      const totalPct = peaks.reduce((s, p) => s + p.area_pct, 0)
      const numComponents = identifiedPeaks.length
      const numUnidentified = unidentifiedPeaks.length

      // Notes section
      const notesHtml = options.notes
        ? `<div class="section">
            <h2>Notes</h2>
            <div class="notes-box">${_escapeXml(options.notes)}</div>
           </div>`
        : ''

      return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GC Analysis Report - Run #${result.run_number}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
      font-size: 11px;
      line-height: 1.4;
      color: #1a1a1a;
      background: #fff;
      padding: 20px 30px;
    }

    .report-header {
      border-bottom: 2px solid #1a56db;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }

    .report-header h1 {
      font-size: 20px;
      font-weight: 700;
      color: #1a1a1a;
      margin-bottom: 2px;
    }

    .report-header .subtitle {
      font-size: 12px;
      color: #555;
    }

    .meta-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 6px 24px;
      margin-bottom: 16px;
      font-size: 11px;
    }

    .meta-grid .meta-item {
      display: flex;
      gap: 6px;
    }

    .meta-grid .meta-label {
      font-weight: 600;
      color: #555;
      white-space: nowrap;
    }

    .meta-grid .meta-value {
      color: #1a1a1a;
    }

    .section {
      margin-bottom: 16px;
      page-break-inside: avoid;
    }

    .section h2 {
      font-size: 13px;
      font-weight: 600;
      color: #1a56db;
      border-bottom: 1px solid #ddd;
      padding-bottom: 3px;
      margin-bottom: 8px;
    }

    .chromatogram-container {
      text-align: center;
      margin-bottom: 16px;
    }

    .chromatogram-container svg {
      max-width: 100%;
      height: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 10px;
    }

    table th {
      background: #f0f4f8;
      border: 1px solid #ccc;
      padding: 4px 6px;
      text-align: left;
      font-weight: 600;
      font-size: 10px;
      color: #333;
    }

    table td {
      border: 1px solid #ddd;
      padding: 3px 6px;
    }

    table td.num {
      text-align: right;
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 10px;
    }

    table td.empty {
      text-align: center;
      color: #888;
      font-style: italic;
      padding: 8px;
    }

    table tr:nth-child(even) {
      background: #fafafa;
    }

    table td.pass {
      color: #16a34a;
      font-weight: 600;
      text-align: center;
    }

    table td.fail {
      color: #dc2626;
      font-weight: 700;
      text-align: center;
      background: #fef2f2;
    }

    .qc-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 8px;
    }

    .qc-item {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 4px;
      padding: 6px 10px;
      text-align: center;
    }

    .qc-item .qc-label {
      font-size: 9px;
      color: #666;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .qc-item .qc-value {
      font-size: 14px;
      font-weight: 700;
      color: #1a1a1a;
      font-family: 'JetBrains Mono', monospace;
    }

    .sst-overall {
      display: inline-block;
      padding: 3px 12px;
      border-radius: 3px;
      font-weight: 700;
      font-size: 11px;
      margin-bottom: 8px;
    }

    .sst-overall.pass {
      background: #dcfce7;
      color: #16a34a;
      border: 1px solid #86efac;
    }

    .sst-overall.fail {
      background: #fef2f2;
      color: #dc2626;
      border: 1px solid #fca5a5;
    }

    .sst-overall.na {
      background: #f1f5f9;
      color: #64748b;
      border: 1px solid #cbd5e1;
    }

    .notes-box {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 4px;
      padding: 8px 12px;
      font-size: 11px;
      white-space: pre-wrap;
      color: #333;
    }

    .report-footer {
      margin-top: 24px;
      padding-top: 8px;
      border-top: 1px solid #ddd;
      font-size: 9px;
      color: #999;
      display: flex;
      justify-content: space-between;
    }

    @media print {
      body {
        padding: 10px 15px;
        font-size: 10px;
      }

      .report-header h1 {
        font-size: 16px;
      }

      .section {
        page-break-inside: avoid;
      }

      .chromatogram-container svg {
        max-width: 100%;
      }

      table {
        font-size: 9px;
      }

      .no-print {
        display: none !important;
      }
    }
  </style>
</head>
<body>
  <div class="report-header">
    <h1>GC Analysis Report</h1>
    <div class="subtitle">Run #${result.run_number}${result.method ? ' | Method: ' + _escapeXml(result.method) : ''}</div>
  </div>

  <div class="meta-grid">
    <div class="meta-item">
      <span class="meta-label">Lab:</span>
      <span class="meta-value">${_escapeXml(options.labName || '--')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Instrument:</span>
      <span class="meta-value">${_escapeXml(options.instrumentName || '--')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Operator:</span>
      <span class="meta-value">${_escapeXml(options.operatorName || '--')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Method:</span>
      <span class="meta-value">${_escapeXml(options.methodName || result.method || '--')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Sample ID:</span>
      <span class="meta-value">${_escapeXml(options.sampleId || '--')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Run Date:</span>
      <span class="meta-value">${runTimestamp}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Port:</span>
      <span class="meta-value">${result.port != null ? result.port : '--'}${result.port_label ? ' (' + _escapeXml(result.port_label) + ')' : ''}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Duration:</span>
      <span class="meta-value">${result.run_duration_s != null ? result.run_duration_s.toFixed(1) + ' s' : '--'}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Finish:</span>
      <span class="meta-value">${_escapeXml(result.finish_reason || '--')}</span>
    </div>
  </div>

  <div class="section chromatogram-container">
    <h2>Chromatogram</h2>
    ${svgContent}
  </div>

  <div class="section">
    <h2>Component Results</h2>
    <table>
      <thead>
        <tr>
          <th>Component</th>
          <th>RT (s)</th>
          <th>Area %</th>
          <th>Concentration</th>
          <th>Unit</th>
          <th>Area</th>
        </tr>
      </thead>
      <tbody>
        ${componentRows}
      </tbody>
    </table>
  </div>

  ${unidentifiedPeaks.length > 0 ? `
  <div class="section">
    <h2>Unidentified Peaks</h2>
    <table>
      <thead>
        <tr>
          <th>Peak</th>
          <th>RT (s)</th>
          <th>Area %</th>
          <th>Area</th>
          <th>Height</th>
          <th>Width (s)</th>
        </tr>
      </thead>
      <tbody>
        ${unidentifiedRows}
      </tbody>
    </table>
  </div>` : ''}

  ${sstPeaks.length > 0 ? `
  <div class="section">
    <h2>System Suitability Test (SST)</h2>
    <div class="${sstOverallPass ? 'sst-overall pass' : 'sst-overall fail'}">
      Overall: ${sstOverallPass ? 'PASS' : 'FAIL'}
    </div>
    <table>
      <thead>
        <tr>
          <th>Component</th>
          <th>Plates (N)</th>
          <th>Plates Status</th>
          <th>Tailing (T)</th>
          <th>Tailing Status</th>
          <th>Resolution (Rs)</th>
          <th>Resolution Status</th>
        </tr>
      </thead>
      <tbody>
        ${sstRows}
      </tbody>
    </table>
  </div>` : `
  <div class="section">
    <h2>System Suitability Test (SST)</h2>
    <div class="sst-overall na">No SST data available</div>
  </div>`}

  <div class="section">
    <h2>QC Summary</h2>
    <div class="qc-grid">
      <div class="qc-item">
        <div class="qc-label">Total Area</div>
        <div class="qc-value">${totalArea.toFixed(0)}</div>
      </div>
      <div class="qc-item">
        <div class="qc-label">Area Sum %</div>
        <div class="qc-value">${totalPct.toFixed(2)}</div>
      </div>
      <div class="qc-item">
        <div class="qc-label">Components</div>
        <div class="qc-value">${numComponents}</div>
      </div>
      <div class="qc-item">
        <div class="qc-label">Unidentified</div>
        <div class="qc-value">${numUnidentified}</div>
      </div>
    </div>
  </div>

  ${notesHtml}

  <div class="report-footer">
    <span>Generated: ${reportDate} | ICCSFlux GC Report</span>
    <span>Page 1 of 1</span>
  </div>
</body>
</html>`
    } finally {
      isGenerating.value = false
    }
  }

  // --------------------------------------------------------------------------
  // Open report in new window and trigger print dialog
  // --------------------------------------------------------------------------
  function printReport(htmlContent: string): void {
    const printWindow = window.open('', '_blank', 'width=800,height=1100')
    if (!printWindow) {
      console.warn('[GcReport] Popup blocked — cannot open print window')
      return
    }
    printWindow.document.write(htmlContent)
    printWindow.document.close()
    printWindow.focus()
    // Delay to allow rendering before print dialog opens
    setTimeout(() => {
      printWindow.print()
    }, 500)
  }

  // --------------------------------------------------------------------------
  // Export analysis data as CSV
  // --------------------------------------------------------------------------
  function exportCsv(result: GCAnalysisResult, chromatogram?: GCChromatogramData): string {
    const lines: string[] = []

    // Section 1: Run metadata
    lines.push('# GC Analysis Report')
    lines.push(`# Run Number,${result.run_number}`)
    lines.push(`# Timestamp,${result.timestamp || ''}`)
    lines.push(`# Method,${result.method || ''}`)
    lines.push(`# Port,${result.port ?? ''}`)
    lines.push(`# Port Label,${result.port_label || ''}`)
    lines.push(`# Duration (s),${result.run_duration_s ?? ''}`)
    lines.push(`# Finish Reason,${result.finish_reason || ''}`)
    lines.push(`# Total Area,${result.total_area ?? ''}`)
    lines.push(`# Chromatogram Points,${result.chromatogram_points ?? ''}`)
    lines.push('')

    // Section 2: Component results
    lines.push('# Component Results')
    lines.push('Name,RT (s),Area %,Concentration,Unit,Area')

    const peaks = _buildPeakList(result)
    for (const peak of peaks) {
      const name = _csvEscape(peak.name)
      const rt = peak.rt.toFixed(4)
      const areaPct = peak.area_pct.toFixed(4)
      const conc = peak.concentration != null ? peak.concentration.toFixed(6) : ''
      const unit = _csvEscape(peak.unit || '')
      const area = peak.area.toFixed(2)
      lines.push(`${name},${rt},${areaPct},${conc},${unit},${area}`)
    }

    // Section 3: Raw chromatogram data
    if (chromatogram && chromatogram.times.length > 0) {
      lines.push('')
      lines.push('# Raw Chromatogram Data')
      lines.push(`# Node ID,${chromatogram.node_id}`)
      lines.push(`# Points,${chromatogram.points}`)
      lines.push(`# Duration (s),${chromatogram.duration_s}`)
      lines.push('Time (s),Value (mV)')
      for (let i = 0; i < chromatogram.times.length; i++) {
        lines.push(`${(chromatogram.times[i] ?? 0).toFixed(4)},${(chromatogram.values[i] ?? 0).toFixed(4)}`)
      }
    }

    return lines.join('\n')
  }

  // --------------------------------------------------------------------------
  // Download a string as a file via browser download dialog
  // --------------------------------------------------------------------------
  function downloadFile(
    content: string,
    filename: string,
    mimeType: string = 'text/plain'
  ): void {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // --------------------------------------------------------------------------
  // Internal: escape a CSV field value
  // --------------------------------------------------------------------------
  function _csvEscape(value: string): string {
    if (value.includes(',') || value.includes('"') || value.includes('\n')) {
      return '"' + value.replace(/"/g, '""') + '"'
    }
    return value
  }

  return {
    isGenerating,
    generateReport,
    printReport,
    exportCsv,
    downloadFile,
  }
}
