<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const store = useDashboardStore()

// UI state
const showDropdown = ref(false)
const editingPageId = ref<string | null>(null)
const editingName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

// Drag-to-page state
const isDraggingWidget = ref(false)
const draggingWidgetId = ref<string | null>(null)
const hoveredPageId = ref<string | null>(null)
const hoverTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const HOVER_DELAY = 600 // ms to wait before switching page

// Computed
const pages = computed(() => store.sortedPages)
const currentPage = computed(() => store.currentPage)
const hasMultiplePages = computed(() => pages.value.length > 1)
const otherPages = computed(() => pages.value.filter(p => p.id !== store.currentPageId))

// Actions
function selectPage(pageId: string) {
  store.switchPage(pageId)
  showDropdown.value = false
}

function addNewPage() {
  const id = store.addPage()
  store.switchPage(id)
  store.saveLayoutToStorage()
  showDropdown.value = false
}

function startRename(pageId: string, currentName: string) {
  editingPageId.value = pageId
  editingName.value = currentName
  nextTick(() => {
    inputRef.value?.focus()
    inputRef.value?.select()
  })
}

function finishRename() {
  if (editingPageId.value && editingName.value.trim()) {
    store.renamePage(editingPageId.value, editingName.value)
    store.saveLayoutToStorage()
  }
  editingPageId.value = null
  editingName.value = ''
}

function cancelRename() {
  editingPageId.value = null
  editingName.value = ''
}

function deletePage(pageId: string, event: Event) {
  event.stopPropagation()
  if (pages.value.length <= 1) return
  if (confirm('Delete this page and all its widgets?')) {
    store.removePage(pageId)
    store.saveLayoutToStorage()
  }
}

function duplicatePage(pageId: string, event: Event) {
  event.stopPropagation()
  const newId = store.duplicatePage(pageId)
  if (newId) {
    store.switchPage(newId)
    store.saveLayoutToStorage()
  }
  showDropdown.value = false
}

function openInNewWindow(pageId: string, event: Event) {
  event.stopPropagation()
  const url = new URL(window.location.href)
  url.searchParams.set('page', pageId)
  window.open(url.toString(), '_blank', 'width=1200,height=800')
  showDropdown.value = false
}

// Handle keyboard
function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    finishRename()
  } else if (event.key === 'Escape') {
    cancelRename()
  }
}

// ============================================================================
// DRAG-TO-PAGE FUNCTIONALITY
// ============================================================================

// Listen for custom drag events from DashboardGrid
function handleWidgetDragStart(event: Event) {
  const customEvent = event as CustomEvent<{ widgetId: string }>
  isDraggingWidget.value = true
  draggingWidgetId.value = customEvent.detail?.widgetId || null
}

function handleWidgetDragEnd() {
  isDraggingWidget.value = false
  draggingWidgetId.value = null
  clearHoverTimeout()
  hoveredPageId.value = null
}

function clearHoverTimeout() {
  if (hoverTimeout.value) {
    clearTimeout(hoverTimeout.value)
    hoverTimeout.value = null
  }
}

// When hovering over a page tab during widget drag
function onPageTabDragEnter(pageId: string) {
  if (!isDraggingWidget.value || pageId === store.currentPageId) return

  hoveredPageId.value = pageId
  clearHoverTimeout()

  // Start timer to move widget and switch page
  hoverTimeout.value = setTimeout(() => {
    if (hoveredPageId.value === pageId && draggingWidgetId.value) {
      // Move the widget to the target page
      store.moveWidgetToPage(draggingWidgetId.value, pageId)
      // Switch to the target page
      store.switchPage(pageId)
      store.saveLayoutToStorage()
    }
  }, HOVER_DELAY)
}

function onPageTabDragLeave() {
  clearHoverTimeout()
  hoveredPageId.value = null
}

// Setup global event listeners for widget drag
onMounted(() => {
  window.addEventListener('widget-drag-start', handleWidgetDragStart)
  window.addEventListener('widget-drag-end', handleWidgetDragEnd)
})

onUnmounted(() => {
  window.removeEventListener('widget-drag-start', handleWidgetDragStart)
  window.removeEventListener('widget-drag-end', handleWidgetDragEnd)
  clearHoverTimeout()
})

// Expose for parent components
defineExpose({
  isDraggingWidget
})
</script>

<template>
  <div class="page-selector" @click.stop>
    <!-- Page tabs - always visible when multiple pages, expand during drag -->
    <div class="page-tabs" :class="{ 'drag-mode': isDraggingWidget, 'has-multiple': hasMultiplePages }">
      <!-- Current page tab -->
      <button
        class="page-tab current"
        :class="{ 'drop-target': isDraggingWidget }"
        @click="showDropdown = !showDropdown"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <line x1="3" y1="9" x2="21" y2="9"/>
        </svg>
        <span class="tab-name">{{ currentPage?.name || 'Page 1' }}</span>
        <svg v-if="!isDraggingWidget" class="chevron" :class="{ open: showDropdown }" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>

      <!-- Other page tabs (visible when dragging or multiple pages) -->
      <template v-if="hasMultiplePages">
        <button
          v-for="page in otherPages"
          :key="page.id"
          class="page-tab other"
          :class="{
            'drop-target': isDraggingWidget,
            'hover-active': hoveredPageId === page.id,
            'expanded': isDraggingWidget
          }"
          @click="selectPage(page.id)"
          @mouseenter="onPageTabDragEnter(page.id)"
          @mouseleave="onPageTabDragLeave"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <line x1="3" y1="9" x2="21" y2="9"/>
          </svg>
          <span class="tab-name">{{ page.name }}</span>
          <!-- Progress indicator during hover -->
          <div v-if="hoveredPageId === page.id" class="hover-progress" />
        </button>
      </template>

      <!-- Add page button (compact) -->
      <button
        v-if="!isDraggingWidget"
        class="add-tab-btn"
        @click.stop="addNewPage"
        title="Add new page"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>

    <!-- Dropdown for page management -->
    <Teleport to="body">
      <div v-if="showDropdown && !isDraggingWidget" class="page-dropdown-overlay" @click="showDropdown = false">
        <div class="page-dropdown" @click.stop>
          <div class="dropdown-header">
            <span>Dashboard Pages</span>
            <button class="add-page-btn" @click="addNewPage" title="Add new page">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </button>
          </div>

          <div class="page-list">
            <div
              v-for="page in pages"
              :key="page.id"
              class="page-item"
              :class="{ active: page.id === store.currentPageId }"
              @click="selectPage(page.id)"
            >
              <div class="page-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="3" width="18" height="18" rx="2"/>
                  <line x1="3" y1="9" x2="21" y2="9"/>
                </svg>
              </div>

              <div class="page-name-container">
                <input
                  v-if="editingPageId === page.id"
                  ref="inputRef"
                  v-model="editingName"
                  class="rename-input"
                  @blur="finishRename"
                  @keydown="handleKeydown"
                  @click.stop
                />
                <span v-else class="page-item-name" @dblclick.stop="startRename(page.id, page.name)">
                  {{ page.name }}
                </span>
              </div>

              <div class="page-actions">
                <button class="action-btn" @click.stop="startRename(page.id, page.name)" title="Rename">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>
                <button class="action-btn" @click="openInNewWindow(page.id, $event)" title="Open in new window">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                    <polyline points="15 3 21 3 21 9"/>
                    <line x1="10" y1="14" x2="21" y2="3"/>
                  </svg>
                </button>
                <button class="action-btn" @click="duplicatePage(page.id, $event)" title="Duplicate page">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                  </svg>
                </button>
                <button
                  v-if="hasMultiplePages"
                  class="action-btn delete"
                  @click="deletePage(page.id, $event)"
                  title="Delete page"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <div class="dropdown-footer">
            <span class="hint">Double-click to rename • Drag widgets to tabs to move</span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.page-selector {
  position: relative;
  display: flex;
  align-items: center;
}

/* Page tabs - inline display */
.page-tabs {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.2);
}

.page-tabs.drag-mode {
  background: rgba(59, 130, 246, 0.1);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.3);
}

.page-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #888;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.page-tab.current {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.page-tab.other {
  max-width: 0;
  padding: 4px 0;
  overflow: hidden;
  opacity: 0;
}

/* Show other tabs when multiple pages exist */
.page-tabs.has-multiple .page-tab.other {
  max-width: 120px;
  padding: 4px 8px;
  opacity: 0.7;
}

.page-tabs.has-multiple .page-tab.other:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.1);
}

/* Expand tabs during drag */
.page-tab.other.expanded {
  max-width: 150px;
  padding: 4px 12px;
  opacity: 1;
}

.page-tab.drop-target {
  border: 1px dashed rgba(59, 130, 246, 0.5);
}

.page-tab.other.drop-target:hover,
.page-tab.hover-active {
  background: rgba(59, 130, 246, 0.3) !important;
  border-color: #3b82f6;
  color: #fff;
  transform: scale(1.02);
}

.tab-name {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chevron {
  transition: transform 0.2s;
  opacity: 0.6;
}

.chevron.open {
  transform: rotate(180deg);
}

/* Hover progress indicator */
.hover-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  background: #3b82f6;
  animation: progress-fill 0.6s linear forwards;
  border-radius: 0 0 4px 4px;
}

@keyframes progress-fill {
  from { width: 0; }
  to { width: 100%; }
}

/* Add tab button */
.add-tab-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: 1px dashed #444;
  border-radius: 4px;
  color: #666;
  cursor: pointer;
  transition: all 0.2s;
}

.add-tab-btn:hover {
  background: rgba(59, 130, 246, 0.2);
  border-color: #3b82f6;
  color: #3b82f6;
}

/* Dropdown styles */
.page-dropdown-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
}

.page-dropdown {
  position: fixed;
  top: 56px;
  left: 50%;
  transform: translateX(-50%);
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  min-width: 320px;
  max-width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  z-index: 1001;
}

.dropdown-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
  font-weight: 600;
  color: #fff;
}

.add-page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: #1e3a5f;
  border: 1px solid #3b82f6;
  border-radius: 4px;
  color: #60a5fa;
  cursor: pointer;
  transition: all 0.2s;
}

.add-page-btn:hover {
  background: #3b82f6;
  color: #fff;
}

.page-list {
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
}

.page-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.page-item:hover {
  background: #252540;
}

.page-item.active {
  background: #1e3a5f;
}

.page-item.active .page-icon {
  color: #60a5fa;
}

.page-icon {
  color: #666;
  flex-shrink: 0;
}

.page-name-container {
  flex: 1;
  min-width: 0;
}

.page-item-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #ccc;
  font-size: 0.9rem;
}

.page-item.active .page-item-name {
  color: #fff;
  font-weight: 500;
}

.rename-input {
  width: 100%;
  padding: 2px 6px;
  background: #0f0f1a;
  border: 1px solid #3b82f6;
  border-radius: 3px;
  color: #fff;
  font-size: 0.9rem;
  outline: none;
}

.page-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.page-item:hover .page-actions {
  opacity: 1;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #888;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn:hover {
  background: #3a3a5a;
  color: #fff;
}

.action-btn.delete:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

.dropdown-footer {
  padding: 8px 16px;
  border-top: 1px solid #2a2a4a;
}

.hint {
  font-size: 0.75rem;
  color: #666;
}
</style>
