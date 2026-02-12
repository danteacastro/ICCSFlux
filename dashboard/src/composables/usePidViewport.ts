/**
 * usePidViewport - Zoom, pan, minimap, rulers, and guide line management
 *
 * Extracted from PidCanvas.vue. Manages all viewport transforms and navigation aids.
 */

import { ref, computed, type Ref, type ComputedRef } from 'vue'
import type { PidPoint, PidLayerData } from '../types'
import type { useDashboardStore } from '../stores/dashboard'

export const RULER_SIZE = 24

type Store = ReturnType<typeof useDashboardStore>

export function usePidViewport(
  store: Store,
  editMode: ComputedRef<boolean>,
  getPidLayer: () => PidLayerData,
  canvasRef: Ref<HTMLElement | null>,
) {
  // ─── Zoom / Pan ──────────────────────────────────────────────
  const zoom = computed(() => editMode.value ? store.pidZoom : 1)
  const panX = computed(() => editMode.value ? store.pidPanX : 0)
  const panY = computed(() => editMode.value ? store.pidPanY : 0)

  const isPanning = ref(false)
  const panStart = ref({ x: 0, y: 0, panX: 0, panY: 0 })
  const spaceHeld = ref(false)

  function getCanvasCoords(event: MouseEvent): PidPoint {
    if (!canvasRef.value) return { x: 0, y: 0 }
    const rect = canvasRef.value.getBoundingClientRect()
    return {
      x: (event.clientX - rect.left - panX.value) / zoom.value,
      y: (event.clientY - rect.top - panY.value) / zoom.value
    }
  }

  function onCanvasWheel(event: WheelEvent) {
    if (!editMode.value) return
    if (!event.ctrlKey) return
    event.preventDefault()

    const rect = canvasRef.value?.getBoundingClientRect()
    if (!rect) return

    const mouseX = event.clientX - rect.left
    const mouseY = event.clientY - rect.top

    const worldX = (mouseX - panX.value) / zoom.value
    const worldY = (mouseY - panY.value) / zoom.value

    const delta = event.deltaY > 0 ? -0.1 : 0.1
    const newZoom = Math.max(0.1, Math.min(5, zoom.value + delta * zoom.value))

    const newPanX = mouseX - worldX * newZoom
    const newPanY = mouseY - worldY * newZoom

    store.setPidZoom(newZoom)
    store.setPidPan(newPanX, newPanY)
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

  function onPanStart(event: MouseEvent) {
    if (!editMode.value) return

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

  // ─── Minimap ─────────────────────────────────────────────────
  const showMinimap = computed(() => store.pidShowMinimap)

  const minimapBounds = computed(() => {
    const layer = getPidLayer()
    let minX = 0, minY = 0, maxX = 1000, maxY = 800
    for (const sym of layer.symbols) {
      minX = Math.min(minX, sym.x)
      minY = Math.min(minY, sym.y)
      maxX = Math.max(maxX, sym.x + sym.width)
      maxY = Math.max(maxY, sym.y + sym.height)
    }
    for (const pipe of layer.pipes) {
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
    const worldX = b.x + (event.clientX - rect.left) / rect.width * b.w
    const worldY = b.y + (event.clientY - rect.top) / rect.height * b.h
    const canvasRect = canvasRef.value?.getBoundingClientRect()
    const vw = (canvasRect?.width ?? 800) / zoom.value
    const vh = (canvasRect?.height ?? 600) / zoom.value
    store.setPidPan(-(worldX - vw / 2) * zoom.value, -(worldY - vh / 2) * zoom.value)
  }

  // ─── Rulers & Guides ────────────────────────────────────────
  const showRulers = computed(() => store.pidShowRulers)
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
    if (!editMode.value) return
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
        store.removePidGuide(draggingGuide.value.id)
      }
      draggingGuide.value = null
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function onGuideMouseDown(event: MouseEvent, guide: { id: string; axis: 'h' | 'v'; position: number }) {
    if (!editMode.value) return
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

  return {
    // Zoom / Pan
    zoom,
    panX,
    panY,
    isPanning,
    panStart,
    spaceHeld,
    getCanvasCoords,
    onCanvasWheel,
    onPanStart,
    onPanMove,
    onPanEnd,
    // Minimap
    showMinimap,
    minimapBounds,
    minimapViewBox,
    minimapViewport,
    onMinimapMouseDown,
    // Rulers & Guides
    showRulers,
    rulerHCanvas,
    rulerVCanvas,
    draggingGuide,
    draggingGuidePos,
    drawRuler,
    onRulerMouseDown,
    onGuideMouseDown,
  }
}
