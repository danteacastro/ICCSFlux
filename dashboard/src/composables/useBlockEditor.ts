/**
 * useBlockEditor - Interaction logic for the P&ID block editor overlay.
 *
 * Manages indicator placement, drag-along-edge, selection, and CRUD
 * for PidIndicator stubs on a symbol's perimeter.
 */

import { ref, computed, type Ref } from 'vue'
import type { PidSymbol, PidIndicator, PidIndicatorType, PidIndicatorShape } from '../types'

export interface SymbolBounds {
  left: number
  top: number
  width: number
  height: number
}

export interface GhostIndicator {
  edge: 'top' | 'right' | 'bottom' | 'left'
  edgeOffset: number
  x: number
  y: number
}

const EDGE_HIT_ZONE = 20 // px from edge to detect clicks/hover

function getIndicatorDefaults(type: PidIndicatorType): Partial<PidIndicator> {
  switch (type) {
    case 'channel_value':
      return { shape: 'circle', showValue: true, decimals: 1, signalLineDashed: true, signalLineLength: 30 }
    case 'interlock':
      return { shape: 'diamond', showValue: false, signalLineDashed: true, signalLineLength: 30 }
    case 'alarm_annotation':
      return { shape: 'flag', showValue: false, signalLineDashed: true, signalLineLength: 24 }
    case 'control_output':
      return { shape: 'square', showValue: false, signalLineDashed: false, signalLineLength: 30 }
  }
}

/**
 * Project a point onto the nearest edge of a rectangle.
 */
export function projectToNearestEdge(
  x: number, y: number, bounds: SymbolBounds
): { edge: 'top' | 'right' | 'bottom' | 'left'; edgeOffset: number } {
  const distTop = Math.abs(y - bounds.top)
  const distBottom = Math.abs(y - (bounds.top + bounds.height))
  const distLeft = Math.abs(x - bounds.left)
  const distRight = Math.abs(x - (bounds.left + bounds.width))

  const min = Math.min(distTop, distBottom, distLeft, distRight)

  if (min === distTop) {
    const offset = Math.max(0, Math.min(1, (x - bounds.left) / bounds.width))
    return { edge: 'top', edgeOffset: offset }
  }
  if (min === distBottom) {
    const offset = Math.max(0, Math.min(1, (x - bounds.left) / bounds.width))
    return { edge: 'bottom', edgeOffset: offset }
  }
  if (min === distLeft) {
    const offset = Math.max(0, Math.min(1, (y - bounds.top) / bounds.height))
    return { edge: 'left', edgeOffset: offset }
  }
  const offset = Math.max(0, Math.min(1, (y - bounds.top) / bounds.height))
  return { edge: 'right', edgeOffset: offset }
}

/**
 * Check if a point is within the edge hit zone of the symbol bounds.
 */
function isNearEdge(x: number, y: number, bounds: SymbolBounds): boolean {
  const inside =
    x >= bounds.left - EDGE_HIT_ZONE &&
    x <= bounds.left + bounds.width + EDGE_HIT_ZONE &&
    y >= bounds.top - EDGE_HIT_ZONE &&
    y <= bounds.top + bounds.height + EDGE_HIT_ZONE

  if (!inside) return false

  // Must be within EDGE_HIT_ZONE of an actual edge (not deep inside)
  const distTop = Math.abs(y - bounds.top)
  const distBottom = Math.abs(y - (bounds.top + bounds.height))
  const distLeft = Math.abs(x - bounds.left)
  const distRight = Math.abs(x - (bounds.left + bounds.width))

  return Math.min(distTop, distBottom, distLeft, distRight) <= EDGE_HIT_ZONE
}

/**
 * Convert edge+offset to pixel coordinates within the symbol bounds.
 */
export function indicatorToPixels(
  edge: string, edgeOffset: number, w: number, h: number
): { x: number; y: number } {
  switch (edge) {
    case 'top':    return { x: edgeOffset * w, y: 0 }
    case 'bottom': return { x: edgeOffset * w, y: h }
    case 'left':   return { x: 0, y: edgeOffset * h }
    case 'right':  return { x: w, y: edgeOffset * h }
    default:       return { x: 0, y: 0 }
  }
}

/**
 * Get the outward direction vector for a signal line from a given edge.
 */
export function getOutwardDirection(edge: string): { dx: number; dy: number } {
  switch (edge) {
    case 'top':    return { dx: 0, dy: -1 }
    case 'bottom': return { dx: 0, dy: 1 }
    case 'left':   return { dx: -1, dy: 0 }
    case 'right':  return { dx: 1, dy: 0 }
    default:       return { dx: 0, dy: -1 }
  }
}

export function useBlockEditor() {
  const workingIndicators = ref<PidIndicator[]>([])
  const selectedIndicatorId = ref<string | null>(null)
  const draggingIndicatorId = ref<string | null>(null)
  const addMode = ref<PidIndicatorType | 'port' | null>(null)
  const ghostIndicator = ref<GhostIndicator | null>(null)

  // Symbol bounds in the canvas coordinate space (set by the component)
  const symbolBounds = ref<SymbolBounds>({ left: 0, top: 0, width: 200, height: 200 })

  const selectedIndicator = computed(() =>
    workingIndicators.value.find(i => i.id === selectedIndicatorId.value) || null
  )

  /**
   * Initialize with a symbol's existing indicators (deep clone).
   */
  function init(symbol: PidSymbol) {
    workingIndicators.value = (symbol.indicators || []).map(i => ({ ...i }))
    selectedIndicatorId.value = null
    draggingIndicatorId.value = null
    addMode.value = null
    ghostIndicator.value = null
  }

  /**
   * Add a new indicator at the given edge position.
   */
  function addIndicator(
    edge: 'top' | 'right' | 'bottom' | 'left',
    edgeOffset: number,
    type: PidIndicatorType
  ): PidIndicator {
    const id = `ind-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const defaults = getIndicatorDefaults(type)
    const indicator: PidIndicator = {
      id,
      edge,
      edgeOffset,
      type,
      shape: (defaults.shape || 'circle') as PidIndicatorShape,
      showValue: defaults.showValue,
      decimals: defaults.decimals,
      signalLineLength: defaults.signalLineLength,
      signalLineDashed: defaults.signalLineDashed,
    }
    workingIndicators.value = [...workingIndicators.value, indicator]
    selectedIndicatorId.value = id
    addMode.value = null
    return indicator
  }

  /**
   * Update an indicator's properties.
   */
  function updateIndicator(id: string, updates: Partial<PidIndicator>) {
    workingIndicators.value = workingIndicators.value.map(ind =>
      ind.id === id ? { ...ind, ...updates } : ind
    )
  }

  /**
   * Delete an indicator.
   */
  function deleteIndicator(id: string) {
    workingIndicators.value = workingIndicators.value.filter(ind => ind.id !== id)
    if (selectedIndicatorId.value === id) {
      selectedIndicatorId.value = null
    }
  }

  /**
   * Select an indicator.
   */
  function selectIndicator(id: string) {
    selectedIndicatorId.value = id
    addMode.value = null
  }

  /**
   * Enter add mode for a specific indicator type.
   */
  function setAddMode(type: PidIndicatorType | 'port') {
    addMode.value = type
    selectedIndicatorId.value = null
  }

  /**
   * Handle canvas click — place indicator if in add mode.
   */
  function onCanvasClick(clientX: number, clientY: number, canvasRect: DOMRect) {
    const x = clientX - canvasRect.left
    const y = clientY - canvasRect.top
    const bounds = symbolBounds.value

    if (addMode.value && addMode.value !== 'port' && isNearEdge(x, y, bounds)) {
      const projected = projectToNearestEdge(x, y, bounds)
      addIndicator(projected.edge, projected.edgeOffset, addMode.value)
      return
    }

    // Deselect if clicking on empty space
    if (!addMode.value) {
      selectedIndicatorId.value = null
    }
  }

  /**
   * Handle canvas mouse move — update ghost indicator preview.
   */
  function onCanvasMouseMove(clientX: number, clientY: number, canvasRect: DOMRect) {
    if (draggingIndicatorId.value) {
      onDragMove(clientX, clientY, canvasRect)
      return
    }

    if (!addMode.value) {
      ghostIndicator.value = null
      return
    }

    const x = clientX - canvasRect.left
    const y = clientY - canvasRect.top
    const bounds = symbolBounds.value

    if (isNearEdge(x, y, bounds)) {
      const projected = projectToNearestEdge(x, y, bounds)
      const pos = indicatorToPixels(projected.edge, projected.edgeOffset, bounds.width, bounds.height)
      ghostIndicator.value = {
        edge: projected.edge,
        edgeOffset: projected.edgeOffset,
        x: bounds.left + pos.x,
        y: bounds.top + pos.y,
      }
    } else {
      ghostIndicator.value = null
    }
  }

  /**
   * Start dragging an indicator.
   */
  function startDrag(indicatorId: string) {
    draggingIndicatorId.value = indicatorId
    selectedIndicatorId.value = indicatorId
  }

  /**
   * Update indicator position during drag.
   */
  function onDragMove(clientX: number, clientY: number, canvasRect: DOMRect) {
    if (!draggingIndicatorId.value) return

    const x = clientX - canvasRect.left
    const y = clientY - canvasRect.top
    const projected = projectToNearestEdge(x, y, symbolBounds.value)

    updateIndicator(draggingIndicatorId.value, {
      edge: projected.edge,
      edgeOffset: projected.edgeOffset,
    })
  }

  /**
   * End drag.
   */
  function endDrag() {
    draggingIndicatorId.value = null
  }

  return {
    workingIndicators,
    selectedIndicatorId,
    selectedIndicator,
    draggingIndicatorId,
    addMode,
    ghostIndicator,
    symbolBounds,
    init,
    addIndicator,
    updateIndicator,
    deleteIndicator,
    selectIndicator,
    setAddMode,
    onCanvasClick,
    onCanvasMouseMove,
    startDrag,
    onDragMove,
    endDrag,
  }
}
