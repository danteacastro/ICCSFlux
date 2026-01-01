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

// Refs to page tab elements for hit testing during drag
const pageTabRefs = ref<Map<string, HTMLElement>>(new Map())

// Computed
const pages = computed(() => store.sortedPages)
// currentPage available via store.currentPage in template
const hasMultiplePages = computed(() => pages.value.length > 1)

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
  // Start listening for mouse movement to detect tab hover
  window.addEventListener('mousemove', handleMouseMoveDuringDrag)
}

function handleWidgetDragEnd() {
  isDraggingWidget.value = false
  draggingWidgetId.value = null
  clearHoverTimeout()
  hoveredPageId.value = null
  // Stop listening for mouse movement
  window.removeEventListener('mousemove', handleMouseMoveDuringDrag)
}

// Track mouse position during drag to detect when over page tabs
function handleMouseMoveDuringDrag(event: MouseEvent) {
  if (!isDraggingWidget.value) return

  const mouseX = event.clientX
  const mouseY = event.clientY

  // Check if mouse is over any page tab
  let foundHoveredPage: string | null = null

  for (const [pageId, element] of pageTabRefs.value.entries()) {
    if (pageId === store.currentPageId) continue // Skip current page

    const rect = element.getBoundingClientRect()
    if (mouseX >= rect.left && mouseX <= rect.right &&
        mouseY >= rect.top && mouseY <= rect.bottom) {
      foundHoveredPage = pageId
      break
    }
  }

  // Handle hover state changes
  if (foundHoveredPage !== hoveredPageId.value) {
    if (foundHoveredPage) {
      onPageTabDragEnter(foundHoveredPage)
    } else {
      onPageTabDragLeave()
    }
  }
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
  window.removeEventListener('mousemove', handleMouseMoveDuringDrag)
  clearHoverTimeout()
})

// Expose for parent components
defineExpose({
  isDraggingWidget
})
</script>

<template>
  <!-- Vertical page tabs on right edge, below header -->
  <Teleport to="body">
    <div class="page-tabs-container" :class="{ 'drag-mode': isDraggingWidget }">
      <!-- Page tabs as vertical book tabs -->
      <div
        v-for="(page, index) in pages"
        :key="page.id"
        :ref="(el) => { if (el) pageTabRefs.set(page.id, el as HTMLElement); else pageTabRefs.delete(page.id) }"
        class="page-tab"
        :class="{
          active: page.id === store.currentPageId,
          'drop-target': isDraggingWidget && page.id !== store.currentPageId,
          'hover-active': hoveredPageId === page.id
        }"
        @click="selectPage(page.id)"
        @contextmenu.prevent="startRename(page.id, page.name)"
      >
        <span class="tab-number">{{ index + 1 }}</span>
        <span class="tab-name">{{ page.name }}</span>
        <!-- Progress indicator during hover -->
        <div v-if="hoveredPageId === page.id" class="hover-progress" />
      </div>

      <!-- Add page button -->
      <button
        class="add-tab-btn"
        @click.stop="addNewPage"
        title="Add new page"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>

    <!-- Dropdown for page management (on right-click or long press) -->
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
</template>

<style scoped>
/* Page tabs container - fixed position on right edge below header */
.page-tabs-container {
  position: fixed;
  top: 48px; /* Below header */
  right: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.page-tabs-container.drag-mode {
  background: rgba(59, 130, 246, 0.1);
  box-shadow: -2px 0 8px rgba(59, 130, 246, 0.3);
}

/* Individual page tab - book tab style */
.page-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-right: none;
  border-radius: 6px 0 0 6px;
  color: #888;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
  min-width: 80px;
  position: relative;
  margin-right: -1px;
}

.page-tab:hover {
  background: #252540;
  color: #ccc;
  padding-left: 14px;
}

.page-tab.active {
  background: #0f0f1a;
  border-color: #3b82f6;
  border-left: 3px solid #3b82f6;
  color: #fff;
  padding-left: 12px;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.3);
  z-index: 1;
}

.page-tab.drop-target {
  border: 1px dashed rgba(59, 130, 246, 0.5);
  border-right: none;
}

.page-tab.hover-active {
  background: rgba(59, 130, 246, 0.3) !important;
  border-color: #3b82f6;
  color: #fff;
  transform: translateX(-4px);
}

.tab-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
}

.page-tab.active .tab-number {
  background: #3b82f6;
  color: #fff;
}

.tab-name {
  max-width: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Hover progress indicator */
.hover-progress {
  position: absolute;
  left: 0;
  top: 0;
  width: 3px;
  background: #3b82f6;
  animation: progress-fill-vertical 0.6s linear forwards;
  border-radius: 6px 0 0 6px;
}

@keyframes progress-fill-vertical {
  from { height: 0; }
  to { height: 100%; }
}

/* Add tab button */
.add-tab-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin: 4px 8px 4px auto;
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
  top: 100px;
  right: 20px;
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
