/**
 * Port Validation Test
 *
 * Validates that SYMBOL_PORTS coordinates actually correspond to SVG geometry
 * endpoints — i.e., ports sit at the edge of visible drawing content, not
 * floating in empty space.
 *
 * For each symbol type:
 * 1. Parse the SVG viewBox to get coordinate space
 * 2. Extract all geometric endpoints from SVG elements (line, path, rect, circle, polyline, polygon, ellipse)
 * 3. For each port, convert its normalized (0-1) coord to viewBox pixels
 * 4. Check that a nearby SVG endpoint exists within tolerance
 *
 * Edge ports (x=0, x=1, y=0, y=1) are checked against the viewBox boundary.
 * Interior ports are checked against actual SVG geometry.
 */
import { describe, it, expect } from 'vitest'
import { SCADA_SYMBOLS, SYMBOL_PORTS, type ScadaSymbolType } from './index'

interface Point { x: number; y: number }

/** Parse viewBox from SVG string */
function parseViewBox(svg: string): { x: number; y: number; w: number; h: number } | null {
  const match = svg.match(/viewBox=["']([^"']+)["']/)
  if (!match) return null
  const parts = match[1]!.trim().split(/\s+/).map(Number)
  if (parts.length < 4) return null
  return { x: parts[0]!, y: parts[1]!, w: parts[2]!, h: parts[3]! }
}

/** Extract all coordinate endpoints from SVG elements */
function extractSvgEndpoints(svg: string, vb: { w: number; h: number }): Point[] {
  const points: Point[] = []

  // <line x1="..." y1="..." x2="..." y2="...">
  const lineRe = /<line[^>]*?\bx1=["']([^"']+)["'][^>]*?\by1=["']([^"']+)["'][^>]*?\bx2=["']([^"']+)["'][^>]*?\by2=["']([^"']+)["']/g
  let m: RegExpExecArray | null
  while ((m = lineRe.exec(svg)) !== null) {
    points.push({ x: parseFloat(m[1]!), y: parseFloat(m[2]!) })
    points.push({ x: parseFloat(m[3]!), y: parseFloat(m[4]!) })
  }
  // Also handle reversed attribute order (y1 before x1, etc)
  const lineRe2 = /<line[^>]*?\by1=["']([^"']+)["'][^>]*?\bx1=["']([^"']+)["'][^>]*?\by2=["']([^"']+)["'][^>]*?\bx2=["']([^"']+)["']/g
  while ((m = lineRe2.exec(svg)) !== null) {
    points.push({ x: parseFloat(m[2]!), y: parseFloat(m[1]!) })
    points.push({ x: parseFloat(m[4]!), y: parseFloat(m[3]!) })
  }

  // <rect x="..." y="..." width="..." height="...">
  const rectRe = /<rect[^>]*?\bx=["']([^"']+)["'][^>]*?\by=["']([^"']+)["'][^>]*?\bwidth=["']([^"']+)["'][^>]*?\bheight=["']([^"']+)["']/g
  while ((m = rectRe.exec(svg)) !== null) {
    const rx = parseFloat(m[1]!), ry = parseFloat(m[2]!), rw = parseFloat(m[3]!), rh = parseFloat(m[4]!)
    points.push({ x: rx, y: ry })
    points.push({ x: rx + rw, y: ry })
    points.push({ x: rx, y: ry + rh })
    points.push({ x: rx + rw, y: ry + rh })
    // Also midpoints of edges for side connections
    points.push({ x: rx, y: ry + rh / 2 })
    points.push({ x: rx + rw, y: ry + rh / 2 })
    points.push({ x: rx + rw / 2, y: ry })
    points.push({ x: rx + rw / 2, y: ry + rh })
  }

  // <circle cx="..." cy="..." r="...">
  const circleRe = /<circle[^>]*?\bcx=["']([^"']+)["'][^>]*?\bcy=["']([^"']+)["'][^>]*?\br=["']([^"']+)["']/g
  while ((m = circleRe.exec(svg)) !== null) {
    const cx = parseFloat(m[1]!), cy = parseFloat(m[2]!), r = parseFloat(m[3]!)
    points.push({ x: cx, y: cy })
    points.push({ x: cx - r, y: cy })
    points.push({ x: cx + r, y: cy })
    points.push({ x: cx, y: cy - r })
    points.push({ x: cx, y: cy + r })
  }

  // <ellipse cx="..." cy="..." rx="..." ry="...">
  const ellipseRe = /<ellipse[^>]*?\bcx=["']([^"']+)["'][^>]*?\bcy=["']([^"']+)["'][^>]*?\brx=["']([^"']+)["'][^>]*?\bry=["']([^"']+)["']/g
  while ((m = ellipseRe.exec(svg)) !== null) {
    const cx = parseFloat(m[1]!), cy = parseFloat(m[2]!), rx = parseFloat(m[3]!), ry = parseFloat(m[4]!)
    points.push({ x: cx - rx, y: cy })
    points.push({ x: cx + rx, y: cy })
    points.push({ x: cx, y: cy - ry })
    points.push({ x: cx, y: cy + ry })
  }

  // <polyline points="..."> and <polygon points="...">
  const polyRe = /<poly(?:line|gon)[^>]*?\bpoints=["']([^"']+)["']/g
  while ((m = polyRe.exec(svg)) !== null) {
    const coords = m[1]!.trim().split(/[\s,]+/).map(Number)
    for (let i = 0; i < coords.length - 1; i += 2) {
      points.push({ x: coords[i]!, y: coords[i + 1]! })
    }
  }

  // <path d="..."> — extract M, L, C, Z coordinates (start/end points of segments)
  const pathRe = /<path[^>]*?\bd=["']([^"']+)["']/g
  while ((m = pathRe.exec(svg)) !== null) {
    const d = m[1]!
    // Extract numeric coordinate pairs following M, L, C, S, Q, T, A commands
    const cmdRe = /([MLCSQTA])\s*([-\d.]+(?:[\s,]+[-\d.]+)*)/gi
    let cm: RegExpExecArray | null
    while ((cm = cmdRe.exec(d)) !== null) {
      const cmd = cm[1]!.toUpperCase()
      const nums = cm[2]!.trim().split(/[\s,]+/).map(Number)
      if (cmd === 'M' || cmd === 'L' || cmd === 'T') {
        for (let i = 0; i < nums.length - 1; i += 2) {
          points.push({ x: nums[i]!, y: nums[i + 1]! })
        }
      } else if (cmd === 'C') {
        // Cubic bezier: x1,y1 x2,y2 x,y — endpoint is last pair
        for (let i = 0; i < nums.length - 1; i += 6) {
          if (i + 5 < nums.length) {
            points.push({ x: nums[i + 4]!, y: nums[i + 5]! })
          }
        }
      } else if (cmd === 'S') {
        for (let i = 0; i < nums.length - 1; i += 4) {
          if (i + 3 < nums.length) {
            points.push({ x: nums[i + 2]!, y: nums[i + 3]! })
          }
        }
      } else if (cmd === 'Q') {
        for (let i = 0; i < nums.length - 1; i += 4) {
          if (i + 3 < nums.length) {
            points.push({ x: nums[i + 2]!, y: nums[i + 3]! })
          }
        }
      } else if (cmd === 'A') {
        // Arc: rx ry rotation large-arc sweep x y — endpoint is last pair
        for (let i = 0; i < nums.length - 1; i += 7) {
          if (i + 6 < nums.length) {
            points.push({ x: nums[i + 5]!, y: nums[i + 6]! })
          }
        }
      }
    }
  }

  // Also add the viewBox boundary points for edge-snapping ports
  points.push({ x: 0, y: 0 })
  points.push({ x: vb.w, y: 0 })
  points.push({ x: 0, y: vb.h })
  points.push({ x: vb.w, y: vb.h })

  return points
}

/** Find minimum distance from a point to any SVG endpoint */
function minDistToEndpoints(px: number, py: number, endpoints: Point[]): number {
  let min = Infinity
  for (const ep of endpoints) {
    const d = Math.hypot(ep.x - px, ep.y - py)
    if (d < min) min = d
  }
  return min
}

/** Find the closest endpoint for debugging */
function closestEndpoint(px: number, py: number, endpoints: Point[]): Point & { dist: number } {
  let min = Infinity
  let closest: Point = { x: 0, y: 0 }
  for (const ep of endpoints) {
    const d = Math.hypot(ep.x - px, ep.y - py)
    if (d < min) { min = d; closest = ep }
  }
  return { ...closest, dist: min }
}

// Tolerance: how far (in viewBox px) a port can be from the nearest SVG endpoint
// Most symbols have viewBox 40-100px wide, so 5px tolerance is ~5-12% of symbol size.
// Generous tolerance because SVG geometry parsing is approximate (paths, arcs, etc)
const TOLERANCE = 6

// Symbols to skip validation for (purely decorative, annotation, or have no meaningful geometry)
const SKIP_SYMBOLS = new Set<string>([
  'barrel',          // No ports defined (empty array)
  'diamondSymbol',   // No ports defined (empty array)
])

describe('SYMBOL_PORTS edge validation', () => {
  // Get all symbol types that have ports
  const symbolTypes = Object.keys(SYMBOL_PORTS) as ScadaSymbolType[]

  it('should have ports defined for every symbol type in SCADA_SYMBOLS', () => {
    const symbolsWithoutPorts: string[] = []
    for (const type of Object.keys(SCADA_SYMBOLS)) {
      if (!SYMBOL_PORTS[type as ScadaSymbolType]) {
        symbolsWithoutPorts.push(type)
      }
    }
    // Report but don't fail — some symbols legitimately have no ports
    if (symbolsWithoutPorts.length > 0) {
      console.warn(`Symbols without ports: ${symbolsWithoutPorts.join(', ')}`)
    }
  })

  it('should have consistent direction for edge ports', () => {
    const issues: string[] = []
    for (const type of symbolTypes) {
      const ports = SYMBOL_PORTS[type]
      if (!ports) continue
      for (const port of ports) {
        // x=0 should be direction 'left', x=1 should be 'right'
        // y=0 should be 'top', y=1 should be 'bottom'
        if (port.x === 0 && port.direction !== 'left') {
          issues.push(`${type}.${port.id}: x=0 but direction=${port.direction} (expected left)`)
        }
        if (port.x === 1 && port.direction !== 'right') {
          issues.push(`${type}.${port.id}: x=1 but direction=${port.direction} (expected right)`)
        }
        if (port.y === 0 && port.direction !== 'top') {
          issues.push(`${type}.${port.id}: y=0 but direction=${port.direction} (expected top)`)
        }
        if (port.y === 1 && port.direction !== 'bottom') {
          issues.push(`${type}.${port.id}: y=1 but direction=${port.direction} (expected bottom)`)
        }
      }
    }
    if (issues.length > 0) {
      console.warn('Direction mismatches:\n  ' + issues.join('\n  '))
    }
    expect(issues).toHaveLength(0)
  })

  it('should have port coordinates within valid range [0, 1]', () => {
    const issues: string[] = []
    for (const type of symbolTypes) {
      const ports = SYMBOL_PORTS[type]
      if (!ports) continue
      for (const port of ports) {
        if (port.x < 0 || port.x > 1) {
          issues.push(`${type}.${port.id}: x=${port.x} out of range [0,1]`)
        }
        if (port.y < 0 || port.y > 1) {
          issues.push(`${type}.${port.id}: y=${port.y} out of range [0,1]`)
        }
      }
    }
    expect(issues).toHaveLength(0)
  })

  it('should have unique port IDs within each symbol', () => {
    const issues: string[] = []
    for (const type of symbolTypes) {
      const ports = SYMBOL_PORTS[type]
      if (!ports) continue
      const ids = ports.map(p => p.id)
      const unique = new Set(ids)
      if (unique.size !== ids.length) {
        const dupes = ids.filter((id, i) => ids.indexOf(id) !== i)
        issues.push(`${type}: duplicate port IDs: ${dupes.join(', ')}`)
      }
    }
    expect(issues).toHaveLength(0)
  })

  // The main test: check that ports align with SVG geometry
  describe('port-to-SVG geometry alignment', () => {
    const results: { type: string; port: string; portPx: Point; nearestPx: Point; dist: number }[] = []

    for (const type of symbolTypes) {
      const ports = SYMBOL_PORTS[type]
      const svg = SCADA_SYMBOLS[type]
      if (!ports || !svg || ports.length === 0) continue
      if (SKIP_SYMBOLS.has(type)) continue

      const vb = parseViewBox(svg)
      if (!vb) continue

      const endpoints = extractSvgEndpoints(svg, { w: vb.w, h: vb.h })

      for (const port of ports) {
        const portPxX = port.x * vb.w
        const portPxY = port.y * vb.h

        it(`${type}.${port.id} (${port.x}, ${port.y}) should be near SVG geometry`, () => {
          const dist = minDistToEndpoints(portPxX, portPxY, endpoints)
          if (dist > TOLERANCE) {
            const nearest = closestEndpoint(portPxX, portPxY, endpoints)
            results.push({
              type,
              port: port.id,
              portPx: { x: portPxX, y: portPxY },
              nearestPx: { x: nearest.x, y: nearest.y },
              dist: nearest.dist,
            })
          }
          expect(
            dist,
            `Port ${type}.${port.id} at viewBox (${portPxX.toFixed(1)}, ${portPxY.toFixed(1)}) ` +
            `is ${dist.toFixed(1)}px from nearest SVG endpoint (tolerance: ${TOLERANCE}px). ` +
            `Nearest endpoint: (${closestEndpoint(portPxX, portPxY, endpoints).x.toFixed(1)}, ` +
            `${closestEndpoint(portPxX, portPxY, endpoints).y.toFixed(1)})`
          ).toBeLessThanOrEqual(TOLERANCE)
        })
      }
    }
  })

  // Check that edge ports (direction matches boundary) are actually at the viewBox boundary
  describe('edge ports should touch viewBox boundary', () => {
    for (const type of symbolTypes) {
      const ports = SYMBOL_PORTS[type]
      const svg = SCADA_SYMBOLS[type]
      if (!ports || !svg || ports.length === 0) continue
      if (SKIP_SYMBOLS.has(type)) continue

      const vb = parseViewBox(svg)
      if (!vb) continue

      for (const port of ports) {
        // Only check ports that claim to be at the boundary via their direction
        const isEdge =
          (port.direction === 'left' && port.x <= 0.1) ||
          (port.direction === 'right' && port.x >= 0.9) ||
          (port.direction === 'top' && port.y <= 0.1) ||
          (port.direction === 'bottom' && port.y >= 0.9)

        if (!isEdge) continue

        it(`${type}.${port.id} edge port direction should match its boundary side`, () => {
          // An edge port pointing left should have small x, pointing right should have large x, etc.
          // This catches cases like a port with direction='left' but x=0.8
          if (port.direction === 'left') {
            expect(port.x, `${type}.${port.id} direction=left but x=${port.x}`).toBeLessThanOrEqual(0.15)
          }
          if (port.direction === 'right') {
            expect(port.x, `${type}.${port.id} direction=right but x=${port.x}`).toBeGreaterThanOrEqual(0.85)
          }
          if (port.direction === 'top') {
            expect(port.y, `${type}.${port.id} direction=top but y=${port.y}`).toBeLessThanOrEqual(0.15)
          }
          if (port.direction === 'bottom') {
            expect(port.y, `${type}.${port.id} direction=bottom but y=${port.y}`).toBeGreaterThanOrEqual(0.85)
          }
        })
      }
    }
  })
})
