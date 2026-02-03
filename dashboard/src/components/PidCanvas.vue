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
import { SCADA_SYMBOLS, SYMBOL_PORTS, getPortPosition, type ScadaSymbolType } from '../assets/symbols'
import type { PidSymbol, PidPipe, PidPoint, PidLayerData, PidPipeConnection } from '../types'
import PidFaceplate from './PidFaceplate.vue'

// Snap threshold in pixels
const SNAP_THRESHOLD = 15

// Grid snap settings (from store)
const gridSnapEnabled = computed(() => store.pidGridSnapEnabled)
const gridSize = computed(() => store.pidGridSize)
const showGrid = computed(() => store.pidShowGrid)
const orthogonalPipes = computed(() => store.pidOrthogonalPipes)

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
  let minDist = SNAP_THRESHOLD

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

// Canvas ref for coordinate calculations
const canvasRef = ref<HTMLElement | null>(null)

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
  // In runtime mode, open faceplate on click
  if (!props.editMode) {
    openFaceplate(event, symbol)
    return
  }

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

  // Check if symbol is in a group - select all group members
  const group = store.pidGetGroup(symbol.id)
  if (group) {
    store.pidSelectGroup(group.id)
  } else {
    // Single symbol selection
    store.pidSelectItems([symbol.id], [], [])
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

  if (hasMultiSelection && selectedSymbolIds.includes(selectedSymbolId.value)) {
    // Move all selected items together
    let newSymbols = props.pidLayer.symbols.map(s => {
      if (selectedSymbolIds.includes(s.id)) {
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

    // Update symbol position
    const newSymbols = props.pidLayer.symbols.map(s =>
      s.id === selectedSymbolId.value
        ? { ...s, x: newX, y: newY }
        : s
    )

    emit('update:pidLayer', { ...props.pidLayer, symbols: newSymbols })
  }
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

// ========================================================================
// MARQUEE (RUBBER-BAND) SELECTION
// ========================================================================

// Start marquee selection when clicking on empty canvas space
function onCanvasMouseDown(event: MouseEvent) {
  if (!props.editMode) return

  // Only start marquee if clicking directly on the canvas (not a symbol/pipe)
  // and not in pipe drawing mode
  if (event.target !== canvasRef.value || props.pipeDrawingMode) return

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

  return {
    left: `${x}px`,
    top: `${y}px`,
    width: `${width}px`,
    height: `${height}px`
  }
})

// Pipe drawing
function onCanvasClick(event: MouseEvent) {
  if (!props.editMode) return

  // Skip deselect if we just finished a marquee selection
  if (justDidMarquee.value) {
    justDidMarquee.value = false
    return
  }

  // If clicking on empty space, deselect
  if (event.target === canvasRef.value) {
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
          // Finish the pipe automatically
          const newPipe: PidPipe = {
            id: `pipe-${Date.now()}`,
            points: [...currentPipePoints.value],
            pathType: 'polyline',
            color: '#60a5fa',
            strokeWidth: 3,
            startConnection: startConnection.value,
            endConnection: {
              symbolId: nearestPort.symbolId,
              portId: nearestPort.portId,
              x: nearestPort.x,
              y: nearestPort.y
            }
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
      color: '#60a5fa',
      strokeWidth: 3,
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
  // Prevent context menu
  event.preventDefault()

  if (!props.pipeDrawingMode || !isDrawingPipe.value) return

  // Check for end snap-to-port
  const rawCoords = getCanvasCoords(event)
  const nearestPort = findNearestPort(rawCoords)

  // Apply orthogonal constraint by default (Shift disables it)
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
      color: '#60a5fa',
      strokeWidth: 3,
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

function onCanvasMouseMove(event: MouseEvent) {
  if (props.pipeDrawingMode) {
    const rawCoords = getCanvasCoords(event)

    // Update snap target for visual feedback
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
    :class="{ 'edit-mode': editMode, 'drawing-mode': pipeDrawingMode, 'ortho-mode': shiftHeld && pipeDrawingMode }"
    tabindex="0"
    @mousedown="onCanvasMouseDown"
    @click="onCanvasClick"
    @dblclick="onCanvasDoubleClick"
    @contextmenu="onCanvasRightClick"
    @mousemove="onCanvasMouseMove"
    @keydown="onCanvasKeyDown"
    @keyup="onCanvasKeyUp"
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

      <!-- Port indicators (shown when drawing pipes) -->
      <g v-if="pipeDrawingMode" class="port-indicators">
        <g v-for="symbol in pidLayer.symbols" :key="`ports-${symbol.id}`">
          <circle
            v-for="port in getSymbolPorts(symbol)"
            :key="port.id"
            :cx="port.x"
            :cy="port.y"
            r="6"
            class="port-indicator"
            :class="{
              'snap-active': snapTarget?.symbolId === symbol.id && snapTarget?.portId === port.id,
              'custom-port': port.isCustom
            }"
          />
        </g>
      </g>

      <!-- Snap highlight -->
      <circle
        v-if="snapTarget"
        :cx="snapTarget.x"
        :cy="snapTarget.y"
        r="12"
        class="snap-highlight"
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
          :class="{ 'group-selected': isGroupSelected(group.id) }"
        />
      </g>
    </svg>

    <!-- Symbols (positioned divs) -->
    <div
      v-for="symbol in pidLayer.symbols"
      :key="symbol.id"
      class="pid-symbol"
      :class="{
        selected: selectedSymbolId === symbol.id,
        'has-channel': !!symbol.channel
      }"
      :style="getSymbolStyle(symbol)"
      @mousedown="onSymbolMouseDown($event, symbol)"
      @dblclick="onSymbolDoubleClick($event, symbol)"
    >
      <!-- Symbol SVG (with tank fill support) -->
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

      <!-- Resize handles (only visible in edit mode when selected) -->
      <template v-if="editMode && selectedSymbolId === symbol.id">
        <div class="resize-handle nw" data-handle="nw" />
        <div class="resize-handle ne" data-handle="ne" />
        <div class="resize-handle sw" data-handle="sw" />
        <div class="resize-handle se" data-handle="se" />
      </template>
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
}

.pid-canvas.edit-mode {
  pointer-events: auto;
}

.pid-canvas.drawing-mode {
  cursor: crosshair;
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

/* Custom port indicator styling in pipe drawing mode */
.port-indicator.custom-port {
  fill: rgba(34, 197, 94, 0.3);
  stroke: #22c55e;
}
</style>
