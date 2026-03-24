/**
 * usePidRendering - Pure rendering helpers extracted from PidCanvas.vue
 *
 * Symbol rendering: SVG lookup, tank fill, alarm state, color, style, value display
 * Pipe rendering: path generation, dash arrays, markers, flow state, line jumps
 */

import { computed } from 'vue'
import { SCADA_SYMBOLS, SYMBOL_INFO, isScadaSymbol, type ScadaSymbolType } from '../assets/symbols'
import type { PidSymbol, PidPipe, PidPoint, PidLayerData, PidArrowType, PidIndicator } from '../types'
import { generateIsaFunctionBlockSvg } from '../utils/isaFunctionBlock'
import type { useDashboardStore } from '../stores/dashboard'
import type { useSafety } from '../composables/useSafety'

// ─── Pure utility functions (no reactive deps) ─────────────────────

export function isTankSymbol(symbol: PidSymbol | null): boolean {
  if (!symbol) return false
  if (isScadaSymbol(symbol.type)) {
    return SYMBOL_INFO[symbol.type].isTank === true
  }
  return false
}

export function isRotatingSymbol(type: string): boolean {
  if (isScadaSymbol(type)) {
    return SYMBOL_INFO[type].isRotating === true
  }
  return false
}

export function isValveSymbol(symbol: PidSymbol): boolean {
  if (isScadaSymbol(symbol.type)) {
    return SYMBOL_INFO[symbol.type].isValve === true
  }
  return false
}

export function getSymbolSvg(type: string, customSymbols?: Record<string, { svg: string }>, symbol?: PidSymbol): string {
  // Parametric ISA function block: generate SVG dynamically from symbol properties
  if (type === 'isaFunctionBlock' && symbol) {
    return generateIsaFunctionBlockSvg(
      symbol.isaLetters || 'TI',
      symbol.isaLocation || 'field',
      symbol.loopNumber
    )
  }
  return customSymbols?.[type]?.svg
    ?? SCADA_SYMBOLS[type as ScadaSymbolType]
    ?? SCADA_SYMBOLS.solenoidValve
}

export function resolveArrowType(val: PidArrowType | boolean | undefined): PidArrowType {
  if (val === true) return 'arrow'
  if (!val) return 'none'
  return val as PidArrowType
}

export function getFlowAnimationDuration(speed: number): string {
  const duration = 1 / Math.max(0.1, speed)
  return `${duration}s`
}

export function segmentIntersection(
  p1: PidPoint, p2: PidPoint, p3: PidPoint, p4: PidPoint
): PidPoint | null {
  const denom = (p4.y - p3.y) * (p2.x - p1.x) - (p4.x - p3.x) * (p2.y - p1.y)
  if (Math.abs(denom) < 1e-10) return null
  const ua = ((p4.x - p3.x) * (p1.y - p3.y) - (p4.y - p3.y) * (p1.x - p3.x)) / denom
  const ub = ((p2.x - p1.x) * (p1.y - p3.y) - (p2.y - p1.y) * (p1.x - p3.x)) / denom
  if (ua < 0.01 || ua > 0.99 || ub < 0.01 || ub > 0.99) return null
  return { x: p1.x + ua * (p2.x - p1.x), y: p1.y + ua * (p2.y - p1.y) }
}

export function generateRoundedPolylinePath(points: PidPoint[], radius: number): string {
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

export function generatePipePath(pipe: PidPipe): string {
  if (pipe.points.length < 2) return ''

  const first = pipe.points[0]!
  let path = `M ${first.x} ${first.y}`

  if (pipe.pathType === 'bezier' && pipe.points.length >= 3) {
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

// ─── Heat Trace rendering (ISA zigzag marking alongside pipe) ────────

const HEAT_TRACE_COLORS: Record<string, string> = {
  electric: '#f97316',    // orange
  steam: '#ef4444',       // red
  'hot-water': '#f59e0b', // amber
}

/**
 * Generate an SVG zigzag path offset from the pipe centerline.
 * Used to show heat tracing per ISA standards.
 */
export function generateHeatTracePath(
  points: PidPoint[],
  offset: number = 6,
  zigzagAmplitude: number = 4,
  zigzagWavelength: number = 12,
): string {
  if (points.length < 2) return ''

  // Walk along each segment, generating zigzag points offset from the pipe
  const result: string[] = []
  let first = true

  for (let seg = 0; seg < points.length - 1; seg++) {
    const a = points[seg]!
    const b = points[seg + 1]!
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy)
    if (len < 1) continue

    // Unit vectors: along segment and perpendicular (offset side)
    const ux = dx / len
    const uy = dy / len
    const nx = -uy  // perpendicular (left side)
    const ny = ux

    // Number of zigzag half-cycles along this segment
    const halfCycles = Math.max(2, Math.round(len / (zigzagWavelength / 2)))
    const stepLen = len / halfCycles

    for (let i = 0; i <= halfCycles; i++) {
      const t = i * stepLen
      // Base point offset from pipe centerline
      const bx = a.x + ux * t + nx * offset
      const by = a.y + uy * t + ny * offset
      // Zigzag: alternate +/- amplitude perpendicular to pipe
      const side = (i % 2 === 0) ? zigzagAmplitude : -zigzagAmplitude
      const px = bx + nx * side
      const py = by + ny * side

      if (first) {
        result.push(`M ${px.toFixed(1)} ${py.toFixed(1)}`)
        first = false
      } else {
        result.push(`L ${px.toFixed(1)} ${py.toFixed(1)}`)
      }
    }
  }

  return result.join(' ')
}

/** Get heat trace color by type */
export function getHeatTraceColor(traceType: string): string {
  return HEAT_TRACE_COLORS[traceType] || '#f97316'
}

// #2.7 — Pipe medium line coding (ISA-5.1 color defaults)
const PIPE_MEDIUM_COLORS: Record<string, string> = {
  water: '#3b82f6',
  steam: '#ef4444',
  gas: '#eab308',
  air: '#a3e635',
  oil: '#a16207',
  chemical: '#a855f7',
  electrical: '#f97316',
  signal: '#06b6d4',
}

// #5.1 — Pipe medium abbreviations for auto-labeling
const PIPE_MEDIUM_ABBREV: Record<string, string> = {
  water: 'W', steam: 'STM', gas: 'G', air: 'A', oil: 'OIL',
  chemical: 'CH', electrical: 'E', signal: 'SIG',
  'cooling-water': 'CW', 'chilled-water': 'CHW', 'hot-water': 'HW',
  condensate: 'C', nitrogen: 'N₂', hydrogen: 'H₂', oxygen: 'O₂',
  'fuel-gas': 'FG', 'natural-gas': 'NG', 'instrument-air': 'IA',
  exhaust: 'EX', vacuum: 'VAC', drain: 'DR', vent: 'VNT',
}

/** Get pipe display label — explicit label > line number > medium abbreviation */
export function getPipeDisplayLabel(pipe: PidPipe): string {
  if (pipe.label) return pipe.label
  if (pipe.lineNumber) return pipe.lineNumber
  if (pipe.medium) {
    const abbrev = PIPE_MEDIUM_ABBREV[pipe.medium]
    if (abbrev) return abbrev
  }
  return ''
}

export function getPipeMediumColor(pipe: PidPipe): string {
  if (pipe.color) return pipe.color
  if (pipe.medium) {
    const color = PIPE_MEDIUM_COLORS[pipe.medium]
    if (color) return color
  }
  return '#60a5fa'
}

export function getPipeDashArray(pipe: PidPipe): string | undefined {
  if (pipe.dashPattern) return pipe.dashPattern
  if (pipe.dashed) return '8,4'
  if (pipe.lineCode) {
    return ISA_SIGNAL_DASH[pipe.lineCode] ?? undefined
  }
  return undefined
}

export function getMarkerUrl(pipe: PidPipe, endpoint: 'start' | 'end'): string | undefined {
  const arrowType = resolveArrowType(endpoint === 'start' ? pipe.startArrow : pipe.endArrow)
  if (arrowType === 'none') return undefined
  const color = getPipeMediumColor(pipe).replace('#', '')
  return `url(#marker-${arrowType}-${endpoint}-${color})`
}

export function getPipeLabelPoint(pipe: PidPipe): PidPoint | null {
  if (pipe.points.length < 2) return null
  const position = pipe.labelPosition || 'middle'
  if (position === 'start') return pipe.points[0]!
  if (position === 'end') return pipe.points[pipe.points.length - 1]!
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

export function distanceToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const A = px - x1
  const B = py - y1
  const C = x2 - x1
  const D = y2 - y1
  const dot = A * C + B * D
  const lenSq = C * C + D * D
  const param = lenSq !== 0 ? dot / lenSq : -1

  let xx, yy
  if (param < 0) { xx = x1; yy = y1 }
  else if (param > 1) { xx = x2; yy = y2 }
  else { xx = x1 + param * C; yy = y1 + param * D }

  return Math.sqrt((px - xx) ** 2 + (py - yy) ** 2)
}

// ─── SVG DOMParser cache (#2.5) ────────────────────────────────────

const svgParserCache = new Map<string, Document>()
const domParser = typeof DOMParser !== 'undefined' ? new DOMParser() : null
const xmlSerializer = typeof XMLSerializer !== 'undefined' ? new XMLSerializer() : null

function parseSvgCached(svgString: string, cacheKey: string): Document | null {
  if (!domParser) return null
  let doc = svgParserCache.get(cacheKey)
  if (!doc) {
    doc = domParser.parseFromString(svgString, 'image/svg+xml')
    svgParserCache.set(cacheKey, doc)
  }
  // Return a deep clone so mutations don't affect the cache
  return doc.cloneNode(true) as Document
}

function serializeSvg(doc: Document): string {
  if (!xmlSerializer) return ''
  const svg = doc.querySelector('svg') || doc.documentElement
  return xmlSerializer.serializeToString(svg)
}

// ─── ISA-5.1 Signal Line Dash Patterns (#3.2) ────────────────────

/** ISA 5.1 signal line dash patterns — each type has a distinct visual encoding */
export const ISA_SIGNAL_DASH: Record<string, string | undefined> = {
  undefined: undefined,               // Solid
  pneumatic: '8,4',                    // Dashed: --- --- ---
  electrical: '2,3',                   // Dotted: · · · ·
  capillary: '8,3,2,3',               // Dash-dot: -·-·-·
  hydraulic: '8,3,2,3,2,3',           // Dash-dot-dot: -··-··-··
  electromagnetic: '2,2,2,2,8,2',     // Triple-dot-dash: ···---···
  software: '12,3',                   // Long dash (data link): ═══
}

/** Get the SVG stroke-dasharray for an indicator's signal line */
export function getSignalLineDashArray(indicator: { signalType?: string; signalLineDashed?: boolean }): string | undefined {
  if (indicator.signalType) {
    return ISA_SIGNAL_DASH[indicator.signalType]
  }
  // Fallback to legacy boolean
  return indicator.signalLineDashed !== false ? '4,3' : undefined
}

// ─── ISA-5.1 Instrument Bubble (#4.3) ────────────────────────────

// ISA function letter defaults per instrument symbol type
const ISA_FUNCTION_MAP: Record<string, string> = {
  pressureTransducer: 'PT', temperatureElement: 'TE', flowMeter: 'FT',
  levelTransmitter: 'LT', flowSwitch: 'FS', pressureSwitch: 'PS',
  analyzer: 'AT', phSensor: 'AE', conductivitySensor: 'AE',
  pressureGauge: 'PI', temperatureIndicator: 'TI', orificePlate: 'FE',
  loadCell: 'WE', vibrationSensor: 'VT', thermowell: 'TE',
}

/** Parse ISA function letters from label (e.g. "PT-101" → "PT", "FIC-200A" → "FIC") */
export function parseIsaLetters(label: string): string {
  const match = label.match(/^([A-Z]{1,4})\s*[-_]/)
  return match?.[1] ?? ''
}

/** Parse tag number from label (e.g. "PT-101" → "101", "FIC-200A" → "200A") */
export function parseIsaTagNumber(label: string): string {
  const match = label.match(/[-_]\s*(.+)$/)
  return match?.[1] ?? label
}

/** Check if a symbol type is an instrument that should show an ISA bubble */
export function isInstrumentSymbol(type: string): boolean {
  return type in ISA_FUNCTION_MAP
}

/** Get ISA function letters for a symbol — from label or default by type */
export function getIsaFunctionLetters(symbol: PidSymbol): string {
  if (symbol.label) {
    const parsed = parseIsaLetters(symbol.label)
    if (parsed) return parsed
  }
  return ISA_FUNCTION_MAP[symbol.type] || ''
}

// ─── Composable (needs store / safety / pidLayer) ──────────────────

type Store = ReturnType<typeof useDashboardStore>
type Safety = ReturnType<typeof useSafety>

export function usePidRendering(
  store: Store,
  safety: Safety,
  getPidLayer: () => PidLayerData,
) {
  const colorScheme = computed(() => store.pidColorScheme)

  function getTankFillLevel(symbol: PidSymbol): number {
    if (!isTankSymbol(symbol)) return -1
    if (symbol.fillChannel) {
      const value = store.values[symbol.fillChannel]
      if (value && typeof value.value === 'number') {
        return Math.max(0, Math.min(100, value.value))
      }
    }
    if (typeof symbol.fillLevel === 'number') {
      return Math.max(0, Math.min(100, symbol.fillLevel))
    }
    return 50
  }

  // Tank fill dimensions per symbol type
  const TANK_FILL_GEOMETRY: Record<string, { x: number; baseY: number; w: number; maxH: number }> = {
    tank:           { x: 15, baseY: 70, w: 30, maxH: 50 },
    horizontalTank: { x: 20, baseY: 43, w: 40, maxH: 18 },
    reactor:        { x: 15, baseY: 60, w: 30, maxH: 35 },
  }

  function getTankSvgWithFill(symbol: PidSymbol): string {
    const baseSvg = getSymbolSvg(symbol.type, store.pidCustomSymbols)
    const fillLevel = getTankFillLevel(symbol)

    if (fillLevel < 0) return baseSvg

    const fillPercent = fillLevel / 100
    const rawColor = symbol.fillColor || 'currentColor'
    const fillColor = /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgb\(\d+,\s*\d+,\s*\d+\)|currentColor)$/.test(rawColor)
      ? rawColor
      : 'currentColor'

    // Use DOMParser approach (#2.5) — robust, no fragile regex
    const doc = parseSvgCached(baseSvg, symbol.type)
    if (!doc) return baseSvg

    const geom = TANK_FILL_GEOMETRY[symbol.type]
    if (!geom) return baseSvg

    const fillHeight = fillPercent * geom.maxH
    const fillY = geom.baseY - fillHeight

    // Find existing level-fill rect, or any fill placeholder rect
    let fillRect = doc.querySelector('.level-fill') as SVGElement | null
    if (!fillRect) {
      fillRect = doc.querySelector('rect[opacity="0.3"]') as SVGElement | null
    }

    if (fillRect) {
      fillRect.setAttribute('x', String(geom.x))
      fillRect.setAttribute('y', String(fillY))
      fillRect.setAttribute('width', String(geom.w))
      fillRect.setAttribute('height', String(fillHeight))
      fillRect.setAttribute('class', 'level-fill')
      fillRect.setAttribute('fill', fillColor)
      fillRect.setAttribute('opacity', '0.5')

      // Add shimmer animation if not already present
      if (!fillRect.querySelector('animate')) {
        const animate = doc.createElementNS('http://www.w3.org/2000/svg', 'animate')
        animate.setAttribute('attributeName', 'opacity')
        animate.setAttribute('values', '0.4;0.6;0.4')
        animate.setAttribute('dur', '2s')
        animate.setAttribute('repeatCount', 'indefinite')
        fillRect.appendChild(animate)
      }
    }

    return serializeSvg(doc)
  }

  // #2.6 — Valve position animation (0-100% open)
  function getValvePosition(symbol: PidSymbol): number {
    if (!symbol.positionChannel) return -1
    const val = store.values[symbol.positionChannel]
    if (val && typeof val.value === 'number') {
      return Math.max(0, Math.min(100, val.value))
    }
    return -1
  }

  function getValveSvgWithPosition(symbol: PidSymbol): string {
    const baseSvg = getSymbolSvg(symbol.type, store.pidCustomSymbols)
    const position = getValvePosition(symbol)
    if (position < 0) return baseSvg

    const info = isScadaSymbol(symbol.type) ? SYMBOL_INFO[symbol.type] : null
    if (!info?.isValve) return baseSvg

    const doc = parseSvgCached(baseSvg, `${symbol.type}-valve`)
    if (!doc) return baseSvg

    const pct = position / 100 // 0 = closed, 1 = fully open

    if (symbol.type === 'butterflyValve') {
      // Butterfly: rotate the disc line from 45° (closed) to 90° (open/vertical)
      const disc = doc.querySelector('line:not([x1="30"][y1="10"])') as SVGElement | null
      if (disc) {
        // Disc rotates from diagonal (closed ~45°) to vertical (open ~90°)
        const angle = 45 + pct * 45  // 45° closed → 90° open
        disc.setAttribute('transform', `rotate(${angle} 30 20)`)
        disc.setAttribute('x1', '30')
        disc.setAttribute('y1', '10')
        disc.setAttribute('x2', '30')
        disc.setAttribute('y2', '30')
      }
    } else {
      // Globe/control/solenoid: move stem up as valve opens
      // The stem is the <line> connecting body to actuator
      const stem = doc.querySelector('line[x1="30"]') as SVGElement | null
      if (stem) {
        const y1 = parseFloat(stem.getAttribute('y1') || '0')
        const y2 = parseFloat(stem.getAttribute('y2') || '0')
        // Shorten stem as valve opens (stem retracts upward)
        const stemTravel = Math.abs(y1 - y2) * 0.3 // max 30% of stem length
        const offset = pct * stemTravel
        stem.setAttribute('y2', String(y2 - offset))
      }
    }

    return serializeSvg(doc)
  }

  // #2.8 — Conveyor/belt animation (scrolling diagonal lines when running)
  function getConveyorSvgWithAnimation(symbol: PidSymbol): string {
    const baseSvg = getSymbolSvg(symbol.type, store.pidCustomSymbols)
    if (symbol.type !== 'conveyor') return baseSvg
    if (!isSymbolRunning(symbol)) return baseSvg

    const doc = parseSvgCached(baseSvg, 'conveyor-anim')
    if (!doc) return baseSvg

    const svg = doc.querySelector('svg') || doc.documentElement

    // Add a scrolling diagonal-line pattern to represent belt motion
    const defs = doc.createElementNS('http://www.w3.org/2000/svg', 'defs')
    const pattern = doc.createElementNS('http://www.w3.org/2000/svg', 'pattern')
    pattern.setAttribute('id', 'belt-lines')
    pattern.setAttribute('patternUnits', 'userSpaceOnUse')
    pattern.setAttribute('width', '8')
    pattern.setAttribute('height', '8')

    const patternLine = doc.createElementNS('http://www.w3.org/2000/svg', 'line')
    patternLine.setAttribute('x1', '0')
    patternLine.setAttribute('y1', '8')
    patternLine.setAttribute('x2', '8')
    patternLine.setAttribute('y2', '0')
    patternLine.setAttribute('stroke', 'currentColor')
    patternLine.setAttribute('stroke-width', '1.5')
    patternLine.setAttribute('stroke-opacity', '0.3')
    pattern.appendChild(patternLine)

    // Animate the pattern offset to create scrolling effect
    const animateTransform = doc.createElementNS('http://www.w3.org/2000/svg', 'animateTransform')
    animateTransform.setAttribute('attributeName', 'patternTransform')
    animateTransform.setAttribute('type', 'translate')
    animateTransform.setAttribute('from', '0 0')
    animateTransform.setAttribute('to', '8 0')
    animateTransform.setAttribute('dur', '0.5s')
    animateTransform.setAttribute('repeatCount', 'indefinite')
    pattern.appendChild(animateTransform)

    defs.appendChild(pattern)
    svg.insertBefore(defs, svg.firstChild)

    // Add a rect between the belt lines using the pattern
    const beltRect = doc.createElementNS('http://www.w3.org/2000/svg', 'rect')
    beltRect.setAttribute('x', '12')
    beltRect.setAttribute('y', '10')
    beltRect.setAttribute('width', '56')
    beltRect.setAttribute('height', '16')
    beltRect.setAttribute('fill', 'url(#belt-lines)')
    svg.appendChild(beltRect)

    return serializeSvg(doc)
  }

  function isSymbolInAlarm(symbol: PidSymbol): boolean {
    if (!symbol.channel) return false
    const value = store.values[symbol.channel]
    return value?.alarm === true || value?.warning === true
  }

  function getSymbolColor(symbol: PidSymbol): string {
    if (symbol.stateChannel && (symbol.onColor || symbol.offColor || symbol.faultColor)) {
      const val = store.values[symbol.stateChannel]
      if (val?.alarm || val?.disconnected || val?.quality === 'bad') {
        return symbol.faultColor || '#ef4444'
      }
      if (val && typeof val.value === 'number') {
        const threshold = symbol.stateThreshold ?? 0.5
        return val.value >= threshold
          ? (symbol.onColor || '#22c55e')
          : (symbol.offColor || '#6b7280')
      }
      return symbol.offColor || '#6b7280'
    }
    return symbol.color || '#60a5fa'
  }

  function getSymbolAlarmState(symbol: PidSymbol): {
    level: 'none' | 'warning' | 'alarm'
    acknowledged: boolean
  } {
    if (!symbol.channel) return { level: 'none', acknowledged: true }
    const val = store.values[symbol.channel]
    if (!val) return { level: 'none', acknowledged: true }
    if (val.alarm) {
      // Check if alarm is acknowledged via safety composable
      const activeAlarm = safety.activeAlarms?.value?.find(
        a => a.channel === symbol.channel && a.state === 'active'
      )
      return { level: 'alarm', acknowledged: !activeAlarm }
    }
    if (val.warning) {
      const activeAlarm = safety.activeAlarms?.value?.find(
        a => a.channel === symbol.channel && a.state === 'active'
      )
      return { level: 'warning', acknowledged: !activeAlarm }
    }
    return { level: 'none', acknowledged: true }
  }

  function isSymbolRunning(symbol: PidSymbol): boolean {
    if (!symbol.stateChannel) return false
    const val = store.values[symbol.stateChannel]
    if (!val || typeof val.value !== 'number') return false
    return val.value >= (symbol.stateThreshold ?? 0.5)
  }

  function isSymbolDisconnected(symbol: PidSymbol): boolean {
    if (!symbol.channel) return false
    const val = store.values[symbol.channel]
    return !val || val.disconnected === true || val.quality === 'bad'
  }

  function getSymbolStyle(symbol: PidSymbol): Record<string, string> {
    const style: Record<string, string> = {
      left: `${symbol.x}px`,
      top: `${symbol.y}px`,
      width: `${symbol.width}px`,
      height: `${symbol.height}px`,
      zIndex: String(symbol.zIndex || 1)
    }
    const transforms: string[] = []
    if (symbol.flipX) transforms.push('scaleX(-1)')
    if (symbol.flipY) transforms.push('scaleY(-1)')
    if (symbol.rotation) transforms.push(`rotate(${symbol.rotation}deg)`)
    if (transforms.length > 0) style.transform = transforms.join(' ')

    // ISA-101 Grayscale mode: show grayscale unless in alarm
    if (colorScheme.value === 'isa101' && !isSymbolInAlarm(symbol)) {
      style.filter = 'grayscale(100%)'
    }

    // #2.3 — Disconnected/bad quality: dim and desaturate
    if (isSymbolDisconnected(symbol)) {
      style.opacity = '0.4'
      style.filter = 'grayscale(80%)'
      style.transition = 'opacity 0.5s, filter 0.5s'
    }

    return style
  }

  function getSymbolAnimationClass(symbol: PidSymbol): string {
    const classes: string[] = []

    // #2.1 — Rotating equipment animation (pumps, fans, motors)
    if (isRotatingSymbol(symbol.type) && isSymbolRunning(symbol)) {
      classes.push('pid-rotating')
    }

    // #2.2 — Alarm blink for unacknowledged alarms (ISA-18.2)
    const alarmState = getSymbolAlarmState(symbol)
    if (!alarmState.acknowledged) {
      if (alarmState.level === 'alarm') {
        classes.push('pid-alarm-blink-fast')
      } else if (alarmState.level === 'warning') {
        classes.push('pid-alarm-blink-slow')
      }
    }

    return classes.join(' ')
  }

  function getSymbolValue(symbol: PidSymbol): string {
    if (!symbol.channel) return ''
    const value = store.values[symbol.channel]
    if (!value) return '--'
    const dec = symbol.decimals ?? 1
    if (typeof value.value === 'number') {
      if (!Number.isFinite(value.value)) return '--'
      return value.value.toFixed(dec)
    }
    return String(value.value)
  }

  function getInterlockBadge(symbol: PidSymbol): { state: 'satisfied' | 'failed' | 'bypassed'; tooltip: string } | null {
    if (!symbol.interlockId) return null
    const status = safety.interlockStatuses.value.find(s => s.id === symbol.interlockId && s.enabled)
    if (!status) return null
    if (!status.satisfied && !status.bypassed) return { state: 'failed', tooltip: `Blocked: ${status.name}` }
    if (status.bypassed) return { state: 'bypassed', tooltip: `Bypassed: ${status.name}` }
    return { state: 'satisfied', tooltip: `OK: ${status.name}` }
  }

  function getPipeFlowState(pipe: PidPipe): {
    animated: boolean
    speed: number
    direction: 'forward' | 'reverse' | 'stopped'
  } {
    if (pipe.flowChannel) {
      const value = store.values[pipe.flowChannel]
      if (value && typeof value.value === 'number') {
        if (value.value > 0) {
          return {
            animated: true,
            speed: Math.min(3, value.value / 10) || 1,
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
    return {
      animated: pipe.animated || false,
      speed: pipe.flowSpeed || 1,
      direction: pipe.flowDirection || 'forward'
    }
  }

  /** Check if a pipe's heat trace is active (always on if no channel bound) */
  function isHeatTraceActive(pipe: PidPipe): boolean {
    if (!pipe.heatTrace || pipe.heatTrace === 'none') return false
    if (!pipe.heatTraceChannel) return true // no channel = always shown
    const val = store.values[pipe.heatTraceChannel]
    if (val && typeof val.value === 'number') {
      return val.value >= (pipe.heatTraceThreshold ?? 0.5)
    }
    return false
  }

  function generatePipePathWithJumps(pipe: PidPipe): string {
    if (!pipe.jumpStyle || pipe.jumpStyle === 'none') return generatePipePath(pipe)
    if (pipe.points.length < 2) return ''

    const jumpR = (pipe.jumpSize || 8) / 2
    const otherPipes = getPidLayer().pipes.filter(p => p.id !== pipe.id)

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
        const segDx = segB.x - segA.x, segDy = segB.y - segA.y
        const segLen = Math.hypot(segDx, segDy)
        const ux = segDx / segLen, uy = segDy / segLen

        for (const hit of hits) {
          const beforeX = hit.pt.x - ux * jumpR
          const beforeY = hit.pt.y - uy * jumpR
          const afterX = hit.pt.x + ux * jumpR
          const afterY = hit.pt.y + uy * jumpR

          path += ` L ${beforeX} ${beforeY}`
          if (pipe.jumpStyle === 'arc') {
            path += ` A ${jumpR} ${jumpR} 0 0 1 ${afterX} ${afterY}`
          } else {
            path += ` M ${afterX} ${afterY}`
          }
        }
        path += ` L ${segB.x} ${segB.y}`
      }
    }
    return path
  }

  const pipeMarkerDefs = computed(() => {
    const defs: { id: string; type: PidArrowType; endpoint: 'start' | 'end'; color: string }[] = []
    const seen = new Set<string>()
    for (const pipe of getPidLayer().pipes) {
      const color = getPipeMediumColor(pipe)
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

  // ─── Indicator rendering (block editor stubs on symbol perimeter) ───

  /**
   * Get runtime color for an indicator based on alarm/interlock state.
   */
  function getIndicatorRuntimeColor(indicator: PidIndicator): string {
    if (indicator.type === 'interlock' && indicator.interlockId) {
      const status = safety.interlockStatuses?.value?.find(
        (s: any) => s.id === indicator.interlockId
      )
      if (status) {
        if (status.bypassed) return '#f59e0b'     // amber
        if (!status.satisfied) return '#ef4444'    // red
        return '#22c55e'                           // green
      }
    }
    if (indicator.channel) {
      const val = store.values[indicator.channel]
      if (val?.alarm) return '#ef4444'             // red
      if (val?.warning) return '#f59e0b'           // amber
      if (val?.disconnected) return '#6b7280'      // gray
    }
    return '#94a3b8'  // default slate
  }

  /**
   * Get formatted live value for a channel-bound indicator.
   */
  function getIndicatorValue(indicator: PidIndicator): string {
    if (!indicator.channel || !indicator.showValue) return ''
    const val = store.values[indicator.channel]
    if (!val) return '--'
    if (typeof val.value === 'number') {
      return val.value.toFixed(indicator.decimals ?? 1)
    }
    return String(val.value ?? '--')
  }

  /**
   * Check if an indicator's bound channel is in alarm.
   */
  function isIndicatorInAlarm(indicator: PidIndicator): boolean {
    if (!indicator.channel) return false
    const val = store.values[indicator.channel]
    return val?.alarm === true || val?.warning === true
  }

  return {
    colorScheme,
    // Symbol rendering
    getTankFillLevel,
    getTankSvgWithFill,
    getValveSvgWithPosition,
    getConveyorSvgWithAnimation,
    isSymbolInAlarm,
    getSymbolColor,
    getSymbolStyle,
    getSymbolValue,
    getInterlockBadge,
    getSymbolAlarmState,
    getSymbolAnimationClass,
    isSymbolRunning,
    isSymbolDisconnected,
    // Pipe rendering
    getPipeFlowState,
    isHeatTraceActive,
    generatePipePathWithJumps,
    pipeMarkerDefs,
    // Indicator rendering
    getIndicatorRuntimeColor,
    getIndicatorValue,
    isIndicatorInAlarm,
  }
}
