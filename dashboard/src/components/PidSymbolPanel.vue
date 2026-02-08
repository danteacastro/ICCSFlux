<script setup lang="ts">
/**
 * PidSymbolPanel - Searchable Symbol Sidebar for P&ID Editor
 *
 * Left-side collapsible panel with:
 * - Search box that filters symbols by name across all categories
 * - Collapsible category sections with symbol count badges
 * - Draggable symbol tiles with SVG thumbnails
 */

import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, type ScadaSymbolType } from '../assets/symbols'
import { PID_SYMBOL_CATALOG } from '../constants/pidSymbols'
import { HMI_CONTROL_CATALOG, getHmiThumbnail, isHmiControl } from '../constants/hmiControls'

const store = useDashboardStore()

const searchQuery = ref('')

// Merge HMI controls (at top) with process symbols
const allSymbols = [
  ...HMI_CONTROL_CATALOG.map(h => ({ type: h.type as ScadaSymbolType, name: h.name, category: h.category })),
  ...PID_SYMBOL_CATALOG,
]

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
  if (!searchQuery.value.trim()) return allSymbols
  const q = searchQuery.value.toLowerCase()
  return allSymbols.filter(s =>
    s.name.toLowerCase().includes(q) || s.category.toLowerCase().includes(q)
  )
})

// Categories with their filtered symbols
const categories = computed(() => {
  const cats = new Map<string, typeof allSymbols>()
  for (const sym of filteredSymbols.value) {
    if (!cats.has(sym.category)) {
      cats.set(sym.category, [])
    }
    cats.get(sym.category)!.push(sym)
  }
  return cats
})

// Get symbol SVG for thumbnail (process symbols from SCADA_SYMBOLS, HMI controls from catalog)
function getSymbolSvg(type: ScadaSymbolType | string): string {
  if (isHmiControl(type)) return getHmiThumbnail(type)
  return SCADA_SYMBOLS[type as ScadaSymbolType] || ''
}

// Drag start handler
function onDragStart(event: DragEvent, type: ScadaSymbolType | string) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('application/x-pid-symbol', type)
  event.dataTransfer.effectAllowed = 'copy'
}

// Close panel
function closePanel() {
  store.pidSymbolPanelOpen = false
}
</script>

<template>
  <div class="pid-symbol-panel">
    <div class="panel-header">
      <span class="panel-title">Symbols</span>
      <button class="btn-close-panel" @click="closePanel" title="Close Panel">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
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
            :title="sym.name"
          >
            <div class="tile-svg" v-html="getSymbolSvg(sym.type)" />
            <span class="tile-name">{{ sym.name }}</span>
          </div>
        </div>
      </div>

      <div v-if="filteredSymbols.length === 0" class="no-results">
        No symbols match "{{ searchQuery }}"
      </div>
    </div>
  </div>
</template>

<style scoped>
.pid-symbol-panel {
  position: absolute;
  top: 0;
  left: 0;
  width: 220px;
  height: 100%;
  background: #0f0f1a;
  border-right: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 50;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #2a2a4a;
  background: #1a1a2e;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn-close-panel {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.btn-close-panel:hover {
  color: #fff;
}

.panel-search {
  padding: 8px;
  border-bottom: 1px solid #1a1a2e;
  position: relative;
}

.search-input {
  width: 100%;
  padding: 6px 28px 6px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  outline: none;
  box-sizing: border-box;
}

.search-input:focus {
  border-color: #3b82f6;
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
  color: #666;
  display: flex;
  align-items: center;
}

.search-clear:hover {
  color: #fff;
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
  background: #2a2a4a;
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
  background: rgba(59, 130, 246, 0.1);
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
  background: #1a1a2e;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: grab;
  transition: all 0.15s;
  min-height: 56px;
}

.symbol-tile:hover {
  background: #252540;
  border-color: #3b82f6;
}

.symbol-tile:active {
  cursor: grabbing;
  border-color: #60a5fa;
  background: #2a2a5a;
}

.tile-svg {
  width: 36px;
  height: 36px;
  color: #60a5fa;
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
</style>
