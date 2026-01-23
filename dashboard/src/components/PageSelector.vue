<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useWindowSync } from '../composables/useWindowSync'

const store = useDashboardStore()
const windowSync = useWindowSync()

// UI state
const showDropdown = ref(false)
const dropdownPageId = ref<string | null>(null) // Which page the dropdown is for
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

function openPageMenu(pageId: string, event: MouseEvent) {
  dropdownPageId.value = pageId
  showDropdown.value = true
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
  const page = pages.value.find(p => p.id === pageId)
  const pageName = page?.name || 'Page'
  windowSync.openPageInWindow(pageId, pageName)
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
  <!-- Horizontal page tabs under header, top left -->
  <Teleport to="body">
    <div class="page-tabs-container" :class="{ 'drag-mode': isDraggingWidget }">
      <!-- Page tabs as horizontal tabs -->
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
        @dblclick.stop="startRename(page.id, page.name)"
        @contextmenu.prevent="openPageMenu(page.id, $event)"
      >
        <span class="tab-number">{{ index + 1 }}</span>
        <input
          v-if="editingPageId === page.id"
          ref="inputRef"
          v-model="editingName"
          class="rename-input"
          @blur="finishRename"
          @keydown="handleKeydown"
          @click.stop
        />
        <span v-else class="tab-name">{{ page.name }}</span>
        <!-- Delete button on tab (visible on hover when multiple pages) -->
        <button
          v-if="hasMultiplePages"
          class="tab-delete-btn"
          @click.stop="deletePage(page.id, $event)"
          title="Delete page"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
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

    <!-- Context menu for page actions (on right-click) -->
    <div v-if="showDropdown && !isDraggingWidget" class="page-context-overlay" @click="showDropdown = false">
      <div class="page-context-menu" @click.stop>
        <button class="context-item" @click="startRename(dropdownPageId!, pages.find(p => p.id === dropdownPageId)?.name || ''); showDropdown = false">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          <span>Rename</span>
        </button>
        <button class="context-item" @click="duplicatePage(dropdownPageId!, $event); showDropdown = false">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
          </svg>
          <span>Duplicate</span>
        </button>
        <button class="context-item" @click="openInNewWindow(dropdownPageId!, $event); showDropdown = false">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
            <polyline points="15 3 21 3 21 9"/>
            <line x1="10" y1="14" x2="21" y2="3"/>
          </svg>
          <span>Open in New Window</span>
        </button>
        <div v-if="hasMultiplePages" class="context-divider"></div>
        <button
          v-if="hasMultiplePages"
          class="context-item delete"
          @click="deletePage(dropdownPageId!, $event); showDropdown = false"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
          </svg>
          <span>Delete Page</span>
        </button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Page tabs container - horizontal position under header */
.page-tabs-container {
  position: fixed;
  top: 56px; /* Flush with the 56px header bottom */
  left: 8px;
  z-index: 40; /* Below header z-index (100) */
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 3px;
  /* Recess when not hovered */
  transform: translateY(-16px);
  opacity: 0.4;
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.page-tabs-container:hover {
  transform: translateY(0);
  opacity: 1;
}

/* Highlight during drag mode - also un-recess */
.page-tabs-container.drag-mode {
  transform: translateY(0);
  opacity: 1;
  background: rgba(59, 130, 246, 0.1);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
  border-radius: 0 0 4px 4px;
}

/* Individual page tab - slim horizontal style */
.page-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-top: none;
  border-radius: 0 0 4px 4px;
  color: #888;
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.15s;
  min-width: 60px;
  position: relative;
}

.page-tab:hover {
  background: #252540;
  color: #ccc;
}

.page-tab.active {
  background: #0f0f1a;
  border-color: #3b82f6;
  border-bottom: 2px solid #3b82f6;
  color: #fff;
  z-index: 1;
}

.page-tab.drop-target {
  border: 1px dashed rgba(59, 130, 246, 0.5);
  border-top: none;
}

.page-tab.hover-active {
  background: rgba(59, 130, 246, 0.3) !important;
  border-color: #3b82f6;
  color: #fff;
  transform: translateY(4px);
}

.tab-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  font-size: 0.6rem;
  font-weight: 600;
}

.page-tab.active .tab-number {
  background: #3b82f6;
  color: #fff;
}

.tab-name {
  max-width: 50px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Delete button on tab - appears on hover */
.tab-delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  padding: 0;
  margin-left: 2px;
  background: transparent;
  border: none;
  border-radius: 2px;
  color: #666;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
}

.page-tab:hover .tab-delete-btn {
  opacity: 1;
}

.tab-delete-btn:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

/* Hover progress indicator - horizontal */
.hover-progress {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 3px;
  background: #3b82f6;
  animation: progress-fill-horizontal 0.6s linear forwards;
  border-radius: 0 0 6px 6px;
}

@keyframes progress-fill-horizontal {
  from { width: 0; }
  to { width: 100%; }
}

/* Add tab button - inline with tabs */
.add-tab-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-left: 2px;
  background: transparent;
  border: 1px dashed #444;
  border-top: none;
  border-radius: 0 0 3px 3px;
  color: #555;
  cursor: pointer;
  transition: all 0.15s;
}

.add-tab-btn:hover {
  background: rgba(59, 130, 246, 0.2);
  border-color: #3b82f6;
  color: #3b82f6;
}

/* Context menu styles */
.page-context-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
}

.page-context-menu {
  position: fixed;
  top: 80px;
  left: 20px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  min-width: 180px;
  padding: 4px 0;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  z-index: 1001;
}

.context-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: #ccc;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.context-item:hover {
  background: #252540;
  color: #fff;
}

.context-item.delete {
  color: #f87171;
}

.context-item.delete:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

.context-divider {
  height: 1px;
  background: #2a2a4a;
  margin: 4px 0;
}

/* Inline rename input */
.rename-input {
  padding: 2px 6px;
  background: #0f0f1a;
  border: 1px solid #3b82f6;
  border-radius: 3px;
  color: #fff;
  font-size: 0.7rem;
  outline: none;
  width: 60px;
}
</style>
