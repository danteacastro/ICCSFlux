/**
 * useDataViewer - Composable for the SQLite historian Data Viewer
 *
 * Provides reactive state and MQTT RPC methods for:
 * - Querying historical data from the backend SQLite historian
 * - Managing multi-panel chart layouts
 * - Global time range with zoom stack (Ctrl+Z undo)
 * - Auto-refresh timer
 * - CSV export
 * - Tag listing and selection
 *
 * Singleton pattern: module-level refs shared across all callers.
 */

import { ref, computed, watch } from 'vue'
import { useMqtt } from './useMqtt'
import type {
  HistorianTag,
  HistorianPanel,
  HistorianTimeRange,
  HistorianQueryResult,
  HistorianStats
} from '../types'

// ── Singleton state ──────────────────────────────────────────

const availableTags = ref<HistorianTag[]>([])
const panels = ref<HistorianPanel[]>([])
const panelData = ref<Record<string, HistorianQueryResult>>({})
const globalTimeRange = ref<HistorianTimeRange>({ preset: '1h' })
const zoomStack = ref<HistorianTimeRange[]>([])
const isLoading = ref(false)
const isExporting = ref(false)
const stats = ref<HistorianStats | null>(null)
const autoRefreshInterval = ref<number | null>(null)

const MAX_EXPORT_POINTS = 100000

let autoRefreshTimer: ReturnType<typeof setInterval> | null = null
let responseHandlersInitialized = false

// Pending MQTT RPC resolvers
const pendingResolvers: {
  query: Map<string, (result: HistorianQueryResult) => void>
  tags?: (tags: HistorianTag[]) => void
  stats?: (s: HistorianStats) => void
} = {
  query: new Map()
}

// ── Persistence ──────────────────────────────────────────────

const STORAGE_KEY = 'historian-panels'
const TIME_RANGE_KEY = 'historian-time-range'

function loadPanelsFromStorage() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed) && parsed.length > 0) {
        panels.value = parsed
      }
    }
    const storedRange = localStorage.getItem(TIME_RANGE_KEY)
    if (storedRange) {
      globalTimeRange.value = JSON.parse(storedRange)
    }
  } catch {
    // Ignore corrupt localStorage
  }
}

function savePanelsToStorage() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(panels.value))
    localStorage.setItem(TIME_RANGE_KEY, JSON.stringify(globalTimeRange.value))
  } catch {
    // Storage full — ignore
  }
}

// ── Time range helpers ───────────────────────────────────────

const PRESET_SECONDS: Record<string, number> = {
  '1h': 3600,
  '6h': 21600,
  '12h': 43200,
  '24h': 86400,
  '7d': 604800,
  '30d': 2592000
}

function resolveTimeRange(range: HistorianTimeRange): { start_ms: number; end_ms: number } {
  if (range.start !== undefined && range.end !== undefined) {
    return { start_ms: range.start, end_ms: range.end }
  }
  const seconds = PRESET_SECONDS[range.preset || '1h'] || 3600
  const now = Date.now()
  return { start_ms: now - seconds * 1000, end_ms: now }
}

// ── Composable ───────────────────────────────────────────────

export function useDataViewer() {
  const mqtt = useMqtt('nisystem')

  // Initialize response handlers once
  if (!responseHandlersInitialized && mqtt.connected.value) {
    initResponseHandlers()
  }

  // Watch for connection to init handlers
  watch(mqtt.connected, (connected) => {
    if (connected && !responseHandlersInitialized) {
      initResponseHandlers()
    }
  })

  function initResponseHandlers() {
    if (responseHandlersInitialized) return

    // Load persisted panels
    loadPanelsFromStorage()

    // Subscribe to historian responses
    mqtt.subscribe('nisystem/nodes/+/historian/query/response', (payload: any) => {
      if (!payload || typeof payload !== 'object') return
      const panelId = payload._panel_id as string | undefined
      const result: HistorianQueryResult = {
        success: payload.success ?? false,
        error: payload.error,
        timestamps: payload.timestamps ?? [],
        series: payload.series ?? {},
        channels: payload.channels ?? [],
        total_points: payload.total_points ?? 0,
        decimated: payload.decimated ?? false
      }

      if (panelId && pendingResolvers.query.has(panelId)) {
        pendingResolvers.query.get(panelId)!(result)
        pendingResolvers.query.delete(panelId)
      }

      // Also store in panelData for reactivity (skip export queries)
      if (panelId && !panelId.startsWith('__export_')) {
        panelData.value[panelId] = result
      }
    })

    mqtt.subscribe('nisystem/nodes/+/historian/tags/response', (payload: any) => {
      if (Array.isArray(payload)) {
        availableTags.value = payload as HistorianTag[]
      } else if (payload && Array.isArray(payload.tags)) {
        availableTags.value = payload.tags as HistorianTag[]
      }
      if (pendingResolvers.tags) {
        pendingResolvers.tags(availableTags.value)
        pendingResolvers.tags = undefined
      }
    })

    mqtt.subscribe('nisystem/nodes/+/historian/stats/response', (payload: any) => {
      if (payload && typeof payload === 'object') {
        stats.value = payload as HistorianStats
        if (pendingResolvers.stats) {
          pendingResolvers.stats(payload as HistorianStats)
          pendingResolvers.stats = undefined
        }
      }
    })

    responseHandlersInitialized = true
  }

  // ── Panel management ─────────────────────────────────────

  function addPanel(channels: string[] = []): string {
    const id = `panel_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    panels.value.push({
      id,
      channels,
      yAxisAuto: true,
      collapsed: false,
      showTable: false
    })
    savePanelsToStorage()
    return id
  }

  function removePanel(id: string) {
    panels.value = panels.value.filter(p => p.id !== id)
    delete panelData.value[id]
    savePanelsToStorage()
  }

  function updatePanelChannels(id: string, channels: string[]) {
    const panel = panels.value.find(p => p.id === id)
    if (panel) {
      panel.channels = channels
      savePanelsToStorage()
    }
  }

  function togglePanelCollapsed(id: string) {
    const panel = panels.value.find(p => p.id === id)
    if (panel) {
      panel.collapsed = !panel.collapsed
      savePanelsToStorage()
    }
  }

  function updatePanelHeight(id: string, height: number) {
    const panel = panels.value.find(p => p.id === id)
    if (panel) {
      panel.height = Math.max(120, Math.min(800, height))
      savePanelsToStorage()
    }
  }

  // ── Query methods ────────────────────────────────────────

  async function queryPanelData(panelId: string): Promise<HistorianQueryResult | null> {
    const panel = panels.value.find(p => p.id === panelId)
    if (!panel || panel.channels.length === 0) return null
    if (!mqtt.connected.value) return null

    initResponseHandlers()
    const { start_ms, end_ms } = resolveTimeRange(globalTimeRange.value)

    return new Promise((resolve) => {
      pendingResolvers.query.set(panelId, resolve)

      mqtt.sendNodeCommand('historian/query', {
        channels: panel.channels,
        start_ms,
        end_ms,
        max_points: 2000,
        _panel_id: panelId
      })

      // Timeout
      setTimeout(() => {
        if (pendingResolvers.query.has(panelId)) {
          pendingResolvers.query.delete(panelId)
          const empty: HistorianQueryResult = {
            success: false, error: 'Query timed out',
            timestamps: [], series: {}, channels: [],
            total_points: 0, decimated: false
          }
          panelData.value[panelId] = empty
          resolve(empty)
        }
      }, 15000)
    })
  }

  async function queryAllPanels() {
    isLoading.value = true
    const promises = panels.value
      .filter(p => !p.collapsed && p.channels.length > 0)
      .map(p => queryPanelData(p.id))
    await Promise.allSettled(promises)
    isLoading.value = false
  }

  async function refreshTags(): Promise<HistorianTag[]> {
    if (!mqtt.connected.value) return []
    initResponseHandlers()

    return new Promise((resolve) => {
      pendingResolvers.tags = resolve

      mqtt.sendNodeCommand('historian/tags', {})

      setTimeout(() => {
        if (pendingResolvers.tags) {
          pendingResolvers.tags = undefined
          resolve([])
        }
      }, 10000)
    })
  }

  async function refreshStats(): Promise<HistorianStats | null> {
    if (!mqtt.connected.value) return null
    initResponseHandlers()

    return new Promise((resolve) => {
      pendingResolvers.stats = resolve

      mqtt.sendNodeCommand('historian/stats', {})

      setTimeout(() => {
        if (pendingResolvers.stats) {
          pendingResolvers.stats = undefined
          resolve(null)
        }
      }, 10000)
    })
  }

  // ── Export (Grafana-style: full-resolution, all tags joined by time) ──

  /**
   * Build CSV string from a HistorianQueryResult.
   * All channels are joined by timestamp (Grafana "Series joined by time" format).
   * ISO 8601 timestamps, one column per channel.
   */
  function buildCSVFromResult(result: HistorianQueryResult): string {
    if (!result.success || !result.timestamps.length) return ''

    const channels = result.channels
    const rows: string[] = []

    // Header
    rows.push(['Timestamp', ...channels].join(','))

    // Data rows
    for (let i = 0; i < result.timestamps.length; i++) {
      const ts = result.timestamps[i]!
      const d = new Date(ts * 1000)
      const isoStr = d.toISOString().replace('T', ' ').replace('Z', '')
      const vals = channels.map(ch => {
        const v = result.series[ch]?.[i]
        return v !== null && v !== undefined ? String(v) : ''
      })
      rows.push([isoStr, ...vals].join(','))
    }

    return rows.join('\n')
  }

  /**
   * Query full-resolution data for export (not stored in panelData).
   * Uses the regular query endpoint with max_points=MAX_EXPORT_POINTS.
   */
  async function queryForExport(channels: string[]): Promise<HistorianQueryResult | null> {
    if (!channels.length || !mqtt.connected.value) return null
    initResponseHandlers()
    const { start_ms, end_ms } = resolveTimeRange(globalTimeRange.value)
    const exportId = `__export_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`

    return new Promise((resolve) => {
      pendingResolvers.query.set(exportId, resolve)

      mqtt.sendNodeCommand('historian/query', {
        channels,
        start_ms,
        end_ms,
        max_points: MAX_EXPORT_POINTS,
        _panel_id: exportId
      })

      // 30s timeout for large exports
      setTimeout(() => {
        if (pendingResolvers.query.has(exportId)) {
          pendingResolvers.query.delete(exportId)
          resolve(null)
        }
      }, 30000)
    })
  }

  /**
   * Export a single panel at full resolution.
   * Queries the historian with max_points=100k (vs 2k for display),
   * builds CSV client-side, triggers download.
   */
  async function exportPanelCSV(panelId: string): Promise<void> {
    const panel = panels.value.find(p => p.id === panelId)
    if (!panel || panel.channels.length === 0) return

    isExporting.value = true
    try {
      const result = await queryForExport(panel.channels)
      if (!result) return
      const csv = buildCSVFromResult(result)
      if (csv) {
        const ts = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
        const pts = result.timestamps.length
        const suffix = result.decimated ? `_${pts}of${result.total_points}pts` : `_${pts}pts`
        downloadCSV(csv, `historian_panel${suffix}_${ts}.csv`)
      }
    } finally {
      isExporting.value = false
    }
  }

  /**
   * Export ALL panels as one CSV — all unique channels joined by time.
   * Like Grafana: collects every channel across all panels, queries at full
   * resolution, produces a single CSV download.
   */
  async function exportAllPanelsCSV(): Promise<void> {
    const allChannels = new Set<string>()
    for (const panel of panels.value) {
      for (const ch of panel.channels) allChannels.add(ch)
    }
    if (allChannels.size === 0) return

    isExporting.value = true
    try {
      const result = await queryForExport(Array.from(allChannels))
      if (!result) return
      const csv = buildCSVFromResult(result)
      if (csv) {
        const ts = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
        const pts = result.timestamps.length
        const suffix = result.decimated ? `_${pts}of${result.total_points}pts` : `_${pts}pts`
        downloadCSV(csv, `historian_all_${allChannels.size}ch${suffix}_${ts}.csv`)
      }
    } finally {
      isExporting.value = false
    }
  }

  function downloadCSV(csv: string, filename: string) {
    if (!csv) return
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── Time range management ────────────────────────────────

  function setTimeRange(range: HistorianTimeRange) {
    // Push current range onto zoom stack for undo
    zoomStack.value.push({ ...globalTimeRange.value })
    if (zoomStack.value.length > 20) zoomStack.value.shift()

    globalTimeRange.value = range
    savePanelsToStorage()
    queryAllPanels()
  }

  function setPreset(preset: string) {
    setTimeRange({ preset })
  }

  function zoomToRange(startMs: number, endMs: number) {
    setTimeRange({ start: startMs, end: endMs })
  }

  function undoZoom() {
    if (zoomStack.value.length === 0) return
    globalTimeRange.value = zoomStack.value.pop()!
    savePanelsToStorage()
    queryAllPanels()
  }

  // ── Auto-refresh ─────────────────────────────────────────

  function setAutoRefresh(intervalMs: number | null) {
    // Clear existing
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer)
      autoRefreshTimer = null
    }
    autoRefreshInterval.value = intervalMs

    if (intervalMs && intervalMs > 0) {
      autoRefreshTimer = setInterval(() => {
        queryAllPanels()
      }, intervalMs)
    }
  }

  // ── Computed ──────────────────────────────────────────────

  const timeRangeLabel = computed(() => {
    const range = globalTimeRange.value
    if (range.preset) return range.preset
    if (range.start && range.end) {
      const d1 = new Date(range.start)
      const d2 = new Date(range.end)
      return `${d1.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${d2.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    }
    return '1h'
  })

  const tagGroups = computed(() => {
    const groups: Record<string, HistorianTag[]> = {
      'Hardware': [],
      'Scripts': [],
      'System': [],
      'User Vars': [],
      'Formulas': [],
      'Other': []
    }
    for (const tag of availableTags.value) {
      if (tag.name.startsWith('py.')) groups['Scripts']!.push(tag)
      else if (tag.name.startsWith('sys.')) groups['System']!.push(tag)
      else if (tag.name.startsWith('uv.')) groups['User Vars']!.push(tag)
      else if (tag.name.startsWith('fx.')) groups['Formulas']!.push(tag)
      else groups['Hardware']!.push(tag)
    }
    // Remove empty groups
    for (const key of Object.keys(groups)) {
      if (groups[key]!.length === 0) delete groups[key]
    }
    return groups
  })

  return {
    // State
    availableTags,
    panels,
    panelData,
    globalTimeRange,
    zoomStack,
    isLoading,
    isExporting,
    stats,
    autoRefreshInterval,

    // Computed
    timeRangeLabel,
    tagGroups,

    // Panel management
    addPanel,
    removePanel,
    updatePanelChannels,
    togglePanelCollapsed,
    updatePanelHeight,

    // Queries
    queryPanelData,
    queryAllPanels,
    refreshTags,
    refreshStats,

    // Export (Grafana-style: full-resolution, multi-tag)
    exportPanelCSV,
    exportAllPanelsCSV,
    downloadCSV,

    // Time range
    setTimeRange,
    setPreset,
    zoomToRange,
    undoZoom,
    resolveTimeRange,

    // Auto-refresh
    setAutoRefresh
  }
}
