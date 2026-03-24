<script setup lang="ts">
/**
 * DataViewerTab.vue — Multi-panel Data Viewer container.
 *
 * Top-level tab that provides:
 * - Global time range bar with presets + custom range
 * - Auto-refresh control (Off, 5s, 10s, 30s, 1m)
 * - Multiple chart panels, each with its own tag selection
 * - Synchronized crosshair across all panels
 * - Drag-to-zoom updates global time range (all panels sync)
 * - Ctrl+Z undo zoom (pop zoom stack)
 * - Panel state persisted to localStorage
 * - Stats bar at bottom (DB size, point count, etc.)
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useDataViewer } from '../composables/useDataViewer'
import DataViewerChart from './DataViewerChart.vue'
import DataViewerTagPicker from './DataViewerTagPicker.vue'

const historian = useDataViewer()

// Time range presets
const presets = [
  { label: '1h', value: '1h' },
  { label: '6h', value: '6h' },
  { label: '12h', value: '12h' },
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' }
]

// Auto-refresh options
const refreshOptions = [
  { label: 'Off', value: null as number | null },
  { label: '5s', value: 5000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
  { label: '1m', value: 60000 }
]
const showRefreshDropdown = ref(false)

// Default colors for chart series
const defaultColors = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
  '#a855f7', '#14b8a6', '#f97316', '#6366f1'
]

function getColors(channels: string[]): string[] {
  return channels.map((_, i) => defaultColors[i % defaultColors.length]!)
}

// Stats display
const formattedStats = computed(() => {
  const s = historian.stats.value
  if (!s) return null

  function fmtSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  function fmtCount(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return String(n)
  }

  return {
    points: fmtCount(s.total_points),
    channels: s.channel_count,
    retention: s.retention_days,
    dbSize: fmtSize(s.db_size_bytes),
    written: fmtCount(s.points_written),
    errors: s.write_errors
  }
})

const currentPreset = computed(() => historian.globalTimeRange.value.preset || null)

// Handle zoom from child charts
function handleChartZoom(startMs: number, endMs: number) {
  if (startMs === 0 && endMs === 0) {
    // Reset: undo zoom
    historian.undoZoom()
  } else {
    historian.zoomToRange(startMs, endMs)
  }
}

function handlePresetClick(preset: string) {
  historian.setPreset(preset)
}

function handleRefreshSelect(intervalMs: number | null) {
  historian.setAutoRefresh(intervalMs)
  showRefreshDropdown.value = false
}

function addNewPanel() {
  historian.addPanel()
}

function removePanel(id: string) {
  historian.removePanel(id)
}

function handleTagUpdate(panelId: string, channels: string[]) {
  historian.updatePanelChannels(panelId, channels)
  // Auto-query if channels changed
  historian.queryPanelData(panelId)
}

async function handleExportCSV(panelId: string) {
  await historian.exportPanelCSV(panelId)
}

async function handleExportAll() {
  await historian.exportAllPanelsCSV()
}

function toggleCollapse(id: string) {
  historian.togglePanelCollapsed(id)
}

// ── Panel resize (Grafana-style drag handle) ──────────────────
const resizingPanelId = ref<string | null>(null)
const resizeStartY = ref(0)
const resizeStartHeight = ref(0)
const DEFAULT_PANEL_HEIGHT = 280

function startResize(panelId: string, event: MouseEvent) {
  event.preventDefault()
  const panel = historian.panels.value.find(p => p.id === panelId)
  if (!panel) return

  resizingPanelId.value = panelId
  resizeStartY.value = event.clientY
  resizeStartHeight.value = panel.height ?? DEFAULT_PANEL_HEIGHT

  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
}

function onResizeMove(event: MouseEvent) {
  if (!resizingPanelId.value) return
  const delta = event.clientY - resizeStartY.value
  const newHeight = resizeStartHeight.value + delta
  historian.updatePanelHeight(resizingPanelId.value, newHeight)
}

function onResizeEnd() {
  resizingPanelId.value = null
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// Keyboard shortcuts
function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
    e.preventDefault()
    historian.undoZoom()
  }
}

// Refresh interval label
const refreshLabel = computed(() => {
  const iv = historian.autoRefreshInterval.value
  if (!iv) return 'Off'
  return refreshOptions.find(o => o.value === iv)?.label || `${iv / 1000}s`
})

// Periodic stats refresh (every 60s while tab is visible)
let statsTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  // Load tags and stats on mount
  historian.refreshTags()
  historian.refreshStats()

  // Query all existing panels
  if (historian.panels.value.length > 0) {
    historian.queryAllPanels()
  }

  // Refresh stats every 60s
  statsTimer = setInterval(() => historian.refreshStats(), 60000)

  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)

  // Clean up any in-progress resize
  if (resizingPanelId.value) {
    onResizeEnd()
  }

  // Clean up stats timer
  if (statsTimer) {
    clearInterval(statsTimer)
    statsTimer = null
  }

  // Stop auto-refresh when leaving tab (timer persists in singleton, restart on return)
  historian.setAutoRefresh(null)
})
</script>

<template>
  <div class="historian-view">
    <!-- Global Time Range Bar -->
    <div class="time-bar">
      <div class="time-presets">
        <button
          v-for="p in presets"
          :key="p.value"
          class="preset-btn"
          :class="{ active: currentPreset === p.value }"
          @click="handlePresetClick(p.value)"
        >
          {{ p.label }}
        </button>
      </div>

      <div class="time-label">
        {{ historian.timeRangeLabel.value }}
      </div>

      <div class="time-actions">
        <!-- Auto-refresh -->
        <div class="refresh-dropdown-container">
          <button class="action-btn" @click="showRefreshDropdown = !showRefreshDropdown" title="Auto-refresh interval">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
              <path d="M3 3v5h5"/>
            </svg>
            {{ refreshLabel }}
          </button>
          <div v-if="showRefreshDropdown" class="refresh-dropdown">
            <button
              v-for="opt in refreshOptions"
              :key="String(opt.value)"
              class="refresh-option"
              :class="{ active: historian.autoRefreshInterval.value === opt.value }"
              @click="handleRefreshSelect(opt.value)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>

        <!-- Undo zoom -->
        <button
          class="action-btn"
          :disabled="historian.zoomStack.value.length === 0"
          @click="historian.undoZoom()"
          title="Undo Zoom (Ctrl+Z)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 14L4 9l5-5"/>
            <path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
          </svg>
        </button>

        <!-- Refresh all -->
        <button
          class="action-btn"
          :class="{ loading: historian.isLoading.value }"
          @click="historian.queryAllPanels()"
          title="Refresh all panels"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: historian.isLoading.value }">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
        </button>

        <!-- Export All CSV -->
        <button
          class="action-btn"
          :class="{ loading: historian.isExporting.value }"
          :disabled="historian.panels.value.length === 0 || historian.isExporting.value"
          @click="handleExportAll"
          title="Export all tags as CSV (full resolution)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: historian.isExporting.value }">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          CSV
        </button>

        <!-- Add panel -->
        <button class="action-btn add-btn" @click="addNewPanel" title="Add Chart Panel">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Panels -->
    <div class="panels-container">
      <div
        v-for="panel in historian.panels.value"
        :key="panel.id"
        class="panel"
        :class="{ collapsed: panel.collapsed }"
      >
        <!-- Panel header -->
        <div class="panel-header">
          <button class="collapse-btn" @click="toggleCollapse(panel.id)" :title="panel.collapsed ? 'Expand' : 'Collapse'">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ rotated: !panel.collapsed }">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </button>

          <span class="panel-channels">
            {{ panel.channels.length > 0 ? panel.channels.join(', ') : 'No channels selected' }}
          </span>

          <div class="panel-actions">
            <DataViewerTagPicker
              :tags="historian.availableTags.value"
              :selected="panel.channels"
              :colors="getColors(panel.channels)"
              @update="(ch) => handleTagUpdate(panel.id, ch)"
            />

            <button
              class="panel-btn"
              :disabled="historian.isExporting.value"
              @click="handleExportCSV(panel.id)"
              title="Export full-resolution CSV"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: historian.isExporting.value }">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>

            <button class="panel-btn remove-btn" @click="removePanel(panel.id)" title="Remove Panel">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Panel chart -->
        <div v-if="!panel.collapsed" class="panel-chart" :style="{ height: (panel.height ?? DEFAULT_PANEL_HEIGHT) + 'px' }">
          <DataViewerChart
            :panel-id="panel.id"
            :data="historian.panelData.value[panel.id] ?? null"
            :channels="panel.channels"
            :is-loading="historian.isLoading.value"
            sync-group="historian"
            @zoom="handleChartZoom"
          />
        </div>

        <!-- Resize handle -->
        <div
          v-if="!panel.collapsed"
          class="resize-handle"
          @mousedown="startResize(panel.id, $event)"
          title="Drag to resize"
        ></div>
      </div>

      <!-- Empty state / Add panel prompt -->
      <div v-if="historian.panels.value.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
          </svg>
        </div>
        <h3>Data Viewer</h3>
        <p>Browse historical data recorded by the SQLite historian.</p>
        <button class="add-chart-btn" @click="addNewPanel">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add Chart
        </button>
      </div>

      <!-- Add another chart button (when panels exist) -->
      <div v-if="historian.panels.value.length > 0" class="add-panel-row">
        <button class="add-chart-btn small" @click="addNewPanel">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add Chart
        </button>
      </div>
    </div>

    <!-- Stats Bar -->
    <div v-if="formattedStats" class="stats-bar">
      <span class="stat-item">{{ formattedStats.points }} pts</span>
      <span class="stat-sep">|</span>
      <span class="stat-item">{{ formattedStats.channels }} tags</span>
      <span class="stat-sep">|</span>
      <span class="stat-item">{{ formattedStats.retention }}d retention</span>
      <span class="stat-sep">|</span>
      <span class="stat-item">DB: {{ formattedStats.dbSize }}</span>
      <span v-if="formattedStats.errors > 0" class="stat-sep">|</span>
      <span v-if="formattedStats.errors > 0" class="stat-item stat-error">{{ formattedStats.errors }} errors</span>
    </div>
  </div>
</template>

<style scoped>
.historian-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

/* ── Time Bar ────────────────────────────────── */

.time-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--bg-widget);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.time-presets {
  display: flex;
  gap: 2px;
}

.preset-btn {
  padding: 4px 10px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
  transition: all 0.15s;
}

.preset-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.preset-btn.active {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.time-label {
  flex: 1;
  text-align: center;
  font-size: 0.7rem;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.time-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.65rem;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.action-btn.add-btn {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.action-btn.add-btn:hover {
  opacity: 0.9;
}

.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* Refresh dropdown */
.refresh-dropdown-container {
  position: relative;
}

.refresh-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  z-index: 200;
  box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.3));
  overflow: hidden;
}

.refresh-option {
  display: block;
  width: 100%;
  padding: 6px 16px;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 0.7rem;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s;
}

.refresh-option:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.refresh-option.active {
  color: var(--color-accent);
  font-weight: 600;
}

/* ── Panels ──────────────────────────────────── */

.panels-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.panel.collapsed .panel-chart {
  display: none;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.collapse-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  transition: transform 0.2s;
}

.collapse-btn svg.rotated {
  transform: rotate(90deg);
}

.panel-channels {
  flex: 1;
  font-size: 0.7rem;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.panel-btn {
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 3px 6px;
  display: flex;
  align-items: center;
  transition: all 0.15s;
}

.panel-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.panel-btn.remove-btn:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.panel-chart {
  /* height set via inline style from panel.height */
  min-height: 120px;
}

.resize-handle {
  height: 6px;
  cursor: row-resize;
  background: transparent;
  position: relative;
  transition: background 0.15s;
}

.resize-handle::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 32px;
  height: 3px;
  border-radius: 2px;
  background: var(--border-color);
  opacity: 0;
  transition: opacity 0.15s;
}

.resize-handle:hover {
  background: var(--bg-hover);
}

.resize-handle:hover::after {
  opacity: 1;
}

/* ── Empty State ─────────────────────────────── */

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-muted);
}

.empty-icon {
  opacity: 0.3;
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 8px;
}

.empty-state p {
  font-size: 0.8rem;
  margin: 0 0 20px;
}

.add-chart-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  background: var(--color-accent);
  border: none;
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}

.add-chart-btn:hover {
  opacity: 0.9;
}

.add-chart-btn.small {
  padding: 6px 14px;
  font-size: 0.7rem;
  border-radius: 4px;
}

.add-panel-row {
  display: flex;
  justify-content: center;
  padding: 8px 0;
}

/* ── Stats Bar ───────────────────────────────── */

.stats-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 16px;
  background: var(--bg-widget);
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted);
}

.stat-item {
  white-space: nowrap;
}

.stat-sep {
  opacity: 0.3;
}

.stat-error {
  color: var(--color-error);
}
</style>
