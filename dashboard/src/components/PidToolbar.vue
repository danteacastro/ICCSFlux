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
import { validatePidLayer, type PidValidationIssue } from '../utils/pidValidation'

const store = useDashboardStore()

// Symbol search (#3.8)
const showSearchOverlay = ref(false)
const searchQuery = ref('')
const searchResults = computed(() => {
  if (!searchQuery.value.trim()) return []
  const q = searchQuery.value.toLowerCase()
  return store.pidLayer.symbols.filter(s =>
    (s.label && s.label.toLowerCase().includes(q)) ||
    s.type.toLowerCase().includes(q) ||
    (s.channel && s.channel.toLowerCase().includes(q))
  )
})
const searchIndex = ref(0)

function openSearch() {
  showSearchOverlay.value = true
  searchQuery.value = ''
  searchIndex.value = 0
}

function closeSearch() {
  showSearchOverlay.value = false
  searchQuery.value = ''
}

function navigateSearch(delta: number) {
  if (searchResults.value.length === 0) return
  searchIndex.value = (searchIndex.value + delta + searchResults.value.length) % searchResults.value.length
  const sym = searchResults.value[searchIndex.value]
  if (sym) {
    // Select and zoom to the symbol
    store.pidSelectItems([sym.id], [], [])
    // Center viewport on symbol
    const cx = sym.x + sym.width / 2
    const cy = sym.y + sym.height / 2
    store.setPidPan(-cx * store.pidZoom + 500, -cy * store.pidZoom + 300)
  }
}

// Connection validation (#5.2)
const showValidationPanel = ref(false)
const validationIssues = computed<PidValidationIssue[]>(() => validatePidLayer(store.pidLayer))
const validationErrors = computed(() => validationIssues.value.filter(i => i.severity === 'error').length)
const validationWarnings = computed(() => validationIssues.value.filter(i => i.severity === 'warning').length)

function navigateToIssue(issue: PidValidationIssue) {
  if (issue.symbolId) {
    store.pidSelectItems([issue.symbolId], [], [])
  } else if (issue.pipeId) {
    store.pidSelectItems([], [issue.pipeId], [])
  }
  store.setPidPan(-issue.x * store.pidZoom + 500, -issue.y * store.pidZoom + 300)
}

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
const viewMenuOpen = ref(false)
const moreMenuOpen = ref(false)
const pipeOptionsOpen = ref(false)

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

  // Find/Search: Ctrl+F (#3.8)
  if (isCtrl && e.key === 'f') {
    e.preventDefault()
    openSearch()
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

  // H: Flip selected symbols horizontal
  if ((e.key === 'h' || e.key === 'H') && !isCtrl) {
    e.preventDefault()
    const ids = store.pidSelectedIds.symbolIds
    if (ids.length > 0) {
      for (const id of ids) {
        const sym = store.pidLayer.symbols.find(s => s.id === id)
        if (sym) store.updatePidSymbolWithUndo(id, { flipX: !sym.flipX })
      }
    }
    return
  }

  // V: Flip selected symbols vertical
  if ((e.key === 'v' || e.key === 'V') && !isCtrl) {
    e.preventDefault()
    const ids = store.pidSelectedIds.symbolIds
    if (ids.length > 0) {
      for (const id of ids) {
        const sym = store.pidLayer.symbols.find(s => s.id === id)
        if (sym) store.updatePidSymbolWithUndo(id, { flipY: !sym.flipY })
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

  // [: Toggle symbol panel collapse
  if (e.key === '[' && !isCtrl) {
    e.preventDefault()
    store.togglePidSymbolPanelCollapse()
    return
  }

  // ]: Toggle properties panel collapse
  if (e.key === ']' && !isCtrl) {
    e.preventDefault()
    store.togglePidPropertiesPanelCollapse()
    return
  }

  // \: Toggle focus mode
  if (e.key === '\\' && !isCtrl) {
    e.preventDefault()
    store.togglePidFocusMode()
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

// Close menus when clicking outside
function handleClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.align-dropdown')) {
    alignMenuOpen.value = false
  }
  if (!target.closest('.view-dropdown')) {
    viewMenuOpen.value = false
  }
  if (!target.closest('.more-dropdown')) {
    moreMenuOpen.value = false
  }
  if (!target.closest('.pipe-section')) {
    pipeOptionsOpen.value = false
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
  <div class="pid-toolbar" :class="{ compact: store.pidToolbarCompact }">
    <!-- ===== COMPACT / FOCUS MODE TOOLBAR ===== -->
    <template v-if="store.pidToolbarCompact">
      <div class="toolbar-section">
        <span class="section-title">P&ID</span>
        <button class="btn-exit" @click="exitEditMode" title="Exit P&ID Edit Mode">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          Exit
        </button>
      </div>
      <div class="toolbar-divider" />
      <div class="toolbar-section">
        <button class="btn-tool" :disabled="!store.canPidUndo" @click="handleUndo" title="Undo (Ctrl+Z)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 10h10a5 5 0 0 1 5 5v2" /><polyline points="3 10 7 6 3 10 7 14" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.canPidRedo" @click="handleRedo" title="Redo (Ctrl+Y)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 10H11a5 5 0 0 0-5 5v2" /><polyline points="21 10 17 6 21 10 17 14" />
          </svg>
        </button>
      </div>
      <div class="toolbar-divider" />
      <div class="toolbar-section">
        <button class="btn-pipe" :class="{ active: store.pidDrawingMode }" @click="togglePipeDrawing" title="Draw Pipe (P)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 12h6l4-4 4 8 4-4h4" />
          </svg>
        </button>
        <button class="btn-text" :class="{ active: textToolActive }" @click="toggleTextTool" title="Text Tool (T)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4 7 4 4 20 4 20 7" /><line x1="9" y1="20" x2="15" y2="20" /><line x1="12" y1="4" x2="12" y2="20" />
          </svg>
        </button>
      </div>
      <div class="toolbar-divider" />
      <div class="toolbar-section">
        <button class="btn-tool btn-focus active" @click="store.togglePidFocusMode()" title="Exit Focus Mode (\\)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
        </button>
      </div>
      <span class="zoom-display" @click="store.pidResetZoom()" title="Click to reset to 100%">
        {{ Math.round(store.pidZoom * 100) }}%
      </span>
    </template>

    <!-- ===== FULL TOOLBAR ===== -->
    <template v-else>
      <div class="toolbar-section">
        <span class="section-title">P&ID</span>
        <button class="btn-exit" @click="exitEditMode" title="Exit P&ID Edit Mode">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          Exit
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Undo/Redo -->
      <div class="toolbar-section">
        <button class="btn-tool" :disabled="!store.canPidUndo" @click="handleUndo" title="Undo (Ctrl+Z)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 10h10a5 5 0 0 1 5 5v2" /><polyline points="3 10 7 6 3 10 7 14" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.canPidRedo" @click="handleRedo" title="Redo (Ctrl+Y)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 10H11a5 5 0 0 0-5 5v2" /><polyline points="21 10 17 6 21 10 17 14" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Copy/Paste/Delete/Z-order -->
      <div class="toolbar-section">
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleCut" title="Cut (Ctrl+X)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" />
            <line x1="20" y1="4" x2="8.12" y2="15.88" /><line x1="14.47" y1="14.48" x2="20" y2="20" />
            <line x1="8.12" y1="8.12" x2="12" y2="12" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleCopy" title="Copy (Ctrl+C)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidClipboard" @click="handlePaste" title="Paste (Ctrl+V)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleDuplicate" title="Duplicate (Ctrl+D)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="8" y="8" width="12" height="12" rx="2" /><path d="M4 16V4h12" />
          </svg>
        </button>
        <button class="btn-tool btn-delete" :disabled="!store.hasPidSelection" @click="handleDelete" title="Delete (Del)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleBringToFront" title="Bring to Front">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="8" height="8" rx="1" /><rect x="13" y="13" width="8" height="8" rx="1" fill="currentColor" opacity="0.3" /><path d="M13 3v8h8" stroke-dasharray="2,2" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleSendToBack" title="Send to Back">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="13" y="13" width="8" height="8" rx="1" /><rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" opacity="0.3" /><path d="M11 13H3v8" stroke-dasharray="2,2" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Alignment + Group -->
      <div class="toolbar-section align-section">
        <div class="align-dropdown">
          <button class="btn-align" :class="{ active: alignMenuOpen }" :disabled="!hasMultipleSelected" @click="toggleAlignMenu" title="Alignment Tools (select 2+ items)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="4" y1="6" x2="4" y2="18" /><rect x="8" y="5" width="12" height="4" rx="1" /><rect x="8" y="11" width="8" height="4" rx="1" /><rect x="8" y="17" width="10" height="4" rx="1" />
            </svg>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9" /></svg>
          </button>
          <div v-if="alignMenuOpen" class="align-menu">
            <div class="align-menu-section">
              <span class="menu-section-title">Align</span>
              <button @click="handleAlignLeft" title="Align Left"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="4" x2="4" y2="20" /><rect x="8" y="6" width="12" height="4" rx="1" /><rect x="8" y="14" width="8" height="4" rx="1" /></svg> Left</button>
              <button @click="handleAlignCenterH" title="Align Center H"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="4" x2="12" y2="20" /><rect x="4" y="6" width="16" height="4" rx="1" /><rect x="6" y="14" width="12" height="4" rx="1" /></svg> Center H</button>
              <button @click="handleAlignRight" title="Align Right"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="20" y1="4" x2="20" y2="20" /><rect x="4" y="6" width="12" height="4" rx="1" /><rect x="8" y="14" width="8" height="4" rx="1" /></svg> Right</button>
              <button @click="handleAlignTop" title="Align Top"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="4" x2="20" y2="4" /><rect x="6" y="8" width="4" height="12" rx="1" /><rect x="14" y="8" width="4" height="8" rx="1" /></svg> Top</button>
              <button @click="handleAlignCenterV" title="Align Center V"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="12" x2="20" y2="12" /><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="6" width="4" height="12" rx="1" /></svg> Center V</button>
              <button @click="handleAlignBottom" title="Align Bottom"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="20" x2="20" y2="20" /><rect x="6" y="4" width="4" height="12" rx="1" /><rect x="14" y="8" width="4" height="8" rx="1" /></svg> Bottom</button>
            </div>
            <div class="align-menu-divider" />
            <div class="align-menu-section">
              <span class="menu-section-title">Distribute</span>
              <button @click="handleDistributeH" :disabled="!hasThreeOrMoreSelected" title="Distribute Horizontally (3+ items)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="8" width="4" height="8" rx="1" /><rect x="10" y="8" width="4" height="8" rx="1" /><rect x="18" y="8" width="4" height="8" rx="1" /></svg> Horizontal</button>
              <button @click="handleDistributeV" :disabled="!hasThreeOrMoreSelected" title="Distribute Vertically (3+ items)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="2" width="8" height="4" rx="1" /><rect x="8" y="10" width="8" height="4" rx="1" /><rect x="8" y="18" width="8" height="4" rx="1" /></svg> Vertical</button>
            </div>
          </div>
        </div>
        <button class="btn-tool" :disabled="!hasMultipleSelected" @click="handleGroup" title="Group (Ctrl+G)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="8" height="8" rx="1" /><rect x="13" y="3" width="8" height="8" rx="1" /><rect x="3" y="13" width="8" height="8" rx="1" /><rect x="13" y="13" width="8" height="8" rx="1" /><path d="M7 11v2M17 11v2M11 7h2M11 17h2" stroke-dasharray="2,2" />
          </svg>
        </button>
        <button class="btn-tool" :disabled="!store.hasPidSelection" @click="handleUngroup" title="Ungroup (Ctrl+Shift+G)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Panel Toggles (icon-only) -->
      <div class="toolbar-section">
        <button class="btn-panel-toggle" :class="{ active: store.pidSymbolPanelOpen && !store.pidSymbolPanelCollapsed }" @click="store.pidSymbolPanelOpen = !store.pidSymbolPanelOpen" title="Toggle Symbol Panel ([)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        </button>
        <button class="btn-panel-toggle" :class="{ active: store.pidPropertiesPanelOpen && !store.pidPropertiesPanelCollapsed }" @click="store.pidPropertiesPanelOpen = !store.pidPropertiesPanelOpen" title="Toggle Properties Panel (])">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="15" y1="3" x2="15" y2="21" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Pipe Drawing (compact: button + inline color, options in popover) -->
      <div class="toolbar-section pipe-section">
        <button class="btn-pipe" :class="{ active: store.pidDrawingMode }" @click="togglePipeDrawing" title="Draw Pipe (P)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 12h6l4-4 4 8 4-4h4" />
          </svg>
          {{ store.pidDrawingMode ? 'Drawing...' : 'Pipe' }}
        </button>
        <input type="color" v-model="pipeColor" class="color-picker" title="Pipe Color" @click.stop />
        <button v-if="store.pidDrawingMode" class="btn-tool" @click="pipeOptionsOpen = !pipeOptionsOpen" title="Pipe Options">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <!-- Pipe options popover -->
        <div v-if="pipeOptionsOpen && store.pidDrawingMode" class="pipe-popover">
          <label class="checkbox-label"><input type="checkbox" v-model="pipeDashed" /> Dashed</label>
          <label class="checkbox-label"><input type="checkbox" v-model="pipeAnimated" /> Flow</label>
          <label class="checkbox-label"><input type="checkbox" :checked="store.pidAutoRoute" @change="store.pidAutoRoute = !store.pidAutoRoute" /> Auto-Route</label>
        </div>
      </div>

      <div class="toolbar-divider" />

      <!-- Text Tool (icon-only) -->
      <div class="toolbar-section">
        <button class="btn-text" :class="{ active: textToolActive }" @click="toggleTextTool" title="Text Tool (T)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4 7 4 4 20 4 20 7" /><line x1="9" y1="20" x2="15" y2="20" /><line x1="12" y1="4" x2="12" y2="20" />
          </svg>
        </button>
        <button v-if="textToolActive" class="btn-add" @click="addTextAnnotation" title="Add Text Label">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- View Dropdown (replaces Grid/Rulers/Layers/ISA-101/Map) -->
      <div class="toolbar-section">
        <div class="view-dropdown">
          <button class="btn-tool" :class="{ active: viewMenuOpen }" @click="viewMenuOpen = !viewMenuOpen" title="View Options">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
            </svg>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9" /></svg>
          </button>
          <div v-if="viewMenuOpen" class="dropdown-menu">
            <button class="dropdown-item" @click="store.togglePidGridSnap()">
              <span class="dropdown-check">{{ store.pidGridSnapEnabled ? '\u2713' : '' }}</span>
              Grid Snap (G)
            </button>
            <div v-if="store.pidGridSnapEnabled" class="dropdown-sub">
              <select
                :value="store.pidGridSize"
                @change="store.setPidGridSize(Number(($event.target as HTMLSelectElement).value))"
                class="dropdown-select"
              >
                <option v-for="s in [5,10,15,20,25,30,40,50]" :key="s" :value="s">{{ s }}px</option>
              </select>
            </div>
            <button class="dropdown-item" @click="store.pidShowGrid = !store.pidShowGrid">
              <span class="dropdown-check">{{ store.pidShowGrid ? '\u2713' : '' }}</span>
              Show Grid
            </button>
            <button class="dropdown-item" @click="store.pidShowRulers = !store.pidShowRulers">
              <span class="dropdown-check">{{ store.pidShowRulers ? '\u2713' : '' }}</span>
              Rulers
            </button>
            <button class="dropdown-item" @click="store.pidShowMinimap = !store.pidShowMinimap">
              <span class="dropdown-check">{{ store.pidShowMinimap ? '\u2713' : '' }}</span>
              Minimap (M)
            </button>
            <button class="dropdown-item" @click="store.togglePidColorScheme()">
              <span class="dropdown-check">{{ store.pidColorScheme === 'isa101' ? '\u2713' : '' }}</span>
              ISA-101 Grayscale
            </button>
            <button class="dropdown-item" @click="store.pidShowNozzleStubs = !store.pidShowNozzleStubs">
              <span class="dropdown-check">{{ store.pidShowNozzleStubs ? '\u2713' : '' }}</span>
              Port Dots
            </button>
            <div class="dropdown-divider" />
            <button class="dropdown-item" @click="layerPanelOpen = !layerPanelOpen; viewMenuOpen = false">
              <span class="dropdown-check">{{ layerPanelOpen ? '\u2713' : '' }}</span>
              Layers Panel
            </button>
          </div>
        </div>
      </div>

      <div class="toolbar-divider" />

      <!-- Zoom Controls -->
      <div class="toolbar-section zoom-section">
        <button class="btn-tool" @click="store.setPidZoom(store.pidZoom - 0.1)" :disabled="store.pidZoom <= 0.1" title="Zoom Out">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" />
          </svg>
        </button>
        <span class="zoom-display" @click="store.pidResetZoom()" title="Click to reset to 100%">{{ Math.round(store.pidZoom * 100) }}%</span>
        <button class="btn-tool" @click="store.setPidZoom(store.pidZoom + 0.1)" :disabled="store.pidZoom >= 5" title="Zoom In">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" />
          </svg>
        </button>
        <button class="btn-tool" @click="fitToContent" title="Fit to Content (Ctrl+Shift+F)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- Focus Mode Toggle -->
      <div class="toolbar-section">
        <button class="btn-tool btn-focus" :class="{ active: store.pidFocusMode }" @click="store.togglePidFocusMode()" title="Focus Mode (\\) - Hide panels and chrome">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
        </button>
      </div>

      <div class="toolbar-divider" />

      <!-- More Dropdown (Background, Export, Clear) -->
      <div class="toolbar-section">
        <div class="more-dropdown">
          <button class="btn-tool" :class="{ active: moreMenuOpen }" @click="moreMenuOpen = !moreMenuOpen" title="More Actions">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="5" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="19" r="1" fill="currentColor" />
            </svg>
          </button>
          <div v-if="moreMenuOpen" class="dropdown-menu">
            <button class="dropdown-item" @click="importBackgroundImage(); moreMenuOpen = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              Background Image
            </button>
            <button v-if="store.pidLayer?.backgroundImage" class="dropdown-item dropdown-item-danger" @click="removeBackgroundImage(); moreMenuOpen = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              Remove Background
            </button>
            <div class="dropdown-divider" />
            <button class="dropdown-item" @click="exportAsSvg(); moreMenuOpen = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Export SVG
            </button>
            <div class="dropdown-divider" />
            <button class="dropdown-item dropdown-item-danger" @click="clearAll(); moreMenuOpen = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              Clear All
            </button>
          </div>
        </div>
      </div>

      <!-- Connection Validation (#5.2) -->
      <button
        class="btn-tool"
        :class="{ 'has-errors': validationErrors > 0, 'has-warnings': validationWarnings > 0 && validationErrors === 0 }"
        @click="showValidationPanel = !showValidationPanel"
        :title="`Validation: ${validationErrors} errors, ${validationWarnings} warnings`"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span v-if="validationIssues.length > 0" class="validation-badge">{{ validationIssues.length }}</span>
      </button>

      <!-- Help Tooltip -->
      <button class="btn-tool btn-help" :title="store.pidDrawingMode ? 'Click to add points, double-click to finish pipe' : 'P=Pipe T=Text G=Grid R=Rotate []=Panels \\\\=Focus'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </button>
    </template>

    <!-- Floating Layer Panel -->
    <div v-if="layerPanelOpen" class="layer-panel-float">
      <PidLayerPanel />
    </div>

    <!-- Symbol Search Overlay (#3.8) -->
    <div v-if="showSearchOverlay" class="search-overlay">
      <div class="search-box">
        <input
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Search symbols by label, type, or channel..."
          class="search-input"
          @keydown.enter="navigateSearch(1)"
          @keydown.escape="closeSearch"
          @keydown.up.prevent="navigateSearch(-1)"
          @keydown.down.prevent="navigateSearch(1)"
        />
        <span v-if="searchResults.length > 0" class="search-count">
          {{ searchIndex + 1 }} / {{ searchResults.length }}
        </span>
        <span v-else-if="searchQuery.trim()" class="search-count no-match">No matches</span>
        <button class="search-close" @click="closeSearch" title="Close (Esc)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Validation Issues Panel (#5.2) -->
    <div v-if="showValidationPanel" class="validation-panel">
      <div class="validation-header">
        <span>Connection Issues ({{ validationIssues.length }})</span>
        <button class="search-close" @click="showValidationPanel = false">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div class="validation-body">
        <div v-if="validationIssues.length === 0" class="validation-empty">No issues found</div>
        <div
          v-for="issue in validationIssues"
          :key="issue.id"
          class="validation-issue"
          :class="issue.severity"
          @click="navigateToIssue(issue)"
        >
          <span class="issue-icon">{{ issue.severity === 'error' ? '\u2716' : '\u26A0' }}</span>
          <span class="issue-text">{{ issue.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pid-toolbar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 12px;
  background: linear-gradient(to right, #1e3a5f, #2a4a6f);
  border-bottom: 1px solid #3b5998;
  flex-wrap: nowrap;
  position: relative;
}

.pid-toolbar.compact {
  padding: 4px 12px;
  gap: 6px;
  justify-content: flex-start;
}

.toolbar-section {
  display: flex;
  align-items: center;
  gap: 4px;
  position: relative;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-accent-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.toolbar-divider {
  width: 1px;
  height: 24px;
  background: #3b5998;
  flex-shrink: 0;
}

/* Base button style */
button {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-exit {
  background: #4a5568;
  color: var(--text-primary);
  padding: 6px 10px;
}

.btn-exit:hover {
  background: #718096;
}

.btn-pipe {
  background: var(--color-accent);
  color: var(--text-primary);
  padding: 6px 10px;
}

.btn-pipe:hover {
  background: var(--color-accent-dark);
}

.btn-pipe.active {
  background: #f59e0b;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Tool buttons (icon-only) */
.btn-tool {
  background: #4a5568;
  color: var(--text-primary);
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
  background: var(--color-error);
}

.btn-tool.active {
  background: #6366f1;
}

/* Focus mode button */
.btn-focus.active {
  background: #f59e0b;
}

/* Text tool */
.btn-text {
  background: #8b5cf6;
  color: var(--text-primary);
}

.btn-text:hover {
  background: #7c3aed;
}

.btn-text.active {
  background: #f59e0b;
  animation: pulse 1s infinite;
}

.btn-add {
  background: #10b981;
  color: var(--text-primary);
}

.btn-add:hover {
  background: #059669;
}

/* Panel toggle */
.btn-panel-toggle {
  background: #4a5568;
  color: var(--text-primary);
}

.btn-panel-toggle:hover {
  background: #718096;
}

.btn-panel-toggle.active {
  background: #6366f1;
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
  color: var(--text-primary);
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
  background: var(--bg-surface);
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
  color: var(--text-dim);
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
  color: var(--text-bright);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  border-radius: 0;
}

.align-menu button:hover:not(:disabled) {
  background: var(--bg-hover);
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

/* Dropdown menus (View, More) */
.view-dropdown,
.more-dropdown {
  position: relative;
}

.dropdown-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: var(--bg-surface);
  border: 1px solid #3b5998;
  border-radius: 6px;
  padding: 4px 0;
  min-width: 180px;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.more-dropdown .dropdown-menu {
  left: auto;
  right: 0;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 12px;
  background: transparent;
  border: none;
  color: var(--text-bright);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  border-radius: 0;
}

.dropdown-item:hover {
  background: var(--bg-hover);
}

.dropdown-item-danger {
  color: var(--color-error-light);
}

.dropdown-item-danger:hover {
  background: #7f1d1d;
}

.dropdown-check {
  width: 16px;
  text-align: center;
  color: #10b981;
  font-weight: 700;
}

.dropdown-divider {
  height: 1px;
  background: #3b5998;
  margin: 4px 0;
}

.dropdown-sub {
  padding: 2px 0;
}

.dropdown-select {
  margin: 0 12px 4px;
  padding: 3px 6px;
  background: #2d3748;
  border: 1px solid #3b5998;
  border-radius: 3px;
  color: var(--text-primary);
  font-size: 11px;
  width: calc(100% - 24px);
}

/* Pipe section */
.pipe-section {
  position: relative;
}

.pipe-popover {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: var(--bg-surface);
  border: 1px solid #3b5998;
  border-radius: 6px;
  padding: 8px 12px;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 130px;
}

/* Inputs */
.color-picker {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  flex-shrink: 0;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #aaa;
  cursor: pointer;
  white-space: nowrap;
}

.checkbox-label input {
  margin: 0;
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
  color: var(--color-accent-light);
  min-width: 40px;
  text-align: center;
  cursor: pointer;
  user-select: none;
}

.zoom-display:hover {
  color: #93c5fd;
}

/* Help button */
.btn-help {
  opacity: 0.5;
}

.btn-help:hover {
  opacity: 1;
}

/* Layer panel float */
.layer-panel-float {
  position: absolute;
  right: 0;
  top: 100%;
  margin-top: 4px;
  z-index: 100;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  border-radius: 6px;
}

/* Symbol search overlay (#3.8) */
.search-overlay {
  position: fixed;
  top: 80px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 200;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-widget);
  border: 1px solid var(--color-accent);
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  min-width: 380px;
}

.search-box .search-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-bright);
  font-size: 14px;
  outline: none;
}

.search-box .search-input::placeholder {
  color: #555;
}

.search-count {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
}

.search-count.no-match {
  color: var(--color-error);
}

.search-close {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.search-close:hover {
  color: var(--text-bright);
}

/* Validation (#5.2) */
.btn-tool.has-errors { color: var(--color-error); }
.btn-tool.has-warnings { color: #eab308; }

.validation-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 14px;
  height: 14px;
  background: var(--color-error);
  color: var(--text-primary);
  font-size: 9px;
  font-weight: 700;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
}

.validation-panel {
  position: absolute;
  top: 100%;
  right: 40px;
  width: 340px;
  max-height: 300px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 100;
  display: flex;
  flex-direction: column;
}

.validation-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.validation-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.validation-empty {
  padding: 16px;
  text-align: center;
  color: var(--color-success);
  font-size: 12px;
}

.validation-issue {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-secondary);
}

.validation-issue:hover {
  background: var(--color-accent-bg);
}

.validation-issue.error .issue-icon { color: var(--color-error); }
.validation-issue.warning .issue-icon { color: #eab308; }

.issue-icon { flex-shrink: 0; }
.issue-text { line-height: 1.3; }
</style>
