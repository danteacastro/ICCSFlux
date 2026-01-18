<script setup lang="ts">
/**
 * PidCanvas - Free-Form P&ID Drawing Layer
 *
 * A separate canvas layer for P&ID diagrams that sits alongside the grid.
 * Unlike the grid-based widgets, everything here uses pixel coordinates
 * for true free-form placement and sizing.
 *
 * Features:
 * - Drag symbols to any position (no grid snapping)
 * - Resize symbols by dragging corners
 * - Free-form pipe drawing (click to add points anywhere)
 * - Bezier, polyline, or orthogonal pipe paths
 * - Rotation at any angle
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, type ScadaSymbolType } from '../assets/symbols'
import type { PidSymbol, PidPipe, PidPoint, PidLayerData } from '../types'

const props = withDefaults(defineProps<{
  pidLayer: PidLayerData
  editMode?: boolean
  pipeDrawingMode?: boolean
}>(), {
  editMode: false,
  pipeDrawingMode: false
})

const emit = defineEmits<{
  (e: 'update:pidLayer', layer: PidLayerData): void
  (e: 'select:symbol', id: string | null): void
  (e: 'select:pipe', id: string | null): void
}>()

const store = useDashboardStore()

// Selection state
const selectedSymbolId = ref<string | null>(null)
const selectedPipeId = ref<string | null>(null)

// Dragging state
const isDragging = ref(false)
const dragStart = ref<{ x: number; y: number; symbolX: number; symbolY: number } | null>(null)

// Resizing state
const isResizing = ref(false)
const resizeHandle = ref<'nw' | 'ne' | 'sw' | 'se' | null>(null)
const resizeStart = ref<{ x: number; y: number; width: number; height: number; symbolX: number; symbolY: number } | null>(null)

// Pipe drawing state
const isDrawingPipe = ref(false)
const currentPipePoints = ref<PidPoint[]>([])
const tempMousePos = ref<PidPoint | null>(null)

// Canvas ref for coordinate calculations
const canvasRef = ref<HTMLElement | null>(null)

// Symbol configuration modal state
const showConfigModal = ref(false)
const configSymbol = ref<PidSymbol | null>(null)
const configForm = ref({
  label: '',
  channel: '',
  showValue: false,
  decimals: 1,
  color: '#60a5fa',
  rotation: 0
})

// Available channels for binding
const availableChannels = computed(() => {
  return Object.entries(store.channels).map(([name, ch]) => ({
    name,
    unit: ch.unit || '',
    type: ch.channel_type
  }))
})

// Open symbol config modal
function openSymbolConfig(symbol: PidSymbol) {
  configSymbol.value = symbol
  configForm.value = {
    label: symbol.label || '',
    channel: symbol.channel || '',
    showValue: symbol.showValue || false,
    decimals: symbol.decimals ?? 1,
    color: symbol.color || '#60a5fa',
    rotation: symbol.rotation || 0
  }
  showConfigModal.value = true
}

// Save symbol config
function saveSymbolConfig() {
  if (!configSymbol.value) return

  const newSymbols = props.pidLayer.symbols.map(s =>
    s.id === configSymbol.value!.id
      ? {
          ...s,
          label: configForm.value.label || undefined,
          channel: configForm.value.channel || undefined,
          showValue: configForm.value.showValue,
          decimals: configForm.value.decimals,
          color: configForm.value.color,
          rotation: configForm.value.rotation
        }
      : s
  )

  emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
  showConfigModal.value = false
  configSymbol.value = null
}

// Handle symbol double-click for config
function onSymbolDoubleClick(event: MouseEvent, symbol: PidSymbol) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()
  openSymbolConfig(symbol)
}

// Get canvas-relative coordinates from mouse event
function getCanvasCoords(event: MouseEvent): PidPoint {
  if (!canvasRef.value) return { x: 0, y: 0 }
  const rect = canvasRef.value.getBoundingClientRect()
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  }
}

// Symbol rendering
function getSymbolSvg(type: string): string {
  return SCADA_SYMBOLS[type as ScadaSymbolType] || SCADA_SYMBOLS.solenoidValve
}

function getSymbolStyle(symbol: PidSymbol): Record<string, string> {
  return {
    left: `${symbol.x}px`,
    top: `${symbol.y}px`,
    width: `${symbol.width}px`,
    height: `${symbol.height}px`,
    transform: symbol.rotation ? `rotate(${symbol.rotation}deg)` : undefined,
    zIndex: String(symbol.zIndex || 1)
  } as Record<string, string>
}

// Get channel value for symbol
function getSymbolValue(symbol: PidSymbol): string {
  if (!symbol.channel) return ''
  const value = store.values[symbol.channel]
  if (!value) return '--'
  const dec = symbol.decimals ?? 1
  return typeof value.value === 'number' ? value.value.toFixed(dec) : String(value.value)
}

// Symbol selection
function onSymbolMouseDown(event: MouseEvent, symbol: PidSymbol) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  // Check if clicking a resize handle
  const target = event.target as HTMLElement
  if (target.classList.contains('resize-handle')) {
    // Handle resize
    const handle = target.dataset.handle as 'nw' | 'ne' | 'sw' | 'se'
    startResize(event, symbol, handle)
    return
  }

  // Start drag
  selectedSymbolId.value = symbol.id
  selectedPipeId.value = null
  emit('select:symbol', symbol.id)
  emit('select:pipe', null)

  isDragging.value = true
  const coords = getCanvasCoords(event)
  dragStart.value = {
    x: coords.x,
    y: coords.y,
    symbolX: symbol.x,
    symbolY: symbol.y
  }

  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}

function onDragMove(event: MouseEvent) {
  if (!isDragging.value || !dragStart.value || !selectedSymbolId.value) return

  const coords = getCanvasCoords(event)
  const dx = coords.x - dragStart.value.x
  const dy = coords.y - dragStart.value.y

  // Update symbol position (free-form, no snapping)
  const newSymbols = props.pidLayer.symbols.map(s =>
    s.id === selectedSymbolId.value
      ? { ...s, x: Math.max(0, dragStart.value!.symbolX + dx), y: Math.max(0, dragStart.value!.symbolY + dy) }
      : s
  )

  emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
}

function onDragEnd() {
  isDragging.value = false
  dragStart.value = null
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
}

// Resize handling
function startResize(event: MouseEvent, symbol: PidSymbol, handle: 'nw' | 'ne' | 'sw' | 'se') {
  event.preventDefault()
  event.stopPropagation()

  isResizing.value = true
  resizeHandle.value = handle
  const coords = getCanvasCoords(event)
  resizeStart.value = {
    x: coords.x,
    y: coords.y,
    width: symbol.width,
    height: symbol.height,
    symbolX: symbol.x,
    symbolY: symbol.y
  }

  selectedSymbolId.value = symbol.id
  emit('select:symbol', symbol.id)

  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', onResizeEnd)
}

function onResizeMove(event: MouseEvent) {
  if (!isResizing.value || !resizeStart.value || !selectedSymbolId.value || !resizeHandle.value) return

  const coords = getCanvasCoords(event)
  const dx = coords.x - resizeStart.value.x
  const dy = coords.y - resizeStart.value.y

  let newWidth = resizeStart.value.width
  let newHeight = resizeStart.value.height
  let newX = resizeStart.value.symbolX
  let newY = resizeStart.value.symbolY

  // Calculate new dimensions based on which handle is being dragged
  switch (resizeHandle.value) {
    case 'se':
      newWidth = Math.max(20, resizeStart.value.width + dx)
      newHeight = Math.max(20, resizeStart.value.height + dy)
      break
    case 'sw':
      newWidth = Math.max(20, resizeStart.value.width - dx)
      newHeight = Math.max(20, resizeStart.value.height + dy)
      newX = resizeStart.value.symbolX + (resizeStart.value.width - newWidth)
      break
    case 'ne':
      newWidth = Math.max(20, resizeStart.value.width + dx)
      newHeight = Math.max(20, resizeStart.value.height - dy)
      newY = resizeStart.value.symbolY + (resizeStart.value.height - newHeight)
      break
    case 'nw':
      newWidth = Math.max(20, resizeStart.value.width - dx)
      newHeight = Math.max(20, resizeStart.value.height - dy)
      newX = resizeStart.value.symbolX + (resizeStart.value.width - newWidth)
      newY = resizeStart.value.symbolY + (resizeStart.value.height - newHeight)
      break
  }

  // Update symbol
  const newSymbols = props.pidLayer.symbols.map(s =>
    s.id === selectedSymbolId.value
      ? { ...s, x: newX, y: newY, width: newWidth, height: newHeight }
      : s
  )

  emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
}

function onResizeEnd() {
  isResizing.value = false
  resizeHandle.value = null
  resizeStart.value = null
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', onResizeEnd)
}

// Pipe drawing
function onCanvasClick(event: MouseEvent) {
  if (!props.editMode) return

  // If clicking on empty space, deselect
  if (event.target === canvasRef.value) {
    if (!props.pipeDrawingMode) {
      selectedSymbolId.value = null
      selectedPipeId.value = null
      emit('select:symbol', null)
      emit('select:pipe', null)
    }
  }

  // Handle pipe drawing mode
  if (props.pipeDrawingMode) {
    const coords = getCanvasCoords(event)

    if (!isDrawingPipe.value) {
      // Start new pipe
      isDrawingPipe.value = true
      currentPipePoints.value = [coords]
    } else {
      // Add point to current pipe
      currentPipePoints.value.push(coords)
    }
  }
}

function onCanvasDoubleClick(event: MouseEvent) {
  if (!props.pipeDrawingMode || !isDrawingPipe.value) return

  // Finish pipe drawing
  if (currentPipePoints.value.length >= 2) {
    const newPipe: PidPipe = {
      id: `pipe-${Date.now()}`,
      points: [...currentPipePoints.value],
      pathType: 'polyline',
      color: '#60a5fa',
      strokeWidth: 3
    }

    emit('update:pidLayer', {
      ...props.pidLayer,
      pipes: [...props.pidLayer.pipes, newPipe]
    })
  }

  // Reset drawing state
  isDrawingPipe.value = false
  currentPipePoints.value = []
  tempMousePos.value = null
}

function onCanvasMouseMove(event: MouseEvent) {
  if (props.pipeDrawingMode && isDrawingPipe.value) {
    tempMousePos.value = getCanvasCoords(event)
  }
}

function onCanvasKeyDown(event: KeyboardEvent) {
  if (!props.editMode) return

  // Escape cancels pipe drawing
  if (event.key === 'Escape' && isDrawingPipe.value) {
    isDrawingPipe.value = false
    currentPipePoints.value = []
    tempMousePos.value = null
    return
  }

  // Delete selected element
  if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedSymbolId.value || selectedPipeId.value)) {
    if (selectedSymbolId.value) {
      const newSymbols = props.pidLayer.symbols.filter(s => s.id !== selectedSymbolId.value)
      emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
      selectedSymbolId.value = null
      emit('select:symbol', null)
    } else if (selectedPipeId.value) {
      const newPipes = props.pidLayer.pipes.filter(p => p.id !== selectedPipeId.value)
      emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
      selectedPipeId.value = null
      emit('select:pipe', null)
    }
  }
}

// Generate SVG path for pipe
function generatePipePath(pipe: PidPipe): string {
  if (pipe.points.length < 2) return ''

  const first = pipe.points[0]!
  let path = `M ${first.x} ${first.y}`

  if (pipe.pathType === 'bezier' && pipe.points.length >= 3) {
    // Smooth bezier curve through points
    for (let i = 1; i < pipe.points.length - 1; i++) {
      const p0 = pipe.points[i - 1]!
      const p1 = pipe.points[i]!
      const p2 = pipe.points[i + 1]!
      const cx2 = (p1.x + p2.x) / 2
      const cy2 = (p1.y + p2.y) / 2
      path += ` Q ${p1.x} ${p1.y} ${cx2} ${cy2}`
    }
    const last = pipe.points[pipe.points.length - 1]!
    path += ` L ${last.x} ${last.y}`
  } else if (pipe.pathType === 'orthogonal') {
    // Right-angle routing
    for (let i = 1; i < pipe.points.length; i++) {
      const prev = pipe.points[i - 1]!
      const curr = pipe.points[i]!
      if (prev.x !== curr.x && prev.y !== curr.y) {
        path += ` L ${curr.x} ${prev.y}`
      }
      path += ` L ${curr.x} ${curr.y}`
    }
  } else {
    // Polyline (straight segments)
    for (let i = 1; i < pipe.points.length; i++) {
      const p = pipe.points[i]!
      path += ` L ${p.x} ${p.y}`
    }
  }

  return path
}

// Get current drawing path (preview)
const currentDrawingPath = computed(() => {
  if (!isDrawingPipe.value || currentPipePoints.value.length === 0) return ''

  const points = [...currentPipePoints.value]
  if (tempMousePos.value) {
    points.push(tempMousePos.value)
  }

  if (points.length < 2) return ''

  const first = points[0]!
  let path = `M ${first.x} ${first.y}`
  for (let i = 1; i < points.length; i++) {
    path += ` L ${points[i]!.x} ${points[i]!.y}`
  }
  return path
})

// Pipe selection and segment dragging
const draggingSegment = ref<{
  pipeId: string
  segmentIndex: number  // index of first point in segment
  orientation: 'horizontal' | 'vertical'
  startY: number
  startX: number
  originalPoints: PidPoint[]
} | null>(null)

function onPipeMouseDown(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  // Select the pipe
  selectedPipeId.value = pipe.id
  selectedSymbolId.value = null
  emit('select:pipe', pipe.id)
  emit('select:symbol', null)

  // Find which segment was clicked
  const coords = getCanvasCoords(event)
  let closestSegment = 0
  let minDist = Infinity

  for (let i = 0; i < pipe.points.length - 1; i++) {
    const p1 = pipe.points[i]!
    const p2 = pipe.points[i + 1]!
    const dist = distanceToSegment(coords.x, coords.y, p1.x, p1.y, p2.x, p2.y)
    if (dist < minDist) {
      minDist = dist
      closestSegment = i
    }
  }

  // Determine segment orientation (horizontal if dx > dy, vertical otherwise)
  const p1 = pipe.points[closestSegment]!
  const p2 = pipe.points[closestSegment + 1]!
  const dx = Math.abs(p2.x - p1.x)
  const dy = Math.abs(p2.y - p1.y)
  const orientation = dx > dy ? 'horizontal' : 'vertical'

  draggingSegment.value = {
    pipeId: pipe.id,
    segmentIndex: closestSegment,
    orientation,
    startX: coords.x,
    startY: coords.y,
    originalPoints: pipe.points.map(p => ({ ...p }))
  }

  window.addEventListener('mousemove', onSegmentMove)
  window.addEventListener('mouseup', onSegmentEnd)
}

function onSegmentMove(event: MouseEvent) {
  if (!draggingSegment.value) return

  const coords = getCanvasCoords(event)
  const { pipeId, segmentIndex, orientation, startX, startY, originalPoints } = draggingSegment.value

  // Calculate delta perpendicular to segment orientation
  let deltaX = 0
  let deltaY = 0

  if (orientation === 'horizontal') {
    // Horizontal segment - shift up/down
    deltaY = coords.y - startY
  } else {
    // Vertical segment - shift left/right
    deltaX = coords.x - startX
  }

  // Move both points of this segment
  const newPoints = originalPoints.map((p, i) => {
    if (i === segmentIndex || i === segmentIndex + 1) {
      return {
        x: p.x + deltaX,
        y: p.y + deltaY
      }
    }
    return { ...p }
  })

  const newPipes = props.pidLayer.pipes.map(p =>
    p.id === pipeId ? { ...p, points: newPoints } : p
  )

  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
}

function onSegmentEnd() {
  draggingSegment.value = null
  window.removeEventListener('mousemove', onSegmentMove)
  window.removeEventListener('mouseup', onSegmentEnd)
}

// Legacy click handler (for selection only when not dragging)
function onPipeClick(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  event.stopPropagation()

  selectedPipeId.value = pipe.id
  selectedSymbolId.value = null
  emit('select:pipe', pipe.id)
  emit('select:symbol', null)
}

// Pipe point dragging
const draggingPipePoint = ref<{ pipeId: string; pointIndex: number } | null>(null)

function onPipePointMouseDown(event: MouseEvent, pipeId: string, pointIndex: number) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  draggingPipePoint.value = { pipeId, pointIndex }
  window.addEventListener('mousemove', onPipePointMove)
  window.addEventListener('mouseup', onPipePointEnd)
}

// Right-click to delete a pipe point
function onPipePointRightClick(event: MouseEvent, pipeId: string, pointIndex: number) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  const pipe = props.pidLayer.pipes.find(p => p.id === pipeId)
  if (!pipe) return

  // Don't allow deleting if only 2 points remain (minimum for a pipe)
  if (pipe.points.length <= 2) return

  // Remove the point
  const newPoints = pipe.points.filter((_, i) => i !== pointIndex)
  const newPipes = props.pidLayer.pipes.map(p =>
    p.id === pipeId ? { ...p, points: newPoints } : p
  )

  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
}

function onPipePointMove(event: MouseEvent) {
  if (!draggingPipePoint.value) return

  const coords = getCanvasCoords(event)
  const newPipes = props.pidLayer.pipes.map(pipe => {
    if (pipe.id !== draggingPipePoint.value!.pipeId) return pipe
    const newPoints = pipe.points.map((p, i) =>
      i === draggingPipePoint.value!.pointIndex ? coords : p
    )
    return { ...pipe, points: newPoints }
  })

  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
}

function onPipePointEnd() {
  draggingPipePoint.value = null
  window.removeEventListener('mousemove', onPipePointMove)
  window.removeEventListener('mouseup', onPipePointEnd)
}

// Add point to existing pipe by double-clicking on segment
function onPipeDoubleClick(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  const coords = getCanvasCoords(event)

  // Find which segment was clicked
  let insertIndex = 1
  let minDist = Infinity

  for (let i = 0; i < pipe.points.length - 1; i++) {
    const p1 = pipe.points[i]!
    const p2 = pipe.points[i + 1]!
    const dist = distanceToSegment(coords.x, coords.y, p1.x, p1.y, p2.x, p2.y)
    if (dist < minDist) {
      minDist = dist
      insertIndex = i + 1
    }
  }

  // Insert new point
  const newPoints = [...pipe.points]
  newPoints.splice(insertIndex, 0, coords)

  const newPipes = props.pidLayer.pipes.map(p =>
    p.id === pipe.id ? { ...p, points: newPoints } : p
  )

  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
}

function distanceToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const A = px - x1
  const B = py - y1
  const C = x2 - x1
  const D = y2 - y1
  const dot = A * C + B * D
  const lenSq = C * C + D * D
  let param = lenSq !== 0 ? dot / lenSq : -1

  let xx, yy
  if (param < 0) { xx = x1; yy = y1 }
  else if (param > 1) { xx = x2; yy = y2 }
  else { xx = x1 + param * C; yy = y1 + param * D }

  return Math.sqrt((px - xx) ** 2 + (py - yy) ** 2)
}
</script>

<template>
  <div
    ref="canvasRef"
    class="pid-canvas"
    :class="{ 'edit-mode': editMode, 'drawing-mode': pipeDrawingMode }"
    tabindex="0"
    @click="onCanvasClick"
    @dblclick="onCanvasDoubleClick"
    @mousemove="onCanvasMouseMove"
    @keydown="onCanvasKeyDown"
  >
    <!-- Pipes (SVG layer) -->
    <svg class="pipes-layer">
      <!-- Existing pipes -->
      <g v-for="pipe in pidLayer.pipes" :key="pipe.id" class="pipe-group">
        <!-- Wider invisible hit area for easier clicking -->
        <path
          :d="generatePipePath(pipe)"
          stroke="transparent"
          stroke-width="12"
          fill="none"
          class="pipe-hit-area"
          @mousedown.stop="onPipeMouseDown($event, pipe)"
          @dblclick.stop="onPipeDoubleClick($event, pipe)"
        />
        <!-- Visible pipe -->
        <path
          :d="generatePipePath(pipe)"
          :stroke="pipe.color || '#60a5fa'"
          :stroke-width="pipe.strokeWidth || 3"
          :stroke-dasharray="pipe.dashed ? '8,4' : undefined"
          stroke-linecap="round"
          stroke-linejoin="round"
          fill="none"
          class="pipe-path"
          :class="{ selected: selectedPipeId === pipe.id, dragging: draggingSegment?.pipeId === pipe.id }"
          pointer-events="none"
        />

        <!-- Flow animation -->
        <path
          v-if="pipe.animated"
          :d="generatePipePath(pipe)"
          stroke="rgba(255,255,255,0.5)"
          :stroke-width="(pipe.strokeWidth || 3) - 1"
          stroke-dasharray="4,12"
          fill="none"
          class="pipe-flow-animation"
        />

        <!-- Pipe points (edit mode only) -->
        <g v-if="editMode && selectedPipeId === pipe.id" class="pipe-points">
          <circle
            v-for="(point, idx) in pipe.points"
            :key="idx"
            :cx="point.x"
            :cy="point.y"
            r="6"
            class="pipe-point"
            :class="{ 'first': idx === 0, 'last': idx === pipe.points.length - 1 }"
            @mousedown="onPipePointMouseDown($event, pipe.id, idx)"
            @contextmenu.prevent="onPipePointRightClick($event, pipe.id, idx)"
          />
        </g>
      </g>

      <!-- Current drawing preview -->
      <path
        v-if="isDrawingPipe && currentDrawingPath"
        :d="currentDrawingPath"
        stroke="#60a5fa"
        stroke-width="3"
        stroke-dasharray="4,4"
        stroke-linecap="round"
        fill="none"
        class="drawing-preview"
      />

      <!-- Drawing points -->
      <g v-if="isDrawingPipe">
        <circle
          v-for="(point, idx) in currentPipePoints"
          :key="idx"
          :cx="point.x"
          :cy="point.y"
          r="5"
          fill="#22c55e"
          stroke="#fff"
          stroke-width="2"
        />
      </g>
    </svg>

    <!-- Symbols (positioned divs) -->
    <div
      v-for="symbol in pidLayer.symbols"
      :key="symbol.id"
      class="pid-symbol"
      :class="{ selected: selectedSymbolId === symbol.id }"
      :style="getSymbolStyle(symbol)"
      @mousedown="onSymbolMouseDown($event, symbol)"
      @dblclick="onSymbolDoubleClick($event, symbol)"
    >
      <!-- Symbol SVG -->
      <div
        class="symbol-svg"
        :style="{ color: symbol.color || '#60a5fa' }"
        v-html="getSymbolSvg(symbol.type)"
      />

      <!-- Label -->
      <div v-if="symbol.label" class="symbol-label">{{ symbol.label }}</div>

      <!-- Value -->
      <div v-if="symbol.showValue && symbol.channel" class="symbol-value">
        {{ getSymbolValue(symbol) }}
      </div>

    </div>

    <!-- Drawing mode indicator -->
    <div v-if="pipeDrawingMode" class="drawing-indicator">
      <span v-if="!isDrawingPipe">Click to start pipe</span>
      <span v-else>Click to add bend, double-click to finish (Esc to cancel)</span>
    </div>

    <!-- Edit mode help -->
    <div v-if="editMode && !pipeDrawingMode && selectedPipeId" class="edit-indicator">
      <span>Drag segment to shift • Right-click point to delete • Del to remove pipe</span>
    </div>

    <!-- Symbol Configuration Modal -->
    <Teleport to="body">
      <div v-if="showConfigModal" class="modal-overlay" @click.self="showConfigModal = false">
        <div class="symbol-config-modal">
          <h3>Configure Symbol</h3>

          <div class="config-form">
            <div class="form-group">
              <label>Label</label>
              <input
                v-model="configForm.label"
                type="text"
                placeholder="e.g., SOV-101"
                class="form-input"
              />
            </div>

            <div class="form-group">
              <label>Bind to Channel</label>
              <select v-model="configForm.channel" class="form-select">
                <option value="">-- None --</option>
                <option v-for="ch in availableChannels" :key="ch.name" :value="ch.name">
                  {{ ch.name }} ({{ ch.unit || ch.type }})
                </option>
              </select>
            </div>

            <div class="form-group form-row">
              <label class="checkbox-label">
                <input type="checkbox" v-model="configForm.showValue" />
                Show Value
              </label>
            </div>

            <div class="form-group" v-if="configForm.showValue">
              <label>Decimals</label>
              <input
                v-model.number="configForm.decimals"
                type="number"
                min="0"
                max="6"
                class="form-input small"
              />
            </div>

            <div class="form-group">
              <label>Color</label>
              <input
                v-model="configForm.color"
                type="color"
                class="form-color"
              />
            </div>

            <div class="form-group">
              <label>Rotation</label>
              <select v-model.number="configForm.rotation" class="form-select">
                <option :value="0">0°</option>
                <option :value="90">90°</option>
                <option :value="180">180°</option>
                <option :value="270">270°</option>
              </select>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showConfigModal = false">Cancel</button>
            <button class="btn btn-primary" @click="saveSymbolConfig">Save</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.pid-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  outline: none;
}

.pid-canvas.edit-mode {
  pointer-events: auto;
}

.pid-canvas.drawing-mode {
  cursor: crosshair;
}

.pipes-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}

.edit-mode .pipes-layer .pipe-hit-area,
.edit-mode .pipes-layer .pipe-point {
  pointer-events: auto;
}

.pipe-hit-area {
  cursor: grab;
}

.pipe-hit-area:active {
  cursor: grabbing;
}

.pipe-path {
  transition: stroke-width 0.15s, filter 0.15s;
}

.pipe-group:hover .pipe-path {
  stroke-width: 5;
  filter: drop-shadow(0 0 3px rgba(96, 165, 250, 0.5));
}

.pipe-path.selected {
  stroke-width: 5;
  filter: drop-shadow(0 0 6px currentColor);
}

.pipe-path.dragging {
  stroke-width: 6;
  filter: drop-shadow(0 0 8px #22c55e);
}

.pipe-flow-animation {
  animation: flow 1s linear infinite;
  pointer-events: none;
}

@keyframes flow {
  0% { stroke-dashoffset: 16; }
  100% { stroke-dashoffset: 0; }
}

.pipe-point {
  fill: #3b82f6;
  stroke: #fff;
  stroke-width: 2;
  cursor: grab;
  transition: r 0.15s;
}

.pipe-point:hover {
  r: 8;
}

.pipe-point.first,
.pipe-point.last {
  fill: #22c55e;
}

.drawing-preview {
  pointer-events: none;
}

.edit-indicator {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(34, 197, 94, 0.9);
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: none;
}

/* P&ID Symbols */
.pid-symbol {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: default;
  pointer-events: none;
  transition: box-shadow 0.15s;
}

/* Only interactive in edit mode */
.edit-mode .pid-symbol {
  cursor: move;
  pointer-events: auto;
}

.edit-mode .pid-symbol.selected {
  outline: 2px dashed #3b82f6;
  outline-offset: 4px;
}

.symbol-svg {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.symbol-svg :deep(svg) {
  width: 100%;
  height: 100%;
}

.symbol-label {
  position: absolute;
  bottom: -18px;
  font-size: 10px;
  color: #888;
  white-space: nowrap;
}

.symbol-value {
  position: absolute;
  top: -20px;
  font-size: 11px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
  background: rgba(0, 0, 0, 0.7);
  padding: 2px 6px;
  border-radius: 3px;
}

/* Resize handles */
.resize-handle {
  position: absolute;
  width: 10px;
  height: 10px;
  background: #3b82f6;
  border: 2px solid #fff;
  border-radius: 2px;
  z-index: 100;
}

.resize-handle.nw { top: -5px; left: -5px; cursor: nw-resize; }
.resize-handle.ne { top: -5px; right: -5px; cursor: ne-resize; }
.resize-handle.sw { bottom: -5px; left: -5px; cursor: sw-resize; }
.resize-handle.se { bottom: -5px; right: -5px; cursor: se-resize; }

.resize-handle:hover {
  background: #60a5fa;
  transform: scale(1.2);
}

/* Drawing indicator */
.drawing-indicator {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(59, 130, 246, 0.9);
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: none;
}

/* Symbol Configuration Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.symbol-config-modal {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 20px;
  min-width: 320px;
  max-width: 400px;
}

.symbol-config-modal h3 {
  margin: 0 0 16px;
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
}

.config-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group label {
  font-size: 0.8rem;
  color: #888;
}

.form-input,
.form-select {
  padding: 8px 10px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
}

.form-input:focus,
.form-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.form-input.small {
  width: 80px;
}

.form-color {
  width: 50px;
  height: 32px;
  padding: 2px;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  cursor: pointer;
}

.form-row {
  flex-direction: row;
  align-items: center;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: #ccc;
  cursor: pointer;
}

.checkbox-label input {
  margin: 0;
}

.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover {
  background: #4b5563;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}
</style>
