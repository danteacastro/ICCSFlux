<script setup lang="ts">
/**
 * PidBlockEditor - Full-screen overlay for editing indicator stubs on a P&ID symbol.
 *
 * Double-click a symbol on the canvas → this overlay opens.
 * Place indicators (channel values, interlocks, alarms, control outputs) around
 * the symbol's perimeter by clicking edges. Drag to reposition along edges.
 * Done → saves indicators back to the symbol. Cancel → discards changes.
 */

import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import type { PidSymbol, PidIndicator, PidIndicatorType, Interlock } from '../types'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useBlockEditor, indicatorToPixels, getOutwardDirection, projectToNearestEdge } from '../composables/useBlockEditor'
import { getSymbolSvg, getSignalLineDashArray } from '../composables/usePidRendering'
import { SYMBOL_PORTS, type SymbolPort } from '../assets/symbols'
import type { ScadaSymbolType } from '../assets/symbols'
import PidIndicatorConfig from './PidIndicatorConfig.vue'

const props = defineProps<{
  symbol: PidSymbol
}>()

const emit = defineEmits<{
  (e: 'save', data: {
    indicators: PidIndicator[]
    customPorts?: PidSymbol['customPorts']
    hiddenPorts?: PidSymbol['hiddenPorts']
  }): void
  (e: 'cancel'): void
}>()

const store = useDashboardStore()
const safety = useSafety()

const {
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
  endDrag,
} = useBlockEditor()

const canvasRef = ref<HTMLElement | null>(null)

// Symbol display sizing
const CANVAS_SIZE = 500
const SYMBOL_PADDING = 60

const symbolDisplaySize = computed(() => {
  const aspect = props.symbol.width / props.symbol.height
  let w: number, h: number
  const maxSize = CANVAS_SIZE - SYMBOL_PADDING * 2
  if (aspect >= 1) {
    w = maxSize
    h = maxSize / aspect
  } else {
    h = maxSize
    w = maxSize * aspect
  }
  return { width: w, height: h }
})

const symbolContainerStyle = computed(() => {
  const { width, height } = symbolDisplaySize.value
  const left = (CANVAS_SIZE - width) / 2
  const top = (CANVAS_SIZE - height) / 2
  return {
    position: 'absolute' as const,
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
  }
})

const symbolSvg = computed(() => getSymbolSvg(props.symbol.type, store.pidCustomSymbols))

const channelNames = computed(() => Object.keys(store.channels).sort())
const availableInterlocks = computed(() => safety.interlocks.value as Interlock[])

// --- Port management state ---
type CustomPort = { id: string; x: number; y: number; direction: 'left' | 'right' | 'top' | 'bottom'; label?: string }

const workingCustomPorts = ref<CustomPort[]>([])
const workingHiddenPorts = ref<string[]>([])
const selectedPortId = ref<string | null>(null)
const draggingPortId = ref<string | null>(null)

const builtInPorts = computed<SymbolPort[]>(() => {
  return SYMBOL_PORTS[props.symbol.type as ScadaSymbolType] || []
})

// Convert a port (built-in or custom) to pixel position within symbol container
function getPortPixelStyle(port: { x: number; y: number }): Record<string, string> {
  const { width, height } = symbolDisplaySize.value
  return {
    position: 'absolute',
    left: `${port.x * width - 6}px`,
    top: `${port.y * height - 6}px`,
  }
}

// Stub lines for custom ports: visible line from bounding box edge inward toward symbol body
const customPortStubLines = computed(() => {
  const { width, height } = symbolDisplaySize.value
  const STUB_LEN = Math.min(width, height) * 0.12 // ~12% of smaller dimension
  return workingCustomPorts.value.map(port => {
    const px = port.x * width
    const py = port.y * height
    let dx = 0, dy = 0
    switch (port.direction) {
      case 'left':   dx = 1; break
      case 'right':  dx = -1; break
      case 'top':    dy = 1; break
      case 'bottom': dy = -1; break
    }
    return { id: port.id, x1: px, y1: py, x2: px + dx * STUB_LEN, y2: py + dy * STUB_LEN }
  })
})

function edgeFromDirection(dir: string): 'top' | 'right' | 'bottom' | 'left' {
  if (dir === 'top' || dir === 'right' || dir === 'bottom' || dir === 'left') return dir
  return 'top'
}

function toggleBuiltInPort(portId: string) {
  const idx = workingHiddenPorts.value.indexOf(portId)
  if (idx >= 0) {
    workingHiddenPorts.value.splice(idx, 1)
  } else {
    workingHiddenPorts.value.push(portId)
  }
}

function addCustomPortAtEdge(edge: 'top' | 'right' | 'bottom' | 'left', edgeOffset: number) {
  let x = 0, y = 0
  switch (edge) {
    case 'top':    x = edgeOffset; y = 0; break
    case 'bottom': x = edgeOffset; y = 1; break
    case 'left':   x = 0; y = edgeOffset; break
    case 'right':  x = 1; y = edgeOffset; break
  }
  const port: CustomPort = {
    id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    x, y,
    direction: edge,
    label: `Port ${workingCustomPorts.value.length + 1}`,
  }
  workingCustomPorts.value = [...workingCustomPorts.value, port]
  selectedPortId.value = port.id
  selectedIndicatorId.value = null
  addMode.value = null
}

function removeCustomPort(portId: string) {
  workingCustomPorts.value = workingCustomPorts.value.filter(p => p.id !== portId)
  if (selectedPortId.value === portId) selectedPortId.value = null
}

function selectPort(portId: string) {
  selectedPortId.value = portId
  selectedIndicatorId.value = null
  addMode.value = null
}

function startPortDrag(portId: string) {
  draggingPortId.value = portId
  selectedPortId.value = portId
  selectedIndicatorId.value = null
}

function onPortDragMove(clientX: number, clientY: number, canvasRect: DOMRect) {
  if (!draggingPortId.value) return
  const x = clientX - canvasRect.left
  const y = clientY - canvasRect.top
  const bounds = symbolBounds.value
  const projected = projectToNearestEdge(x, y, bounds)
  // Convert edge+offset to normalized x,y
  let px = 0, py = 0
  switch (projected.edge) {
    case 'top':    px = projected.edgeOffset; py = 0; break
    case 'bottom': px = projected.edgeOffset; py = 1; break
    case 'left':   px = 0; py = projected.edgeOffset; break
    case 'right':  px = 1; py = projected.edgeOffset; break
  }
  workingCustomPorts.value = workingCustomPorts.value.map(p =>
    p.id === draggingPortId.value
      ? { ...p, x: px, y: py, direction: projected.edge }
      : p
  )
}

// Convert indicator to pixel style within the symbol container
function getIndicatorPixelStyle(ind: PidIndicator): Record<string, string> {
  const { width, height } = symbolDisplaySize.value
  const pos = indicatorToPixels(ind.edge, ind.edgeOffset, width, height)
  return {
    position: 'absolute',
    left: `${pos.x - 10}px`,
    top: `${pos.y - 10}px`,
  }
}

// Signal line endpoint for an indicator
function getSignalLinePoints(ind: PidIndicator): { x1: number; y1: number; x2: number; y2: number } {
  const dir = getOutwardDirection(ind.edge)
  const len = ind.signalLineLength ?? 30
  return { x1: 10, y1: 10, x2: 10 + dir.dx * len, y2: 10 + dir.dy * len }
}

// Initialize
onMounted(() => {
  init(props.symbol)
  workingCustomPorts.value = props.symbol.customPorts ? props.symbol.customPorts.map(p => ({ ...p })) : []
  workingHiddenPorts.value = props.symbol.hiddenPorts ? [...props.symbol.hiddenPorts] : []
  selectedPortId.value = null
  draggingPortId.value = null
  nextTick(() => updateSymbolBounds())
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('mouseup', onMouseUp)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('mouseup', onMouseUp)
})

function updateSymbolBounds() {
  const { width, height } = symbolDisplaySize.value
  const left = (CANVAS_SIZE - width) / 2
  const top = (CANVAS_SIZE - height) / 2
  symbolBounds.value = { left, top, width, height }
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (addMode.value) {
      addMode.value = null
    } else {
      emit('cancel')
    }
  }
  if (e.key === 'Delete') {
    if (selectedIndicatorId.value) deleteIndicator(selectedIndicatorId.value)
    else if (selectedPortId.value) removeCustomPort(selectedPortId.value)
  }
}

function onMouseUp() {
  endDrag()
  draggingPortId.value = null
}

function handleCanvasClick(e: MouseEvent) {
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  // Handle port add mode
  if (addMode.value === 'port') {
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const bounds = symbolBounds.value
    const projected = projectToNearestEdge(x, y, bounds)
    addCustomPortAtEdge(projected.edge, projected.edgeOffset)
    return
  }
  onCanvasClick(e.clientX, e.clientY, rect)
  // Deselect port if clicking empty space (not in add mode)
  if (!addMode.value) selectedPortId.value = null
}

function handleCanvasMouseMove(e: MouseEvent) {
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  if (draggingPortId.value) {
    onPortDragMove(e.clientX, e.clientY, rect)
    return
  }
  onCanvasMouseMove(e.clientX, e.clientY, rect)
}

function handleIndicatorMouseDown(e: MouseEvent, ind: PidIndicator) {
  e.stopPropagation()
  e.preventDefault()
  selectIndicator(ind.id)
  selectedPortId.value = null
  startDrag(ind.id)
}

function saveAndClose() {
  emit('save', {
    indicators: [...workingIndicators.value],
    customPorts: workingCustomPorts.value.length > 0 ? [...workingCustomPorts.value] : undefined,
    hiddenPorts: workingHiddenPorts.value.length > 0 ? [...workingHiddenPorts.value] : undefined,
  })
}

function onIndicatorUpdate(updates: Partial<PidIndicator>) {
  if (selectedIndicatorId.value) {
    updateIndicator(selectedIndicatorId.value, updates)
  }
}

function onIndicatorDelete() {
  if (selectedIndicatorId.value) {
    deleteIndicator(selectedIndicatorId.value)
  }
}

// Indicator shape SVG paths (circle/circleBar/dashedCircle/circleInSquare use <circle>/<rect> elements)
const shapePaths: Record<string, string> = {
  circle: '',
  circleBar: '',
  dashedCircle: '',
  circleInSquare: '',
  diamond: 'M10,1 L19,10 L10,19 L1,10 Z',
  flag: 'M1,1 L19,1 L19,12 L10,10 L1,12 Z',
  square: 'M2,2 L18,2 L18,18 L2,18 Z',
  hexagon: 'M5,1 L15,1 L19,10 L15,19 L5,19 L1,10 Z',
}

const addButtons: { type: PidIndicatorType | 'port'; label: string; icon: string }[] = [
  { type: 'channel_value', label: 'Channel Value', icon: 'O' },
  { type: 'interlock', label: 'Interlock', icon: '\u25C7' },
  { type: 'alarm_annotation', label: 'Alarm', icon: '\u2691' },
  { type: 'control_output', label: 'Control Output', icon: '\u25A1' },
  { type: 'port', label: 'Connection Port', icon: '\u25CF' },
]
</script>

<template>
  <Teleport to="body">
    <div class="block-editor-overlay" @click.self="emit('cancel')">
      <div class="block-editor-container">

        <!-- Header -->
        <div class="block-editor-header">
          <div class="header-left">
            <h3>Block Editor</h3>
            <span class="header-symbol-name">{{ symbol.label || symbol.type }}</span>
          </div>
          <div class="header-actions">
            <button class="btn btn-secondary" @click="emit('cancel')">Cancel</button>
            <button class="btn btn-primary" @click="saveAndClose">Done</button>
          </div>
        </div>

        <!-- Body: two columns -->
        <div class="block-editor-body">

          <!-- LEFT: Symbol canvas -->
          <div
            ref="canvasRef"
            class="symbol-canvas"
            :class="{ 'add-mode': !!addMode }"
            :style="{ width: `${CANVAS_SIZE}px`, height: `${CANVAS_SIZE}px` }"
            @click="handleCanvasClick"
            @mousemove="handleCanvasMouseMove"
          >
            <!-- Grid background -->
            <svg class="canvas-grid" :width="CANVAS_SIZE" :height="CANVAS_SIZE">
              <defs>
                <pattern id="grid-small" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#1e293b" stroke-width="0.5" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid-small)" />
            </svg>

            <!-- Symbol container -->
            <div class="symbol-container" :style="symbolContainerStyle">
              <!-- The symbol SVG -->
              <div
                class="symbol-svg-display"
                v-html="symbolSvg"
              />

              <!-- Edge highlight zones -->
              <div class="edge-zone top" />
              <div class="edge-zone right" />
              <div class="edge-zone bottom" />
              <div class="edge-zone left" />

              <!-- Existing indicators -->
              <div
                v-for="ind in workingIndicators"
                :key="ind.id"
                class="indicator-stub"
                :class="{
                  selected: selectedIndicatorId === ind.id,
                  dragging: draggingIndicatorId === ind.id,
                }"
                :style="getIndicatorPixelStyle(ind)"
                @mousedown="handleIndicatorMouseDown($event, ind)"
                @click.stop="selectIndicator(ind.id)"
              >
                <!-- Signal line -->
                <svg class="signal-line-svg" width="60" height="60"
                     style="position: absolute; left: -20px; top: -20px; overflow: visible; pointer-events: none;">
                  <line
                    :x1="30" :y1="30"
                    :x2="30 + getSignalLinePoints(ind).x2 - 10"
                    :y2="30 + getSignalLinePoints(ind).y2 - 10"
                    stroke="#64748b"
                    stroke-width="1.5"
                    :stroke-dasharray="getSignalLineDashArray(ind)"
                  />
                </svg>

                <!-- Shape -->
                <svg class="indicator-shape-svg" width="20" height="20" viewBox="0 0 20 20">
                  <circle v-if="ind.shape === 'circle'"
                    cx="10" cy="10" r="8" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                  <template v-else-if="ind.shape === 'circleBar'">
                    <circle cx="10" cy="10" r="8" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                    <line x1="2" y1="10" x2="18" y2="10" stroke="#94a3b8" stroke-width="1" />
                  </template>
                  <circle v-else-if="ind.shape === 'dashedCircle'"
                    cx="10" cy="10" r="8" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="3,2" />
                  <template v-else-if="ind.shape === 'circleInSquare'">
                    <rect x="1" y="1" width="18" height="18" fill="none" stroke="#94a3b8" stroke-width="1.2" />
                    <circle cx="10" cy="10" r="7" fill="none" stroke="#94a3b8" stroke-width="1.2" />
                  </template>
                  <polygon v-else-if="ind.shape === 'diamond'"
                    points="10,2 18,10 10,18 2,10" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                  <polygon v-else-if="ind.shape === 'flag'"
                    points="2,2 18,2 18,12 10,10 2,12" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                  <rect v-else-if="ind.shape === 'square'"
                    x="2" y="2" width="16" height="16" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                  <polygon v-else-if="ind.shape === 'hexagon'"
                    points="5,2 15,2 19,10 15,18 5,18 1,10" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                  <circle v-else cx="10" cy="10" r="8" fill="none" stroke="#94a3b8" stroke-width="1.5" />
                </svg>

                <!-- Label -->
                <span v-if="ind.isaLetters || ind.label" class="indicator-label-text">
                  {{ ind.isaLetters || ind.label }}
                </span>
              </div>

              <!-- Built-in ports (only visible ones) -->
              <div
                v-for="port in builtInPorts.filter(p => !workingHiddenPorts.includes(p.id))"
                :key="`bp-${port.id}`"
                class="port-stub builtin-port"
                :style="getPortPixelStyle(port)"
                :title="`${port.label || port.id} (${port.direction})`"
              >
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <circle cx="6" cy="6" r="5" fill="none" stroke="#22c55e" stroke-width="1.5" />
                </svg>
              </div>

              <!-- Custom port stub lines (edge → inward) -->
              <svg
                v-if="customPortStubLines.length"
                class="custom-stub-overlay"
                :width="symbolDisplaySize.width"
                :height="symbolDisplaySize.height"
              >
                <line
                  v-for="stub in customPortStubLines"
                  :key="`stub-${stub.id}`"
                  :x1="stub.x1" :y1="stub.y1"
                  :x2="stub.x2" :y2="stub.y2"
                  stroke="#22c55e"
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>

              <!-- Custom ports (draggable) -->
              <div
                v-for="port in workingCustomPorts"
                :key="`cp-${port.id}`"
                class="port-stub custom-port"
                :class="{ selected: selectedPortId === port.id, dragging: draggingPortId === port.id }"
                :style="getPortPixelStyle(port)"
                @mousedown.stop.prevent="startPortDrag(port.id)"
                @click.stop="selectPort(port.id)"
              >
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <circle cx="6" cy="6" r="5" fill="rgba(34, 197, 94, 0.2)" stroke="#22c55e" stroke-width="1.5" />
                </svg>
                <span v-if="port.label" class="port-label-text">{{ port.label }}</span>
              </div>

              <!-- Ghost preview (indicator or port in add mode) -->
              <div
                v-if="ghostIndicator && addMode && addMode !== 'port'"
                class="indicator-ghost"
                :style="{
                  position: 'absolute',
                  left: `${ghostIndicator.x - symbolBounds.left - 10}px`,
                  top: `${ghostIndicator.y - symbolBounds.top - 10}px`,
                  pointerEvents: 'none',
                }"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" opacity="0.5">
                  <circle v-if="addMode === 'channel_value'" cx="10" cy="10" r="8"
                    fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3,2" />
                  <polygon v-else-if="addMode === 'interlock'"
                    points="10,2 18,10 10,18 2,10"
                    fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3,2" />
                  <polygon v-else-if="addMode === 'alarm_annotation'"
                    points="2,2 18,2 18,12 10,10 2,12"
                    fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3,2" />
                  <rect v-else
                    x="2" y="2" width="16" height="16"
                    fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3,2" />
                </svg>
              </div>
              <!-- Ghost port (in port add mode) -->
              <div
                v-if="ghostIndicator && addMode === 'port'"
                class="indicator-ghost"
                :style="{
                  position: 'absolute',
                  left: `${ghostIndicator.x - symbolBounds.left - 6}px`,
                  top: `${ghostIndicator.y - symbolBounds.top - 6}px`,
                  pointerEvents: 'none',
                }"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" opacity="0.5">
                  <circle cx="6" cy="6" r="5" fill="rgba(34, 197, 94, 0.15)" stroke="#22c55e" stroke-width="1.5" stroke-dasharray="2,2" />
                </svg>
              </div>
            </div>

            <!-- Add mode instructions -->
            <div v-if="addMode" class="add-mode-hint">
              Click on the symbol edge to place
            </div>
          </div>

          <!-- RIGHT: Properties panel -->
          <div class="indicator-panel">
            <!-- Add buttons -->
            <div class="add-section">
              <h4 class="panel-heading">Add Indicator</h4>
              <div class="add-buttons">
                <button
                  v-for="btn in addButtons"
                  :key="btn.type"
                  class="add-btn"
                  :class="{ active: addMode === btn.type }"
                  @click="setAddMode(btn.type)"
                >
                  <span class="add-btn-icon">{{ btn.icon }}</span>
                  {{ btn.label }}
                </button>
              </div>
            </div>

            <!-- Indicator list -->
            <div v-if="workingIndicators.length > 0" class="list-section">
              <h4 class="panel-heading">Indicators ({{ workingIndicators.length }})</h4>
              <div class="indicator-list">
                <div
                  v-for="ind in workingIndicators"
                  :key="ind.id"
                  class="indicator-list-item"
                  :class="{ selected: selectedIndicatorId === ind.id }"
                  @click="selectIndicator(ind.id)"
                >
                  <span class="list-item-type">{{ ind.type.replace('_', ' ') }}</span>
                  <span v-if="ind.isaLetters || ind.label" class="list-item-label">{{ ind.isaLetters || ind.label }}</span>
                  <span class="list-item-edge">{{ ind.edge }}</span>
                </div>
              </div>
            </div>

            <div v-if="workingIndicators.length === 0 && builtInPorts.length === 0 && workingCustomPorts.length === 0" class="empty-state">
              <p>No indicators or ports yet.</p>
              <p class="hint">Click an add button above, then click on the symbol edge to place it.</p>
            </div>

            <!-- Ports section -->
            <div v-if="builtInPorts.length > 0 || workingCustomPorts.length > 0" class="list-section">
              <h4 class="panel-heading">Ports ({{ builtInPorts.filter(p => !workingHiddenPorts.includes(p.id)).length + workingCustomPorts.length }})</h4>

              <!-- Built-in ports (visible ones) -->
              <div v-if="builtInPorts.some(p => !workingHiddenPorts.includes(p.id))" class="port-list">
                <div class="port-subsection-label">Built-in</div>
                <div
                  v-for="port in builtInPorts.filter(p => !workingHiddenPorts.includes(p.id))"
                  :key="`bp-list-${port.id}`"
                  class="port-list-item"
                >
                  <span class="port-name">{{ port.label || port.id }}</span>
                  <span class="port-dir">({{ port.direction }})</span>
                  <button class="port-remove-btn" @click.stop="toggleBuiltInPort(port.id)" title="Remove port">&times;</button>
                </div>
              </div>
              <!-- Removed built-in ports (can restore) -->
              <div v-if="workingHiddenPorts.length > 0" class="port-list">
                <div class="port-subsection-label">Removed</div>
                <div
                  v-for="port in builtInPorts.filter(p => workingHiddenPorts.includes(p.id))"
                  :key="`bp-removed-${port.id}`"
                  class="port-list-item removed"
                >
                  <span class="port-name">{{ port.label || port.id }}</span>
                  <button class="port-restore-btn" @click.stop="toggleBuiltInPort(port.id)" title="Restore port">+</button>
                </div>
              </div>

              <!-- Custom ports -->
              <div v-if="workingCustomPorts.length > 0" class="port-list">
                <div class="port-subsection-label">Custom</div>
                <div
                  v-for="port in workingCustomPorts"
                  :key="`cp-list-${port.id}`"
                  class="port-list-item custom"
                  :class="{ selected: selectedPortId === port.id }"
                  @click="selectPort(port.id)"
                >
                  <span class="port-name">{{ port.label || 'Port' }}</span>
                  <span class="port-dir">({{ port.direction }} @ {{ Math.round((port.direction === 'left' || port.direction === 'right' ? port.y : port.x) * 100) }}%)</span>
                  <button class="port-remove-btn" @click.stop="removeCustomPort(port.id)" title="Remove port">&times;</button>
                </div>
              </div>
            </div>

            <!-- Selected indicator config -->
            <div v-if="selectedIndicator" class="config-section">
              <PidIndicatorConfig
                :indicator="selectedIndicator"
                :channel-names="channelNames"
                :interlocks="availableInterlocks"
                @update="onIndicatorUpdate"
                @delete="onIndicatorDelete"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.block-editor-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
  backdrop-filter: blur(4px);
}

.block-editor-container {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  max-width: 900px;
  max-height: 90vh;
  width: 90vw;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

/* Header */
.block-editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #334155;
  background: #1e293b;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #e2e8f0;
}

.header-symbol-name {
  font-size: 0.8rem;
  color: #94a3b8;
  background: #334155;
  padding: 2px 8px;
  border-radius: 4px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-secondary {
  background: #334155;
  color: #e2e8f0;
}

.btn-secondary:hover {
  background: #475569;
}

.btn-primary {
  background: #3b82f6;
  color: white;
}

.btn-primary:hover {
  background: #2563eb;
}

/* Body */
.block-editor-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Symbol canvas */
.symbol-canvas {
  position: relative;
  background: #0f172a;
  flex-shrink: 0;
  overflow: hidden;
  cursor: default;
}

.symbol-canvas.add-mode {
  cursor: crosshair;
}

.canvas-grid {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

.symbol-container {
  /* positioned absolutely via style binding */
  border: 1px solid #334155;
  border-radius: 4px;
  background: #1e293b40;
}

.symbol-svg-display {
  width: 100%;
  height: 100%;
  color: #94a3b8;
}

.symbol-svg-display :deep(svg) {
  width: 100%;
  height: 100%;
}

/* Edge highlight zones */
.edge-zone {
  position: absolute;
  background: transparent;
  transition: background 0.15s;
}

.add-mode .edge-zone:hover {
  background: rgba(59, 130, 246, 0.1);
}

.edge-zone.top {
  top: -8px;
  left: 0;
  right: 0;
  height: 16px;
}

.edge-zone.bottom {
  bottom: -8px;
  left: 0;
  right: 0;
  height: 16px;
}

.edge-zone.left {
  left: -8px;
  top: 0;
  bottom: 0;
  width: 16px;
}

.edge-zone.right {
  right: -8px;
  top: 0;
  bottom: 0;
  width: 16px;
}

/* Indicator stubs */
.indicator-stub {
  position: absolute;
  cursor: grab;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 2px;
}

.indicator-stub.dragging {
  cursor: grabbing;
  opacity: 0.8;
}

.indicator-stub.selected .indicator-shape-svg {
  filter: drop-shadow(0 0 3px #3b82f6);
}

.indicator-stub.selected .indicator-shape-svg circle,
.indicator-stub.selected .indicator-shape-svg polygon,
.indicator-stub.selected .indicator-shape-svg rect {
  stroke: #3b82f6;
}

.indicator-shape-svg {
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}

.indicator-label-text {
  font-size: 9px;
  font-weight: 600;
  color: #94a3b8;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  white-space: nowrap;
  position: relative;
  z-index: 2;
}

/* Ghost indicator */
.indicator-ghost {
  pointer-events: none;
  z-index: 10;
}

/* Add mode hint */
.add-mode-hint {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: #1e293b;
  border: 1px solid #3b82f6;
  color: #93c5fd;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 0.75rem;
  pointer-events: none;
}

/* Right panel */
.indicator-panel {
  flex: 1;
  min-width: 260px;
  max-width: 320px;
  border-left: 1px solid #334155;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-heading {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 6px;
}

/* Add buttons */
.add-buttons {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.add-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #1e293b;
  border: 1px solid #334155;
  color: #cbd5e1;
  border-radius: 6px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
}

.add-btn:hover {
  background: #334155;
  border-color: #475569;
}

.add-btn.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #93c5fd;
}

.add-btn-icon {
  font-size: 0.9rem;
  width: 18px;
  text-align: center;
}

/* Indicator list */
.indicator-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.indicator-list-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: #1e293b;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.7rem;
  color: #cbd5e1;
  transition: all 0.1s;
}

.indicator-list-item:hover {
  background: #334155;
}

.indicator-list-item.selected {
  border-color: #3b82f6;
  background: #1e3a5f;
}

.list-item-type {
  color: #64748b;
  font-size: 0.65rem;
  text-transform: capitalize;
}

.list-item-label {
  font-weight: 600;
  color: #e2e8f0;
}

.list-item-edge {
  margin-left: auto;
  font-size: 0.6rem;
  color: #475569;
  text-transform: uppercase;
}

/* Config section */
.config-section {
  border-top: 1px solid #334155;
  padding-top: 12px;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 20px;
  color: #64748b;
  font-size: 0.8rem;
}

.empty-state .hint {
  font-size: 0.7rem;
  color: #475569;
  margin-top: 4px;
}

/* Port stubs on canvas */
.port-stub {
  position: absolute;
  z-index: 4;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 3px;
}

.custom-stub-overlay {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  overflow: visible;
}

.port-stub.builtin-port {
  cursor: default;
}

.port-stub.custom-port {
  cursor: grab;
}

.port-stub.custom-port.dragging {
  cursor: grabbing;
  opacity: 0.7;
}

.port-stub.custom-port.selected svg circle {
  stroke: #3b82f6;
  fill: rgba(59, 130, 246, 0.2);
}

.port-label-text {
  font-size: 8px;
  color: #22c55e;
  white-space: nowrap;
}

/* Port list in right panel */
.port-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}

.port-subsection-label {
  font-size: 0.6rem;
  text-transform: uppercase;
  color: #475569;
  letter-spacing: 0.05em;
  margin-top: 4px;
}

.port-list-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #1e293b;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 0.7rem;
  color: #cbd5e1;
}

.port-list-item.selected {
  border-color: #22c55e;
  background: #1e3b2a;
}

.port-list-item.removed {
  opacity: 0.5;
}

.port-list-item .port-name {
  font-weight: 500;
  color: #e2e8f0;
}

.port-list-item .port-dir {
  color: #64748b;
  font-size: 0.6rem;
}

.port-remove-btn {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.port-remove-btn:hover {
  opacity: 1;
}

.port-restore-btn {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #22c55e;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.port-restore-btn:hover {
  opacity: 1;
}
</style>
