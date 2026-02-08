/**
 * Auto-routing for orthogonal pipes in P&ID editor.
 *
 * Given a start and end port (position + direction), and a set of obstacle
 * bounding boxes, finds an orthogonal path (horizontal/vertical segments only)
 * that avoids all obstacles.
 *
 * Algorithm: A* on an orthogonal visibility graph built from obstacle corners.
 */

interface Point { x: number; y: number }
interface Rect { x: number; y: number; width: number; height: number }
interface PortInfo { x: number; y: number; direction: string }

const DIRECTION_OFFSETS: Record<string, { dx: number; dy: number }> = {
  left:   { dx: -1, dy:  0 },
  right:  { dx:  1, dy:  0 },
  top:    { dx:  0, dy: -1 },
  bottom: { dx:  0, dy:  1 },
}

/**
 * Auto-route an orthogonal pipe from start to end, avoiding obstacles.
 *
 * @param start - Start port position and direction
 * @param end - End port position and direction
 * @param obstacles - Bounding boxes to route around
 * @param padding - Gap between pipe and obstacles (default 15px)
 * @returns Array of waypoints forming an orthogonal path
 */
export function autoRoute(
  start: PortInfo,
  end: PortInfo,
  obstacles: Rect[],
  padding = 15
): Point[] {
  // Expand obstacles by padding
  const expanded = obstacles.map(r => ({
    x: r.x - padding,
    y: r.y - padding,
    width: r.width + padding * 2,
    height: r.height + padding * 2,
  }))

  // Create initial stubs extending from ports in their direction
  const stubLen = padding
  const startDir = DIRECTION_OFFSETS[start.direction] || { dx: 1, dy: 0 }
  const endDir = DIRECTION_OFFSETS[end.direction] || { dx: -1, dy: 0 }
  const startStub: Point = {
    x: start.x + startDir.dx * stubLen,
    y: start.y + startDir.dy * stubLen,
  }
  const endStub: Point = {
    x: end.x + endDir.dx * stubLen,
    y: end.y + endDir.dy * stubLen,
  }

  // Collect candidate waypoints from expanded obstacle corners + start/end stubs
  const candidates: Point[] = [startStub, endStub]
  for (const r of expanded) {
    candidates.push(
      { x: r.x, y: r.y },
      { x: r.x + r.width, y: r.y },
      { x: r.x, y: r.y + r.height },
      { x: r.x + r.width, y: r.y + r.height },
    )
  }

  // Build adjacency: two candidates are connected if an orthogonal line between them
  // (sharing x or y coordinate) doesn't cross any expanded obstacle
  type Node = number
  const n = candidates.length
  const adj: Map<Node, Array<{ to: Node; cost: number }>> = new Map()
  for (let i = 0; i < n; i++) adj.set(i, [])

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = candidates[i]!
      const b = candidates[j]!
      // Only orthogonal edges (shared x or shared y)
      if (a.x !== b.x && a.y !== b.y) continue
      if (!isOrthoClear(a, b, expanded)) continue
      const cost = Math.abs(a.x - b.x) + Math.abs(a.y - b.y)
      adj.get(i)!.push({ to: j, cost })
      adj.get(j)!.push({ to: i, cost })
    }
  }

  // If direct orthogonal edges don't connect start to end, also try L-shaped connections
  // by adding intermediate points at the intersection of horizontal/vertical lines
  const intermediates: Point[] = []
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = candidates[i]!
      const b = candidates[j]!
      if (a.x === b.x || a.y === b.y) continue
      intermediates.push({ x: a.x, y: b.y })
      intermediates.push({ x: b.x, y: a.y })
    }
  }

  // Add unique intermediates that aren't inside obstacles
  const seen = new Set(candidates.map(p => `${p.x},${p.y}`))
  for (const p of intermediates) {
    const key = `${p.x},${p.y}`
    if (seen.has(key)) continue
    if (isInsideAnyRect(p, expanded)) continue
    seen.add(key)
    const idx = candidates.length
    candidates.push(p)
    adj.set(idx, [])
    // Connect to all existing nodes via orthogonal clear lines
    for (let j = 0; j < idx; j++) {
      const b = candidates[j]!
      if (p.x !== b.x && p.y !== b.y) continue
      if (!isOrthoClear(p, b, expanded)) continue
      const cost = Math.abs(p.x - b.x) + Math.abs(p.y - b.y)
      adj.get(idx)!.push({ to: j, cost })
      adj.get(j)!.push({ to: idx, cost })
    }
  }

  // A* from node 0 (startStub) to node 1 (endStub)
  const path = astar(0, 1, candidates, adj)

  if (!path) {
    // Fallback: direct L-shaped path (no obstacle avoidance)
    return [
      { x: start.x, y: start.y },
      startStub,
      { x: startStub.x, y: endStub.y },
      endStub,
      { x: end.x, y: end.y },
    ]
  }

  // Build full path: start port → stub → A* path → stub → end port
  const result: Point[] = [{ x: start.x, y: start.y }]
  for (const idx of path) {
    result.push({ ...candidates[idx]! })
  }
  result.push({ x: end.x, y: end.y })

  return simplifyOrthoPath(result)
}

/** Check if an orthogonal line segment (horizontal or vertical) is clear of obstacles */
function isOrthoClear(a: Point, b: Point, rects: Rect[]): boolean {
  for (const r of rects) {
    if (a.x === b.x) {
      // Vertical line
      const x = a.x
      const minY = Math.min(a.y, b.y)
      const maxY = Math.max(a.y, b.y)
      if (x > r.x && x < r.x + r.width && maxY > r.y && minY < r.y + r.height) {
        return false
      }
    } else {
      // Horizontal line
      const y = a.y
      const minX = Math.min(a.x, b.x)
      const maxX = Math.max(a.x, b.x)
      if (y > r.y && y < r.y + r.height && maxX > r.x && minX < r.x + r.width) {
        return false
      }
    }
  }
  return true
}

/** Check if a point is strictly inside any rectangle */
function isInsideAnyRect(p: Point, rects: Rect[]): boolean {
  for (const r of rects) {
    if (p.x > r.x && p.x < r.x + r.width && p.y > r.y && p.y < r.y + r.height) {
      return true
    }
  }
  return false
}

/** A* pathfinding with Manhattan distance heuristic + bend penalty */
function astar(
  startIdx: number,
  endIdx: number,
  nodes: Point[],
  adj: Map<number, Array<{ to: number; cost: number }>>
): number[] | null {
  const end = nodes[endIdx]!
  const gScore = new Map<number, number>()
  const fScore = new Map<number, number>()
  const cameFrom = new Map<number, number>()

  gScore.set(startIdx, 0)
  fScore.set(startIdx, manhattan(nodes[startIdx]!, end))

  // Priority queue (simple sorted array — fine for small graphs)
  const open = new Set<number>([startIdx])

  while (open.size > 0) {
    // Pick node with lowest fScore
    let current = -1
    let bestF = Infinity
    for (const n of open) {
      const f = fScore.get(n) ?? Infinity
      if (f < bestF) { bestF = f; current = n }
    }
    if (current === -1) break

    if (current === endIdx) {
      // Reconstruct path
      const path: number[] = []
      let c: number | undefined = current
      while (c !== undefined) {
        path.push(c)
        c = cameFrom.get(c)
      }
      return path.reverse()
    }

    open.delete(current)
    const currentG = gScore.get(current) ?? Infinity

    for (const edge of adj.get(current) || []) {
      // Add a bend penalty: if direction changes from previous segment, add cost
      let bendPenalty = 0
      const prev = cameFrom.get(current)
      if (prev !== undefined) {
        const prevPt = nodes[prev]!
        const curPt = nodes[current]!
        const nextPt = nodes[edge.to]!
        const prevDir = prevPt.x === curPt.x ? 'v' : 'h'
        const nextDir = curPt.x === nextPt.x ? 'v' : 'h'
        if (prevDir !== nextDir) bendPenalty = 20
      }

      const tentativeG = currentG + edge.cost + bendPenalty
      if (tentativeG < (gScore.get(edge.to) ?? Infinity)) {
        cameFrom.set(edge.to, current)
        gScore.set(edge.to, tentativeG)
        fScore.set(edge.to, tentativeG + manhattan(nodes[edge.to]!, end))
        open.add(edge.to)
      }
    }
  }

  return null // No path found
}

function manhattan(a: Point, b: Point): number {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y)
}

/** Remove redundant collinear intermediate points from an orthogonal path */
function simplifyOrthoPath(points: Point[]): Point[] {
  if (points.length <= 2) return points
  const result: Point[] = [points[0]!]
  for (let i = 1; i < points.length - 1; i++) {
    const prev = result[result.length - 1]!
    const curr = points[i]!
    const next = points[i + 1]!
    // Skip if collinear (all same x or all same y)
    if ((prev.x === curr.x && curr.x === next.x) ||
        (prev.y === curr.y && curr.y === next.y)) {
      continue
    }
    result.push(curr)
  }
  result.push(points[points.length - 1]!)
  return result
}
