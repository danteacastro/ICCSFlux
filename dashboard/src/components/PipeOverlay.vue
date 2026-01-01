<script setup lang="ts">
/**
 * PipeOverlay Component
 *
 * Renders P&ID pipe connections as an SVG overlay on the dashboard grid.
 * Supports:
 * - Orthogonal (right-angle) pipe routing
 * - Draggable waypoints for manual routing
 * - Optional flow animation
 * - Pipe labels
 * - Connection to widget ports
 */

import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { PipeConnection, PipePoint } from '../types'

const props = defineProps<{
  pipes: PipeConnection[]
  gridColumns: number
  rowHeight: number
  margin?: number
  editMode?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:pipe', pipe: PipeConnection): void
  (e: 'delete:pipe', pipeId: string): void
  (e: 'select:pipe', pipeId: string | null): void
}>()

const store = useDashboardStore()

// Currently selected pipe for editing
const selectedPipeId = ref<string | null>(null)
// Currently dragging waypoint
const draggingPoint = ref<{ pipeId: string; pointIndex: number } | null>(null)
// Mouse position during drag
const dragPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })

// Grid cell width calculation
const cellWidth = computed(() => {
  // Approximate based on container - will be updated on mount
  const containerWidth = 1200 // Default, updated by parent
  return containerWidth / props.gridColumns
})

const margin = computed(() => props.margin ?? 8)

// Convert grid coordinates to pixel coordinates
function gridToPixel(point: PipePoint): { x: number; y: number } {
  return {
    x: point.x * cellWidth.value + margin.value + cellWidth.value / 2,
    y: point.y * props.rowHeight + margin.value + props.rowHeight / 2
  }
}

// Convert pixel coordinates to grid coordinates (snapped)
function pixelToGrid(px: number, py: number): PipePoint {
  return {
    x: Math.round((px - margin.value) / cellWidth.value),
    y: Math.round((py - margin.value) / props.rowHeight)
  }
}

// Get widget center position for anchored pipes
function getWidgetPortPosition(widgetId: string, port: 'top' | 'bottom' | 'left' | 'right'): PipePoint | null {
  const widget = store.widgets.find(w => w.id === widgetId)
  if (!widget) return null

  const cx = widget.x + widget.w / 2
  const cy = widget.y + widget.h / 2

  switch (port) {
    case 'top': return { x: cx, y: widget.y }
    case 'bottom': return { x: cx, y: widget.y + widget.h }
    case 'left': return { x: widget.x, y: cy }
    case 'right': return { x: widget.x + widget.w, y: cy }
  }
}

// Generate SVG path for orthogonal pipe
function generatePipePath(pipe: PipeConnection): string {
  const points = [...pipe.points]

  // If anchored to widgets, update first/last points
  if (pipe.startWidgetId && pipe.startPort) {
    const startPos = getWidgetPortPosition(pipe.startWidgetId, pipe.startPort)
    if (startPos && points.length > 0) {
      points[0] = startPos
    }
  }
  if (pipe.endWidgetId && pipe.endPort) {
    const endPos = getWidgetPortPosition(pipe.endWidgetId, pipe.endPort)
    if (endPos && points.length > 0) {
      points[points.length - 1] = endPos
    }
  }

  if (points.length < 2) return ''

  const pixelPoints = points.map(gridToPixel)
  const firstPoint = pixelPoints[0]
  if (!firstPoint) return ''

  // Build orthogonal path
  let path = `M ${firstPoint.x} ${firstPoint.y}`

  for (let i = 1; i < pixelPoints.length; i++) {
    const prev = pixelPoints[i - 1]
    const curr = pixelPoints[i]
    if (!prev || !curr) continue

    // For orthogonal routing: go horizontal first, then vertical
    // Unless points are already aligned
    if (prev.x !== curr.x && prev.y !== curr.y) {
      // Add intermediate point for orthogonal routing
      path += ` L ${curr.x} ${prev.y}`
    }
    path += ` L ${curr.x} ${curr.y}`
  }

  return path
}

// Get waypoint positions for editing
function getWaypointPositions(pipe: PipeConnection): { x: number; y: number; index: number }[] {
  return pipe.points.map((point, index) => {
    const pos = gridToPixel(point)
    return { ...pos, index }
  })
}

// Handle waypoint drag start
function onWaypointMouseDown(event: MouseEvent, pipeId: string, pointIndex: number) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  draggingPoint.value = { pipeId, pointIndex }
  selectedPipeId.value = pipeId
  emit('select:pipe', pipeId)

  // Add global mouse listeners
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function onMouseMove(event: MouseEvent) {
  if (!draggingPoint.value) return

  const overlay = document.querySelector('.pipe-overlay') as HTMLElement
  if (!overlay) return

  const rect = overlay.getBoundingClientRect()
  dragPos.value = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  }

  // Update the point position (snapped to grid)
  const pipe = props.pipes.find(p => p.id === draggingPoint.value?.pipeId)
  if (!pipe) return

  const gridPoint = pixelToGrid(dragPos.value.x, dragPos.value.y)
  const updatedPipe = {
    ...pipe,
    points: pipe.points.map((p, i) =>
      i === draggingPoint.value?.pointIndex ? gridPoint : p
    )
  }

  emit('update:pipe', updatedPipe)
}

function onMouseUp() {
  draggingPoint.value = null
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
}

// Add waypoint by clicking on pipe segment
function onPipeClick(_event: MouseEvent, pipeId: string) {
  if (!props.editMode) return

  selectedPipeId.value = pipeId
  emit('select:pipe', pipeId)
}

// Double-click to add waypoint
function onPipeDoubleClick(event: MouseEvent, pipeId: string) {
  if (!props.editMode) return
  event.preventDefault()
  event.stopPropagation()

  const overlay = document.querySelector('.pipe-overlay') as HTMLElement
  if (!overlay) return

  const rect = overlay.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const clickY = event.clientY - rect.top

  const gridPoint = pixelToGrid(clickX, clickY)

  const pipe = props.pipes.find(p => p.id === pipeId)
  if (!pipe || pipe.points.length < 2) return

  // Find which segment was clicked and insert point there
  const pixelPoints = pipe.points.map(gridToPixel)
  let insertIndex = 1

  for (let i = 0; i < pixelPoints.length - 1; i++) {
    const p1 = pixelPoints[i]
    const p2 = pixelPoints[i + 1]
    if (!p1 || !p2) continue

    // Check if click is near this segment
    const dist = distanceToSegment(clickX, clickY, p1.x, p1.y, p2.x, p2.y)
    if (dist < 20) {
      insertIndex = i + 1
      break
    }
  }

  const newPoints = [...pipe.points]
  newPoints.splice(insertIndex, 0, gridPoint)

  emit('update:pipe', { ...pipe, points: newPoints })
}

// Delete waypoint on right-click (keep at least 2 points)
function onWaypointContextMenu(event: MouseEvent, pipeId: string, pointIndex: number) {
  if (!props.editMode) return
  event.preventDefault()

  const pipe = props.pipes.find(p => p.id === pipeId)
  if (!pipe || pipe.points.length <= 2) return

  const newPoints = pipe.points.filter((_, i) => i !== pointIndex)
  emit('update:pipe', { ...pipe, points: newPoints })
}

// Distance from point to line segment
function distanceToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const A = px - x1
  const B = py - y1
  const C = x2 - x1
  const D = y2 - y1

  const dot = A * C + B * D
  const lenSq = C * C + D * D
  let param = -1

  if (lenSq !== 0) param = dot / lenSq

  let xx, yy

  if (param < 0) {
    xx = x1
    yy = y1
  } else if (param > 1) {
    xx = x2
    yy = y2
  } else {
    xx = x1 + param * C
    yy = y1 + param * D
  }

  const dx = px - xx
  const dy = py - yy

  return Math.sqrt(dx * dx + dy * dy)
}

// Delete selected pipe
function deleteSelectedPipe() {
  if (selectedPipeId.value) {
    emit('delete:pipe', selectedPipeId.value)
    selectedPipeId.value = null
  }
}

// Handle keyboard events
function onKeyDown(event: KeyboardEvent) {
  if (!props.editMode || !selectedPipeId.value) return

  if (event.key === 'Delete' || event.key === 'Backspace') {
    deleteSelectedPipe()
  } else if (event.key === 'Escape') {
    selectedPipeId.value = null
    emit('select:pipe', null)
  }
}

// Click outside to deselect
function onOverlayClick(event: MouseEvent) {
  if (event.target === event.currentTarget) {
    selectedPipeId.value = null
    emit('select:pipe', null)
  }
}
</script>

<template>
  <svg
    class="pipe-overlay"
    :class="{ 'edit-mode': editMode }"
    @click="onOverlayClick"
    @keydown="onKeyDown"
    tabindex="0"
  >
    <!-- Pipe paths -->
    <g v-for="pipe in pipes" :key="pipe.id" class="pipe-group">
      <!-- Main pipe line -->
      <path
        :d="generatePipePath(pipe)"
        :stroke="pipe.color || '#60a5fa'"
        :stroke-width="pipe.strokeWidth || 3"
        :stroke-dasharray="pipe.dashed ? '8,4' : undefined"
        stroke-linecap="round"
        stroke-linejoin="round"
        fill="none"
        class="pipe-path"
        :class="{
          selected: selectedPipeId === pipe.id,
          animated: pipe.animated
        }"
        @click.stop="onPipeClick($event, pipe.id)"
        @dblclick.stop="onPipeDoubleClick($event, pipe.id)"
      />

      <!-- Animated flow overlay -->
      <path
        v-if="pipe.animated"
        :d="generatePipePath(pipe)"
        stroke="rgba(255,255,255,0.5)"
        :stroke-width="(pipe.strokeWidth || 3) - 1"
        stroke-dasharray="4,12"
        stroke-linecap="round"
        fill="none"
        class="pipe-flow-animation"
      />

      <!-- Pipe label -->
      <text
        v-if="pipe.label && pipe.points[Math.floor(pipe.points.length / 2)]"
        :x="gridToPixel(pipe.points[Math.floor(pipe.points.length / 2)]!).x"
        :y="gridToPixel(pipe.points[Math.floor(pipe.points.length / 2)]!).y - 10"
        class="pipe-label"
        text-anchor="middle"
      >
        {{ pipe.label }}
      </text>

      <!-- Waypoints (only in edit mode) -->
      <g v-if="editMode" class="waypoints">
        <circle
          v-for="wp in getWaypointPositions(pipe)"
          :key="wp.index"
          :cx="wp.x"
          :cy="wp.y"
          r="6"
          class="waypoint"
          :class="{
            'first': wp.index === 0,
            'last': wp.index === pipe.points.length - 1,
            'dragging': draggingPoint?.pipeId === pipe.id && draggingPoint?.pointIndex === wp.index
          }"
          @mousedown="onWaypointMouseDown($event, pipe.id, wp.index)"
          @contextmenu="onWaypointContextMenu($event, pipe.id, wp.index)"
        />
      </g>
    </g>
  </svg>
</template>

<style scoped>
.pipe-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
  outline: none;
}

/* Only enable pointer-events on the actual pipe paths and waypoints,
   not the entire overlay, so widgets can still be dragged */
.pipe-overlay.edit-mode .pipe-path,
.pipe-overlay.edit-mode .waypoint {
  pointer-events: auto;
}

.pipe-path {
  cursor: default;
  transition: stroke 0.2s, stroke-width 0.2s;
}

.edit-mode .pipe-path {
  cursor: pointer;
}

.pipe-path:hover {
  stroke-width: 5;
  filter: drop-shadow(0 0 4px currentColor);
}

.pipe-path.selected {
  stroke-width: 5;
  filter: drop-shadow(0 0 6px currentColor);
}

.pipe-flow-animation {
  animation: flow 1s linear infinite;
  pointer-events: none;
}

@keyframes flow {
  0% { stroke-dashoffset: 16; }
  100% { stroke-dashoffset: 0; }
}

.pipe-label {
  font-size: 10px;
  font-weight: 600;
  fill: #fff;
  paint-order: stroke;
  stroke: #1a1a2e;
  stroke-width: 3px;
  pointer-events: none;
}

.waypoint {
  fill: #3b82f6;
  stroke: #fff;
  stroke-width: 2;
  cursor: grab;
  transition: r 0.15s, fill 0.15s;
}

.waypoint:hover {
  r: 8;
  fill: #60a5fa;
}

.waypoint.first,
.waypoint.last {
  fill: #22c55e;
}

.waypoint.dragging {
  r: 10;
  fill: #fbbf24;
  cursor: grabbing;
}

/* Hide waypoints when not in edit mode (already handled by v-if, but just in case) */
.pipe-overlay:not(.edit-mode) .waypoints {
  display: none;
}
</style>
