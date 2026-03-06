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

import { ref, computed, onMounted, onUnmounted, nextTick, watchEffect, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SYMBOL_PORTS, SYMBOL_INFO, NOZZLE_STUB_CATEGORIES, OFF_PAGE_CONNECTOR_TYPES, getPortPosition, rotateCW, rotateDirection, flipPoint, flipDirection, type ScadaSymbolType } from '../assets/symbols'
import { autoRoute, bundleParallelPipes } from '../utils/autoRoute'
import type { PidSymbol, PidPipe, PidPoint, PidLayerData, PidPipeConnection, PidTextAnnotation, PidIndicator, PidArrowType } from '../types'
import PidFaceplate from './PidFaceplate.vue'
import PidBlockEditor from './PidBlockEditor.vue'
import PidContextMenu from './PidContextMenu.vue'
import type { MenuTarget } from './PidContextMenu.vue'
import { isHmiControl, getHmiDefaultSize } from '../constants/hmiControls'
import { getHmiComponent } from './hmi/index'
import { useSafety } from '../composables/useSafety'
import {
  isTankSymbol, isValveSymbol, isInstrumentSymbol, getIsaFunctionLetters, parseIsaTagNumber,
  getSymbolSvg, resolveArrowType, getFlowAnimationDuration,
  segmentIntersection, generateRoundedPolylinePath, generatePipePath,
  getPipeDashArray, getMarkerUrl, getPipeLabelPoint, distanceToSegment,
  getPipeMediumColor, getPipeDisplayLabel, generateHeatTracePath, getHeatTraceColor,
  getSignalLineDashArray, usePidRendering,
} from '../composables/usePidRendering'
import { usePidViewport, RULER_SIZE } from '../composables/usePidViewport'
import { useScripts } from '../composables/useScripts'

const store = useDashboardStore()

// Snap threshold in pixels (base value, adjusted by zoom)
const SNAP_THRESHOLD_BASE = 25
const SNAP_THRESHOLD = computed(() => SNAP_THRESHOLD_BASE / zoom.value)

// Grid snap settings (from store)
const gridSnapEnabled = computed(() => store.pidGridSnapEnabled)
const gridSize = computed(() => store.pidGridSize)
const showGrid = computed(() => store.pidShowGrid)
const orthogonalPipes = computed(() => store.pidOrthogonalPipes)
const safety = useSafety()
const scriptsComposable = useScripts()
const rendering = usePidRendering(store, safety, () => props.pidLayer)
const {
  colorScheme,
  getTankFillLevel, getTankSvgWithFill, getValveSvgWithPosition,
  getConveyorSvgWithAnimation, isSymbolInAlarm, getSymbolColor,
  getSymbolStyle, getSymbolValue, getInterlockBadge,
  getSymbolAnimationClass, isSymbolDisconnected,
  getPipeFlowState, isHeatTraceActive, generatePipePathWithJumps, pipeMarkerDefs,
  getIndicatorRuntimeColor, getIndicatorValue, isIndicatorInAlarm,
} = rendering

const canvasRef = ref<HTMLElement | null>(null)
const editModeComputed = computed(() => props.editMode)
const viewport = usePidViewport(store, editModeComputed, () => props.pidLayer, canvasRef)
const {
  zoom, panX, panY, isPanning, panStart, spaceHeld,
  getCanvasCoords, onCanvasWheel, onPanStart, onPanMove, onPanEnd,
  showMinimap, minimapBounds, minimapViewBox, minimapViewport, onMinimapMouseDown,
  showRulers, rulerHCanvas, rulerVCanvas, draggingGuide, draggingGuidePos,
  drawRuler, onRulerMouseDown, onGuideMouseDown,
} = viewport

// Alignment guides
interface AlignmentGuide {
  axis: 'h' | 'v'        // horizontal or vertical line
  pos: number             // y for horizontal, x for vertical
  from: number            // start extent
  to: number              // end extent
}
const activeGuides = ref<AlignmentGuide[]>([])

// Layer visibility filtering
const hiddenLayerIds = computed(() => {
  const infos = props.pidLayer.layerInfos
  if (!infos || infos.length === 0) return new Set<string>()
  return new Set(infos.filter(l => !l.visible).map(l => l.id))
})

// Viewport culling (#7.1) — compute world-coordinate bounds of visible area
const CULL_MARGIN = 100 // extra px in world coords outside viewport
const viewportWorldBounds = computed(() => {
  const el = canvasRef.value
  if (!el) return null
  const w = el.clientWidth
  const h = el.clientHeight
  const z = zoom.value
  return {
    left: -panX.value / z - CULL_MARGIN,
    top: -panY.value / z - CULL_MARGIN,
    right: (w - panX.value) / z + CULL_MARGIN,
    bottom: (h - panY.value) / z + CULL_MARGIN,
  }
})

function isRectInViewport(x: number, y: number, w: number, h: number): boolean {
  const vp = viewportWorldBounds.value
  if (!vp) return true // no viewport info → show everything
  return x + w >= vp.left && x <= vp.right && y + h >= vp.top && y <= vp.bottom
}

function isPipeInViewport(pipe: PidPipe): boolean {
  const vp = viewportWorldBounds.value
  if (!vp) return true
  // Check if any pipe point or segment bbox intersects viewport
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const pt of pipe.points) {
    if (pt.x < minX) minX = pt.x
    if (pt.y < minY) minY = pt.y
    if (pt.x > maxX) maxX = pt.x
    if (pt.y > maxY) maxY = pt.y
  }
  return maxX >= vp.left && minX <= vp.right && maxY >= vp.top && minY <= vp.bottom
}

const layerFilteredSymbols = computed(() => {
  if (hiddenLayerIds.value.size === 0) return props.pidLayer.symbols
  return props.pidLayer.symbols.filter(s => !hiddenLayerIds.value.has(s.layerId || 'main'))
})

const layerFilteredPipes = computed(() => {
  if (hiddenLayerIds.value.size === 0) return props.pidLayer.pipes
  return props.pidLayer.pipes.filter(p => !hiddenLayerIds.value.has(p.layerId || 'main'))
})

const layerFilteredTextAnnotations = computed(() => {
  const all = props.pidLayer.textAnnotations || []
  if (hiddenLayerIds.value.size === 0) return all
  return all.filter(t => !hiddenLayerIds.value.has(t.layerId || 'main'))
})

const visibleSymbols = computed(() => {
  return layerFilteredSymbols.value.filter(s =>
    isRectInViewport(s.x, s.y, s.width || 60, s.height || 60)
  )
})

const visiblePipes = computed(() => {
  return layerFilteredPipes.value.filter(p => isPipeInViewport(p))
})

// Bundle overlapping orthogonal pipes for visual offset (rendering only, doesn't modify stored data)
const bundledPipePoints = computed(() => {
  const orthoPipes = props.pidLayer.pipes.filter(p => p.pathType === 'orthogonal')
  if (orthoPipes.length < 2) return new Map<string, { x: number; y: number }[]>()
  return bundleParallelPipes(
    orthoPipes.map(p => ({ id: p.id, points: p.points, strokeWidth: p.strokeWidth ?? 2 }))
  )
})

/** Get pipe points with bundle offset applied (if any) */
function getPipePointsWithBundling(pipe: PidPipe): { x: number; y: number }[] {
  return bundledPipePoints.value.get(pipe.id) ?? pipe.points
}

/** Return a shallow copy of the pipe with bundled points for visual rendering.
 *  Use this for generatePipePath/generatePipePathWithJumps/generateHeatTracePath calls.
 *  Editing/interaction code should use pipe.points directly (original coordinates). */
function pipeView(pipe: PidPipe): PidPipe {
  const bundled = bundledPipePoints.value.get(pipe.id)
  if (!bundled) return pipe
  return { ...pipe, points: bundled as PidPoint[] }
}

const visibleTextAnnotations = computed(() => {
  return layerFilteredTextAnnotations.value.filter(t =>
    isRectInViewport(t.x, t.y, t.text.length * t.fontSize * 0.6, t.fontSize * 1.5)
  )
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

// Focus mode badge
const showFocusBadge = ref(false)
let focusBadgeTimer: ReturnType<typeof setTimeout> | null = null
watch(() => store.pidFocusMode, (v) => {
  if (v) {
    showFocusBadge.value = true
    if (focusBadgeTimer) clearTimeout(focusBadgeTimer)
    focusBadgeTimer = setTimeout(() => { showFocusBadge.value = false }, 3000)
  } else {
    showFocusBadge.value = false
  }
})

// Selection state
const selectedSymbolId = ref<string | null>(null)
const selectedPipeId = ref<string | null>(null)
const selectedPipeSegmentIdx = ref<number | null>(null) // which segment of the selected pipe is active
const hoveredSymbolId = ref<string | null>(null)

// Runtime tooltip (#6.1) — delayed popup on symbol hover in runtime mode
const tooltipSymbol = ref<PidSymbol | null>(null)
const tooltipPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
let tooltipTimer: ReturnType<typeof setTimeout> | null = null

function showRuntimeTooltip(symbol: PidSymbol) {
  if (props.editMode || !symbol.channel) return
  tooltipTimer = setTimeout(() => {
    tooltipSymbol.value = symbol
    tooltipPos.value = {
      x: symbol.x + symbol.width / 2,
      y: symbol.y - 10
    }
  }, 300)
}

function hideRuntimeTooltip() {
  if (tooltipTimer) { clearTimeout(tooltipTimer); tooltipTimer = null }
  tooltipSymbol.value = null
}

// Alarm propagation: highlight pipes connected to alarmed symbols (#6.4)
const alarmedPipeIds = computed<Set<string>>(() => {
  if (props.editMode) return new Set()
  const alarmed = new Set<string>()
  for (const symbol of props.pidLayer.symbols) {
    if (!isSymbolInAlarm(symbol)) continue
    for (const pipe of props.pidLayer.pipes) {
      if (pipe.startSymbolId === symbol.id || pipe.endSymbolId === symbol.id) {
        alarmed.add(pipe.id)
      }
    }
  }
  return alarmed
})

// Procedure overlay: map symbolId → step badge info (#6.5)
const procedureStepBadges = computed<Map<string, { stepNum: number; status: 'current' | 'done' | 'pending' }>>(() => {
  const map = new Map<string, { stepNum: number; status: 'current' | 'done' | 'pending' }>()
  if (props.editMode) return map
  const seq = scriptsComposable.runningSequence.value
  if (!seq || seq.state !== 'running') return map
  for (let i = 0; i < seq.steps.length; i++) {
    const step = seq.steps[i]
    if (!step?.symbolRef) continue
    const status = i < seq.currentStepIndex ? 'done' : i === seq.currentStepIndex ? 'current' : 'pending'
    map.set(step.symbolRef, { stepNum: i + 1, status })
  }
  return map
})

// Operator notes (#6.6) — runtime-mode sticky notes
const editingNoteId = ref<string | null>(null)
const editingNoteText = ref('')
const draggingNoteId = ref<string | null>(null)
const noteDragStart = ref<{ x: number; y: number; noteX: number; noteY: number } | null>(null)

const NOTE_COLORS = ['#fbbf24', '#34d399', '#60a5fa', '#f87171', '#c084fc', '#fb923c']

function addOperatorNote(event: MouseEvent) {
  if (props.editMode) return
  const pt = getCanvasCoords(event)
  const id = store.pidAddOperatorNote(pt.x, pt.y, 'New note')
  editingNoteId.value = id
  editingNoteText.value = 'New note'
}

function startNoteEdit(note: { id: string; text: string }) {
  editingNoteId.value = note.id
  editingNoteText.value = note.text
}

function commitNoteEdit() {
  if (editingNoteId.value && editingNoteText.value.trim()) {
    store.pidUpdateOperatorNote(editingNoteId.value, { text: editingNoteText.value.trim() })
  } else if (editingNoteId.value && !editingNoteText.value.trim()) {
    store.pidRemoveOperatorNote(editingNoteId.value)
  }
  editingNoteId.value = null
  editingNoteText.value = ''
}

function cycleNoteColor(noteId: string) {
  const note = store.pidOperatorNotes.find(n => n.id === noteId)
  if (!note) return
  const idx = NOTE_COLORS.indexOf(note.color)
  const nextColor = NOTE_COLORS[(idx + 1) % NOTE_COLORS.length]
  store.pidUpdateOperatorNote(noteId, { color: nextColor })
}

function onNoteMouseDown(event: MouseEvent, note: { id: string; x: number; y: number }) {
  if (event.button !== 0) return
  draggingNoteId.value = note.id
  noteDragStart.value = { x: event.clientX, y: event.clientY, noteX: note.x, noteY: note.y }
  const onMove = (e: MouseEvent) => {
    if (!noteDragStart.value) return
    const dx = (e.clientX - noteDragStart.value.x) / zoom.value
    const dy = (e.clientY - noteDragStart.value.y) / zoom.value
    store.pidUpdateOperatorNote(note.id, {
      x: noteDragStart.value.noteX + dx,
      y: noteDragStart.value.noteY + dy,
    })
  }
  const onUp = () => {
    draggingNoteId.value = null
    noteDragStart.value = null
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// Context menu state
const contextMenu = ref<{ x: number; y: number; target: MenuTarget } | null>(null)

// Template save dialog state
const showTemplateSaveDialog = ref(false)
const templateName = ref('')
const templateCategory = ref('General')

function saveTemplate() {
  if (!templateName.value.trim()) return
  store.createPidTemplate(templateName.value.trim(), undefined, templateCategory.value)
  showTemplateSaveDialog.value = false
  templateName.value = ''
  templateCategory.value = 'General'
}

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

// Find nearest port within snap threshold (includes symbol ports AND pipe endpoints)
function findNearestPort(mousePos: PidPoint): typeof snapTarget.value {
  const allPorts = getAllPortPositions()
  let nearest: typeof snapTarget.value = null
  let minDist = SNAP_THRESHOLD.value

  // Check symbol ports
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

  // Also check existing pipe endpoints for pipe-to-pipe connections
  for (const pipe of props.pidLayer.pipes) {
    // Skip the pipe currently being drawn (if extending an existing one)
    if (pipe.points.length < 2) continue
    const endpoints = [
      { pt: pipe.points[0]!, id: 'start' },
      { pt: pipe.points[pipe.points.length - 1]!, id: 'end' },
    ]
    for (const ep of endpoints) {
      const dist = Math.sqrt((mousePos.x - ep.pt.x) ** 2 + (mousePos.y - ep.pt.y) ** 2)
      if (dist < minDist) {
        minDist = dist
        nearest = {
          symbolId: `pipe:${pipe.id}`,
          portId: ep.id,
          x: ep.pt.x,
          y: ep.pt.y
        }
      }
    }
  }

  return nearest
}

// Check if a snap target is a pipe endpoint (not a symbol port)
function isPipeEndpointSnap(port: NonNullable<typeof snapTarget.value>): boolean {
  return port.symbolId.startsWith('pipe:')
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

// Generate L-bend corner point for orthogonal routing between two points.
// Returns the intermediate corner so the path goes: lastPoint → corner → target
// Uses "horizontal-first" routing (go H then V) by default, choosing the
// variant closest to the raw mouse position for a natural feel.
function getOrthogonalCorner(lastPoint: PidPoint, target: PidPoint): PidPoint | null {
  const dx = Math.abs(target.x - lastPoint.x)
  const dy = Math.abs(target.y - lastPoint.y)

  // If already on same axis, no corner needed
  if (dx < 1 || dy < 1) return null

  // H-first corner: go horizontal to target.x, then vertical
  return { x: target.x, y: lastPoint.y }
}

// ─── Indicator rendering helpers (block editor stubs on symbol edge) ─────

function getIndicatorEdgeStyle(symbol: PidSymbol, ind: PidIndicator): Record<string, string> {
  let left: number, top: number
  switch (ind.edge) {
    case 'top':
      left = ind.edgeOffset * symbol.width - 7
      top = -7
      break
    case 'bottom':
      left = ind.edgeOffset * symbol.width - 7
      top = symbol.height - 7
      break
    case 'left':
      left = -7
      top = ind.edgeOffset * symbol.height - 7
      break
    case 'right':
      left = symbol.width - 7
      top = ind.edgeOffset * symbol.height - 7
      break
    default:
      left = 0; top = 0
  }
  return {
    position: 'absolute',
    left: `${left}px`,
    top: `${top}px`,
    zIndex: '10',
    display: 'flex',
    alignItems: 'center',
    gap: '2px',
    pointerEvents: 'none',
  }
}

function getIndicatorSignalEnd(ind: PidIndicator): { dx: number; dy: number } {
  const len = ind.signalLineLength ?? 30
  switch (ind.edge) {
    case 'top':    return { dx: 0, dy: -len }
    case 'bottom': return { dx: 0, dy: len }
    case 'left':   return { dx: -len, dy: 0 }
    case 'right':  return { dx: len, dy: 0 }
    default:       return { dx: 0, dy: -len }
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
        (symbol.rotation || 0) as 0 | 90 | 180 | 270,
        !!symbol.flipX,
        !!symbol.flipY
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
  // Custom ports are defined relative to the bounding box (0-1 normalized to div, not viewBox).
  // Flip+rotation is applied as pixel-level transforms around div center, matching CSS transform order.
  if (symbol.customPorts && symbol.customPorts.length > 0) {
    const width = symbol.width || 60
    const height = symbol.height || 60
    const rotation = (symbol.rotation || 0) as 0 | 90 | 180 | 270
    const doFlipX = !!symbol.flipX
    const doFlipY = !!symbol.flipY
    const cx = width / 2, cy = height / 2

    for (const customPort of symbol.customPorts) {
      // Convert normalized coords to local-div pixel position
      const localX = customPort.x * width
      const localY = customPort.y * height

      // Flip then rotate around div center (matching CSS transform order: scaleX scaleY rotate)
      const flipped = flipPoint(localX, localY, cx, cy, doFlipX, doFlipY)
      const rotated = rotateCW(flipped.x, flipped.y, cx, cy, rotation)

      let direction = customPort.direction
      if (doFlipX || doFlipY) direction = flipDirection(direction, doFlipX, doFlipY)
      if (rotation !== 0) direction = rotateDirection(direction, rotation)

      result.push({
        id: customPort.id,
        x: symbol.x + rotated.x,
        y: symbol.y + rotated.y,
        direction,
        isCustom: true
      })
    }
  }

  return result
}

// --- Port dot rendering for equipment symbols ---
function symbolHasNozzleStubs(symbolType: string): boolean {
  const info = SYMBOL_INFO[symbolType as ScadaSymbolType]
  return !!info && NOZZLE_STUB_CATEGORIES.has(info.category)
}

const nozzlePorts = computed(() => {
  if (!props.editMode || !store.pidShowNozzleStubs) return []
  const ports: Array<{ symbolId: string; portId: string; color: string; x: number; y: number }> = []
  for (const symbol of props.pidLayer.symbols) {
    if (!symbolHasNozzleStubs(symbol.type)) continue
    const color = symbol.color || '#60a5fa'
    for (const port of getSymbolPorts(symbol)) {
      ports.push({ symbolId: symbol.id, portId: port.id, color, x: port.x, y: port.y })
    }
  }
  return ports
})

// Stub lines for custom ports (dynamic — not baked into static SVG like built-in ports)
// Visible in both edit and runtime mode so pipes visually connect to the symbol body.
const customPortStubs = computed(() => {
  const STUB_LEN = 10 // px in world coordinates
  const stubs: Array<{ key: string; x1: number; y1: number; x2: number; y2: number; color: string }> = []
  for (const symbol of props.pidLayer.symbols) {
    if (!symbol.customPorts || symbol.customPorts.length === 0) continue
    const color = symbol.color || '#94a3b8'
    const ports = getSymbolPorts(symbol).filter(p => p.isCustom)
    for (const port of ports) {
      // Stub goes from edge inward (opposite of port direction)
      let dx = 0, dy = 0
      switch (port.direction) {
        case 'left':   dx = 1; break
        case 'right':  dx = -1; break
        case 'top':    dy = 1; break
        case 'bottom': dy = -1; break
      }
      stubs.push({
        key: `stub-${symbol.id}-${port.id}`,
        x1: port.x,
        y1: port.y,
        x2: port.x + dx * STUB_LEN,
        y2: port.y + dy * STUB_LEN,
        color,
      })
    }
  }
  return stubs
})

const viewportRef = ref<HTMLElement | null>(null)

// Block editor state (edit mode — double-click to open)
const showBlockEditor = ref(false)
const blockEditorSymbol = ref<PidSymbol | null>(null)

function openBlockEditor(symbol: PidSymbol) {
  blockEditorSymbol.value = symbol
  showBlockEditor.value = true
}

function onBlockEditorSave(data: {
  indicators: PidIndicator[]
  customPorts?: PidSymbol['customPorts']
  hiddenPorts?: PidSymbol['hiddenPorts']
}) {
  if (blockEditorSymbol.value) {
    store.updatePidSymbolWithUndo(blockEditorSymbol.value.id, {
      indicators: data.indicators,
      customPorts: data.customPorts,
      hiddenPorts: data.hiddenPorts,
    })
  }
  showBlockEditor.value = false
  blockEditorSymbol.value = null
}

function onBlockEditorCancel() {
  showBlockEditor.value = false
  blockEditorSymbol.value = null
}

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

// Find pipe connected to a specific port
function findPipeAtPort(symbolId: string, portId: string): { pipe: PidPipe; end: 'start' | 'end' } | null {
  for (const pipe of props.pidLayer.pipes) {
    if (pipe.startConnection?.symbolId === symbolId && pipe.startConnection?.portId === portId) {
      return { pipe, end: 'start' }
    }
    if (pipe.endConnection?.symbolId === symbolId && pipe.endConnection?.portId === portId) {
      return { pipe, end: 'end' }
    }
    // Legacy fields
    if (pipe.startSymbolId === symbolId && pipe.startPortId === portId) {
      return { pipe, end: 'start' }
    }
    if (pipe.endSymbolId === symbolId && pipe.endPortId === portId) {
      return { pipe, end: 'end' }
    }
  }
  return null
}

// Right-click on a port nozzle dot
function onPortRightClick(event: MouseEvent, symbolId: string, portId: string) {
  if (!props.editMode || props.pipeDrawingMode) return
  event.preventDefault()
  event.stopPropagation()

  const conn = findPipeAtPort(symbolId, portId)
  if (!conn) return  // No pipe connected — nothing to do

  const currentArrow = conn.end === 'start'
    ? (typeof conn.pipe.startArrow === 'string' ? conn.pipe.startArrow : (conn.pipe.startArrow ? 'arrow' : 'none'))
    : (typeof conn.pipe.endArrow === 'string' ? conn.pipe.endArrow : (conn.pipe.endArrow ? 'arrow' : 'none'))

  contextMenu.value = {
    x: event.clientX,
    y: event.clientY,
    target: {
      type: 'port',
      symbolId,
      portId,
      pipeId: conn.pipe.id,
      pipeEnd: conn.end,
      currentArrow: currentArrow === 'none' ? undefined : currentArrow,
    }
  }
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

  // Find which segment was right-clicked
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

  selectedPipeId.value = pipe.id
  selectedPipeSegmentIdx.value = closestSegment
  selectedSymbolId.value = null
  emit('select:pipe', pipe.id)
  emit('select:symbol', null)
  canvasRef.value?.focus()
  contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'pipe', id: pipe.id } }
}

function handleContextMenuAction(action: string) {
  const target = contextMenu.value?.target
  if (!target) return

  // Ensure right-clicked element is in store selection (for cut/copy/duplicate/bringToFront/sendToBack)
  if (target.type === 'symbol') {
    store.pidSelectItems([target.id], [], [])
  } else if (target.type === 'pipe') {
    store.pidSelectItems([], [target.id], [])
  }

  // Shared actions (work for any target type)
  if (action === 'saveAsTemplate') {
    showTemplateSaveDialog.value = true
    contextMenu.value = null
    return
  }

  if (target.type === 'symbol') {
    switch (action) {
      case 'configure':
        const sym = props.pidLayer.symbols.find(s => s.id === target.id)
        if (sym) openBlockEditor(sym)
        break
      case 'cut': store.pidCut(); break
      case 'copy': store.pidCopy(); break
      case 'duplicate': store.pidDuplicate(); break
      case 'delete': store.removePidSymbolWithUndo(target.id); selectedSymbolId.value = null; emit('select:symbol', null); break
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
      case 'flipH': {
        const s = props.pidLayer.symbols.find(s => s.id === target.id)
        if (s) store.updatePidSymbolWithUndo(target.id, { flipX: !s.flipX })
        break
      }
      case 'flipV': {
        const s = props.pidLayer.symbols.find(s => s.id === target.id)
        if (s) store.updatePidSymbolWithUndo(target.id, { flipY: !s.flipY })
        break
      }
    }
  } else if (target.type === 'pipe') {
    switch (action) {
      case 'delete': store.removePidPipeWithUndo(target.id); selectedPipeId.value = null; selectedPipeSegmentIdx.value = null; break
      case 'deleteSegment': {
        store.pidDeletePipeSegment(target.id, selectedPipeSegmentIdx.value)
        selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
        emit('select:pipe', null)
        break
      }
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
  } else if (target.type === 'port') {
    if (action.startsWith('portArrow:')) {
      const arrowType = action.split(':')[1] as PidArrowType | 'none'
      const value = arrowType === 'none' ? undefined : arrowType
      if (target.pipeEnd === 'start') {
        store.updatePidPipeWithUndo(target.pipeId, { startArrow: value })
      } else {
        store.updatePidPipeWithUndo(target.pipeId, { endArrow: value })
      }
    } else if (action === 'portSelectPipe') {
      selectedPipeId.value = target.pipeId
      selectedSymbolId.value = null
      emit('select:pipe', target.pipeId)
      emit('select:symbol', null)
      canvasRef.value?.focus()
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

// Handle symbol double-click for config
function onSymbolDoubleClick(event: MouseEvent, symbol: PidSymbol) {
  event.preventDefault()
  event.stopPropagation()
  if (props.editMode) {
    openBlockEditor(symbol)
  } else if (OFF_PAGE_CONNECTOR_TYPES.has(symbol.type) && symbol.linkedPageId) {
    store.switchPage(symbol.linkedPageId)
  }
}

// Symbol selection
function onSymbolMouseDown(event: MouseEvent, symbol: PidSymbol) {
  // In runtime mode, open faceplate on click (skip for HMI controls — they handle their own interaction)
  if (!props.editMode) {
    // Off-page connectors: navigate to linked page on click
    if (OFF_PAGE_CONNECTOR_TYPES.has(symbol.type) && symbol.linkedPageId) {
      event.preventDefault()
      event.stopPropagation()
      store.switchPage(symbol.linkedPageId)
      return
    }
    if (!isHmiControl(symbol.type)) {
      openFaceplate(event, symbol)
    }
    return
  }

  event.preventDefault()
  event.stopPropagation()

  // Check if element is locked (symbol-level or layer-level)
  const isLocked = symbol.locked || store.isLayerLocked(symbol.layerId)

  // Check if clicking a resize handle
  const target = event.target as HTMLElement
  if (target.classList.contains('resize-handle')) {
    if (isLocked) return  // Locked symbols can't be resized
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
  if (isLocked) {
    selectedSymbolId.value = symbol.id
    selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
    emit('select:symbol', symbol.id)
    emit('select:pipe', null)
    return
  }

  // Start drag
  selectedSymbolId.value = symbol.id
  selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
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
  selectedPipeId.value = null; selectedPipeSegmentIdx.value = null

  // Layer-locked text annotations can be selected but not dragged
  if (store.isLayerLocked(text.layerId)) return

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
/** Fast endpoint-only update — moves first/last pipe points to match port positions (no A*) */
function rerouteEndpointsOnly(pipes: PidPipe[], symbols: PidSymbol[]): PidPipe[] {
  const symbolMap = new Map(symbols.map(s => [s.id, s]))
  const isOrtho = orthogonalPipes.value
  return pipes.map(pipe => {
    let updated = false
    let newPoints = pipe.points

    if (pipe.startConnection) {
      const sym = symbolMap.get(pipe.startConnection.symbolId)
      if (sym) {
        const pos = getPortPosition(
          sym.type as ScadaSymbolType, pipe.startConnection.portId,
          sym.x, sym.y, sym.width, sym.height, (sym.rotation || 0) as 0 | 90 | 180 | 270
        )
        if (pos && newPoints.length > 0) {
          const first = newPoints[0]!
          if (first.x !== pos.x || first.y !== pos.y) {
            newPoints = [...newPoints]
            newPoints[0] = { x: pos.x, y: pos.y }
            updated = true
            // Maintain orthogonality: adjust adjacent point so the first segment stays H or V
            if (isOrtho && newPoints.length >= 3) {
              const second = newPoints[1]!
              const dx = Math.abs(pos.x - second.x)
              const dy = Math.abs(pos.y - second.y)
              if (dx > 1 && dy > 1) {
                // Segment became diagonal — pick the axis that moved less and snap
                const oldFirst = first
                const wasMostlyH = Math.abs(oldFirst.x - second.x) > Math.abs(oldFirst.y - second.y)
                if (wasMostlyH) {
                  // Was horizontal: keep X, adjust Y to match new start
                  newPoints[1] = { x: second.x, y: pos.y }
                } else {
                  // Was vertical: keep Y, adjust X to match new start
                  newPoints[1] = { x: pos.x, y: second.y }
                }
              }
            }
          }
        }
      }
    }

    if (pipe.endConnection) {
      const sym = symbolMap.get(pipe.endConnection.symbolId)
      if (sym) {
        const pos = getPortPosition(
          sym.type as ScadaSymbolType, pipe.endConnection.portId,
          sym.x, sym.y, sym.width, sym.height, (sym.rotation || 0) as 0 | 90 | 180 | 270
        )
        if (pos && newPoints.length > 0) {
          const last = newPoints[newPoints.length - 1]!
          if (last.x !== pos.x || last.y !== pos.y) {
            if (!updated) newPoints = [...newPoints]
            newPoints[newPoints.length - 1] = { x: pos.x, y: pos.y }
            updated = true
            // Maintain orthogonality: adjust adjacent point so the last segment stays H or V
            if (isOrtho && newPoints.length >= 3) {
              const penult = newPoints[newPoints.length - 2]!
              const dx = Math.abs(pos.x - penult.x)
              const dy = Math.abs(pos.y - penult.y)
              if (dx > 1 && dy > 1) {
                const oldLast = last
                const wasMostlyH = Math.abs(oldLast.x - penult.x) > Math.abs(oldLast.y - penult.y)
                if (wasMostlyH) {
                  newPoints[newPoints.length - 2] = { x: penult.x, y: pos.y }
                } else {
                  newPoints[newPoints.length - 2] = { x: pos.x, y: penult.y }
                }
              }
            }
          }
        }
      }
    }

    return updated ? { ...pipe, points: newPoints } : pipe
  })
}

/** Full reroute including A* pathfinding — expensive, use sparingly during drag */
function rerouteConnectedPipes(pipes: PidPipe[], symbols: PidSymbol[]): PidPipe[] {
  if (!store.pidAutoRoute) return rerouteEndpointsOnly(pipes, symbols)
  const symbolMap = new Map(symbols.map(s => [s.id, s]))
  const endpointUpdated = rerouteEndpointsOnly(pipes, symbols)
  return endpointUpdated.map((pipe, i) => {
    if (pipe === pipes[i] || !pipe.startConnection || !pipe.endConnection) return pipe
    const startSym = symbolMap.get(pipe.startConnection.symbolId)
    const endSym = symbolMap.get(pipe.endConnection.symbolId)
    if (!startSym || !endSym) return pipe
    const sp = getSymbolPorts(startSym).find(p => p.id === pipe.startConnection!.portId)
    const ep = getSymbolPorts(endSym).find(p => p.id === pipe.endConnection!.portId)
    if (!sp || !ep) return pipe
    const obstacles = symbols
      .filter(s => s.id !== startSym.id && s.id !== endSym.id)
      .map(s => ({ x: s.x, y: s.y, width: s.width, height: s.height }))
    const newPoints = autoRoute(
      { x: sp.x, y: sp.y, direction: sp.direction },
      { x: ep.x, y: ep.y, direction: ep.direction },
      obstacles
    )
    return { ...pipe, points: newPoints }
  })
}

// Debounced A* reroute during drag (#7.3)
let debouncedRerouteTimer: ReturnType<typeof setTimeout> | null = null

function debouncedRerouteConnectedPipes(symbols: PidSymbol[]) {
  if (debouncedRerouteTimer) clearTimeout(debouncedRerouteTimer)
  debouncedRerouteTimer = setTimeout(() => {
    if (!store.pidAutoRoute || !isDragging.value) return
    const newPipes = rerouteConnectedPipes(props.pidLayer.pipes, symbols)
    emit('update:pidLayer', { ...props.pidLayer, symbols, pipes: newPipes })
    debouncedRerouteTimer = null
  }, 100)
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

    // Fast endpoint-only reroute during drag; debounce full A* (#7.3)
    newPipes = rerouteEndpointsOnly(newPipes, newSymbols)
    debouncedRerouteConnectedPipes(newSymbols)

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

    // Fast endpoint-only reroute during drag; debounce full A* (#7.3)
    const newPipes = rerouteEndpointsOnly(props.pidLayer.pipes, newSymbols)
    debouncedRerouteConnectedPipes(newSymbols)

    emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols, pipes: newPipes })
  }
}

function onDragEnd() {
  isDragging.value = false
  dragStart.value = null
  activeGuides.value = []
  // Cancel pending debounce and run final full A* reroute synchronously
  if (debouncedRerouteTimer) { clearTimeout(debouncedRerouteTimer); debouncedRerouteTimer = null }
  if (store.pidAutoRoute) {
    const newPipes = rerouteConnectedPipes(props.pidLayer.pipes, props.pidLayer.symbols)
    emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
  }
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
    selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
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
      selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
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

    // Determine final coords: snap-to-port > raw
    let coords: PidPoint
    if (nearestPort) {
      coords = { x: nearestPort.x, y: nearestPort.y }
    } else {
      coords = rawCoords
    }

    if (!isDrawingPipe.value) {
      // Start new pipe
      isDrawingPipe.value = true
      currentPipePoints.value = [coords]

      // Store start connection if snapped to a symbol port (not a pipe endpoint)
      if (nearestPort && !isPipeEndpointSnap(nearestPort)) {
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
      // Add point to current pipe — in orthogonal mode, auto-insert L-bend corner
      // Skip duplicate consecutive points (double-click on same spot)
      const lastPt = currentPipePoints.value[currentPipePoints.value.length - 1]
      if (lastPt && Math.abs(lastPt.x - coords.x) < 1 && Math.abs(lastPt.y - coords.y) < 1) {
        return
      }
      const shouldOrtho = orthogonalPipes.value && !shiftHeld.value
      if (shouldOrtho && currentPipePoints.value.length > 0) {
        const prevPt = currentPipePoints.value[currentPipePoints.value.length - 1]!
        const corner = getOrthogonalCorner(prevPt, coords)
        if (corner) currentPipePoints.value.push(corner)
      }
      currentPipePoints.value.push(coords)

      // AUTO-TERMINATE: If clicked on any port (symbol or pipe endpoint), finish the pipe
      const isEndpointSnap = nearestPort != null
      const isSymbolPort = nearestPort && !isPipeEndpointSnap(nearestPort)
      if (isEndpointSnap && currentPipePoints.value.length >= 2) {
        // Check it's not the same port we started from
        const isSamePort = startConnection.value &&
                           startConnection.value.symbolId === nearestPort!.symbolId &&
                           startConnection.value.portId === nearestPort!.portId
        if (!isSamePort) {
          // Auto-route: if enabled, replace user waypoints with computed path
          let pipePoints = [...currentPipePoints.value]
          let pipePathType: 'polyline' | 'orthogonal' = 'polyline'
          // Only store end connection for symbol ports (not pipe endpoints)
          const endConn = isSymbolPort ? {
            symbolId: nearestPort!.symbolId,
            portId: nearestPort!.portId,
            x: nearestPort!.x,
            y: nearestPort!.y
          } : undefined

          if (store.pidAutoRoute && startConnection.value && endConn) {
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
            startConnection: startConnection.value ?? undefined,
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

  // Determine final coords: snap-to-port > raw
  let endCoords: PidPoint
  if (nearestPort) {
    endCoords = { x: nearestPort.x, y: nearestPort.y }
  } else {
    endCoords = rawCoords
  }

  // Add final point (with L-bend corner in orthogonal mode)
  if (currentPipePoints.value.length >= 1) {
    const shouldOrtho = orthogonalPipes.value && !shiftHeld.value
    if (shouldOrtho) {
      const lastPt = currentPipePoints.value[currentPipePoints.value.length - 1]!
      const corner = getOrthogonalCorner(lastPt, endCoords)
      if (corner) currentPipePoints.value.push(corner)
    }
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
      endArrow: 'arrow',  // Default flow direction indicator
      // Store connection info if snapped to symbol ports (not pipe endpoints)
      startConnection: startConnection.value || undefined,
      endConnection: (nearestPort && !isPipeEndpointSnap(nearestPort)) ? {
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
    } else {
      endCoords = rawCoords
    }

    if (currentPipePoints.value.length >= 1) {
      // In orthogonal mode, insert L-bend corner before the final point
      const shouldOrtho = orthogonalPipes.value && !shiftHeld.value
      if (shouldOrtho) {
        const lastPt = currentPipePoints.value[currentPipePoints.value.length - 1]!
        const corner = getOrthogonalCorner(lastPt, endCoords)
        if (corner) currentPipePoints.value.push(corner)
      }
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
        endArrow: 'arrow',  // Default flow direction indicator
        startConnection: startConnection.value || undefined,
        endConnection: (nearestPort && !isPipeEndpointSnap(nearestPort)) ? {
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
  // If a pipe or symbol is currently selected, show its context menu instead of the generic canvas menu
  if (props.editMode && !props.pipeDrawingMode) {
    if (selectedPipeId.value) {
      contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'pipe', id: selectedPipeId.value } }
    } else if (selectedSymbolId.value) {
      contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'symbol', id: selectedSymbolId.value } }
    } else {
      contextMenu.value = { x: event.clientX, y: event.clientY, target: { type: 'canvas' } }
    }
  }
}

function onCanvasMouseMove(event: MouseEvent) {
  if (props.pipeDrawingMode) {
    const rawCoords = getCanvasCoords(event)

    // Update snap target for visual feedback (ports highlight in pipe drawing mode)
    snapTarget.value = findNearestPort(rawCoords)

    if (isDrawingPipe.value) {
      // Determine preview position: snap-to-port > alignment-snap > orthogonal > raw
      if (snapTarget.value) {
        tempMousePos.value = { x: snapTarget.value.x, y: snapTarget.value.y }
        activeGuides.value = []
      } else if (currentPipePoints.value.length > 0) {
        // In orthogonal mode, the preview path (currentDrawingPath) automatically
        // inserts L-bend corners, so we pass the raw target position here.
        // The preview path renders as: lastPoint → corner → target
        let pos = rawCoords

        // #3.5 — Snap to symbol edges/centers during pipe drawing
        const snapDist = SNAP_THRESHOLD.value
        const guides: AlignmentGuide[] = []
        for (const sym of props.pidLayer.symbols) {
          const cx = sym.x + sym.width / 2
          const cy = sym.y + sym.height / 2
          const edges = [sym.x, sym.x + sym.width]
          const vEdges = [sym.y, sym.y + sym.height]
          for (const ex of [...edges, cx]) {
            if (Math.abs(pos.x - ex) < snapDist) {
              pos = { ...pos, x: ex }
              guides.push({ axis: 'v', pos: ex, from: Math.min(sym.y, pos.y), to: Math.max(sym.y + sym.height, pos.y) })
              break
            }
          }
          for (const ey of [...vEdges, cy]) {
            if (Math.abs(pos.y - ey) < snapDist) {
              pos = { ...pos, y: ey }
              guides.push({ axis: 'h', pos: ey, from: Math.min(sym.x, pos.x), to: Math.max(sym.x + sym.width, pos.x) })
              break
            }
          }
        }
        activeGuides.value = guides
        tempMousePos.value = pos
      } else {
        tempMousePos.value = rawCoords
        activeGuides.value = []
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

  // Delete selected element (only when not drawing) — route through store for undo + pipe cleanup
  if ((event.key === 'Delete' || event.key === 'Backspace') && !isDrawingPipe.value && (selectedSymbolId.value || selectedPipeId.value)) {
    if (selectedSymbolId.value) {
      store.pidSelectItems([selectedSymbolId.value], [], [])
      store.pidDeleteSelected()
      selectedSymbolId.value = null
      emit('select:symbol', null)
    } else if (selectedPipeId.value) {
      store.pidDeletePipeSegment(selectedPipeId.value, selectedPipeSegmentIdx.value)
      selectedPipeId.value = null; selectedPipeSegmentIdx.value = null
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

function onCanvasBlur() {
  // Reset held key states when canvas loses focus (prevents stuck keys)
  shiftHeld.value = false
  spaceHeld.value = false
}

// Drag-drop symbol from panel
function onCanvasDragOver(event: DragEvent) {
  if (!props.editMode || !event.dataTransfer) return
  if (event.dataTransfer.types.includes('application/x-pid-symbol') ||
      event.dataTransfer.types.includes('application/x-pid-template')) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function onCanvasDrop(event: DragEvent) {
  if (!props.editMode || !event.dataTransfer) return

  // Handle template drop
  const templateId = event.dataTransfer.getData('application/x-pid-template')
  if (templateId) {
    const coords = getCanvasCoords(event as unknown as MouseEvent)
    store.instantiatePidTemplate(templateId, Math.round(coords.x), Math.round(coords.y))
    return
  }

  const symbolType = event.dataTransfer.getData('application/x-pid-symbol')
  if (!symbolType) return

  const coords = getCanvasCoords(event as unknown as MouseEvent)
  const hmiSize = getHmiDefaultSize(symbolType)
  const w = hmiSize?.width ?? 60
  const h = hmiSize?.height ?? 60

  // Check if symbol is dropped on an existing pipe (inline insertion)
  const hitPipe = findPipeAtPoint(coords.x, coords.y, 15 / zoom.value)

  const newSymbolId = store.addPidSymbolWithUndo({
    type: symbolType as import('../assets/symbols').ScadaSymbolType,
    x: coords.x - w / 2,
    y: coords.y - h / 2,
    width: w,
    height: h,
    rotation: 0,
    color: hmiSize ? undefined : '#60a5fa',
    showValue: false
  })

  // If dropped on a pipe, split the pipe and connect both halves to the new symbol
  if (hitPipe && newSymbolId) {
    splitPipeAtSymbol(hitPipe.pipe, hitPipe.segmentIndex, coords, newSymbolId, w, h, symbolType)
  }

  store.pidTrackRecentSymbol(symbolType)
}

/** Find a pipe near a point (returns pipe and segment index). */
function findPipeAtPoint(px: number, py: number, threshold: number): { pipe: PidPipe; segmentIndex: number } | null {
  let best: { pipe: PidPipe; segmentIndex: number; dist: number } | null = null
  for (const pipe of props.pidLayer.pipes) {
    for (let i = 0; i < pipe.points.length - 1; i++) {
      const p1 = pipe.points[i]!
      const p2 = pipe.points[i + 1]!
      const dist = distanceToSegment(px, py, p1.x, p1.y, p2.x, p2.y)
      if (dist < threshold && (!best || dist < best.dist)) {
        best = { pipe, segmentIndex: i, dist }
      }
    }
  }
  return best
}

/** Split a pipe at a dropped symbol position, creating two pipe halves connected to the symbol. */
function splitPipeAtSymbol(
  pipe: PidPipe,
  segmentIndex: number,
  dropPoint: PidPoint,
  symbolId: string,
  symbolW: number,
  symbolH: number,
  symbolType: string
) {
  // Get the symbol's ports to determine connection points
  const symType = symbolType as ScadaSymbolType
  const ports = SYMBOL_PORTS[symType]
  if (!ports || ports.length < 2) return  // Need at least 2 ports (inlet/outlet)

  const inletPort = ports.find(p => INLET_PORT_IDS.has(p.id)) || ports[0]!
  const outletPort = ports.find(p => OUTLET_PORT_IDS.has(p.id)) || ports[1] || ports[0]!

  // Calculate symbol position
  const symX = dropPoint.x - symbolW / 2
  const symY = dropPoint.y - symbolH / 2

  // Get port absolute positions
  const inletPos = getPortPosition(symType, inletPort.id, symX, symY, symbolW, symbolH, 0)
  const outletPos = getPortPosition(symType, outletPort.id, symX, symY, symbolW, symbolH, 0)
  if (!inletPos || !outletPos) return

  // Split pipe points: first half goes from pipe start → symbol inlet
  const firstHalfPoints = [...pipe.points.slice(0, segmentIndex + 1), { x: inletPos.x, y: inletPos.y }]
  // Second half goes from symbol outlet → pipe end
  const secondHalfPoints = [{ x: outletPos.x, y: outletPos.y }, ...pipe.points.slice(segmentIndex + 1)]

  // Create two new pipes
  const pipe1: PidPipe = {
    ...pipe,
    id: `pipe-${Date.now()}-a`,
    points: firstHalfPoints,
    endArrow: undefined,
    startConnection: pipe.startConnection,
    endConnection: { symbolId, portId: inletPort.id, x: inletPos.x, y: inletPos.y },
    endSymbolId: symbolId,
    endPortId: inletPort.id,
  }

  const pipe2: PidPipe = {
    ...pipe,
    id: `pipe-${Date.now()}-b`,
    points: secondHalfPoints,
    startArrow: undefined,
    endArrow: pipe.endArrow,
    startConnection: { symbolId, portId: outletPort.id, x: outletPos.x, y: outletPos.y },
    endConnection: pipe.endConnection,
    startSymbolId: symbolId,
    startPortId: outletPort.id,
  }

  // Remove old pipe, add two new pipes
  const newPipes = props.pidLayer.pipes.filter(p => p.id !== pipe.id)
  newPipes.push(pipe1, pipe2)

  emit('update:pidLayer', {
    ...props.pidLayer,
    pipes: newPipes,
  })
}

/** Port IDs considered inlets (used for inline insertion). */
const INLET_PORT_IDS = new Set(['inlet', 'suction', 'input', 'in', 'return', 'fill', 'process'])
/** Port IDs considered outlets (used for inline insertion). */
const OUTLET_PORT_IDS = new Set(['outlet', 'discharge', 'output', 'out', 'supply', 'vent', 'drain'])

// Get current drawing path (preview)
const currentDrawingPath = computed(() => {
  if (!isDrawingPipe.value || currentPipePoints.value.length === 0) return ''

  const points = [...currentPipePoints.value]
  if (tempMousePos.value && points.length > 0) {
    // In orthogonal mode, insert an L-bend corner before the preview endpoint
    const shouldOrtho = orthogonalPipes.value && !shiftHeld.value
    if (shouldOrtho) {
      const lastPt = points[points.length - 1]!
      const corner = getOrthogonalCorner(lastPt, tempMousePos.value)
      if (corner) points.push(corner)
    }
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

  // Find which segment was clicked (needed for selection + dragging)
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

  // Select the pipe + segment and ensure canvas has focus for keyboard events (Delete key)
  selectedPipeId.value = pipe.id
  selectedPipeSegmentIdx.value = closestSegment
  selectedSymbolId.value = null
  emit('select:pipe', pipe.id)
  emit('select:symbol', null)
  canvasRef.value?.focus()

  // Layer-locked pipes can be selected but not dragged
  if (store.isLayerLocked(pipe.layerId)) return

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
// Get connected pipe chain through symbol ports (#5.5)
function getConnectedPipes(pipeId: string): string[] {
  const visited = new Set<string>([pipeId])
  const queue = [pipeId]

  while (queue.length > 0) {
    const currentId = queue.shift()!
    const current = props.pidLayer.pipes.find(p => p.id === currentId)
    if (!current) continue

    // Find symbols at both ends
    const connectedSymbolIds = [current.startSymbolId, current.endSymbolId].filter(Boolean) as string[]

    for (const symbolId of connectedSymbolIds) {
      // Find other pipes connected to this symbol
      for (const other of props.pidLayer.pipes) {
        if (visited.has(other.id)) continue
        if (other.startSymbolId === symbolId || other.endSymbolId === symbolId) {
          visited.add(other.id)
          queue.push(other.id)
        }
      }
    }
  }

  return Array.from(visited)
}

function onPipeClick(event: MouseEvent, pipe: PidPipe) {
  if (!props.editMode) return
  event.stopPropagation()

  // Shift+click: select connected pipe chain (#5.5)
  if (event.shiftKey) {
    const chain = getConnectedPipes(pipe.id)
    store.pidSelectItems([], chain, [])
    return
  }

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

  selectedPipeId.value = pipe.id
  selectedPipeSegmentIdx.value = closestSegment
  selectedSymbolId.value = null
  emit('select:pipe', pipe.id)
  emit('select:symbol', null)
  canvasRef.value?.focus()
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
    const idx = draggingPipePoint.value!.pointIndex
    let target = coords

    // When orthogonal mode is on, constrain point to maintain 90-degree angles
    if (orthogonalPipes.value && !shiftHeld.value) {
      const prev = pipe.points[idx - 1]
      const next = pipe.points[idx + 1]
      if (prev && next) {
        // Snap to the grid intersection of the previous and next point axes
        // Choose the axis combination closest to the raw cursor position
        const opt1 = { x: prev.x, y: next.y }  // vertical from prev, horizontal from next
        const opt2 = { x: next.x, y: prev.y }  // horizontal from prev, vertical from next
        const d1 = Math.hypot(coords.x - opt1.x, coords.y - opt1.y)
        const d2 = Math.hypot(coords.x - opt2.x, coords.y - opt2.y)
        target = d1 < d2 ? opt1 : opt2
      } else if (prev) {
        target = constrainToOrthogonal(coords, prev)
      } else if (next) {
        target = constrainToOrthogonal(coords, next)
      }
    }

    const newPoints = pipe.points.map((p, i) =>
      i === idx ? target : p
    )
    return { ...pipe, points: newPoints }
  })

  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })
}

// Insert a midpoint between two existing points and start dragging it (#3.1)
function onPipeMidpointMouseDown(event: MouseEvent, pipeId: string, afterIndex: number) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  const pipe = props.pidLayer.pipes.find(p => p.id === pipeId)
  if (!pipe || afterIndex >= pipe.points.length - 1) return

  const p1 = pipe.points[afterIndex]!
  const p2 = pipe.points[afterIndex + 1]!
  const midpoint: PidPoint = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }

  // Insert the new point
  const newPoints = [...pipe.points]
  newPoints.splice(afterIndex + 1, 0, midpoint)
  const newPipes = props.pidLayer.pipes.map(p =>
    p.id === pipeId ? { ...p, points: newPoints } : p
  )
  emit('update:pidLayer', { ...props.pidLayer, pipes: newPipes })

  // Immediately start dragging the new point
  draggingPipePoint.value = { pipeId, pointIndex: afterIndex + 1 }
  window.addEventListener('mousemove', onPipePointMove)
  window.addEventListener('mouseup', onPipePointEnd)
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
    @blur="onCanvasBlur"
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
          :d="generatePipePath(pipeView(pipe))"
          stroke="transparent"
          stroke-width="16"
          fill="none"
          class="pipe-hit-area"
          @mousedown.stop="onPipeMouseDown($event, pipe)"
          @dblclick.stop="onPipeDoubleClick($event, pipe)"
          @contextmenu.prevent.stop="onPipeRightClick($event, pipe)"
        />
        <!-- Visible pipe -->
        <path
          :d="generatePipePathWithJumps(pipeView(pipe))"
          :stroke="getPipeMediumColor(pipe)"
          :stroke-width="pipe.strokeWidth || 3"
          :stroke-opacity="pipe.opacity ?? 1"
          :stroke-dasharray="getPipeDashArray(pipe)"
          :marker-start="getMarkerUrl(pipe, 'start')"
          :marker-end="getMarkerUrl(pipe, 'end')"
          stroke-linecap="round"
          stroke-linejoin="round"
          fill="none"
          class="pipe-path"
          :class="{ selected: selectedPipeId === pipe.id, dragging: draggingSegment?.pipeId === pipe.id, 'alarm-propagation': alarmedPipeIds.has(pipe.id) }"
          pointer-events="none"
        />

        <!-- Selected segment highlight -->
        <path
          v-if="editMode && selectedPipeId === pipe.id && selectedPipeSegmentIdx != null && pipe.points[selectedPipeSegmentIdx] && pipe.points[selectedPipeSegmentIdx + 1]"
          :d="`M ${pipe.points[selectedPipeSegmentIdx]!.x} ${pipe.points[selectedPipeSegmentIdx]!.y} L ${pipe.points[selectedPipeSegmentIdx + 1]!.x} ${pipe.points[selectedPipeSegmentIdx + 1]!.y}`"
          stroke="#f59e0b"
          :stroke-width="(pipe.strokeWidth || 3) + 4"
          stroke-linecap="round"
          fill="none"
          class="pipe-segment-highlight"
          pointer-events="none"
          opacity="0.5"
        />

        <!-- Heat trace zigzag (ISA marking alongside pipe) -->
        <path
          v-if="pipe.heatTrace && pipe.heatTrace !== 'none' && (editMode || isHeatTraceActive(pipe))"
          :d="generateHeatTracePath(getPipePointsWithBundling(pipe))"
          :stroke="getHeatTraceColor(pipe.heatTrace)"
          :stroke-width="1.5 / zoom"
          stroke-linecap="round"
          stroke-linejoin="round"
          fill="none"
          pointer-events="none"
          :opacity="isHeatTraceActive(pipe) ? 1 : 0.3"
        />

        <!-- Flow animation (enhanced) -->
        <path
          v-if="getPipeFlowState(pipe).animated"
          :d="generatePipePath(pipeView(pipe))"
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
          :d="generatePipePath(pipeView(pipe))"
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

        <!-- Flow particles (animateMotion circles along pipe path) -->
        <template v-if="pipe.flowParticles && getPipeFlowState(pipe).animated">
          <!-- Hidden reference path for animateMotion (clean path without jumps) -->
          <path
            :id="'pipe-path-' + pipe.id"
            :d="generatePipePath(pipeView(pipe))"
            fill="none" stroke="none"
          />
          <circle
            v-for="i in (pipe.particleCount || 4)"
            :key="'particle-' + pipe.id + '-' + i"
            :r="Math.max(2, (pipe.strokeWidth || 3) * 0.6) / zoom"
            :fill="pipe.particleColor || getPipeMediumColor(pipe)"
            opacity="0.8"
          >
            <animateMotion
              :dur="getFlowAnimationDuration(getPipeFlowState(pipe).speed)"
              repeatCount="indefinite"
              :begin="`${(i - 1) / (pipe.particleCount || 4) * parseFloat(getFlowAnimationDuration(getPipeFlowState(pipe).speed))}s`"
              :keyPoints="getPipeFlowState(pipe).direction === 'reverse' ? '1;0' : '0;1'"
              keyTimes="0;1"
              calcMode="linear"
            >
              <mpath :href="'#pipe-path-' + pipe.id" />
            </animateMotion>
          </circle>
        </template>

        <!-- Pipe label (double-click to edit inline; auto-labels from medium) -->
        <g v-if="getPipeDisplayLabel(pipe) && getPipeLabelPoint(pipe)" class="pipe-label-group"
          :class="{ 'editable': editMode }"
          @dblclick.stop="onPipeLabelDblClick($event, pipe)">
          <rect
            :x="getPipeLabelPoint(pipe)!.x - (getPipeDisplayLabel(pipe).length * 3.5 + 6) / zoom"
            :y="getPipeLabelPoint(pipe)!.y - 8 / zoom"
            :width="(getPipeDisplayLabel(pipe).length * 7 + 12) / zoom"
            :height="16 / zoom"
            :rx="3 / zoom"
            :style="{ fill: 'var(--bg-panel)' }"
            class="pipe-label-bg"
          />
          <text
            :x="getPipeLabelPoint(pipe)!.x"
            :y="getPipeLabelPoint(pipe)!.y"
            text-anchor="middle"
            dominant-baseline="central"
            :fill="getPipeMediumColor(pipe)"
            :font-size="12 / zoom"
            class="pipe-label-text"
          >{{ getPipeDisplayLabel(pipe) }}</text>
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
          <!-- Midpoint waypoint handles (#3.1) -->
          <g
            v-for="idx in pipe.points.length - 1"
            :key="'mid-' + idx"
            class="pipe-midpoint"
            @mousedown="onPipeMidpointMouseDown($event, pipe.id, idx - 1)"
          >
            <circle
              :cx="(pipe.points[idx - 1]!.x + pipe.points[idx]!.x) / 2"
              :cy="(pipe.points[idx - 1]!.y + pipe.points[idx]!.y) / 2"
              :r="5 / zoom"
              :stroke-width="1.5 / zoom"
            />
            <line
              :x1="(pipe.points[idx - 1]!.x + pipe.points[idx]!.x) / 2 - 3 / zoom"
              :y1="(pipe.points[idx - 1]!.y + pipe.points[idx]!.y) / 2"
              :x2="(pipe.points[idx - 1]!.x + pipe.points[idx]!.x) / 2 + 3 / zoom"
              :y2="(pipe.points[idx - 1]!.y + pipe.points[idx]!.y) / 2"
              :stroke-width="1.5 / zoom"
              stroke="currentColor"
            />
            <line
              :x1="(pipe.points[idx - 1]!.x + pipe.points[idx]!.x) / 2"
              :y1="(pipe.points[idx - 1]!.y + pipe.points[idx]!.y) / 2 - 3 / zoom"
              :x2="(pipe.points[idx - 1]!.x + pipe.points[idx]!.x) / 2"
              :y2="(pipe.points[idx - 1]!.y + pipe.points[idx]!.y) / 2 + 3 / zoom"
              :stroke-width="1.5 / zoom"
              stroke="currentColor"
            />
          </g>
          <!-- Bend radius indicators (#5.4) -->
          <template v-if="pipe.rounded && pipe.points.length >= 3">
            <circle
              v-for="idx in pipe.points.length - 2"
              :key="'bend-' + idx"
              :cx="pipe.points[idx]!.x"
              :cy="pipe.points[idx]!.y"
              :r="(pipe.cornerRadius || 8)"
              fill="none"
              stroke="#3b82f6"
              :stroke-width="1 / zoom"
              stroke-dasharray="4,3"
              opacity="0.4"
              class="bend-indicator"
            />
          </template>
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

      <!-- Custom port stub lines (always visible — matches built-in SVG stubs) -->
      <g v-if="customPortStubs.length" class="custom-port-stubs">
        <line
          v-for="stub in customPortStubs"
          :key="stub.key"
          :x1="stub.x1" :y1="stub.y1"
          :x2="stub.x2" :y2="stub.y2"
          :stroke="stub.color"
          :stroke-width="2 / zoom"
          stroke-linecap="round"
        />
      </g>

      <!-- Port dots (always visible in edit mode for equipment-type symbols) -->
      <g v-if="editMode && nozzlePorts.length" class="nozzle-ports">
        <circle
          v-for="p in nozzlePorts"
          :key="`port-${p.symbolId}-${p.portId}`"
          :cx="p.x"
          :cy="p.y"
          :r="4 / zoom"
          :fill="p.color"
          :stroke="p.color"
          :stroke-width="1.5 / zoom"
          fill-opacity="0.4"
          class="nozzle-port-dot"
          @contextmenu.prevent.stop="onPortRightClick($event, p.symbolId, p.portId)"
        />
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
              :r="(pipeDrawingMode ? 8 : 5) / zoom"
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

      <!-- Pipe endpoint indicators (shown when drawing pipes for pipe-to-pipe snapping) -->
      <g v-if="pipeDrawingMode" class="pipe-endpoint-indicators">
        <template v-for="pipe in visiblePipes" :key="`pep-${pipe.id}`">
          <circle
            v-if="pipe.points.length >= 2"
            :cx="pipe.points[0]!.x"
            :cy="pipe.points[0]!.y"
            :r="6 / zoom"
            class="port-indicator pipe-endpoint"
            :class="{ 'snap-active': snapTarget?.symbolId === `pipe:${pipe.id}` && snapTarget?.portId === 'start' }"
            :stroke-width="1.5 / zoom"
          />
          <circle
            v-if="pipe.points.length >= 2"
            :cx="pipe.points[pipe.points.length - 1]!.x"
            :cy="pipe.points[pipe.points.length - 1]!.y"
            :r="6 / zoom"
            class="port-indicator pipe-endpoint"
            :class="{ 'snap-active': snapTarget?.symbolId === `pipe:${pipe.id}` && snapTarget?.portId === 'end' }"
            :stroke-width="1.5 / zoom"
          />
        </template>
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
        selected: selectedSymbolId === symbol.id || store.pidSelectedIds.symbolIds.includes(symbol.id),
        'has-channel': !!symbol.channel
      }"
      :style="getSymbolStyle(symbol)"
      @mousedown="onSymbolMouseDown($event, symbol)"
      @dblclick="onSymbolDoubleClick($event, symbol)"
      @contextmenu.prevent="onSymbolRightClick($event, symbol)"
      @mouseenter="hoveredSymbolId = symbol.id; showRuntimeTooltip(symbol)"
      @mouseleave="hoveredSymbolId = null; hideRuntimeTooltip()"
    >
      <!-- HMI Control (HTML component) -->
      <template v-if="isHmiControl(symbol.type)">
        <div :style="{ pointerEvents: editMode ? 'none' : 'auto' }" style="width: 100%; height: 100%">
          <component
            :is="getHmiComponent(symbol.type)"
            :symbol="symbol"
            :edit-mode="editMode"
          />
        </div>
      </template>
      <!-- Off-Page Connector (label inside pentagon) -->
      <template v-else-if="OFF_PAGE_CONNECTOR_TYPES.has(symbol.type)">
        <div
          class="symbol-svg"
          :style="{ color: getSymbolColor(symbol) }"
          v-html="getSymbolSvg(symbol.type, store.pidCustomSymbols)"
        />
        <div class="offpage-label" :class="{ 'not-linked': editMode && !symbol.linkedPageId }">
          {{ symbol.label || '?' }}
        </div>
      </template>
      <!-- Process Symbol SVG (with tank fill support) -->
      <template v-else>
        <div
          class="symbol-svg"
          :class="getSymbolAnimationClass(symbol)"
          :style="{ color: getSymbolColor(symbol) }"
          v-html="isTankSymbol(symbol)
            ? getTankSvgWithFill(symbol)
            : (isValveSymbol(symbol) && symbol.positionChannel)
              ? getValveSvgWithPosition(symbol)
              : symbol.type === 'conveyor'
                ? getConveyorSvgWithAnimation(symbol)
                : getSymbolSvg(symbol.type, store.pidCustomSymbols, symbol)"
        />

        <!-- Label -->
        <div v-if="symbol.label" class="symbol-label">{{ symbol.label }}</div>

        <!-- Value -->
        <div v-if="symbol.showValue && symbol.channel" class="symbol-value">
          {{ getSymbolValue(symbol) }}
        </div>
      </template>

      <!-- ISA-5.1 Instrument Bubble (shown on instruments with label) -->
      <div
        v-if="isInstrumentSymbol(symbol.type) && symbol.label && getIsaFunctionLetters(symbol)"
        class="isa-bubble"
      >
        <svg width="44" height="28" viewBox="0 0 44 28">
          <circle cx="22" cy="14" r="13" stroke="currentColor" stroke-width="1.5" fill="none"/>
          <line x1="9" y1="14" x2="35" y2="14" stroke="currentColor" stroke-width="1"/>
          <text x="22" y="11" text-anchor="middle" font-size="8" font-weight="600" fill="currentColor">{{ parseIsaTagNumber(symbol.label) }}</text>
          <text x="22" y="22" text-anchor="middle" font-size="8" font-weight="600" fill="currentColor">{{ getIsaFunctionLetters(symbol) }}</text>
        </svg>
      </div>

      <!-- Interlock Shield Badge (runtime only, on symbols with explicit interlockId binding) -->
      <div
        v-if="!editMode && symbol.interlockId && getInterlockBadge(symbol)"
        class="interlock-badge"
        :class="getInterlockBadge(symbol)!.state"
        :title="getInterlockBadge(symbol)!.tooltip"
      >
        <svg width="14" height="16" viewBox="0 0 14 16" fill="currentColor">
          <path d="M7 0L0 3v5c0 3.87 2.99 7.49 7 8 4.01-.51 7-4.13 7-8V3L7 0z"/>
        </svg>
      </div>

      <!-- Block Editor Indicators (rendered on symbol perimeter) -->
      <template v-if="symbol.indicators?.length">
        <div
          v-for="ind in symbol.indicators"
          :key="ind.id"
          class="pid-indicator"
          :style="getIndicatorEdgeStyle(symbol, ind)"
        >
          <!-- Signal line stub -->
          <svg class="indicator-signal-svg" width="80" height="80"
               style="position: absolute; left: -30px; top: -30px; overflow: visible; pointer-events: none;">
            <line
              :x1="30" :y1="30"
              :x2="30 + getIndicatorSignalEnd(ind).dx" :y2="30 + getIndicatorSignalEnd(ind).dy"
              :stroke="editMode ? '#475569' : getIndicatorRuntimeColor(ind)"
              stroke-width="1"
              :stroke-dasharray="getSignalLineDashArray(ind)"
            />
          </svg>
          <!-- Shape -->
          <svg class="indicator-shape-icon" width="14" height="14" viewBox="0 0 14 14"
               :style="{ color: editMode ? '#94a3b8' : getIndicatorRuntimeColor(ind) }">
            <circle v-if="ind.shape === 'circle'" cx="7" cy="7" r="6"
              fill="none" stroke="currentColor" stroke-width="1.2" />
            <template v-else-if="ind.shape === 'circleBar'">
              <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" stroke-width="1.2" />
              <line x1="1" y1="7" x2="13" y2="7" stroke="currentColor" stroke-width="0.8" />
            </template>
            <circle v-else-if="ind.shape === 'dashedCircle'" cx="7" cy="7" r="6"
              fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="2.5,1.5" />
            <template v-else-if="ind.shape === 'circleInSquare'">
              <rect x="0.5" y="0.5" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1" />
              <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1" />
            </template>
            <polygon v-else-if="ind.shape === 'diamond'"
              points="7,1 13,7 7,13 1,7" fill="none" stroke="currentColor" stroke-width="1.2" />
            <polygon v-else-if="ind.shape === 'flag'"
              points="1,1 13,1 13,9 7,7 1,9" fill="none" stroke="currentColor" stroke-width="1.2" />
            <rect v-else-if="ind.shape === 'square'"
              x="1" y="1" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.2" />
            <polygon v-else-if="ind.shape === 'hexagon'"
              points="4,1 10,1 13,7 10,13 4,13 1,7" fill="none" stroke="currentColor" stroke-width="1.2" />
          </svg>
          <!-- ISA label -->
          <span v-if="ind.isaLetters || ind.label" class="indicator-isa-text"
                :style="{ transform: `scale(${1/zoom})` }">
            {{ ind.isaLetters || ind.label }}
          </span>
          <!-- Live value (runtime only) -->
          <span v-if="!editMode && ind.showValue && ind.channel" class="indicator-live-value"
                :class="{ alarm: isIndicatorInAlarm(ind) }"
                :style="{ transform: `scale(${1/zoom})` }">
            {{ getIndicatorValue(ind) }}
          </span>
        </div>
      </template>

      <!-- Procedure Step Badge (#6.5) -->
      <div
        v-if="procedureStepBadges.has(symbol.id)"
        class="procedure-badge"
        :class="procedureStepBadges.get(symbol.id)!.status"
        :title="`Step ${procedureStepBadges.get(symbol.id)!.stepNum}`"
      >{{ procedureStepBadges.get(symbol.id)!.status === 'done' ? '\u2713' : procedureStepBadges.get(symbol.id)!.stepNum }}</div>

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
        fontStyle: text.fontStyle || 'normal',
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

    <!-- Operator Notes (#6.6) — runtime sticky notes -->
    <template v-if="!editMode">
      <div
        v-for="note in store.pidOperatorNotes"
        :key="note.id"
        class="operator-note"
        :style="{
          left: `${note.x}px`,
          top: `${note.y}px`,
          borderColor: note.color,
          '--note-color': note.color,
        }"
        @mousedown.stop="onNoteMouseDown($event, note)"
        @dblclick.stop="startNoteEdit(note)"
        @contextmenu.prevent.stop="store.pidRemoveOperatorNote(note.id)"
      >
        <div class="note-header">
          <span class="note-author">{{ note.author }}</span>
          <span class="note-time">{{ new Date(note.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</span>
          <button class="note-color-btn" @click.stop="cycleNoteColor(note.id)" title="Change color">
            <span class="note-color-dot" :style="{ background: note.color }" />
          </button>
        </div>
        <div v-if="editingNoteId !== note.id" class="note-text">{{ note.text }}</div>
        <textarea
          v-else
          v-model="editingNoteText"
          class="note-edit"
          @keydown.enter.prevent="commitNoteEdit"
          @keydown.escape.prevent="editingNoteId = null"
          @blur="commitNoteEdit"
          @click.stop
          autofocus
        />
      </div>
    </template>

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
          :points="getPipePointsWithBundling(pipe).map(p => `${p.x},${p.y}`).join(' ')"
          fill="none" :stroke="getPipeMediumColor(pipe)" stroke-width="2" stroke-opacity="0.6"
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

    <!-- Focus mode badge -->
    <Transition name="focus-badge">
      <div v-if="store.pidFocusMode && showFocusBadge" class="focus-badge">
        Focus Mode — press \ to exit
      </div>
    </Transition>

    <!-- Operator Note Add Button (runtime mode) -->
    <button
      v-if="!editMode"
      class="add-note-btn"
      @click="addOperatorNote($event)"
      title="Add operator note (double-click to place)"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <line x1="12" y1="8" x2="12" y2="16" />
        <line x1="8" y1="12" x2="16" y2="12" />
      </svg>
      Note
    </button>

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
      :pipeSegmentCount="contextMenu.target.type === 'pipe' ? (pidLayer.pipes.find(p => p.id === (contextMenu!.target as { type: 'pipe'; id: string }).id)?.points.length ?? 2) - 1 : undefined"
      @action="handleContextMenuAction"
      @close="contextMenu = null"
    />

    <!-- Template Save Dialog -->
    <Teleport to="body">
      <div v-if="showTemplateSaveDialog" class="pid-modal-overlay" @click.self="showTemplateSaveDialog = false">
        <div class="pid-modal-dialog">
          <div class="pid-modal-title">Save as Template</div>
          <label class="pid-modal-label">Name</label>
          <input v-model="templateName" class="pid-modal-input" placeholder="e.g. Pump Station" autofocus @keydown.enter="saveTemplate" />
          <label class="pid-modal-label">Category</label>
          <select v-model="templateCategory" class="pid-modal-input">
            <option>General</option>
            <option>Control Loops</option>
            <option>Equipment Groups</option>
            <option>Safety Systems</option>
          </select>
          <div class="pid-modal-actions">
            <button class="pid-modal-btn" @click="showTemplateSaveDialog = false">Cancel</button>
            <button class="pid-modal-btn primary" :disabled="!templateName.trim()" @click="saveTemplate">Save</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Runtime Tooltip (#6.1) -->
    <div
      v-if="tooltipSymbol && tooltipSymbol.channel"
      class="runtime-tooltip"
      :style="{
        left: (tooltipPos.x * zoom + panX) + 'px',
        top: (tooltipPos.y * zoom + panY) + 'px'
      }"
    >
      <div class="tooltip-channel">{{ tooltipSymbol.channel }}</div>
      <div class="tooltip-value">
        {{ getSymbolValue(tooltipSymbol) }}
        <span v-if="store.channels[tooltipSymbol.channel]?.unit" class="tooltip-unit">{{ store.channels[tooltipSymbol.channel]?.unit }}</span>
      </div>
      <div v-if="isSymbolInAlarm(tooltipSymbol)" class="tooltip-alarm">ALARM</div>
      <div v-if="isSymbolDisconnected(tooltipSymbol)" class="tooltip-disconnected">DISCONNECTED</div>
    </div>

    <!-- Block Editor (Edit Mode — double-click to open) -->
    <PidBlockEditor
      v-if="showBlockEditor && blockEditorSymbol"
      :symbol="blockEditorSymbol"
      @save="onBlockEditorSave"
      @cancel="onBlockEditorCancel"
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
  z-index: 5;
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
  border: 2px dashed var(--color-accent-light);
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
  filter: drop-shadow(0 0 3px var(--color-accent-glow));
}

.pipe-path.selected {
  stroke-width: 5;
  filter: drop-shadow(0 0 6px currentColor);
}

.pipe-path.dragging {
  stroke-width: 6;
  filter: drop-shadow(0 0 8px var(--color-success));
}

/* Alarm propagation glow (#6.4) */
.pipe-path.alarm-propagation {
  filter: drop-shadow(0 0 8px var(--color-error));
  animation: alarm-pipe-pulse 1.5s ease-in-out infinite;
}

@keyframes alarm-pipe-pulse {
  0%, 100% { filter: drop-shadow(0 0 4px var(--color-error)); }
  50% { filter: drop-shadow(0 0 12px var(--color-error)); }
}

/* Procedure step badges (#6.5) */
.procedure-badge {
  position: absolute;
  top: -12px;
  right: -8px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
  pointer-events: none;
}

.procedure-badge.current {
  background: var(--color-success);
  color: var(--text-primary);
  animation: procedure-pulse 1s ease-in-out infinite;
}

.procedure-badge.done {
  background: var(--border-heavy);
  color: var(--text-secondary);
}

.procedure-badge.pending {
  background: var(--bg-surface);
  color: var(--text-dim);
  border: 1px solid var(--bg-hover);
}

@keyframes procedure-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); }
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
  fill: var(--color-accent);
  stroke: var(--text-primary);
  stroke-width: 2;
  cursor: grab;
  transition: r 0.15s;
}

.pipe-point:hover {
  r: 8;
}

.pipe-point.first,
.pipe-point.last {
  fill: var(--color-success);
}

.pipe-midpoint circle {
  fill: var(--color-accent-bg);
  stroke: var(--color-accent-light);
  cursor: copy;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.pipe-midpoint:hover circle {
  opacity: 1;
  fill: var(--color-accent-border);
}

.pipe-midpoint line {
  pointer-events: none;
  color: var(--color-accent-light);
  opacity: 0.5;
}

.pipe-midpoint:hover line {
  opacity: 1;
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
  fill: var(--color-accent-border);
  stroke: var(--color-accent);
  stroke-width: 2;
  pointer-events: none;
  transition: all 0.15s;
}

/* Nozzle port dots on equipment symbols */
.nozzle-port-dot {
  pointer-events: none;
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
  background: var(--bg-surface);
  z-index: 51;
  border-right: 1px solid var(--bg-hover);
  border-bottom: 1px solid var(--bg-hover);
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
  fill: var(--color-success);
  stroke: var(--text-primary);
  stroke-width: 2;
  r: 8;
}

.snap-highlight {
  fill: none;
  stroke: var(--color-success);
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
  background: var(--bg-overlay);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  z-index: 60;
  cursor: pointer;
  overflow: hidden;
  box-shadow: var(--shadow-md);
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
  outline: 2px solid var(--color-accent-light);
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
  color: var(--text-primary);
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: none;
}

/* Focus mode badge */
.focus-badge {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(30, 58, 95, 0.9);
  color: #93c5fd;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  z-index: 60;
  pointer-events: none;
  backdrop-filter: blur(4px);
}

.focus-badge-enter-active { transition: opacity 0.3s; }
.focus-badge-leave-active { transition: opacity 1s; }
.focus-badge-enter-from,
.focus-badge-leave-to { opacity: 0; }

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

/* Selection indicator - visible outline + glow */
.edit-mode .pid-symbol.selected {
  outline: 2px solid rgba(59, 130, 246, 0.8);
  outline-offset: 2px;
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
  color: var(--text-muted);
  white-space: nowrap;
}

.isa-bubble {
  position: absolute;
  top: -30px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--text-secondary);
  pointer-events: none;
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
  color: var(--text-primary);
  background: var(--bg-overlay-light);
  padding: 2px 6px;
  border-radius: 3px;
}

/* Interlock shield badge */
.interlock-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 16px;
  height: 18px;
  z-index: 10;
  pointer-events: auto;
  cursor: help;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3));
}


.interlock-badge.satisfied { color: var(--color-success); }
.interlock-badge.failed {
  color: var(--color-error);
  animation: interlock-badge-pulse 1.5s ease-in-out infinite;
}
.interlock-badge.bypassed { color: #f59e0b; }

@keyframes interlock-badge-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Resize handles - small circular handles for clean design */
.resize-handle {
  position: absolute;
  width: 8px;
  height: 8px;
  background: rgba(59, 130, 246, 0.9);
  border: 1.5px solid var(--text-primary);
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
  background: var(--color-accent-light);
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
  color: var(--text-primary);
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

/* Hover port indicator (subtle blue, shown on symbol hover in edit mode) */
.port-indicator.hover-port {
  fill: var(--color-accent-glow);
  stroke: rgba(59, 130, 246, 0.8);
}

/* Custom port indicator styling in pipe drawing mode */
.port-indicator.custom-port {
  fill: rgba(34, 197, 94, 0.3);
  stroke: var(--color-success);
}

/* Pipe endpoint indicators for pipe-to-pipe snapping */
.port-indicator.pipe-endpoint {
  fill: rgba(251, 191, 36, 0.3);
  stroke: #f59e0b;
}

/* #2.1 — Rotating equipment animation (pumps, fans, motors) */
.pid-rotating :deep(svg) {
  animation: pid-spin 2s linear infinite;
}

@keyframes pid-spin {
  to { transform: rotate(360deg); }
}

/* #2.2 — Alarm blink for unacknowledged alarms (ISA-18.2) */
.pid-alarm-blink-fast {
  animation: pid-alarm-blink 0.5s step-end infinite;
}

.pid-alarm-blink-slow {
  animation: pid-alarm-blink 1s step-end infinite;
}

@keyframes pid-alarm-blink {
  50% { opacity: 0.3; }
}

/* #2.4 — Smooth tank fill level transitions */
.symbol-svg :deep(.level-fill) {
  transition: y 0.5s ease, height 0.5s ease;
}

/* Runtime Tooltip (#6.1) */
.pid-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 10000;
  display: flex; align-items: center; justify-content: center;
}
.pid-modal-dialog {
  background: var(--bg-panel); border: 1px solid var(--border-color);
  border-radius: 8px; padding: 16px; min-width: 280px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.pid-modal-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-primary); }
.pid-modal-label { font-size: 11px; color: var(--text-secondary); display: block; margin-bottom: 4px; margin-top: 8px; }
.pid-modal-input {
  width: 100%; padding: 6px 8px; background: var(--bg-widget); border: 1px solid var(--border-color);
  border-radius: 4px; color: var(--text-primary); font-size: 12px; outline: none; box-sizing: border-box;
}
.pid-modal-input:focus { border-color: var(--color-accent); }
.pid-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.pid-modal-btn {
  padding: 5px 12px; border-radius: 4px; border: 1px solid var(--border-color);
  background: var(--bg-widget); color: var(--text-primary); font-size: 11px; cursor: pointer;
}
.pid-modal-btn.primary { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
.pid-modal-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.runtime-tooltip {
  position: absolute;
  transform: translate(-50%, -100%);
  background: var(--bg-panel);
  border: 1px solid var(--color-accent);
  border-radius: 6px;
  padding: 6px 10px;
  pointer-events: none;
  z-index: 200;
  min-width: 100px;
  text-align: center;
}

.tooltip-channel {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.tooltip-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-bright);
}

.tooltip-unit {
  font-size: 10px;
  color: var(--text-secondary);
  font-weight: 400;
  margin-left: 2px;
}

.tooltip-alarm {
  font-size: 10px;
  font-weight: 700;
  color: var(--color-error);
  margin-top: 2px;
}

.tooltip-disconnected {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-dim);
  margin-top: 2px;
}

/* Operator Notes (#6.6) */
.operator-note {
  position: absolute;
  min-width: 120px;
  max-width: 220px;
  background: var(--bg-surface);
  border-left: 3px solid var(--note-color, var(--color-warning));
  border-radius: 4px;
  padding: 0;
  box-shadow: var(--shadow-lg);
  cursor: grab;
  z-index: 60;
  font-size: 11px;
}

.operator-note:active {
  cursor: grabbing;
}

.note-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 4px 4px 0 0;
}

.note-author {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-secondary);
  flex: 1;
}

.note-time {
  font-size: 8px;
  color: var(--text-dim);
}

.note-color-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 1px;
  display: flex;
  align-items: center;
}

.note-color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.note-text {
  padding: 4px 6px;
  color: var(--text-bright);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.3;
}

.note-edit {
  width: 100%;
  min-height: 40px;
  padding: 4px 6px;
  background: var(--bg-secondary);
  border: none;
  color: var(--text-bright);
  font-size: 11px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
}

.add-note-btn {
  position: absolute;
  bottom: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--bg-surface);
  border: 1px solid var(--bg-hover);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  z-index: 50;
  transition: background 0.15s, color 0.15s;
}

.add-note-btn:hover {
  background: var(--bg-hover);
  color: var(--color-warning);
  border-color: var(--color-warning);
}

/* Block Editor Indicators on symbol perimeter */
.pid-indicator {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 2px;
  pointer-events: none;
  z-index: 10;
}

.indicator-signal-svg {
  position: absolute;
  left: -30px;
  top: -30px;
  overflow: visible;
  pointer-events: none;
}

.indicator-shape-icon {
  flex-shrink: 0;
}

.indicator-isa-text {
  font-size: 8px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  transform-origin: left center;
}

.indicator-live-value {
  font-size: 9px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-bright);
  background: var(--bg-overlay-light);
  padding: 0 3px;
  border-radius: 2px;
  white-space: nowrap;
  transform-origin: left center;
}

.indicator-live-value.alarm {
  color: var(--color-error-light);
  background: var(--color-error-bg);
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
