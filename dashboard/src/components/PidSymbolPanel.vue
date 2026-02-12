<script setup lang="ts">
/**
 * PidSymbolPanel - Searchable Symbol Sidebar for P&ID Editor
 *
 * Left-side collapsible panel with:
 * - Search box that filters symbols by name across all categories
 * - Collapsible category sections with symbol count badges
 * - Draggable symbol tiles with SVG thumbnails
 * - Collapse to thin icon strip for maximum canvas space
 * - Resizable via drag handle
 */

import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, getSymbolCatalog, type ScadaSymbolType } from '../assets/symbols'
import { HMI_CONTROL_CATALOG, getHmiThumbnail, isHmiControl } from '../constants/hmiControls'
import { useResizablePanel } from '../composables/useResizablePanel'
import PidCustomSymbolImport from './PidCustomSymbolImport.vue'

const showImportDialog = ref(false)

const store = useDashboardStore()

const searchQuery = ref('')

// Merge HMI controls + process symbols + custom symbols
const builtInSymbols = [
  ...HMI_CONTROL_CATALOG.map(h => ({ type: h.type as ScadaSymbolType, name: h.name, category: h.category })),
  ...getSymbolCatalog(),
]
const allSymbols = computed(() => [
  ...builtInSymbols,
  ...Object.entries(store.pidCustomSymbols).map(([id, def]) => ({
    type: id as ScadaSymbolType, name: def.name, category: def.category
  }))
])

// Collapsed category state
const collapsedCategories = ref<Set<string>>(new Set())

function toggleCategory(category: string) {
  if (collapsedCategories.value.has(category)) {
    collapsedCategories.value.delete(category)
  } else {
    collapsedCategories.value.add(category)
  }
  // Force reactivity
  collapsedCategories.value = new Set(collapsedCategories.value)
}

// Filtered symbols based on search
const filteredSymbols = computed(() => {
  if (!searchQuery.value.trim()) return allSymbols.value
  const q = searchQuery.value.toLowerCase()
  return allSymbols.value.filter(s =>
    s.name.toLowerCase().includes(q) || s.category.toLowerCase().includes(q)
  )
})

// Categories with their filtered symbols, plus Favorites & Recent at top
type PidSymbolEntry = { type: ScadaSymbolType; name: string; category: string }
const categories = computed(() => {
  const cats = new Map<string, PidSymbolEntry[]>()

  // Add Favorites category at top (if any)
  if (!searchQuery.value.trim() && store.pidFavoriteSymbols.length > 0) {
    const favs = allSymbols.value.filter(s => store.pidFavoriteSymbols.includes(s.type))
    if (favs.length > 0) cats.set('Favorites', favs)
  }

  // Add Recent category (if any)
  if (!searchQuery.value.trim() && store.pidRecentSymbols.length > 0) {
    const recent = store.pidRecentSymbols
      .map(type => allSymbols.value.find(s => s.type === type))
      .filter((s): s is PidSymbolEntry => !!s)
    if (recent.length > 0) cats.set('Recent', recent)
  }

  for (const sym of filteredSymbols.value) {
    if (!cats.has(sym.category)) {
      cats.set(sym.category, [])
    }
    cats.get(sym.category)!.push(sym)
  }
  return cats
})

// Get symbol SVG for thumbnail (process symbols from SCADA_SYMBOLS, HMI controls from catalog, custom symbols)
function getSymbolSvg(type: ScadaSymbolType | string): string {
  if (isHmiControl(type)) return getHmiThumbnail(type)
  if (store.pidCustomSymbols[type]) return store.pidCustomSymbols[type].svg
  return SCADA_SYMBOLS[type as ScadaSymbolType] || ''
}

// Drag start handler
function onDragStart(event: DragEvent, type: ScadaSymbolType | string) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('application/x-pid-symbol', type)
  event.dataTransfer.effectAllowed = 'copy'
}

// Double-click to place symbol at viewport center
function onSymbolDblClick(type: ScadaSymbolType | string) {
  const zoom = store.pidZoom || 1
  // Estimate visible canvas center (~600x400 is typical canvas size)
  const cx = (-store.pidPanX + 600) / zoom
  const cy = (-store.pidPanY + 300) / zoom
  const w = 60, h = 60
  store.addPidSymbolWithUndo({
    type,
    x: Math.round(cx - w / 2),
    y: Math.round(cy - h / 2),
    width: w,
    height: h,
    rotation: 0,
  } as any)
  store.pidTrackRecentSymbol(type)
}

// Close panel (fully hide)
function closePanel() {
  store.pidSymbolPanelOpen = false
}

// Toggle collapse state
function toggleCollapse() {
  store.pidSymbolPanelCollapsed = !store.pidSymbolPanelCollapsed
}

// Resizable panel
const { isResizing, onMouseDown: onResizeStart } = useResizablePanel({
  side: 'left',
  minWidth: 160,
  maxWidth: 400,
  getWidth: () => store.pidSymbolPanelWidth,
  setWidth: (w) => { store.pidSymbolPanelWidth = w },
})
</script>

<template>
  <!-- Collapse/expand tab — vertically centered on panel edge -->
  <div
    class="panel-tab panel-tab-left"
    :style="{ left: store.pidSymbolPanelCollapsed ? '0px' : (store.pidSymbolPanelWidth - 1) + 'px' }"
    @click="toggleCollapse"
    :title="store.pidSymbolPanelCollapsed ? 'Expand Symbols ([)' : 'Collapse Symbols ([)'"
  >
    <svg width="10" height="18" viewBox="0 0 10 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline v-if="store.pidSymbolPanelCollapsed" points="3 2 8 9 3 16" />
      <polyline v-else points="7 2 2 9 7 16" />
    </svg>
  </div>

  <!-- Full panel -->
  <div
    v-if="!store.pidSymbolPanelCollapsed"
    class="pid-symbol-panel"
    :style="{ width: store.pidSymbolPanelWidth + 'px' }"
  >
    <div class="panel-header">
      <span class="panel-title">Symbols</span>
      <div class="header-actions">
        <button class="btn-import" @click="showImportDialog = true" title="Import Custom SVG Symbol">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
        <button class="btn-close-panel" @click="closePanel" title="Close Panel">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>

    <div class="panel-search">
      <input
        v-model="searchQuery"
        type="text"
        placeholder="Search symbols..."
        class="search-input"
      />
      <span v-if="searchQuery" class="search-clear" @click="searchQuery = ''">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </span>
    </div>

    <div class="panel-body">
      <div v-for="[category, symbols] in categories" :key="category" class="category-section">
        <div class="category-header" @click="toggleCategory(category)">
          <svg
            width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            :class="{ collapsed: collapsedCategories.has(category) }"
            class="chevron"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
          <span class="category-name">{{ category }}</span>
          <span class="category-count">{{ symbols.length }}</span>
        </div>
        <div v-if="!collapsedCategories.has(category)" class="symbol-grid">
          <div
            v-for="sym in symbols"
            :key="sym.type"
            class="symbol-tile"
            draggable="true"
            @dragstart="onDragStart($event, sym.type)"
            @dblclick="onSymbolDblClick(sym.type)"
            :title="`${sym.name} (double-click to place)`"
          >
            <span
              class="tile-fav"
              :class="{ active: store.pidFavoriteSymbols.includes(sym.type) }"
              @click.stop.prevent="store.pidToggleFavorite(sym.type)"
              title="Toggle Favorite"
            >&#9733;</span>
            <div class="tile-svg" v-html="getSymbolSvg(sym.type)" />
            <span class="tile-name">{{ sym.name }}</span>
          </div>
        </div>
      </div>

      <div v-if="filteredSymbols.length === 0" class="no-results">
        No symbols match "{{ searchQuery }}"
      </div>
    </div>

    <!-- Resize handle -->
    <div
      class="resize-handle resize-handle-right"
      :class="{ active: isResizing }"
      @mousedown="onResizeStart"
    />
  </div>

  <!-- Custom symbol import dialog -->
  <PidCustomSymbolImport v-if="showImportDialog" @close="showImportDialog = false" />
</template>

<style scoped>
/* Collapse/expand tab handle */
.panel-tab {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 64px;
  background: var(--bg-widget);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 56;
  color: #888;
  transition: background 0.15s, color 0.15s;
  box-shadow: 2px 0 6px rgba(0, 0, 0, 0.3);
}

.panel-tab:hover {
  background: #252540;
  color: var(--color-accent-light);
}

.panel-tab-left {
  border: 1px solid var(--border-color);
  border-left: none;
  border-radius: 0 6px 6px 0;
}

/* Full panel */
.pid-symbol-panel {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  z-index: 55;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-widget);
  flex-shrink: 0;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-import {
  background: transparent;
  border: 1px solid var(--border-heavy);
  color: var(--color-accent-light);
  cursor: pointer;
  padding: 2px;
  border-radius: 3px;
  display: flex;
  align-items: center;
}

.btn-import:hover {
  background: #252540;
  border-color: var(--color-accent);
}

.btn-close-panel {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.btn-close-panel:hover {
  color: var(--text-primary);
}

.panel-search {
  padding: 8px;
  border-bottom: 1px solid var(--bg-widget);
  position: relative;
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  padding: 6px 28px 6px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  box-sizing: border-box;
}

.search-input:focus {
  border-color: var(--color-accent);
}

.search-input::placeholder {
  color: #555;
}

.search-clear {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
}

.search-clear:hover {
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.panel-body::-webkit-scrollbar {
  width: 6px;
}

.panel-body::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.panel-body::-webkit-scrollbar-track {
  background: transparent;
}

.category-section {
  margin-bottom: 2px;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  color: #ccc;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.category-header:hover {
  background: var(--color-accent-bg);
}

.chevron {
  transition: transform 0.15s;
}

.chevron.collapsed {
  transform: rotate(-90deg);
}

.category-count {
  margin-left: auto;
  font-size: 10px;
  color: #555;
  font-weight: 400;
}

.symbol-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 4px 8px 8px;
}

.symbol-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 2px 4px;
  background: var(--bg-widget);
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: grab;
  transition: all 0.15s;
  min-height: 56px;
  position: relative;
}

.symbol-tile:hover {
  background: #252540;
  border-color: var(--color-accent);
}

.symbol-tile:active {
  cursor: grabbing;
  border-color: var(--color-accent-light);
  background: #2a2a5a;
}

.tile-fav {
  position: absolute;
  top: 2px;
  right: 2px;
  font-size: 10px;
  color: var(--text-disabled);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s;
  z-index: 1;
}

.symbol-tile:hover .tile-fav {
  opacity: 1;
}

.tile-fav.active {
  opacity: 1;
  color: #eab308;
}

.tile-fav:hover {
  color: #facc15;
}

.tile-svg {
  width: 36px;
  height: 36px;
  color: var(--color-accent-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.tile-svg :deep(svg) {
  width: 100%;
  height: 100%;
}

.tile-name {
  font-size: 9px;
  color: #888;
  text-align: center;
  margin-top: 2px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  max-width: 100%;
}

.no-results {
  padding: 20px;
  text-align: center;
  color: #555;
  font-size: 12px;
  font-style: italic;
}

/* Resize handle */
.resize-handle {
  position: absolute;
  top: 0;
  width: 4px;
  height: 100%;
  cursor: col-resize;
  z-index: 51;
}

.resize-handle:hover,
.resize-handle.active {
  background: var(--color-accent-glow);
}

.resize-handle-right {
  right: 0;
}
</style>
