<script setup lang="ts">
/**
 * PidToolbar - Toolbar for P&ID Canvas Editing
 *
 * Provides controls for:
 * - Adding P&ID symbols (valves, pumps, tanks, etc.)
 * - Drawing free-form pipes
 * - Symbol type selection
 * - Pipe style options
 * - Undo/Redo operations
 * - Copy/Paste/Duplicate
 * - Text annotations
 * - Keyboard shortcuts
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import PidLayerPanel from './PidLayerPanel.vue'

const store = useDashboardStore()

// Pipe drawing options — shared with canvas via store
const pipeColor = computed({
  get: () => store.pidPipeColor,
  set: (v: string) => { store.pidPipeColor = v }
})
const pipeDashed = computed({
  get: () => store.pidPipeDashed,
  set: (v: boolean) => { store.pidPipeDashed = v }
})
const pipeAnimated = computed({
  get: () => store.pidPipeAnimated,
  set: (v: boolean) => { store.pidPipeAnimated = v }
})

// UI state
const textToolActive = ref(false)
const alignMenuOpen = ref(false)
const layerPanelOpen = ref(false)

// Toggle pipe drawing mode
function togglePipeDrawing() {
  store.setPidDrawingMode(!store.pidDrawingMode)
}

// Exit P&ID edit mode
function exitEditMode() {
  store.setPidEditMode(false)
}

// Clear all P&ID elements
function clearAll() {
  if (confirm('Clear all P&ID symbols and pipes on this page?')) {
    store.clearPidLayer()
  }
}

// Fit to content
function fitToContent() {
  const canvasEl = document.querySelector('.pid-canvas') as HTMLElement | null
  if (canvasEl) {
    store.pidFitToContent(canvasEl.clientWidth, canvasEl.clientHeight)
  }
}

// Toggle text tool mode
function toggleTextTool() {
  textToolActive.value = !textToolActive.value
  if (textToolActive.value) {
    store.setPidDrawingMode(false)  // Disable pipe drawing when text tool is active
  }
}

// Add text annotation at center
function addTextAnnotation() {
  store.addPidTextAnnotation({
    text: 'New Text',
    x: 200,
    y: 200,
    fontSize: 14,
    color: '#ffffff'
  })
  textToolActive.value = false
}

// Undo/Redo handlers
function handleUndo() {
  store.pidUndo()
}

function handleRedo() {
  store.pidRedo()
}

// Copy/Paste handlers
function handleCopy() {
  store.pidCopy()
}

function handlePaste() {
  store.pidPaste()
}

function handleCut() {
  store.pidCut()
}

function handleDuplicate() {
  store.pidDuplicate()
}

function handleDelete() {
  store.pidDeleteSelected()
}

function handleSelectAll() {
  store.pidSelectAll()
}

function handleBringToFront() {
  store.pidBringToFront()
}

function handleSendToBack() {
  store.pidSendToBack()
}

// Alignment handlers
function handleAlignLeft() {
  store.pidAlignLeft()
  alignMenuOpen.value = false
}

function handleAlignCenterH() {
  store.pidAlignCenterH()
  alignMenuOpen.value = false
}

function handleAlignRight() {
  store.pidAlignRight()
  alignMenuOpen.value = false
}

function handleAlignTop() {
  store.pidAlignTop()
  alignMenuOpen.value = false
}

function handleAlignCenterV() {
  store.pidAlignCenterV()
  alignMenuOpen.value = false
}

function handleAlignBottom() {
  store.pidAlignBottom()
  alignMenuOpen.value = false
}

function handleDistributeH() {
  store.pidDistributeH()
  alignMenuOpen.value = false
}

function handleDistributeV() {
  store.pidDistributeV()
  alignMenuOpen.value = false
}

// Group/Ungroup handlers
function handleGroup() {
  store.pidGroup()
}

function handleUngroup() {
  store.pidUngroup()
}

function toggleAlignMenu() {
  alignMenuOpen.value = !alignMenuOpen.value
}

// Check if multiple items are selected (needed for alignment)
const hasMultipleSelected = computed(() => {
  const total = store.pidSelectedIds.symbolIds.length +
    store.pidSelectedIds.pipeIds.length +
    store.pidSelectedIds.textAnnotationIds.length
  return total >= 2
})

// Check if 3+ items selected (needed for distribute)
const hasThreeOrMoreSelected = computed(() => {
  const total = store.pidSelectedIds.symbolIds.length +
    store.pidSelectedIds.pipeIds.length +
    store.pidSelectedIds.textAnnotationIds.length
  return total >= 3
})

// Keyboard shortcut handler
function handleKeyDown(e: KeyboardEvent) {
  // Only handle when in P&ID edit mode
  if (!store.pidEditMode) return

  // Ignore if typing in an input field
  const target = e.target as HTMLElement
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
    return
  }

  const isCtrl = e.ctrlKey || e.metaKey
  const isShift = e.shiftKey

  // Undo: Ctrl+Z
  if (isCtrl && e.key === 'z' && !isShift) {
    e.preventDefault()
    handleUndo()
    return
  }

  // Redo: Ctrl+Y or Ctrl+Shift+Z
  if ((isCtrl && e.key === 'y') || (isCtrl && isShift && e.key === 'z')) {
    e.preventDefault()
    handleRedo()
    return
  }

  // Copy: Ctrl+C
  if (isCtrl && e.key === 'c') {
    e.preventDefault()
    handleCopy()
    return
  }

  // Paste: Ctrl+V
  if (isCtrl && e.key === 'v') {
    e.preventDefault()
    handlePaste()
    return
  }

  // Cut: Ctrl+X
  if (isCtrl && e.key === 'x') {
    e.preventDefault()
    handleCut()
    return
  }

  // Duplicate: Ctrl+D
  if (isCtrl && e.key === 'd') {
    e.preventDefault()
    handleDuplicate()
    return
  }

  // Delete: Delete or Backspace
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault()
    handleDelete()
    return
  }

  // Select All: Ctrl+A
  if (isCtrl && e.key === 'a') {
    e.preventDefault()
    handleSelectAll()
    return
  }

  // Escape: Cancel/Deselect
  if (e.key === 'Escape') {
    e.preventDefault()
    store.pidClearSelection()
    store.setPidDrawingMode(false)
    textToolActive.value = false
    return
  }

  // T: Text tool
  if (e.key === 't' || e.key === 'T') {
    if (!isCtrl) {
      e.preventDefault()
      toggleTextTool()
      return
    }
  }

  // P: Pipe tool
  if (e.key === 'p' || e.key === 'P') {
    if (!isCtrl) {
      e.preventDefault()
      togglePipeDrawing()
      return
    }
  }

  // R: Rotate selected symbol 90° CW
  if ((e.key === 'r' || e.key === 'R') && !isCtrl) {
    e.preventDefault()
    const ids = store.pidSelectedIds.symbolIds
    if (ids.length > 0) {
      for (const id of ids) {
        const sym = store.pidLayer.symbols.find(s => s.id === id)
        if (sym) store.updatePidSymbolWithUndo(id, { rotation: (sym.rotation || 0) + 90 })
      }
    }
    return
  }

  // Ctrl+G: Group selected
  if (isCtrl && (e.key === 'g' || e.key === 'G') && !isShift) {
    e.preventDefault()
    handleGroup()
    return
  }

  // Ctrl+Shift+G: Ungroup
  if (isCtrl && isShift && (e.key === 'g' || e.key === 'G')) {
    e.preventDefault()
    handleUngroup()
    return
  }

  // G (without Ctrl): Toggle grid snap
  if ((e.key === 'g' || e.key === 'G') && !isCtrl) {
    e.preventDefault()
    store.togglePidGridSnap()
    return
  }

  // M: Toggle minimap
  if ((e.key === 'm' || e.key === 'M') && !isCtrl) {
    e.preventDefault()
    store.pidShowMinimap = !store.pidShowMinimap
    return
  }

  // Zoom: Ctrl+= (zoom in), Ctrl+- (zoom out), Ctrl+0 (reset)
  if (isCtrl && (e.key === '=' || e.key === '+')) {
    e.preventDefault()
    store.setPidZoom(store.pidZoom + 0.1)
    return
  }
  if (isCtrl && e.key === '-') {
    e.preventDefault()
    store.setPidZoom(store.pidZoom - 0.1)
    return
  }
  if (isCtrl && e.key === '0') {
    e.preventDefault()
    store.pidResetZoom()
    return
  }
  if (isCtrl && isShift && (e.key === 'f' || e.key === 'F')) {
    e.preventDefault()
    fitToContent()
    return
  }

  // Arrow keys: Nudge selected elements
  const nudgeAmount = isShift ? 10 : 1
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    store.pidMoveSelected(0, -nudgeAmount)
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    store.pidMoveSelected(0, nudgeAmount)
    return
  }
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    store.pidMoveSelected(-nudgeAmount, 0)
    return
  }
  if (e.key === 'ArrowRight') {
    e.preventDefault()
    store.pidMoveSelected(nudgeAmount, 0)
    return
  }
}

// Background image handlers
function importBackgroundImage() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = async (e) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return

    // Convert to data URL for storage
    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string
      if (dataUrl) {
        // Get image dimensions
        const img = new Image()
        img.onload = () => {
          // Scale to fit canvas while maintaining aspect ratio
          const maxWidth = 1000
          const maxHeight = 800
          let width = img.width
          let height = img.height

          if (width > maxWidth) {
            height = (height * maxWidth) / width
            width = maxWidth
          }
          if (height > maxHeight) {
            width = (width * maxHeight) / height
            height = maxHeight
          }

          store.setPidBackgroundImage({
            url: dataUrl,
            x: 50,
            y: 50,
            width: Math.round(width),
            height: Math.round(height),
            opacity: 0.4,
            locked: false
          })
        }
        img.src = dataUrl
      }
    }
    reader.readAsDataURL(file)
  }
  input.click()
}

function removeBackgroundImage() {
  if (confirm('Remove background image?')) {
    store.removePidBackgroundImage()
  }
}

// Export P&ID as SVG
async function exportAsSvg() {
  try {
    // Find the PID canvas element
    const canvasEl = document.querySelector('.pid-canvas') as HTMLElement
    if (!canvasEl) {
      alert('No P&ID canvas found')
      return
    }

    // Use SVG export (no external dependencies)
    exportSvgFallback(canvasEl)
  } catch (err) {
    console.error('Export failed:', err)
    alert('SVG export failed. See console for details.')
  }
}

// Fallback SVG export method
function exportSvgFallback(canvasEl: HTMLElement) {
  // Get the SVG element from the canvas
  const svgEl = canvasEl.querySelector('svg.pid-canvas-svg')
  if (!svgEl) {
    alert('No SVG content found to export')
    return
  }

  // Clone the SVG
  const svgClone = svgEl.cloneNode(true) as SVGElement
  svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')

  // Serialize to string
  const serializer = new XMLSerializer()
  const svgString = serializer.serializeToString(svgClone)

  // Create blob and download
  const blob = new Blob([svgString], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.download = `pid-export-${Date.now()}.svg`
  link.href = url
  link.click()
  URL.revokeObjectURL(url)
}

// Close align menu when clicking outside
function handleClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.align-dropdown')) {
    alignMenuOpen.value = false
  }
}

// Register event listeners
onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="pid-toolbar">
    <div class="toolbar-section">
      <span class="section-title">P&ID Editor</span>
      <button class="btn-exit" @click="exitEditMode" title="Exit P&ID Edit Mode">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
        Exit
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Undo/Redo Section -->
    <div class="toolbar-section">
      <button
        class="btn-tool"
        :disabled="!store.canPidUndo"
        @click="handleUndo"
        title="Undo (Ctrl+Z)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 10h10a5 5 0 0 1 5 5v2" />
          <polyline points="3 10 7 6 3 10 7 14" />
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.canPidRedo"
        @click="handleRedo"
        title="Redo (Ctrl+Y)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 10H11a5 5 0 0 0-5 5v2" />
          <polyline points="21 10 17 6 21 10 17 14" />
        </svg>
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Copy/Paste Section -->
    <div class="toolbar-section">
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleCut"
        title="Cut (Ctrl+X)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" />
          <line x1="20" y1="4" x2="8.12" y2="15.88" /><line x1="14.47" y1="14.48" x2="20" y2="20" />
          <line x1="8.12" y1="8.12" x2="12" y2="12" />
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleCopy"
        title="Copy (Ctrl+C)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.hasPidClipboard"
        @click="handlePaste"
        title="Paste (Ctrl+V)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path>
          <rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect>
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleDuplicate"
        title="Duplicate (Ctrl+D)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="8" y="8" width="12" height="12" rx="2"></rect>
          <path d="M4 16V4h12"></path>
        </svg>
      </button>
      <button
        class="btn-tool btn-delete"
        :disabled="!store.hasPidSelection"
        @click="handleDelete"
        title="Delete (Del)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      </button>
      <!-- Z-index controls -->
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleBringToFront"
        title="Bring to Front"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="8" height="8" rx="1" />
          <rect x="13" y="13" width="8" height="8" rx="1" fill="currentColor" opacity="0.3" />
          <path d="M13 3v8h8" stroke-dasharray="2,2" />
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleSendToBack"
        title="Send to Back"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="13" y="13" width="8" height="8" rx="1" />
          <rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" opacity="0.3" />
          <path d="M11 13H3v8" stroke-dasharray="2,2" />
        </svg>
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Alignment Section -->
    <div class="toolbar-section align-section">
      <div class="align-dropdown">
        <button
          class="btn-align"
          :class="{ active: alignMenuOpen }"
          :disabled="!hasMultipleSelected"
          @click="toggleAlignMenu"
          title="Alignment Tools (select 2+ items)"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="4" y1="6" x2="4" y2="18" />
            <rect x="8" y="5" width="12" height="4" rx="1" />
            <rect x="8" y="11" width="8" height="4" rx="1" />
            <rect x="8" y="17" width="10" height="4" rx="1" />
          </svg>
          Align
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
        <div v-if="alignMenuOpen" class="align-menu">
          <div class="align-menu-section">
            <span class="menu-section-title">Align</span>
            <button @click="handleAlignLeft" title="Align Left">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="4" x2="4" y2="20" />
                <rect x="8" y="6" width="12" height="4" rx="1" />
                <rect x="8" y="14" width="8" height="4" rx="1" />
              </svg>
              Left
            </button>
            <button @click="handleAlignCenterH" title="Align Center Horizontal">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="4" x2="12" y2="20" />
                <rect x="4" y="6" width="16" height="4" rx="1" />
                <rect x="6" y="14" width="12" height="4" rx="1" />
              </svg>
              Center H
            </button>
            <button @click="handleAlignRight" title="Align Right">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="20" y1="4" x2="20" y2="20" />
                <rect x="4" y="6" width="12" height="4" rx="1" />
                <rect x="8" y="14" width="8" height="4" rx="1" />
              </svg>
              Right
            </button>
            <button @click="handleAlignTop" title="Align Top">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="4" x2="20" y2="4" />
                <rect x="6" y="8" width="4" height="12" rx="1" />
                <rect x="14" y="8" width="4" height="8" rx="1" />
              </svg>
              Top
            </button>
            <button @click="handleAlignCenterV" title="Align Center Vertical">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="12" x2="20" y2="12" />
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="6" width="4" height="12" rx="1" />
              </svg>
              Center V
            </button>
            <button @click="handleAlignBottom" title="Align Bottom">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="20" x2="20" y2="20" />
                <rect x="6" y="4" width="4" height="12" rx="1" />
                <rect x="14" y="8" width="4" height="8" rx="1" />
              </svg>
              Bottom
            </button>
          </div>
          <div class="align-menu-divider" />
          <div class="align-menu-section">
            <span class="menu-section-title">Distribute</span>
            <button @click="handleDistributeH" :disabled="!hasThreeOrMoreSelected" title="Distribute Horizontally (3+ items)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="8" width="4" height="8" rx="1" />
                <rect x="10" y="8" width="4" height="8" rx="1" />
                <rect x="18" y="8" width="4" height="8" rx="1" />
              </svg>
              Horizontal
            </button>
            <button @click="handleDistributeV" :disabled="!hasThreeOrMoreSelected" title="Distribute Vertically (3+ items)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="8" y="2" width="8" height="4" rx="1" />
                <rect x="8" y="10" width="8" height="4" rx="1" />
                <rect x="8" y="18" width="8" height="4" rx="1" />
              </svg>
              Vertical
            </button>
          </div>
        </div>
      </div>
      <!-- Group/Ungroup buttons -->
      <button
        class="btn-tool"
        :disabled="!hasMultipleSelected"
        @click="handleGroup"
        title="Group (Ctrl+G)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="8" height="8" rx="1" />
          <rect x="13" y="3" width="8" height="8" rx="1" />
          <rect x="3" y="13" width="8" height="8" rx="1" />
          <rect x="13" y="13" width="8" height="8" rx="1" />
          <path d="M7 11v2M17 11v2M11 7h2M11 17h2" stroke-dasharray="2,2" />
        </svg>
      </button>
      <button
        class="btn-tool"
        :disabled="!store.hasPidSelection"
        @click="handleUngroup"
        title="Ungroup (Ctrl+Shift+G)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Add Symbol Section -->
    <div class="toolbar-section">
      <button
        class="btn-panel-toggle"
        :class="{ active: store.pidSymbolPanelOpen }"
        @click="store.pidSymbolPanelOpen = !store.pidSymbolPanelOpen"
        title="Toggle Symbol Panel"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="9" y1="3" x2="9" y2="21" />
        </svg>
        Symbols
      </button>
      <button
        class="btn-panel-toggle"
        :class="{ active: store.pidPropertiesPanelOpen }"
        @click="store.pidPropertiesPanelOpen = !store.pidPropertiesPanelOpen"
        title="Toggle Properties Panel"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="15" y1="3" x2="15" y2="21" />
        </svg>
        Props
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Pipe Drawing Section -->
    <div class="toolbar-section">
      <button
        class="btn-pipe"
        :class="{ active: store.pidDrawingMode }"
        @click="togglePipeDrawing"
        title="Draw Pipe"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M2 12h6l4-4 4 8 4-4h4" />
        </svg>
        {{ store.pidDrawingMode ? 'Drawing...' : 'Draw Pipe' }}
      </button>

      <input
        type="color"
        v-model="pipeColor"
        class="color-picker"
        title="Pipe Color"
      />

      <label class="checkbox-label" title="Dashed Line">
        <input type="checkbox" v-model="pipeDashed" />
        Dashed
      </label>

      <label class="checkbox-label" title="Animated Flow">
        <input type="checkbox" v-model="pipeAnimated" />
        Flow
      </label>

      <label class="checkbox-label" title="Auto-Route: pipes route around obstacles">
        <input type="checkbox" :checked="store.pidAutoRoute" @change="store.pidAutoRoute = !store.pidAutoRoute" />
        Auto-Route
      </label>
    </div>

    <div class="toolbar-divider" />

    <!-- Text Tool Section -->
    <div class="toolbar-section">
      <button
        class="btn-text"
        :class="{ active: textToolActive }"
        @click="toggleTextTool"
        title="Text Tool (T)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="4 7 4 4 20 4 20 7"></polyline>
          <line x1="9" y1="20" x2="15" y2="20"></line>
          <line x1="12" y1="4" x2="12" y2="20"></line>
        </svg>
        Text
      </button>
      <button
        v-if="textToolActive"
        class="btn-add"
        @click="addTextAnnotation"
        title="Add Text Label"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        Add
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Grid Snap Toggle with Size Control -->
    <div class="toolbar-section grid-section">
      <button
        class="btn-grid"
        :class="{ active: store.pidGridSnapEnabled }"
        @click="store.togglePidGridSnap()"
        title="Toggle Grid Snap (G) - Snaps ports to grid"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7" />
          <rect x="14" y="3" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" />
        </svg>
        Grid
      </button>
      <select
        v-if="store.pidGridSnapEnabled"
        :value="store.pidGridSize"
        @change="store.setPidGridSize(Number(($event.target as HTMLSelectElement).value))"
        class="grid-size-select"
        title="Grid Size (pixels)"
      >
        <option :value="5">5px</option>
        <option :value="10">10px</option>
        <option :value="15">15px</option>
        <option :value="20">20px</option>
        <option :value="25">25px</option>
        <option :value="30">30px</option>
        <option :value="40">40px</option>
        <option :value="50">50px</option>
      </select>
      <!-- Rulers toggle -->
      <button
        class="btn-grid"
        :class="{ active: store.pidShowRulers }"
        @click="store.pidShowRulers = !store.pidShowRulers"
        title="Toggle Rulers + Guides"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="3" x2="3" y2="21" />
          <line x1="3" y1="3" x2="21" y2="3" />
          <line x1="7" y1="3" x2="7" y2="5" />
          <line x1="11" y1="3" x2="11" y2="7" />
          <line x1="15" y1="3" x2="15" y2="5" />
          <line x1="19" y1="3" x2="19" y2="7" />
          <line x1="3" y1="7" x2="5" y2="7" />
          <line x1="3" y1="11" x2="7" y2="11" />
          <line x1="3" y1="15" x2="5" y2="15" />
          <line x1="3" y1="19" x2="7" y2="19" />
        </svg>
        Rulers
      </button>
      <!-- Layers toggle -->
      <button
        class="btn-grid"
        :class="{ active: layerPanelOpen }"
        @click="layerPanelOpen = !layerPanelOpen"
        title="Toggle Layers Panel"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
        Layers
      </button>
      <!-- ISA-101 Grayscale Mode -->
      <button
        class="btn-isa"
        :class="{ active: store.pidColorScheme === 'isa101' }"
        @click="store.togglePidColorScheme()"
        title="ISA-101 Grayscale Mode (High Performance HMI)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 3 A9 9 0 0 1 12 21" fill="currentColor" opacity="0.3" />
        </svg>
        ISA-101
      </button>
      <!-- Minimap Toggle -->
      <button
        class="btn-minimap"
        :class="{ active: store.pidShowMinimap }"
        @click="store.pidShowMinimap = !store.pidShowMinimap"
        title="Toggle Minimap (M)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <rect x="12" y="12" width="8" height="8" rx="1" opacity="0.5" />
        </svg>
        Map
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Zoom Controls -->
    <div class="toolbar-section zoom-section">
      <button
        class="btn-tool"
        @click="store.setPidZoom(store.pidZoom - 0.1)"
        :disabled="store.pidZoom <= 0.1"
        title="Zoom Out"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
          <line x1="8" y1="11" x2="14" y2="11" />
        </svg>
      </button>
      <span class="zoom-display" @click="store.pidResetZoom()" title="Click to reset to 100%">
        {{ Math.round(store.pidZoom * 100) }}%
      </span>
      <button
        class="btn-tool"
        @click="store.setPidZoom(store.pidZoom + 0.1)"
        :disabled="store.pidZoom >= 5"
        title="Zoom In"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
          <line x1="11" y1="8" x2="11" y2="14" />
          <line x1="8" y1="11" x2="14" y2="11" />
        </svg>
      </button>
      <button
        class="btn-tool"
        @click="store.pidResetZoom()"
        title="Reset Zoom & Pan (100%)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      </button>
      <button
        class="btn-tool"
        @click="fitToContent"
        title="Fit to Content (Ctrl+Shift+F)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
        </svg>
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Background Image -->
    <div class="toolbar-section">
      <button class="btn-bg" @click="importBackgroundImage" title="Import Background Image">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <polyline points="21 15 16 10 5 21"/>
        </svg>
        Background
      </button>
      <button
        v-if="store.pidLayer?.backgroundImage"
        class="btn-tool btn-delete"
        @click="removeBackgroundImage"
        title="Remove Background Image"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Export -->
    <div class="toolbar-section">
      <button class="btn-export" @click="exportAsSvg" title="Export as SVG Image">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Export SVG
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Actions -->
    <div class="toolbar-section">
      <button class="btn-clear" @click="clearAll" title="Clear All P&ID Elements">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
        Clear
      </button>
    </div>

    <!-- Help Text -->
    <div class="toolbar-help">
      <span v-if="store.pidDrawingMode">Click to add points, double-click to finish pipe</span>
      <span v-else>Drag symbols to position, corners to resize</span>
    </div>

    <!-- Floating Layer Panel -->
    <div v-if="layerPanelOpen" class="layer-panel-float">
      <PidLayerPanel />
    </div>
  </div>
</template>

<style scoped>
.pid-toolbar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px 16px;
  background: linear-gradient(to right, #1e3a5f, #2a4a6f);
  border-bottom: 1px solid #3b5998;
  flex-wrap: wrap;
}

.toolbar-section {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-label {
  font-size: 12px;
  color: #aaa;
}

.toolbar-divider {
  width: 1px;
  height: 24px;
  background: #3b5998;
}

/* Buttons */
button {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-exit {
  background: #4a5568;
  color: #fff;
}

.btn-exit:hover {
  background: #718096;
}


.btn-pipe {
  background: #3b82f6;
  color: #fff;
}

.btn-pipe:hover {
  background: #2563eb;
}

.btn-pipe.active {
  background: #f59e0b;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.btn-clear {
  background: #ef4444;
  color: #fff;
}

.btn-clear:hover {
  background: #dc2626;
}

/* Tool buttons (undo/redo, copy/paste) */
.btn-tool {
  background: #4a5568;
  color: #fff;
  padding: 6px 8px;
}

.btn-tool:hover:not(:disabled) {
  background: #718096;
}

.btn-tool:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-tool.btn-delete:hover:not(:disabled) {
  background: #ef4444;
}

/* Text tool button */
.btn-text {
  background: #8b5cf6;
  color: #fff;
}

.btn-text:hover {
  background: #7c3aed;
}

.btn-text.active {
  background: #f59e0b;
  animation: pulse 1s infinite;
}

/* Add text button */
.btn-add {
  background: #10b981;
  color: #fff;
}

.btn-add:hover {
  background: #059669;
}

/* Grid section */
.grid-section {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* Grid button */
.btn-grid {
  background: #4a5568;
  color: #fff;
}

.btn-grid:hover {
  background: #718096;
}

.btn-grid.active {
  background: #10b981;
}

/* Grid size selector */
.grid-size-select {
  padding: 4px 6px;
  background: #2d3748;
  border: 1px solid #10b981;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  cursor: pointer;
  min-width: 55px;
}

.grid-size-select:hover {
  background: #374151;
}

.grid-size-select:focus {
  outline: none;
  border-color: #34d399;
}

/* ISA-101 button */
.btn-isa {
  background: #4a5568;
  color: #fff;
}

.btn-isa:hover {
  background: #718096;
}

.btn-isa.active {
  background: #6b7280;
  filter: grayscale(0%);
}

/* Background image button */
.btn-bg {
  background: #0ea5e9;
  color: #fff;
}

.btn-bg:hover {
  background: #0284c7;
}

/* Export button */
.btn-export {
  background: #10b981;
  color: #fff;
}

.btn-export:hover {
  background: #059669;
}

/* Alignment dropdown */
.align-section {
  position: relative;
}

.align-dropdown {
  position: relative;
}

.btn-align {
  background: #6366f1;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-align:hover:not(:disabled) {
  background: #4f46e5;
}

.btn-align:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-align.active {
  background: #4f46e5;
}

.align-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: #1e293b;
  border: 1px solid #3b5998;
  border-radius: 6px;
  padding: 8px 0;
  min-width: 150px;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.align-menu-section {
  padding: 4px 0;
}

.menu-section-title {
  display: block;
  padding: 4px 12px;
  font-size: 10px;
  text-transform: uppercase;
  color: #64748b;
  letter-spacing: 0.5px;
}

.align-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 12px;
  background: transparent;
  border: none;
  color: #e2e8f0;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  border-radius: 0;
}

.align-menu button:hover:not(:disabled) {
  background: #334155;
}

.align-menu button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.align-menu-divider {
  height: 1px;
  background: #3b5998;
  margin: 4px 0;
}

/* Inputs */

.color-picker {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #aaa;
  cursor: pointer;
}

.checkbox-label input {
  margin: 0;
}

/* Panel toggle button */
.btn-panel-toggle {
  background: #4a5568;
  color: #fff;
}

.btn-panel-toggle:hover {
  background: #718096;
}

.btn-panel-toggle.active {
  background: #6366f1;
}

/* Zoom controls */
.zoom-section {
  display: flex;
  align-items: center;
  gap: 4px;
}

.zoom-display {
  font-size: 12px;
  font-weight: 600;
  color: #60a5fa;
  min-width: 40px;
  text-align: center;
  cursor: pointer;
  user-select: none;
}

.zoom-display:hover {
  color: #93c5fd;
}

/* Help text */
.toolbar-help {
  font-size: 11px;
  color: #888;
  font-style: italic;
}

.layer-panel-float {
  position: absolute;
  right: 0;
  top: 100%;
  margin-top: 4px;
  z-index: 100;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  border-radius: 6px;
}
</style>
