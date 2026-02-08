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

import { ref, computed, onMounted, onUnmounted, nextTick, watchEffect } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, SYMBOL_PORTS, SYMBOL_INFO, NOZZLE_STUB_CATEGORIES, OFF_PAGE_CONNECTOR_TYPES, getPortPosition, type ScadaSymbolType } from '../assets/symbols'
import { autoRoute } from '../utils/autoRoute'
import type { PidSymbol, PidPipe, PidPoint, PidLayerData, PidPipeConnection, PidTextAnnotation, PidArrowType } from '../types'
import PidFaceplate from './PidFaceplate.vue'
import PidContextMenu from './PidContextMenu.vue'
import type { MenuTarget } from './PidContextMenu.vue'
import { isHmiControl, getHmiDefaultSize } from '../constants/hmiControls'
import { getHmiComponent } from './hmi/index'

// Snap threshold in pixels (base value, adjusted by zoom)
const SNAP_THRESHOLD_BASE = 15
const SNAP_THRESHOLD = computed(() => SNAP_THRESHOLD_BASE / zoom.value)

// Grid snap settings (from store)
const gridSnapEnabled = computed(() => store.pidGridSnapEnabled)
const gridSize = computed(() => store.pidGridSize)
const showGrid = computed(() => store.pidShowGrid)
const orthogonalPipes = computed(() => store.pidOrthogonalPipes)

// Zoom/Pan (edit-mode only)
const zoom = computed(() => props.editMode ? store.pidZoom : 1)
const panX = computed(() => props.editMode ? store.pidPanX : 0)
const panY = computed(() => props.editMode ? store.pidPanY : 0)

// Panning state
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0, panX: 0, panY: 0 })
const spaceHeld = ref(false)

// Alignment guides
interface AlignmentGuide {
  axis: 'h' | 'v'        // horizontal or vertical line
  pos: number             // y for horizontal, x for vertical
  from: number            // start extent
  to: number              // end extent
}
const activeGuides = ref<AlignmentGuide[]>([])

// Minimap
const showMinimap = computed(() => store.pidShowMinimap)

const minimapBounds = computed(() => {
  let minX = 0, minY = 0, maxX = 1000, maxY = 800
  for (const sym of props.pidLayer.symbols) {
    minX = Math.min(minX, sym.x)
    minY = Math.min(minY, sym.y)
    maxX = Math.max(maxX, sym.x + sym.width)
    maxY = Math.max(maxY, sym.y + sym.height)
  }
  for (const pipe of props.pidLayer.pipes) {
    for (const pt of pipe.points) {
      minX = Math.min(minX, pt.x)
      minY = Math.min(minY, pt.y)
      maxX = Math.max(maxX, pt.x)
      maxY = Math.max(maxY, pt.y)
    }
  }
  const pad = 50
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 }
})

const minimapViewBox = computed(() => {
  const b = minimapBounds.value
  return `${b.x} ${b.y} ${b.w} ${b.h}`
})

const minimapViewport = computed(() => {
  const rect = canvasRef.value?.getBoundingClientRect()
  const w = (rect?.width ?? 800) / zoom.value
  const h = (rect?.height ?? 600) / zoom.value
  const x = -panX.value / zoom.value
  const y = -panY.value / zoom.value
  return { x, y, w, h }
})

function onMinimapMouseDown(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement
  const svg = target.querySelector('svg')
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const b = minimapBounds.value
  // Map click position to world coordinates
  const worldX = b.x + (event.clientX - rect.left) / rect.width * b.w
  const worldY = b.y + (event.clientY - rect.top) / rect.height * b.h
  // Center viewport on clicked position
  const canvasRect = canvasRef.value?.getBoundingClientRect()
  const vw = (canvasRect?.width ?? 800) / zoom.value
  const vh = (canvasRect?.height ?? 600) / zoom.value
  store.setPidPan(-(worldX - vw / 2) * zoom.value, -(worldY - vh / 2) * zoom.value)
}

// Layer visibility filtering
const hiddenLayerIds = computed(() => {
  const infos = props.pidLayer.layerInfos
  if (!infos || infos.length === 0) return new Set<string>()
  return new Set(infos.filter(l => !l.visible).map(l => l.id))
})

const visibleSymbols = computed(() => {
  if (hiddenLayerIds.value.size === 0) return props.pidLayer.symbols
  return props.pidLayer.symbols.filter(s => !hiddenLayerIds.value.has(s.layerId || 'main'))
})

const visiblePipes = computed(() => {
  if (hiddenLayerIds.value.size === 0) return props.pidLayer.pipes
  return props.pidLayer.pipes.filter(p => !hiddenLayerIds.value.has(p.layerId || 'main'))
})

const visibleTextAnnotations = computed(() => {
  const all = props.pidLayer.textAnnotations || []
  if (hiddenLayerIds.value.size === 0) return all
  return all.filter(t => !hiddenLayerIds.value.has(t.layerId || 'main'))
})

// Groups with calculated bounding boxes
const visibleGroups = computed(() => {
  const groups = props.pidLayer.groups || []
  return groups.map(group => {
    // Calculate bounding box from members
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity

    for (const symbolId of group.symbolIds) {
      const symbol = props.pidLayer.symbols.find(s => s.id === symbolId)
      if (symbol) {
        minX = Math.min(minX, symbol.x)
        minY = Math.min(minY, symbol.y)
        maxX = Math.max(maxX, symbol.x + (symbol.width || 60))
        maxY = Math.max(maxY, symbol.y + (symbol.height || 60))
      }
    }

    for (const pipeId of group.pipeIds) {
      const pipe = props.pidLayer.pipes.find(p => p.id === pipeId)
      if (pipe) {
        for (const pt of pipe.points) {
          minX = Math.min(minX, pt.x)
          minY = Math.min(minY, pt.y)
          maxX = Math.max(maxX, pt.x)
          maxY = Math.max(maxY, pt.y)
        }
      }
    }

    for (const textId of group.textAnnotationIds) {
      const text = (props.pidLayer.textAnnotations || []).find(t => t.id === textId)
      if (text) {
        const estWidth = text.text.length * text.fontSize * 0.6
        const estHeight = text.fontSize * 1.2
        minX = Math.min(minX, text.x)
        minY = Math.min(minY, text.y)
        maxX = Math.max(maxX, text.x + estWidth)
        maxY = Math.max(maxY, text.y + estHeight)
      }
    }

    return {
      ...group,
      x: minX === Infinity ? 0 : minX,
      y: minY === Infinity ? 0 : minY,
      width: maxX === -Infinity ? 0 : maxX - minX,
      height: maxY === -Infinity ? 0 : maxY - minY
    }
  }).filter(g => g.width > 0 && g.height > 0)
})

// Check if any member of a group is selected
function isGroupSelected(groupId: string): boolean {
  const group = (props.pidLayer.groups || []).find(g => g.id === groupId)
  if (!group) return false

  return store.pidSelectedIds.symbolIds.some(id => group.symbolIds.includes(id)) ||
    store.pidSelectedIds.pipeIds.some(id => group.pipeIds.includes(id)) ||
    store.pidSelectedIds.textAnnotationIds.some(id => group.textAnnotationIds.includes(id))
}

// Inline label editing (pipe labels + text annotations)
const inlineEditTarget = ref<{ type: 'pipeLabel'; pipeId: string } | { type: 'textAnnotation'; id: string } | null>(null)
const inlineEditValue = ref('')
const inlineEditPos = ref({ x: 0, y: 0 })
const inlineEditInput = ref<HTMLInputElement | null>(null)

function onPipeLabelDblClick(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  event.stopPropagation()
  event.preventDefault()
  const labelPt = getPipeLabelPoint(pipe)
  if (!labelPt || !canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  inlineEditPos.value = {
    x: rect.left + labelPt.x * zoom.value + panX.value,
    y: rect.top + labelPt.y * zoom.value + panY.value
  }
  inlineEditValue.value = pipe.label || ''
  inlineEditTarget.value = { type: 'pipeLabel', pipeId: pipe.id }
  nextTick(() => {
    inlineEditInput.value?.focus()
    inlineEditInput.value?.select()
  })
}

function onTextAnnotationDblClick(event: MouseEvent, text: PidTextAnnotation) {
  if (!props.editMode) return
  event.stopPropagation()
  event.preventDefault()
  const el = event.currentTarget as HTMLElement
  if (!el || !canvasRef.value) return
  const elRect = el.getBoundingClientRect()
  inlineEditPos.value = {
    x: elRect.left + elRect.width / 2,
    y: elRect.top + elRect.height / 2
  }
  inlineEditValue.value = text.text || ''
  inlineEditTarget.value = { type: 'textAnnotation', id: text.id }
  nextTick(() => {
    inlineEditInput.value?.focus()
    inlineEditInput.value?.select()
  })
}

function commitInlineEdit() {
  if (!inlineEditTarget.value) return
  const target = inlineEditTarget.value
  const value = inlineEditValue.value.trim()
  inlineEditTarget.value = null
  if (target.type === 'pipeLabel') {
    store.updatePidPipeWithUndo(target.pipeId, { label: value || undefined })
  } else {
    if (value) {
      store.updatePidTextAnnotation(target.id, { text: value })
    }
  }
}

function cancelInlineEdit() {
  inlineEditTarget.value = null
}

// Rulers and guide lines
const showRulers = computed(() => store.pidShowRulers)
const RULER_SIZE = 24 // pixels
const rulerHCanvas = ref<HTMLCanvasElement | null>(null)
const rulerVCanvas = ref<HTMLCanvasElement | null>(null)
const draggingGuide = ref<{ axis: 'h' | 'v'; position: number; id?: string } | null>(null)
const draggingGuidePos = ref(0)

function drawRuler(canvas: HTMLCanvasElement | null, axis: 'h' | 'v', zoomVal: number, panVal: number, length: number) {
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  const w = axis === 'h' ? length : RULER_SIZE
  const h = axis === 'h' ? RULER_SIZE : length
  canvas.width = w * dpr
  canvas.height = h * dpr
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, w, h)
  ctx.fillStyle = '#1e293b'
  ctx.fillRect(0, 0, w, h)

  // Determine tick spacing based on zoom
  let majorStep = 100
  if (zoomVal < 0.25) majorStep = 500
  else if (zoomVal < 0.5) majorStep = 200
  else if (zoomVal > 3) majorStep = 50
  const minorStep = majorStep / 5

  ctx.strokeStyle = '#475569'
  ctx.fillStyle = '#94a3b8'
  ctx.font = '9px system-ui'
  ctx.textBaseline = axis === 'h' ? 'top' : 'middle'

  const start = -panVal / zoomVal
  const end = start + length / zoomVal
  const firstMajor = Math.floor(start / majorStep) * majorStep
  const firstMinor = Math.floor(start / minorStep) * minorStep

  // Minor ticks
  ctx.beginPath()
  for (let v = firstMinor; v <= end; v += minorStep) {
    const screenPos = (v * zoomVal) + panVal
    if (axis === 'h') {
      ctx.moveTo(screenPos, RULER_SIZE - 4)
      ctx.lineTo(screenPos, RULER_SIZE)
    } else {
      ctx.moveTo(RULER_SIZE - 4, screenPos)
      ctx.lineTo(RULER_SIZE, screenPos)
    }
  }
  ctx.stroke()

  // Major ticks + labels
  ctx.strokeStyle = '#64748b'
  ctx.beginPath()
  for (let v = firstMajor; v <= end; v += majorStep) {
    const screenPos = (v * zoomVal) + panVal
    if (axis === 'h') {
      ctx.moveTo(screenPos, RULER_SIZE - 10)
      ctx.lineTo(screenPos, RULER_SIZE)
      ctx.fillText(String(Math.round(v)), screenPos + 2, 2)
    } else {
      ctx.moveTo(RULER_SIZE - 10, screenPos)
      ctx.lineTo(RULER_SIZE, screenPos)
      ctx.save()
      ctx.translate(2, screenPos + 2)
      ctx.rotate(-Math.PI / 2)
      ctx.fillText(String(Math.round(v)), 0, 0)
      ctx.restore()
    }
  }
  ctx.stroke()

  // Bottom/right border
  ctx.strokeStyle = '#334155'
  ctx.beginPath()
  if (axis === 'h') {
    ctx.moveTo(0, RULER_SIZE - 0.5)
    ctx.lineTo(w, RULER_SIZE - 0.5)
  } else {
    ctx.moveTo(RULER_SIZE - 0.5, 0)
    ctx.lineTo(RULER_SIZE - 0.5, h)
  }
  ctx.stroke()
}

function onRulerMouseDown(event: MouseEvent, axis: 'h' | 'v') {
  if (!props.editMode) return
  event.preventDefault()
  const pos = axis === 'h'
    ? (event.clientY - (canvasRef.value?.getBoundingClientRect().top ?? 0) - panY.value) / zoom.value
    : (event.clientX - (canvasRef.value?.getBoundingClientRect().left ?? 0) - panX.value) / zoom.value
  draggingGuide.value = { axis, position: pos }
  draggingGuidePos.value = pos

  function onMove(e: MouseEvent) {
    if (!draggingGuide.value || !canvasRef.value) return
    const rect = canvasRef.value.getBoundingClientRect()
    const newPos = axis === 'h'
      ? (e.clientY - rect.top - panY.value) / zoom.value
      : (e.clientX - rect.left - panX.value) / zoom.value
    draggingGuidePos.value = newPos
    draggingGuide.value.position = newPos
  }

  function onUp(e: MouseEvent) {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    if (!draggingGuide.value || !canvasRef.value) return
    const rect = canvasRef.value.getBoundingClientRect()
    const inCanvas = axis === 'h'
      ? (e.clientY > rect.top + RULER_SIZE && e.clientY < rect.bottom)
      : (e.clientX > rect.left + RULER_SIZE && e.clientX < rect.right)
    if (inCanvas) {
      if (draggingGuide.value.id) {
        store.updatePidGuide(draggingGuide.value.id, draggingGuide.value.position)
      } else {
        store.addPidGuide(axis, draggingGuide.value.position)
      }
    } else if (draggingGuide.value.id) {
      // Dragged back to ruler = delete
      store.removePidGuide(draggingGuide.value.id)
    }
    draggingGuide.value = null
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function onGuideMouseDown(event: MouseEvent, guide: { id: string; axis: 'h' | 'v'; position: number }) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()
  draggingGuide.value = { axis: guide.axis, position: guide.position, id: guide.id }
  draggingGuidePos.value = guide.position

  function onMove(e: MouseEvent) {
    if (!draggingGuide.value || !canvasRef.value) return
    const rect = canvasRef.value.getBoundingClientRect()
    const newPos = guide.axis === 'h'
      ? (e.clientY - rect.top - panY.value) / zoom.value
      : (e.clientX - rect.left - panX.value) / zoom.value
    draggingGuidePos.value = newPos
    draggingGuide.value.position = newPos
  }

  function onUp(e: MouseEvent) {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    if (!draggingGuide.value || !canvasRef.value) return
    const rect = canvasRef.value.getBoundingClientRect()
    const inCanvas = guide.axis === 'h'
      ? (e.clientY > rect.top + RULER_SIZE && e.clientY < rect.bottom)
      : (e.clientX > rect.left + RULER_SIZE && e.clientX < rect.right)
    if (inCanvas) {
      store.updatePidGuide(guide.id, draggingGuide.value.position)
    } else {
      store.removePidGuide(guide.id)
    }
    draggingGuide.value = null
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// Snap coordinate to grid
function snapToGrid(value: number): number {
  if (!gridSnapEnabled.value) return value
  return Math.round(value / gridSize.value) * gridSize.value
}

// Snap point to grid
function snapPointToGrid(point: PidPoint): PidPoint {
  if (!gridSnapEnabled.value) return point
  return {
    x: snapToGrid(point.x),
    y: snapToGrid(point.y)
  }
}

// Get primary port for a symbol (first inlet/suction, or first port)
function getPrimaryPort(symbol: PidSymbol): { id: string; x: number; y: number } | null {
  const symbolType = symbol.type as ScadaSymbolType
  const ports = SYMBOL_PORTS[symbolType]
  if (!ports || ports.length === 0) return null

  // Find primary port: prefer inlet/suction/process, fallback to first port
  const primaryPort = ports.find(p =>
    p.id === 'inlet' || p.id === 'suction' || p.id === 'process'
  ) || ports[0]

  if (!primaryPort) return null

  // Get absolute position of this port
  const pos = getPortPosition(
    symbolType,
    primaryPort.id,
    symbol.x,
    symbol.y,
    symbol.width,
    symbol.height,
    (symbol.rotation || 0) as 0 | 90 | 180 | 270
  )

  return pos ? { id: primaryPort.id, x: pos.x, y: pos.y } : null
}

// Snap symbol position so primary port lands on grid
function snapSymbolToPortGrid(
  symbol: PidSymbol,
  newX: number,
  newY: number
): { x: number; y: number } {
  if (!gridSnapEnabled.value) return { x: newX, y: newY }

  const symbolType = symbol.type as ScadaSymbolType
  const ports = SYMBOL_PORTS[symbolType]
  if (!ports || ports.length === 0) {
    // No ports, snap bounding box corner
    return { x: snapToGrid(newX), y: snapToGrid(newY) }
  }

  // Find primary port
  const primaryPort = ports.find(p =>
    p.id === 'inlet' || p.id === 'suction' || p.id === 'process'
  ) || ports[0]

  if (!primaryPort) {
    return { x: snapToGrid(newX), y: snapToGrid(newY) }
  }

  // Calculate where port would be at the new position
  // Port uses normalized coords (0-1), so port.x=0.5 means center
  const width = symbol.width || 60
  const height = symbol.height || 60

  // Apply rotation to get effective port position
  let relX = primaryPort.x
  let relY = primaryPort.y
  const rotation = (symbol.rotation || 0) as 0 | 90 | 180 | 270

  if (rotation === 90) {
    const temp = relX
    relX = 1 - relY
    relY = temp
  } else if (rotation === 180) {
    relX = 1 - relX
    relY = 1 - relY
  } else if (rotation === 270) {
    const temp = relX
    relX = relY
    relY = 1 - temp
  }

  // Port absolute position would be: newX + relX * width, newY + relY * height
  const portX = newX + relX * width
  const portY = newY + relY * height

  // Snap port to grid
  const snappedPortX = snapToGrid(portX)
  const snappedPortY = snapToGrid(portY)

  // Calculate symbol position that puts port on grid
  const snappedSymbolX = snappedPortX - relX * width
  const snappedSymbolY = snappedPortY - relY * height

  return {
    x: Math.max(0, snappedSymbolX),
    y: Math.max(0, snappedSymbolY)
  }
}

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
  (e: 'control', action: { type: string; channel: string; value: any }): void
}>()

const store = useDashboardStore()

// Selection state
const selectedSymbolId = ref<string | null>(null)
const selectedPipeId = ref<string | null>(null)
const hoveredSymbolId = ref<string | null>(null)

// Context menu state
const contextMenu = ref<{ x: number; y: number; target: MenuTarget } | null>(null)

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

// Snap-to-port state
const snapTarget = ref<{
  symbolId: string
  portId: string
  x: number
  y: number
} | null>(null)
const startConnection = ref<PidPipeConnection | null>(null)

// Orthogonal constraint (Shift key)
const shiftHeld = ref(false)

// Marquee (rubber-band) selection state
const isMarqueeSelecting = ref(false)
const marqueeStart = ref<PidPoint | null>(null)
const marqueeEnd = ref<PidPoint | null>(null)
const justDidMarquee = ref(false)  // Prevents click handler from deselecting after marquee

// Get all port positions for all symbols on the canvas
// Includes both built-in and custom ports
function getAllPortPositions(): Array<{
  symbolId: string
  portId: string
  x: number
  y: number
  direction: 'left' | 'right' | 'top' | 'bottom'
  isCustom?: boolean
}> {
  const ports: Array<{
    symbolId: string
    portId: string
    x: number
    y: number
    direction: 'left' | 'right' | 'top' | 'bottom'
    isCustom?: boolean
  }> = []

  for (const symbol of props.pidLayer.symbols) {
    // Use getSymbolPorts which handles both built-in and custom ports
    const symbolPorts = getSymbolPorts(symbol)
    for (const port of symbolPorts) {
      ports.push({
        symbolId: symbol.id,
        portId: port.id,
        x: port.x,
        y: port.y,
        direction: port.direction,
        isCustom: port.isCustom
      })
    }
  }

  return ports
}

// Find nearest port within snap threshold
function findNearestPort(mousePos: PidPoint): typeof snapTarget.value {
  const allPorts = getAllPortPositions()
  let nearest: typeof snapTarget.value = null
  let minDist = SNAP_THRESHOLD.value

  for (const port of allPorts) {
    const dist = Math.sqrt((mousePos.x - port.x) ** 2 + (mousePos.y - port.y) ** 2)
    if (dist < minDist) {
      minDist = dist
      nearest = {
        symbolId: port.symbolId,
        portId: port.portId,
        x: port.x,
        y: port.y
      }
    }
  }

  return nearest
}

// Constrain point to orthogonal (horizontal or vertical) from last point
function constrainToOrthogonal(point: PidPoint, lastPoint: PidPoint): PidPoint {
  const dx = Math.abs(point.x - lastPoint.x)
  const dy = Math.abs(point.y - lastPoint.y)

  // Choose horizontal or vertical based on which delta is larger
  if (dx > dy) {
    // Horizontal constraint
    return { x: point.x, y: lastPoint.y }
  } else {
    // Vertical constraint
    return { x: lastPoint.x, y: point.y }
  }
}

// Get ports for a specific symbol (for rendering port indicators)
// Includes both built-in ports and custom user-defined ports
function getSymbolPorts(symbol: PidSymbol): Array<{
  id: string
  x: number
  y: number
  direction: 'left' | 'right' | 'top' | 'bottom'
  isCustom?: boolean
}> {
  const symbolType = symbol.type as ScadaSymbolType
  const symbolPorts = SYMBOL_PORTS[symbolType]
  const hiddenPorts = symbol.hiddenPorts || []

  const result: Array<{
    id: string
    x: number
    y: number
    direction: 'left' | 'right' | 'top' | 'bottom'
    isCustom?: boolean
  }> = []

  // Add built-in ports (skip hidden ones)
  if (symbolPorts) {
    for (const port of symbolPorts) {
      // Skip hidden ports
      if (hiddenPorts.includes(port.id)) continue

      const pos = getPortPosition(
        symbolType,
        port.id,
        symbol.x,
        symbol.y,
        symbol.width,
        symbol.height,
        (symbol.rotation || 0) as 0 | 90 | 180 | 270
      )
      if (pos) {
        result.push({
          id: port.id,
          x: pos.x,
          y: pos.y,
          direction: pos.direction,
          isCustom: false
        })
      }
    }
  }

  // Add custom user-defined ports
  if (symbol.customPorts && symbol.customPorts.length > 0) {
    const width = symbol.width || 60
    const height = symbol.height || 60
    const rotation = (symbol.rotation || 0) as 0 | 90 | 180 | 270

    for (const customPort of symbol.customPorts) {
      // Apply rotation to relative coordinates
      let relX = customPort.x
      let relY = customPort.y
      let direction = customPort.direction

      if (rotation === 90) {
        const temp = relX
        relX = 1 - relY
        relY = temp
        // Rotate direction
        const dirMap: Record<string, 'left' | 'right' | 'top' | 'bottom'> = {
          'left': 'top', 'top': 'right', 'right': 'bottom', 'bottom': 'left'
        }
        direction = dirMap[direction] || direction
      } else if (rotation === 180) {
        relX = 1 - relX
        relY = 1 - relY
        const dirMap: Record<string, 'left' | 'right' | 'top' | 'bottom'> = {
          'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'
        }
        direction = dirMap[direction] || direction
      } else if (rotation === 270) {
        const temp = relX
        relX = relY
        relY = 1 - temp
        const dirMap: Record<string, 'left' | 'right' | 'top' | 'bottom'> = {
          'left': 'bottom', 'bottom': 'right', 'right': 'top', 'top': 'left'
        }
        direction = dirMap[direction] || direction
      }

      result.push({
        id: customPort.id,
        x: symbol.x + relX * width,
        y: symbol.y + relY * height,
        direction,
        isCustom: true
      })
    }
  }

  return result
}

// --- Nozzle stub rendering for equipment symbols ---
const NOZZLE_STUB_LENGTH = 12

const DIRECTION_VECTORS: Record<string, { dx: number; dy: number }> = {
  left:   { dx: -1, dy:  0 },
  right:  { dx:  1, dy:  0 },
  top:    { dx:  0, dy: -1 },
  bottom: { dx:  0, dy:  1 },
}

function symbolHasNozzleStubs(symbolType: string): boolean {
  const info = SYMBOL_INFO[symbolType as ScadaSymbolType]
  return !!info && NOZZLE_STUB_CATEGORIES.has(info.category)
}

function getNozzleStubGeometry(port: { x: number; y: number; direction: string }) {
  const vec = DIRECTION_VECTORS[port.direction] || { dx: 1, dy: 0 }
  const capHalf = 3
  const x2 = port.x + vec.dx * NOZZLE_STUB_LENGTH
  const y2 = port.y + vec.dy * NOZZLE_STUB_LENGTH
  const perpDx = -vec.dy
  const perpDy = vec.dx
  return {
    x1: port.x, y1: port.y, x2, y2,
    capX1: x2 + perpDx * capHalf, capY1: y2 + perpDy * capHalf,
    capX2: x2 - perpDx * capHalf, capY2: y2 - perpDy * capHalf,
  }
}

const nozzleStubs = computed(() => {
  if (!props.editMode) return []
  const stubs: Array<{
    symbolId: string; portId: string; color: string
    x1: number; y1: number; x2: number; y2: number
    capX1: number; capY1: number; capX2: number; capY2: number
  }> = []
  for (const symbol of props.pidLayer.symbols) {
    if (!symbolHasNozzleStubs(symbol.type)) continue
    const color = symbol.color || '#60a5fa'
    for (const port of getSymbolPorts(symbol)) {
      stubs.push({ symbolId: symbol.id, portId: port.id, color, ...getNozzleStubGeometry(port) })
    }
  }
  return stubs
})

// Canvas ref for coordinate calculations
const canvasRef = ref<HTMLElement | null>(null)
const viewportRef = ref<HTMLElement | null>(null)

// Symbol configuration modal state
const showConfigModal = ref(false)
const configSymbol = ref<PidSymbol | null>(null)

// Faceplate popup state (runtime mode)
const showFaceplate = ref(false)
const faceplateSymbol = ref<PidSymbol | null>(null)
const faceplatePosition = ref({ x: 0, y: 0 })

// Open faceplate on symbol click in runtime mode
function openFaceplate(event: MouseEvent, symbol: PidSymbol) {
  if (props.editMode) return  // Don't show in edit mode
  if (!symbol.channel) return // Only show if channel is bound

  event.preventDefault()
  event.stopPropagation()

  faceplateSymbol.value = symbol
  faceplatePosition.value = {
    x: event.clientX,
    y: event.clientY
  }
  showFaceplate.value = true
}

function closeFaceplate() {
  showFaceplate.value = false
  faceplateSymbol.value = null
}

// Handle control action from faceplate
function handleFaceplateControl(action: { type: string; value: { channel: string; value: any } }) {
  // Emit to parent for MQTT publishing
  console.log('[PidCanvas] Faceplate control action:', action)

  // Emit control event to parent (Dashboard) for MQTT publishing
  emit('control', {
    type: action.type,
    channel: action.value.channel,
    value: action.value.value
  })
}

// Context menu handlers
function onSymbolRightClick(event: MouseEvent, symbol: PidSymbol) {
  if (!props.editMode) return
  // During pipe drawing, let the canvas handler finish the pipe instead
  if (props.pipeDrawingMode) return
  event.stopPropagation()
  selectedSymbolId.value = symbol.id
  emit('select:symbol', symbol.id)
  contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'symbol', id: symbol.id } }
}

function onPipeRightClick(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  // During pipe drawing, let the canvas handler finish the pipe instead
  if (props.pipeDrawingMode) return
  selectedPipeId.value = pipe.id
  emit('select:pipe', pipe.id)
  contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'pipe', id: pipe.id } }
}

function handleContextMenuAction(action: string) {
  const target = contextMenu.value?.target
  if (!target) return

  if (target.type === 'symbol') {
    switch (action) {
      case 'configure':
        const sym = props.pidLayer.symbols.find(s => s.id === target.id)
        if (sym) openSymbolConfig(sym)
        break
      case 'cut': store.pidCut(); break
      case 'copy': store.pidCopy(); break
      case 'duplicate': store.pidDuplicate(); break
      case 'delete': store.pidDeleteSelected(); break
      case 'bringToFront': store.pidBringToFront(); break
      case 'sendToBack': store.pidSendToBack(); break
      case 'rotateCW': {
        const s = props.pidLayer.symbols.find(s => s.id === target.id)
        if (s) store.updatePidSymbolWithUndo(target.id, { rotation: (s.rotation || 0) + 90 })
        break
      }
      case 'rotateCCW': {
        const s = props.pidLayer.symbols.find(s => s.id === target.id)
        if (s) store.updatePidSymbolWithUndo(target.id, { rotation: (s.rotation || 0) - 90 })
        break
      }
    }
  } else if (target.type === 'pipe') {
    switch (action) {
      case 'delete': store.pidDeleteSelected(); break
      case 'toggleDashed': {
        const p = props.pidLayer.pipes.find(p => p.id === target.id)
        if (p) store.updatePidPipeWithUndo(target.id, { dashed: !p.dashed, dashPattern: undefined })
        break
      }
      case 'toggleAnimation': {
        const p = props.pidLayer.pipes.find(p => p.id === target.id)
        if (p) store.updatePidPipeWithUndo(target.id, { animated: !p.animated })
        break
      }
      case 'reversePipe': {
        const p = props.pidLayer.pipes.find(p => p.id === target.id)
        if (p) {
          store.updatePidPipeWithUndo(target.id, {
            points: [...p.points].reverse(),
            startConnection: p.endConnection,
            endConnection: p.startConnection,
            startSymbolId: p.endSymbolId,
            endSymbolId: p.startSymbolId,
            startPortId: p.endPortId,
            endPortId: p.startPortId,
            startArrow: p.endArrow,
            endArrow: p.startArrow,
          })
        }
        break
      }
      case 'copyStyle': {
        store.pidCopyStyle(target.id)
        break
      }
      case 'pasteStyle': {
        store.pidPasteStyle(target.id)
        break
      }
    }
  } else {
    switch (action) {
      case 'paste': store.pidPaste(); break
      case 'selectAll': store.pidSelectAll(); break
      case 'toggleGrid': store.togglePidGridSnap(); break
      case 'resetZoom': store.pidResetZoom(); break
    }
  }
}

const configForm = ref({
  label: '',
  channel: '',
  showValue: false,
  decimals: 1,
  color: '#60a5fa',
  rotation: 0,
  // Tank fill options
  fillChannel: '',
  fillLevel: 50,
  fillColor: '#3b82f6',
  // Custom ports
  customPorts: [] as Array<{
    id: string
    x: number
    y: number
    direction: 'left' | 'right' | 'top' | 'bottom'
    label?: string
  }>,
  // Hidden built-in ports
  hiddenPorts: [] as string[]
})

// New custom port input state
const newPortDirection = ref<'left' | 'right' | 'top' | 'bottom'>('left')
const newPortPosition = ref(50) // 0-100 slider position along the edge

// Available channels for binding
const availableChannels = computed(() => {
  return Object.entries(store.channels).map(([name, ch]) => ({
    name,
    unit: ch.unit || '',
    type: ch.channel_type
  }))
})

// Get built-in ports for the config symbol (for showing in modal)
const builtInPortsForConfig = computed(() => {
  if (!configSymbol.value) return []
  const symbolType = configSymbol.value.type as ScadaSymbolType
  const ports = SYMBOL_PORTS[symbolType]
  return ports || []
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
    rotation: symbol.rotation || 0,
    // Tank fill options
    fillChannel: symbol.fillChannel || '',
    fillLevel: symbol.fillLevel ?? 50,
    fillColor: symbol.fillColor || '#3b82f6',
    // Custom ports - deep copy
    customPorts: symbol.customPorts ? symbol.customPorts.map(p => ({ ...p })) : [],
    // Hidden ports - copy array
    hiddenPorts: symbol.hiddenPorts ? [...symbol.hiddenPorts] : []
  }
  // Reset new port inputs
  newPortDirection.value = 'left'
  newPortPosition.value = 50
  showConfigModal.value = true
}

// Toggle visibility of a built-in port
function toggleBuiltInPort(portId: string) {
  const idx = configForm.value.hiddenPorts.indexOf(portId)
  if (idx >= 0) {
    // Currently hidden, make visible
    configForm.value.hiddenPorts.splice(idx, 1)
  } else {
    // Currently visible, hide it
    configForm.value.hiddenPorts.push(portId)
  }
}

// Add a custom port to the symbol
function addCustomPort() {
  const direction = newPortDirection.value
  const pos = newPortPosition.value / 100  // Convert 0-100 to 0-1

  // Calculate x, y based on direction and position
  let x = 0, y = 0
  switch (direction) {
    case 'left':
      x = 0
      y = pos
      break
    case 'right':
      x = 1
      y = pos
      break
    case 'top':
      x = pos
      y = 0
      break
    case 'bottom':
      x = pos
      y = 1
      break
  }

  const newPort = {
    id: `custom-${Date.now()}`,
    x,
    y,
    direction,
    label: `Port ${configForm.value.customPorts.length + 1}`
  }

  configForm.value.customPorts.push(newPort)
}

// Remove a custom port
function removeCustomPort(portId: string) {
  configForm.value.customPorts = configForm.value.customPorts.filter(p => p.id !== portId)
}

// Get human-readable port position description
function getPortPositionLabel(port: { x: number; y: number; direction: string }): string {
  const pos = port.direction === 'left' || port.direction === 'right'
    ? Math.round(port.y * 100)
    : Math.round(port.x * 100)
  return `${port.direction} @ ${pos}%`
}

// Check if symbol is a tank type
function isTankSymbol(symbol: PidSymbol | null): boolean {
  if (!symbol) return false
  const type = symbol.type.toLowerCase()
  return type.includes('tank') || type === 'reactor'
}

// Save symbol config
function saveSymbolConfig() {
  if (!configSymbol.value) return

  const isTank = isTankSymbol(configSymbol.value)

  const newSymbols = props.pidLayer.symbols.map(s =>
    s.id === configSymbol.value!.id
      ? {
          ...s,
          label: configForm.value.label || undefined,
          channel: configForm.value.channel || undefined,
          showValue: configForm.value.showValue,
          decimals: configForm.value.decimals,
          color: configForm.value.color,
          rotation: configForm.value.rotation,
          // Custom connection ports
          customPorts: configForm.value.customPorts.length > 0
            ? configForm.value.customPorts
            : undefined,
          // Hidden built-in ports
          hiddenPorts: configForm.value.hiddenPorts.length > 0
            ? configForm.value.hiddenPorts
            : undefined,
          // Tank-specific properties
          ...(isTank ? {
            fillChannel: configForm.value.fillChannel || undefined,
            fillLevel: configForm.value.fillLevel,
            fillColor: configForm.value.fillColor
          } : {})
        }
      : s
  )

  emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
  showConfigModal.value = false
  configSymbol.value = null
}

// Handle symbol double-click for config
function onSymbolDoubleClick(event: MouseEvent, symbol: PidSymbol) {
  event.preventDefault()
  event.stopPropagation()
  if (props.editMode) {
    openSymbolConfig(symbol)
  } else if (OFF_PAGE_CONNECTOR_TYPES.has(symbol.type) && symbol.linkedPageId) {
    store.switchPage(symbol.linkedPageId)
  }
}

// Get canvas-relative coordinates from mouse event
function getCanvasCoords(event: MouseEvent): PidPoint {
  if (!canvasRef.value) return { x: 0, y: 0 }
  const rect = canvasRef.value.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left - panX.value) / zoom.value,
    y: (event.clientY - rect.top - panY.value) / zoom.value
  }
}

// Symbol rendering
function getSymbolSvg(type: string): string {
  return SCADA_SYMBOLS[type as ScadaSymbolType] || SCADA_SYMBOLS.solenoidValve
}

// Get tank fill level (0-100) from channel or static value
function getTankFillLevel(symbol: PidSymbol): number {
  // Check if this is a tank-type symbol
  if (!symbol.type.toLowerCase().includes('tank') && symbol.type !== 'reactor') {
    return -1 // Not a tank
  }

  // Get fill level from bound channel
  if (symbol.fillChannel) {
    const value = store.values[symbol.fillChannel]
    if (value && typeof value.value === 'number') {
      // Clamp to 0-100
      return Math.max(0, Math.min(100, value.value))
    }
  }

  // Use static fillLevel if set
  if (typeof symbol.fillLevel === 'number') {
    return Math.max(0, Math.min(100, symbol.fillLevel))
  }

  // Default to 50% if no binding
  return 50
}

// Generate tank SVG with dynamic fill level
function getTankSvgWithFill(symbol: PidSymbol): string {
  const baseSvg = getSymbolSvg(symbol.type)
  const fillLevel = getTankFillLevel(symbol)

  if (fillLevel < 0) {
    return baseSvg // Not a tank, return as-is
  }

  // Calculate fill rectangle y position and height
  // For vertical tank: viewBox is 60x80, level area is y=20 to y=70 (height 50)
  // Fill from bottom: y = 70 - (fillLevel/100 * 50), height = fillLevel/100 * 50
  const fillPercent = fillLevel / 100
  // Sanitize fillColor to prevent SVG injection via attribute escape
  const rawColor = symbol.fillColor || 'currentColor'
  const fillColor = /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgb\(\d+,\s*\d+,\s*\d+\)|currentColor)$/.test(rawColor)
    ? rawColor
    : 'currentColor'

  // Replace the static level-fill rect with dynamic one
  // Original: <rect x="15" y="40" width="30" height="30" class="level-fill" ...>
  // New: Calculate y based on fill level

  // For vertical tank (viewBox 0 0 60 80):
  // Level area: y=20 to y=70 (50px height)
  // Fill y = 70 - fillPercent * 50 = 70 - fillHeight
  // Fill height = fillPercent * 50

  if (symbol.type === 'tank') {
    const fillHeight = fillPercent * 50
    const fillY = 70 - fillHeight
    return baseSvg.replace(
      /<rect[^>]*class="level-fill"[^>]*\/>/,
      `<rect x="15" y="${fillY}" width="30" height="${fillHeight}" class="level-fill" fill="${fillColor}" opacity="0.5">
        <animate attributeName="opacity" values="0.4;0.6;0.4" dur="2s" repeatCount="indefinite"/>
      </rect>`
    )
  }

  // For horizontal tank (viewBox 0 0 80 50):
  // Level area: y=25 to y=43 (18px height), but we fill from bottom
  if (symbol.type === 'horizontalTank') {
    const fillHeight = fillPercent * 18
    const fillY = 43 - fillHeight
    return baseSvg.replace(
      /<rect[^>]*fill="currentColor"[^>]*opacity="0.3"[^>]*\/>/,
      `<rect x="20" y="${fillY}" width="40" height="${fillHeight}" fill="${fillColor}" opacity="0.5">
        <animate attributeName="opacity" values="0.4;0.6;0.4" dur="2s" repeatCount="indefinite"/>
      </rect>`
    )
  }

  // For reactor (similar to vertical tank)
  if (symbol.type === 'reactor') {
    const fillHeight = fillPercent * 35
    const fillY = 60 - fillHeight
    return baseSvg.replace(
      /<rect[^>]*opacity="0\.3"[^>]*\/>/,
      `<rect x="15" y="${fillY}" width="30" height="${fillHeight}" fill="${fillColor}" opacity="0.5">
        <animate attributeName="opacity" values="0.4;0.6;0.4" dur="2s" repeatCount="indefinite"/>
      </rect>`
    )
  }

  return baseSvg
}

// Check if a symbol should be shown in color (alarm state) or grayscale (ISA-101)
function isSymbolInAlarm(symbol: PidSymbol): boolean {
  if (!symbol.channel) return false
  const value = store.values[symbol.channel]
  return value?.alarm === true || value?.warning === true
}

// Get color scheme from store
const colorScheme = computed(() => store.pidColorScheme)

function getSymbolStyle(symbol: PidSymbol): Record<string, string> {
  const style: Record<string, string> = {
    left: `${symbol.x}px`,
    top: `${symbol.y}px`,
    width: `${symbol.width}px`,
    height: `${symbol.height}px`,
    zIndex: String(symbol.zIndex || 1)
  }
  if (symbol.rotation) {
    style.transform = `rotate(${symbol.rotation}deg)`
  }

  // ISA-101 Grayscale mode: show grayscale unless in alarm
  if (colorScheme.value === 'isa101' && !isSymbolInAlarm(symbol)) {
    style.filter = 'grayscale(100%)'
  }

  return style
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
  // In runtime mode, open faceplate on click (skip for HMI controls — they handle their own interaction)
  if (!props.editMode) {
    if (!isHmiControl(symbol.type)) {
      openFaceplate(event, symbol)
    }
    return
  }

  event.preventDefault()
  event.stopPropagation()

  // Check if clicking a resize handle
  const target = event.target as HTMLElement
  if (target.classList.contains('resize-handle')) {
    if (symbol.locked) return  // Locked symbols can't be resized
    const handle = target.dataset.handle as 'nw' | 'ne' | 'sw' | 'se'
    startResize(event, symbol, handle)
    return
  }

  // Check if symbol is in a group - select all group members
  const group = store.pidGetGroup(symbol.id)
  if (group) {
    store.pidSelectGroup(group.id)
  } else if (event.shiftKey) {
    // Shift+click: toggle selection (add/remove)
    store.pidToggleSelection(symbol.id, 'symbol')
  } else {
    // Single symbol selection
    store.pidSelectItems([symbol.id], [], [])
  }

  // Locked symbols can be selected but not dragged
  if (symbol.locked) {
    selectedSymbolId.value = symbol.id
    selectedPipeId.value = null
    emit('select:symbol', symbol.id)
    emit('select:pipe', null)
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

function onTextAnnotationMouseDown(event: MouseEvent, text: PidTextAnnotation) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  // Select the text annotation
  store.pidSelectItems([], [], [text.id])
  selectedSymbolId.value = null
  selectedPipeId.value = null

  // Start drag using the same drag infrastructure
  isDragging.value = true
  const coords = getCanvasCoords(event)
  dragStart.value = {
    x: coords.x,
    y: coords.y,
    symbolX: text.x,
    symbolY: text.y
  }

  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}

// Auto-reroute pipe endpoints connected to moved symbols
function rerouteConnectedPipes(pipes: PidPipe[], symbols: PidSymbol[]): PidPipe[] {
  const symbolMap = new Map(symbols.map(s => [s.id, s]))
  return pipes.map(pipe => {
    let updated = false
    let newPoints = pipe.points

    // Check start connection
    if (pipe.startConnection) {
      const sym = symbolMap.get(pipe.startConnection.symbolId)
      if (sym) {
        const pos = getPortPosition(
          sym.type as ScadaSymbolType,
          pipe.startConnection.portId,
          sym.x, sym.y, sym.width, sym.height,
          (sym.rotation || 0) as 0 | 90 | 180 | 270
        )
        if (pos && newPoints.length > 0) {
          const first = newPoints[0]!
          if (first.x !== pos.x || first.y !== pos.y) {
            newPoints = [...newPoints]
            newPoints[0] = { x: pos.x, y: pos.y }
            updated = true
          }
        }
      }
    }

    // Check end connection
    if (pipe.endConnection) {
      const sym = symbolMap.get(pipe.endConnection.symbolId)
      if (sym) {
        const pos = getPortPosition(
          sym.type as ScadaSymbolType,
          pipe.endConnection.portId,
          sym.x, sym.y, sym.width, sym.height,
          (sym.rotation || 0) as 0 | 90 | 180 | 270
        )
        if (pos && newPoints.length > 0) {
          const last = newPoints[newPoints.length - 1]!
          if (last.x !== pos.x || last.y !== pos.y) {
            if (!updated) newPoints = [...newPoints]
            newPoints[newPoints.length - 1] = { x: pos.x, y: pos.y }
            updated = true
          }
        }
      }
    }

    // Full auto-reroute when enabled and both ends are port-connected
    if (store.pidAutoRoute && updated && pipe.startConnection && pipe.endConnection) {
      const startSym = symbolMap.get(pipe.startConnection.symbolId)
      const endSym = symbolMap.get(pipe.endConnection.symbolId)
      if (startSym && endSym) {
        const sp = getSymbolPorts(startSym).find(p => p.id === pipe.startConnection!.portId)
        const ep = getSymbolPorts(endSym).find(p => p.id === pipe.endConnection!.portId)
        if (sp && ep) {
          const obstacles = symbols
            .filter(s => s.id !== startSym.id && s.id !== endSym.id)
            .map(s => ({ x: s.x, y: s.y, width: s.width, height: s.height }))
          newPoints = autoRoute(
            { x: sp.x, y: sp.y, direction: sp.direction },
            { x: ep.x, y: ep.y, direction: ep.direction },
            obstacles
          )
        }
      }
    }

    return updated ? { ...pipe, points: newPoints } : pipe
  })
}

// Compute alignment guides and return snapped position
function computeAlignmentSnap(
  draggedIds: string[],
  targetX: number, targetY: number,
  targetW: number, targetH: number
): { x: number; y: number; guides: AlignmentGuide[] } {
  const ALIGN_THRESHOLD = 5 / zoom.value
  const guides: AlignmentGuide[] = []
  let snapX = targetX
  let snapY = targetY

  // Edges and center of dragged symbol
  const dLeft = targetX
  const dRight = targetX + targetW
  const dCx = targetX + targetW / 2
  const dTop = targetY
  const dBottom = targetY + targetH
  const dCy = targetY + targetH / 2

  let bestDx = ALIGN_THRESHOLD + 1
  let bestDy = ALIGN_THRESHOLD + 1

  for (const other of props.pidLayer.symbols) {
    if (draggedIds.includes(other.id)) continue

    const oLeft = other.x
    const oRight = other.x + other.width
    const oCx = other.x + other.width / 2
    const oTop = other.y
    const oBottom = other.y + other.height
    const oCy = other.y + other.height / 2

    // Vertical alignment checks (snap X)
    const vChecks: [number, number][] = [
      [dLeft, oLeft], [dLeft, oRight], [dRight, oLeft], [dRight, oRight], [dCx, oCx]
    ]
    for (const [dEdge, oEdge] of vChecks) {
      const diff = Math.abs(dEdge - oEdge)
      if (diff < bestDx) {
        bestDx = diff
        snapX = targetX + (oEdge - dEdge)
      }
    }

    // Horizontal alignment checks (snap Y)
    const hChecks: [number, number][] = [
      [dTop, oTop], [dTop, oBottom], [dBottom, oTop], [dBottom, oBottom], [dCy, oCy]
    ]
    for (const [dEdge, oEdge] of hChecks) {
      const diff = Math.abs(dEdge - oEdge)
      if (diff < bestDy) {
        bestDy = diff
        snapY = targetY + (oEdge - dEdge)
      }
    }
  }

  // Also snap to user guide lines
  for (const guide of props.pidLayer.guides || []) {
    if (guide.axis === 'v') {
      for (const dEdge of [dLeft, dRight, dCx]) {
        const diff = Math.abs(dEdge - guide.position)
        if (diff < bestDx) {
          bestDx = diff
          snapX = targetX + (guide.position - dEdge)
        }
      }
    } else {
      for (const dEdge of [dTop, dBottom, dCy]) {
        const diff = Math.abs(dEdge - guide.position)
        if (diff < bestDy) {
          bestDy = diff
          snapY = targetY + (guide.position - dEdge)
        }
      }
    }
  }

  // If no snap occurred, revert
  if (bestDx > ALIGN_THRESHOLD) snapX = targetX
  if (bestDy > ALIGN_THRESHOLD) snapY = targetY

  // Build guide lines for snapped positions
  if (snapX !== targetX) {
    // Find which vertical line we snapped to
    const sLeft = snapX
    const sRight = snapX + targetW
    const sCx = snapX + targetW / 2
    for (const other of props.pidLayer.symbols) {
      if (draggedIds.includes(other.id)) continue
      const oEdges = [other.x, other.x + other.width, other.x + other.width / 2]
      for (const oEdge of oEdges) {
        for (const sEdge of [sLeft, sRight, sCx]) {
          if (Math.abs(sEdge - oEdge) < 1) {
            const minY = Math.min(snapY, other.y)
            const maxY = Math.max(snapY + targetH, other.y + other.height)
            guides.push({ axis: 'v', pos: sEdge, from: minY, to: maxY })
          }
        }
      }
    }
  }

  if (snapY !== targetY) {
    const sTop = snapY
    const sBottom = snapY + targetH
    const sCy = snapY + targetH / 2
    for (const other of props.pidLayer.symbols) {
      if (draggedIds.includes(other.id)) continue
      const oEdges = [other.y, other.y + other.height, other.y + other.height / 2]
      for (const oEdge of oEdges) {
        for (const sEdge of [sTop, sBottom, sCy]) {
          if (Math.abs(sEdge - oEdge) < 1) {
            const minX = Math.min(snapX, other.x)
            const maxX = Math.max(snapX + targetW, other.x + other.width)
            guides.push({ axis: 'h', pos: sEdge, from: minX, to: maxX })
          }
        }
      }
    }
  }

  return { x: snapX, y: snapY, guides }
}

function onDragMove(event: MouseEvent) {
  if (!isDragging.value || !dragStart.value || !selectedSymbolId.value) return

  const coords = getCanvasCoords(event)
  let dx = coords.x - dragStart.value.x
  let dy = coords.y - dragStart.value.y

  // Check if this symbol is part of a selection (group)
  const selectedSymbolIds = store.pidSelectedIds.symbolIds
  const selectedPipeIds = store.pidSelectedIds.pipeIds
  const selectedTextIds = store.pidSelectedIds.textAnnotationIds
  const hasMultiSelection = selectedSymbolIds.length > 1 || selectedPipeIds.length > 0 || selectedTextIds.length > 0

  // Apply port-based grid snap for multi-selection (based on dragged symbol)
  if (gridSnapEnabled.value && hasMultiSelection) {
    const draggedSymbol = props.pidLayer.symbols.find(s => s.id === selectedSymbolId.value)
    if (draggedSymbol) {
      const rawX = draggedSymbol.x + dx
      const rawY = draggedSymbol.y + dy
      const snapped = snapSymbolToPortGrid(draggedSymbol, rawX, rawY)
      dx = snapped.x - draggedSymbol.x
      dy = snapped.y - draggedSymbol.y
    }
  }

  // Alignment guides for multi-selection (based on dragged symbol)
  if (hasMultiSelection) {
    const draggedSymbol = props.pidLayer.symbols.find(s => s.id === selectedSymbolId.value)
    if (draggedSymbol) {
      const alignResult = computeAlignmentSnap(
        selectedSymbolIds, draggedSymbol.x + dx, draggedSymbol.y + dy,
        draggedSymbol.width, draggedSymbol.height
      )
      if (alignResult.guides.length > 0) {
        dx += alignResult.x - (draggedSymbol.x + dx)
        dy += alignResult.y - (draggedSymbol.y + dy)
      }
      activeGuides.value = alignResult.guides
    }
  }

  if (hasMultiSelection && selectedSymbolIds.includes(selectedSymbolId.value)) {
    // Move all selected items together (skip locked symbols)
    let newSymbols = props.pidLayer.symbols.map(s => {
      if (selectedSymbolIds.includes(s.id) && !s.locked) {
        return { ...s, x: Math.max(0, s.x + dx), y: Math.max(0, s.y + dy) }
      }
      return s
    })

    let newPipes = props.pidLayer.pipes.map(p => {
      if (selectedPipeIds.includes(p.id)) {
        return { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y + dy })) }
      }
      return p
    })

    // Auto-reroute non-selected pipes connected to moved symbols
    newPipes = rerouteConnectedPipes(newPipes, newSymbols)

    let newTextAnnotations = (props.pidLayer.textAnnotations || []).map(t => {
      if (selectedTextIds.includes(t.id)) {
        return { ...t, x: t.x + dx, y: t.y + dy }
      }
      return t
    })

    emit('update:pidLayer', {
      ...props.pidLayer,
      symbols: newSymbols,
      pipes: newPipes,
      textAnnotations: newTextAnnotations
    })

    // Update drag start to current position for smooth dragging
    dragStart.value = {
      x: coords.x,
      y: coords.y,
      symbolX: dragStart.value.symbolX + dx,
      symbolY: dragStart.value.symbolY + dy
    }
  } else {
    // Single symbol drag - use port-based grid snapping
    const symbol = props.pidLayer.symbols.find(s => s.id === selectedSymbolId.value)
    if (!symbol) return

    let newX = Math.max(0, dragStart.value.symbolX + dx)
    let newY = Math.max(0, dragStart.value.symbolY + dy)

    // Apply port-based grid snap if enabled (snaps so primary port lands on grid)
    if (gridSnapEnabled.value) {
      const snapped = snapSymbolToPortGrid(symbol, newX, newY)
      newX = snapped.x
      newY = snapped.y
    }

    // Alignment guides (override grid snap when triggered)
    const alignResult = computeAlignmentSnap(
      [selectedSymbolId.value], newX, newY, symbol.width, symbol.height
    )
    if (alignResult.guides.length > 0) {
      newX = alignResult.x
      newY = alignResult.y
    }
    activeGuides.value = alignResult.guides

    // Update symbol position
    const newSymbols = props.pidLayer.symbols.map(s =>
      s.id === selectedSymbolId.value
        ? { ...s, x: newX, y: newY }
        : s
    )

    // Auto-reroute connected pipe endpoints
    const newPipes = rerouteConnectedPipes(props.pidLayer.pipes, newSymbols)

    emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols, pipes: newPipes })
  }
}

function onDragEnd() {
  isDragging.value = false
  dragStart.value = null
  activeGuides.value = []
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

// ========================================================================
// MARQUEE (RUBBER-BAND) SELECTION
// ========================================================================

// Start marquee selection when clicking on empty canvas space
function onCanvasMouseDown(event: MouseEvent) {
  if (!props.editMode) return

  // Pan with middle-mouse or Space+left-click
  if (event.button === 1 || (spaceHeld.value && event.button === 0)) {
    onPanStart(event)
    return
  }

  // Only start marquee if clicking directly on the canvas/viewport (not a symbol/pipe)
  // and not in pipe drawing mode
  if ((event.target !== canvasRef.value && event.target !== viewportRef.value) || props.pipeDrawingMode) return

  // Don't start marquee on right-click
  if (event.button !== 0) return

  event.preventDefault()

  const coords = getCanvasCoords(event)
  isMarqueeSelecting.value = true
  marqueeStart.value = coords
  marqueeEnd.value = coords

  // Clear selection unless Shift is held (additive selection)
  if (!event.shiftKey) {
    store.pidClearSelection()
    selectedSymbolId.value = null
    selectedPipeId.value = null
    emit('select:symbol', null)
    emit('select:pipe', null)
  }

  window.addEventListener('mousemove', onMarqueeMove)
  window.addEventListener('mouseup', onMarqueeEnd)
}

function onMarqueeMove(event: MouseEvent) {
  if (!isMarqueeSelecting.value || !marqueeStart.value) return

  marqueeEnd.value = getCanvasCoords(event)
}

function onMarqueeEnd(event: MouseEvent) {
  if (!isMarqueeSelecting.value || !marqueeStart.value || !marqueeEnd.value) {
    isMarqueeSelecting.value = false
    marqueeStart.value = null
    marqueeEnd.value = null
    window.removeEventListener('mousemove', onMarqueeMove)
    window.removeEventListener('mouseup', onMarqueeEnd)
    return
  }

  // Calculate selection rectangle (normalize to handle any drag direction)
  const x1 = Math.min(marqueeStart.value.x, marqueeEnd.value.x)
  const y1 = Math.min(marqueeStart.value.y, marqueeEnd.value.y)
  const x2 = Math.max(marqueeStart.value.x, marqueeEnd.value.x)
  const y2 = Math.max(marqueeStart.value.y, marqueeEnd.value.y)

  // Only select if drag distance is meaningful (>5px)
  const dragDistance = Math.sqrt(
    (marqueeEnd.value.x - marqueeStart.value.x) ** 2 +
    (marqueeEnd.value.y - marqueeStart.value.y) ** 2
  )

  if (dragDistance > 5) {
    // Find all items inside the selection rectangle
    const selectedSymbolIds: string[] = []
    const selectedPipeIds: string[] = []
    const selectedTextIds: string[] = []

    // Check symbols
    for (const symbol of props.pidLayer.symbols) {
      const sx = symbol.x
      const sy = symbol.y
      const sw = symbol.width || 60
      const sh = symbol.height || 60

      // Check if symbol overlaps with selection rectangle
      if (sx + sw >= x1 && sx <= x2 && sy + sh >= y1 && sy <= y2) {
        selectedSymbolIds.push(symbol.id)
      }
    }

    // Check pipes (any point inside = selected)
    for (const pipe of props.pidLayer.pipes) {
      const pipeInside = pipe.points.some(pt =>
        pt.x >= x1 && pt.x <= x2 && pt.y >= y1 && pt.y <= y2
      )
      if (pipeInside) {
        selectedPipeIds.push(pipe.id)
      }
    }

    // Check text annotations
    for (const text of (props.pidLayer.textAnnotations || [])) {
      const tw = text.text.length * text.fontSize * 0.6  // Estimate width
      const th = text.fontSize * 1.2  // Estimate height

      if (text.x + tw >= x1 && text.x <= x2 && text.y + th >= y1 && text.y <= y2) {
        selectedTextIds.push(text.id)
      }
    }

    // Apply selection (additive if Shift was held)
    if (event.shiftKey) {
      store.pidAddToSelection(selectedSymbolIds, selectedPipeIds, selectedTextIds)
    } else {
      store.pidSelectItems(selectedSymbolIds, selectedPipeIds, selectedTextIds)
    }

    // Update local selection state for visual feedback
    if (selectedSymbolIds.length === 1 && selectedPipeIds.length === 0) {
      selectedSymbolId.value = selectedSymbolIds[0]!
      emit('select:symbol', selectedSymbolIds[0]!)
    } else if (selectedPipeIds.length === 1 && selectedSymbolIds.length === 0) {
      selectedPipeId.value = selectedPipeIds[0]!
      emit('select:pipe', selectedPipeIds[0]!)
    }

    // Prevent the click handler from immediately deselecting
    justDidMarquee.value = true
    setTimeout(() => { justDidMarquee.value = false }, 50)
  }

  // Reset marquee state
  isMarqueeSelecting.value = false
  marqueeStart.value = null
  marqueeEnd.value = null

  window.removeEventListener('mousemove', onMarqueeMove)
  window.removeEventListener('mouseup', onMarqueeEnd)
}

// Computed: Marquee selection rectangle style
const marqueeStyle = computed(() => {
  if (!isMarqueeSelecting.value || !marqueeStart.value || !marqueeEnd.value) {
    return null
  }

  const x = Math.min(marqueeStart.value.x, marqueeEnd.value.x)
  const y = Math.min(marqueeStart.value.y, marqueeEnd.value.y)
  const width = Math.abs(marqueeEnd.value.x - marqueeStart.value.x)
  const height = Math.abs(marqueeEnd.value.y - marqueeStart.value.y)

  // Convert world coords to screen coords (marquee is outside viewport)
  return {
    left: `${x * zoom.value + panX.value}px`,
    top: `${y * zoom.value + panY.value}px`,
    width: `${width * zoom.value}px`,
    height: `${height * zoom.value}px`
  }
})

// Pipe drawing
function onCanvasClick(event: MouseEvent) {
  if (!props.editMode) return

  // Close context menu on any click
  contextMenu.value = null

  // Don't trigger click actions during pan mode
  if (spaceHeld.value || isPanning.value) return

  // Skip deselect if we just finished a marquee selection
  if (justDidMarquee.value) {
    justDidMarquee.value = false
    return
  }

  // If clicking on empty space, deselect
  if (event.target === canvasRef.value || event.target === viewportRef.value) {
    if (!props.pipeDrawingMode) {
      selectedSymbolId.value = null
      selectedPipeId.value = null
      store.pidClearSelection()
      emit('select:symbol', null)
      emit('select:pipe', null)
    }
  }

  // Handle pipe drawing mode
  if (props.pipeDrawingMode) {
    const rawCoords = getCanvasCoords(event)

    // Check for snap-to-port
    const nearestPort = findNearestPort(rawCoords)

    // Determine final coords: snap-to-port > orthogonal constraint > raw
    let coords: PidPoint
    if (nearestPort) {
      coords = { x: nearestPort.x, y: nearestPort.y }
    } else if (isDrawingPipe.value && currentPipePoints.value.length > 0) {
      // Apply orthogonal constraint by default (Shift disables it)
      const shouldConstrainOrthogonal = orthogonalPipes.value && !shiftHeld.value
      if (shouldConstrainOrthogonal) {
        const lastPoint = currentPipePoints.value[currentPipePoints.value.length - 1]!
        coords = constrainToOrthogonal(rawCoords, lastPoint)
      } else {
        coords = rawCoords
      }
    } else {
      coords = rawCoords
    }

    if (!isDrawingPipe.value) {
      // Start new pipe
      isDrawingPipe.value = true
      currentPipePoints.value = [coords]

      // Store start connection if snapped to port
      if (nearestPort) {
        startConnection.value = {
          symbolId: nearestPort.symbolId,
          portId: nearestPort.portId,
          x: nearestPort.x,
          y: nearestPort.y
        }
      } else {
        startConnection.value = null
      }
    } else {
      // Add point to current pipe (use snapped/constrained coords)
      currentPipePoints.value.push(coords)

      // AUTO-TERMINATE: If clicked on a port (not the start port), finish the pipe
      if (nearestPort && startConnection.value) {
        // Check it's not the same port we started from
        const isSamePort = startConnection.value.symbolId === nearestPort.symbolId &&
                           startConnection.value.portId === nearestPort.portId
        if (!isSamePort && currentPipePoints.value.length >= 2) {
          // Auto-route: if enabled, replace user waypoints with computed path
          let pipePoints = [...currentPipePoints.value]
          let pipePathType: 'polyline' | 'orthogonal' = 'polyline'
          const endConn = {
            symbolId: nearestPort.symbolId,
            portId: nearestPort.portId,
            x: nearestPort.x,
            y: nearestPort.y
          }

          if (store.pidAutoRoute && startConnection.value) {
            const startSym = props.pidLayer.symbols.find(s => s.id === startConnection.value!.symbolId)
            const endSym = props.pidLayer.symbols.find(s => s.id === endConn.symbolId)
            if (startSym && endSym) {
              const startPort = getSymbolPorts(startSym).find(p => p.id === startConnection.value!.portId)
              const endPort = getSymbolPorts(endSym).find(p => p.id === endConn.portId)
              if (startPort && endPort) {
                const obstacles = props.pidLayer.symbols
                  .filter(s => s.id !== startSym.id && s.id !== endSym.id)
                  .map(s => ({ x: s.x, y: s.y, width: s.width, height: s.height }))
                pipePoints = autoRoute(
                  { x: startPort.x, y: startPort.y, direction: startPort.direction },
                  { x: endPort.x, y: endPort.y, direction: endPort.direction },
                  obstacles
                )
                pipePathType = 'orthogonal'
              }
            }
          }

          // Finish the pipe automatically
          const newPipe: PidPipe = {
            id: `pipe-${Date.now()}`,
            points: pipePoints,
            pathType: pipePathType,
            color: store.pidPipeColor,
            strokeWidth: 3,
            dashed: store.pidPipeDashed || undefined,
            animated: store.pidPipeAnimated || undefined,
            startConnection: startConnection.value,
            endConnection: endConn
          }

          emit('update:pidLayer', {
            ...props.pidLayer,
            pipes: [...props.pidLayer.pipes, newPipe]
          })

          // Reset drawing state - ready for new pipe
          isDrawingPipe.value = false
          currentPipePoints.value = []
          tempMousePos.value = null
          snapTarget.value = null
          startConnection.value = null
        }
      }
    }
  }
}

function onCanvasDoubleClick(event: MouseEvent) {
  if (!props.pipeDrawingMode || !isDrawingPipe.value) return

  // Check for end snap-to-port
  const rawCoords = getCanvasCoords(event)
  const nearestPort = findNearestPort(rawCoords)

  // Determine final coords: snap-to-port > orthogonal constraint > raw
  let endCoords: PidPoint
  if (nearestPort) {
    endCoords = { x: nearestPort.x, y: nearestPort.y }
  } else if (currentPipePoints.value.length > 0) {
    // Apply orthogonal constraint by default (Shift disables it)
    const shouldConstrainOrthogonal = orthogonalPipes.value && !shiftHeld.value
    if (shouldConstrainOrthogonal) {
      const lastPoint = currentPipePoints.value[currentPipePoints.value.length - 1]!
      endCoords = constrainToOrthogonal(rawCoords, lastPoint)
    } else {
      endCoords = rawCoords
    }
  } else {
    endCoords = rawCoords
  }

  // Add final point
  if (currentPipePoints.value.length >= 1) {
    currentPipePoints.value.push(endCoords)
  }

  // Finish pipe drawing
  if (currentPipePoints.value.length >= 2) {
    const newPipe: PidPipe = {
      id: `pipe-${Date.now()}`,
      points: [...currentPipePoints.value],
      pathType: 'polyline',
      color: store.pidPipeColor,
      strokeWidth: 3,
      dashed: store.pidPipeDashed || undefined,
      animated: store.pidPipeAnimated || undefined,
      // Store connection info if snapped to ports
      startConnection: startConnection.value || undefined,
      endConnection: nearestPort ? {
        symbolId: nearestPort.symbolId,
        portId: nearestPort.portId,
        x: nearestPort.x,
        y: nearestPort.y
      } : undefined
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
  snapTarget.value = null
  startConnection.value = null
}

// Right-click to finish pipe (alternative to double-click)
function onCanvasRightClick(event: MouseEvent) {
  // Prevent browser context menu
  event.preventDefault()

  // If drawing a pipe, right-click finishes it (existing behavior)
  if (props.pipeDrawingMode && isDrawingPipe.value) {
    const rawCoords = getCanvasCoords(event)
    const nearestPort = findNearestPort(rawCoords)

    let endCoords: PidPoint
    if (nearestPort) {
      endCoords = { x: nearestPort.x, y: nearestPort.y }
    } else if (currentPipePoints.value.length > 0) {
      const shouldConstrainOrthogonal = orthogonalPipes.value && !shiftHeld.value
      if (shouldConstrainOrthogonal) {
        const lastPoint = currentPipePoints.value[currentPipePoints.value.length - 1]!
        endCoords = constrainToOrthogonal(rawCoords, lastPoint)
      } else {
        endCoords = rawCoords
      }
    } else {
      endCoords = rawCoords
    }

    if (currentPipePoints.value.length >= 1) {
      currentPipePoints.value.push(endCoords)
    }

    if (currentPipePoints.value.length >= 2) {
      const newPipe: PidPipe = {
        id: `pipe-${Date.now()}`,
        points: [...currentPipePoints.value],
        pathType: 'polyline',
        color: store.pidPipeColor,
        strokeWidth: 3,
        dashed: store.pidPipeDashed || undefined,
        animated: store.pidPipeAnimated || undefined,
        startConnection: startConnection.value || undefined,
        endConnection: nearestPort ? {
          symbolId: nearestPort.symbolId,
          portId: nearestPort.portId,
          x: nearestPort.x,
          y: nearestPort.y
        } : undefined
      }

      emit('update:pidLayer', {
        ...props.pidLayer,
        pipes: [...props.pidLayer.pipes, newPipe]
      })
    }

    isDrawingPipe.value = false
    currentPipePoints.value = []
    tempMousePos.value = null
    snapTarget.value = null
    startConnection.value = null
    return
  }

  // Show context menu in edit mode (not during pipe drawing)
  if (props.editMode && !props.pipeDrawingMode) {
    contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'canvas' } }
  }
}

function onCanvasMouseMove(event: MouseEvent) {
  if (props.pipeDrawingMode) {
    const rawCoords = getCanvasCoords(event)

    // Update snap target for visual feedback (ports highlight in pipe drawing mode)
    snapTarget.value = findNearestPort(rawCoords)

    if (isDrawingPipe.value) {
      // Determine preview position: snap-to-port > orthogonal > raw
      if (snapTarget.value) {
        tempMousePos.value = { x: snapTarget.value.x, y: snapTarget.value.y }
      } else if (currentPipePoints.value.length > 0) {
        // Apply orthogonal constraint by default (Shift disables it)
        const shouldConstrainOrthogonal = orthogonalPipes.value && !shiftHeld.value
        if (shouldConstrainOrthogonal) {
          const lastPoint = currentPipePoints.value[currentPipePoints.value.length - 1]!
          tempMousePos.value = constrainToOrthogonal(rawCoords, lastPoint)
        } else {
          tempMousePos.value = rawCoords
        }
      } else {
        tempMousePos.value = rawCoords
      }
    }
  }
}

function onCanvasKeyDown(event: KeyboardEvent) {
  if (!props.editMode) return

  // Track Shift key for orthogonal constraint
  if (event.key === 'Shift') {
    shiftHeld.value = true
  }

  // Track Space key for pan mode
  if (event.key === ' ') {
    event.preventDefault()
    spaceHeld.value = true
  }

  // Escape cancels pipe drawing
  if (event.key === 'Escape' && isDrawingPipe.value) {
    isDrawingPipe.value = false
    currentPipePoints.value = []
    tempMousePos.value = null
    snapTarget.value = null
    startConnection.value = null
    return
  }

  // Backspace removes last point while drawing pipe
  if (event.key === 'Backspace' && isDrawingPipe.value && currentPipePoints.value.length > 1) {
    event.preventDefault()
    currentPipePoints.value.pop()
    // If we removed the start connection point, clear it
    if (currentPipePoints.value.length === 1) {
      // Keep the first point, but it may still have startConnection
    }
    return
  }

  // Delete selected element (only when not drawing)
  if ((event.key === 'Delete' || event.key === 'Backspace') && !isDrawingPipe.value && (selectedSymbolId.value || selectedPipeId.value)) {
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

function onCanvasKeyUp(event: KeyboardEvent) {
  // Track Shift key release
  if (event.key === 'Shift') {
    shiftHeld.value = false
  }
  if (event.key === ' ') {
    spaceHeld.value = false
  }
}

// Drag-drop symbol from panel
function onCanvasDragOver(event: DragEvent) {
  if (!props.editMode || !event.dataTransfer) return
  if (event.dataTransfer.types.includes('application/x-pid-symbol')) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function onCanvasDrop(event: DragEvent) {
  if (!props.editMode || !event.dataTransfer) return
  const symbolType = event.dataTransfer.getData('application/x-pid-symbol')
  if (!symbolType) return

  const coords = getCanvasCoords(event as unknown as MouseEvent)
  const hmiSize = getHmiDefaultSize(symbolType)
  const w = hmiSize?.width ?? 60
  const h = hmiSize?.height ?? 60
  store.addPidSymbolWithUndo({
    type: symbolType as import('../assets/symbols').ScadaSymbolType,
    x: coords.x - w / 2,
    y: coords.y - h / 2,
    width: w,
    height: h,
    rotation: 0,
    color: hmiSize ? undefined : '#60a5fa',
    showValue: false
  })
}

// Zoom with Ctrl+Wheel (edit-mode only)
function onCanvasWheel(event: WheelEvent) {
  if (!props.editMode) return
  if (!event.ctrlKey) return
  event.preventDefault()

  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return

  // Mouse position relative to the canvas container
  const mouseX = event.clientX - rect.left
  const mouseY = event.clientY - rect.top

  // Current world-space position under cursor
  const worldX = (mouseX - panX.value) / zoom.value
  const worldY = (mouseY - panY.value) / zoom.value

  // Compute new zoom
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  const newZoom = Math.max(0.1, Math.min(5, zoom.value + delta * zoom.value))

  // Adjust pan so the world point under cursor stays fixed
  const newPanX = mouseX - worldX * newZoom
  const newPanY = mouseY - worldY * newZoom

  store.setPidZoom(newZoom)
  store.setPidPan(newPanX, newPanY)
}

// Start panning (middle-mouse or Space+left-click)
function onPanStart(event: MouseEvent) {
  if (!props.editMode) return

  // Middle mouse button (button 1) or Space+left-click
  const isMiddleButton = event.button === 1
  const isSpaceDrag = spaceHeld.value && event.button === 0

  if (!isMiddleButton && !isSpaceDrag) return

  event.preventDefault()
  isPanning.value = true
  panStart.value = {
    x: event.clientX,
    y: event.clientY,
    panX: store.pidPanX,
    panY: store.pidPanY
  }

  window.addEventListener('mousemove', onPanMove)
  window.addEventListener('mouseup', onPanEnd)
}

function onPanMove(event: MouseEvent) {
  if (!isPanning.value) return
  const dx = event.clientX - panStart.value.x
  const dy = event.clientY - panStart.value.y
  store.setPidPan(panStart.value.panX + dx, panStart.value.panY + dy)
}

function onPanEnd() {
  isPanning.value = false
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
}

// ISA-5.1 line coding: dash patterns by lineCode, dashPattern, or explicit dashed flag
function getPipeDashArray(pipe: PidPipe): string | undefined {
  // Custom dash pattern takes highest priority
  if (pipe.dashPattern) return pipe.dashPattern
  // Explicit dashed toggle
  if (pipe.dashed) return '8,4'
  // ISA-5.1 patterns only when lineCode is explicitly set
  if (pipe.lineCode) {
    switch (pipe.lineCode) {
      case 'pneumatic':   return '8,3,2,3,2,3'  // Dash-dot-dot
      case 'hydraulic':   return '16,4'          // Extra-long dash
      case 'electrical':  return '2,4'           // Dotted
      case 'capillary':   return '2,2'           // Fine dots
      case 'signal':      return '2,6'           // Wide-spaced dots
      default:            return undefined
    }
  }
  // No dash — solid line is the default
  return undefined
}

// Resolve arrow type from PidArrowType | boolean for backwards compat
function resolveArrowType(val: PidArrowType | boolean | undefined): PidArrowType {
  if (val === true) return 'arrow'
  if (!val) return 'none'
  return val as PidArrowType
}

// Collect unique marker definitions needed by all pipes
const pipeMarkerDefs = computed(() => {
  const defs: { id: string; type: PidArrowType; endpoint: 'start' | 'end'; color: string }[] = []
  const seen = new Set<string>()
  for (const pipe of props.pidLayer.pipes) {
    const color = pipe.color || '#60a5fa'
    const startType = resolveArrowType(pipe.startArrow)
    const endType = resolveArrowType(pipe.endArrow)
    if (startType !== 'none') {
      const id = `marker-${startType}-start-${color.replace('#', '')}`
      if (!seen.has(id)) { seen.add(id); defs.push({ id, type: startType, endpoint: 'start', color }) }
    }
    if (endType !== 'none') {
      const id = `marker-${endType}-end-${color.replace('#', '')}`
      if (!seen.has(id)) { seen.add(id); defs.push({ id, type: endType, endpoint: 'end', color }) }
    }
  }
  return defs
})

// Get marker URL for a pipe endpoint
function getMarkerUrl(pipe: PidPipe, endpoint: 'start' | 'end'): string | undefined {
  const arrowType = resolveArrowType(endpoint === 'start' ? pipe.startArrow : pipe.endArrow)
  if (arrowType === 'none') return undefined
  const color = (pipe.color || '#60a5fa').replace('#', '')
  return `url(#marker-${arrowType}-${endpoint}-${color})`
}

// Compute pipe label position along the path
function getPipeLabelPoint(pipe: PidPipe): PidPoint | null {
  if (pipe.points.length < 2) return null
  const position = pipe.labelPosition || 'middle'
  if (position === 'start') return pipe.points[0]!
  if (position === 'end') return pipe.points[pipe.points.length - 1]!
  // 'middle': walk segments to find the halfway distance point
  let totalLen = 0
  const segments: { from: PidPoint; to: PidPoint; len: number }[] = []
  for (let i = 1; i < pipe.points.length; i++) {
    const from = pipe.points[i - 1]!
    const to = pipe.points[i]!
    const len = Math.hypot(to.x - from.x, to.y - from.y)
    segments.push({ from, to, len })
    totalLen += len
  }
  const halfDist = totalLen / 2
  let walked = 0
  for (const seg of segments) {
    if (walked + seg.len >= halfDist) {
      const t = seg.len > 0 ? (halfDist - walked) / seg.len : 0
      return {
        x: seg.from.x + t * (seg.to.x - seg.from.x),
        y: seg.from.y + t * (seg.to.y - seg.from.y)
      }
    }
    walked += seg.len
  }
  return pipe.points[Math.floor(pipe.points.length / 2)]!
}

// Get pipe flow state from channel binding
function getPipeFlowState(pipe: PidPipe): {
  animated: boolean
  speed: number
  direction: 'forward' | 'reverse' | 'stopped'
} {
  // Check if pipe has flow channel binding
  if (pipe.flowChannel) {
    const value = store.values[pipe.flowChannel]
    if (value && typeof value.value === 'number') {
      // Positive value = forward, negative = reverse, zero = stopped
      if (value.value > 0) {
        return {
          animated: true,
          speed: Math.min(3, value.value / 10) || 1,  // Scale speed
          direction: 'forward'
        }
      } else if (value.value < 0) {
        return {
          animated: true,
          speed: Math.min(3, Math.abs(value.value) / 10) || 1,
          direction: 'reverse'
        }
      } else {
        return { animated: false, speed: 0, direction: 'stopped' }
      }
    }
  }

  // Use static settings
  return {
    animated: pipe.animated || false,
    speed: pipe.flowSpeed || 1,
    direction: pipe.flowDirection || 'forward'
  }
}

// Get animation duration based on speed
function getFlowAnimationDuration(speed: number): string {
  // Speed 1 = 1s, Speed 2 = 0.5s, etc.
  const duration = 1 / Math.max(0.1, speed)
  return `${duration}s`
}

// Line segment intersection detection for line jumps
function segmentIntersection(
  p1: PidPoint, p2: PidPoint, p3: PidPoint, p4: PidPoint
): PidPoint | null {
  const denom = (p4.y - p3.y) * (p2.x - p1.x) - (p4.x - p3.x) * (p2.y - p1.y)
  if (Math.abs(denom) < 1e-10) return null
  const ua = ((p4.x - p3.x) * (p1.y - p3.y) - (p4.y - p3.y) * (p1.x - p3.x)) / denom
  const ub = ((p2.x - p1.x) * (p1.y - p3.y) - (p2.y - p1.y) * (p1.x - p3.x)) / denom
  if (ua < 0.01 || ua > 0.99 || ub < 0.01 || ub > 0.99) return null
  return { x: p1.x + ua * (p2.x - p1.x), y: p1.y + ua * (p2.y - p1.y) }
}

// Generate pipe path with line jumps (arc or gap) at crossing points
function generatePipePathWithJumps(pipe: PidPipe): string {
  if (!pipe.jumpStyle || pipe.jumpStyle === 'none') return generatePipePath(pipe)
  if (pipe.points.length < 2) return ''

  const jumpR = (pipe.jumpSize || 8) / 2
  const otherPipes = props.pidLayer.pipes.filter(p => p.id !== pipe.id)

  // Collect all other pipes' segments
  const otherSegments: { from: PidPoint; to: PidPoint }[] = []
  for (const op of otherPipes) {
    for (let i = 0; i < op.points.length - 1; i++) {
      otherSegments.push({ from: op.points[i]!, to: op.points[i + 1]! })
    }
  }

  let path = ''
  for (let i = 0; i < pipe.points.length - 1; i++) {
    const segA = pipe.points[i]!
    const segB = pipe.points[i + 1]!

    // Find all intersections on this segment
    const hits: { t: number; pt: PidPoint }[] = []
    for (const os of otherSegments) {
      const pt = segmentIntersection(segA, segB, os.from, os.to)
      if (pt) {
        const dx = pt.x - segA.x, dy = pt.y - segA.y
        const t = Math.hypot(dx, dy) / Math.hypot(segB.x - segA.x, segB.y - segA.y)
        hits.push({ t, pt })
      }
    }
    hits.sort((a, b) => a.t - b.t)

    if (i === 0) path += `M ${segA.x} ${segA.y}`

    if (hits.length === 0) {
      path += ` L ${segB.x} ${segB.y}`
    } else {
      // Walk segment, inserting jumps at each intersection
      const segDx = segB.x - segA.x, segDy = segB.y - segA.y
      const segLen = Math.hypot(segDx, segDy)
      const ux = segDx / segLen, uy = segDy / segLen

      let lastX = segA.x, lastY = segA.y
      for (const hit of hits) {
        const beforeX = hit.pt.x - ux * jumpR
        const beforeY = hit.pt.y - uy * jumpR
        const afterX = hit.pt.x + ux * jumpR
        const afterY = hit.pt.y + uy * jumpR

        path += ` L ${beforeX} ${beforeY}`
        if (pipe.jumpStyle === 'arc') {
          // Semicircular arc over the crossing
          path += ` A ${jumpR} ${jumpR} 0 0 1 ${afterX} ${afterY}`
        } else {
          // Gap: move without drawing
          path += ` M ${afterX} ${afterY}`
        }
        lastX = afterX
        lastY = afterY
      }
      path += ` L ${segB.x} ${segB.y}`
    }
  }
  return path
}

// Generate rounded polyline path with curved corners
function generateRoundedPolylinePath(points: PidPoint[], radius: number): string {
  if (points.length < 2) return ''
  let path = `M ${points[0]!.x} ${points[0]!.y}`

  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1]!
    const curr = points[i]!
    const next = points[i + 1]!

    const dx1 = prev.x - curr.x, dy1 = prev.y - curr.y
    const dx2 = next.x - curr.x, dy2 = next.y - curr.y
    const len1 = Math.hypot(dx1, dy1)
    const len2 = Math.hypot(dx2, dy2)

    if (len1 < 1 || len2 < 1) {
      path += ` L ${curr.x} ${curr.y}`
      continue
    }

    // Clamp radius to half the shorter adjacent segment
    const r = Math.min(radius, len1 / 2, len2 / 2)

    const entryX = curr.x + (dx1 / len1) * r
    const entryY = curr.y + (dy1 / len1) * r
    const exitX = curr.x + (dx2 / len2) * r
    const exitY = curr.y + (dy2 / len2) * r

    path += ` L ${entryX} ${entryY}`
    path += ` Q ${curr.x} ${curr.y} ${exitX} ${exitY}`
  }

  const last = points[points.length - 1]!
  path += ` L ${last.x} ${last.y}`
  return path
}

// Generate SVG path for pipe
function generatePipePath(pipe: PidPipe): string {
  if (pipe.points.length < 2) return ''

  const first = pipe.points[0]!
  let path = `M ${first.x} ${first.y}`

  if (pipe.pathType === 'bezier' && pipe.points.length >= 3) {
    // Catmull-Rom to cubic Bezier for smooth curves through all waypoints
    const pts = pipe.points
    const tension = 6
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)]!
      const p1 = pts[i]!
      const p2 = pts[i + 1]!
      const p3 = pts[Math.min(pts.length - 1, i + 2)]!

      const cp1x = p1.x + (p2.x - p0.x) / tension
      const cp1y = p1.y + (p2.y - p0.y) / tension
      const cp2x = p2.x - (p3.x - p1.x) / tension
      const cp2y = p2.y - (p3.y - p1.y) / tension

      path += ` C ${cp1x} ${cp1y} ${cp2x} ${cp2y} ${p2.x} ${p2.y}`
    }
  } else if (pipe.pathType === 'orthogonal') {
    // Build full list of orthogonal waypoints (including intermediate right-angle points)
    const waypoints: PidPoint[] = [first]
    for (let i = 1; i < pipe.points.length; i++) {
      const prev = pipe.points[i - 1]!
      const curr = pipe.points[i]!
      if (prev.x !== curr.x && prev.y !== curr.y) {
        waypoints.push({ x: curr.x, y: prev.y })
      }
      waypoints.push(curr)
    }

    if (pipe.rounded && waypoints.length >= 3) {
      path = generateRoundedPolylinePath(waypoints, pipe.cornerRadius || 8)
    } else {
      for (const wp of waypoints.slice(1)) {
        path += ` L ${wp.x} ${wp.y}`
      }
    }
  } else {
    // Polyline (straight segments)
    if (pipe.rounded && pipe.points.length >= 3) {
      path = generateRoundedPolylinePath(pipe.points, pipe.cornerRadius || 8)
    } else {
      for (let i = 1; i < pipe.points.length; i++) {
        const p = pipe.points[i]!
        path += ` L ${p.x} ${p.y}`
      }
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

// Reactive ruler drawing
watchEffect(() => {
  if (!showRulers.value || !props.editMode) return
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  drawRuler(rulerHCanvas.value, 'h', zoom.value, panX.value, rect.width - RULER_SIZE)
  drawRuler(rulerVCanvas.value, 'v', zoom.value, panY.value, rect.height - RULER_SIZE)
})

</script>

<template>
  <div
    ref="canvasRef"
    class="pid-canvas"
    :class="{
      'edit-mode': editMode,
      'drawing-mode': pipeDrawingMode,
      'ortho-mode': shiftHeld && pipeDrawingMode,
      'panning': isPanning || spaceHeld
    }"
    tabindex="0"
    @mousedown="onCanvasMouseDown"
    @click="onCanvasClick"
    @dblclick="onCanvasDoubleClick"
    @contextmenu="onCanvasRightClick"
    @mousemove="onCanvasMouseMove"
    @keydown="onCanvasKeyDown"
    @keyup="onCanvasKeyUp"
    @wheel="onCanvasWheel"
    @dragover.prevent="onCanvasDragOver"
    @drop.prevent="onCanvasDrop"
  >
    <!-- Rulers (fixed position, outside viewport transform) -->
    <div v-if="editMode && showRulers" class="ruler ruler-h" @mousedown.prevent="onRulerMouseDown($event, 'h')">
      <canvas ref="rulerHCanvas" />
    </div>
    <div v-if="editMode && showRulers" class="ruler ruler-v" @mousedown.prevent="onRulerMouseDown($event, 'v')">
      <canvas ref="rulerVCanvas" />
    </div>
    <div v-if="editMode && showRulers" class="ruler-corner" />

    <!-- Zoom/Pan viewport (transforms all content; edit-mode only) -->
    <div
      ref="viewportRef"
      class="pid-viewport"
      :style="{
        transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
        transformOrigin: '0 0'
      }"
    >
    <!-- Background image -->
    <img
      v-if="pidLayer.backgroundImage"
      :src="pidLayer.backgroundImage.url"
      class="background-image"
      :style="{
        left: `${pidLayer.backgroundImage.x}px`,
        top: `${pidLayer.backgroundImage.y}px`,
        width: `${pidLayer.backgroundImage.width}px`,
        height: `${pidLayer.backgroundImage.height}px`,
        opacity: pidLayer.backgroundImage.opacity
      }"
      draggable="false"
    />

    <!-- Grid overlay (when snap-to-grid is enabled) -->
    <svg v-if="showGrid && editMode" class="grid-layer">
      <defs>
        <pattern
          id="pid-grid"
          :width="gridSize"
          :height="gridSize"
          patternUnits="userSpaceOnUse"
        >
          <path
            :d="`M ${gridSize} 0 L 0 0 0 ${gridSize}`"
            fill="none"
            stroke="rgba(96, 165, 250, 0.15)"
            stroke-width="0.5"
          />
        </pattern>
        <pattern
          id="pid-grid-major"
          :width="gridSize * 5"
          :height="gridSize * 5"
          patternUnits="userSpaceOnUse"
        >
          <rect :width="gridSize * 5" :height="gridSize * 5" fill="url(#pid-grid)" />
          <path
            :d="`M ${gridSize * 5} 0 L 0 0 0 ${gridSize * 5}`"
            fill="none"
            stroke="rgba(96, 165, 250, 0.3)"
            stroke-width="1"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#pid-grid-major)" />
    </svg>

    <!-- Pipes (SVG layer) -->
    <svg class="pipes-layer">
      <!-- Arrow marker definitions -->
      <defs>
        <template v-for="def in pipeMarkerDefs" :key="def.id">
          <!-- Arrow (filled triangle) -->
          <marker v-if="def.type === 'arrow'" :id="def.id"
            viewBox="0 0 10 10" markerWidth="8" markerHeight="8"
            :refX="def.endpoint === 'end' ? 9 : 1" refY="5"
            orient="auto-start-reverse" markerUnits="strokeWidth">
            <polygon :points="def.endpoint === 'end' ? '0,1 10,5 0,9' : '10,1 0,5 10,9'" :fill="def.color" />
          </marker>
          <!-- Open (unfilled triangle) -->
          <marker v-else-if="def.type === 'open'" :id="def.id"
            viewBox="0 0 10 10" markerWidth="8" markerHeight="8"
            :refX="def.endpoint === 'end' ? 9 : 1" refY="5"
            orient="auto-start-reverse" markerUnits="strokeWidth">
            <polyline :points="def.endpoint === 'end' ? '0,1 10,5 0,9' : '10,1 0,5 10,9'"
              fill="none" :stroke="def.color" stroke-width="1.5" />
          </marker>
          <!-- Dot (filled circle) -->
          <marker v-else-if="def.type === 'dot'" :id="def.id"
            viewBox="0 0 10 10" markerWidth="6" markerHeight="6"
            refX="5" refY="5" orient="auto-start-reverse" markerUnits="strokeWidth">
            <circle cx="5" cy="5" r="4" :fill="def.color" />
          </marker>
          <!-- Diamond (filled diamond) -->
          <marker v-else-if="def.type === 'diamond'" :id="def.id"
            viewBox="0 0 12 12" markerWidth="8" markerHeight="8"
            refX="6" refY="6" orient="auto-start-reverse" markerUnits="strokeWidth">
            <polygon points="6,0 12,6 6,12 0,6" :fill="def.color" />
          </marker>
          <!-- Bar (perpendicular line) -->
          <marker v-else-if="def.type === 'bar'" :id="def.id"
            viewBox="0 0 4 10" markerWidth="4" markerHeight="8"
            refX="2" refY="5" orient="auto-start-reverse" markerUnits="strokeWidth">
            <line x1="2" y1="0" x2="2" y2="10" :stroke="def.color" stroke-width="2" />
          </marker>
        </template>
      </defs>
      <!-- Existing pipes (filtered by layer visibility) -->
      <g v-for="pipe in visiblePipes" :key="pipe.id" class="pipe-group">
        <!-- Wider invisible hit area for easier clicking -->
        <path
          :d="generatePipePath(pipe)"
          stroke="transparent"
          stroke-width="12"
          fill="none"
          class="pipe-hit-area"
          @mousedown.stop="onPipeMouseDown($event, pipe)"
          @dblclick.stop="onPipeDoubleClick($event, pipe)"
          @contextmenu.prevent.stop="onPipeRightClick($event, pipe)"
        />
        <!-- Visible pipe -->
        <path
          :d="generatePipePathWithJumps(pipe)"
          :stroke="pipe.color || '#60a5fa'"
          :stroke-width="pipe.strokeWidth || 3"
          :stroke-opacity="pipe.opacity ?? 1"
          :stroke-dasharray="getPipeDashArray(pipe)"
          :marker-start="getMarkerUrl(pipe, 'start')"
          :marker-end="getMarkerUrl(pipe, 'end')"
          stroke-linecap="round"
          stroke-linejoin="round"
          fill="none"
          class="pipe-path"
          :class="{ selected: selectedPipeId === pipe.id, dragging: draggingSegment?.pipeId === pipe.id }"
          pointer-events="none"
        />

        <!-- Flow animation (enhanced) -->
        <path
          v-if="getPipeFlowState(pipe).animated"
          :d="generatePipePath(pipe)"
          stroke="rgba(255,255,255,0.6)"
          :stroke-width="(pipe.strokeWidth || 3) - 1"
          stroke-dasharray="8,8"
          stroke-linecap="round"
          fill="none"
          class="pipe-flow-animation"
          :class="{ reverse: getPipeFlowState(pipe).direction === 'reverse' }"
          :style="{
            animationDuration: getFlowAnimationDuration(getPipeFlowState(pipe).speed)
          }"
        />
        <!-- Secondary flow particles for better visibility -->
        <path
          v-if="getPipeFlowState(pipe).animated"
          :d="generatePipePath(pipe)"
          stroke="rgba(96, 165, 250, 0.4)"
          :stroke-width="(pipe.strokeWidth || 3) + 2"
          stroke-dasharray="2,20"
          stroke-linecap="round"
          fill="none"
          class="pipe-flow-particles"
          :class="{ reverse: getPipeFlowState(pipe).direction === 'reverse' }"
          :style="{
            animationDuration: getFlowAnimationDuration(getPipeFlowState(pipe).speed * 0.8)
          }"
        />

        <!-- Pipe label (double-click to edit inline) -->
        <g v-if="pipe.label && getPipeLabelPoint(pipe)" class="pipe-label-group"
          :class="{ 'editable': editMode }"
          @dblclick.stop="onPipeLabelDblClick($event, pipe)">
          <rect
            :x="getPipeLabelPoint(pipe)!.x - (pipe.label.length * 3.5 + 6) / zoom"
            :y="getPipeLabelPoint(pipe)!.y - 8 / zoom"
            :width="(pipe.label.length * 7 + 12) / zoom"
            :height="16 / zoom"
            :rx="3 / zoom"
            fill="rgba(15, 15, 26, 0.85)"
            class="pipe-label-bg"
          />
          <text
            :x="getPipeLabelPoint(pipe)!.x"
            :y="getPipeLabelPoint(pipe)!.y"
            text-anchor="middle"
            dominant-baseline="central"
            :fill="pipe.color || '#60a5fa'"
            :font-size="12 / zoom"
            class="pipe-label-text"
          >{{ pipe.label }}</text>
        </g>

        <!-- Pipe points (edit mode only; counter-scaled for zoom) -->
        <g v-if="editMode && selectedPipeId === pipe.id" class="pipe-points">
          <circle
            v-for="(point, idx) in pipe.points"
            :key="idx"
            :cx="point.x"
            :cy="point.y"
            :r="6 / zoom"
            class="pipe-point"
            :class="{ 'first': idx === 0, 'last': idx === pipe.points.length - 1 }"
            :stroke-width="2 / zoom"
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

      <!-- Drawing points (counter-scaled for zoom) -->
      <g v-if="isDrawingPipe">
        <circle
          v-for="(point, idx) in currentPipePoints"
          :key="idx"
          :cx="point.x"
          :cy="point.y"
          :r="5 / zoom"
          fill="#22c55e"
          stroke="#fff"
          :stroke-width="2 / zoom"
        />
      </g>

      <!-- User guide lines -->
      <g v-if="editMode" class="guide-lines">
        <line
          v-for="guide in (pidLayer.guides || [])"
          :key="guide.id"
          :x1="guide.axis === 'v' ? guide.position : -10000"
          :y1="guide.axis === 'h' ? guide.position : -10000"
          :x2="guide.axis === 'v' ? guide.position : 10000"
          :y2="guide.axis === 'h' ? guide.position : 10000"
          class="guide-line"
          :stroke-width="1 / zoom"
          stroke-dasharray="4,4"
          @mousedown.stop="onGuideMouseDown($event, guide)"
        />
        <!-- Dragging guide preview -->
        <line
          v-if="draggingGuide"
          :x1="draggingGuide.axis === 'v' ? draggingGuide.position : -10000"
          :y1="draggingGuide.axis === 'h' ? draggingGuide.position : -10000"
          :x2="draggingGuide.axis === 'v' ? draggingGuide.position : 10000"
          :y2="draggingGuide.axis === 'h' ? draggingGuide.position : 10000"
          class="guide-line dragging"
          :stroke-width="1 / zoom"
          stroke-dasharray="4,4"
        />
      </g>

      <!-- Nozzle stubs (always visible in edit mode for equipment-type symbols) -->
      <g v-if="editMode && nozzleStubs.length" class="nozzle-stubs">
        <g v-for="stub in nozzleStubs" :key="`stub-${stub.symbolId}-${stub.portId}`">
          <line
            :x1="stub.x1" :y1="stub.y1" :x2="stub.x2" :y2="stub.y2"
            :stroke="stub.color" :stroke-width="2 / zoom" stroke-linecap="round"
            class="nozzle-stub-line"
          />
          <line
            :x1="stub.capX1" :y1="stub.capY1" :x2="stub.capX2" :y2="stub.capY2"
            :stroke="stub.color" :stroke-width="2 / zoom" stroke-linecap="round"
            class="nozzle-stub-cap"
          />
        </g>
      </g>

      <!-- Port indicators (shown when drawing pipes or hovering in edit mode) -->
      <g v-if="pipeDrawingMode || (editMode && hoveredSymbolId)" class="port-indicators">
        <g v-for="symbol in visibleSymbols" :key="`ports-${symbol.id}`">
          <template v-if="pipeDrawingMode || hoveredSymbolId === symbol.id">
            <circle
              v-for="port in getSymbolPorts(symbol)"
              :key="port.id"
              :cx="port.x"
              :cy="port.y"
              :r="(pipeDrawingMode ? 6 : 4) / zoom"
              class="port-indicator"
              :class="{
                'snap-active': snapTarget?.symbolId === symbol.id && snapTarget?.portId === port.id,
                'custom-port': port.isCustom,
                'hover-port': !pipeDrawingMode
              }"
              :stroke-width="(pipeDrawingMode ? 2 : 1.5) / zoom"
            />
          </template>
        </g>
      </g>

      <!-- Snap highlight (counter-scaled for zoom) -->
      <circle
        v-if="snapTarget"
        :cx="snapTarget.x"
        :cy="snapTarget.y"
        :r="12 / zoom"
        class="snap-highlight"
        :stroke-width="2 / zoom"
      />

      <!-- Alignment guides -->
      <line
        v-for="(guide, gi) in activeGuides"
        :key="'ag-' + gi"
        :x1="guide.axis === 'v' ? guide.pos : guide.from"
        :y1="guide.axis === 'h' ? guide.pos : guide.from"
        :x2="guide.axis === 'v' ? guide.pos : guide.to"
        :y2="guide.axis === 'h' ? guide.pos : guide.to"
        class="alignment-guide"
        :stroke-width="0.5 / zoom"
      />

      <!-- Group bounding boxes (visible in edit mode) -->
      <g v-if="editMode" class="group-indicators">
        <rect
          v-for="group in visibleGroups"
          :key="group.id"
          :x="group.x - 4"
          :y="group.y - 4"
          :width="group.width + 8"
          :height="group.height + 8"
          class="group-box"
          :stroke-width="1 / zoom"
          :class="{ 'group-selected': isGroupSelected(group.id) }"
        />
      </g>
    </svg>

    <!-- Symbols (positioned divs, filtered by layer visibility) -->
    <div
      v-for="symbol in visibleSymbols"
      :key="symbol.id"
      class="pid-symbol"
      :class="{
        selected: selectedSymbolId === symbol.id,
        'has-channel': !!symbol.channel
      }"
      :style="getSymbolStyle(symbol)"
      @mousedown="onSymbolMouseDown($event, symbol)"
      @dblclick="onSymbolDoubleClick($event, symbol)"
      @contextmenu.prevent="onSymbolRightClick($event, symbol)"
      @mouseenter="hoveredSymbolId = symbol.id"
      @mouseleave="hoveredSymbolId = null"
    >
      <!-- HMI Control (HTML component) -->
      <template v-if="isHmiControl(symbol.type)">
        <component
          :is="getHmiComponent(symbol.type)"
          :symbol="symbol"
          :edit-mode="editMode"
        />
      </template>
      <!-- Off-Page Connector (label inside pentagon) -->
      <template v-else-if="OFF_PAGE_CONNECTOR_TYPES.has(symbol.type)">
        <div
          class="symbol-svg"
          :style="{ color: symbol.color || '#60a5fa' }"
          v-html="getSymbolSvg(symbol.type)"
        />
        <div class="offpage-label" :class="{ 'not-linked': editMode && !symbol.linkedPageId }">
          {{ symbol.label || '?' }}
        </div>
      </template>
      <!-- Process Symbol SVG (with tank fill support) -->
      <template v-else>
        <div
          class="symbol-svg"
          :style="{ color: symbol.color || '#60a5fa' }"
          v-html="symbol.type.toLowerCase().includes('tank') || symbol.type === 'reactor'
            ? getTankSvgWithFill(symbol)
            : getSymbolSvg(symbol.type)"
        />

        <!-- Label -->
        <div v-if="symbol.label" class="symbol-label">{{ symbol.label }}</div>

        <!-- Value -->
        <div v-if="symbol.showValue && symbol.channel" class="symbol-value">
          {{ getSymbolValue(symbol) }}
        </div>
      </template>

      <!-- Resize handles (only visible in edit mode when selected; counter-scaled for zoom) -->
      <template v-if="editMode && selectedSymbolId === symbol.id">
        <div class="resize-handle nw" data-handle="nw" :style="{ transform: `scale(${1/zoom})` }" />
        <div class="resize-handle ne" data-handle="ne" :style="{ transform: `scale(${1/zoom})` }" />
        <div class="resize-handle sw" data-handle="sw" :style="{ transform: `scale(${1/zoom})` }" />
        <div class="resize-handle se" data-handle="se" :style="{ transform: `scale(${1/zoom})` }" />
      </template>
    </div>

    <!-- Text Annotations (filtered by layer visibility) -->
    <div
      v-for="text in visibleTextAnnotations"
      :key="text.id"
      class="pid-text-annotation"
      :class="{
        selected: store.pidSelectedIds.textAnnotationIds.includes(text.id)
      }"
      :style="{
        left: `${text.x}px`,
        top: `${text.y}px`,
        fontSize: `${text.fontSize}px`,
        fontWeight: text.fontWeight || 'normal',
        color: text.color || '#333',
        backgroundColor: text.backgroundColor || 'transparent',
        transform: text.rotation ? `rotate(${text.rotation}deg)` : undefined,
        textAlign: text.textAlign || 'left',
        zIndex: String(text.zIndex || 2),
        border: text.border ? `1px solid ${text.borderColor || '#888'}` : 'none',
        padding: text.border ? '2px 6px' : undefined
      }"
      @mousedown.stop="onTextAnnotationMouseDown($event, text)"
      @dblclick.stop="onTextAnnotationDblClick($event, text)"
    >{{ text.text }}</div>

    </div><!-- /pid-viewport -->

    <!-- Minimap (edit-mode only) -->
    <div v-if="editMode && showMinimap" class="pid-minimap" @mousedown.stop="onMinimapMouseDown">
      <svg :viewBox="minimapViewBox" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
        <!-- Symbol rectangles -->
        <rect
          v-for="sym in pidLayer.symbols"
          :key="'mm-' + sym.id"
          :x="sym.x" :y="sym.y" :width="sym.width" :height="sym.height"
          :fill="sym.color || '#60a5fa'" fill-opacity="0.6" stroke="none" rx="2"
        />
        <!-- Pipe polylines -->
        <polyline
          v-for="pipe in pidLayer.pipes"
          :key="'mm-' + pipe.id"
          :points="pipe.points.map(p => `${p.x},${p.y}`).join(' ')"
          fill="none" :stroke="pipe.color || '#94a3b8'" stroke-width="2" stroke-opacity="0.6"
        />
        <!-- Viewport rectangle -->
        <rect
          :x="minimapViewport.x" :y="minimapViewport.y"
          :width="minimapViewport.w" :height="minimapViewport.h"
          fill="rgba(59,130,246,0.1)" stroke="#3b82f6" stroke-width="2" rx="1"
        />
      </svg>
    </div>

    <!-- Drawing mode indicator -->
    <div v-if="pipeDrawingMode" class="drawing-indicator" :class="{ 'ortho-active': shiftHeld }">
      <span v-if="!isDrawingPipe">Click to start pipe • Hold Shift for orthogonal</span>
      <span v-else-if="shiftHeld">⊥ Orthogonal mode • Click to add • Right-click or double-click to finish</span>
      <span v-else>Click to add bend • Backspace to undo • Right-click/double-click to finish • Shift for H/V</span>
    </div>

    <!-- Edit mode help -->
    <div v-if="editMode && !pipeDrawingMode && selectedPipeId" class="edit-indicator">
      <span>Drag segment to shift • Right-click point to delete • Del to remove pipe</span>
    </div>

    <!-- Marquee Selection Rectangle -->
    <div
      v-if="isMarqueeSelecting && marqueeStyle"
      class="marquee-selection"
      :style="marqueeStyle"
    />

    <!-- Inline Label Edit Overlay -->
    <Teleport to="body">
      <input
        v-if="inlineEditTarget"
        ref="inlineEditInput"
        v-model="inlineEditValue"
        class="pid-inline-edit-input"
        :style="{ left: `${inlineEditPos.x}px`, top: `${inlineEditPos.y}px` }"
        @keydown.enter.prevent="commitInlineEdit"
        @keydown.escape.prevent="cancelInlineEdit"
        @blur="commitInlineEdit"
      />
    </Teleport>

    <!-- Context Menu (Edit Mode) -->
    <PidContextMenu
      v-if="contextMenu"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :target="contextMenu.target"
      :hasStyleClipboard="!!store.pidStyleClipboard"
      @action="handleContextMenuAction"
      @close="contextMenu = null"
    />

    <!-- Faceplate Popup (Runtime Mode) -->
    <Teleport to="body">
      <PidFaceplate
        v-if="showFaceplate && faceplateSymbol"
        :symbol="faceplateSymbol"
        :position="faceplatePosition"
        @close="closeFaceplate"
        @control="handleFaceplateControl"
      />
    </Teleport>

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

            <!-- Connection Ports -->
            <div class="form-divider"></div>
            <div class="form-section-title">Connection Ports</div>

            <!-- Built-in ports with visibility toggles -->
            <div v-if="builtInPortsForConfig.length > 0" class="ports-list">
              <div class="ports-subsection">Built-in</div>
              <div
                v-for="port in builtInPortsForConfig"
                :key="port.id"
                class="port-item builtin"
              >
                <label class="port-toggle">
                  <input
                    type="checkbox"
                    :checked="!configForm.hiddenPorts.includes(port.id)"
                    @change="toggleBuiltInPort(port.id)"
                  />
                  <span class="port-name">{{ port.id }}</span>
                  <span class="port-dir">({{ port.direction }})</span>
                </label>
              </div>
            </div>

            <!-- Custom ports list -->
            <div v-if="configForm.customPorts.length > 0" class="ports-list">
              <div class="ports-subsection">Custom</div>
              <div
                v-for="port in configForm.customPorts"
                :key="port.id"
                class="port-item custom"
              >
                <span class="port-info">{{ getPortPositionLabel(port) }}</span>
                <button
                  type="button"
                  class="btn-remove-port"
                  @click="removeCustomPort(port.id)"
                  title="Remove port"
                >
                  ×
                </button>
              </div>
            </div>

            <!-- Add new port controls -->
            <div class="add-port-controls">
              <div class="form-group">
                <label>Edge</label>
                <select v-model="newPortDirection" class="form-select">
                  <option value="left">Left</option>
                  <option value="right">Right</option>
                  <option value="top">Top</option>
                  <option value="bottom">Bottom</option>
                </select>
              </div>
              <div class="form-group">
                <label>Position ({{ newPortPosition }}%)</label>
                <input
                  v-model.number="newPortPosition"
                  type="range"
                  min="0"
                  max="100"
                  class="form-range"
                />
              </div>
              <button type="button" class="btn btn-add-port" @click="addCustomPort">
                + Add Port
              </button>
            </div>

            <!-- Tank Fill Options -->
            <template v-if="isTankSymbol(configSymbol)">
              <div class="form-divider"></div>
              <div class="form-section-title">Tank Fill Level</div>

              <div class="form-group">
                <label>Fill Level Channel</label>
                <select v-model="configForm.fillChannel" class="form-select">
                  <option value="">-- Static Level --</option>
                  <option v-for="ch in availableChannels" :key="ch.name" :value="ch.name">
                    {{ ch.name }} ({{ ch.unit || ch.type }})
                  </option>
                </select>
              </div>

              <div class="form-group" v-if="!configForm.fillChannel">
                <label>Static Fill Level (%)</label>
                <input
                  v-model.number="configForm.fillLevel"
                  type="range"
                  min="0"
                  max="100"
                  class="form-range"
                />
                <span class="range-value">{{ configForm.fillLevel }}%</span>
              </div>

              <div class="form-group">
                <label>Fill Color</label>
                <input
                  v-model="configForm.fillColor"
                  type="color"
                  class="form-color"
                />
              </div>
            </template>
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
  overflow: hidden;
}

.pid-canvas.edit-mode {
  pointer-events: auto;
}

.pid-canvas.drawing-mode {
  cursor: crosshair;
}

.pid-canvas.panning {
  cursor: grab;
}

.pid-canvas.panning:active {
  cursor: grabbing;
}

.pid-viewport {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  will-change: transform;
}

/* Marquee (rubber-band) selection rectangle */
.marquee-selection {
  position: absolute;
  border: 2px dashed #60a5fa;
  background: rgba(96, 165, 250, 0.15);
  pointer-events: none;
  z-index: 9999;
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.3);
}

.grid-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
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
  animation: flow-forward 1s linear infinite;
  pointer-events: none;
}

.pipe-flow-animation.reverse {
  animation-name: flow-reverse;
}

.pipe-flow-particles {
  animation: flow-forward 1.2s linear infinite;
  pointer-events: none;
}

.pipe-flow-particles.reverse {
  animation-name: flow-reverse;
}

@keyframes flow-forward {
  0% { stroke-dashoffset: 16; }
  100% { stroke-dashoffset: 0; }
}

@keyframes flow-reverse {
  0% { stroke-dashoffset: 0; }
  100% { stroke-dashoffset: 16; }
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

.pipe-label-text {
  pointer-events: none;
  font-family: system-ui, -apple-system, sans-serif;
  font-weight: 500;
}

.pipe-label-bg {
  pointer-events: none;
}

.pipe-label-group.editable {
  cursor: text;
}

.pipe-label-group.editable .pipe-label-bg,
.pipe-label-group.editable .pipe-label-text {
  pointer-events: auto;
}

.drawing-preview {
  pointer-events: none;
}

/* Port indicators for snap-to-port */
.port-indicator {
  fill: rgba(59, 130, 246, 0.3);
  stroke: #3b82f6;
  stroke-width: 2;
  pointer-events: none;
  transition: all 0.15s;
}

/* Nozzle stubs on equipment symbols */
.nozzle-stub-line,
.nozzle-stub-cap {
  pointer-events: none;
  opacity: 0.85;
}

/* Rulers */
.ruler {
  position: absolute;
  z-index: 50;
  overflow: hidden;
}

.ruler-h {
  top: 0;
  left: 24px;
  right: 0;
  height: 24px;
  cursor: row-resize;
}

.ruler-v {
  top: 24px;
  left: 0;
  bottom: 0;
  width: 24px;
  cursor: col-resize;
}

.ruler-corner {
  position: absolute;
  top: 0;
  left: 0;
  width: 24px;
  height: 24px;
  background: #1e293b;
  z-index: 51;
  border-right: 1px solid #334155;
  border-bottom: 1px solid #334155;
}

/* Guide lines */
.guide-line {
  stroke: #06b6d4;
  pointer-events: stroke;
  cursor: move;
  opacity: 0.6;
}

.guide-line:hover {
  opacity: 1;
  stroke: #22d3ee;
}

.guide-line.dragging {
  stroke: #22d3ee;
  opacity: 0.8;
  pointer-events: none;
}

.port-indicator.snap-active {
  fill: #22c55e;
  stroke: #fff;
  stroke-width: 2;
  r: 8;
}

.snap-highlight {
  fill: none;
  stroke: #22c55e;
  stroke-width: 2;
  stroke-dasharray: 4,2;
  pointer-events: none;
  animation: snap-pulse 0.5s ease-in-out infinite alternate;
}

.alignment-guide {
  stroke: #f472b6;
  stroke-dasharray: 4,3;
  pointer-events: none;
}

.pid-minimap {
  position: absolute;
  bottom: 12px;
  right: 12px;
  width: 200px;
  height: 150px;
  background: rgba(15, 15, 26, 0.85);
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  z-index: 60;
  cursor: pointer;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

@keyframes snap-pulse {
  from { opacity: 0.5; r: 10; }
  to { opacity: 1; r: 14; }
}

/* Group bounding boxes */
.group-box {
  fill: none;
  stroke: #8b5cf6;
  stroke-width: 1;
  stroke-dasharray: 6,3;
  opacity: 0.5;
  pointer-events: none;
}

.group-box.group-selected {
  stroke: #a78bfa;
  stroke-width: 2;
  opacity: 0.8;
  animation: group-pulse 1s ease-in-out infinite alternate;
}

@keyframes group-pulse {
  from { opacity: 0.6; }
  to { opacity: 1; }
}

/* Text Annotations */
.pid-text-annotation {
  position: absolute;
  white-space: pre-wrap;
  pointer-events: none;
  cursor: default;
  line-height: 1.3;
  font-family: 'Segoe UI', Arial, sans-serif;
  border-radius: 1px;
}

.edit-mode .pid-text-annotation {
  pointer-events: auto;
  cursor: move;
}

.edit-mode .pid-text-annotation.selected {
  outline: 2px solid #60a5fa;
  outline-offset: 2px;
}

.edit-mode .pid-text-annotation:hover:not(.selected) {
  outline: 1px dashed rgba(96, 165, 250, 0.5);
  outline-offset: 2px;
}

/* Background image */
.background-image {
  position: absolute;
  pointer-events: none;
  object-fit: contain;
  z-index: 0;
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

/* Interactive in edit mode */
.edit-mode .pid-symbol {
  cursor: move;
  pointer-events: auto;
}

/* Clickable in runtime mode when has channel (for faceplate) */
.pid-symbol.has-channel {
  pointer-events: auto;
  cursor: pointer;
}

.pid-symbol.has-channel:hover {
  filter: brightness(1.2);
}

/* Selection indicator - subtle glow instead of boxy outline */
.edit-mode .pid-symbol.selected {
  filter: drop-shadow(0 0 4px rgba(59, 130, 246, 0.6));
}

.edit-mode .pid-symbol:hover:not(.selected) {
  filter: drop-shadow(0 0 2px rgba(59, 130, 246, 0.3));
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

.offpage-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 700;
  color: #333;
  text-transform: uppercase;
  pointer-events: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 20% 0 8%;
  letter-spacing: 0.5px;
}

.offpage-label.not-linked {
  color: #999;
  font-style: italic;
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

/* Resize handles - small circular handles for clean design */
.resize-handle {
  position: absolute;
  width: 8px;
  height: 8px;
  background: rgba(59, 130, 246, 0.9);
  border: 1.5px solid #fff;
  border-radius: 50%;
  z-index: 100;
  opacity: 0.8;
  transition: transform 0.1s, opacity 0.1s, background 0.1s;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

.resize-handle.nw { top: -4px; left: -4px; cursor: nw-resize; }
.resize-handle.ne { top: -4px; right: -4px; cursor: ne-resize; }
.resize-handle.sw { bottom: -4px; left: -4px; cursor: sw-resize; }
.resize-handle.se { bottom: -4px; right: -4px; cursor: se-resize; }

.resize-handle:hover {
  background: #60a5fa;
  transform: scale(1.3);
  opacity: 1;
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
  transition: background 0.15s;
}

.drawing-indicator.ortho-active {
  background: rgba(139, 92, 246, 0.95);
  box-shadow: 0 0 10px rgba(139, 92, 246, 0.5);
}

/* Orthogonal mode cursor */
.pid-canvas.ortho-mode {
  cursor: crosshair;
}

.pid-canvas.ortho-mode .drawing-preview {
  stroke: #8b5cf6 !important;
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

.form-divider {
  height: 1px;
  background: #2a2a4a;
  margin: 12px 0;
}

.form-section-title {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #60a5fa;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.form-range {
  width: 100%;
  accent-color: #3b82f6;
}

.range-value {
  font-size: 0.8rem;
  color: #888;
  margin-left: 8px;
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

/* Connection ports management */
.ports-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.ports-subsection {
  font-size: 0.65rem;
  text-transform: uppercase;
  color: #666;
  letter-spacing: 0.5px;
  margin-top: 4px;
}

.port-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: #0f0f1a;
  border: 1px solid #1a1a2e;
  border-radius: 3px;
  font-size: 0.75rem;
}

.port-item.builtin {
  border-left: 2px solid #3b82f6;
}

.port-item.custom {
  border-left: 2px solid #22c55e;
}

.port-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  flex: 1;
}

.port-toggle input[type="checkbox"] {
  width: 14px;
  height: 14px;
  accent-color: #3b82f6;
}

.port-name {
  color: #ccc;
  font-weight: 500;
}

.port-dir {
  color: #666;
  font-size: 0.7rem;
}

.port-info {
  font-size: 0.8rem;
  color: #ccc;
  text-transform: capitalize;
}

.btn-remove-port {
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 1.2rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
  opacity: 0.7;
  transition: opacity 0.15s;
}

.btn-remove-port:hover {
  opacity: 1;
}

.no-ports-hint {
  font-size: 0.75rem;
  color: #666;
  font-style: italic;
  margin-bottom: 12px;
}

.add-port-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  background: rgba(59, 130, 246, 0.05);
  border: 1px dashed #2a2a4a;
  border-radius: 4px;
}

.add-port-controls .form-group {
  gap: 2px;
}

.btn-add-port {
  padding: 6px 12px;
  background: #22c55e;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  margin-top: 4px;
}

.btn-add-port:hover {
  background: #16a34a;
}

/* Hover port indicator (subtle blue, shown on symbol hover in edit mode) */
.port-indicator.hover-port {
  fill: rgba(59, 130, 246, 0.4);
  stroke: rgba(59, 130, 246, 0.8);
}

/* Custom port indicator styling in pipe drawing mode */
.port-indicator.custom-port {
  fill: rgba(34, 197, 94, 0.3);
  stroke: #22c55e;
}
</style>

<style>
/* Teleported inline edit input — must be unscoped */
.pid-inline-edit-input {
  position: fixed;
  z-index: 100000;
  background: #1e293b;
  color: #e2e8f0;
  border: 2px solid #60a5fa;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  font-family: system-ui, -apple-system, sans-serif;
  min-width: 80px;
  outline: none;
  transform: translate(-50%, -50%);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}
</style>
