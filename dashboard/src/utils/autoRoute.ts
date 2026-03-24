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

/** Binary min-heap for A* open set — O(log n) insert/extract vs O(n) scan */
class MinHeap {
  private heap: Array<{ node: number; f: number }> = []
  private inHeap = new Set<number>()

  get size() { return this.heap.length }

  push(node: number, f: number) {
    this.heap.push({ node, f })
    this.inHeap.add(node)
    this._bubbleUp(this.heap.length - 1)
  }

  pop(): number {
    const top = this.heap[0]!
    this.inHeap.delete(top.node)
    const last = this.heap.pop()!
    if (this.heap.length > 0) {
      this.heap[0] = last
      this._sinkDown(0)
    }
    return top.node
  }

  has(node: number): boolean {
    return this.inHeap.has(node)
  }

  /** Update priority if lower — re-insert (duplicate allowed, handled by closed set) */
  decreaseKey(node: number, f: number) {
    this.push(node, f)
  }

  private _bubbleUp(i: number) {
    while (i > 0) {
      const parent = (i - 1) >> 1
      if (this.heap[i]!.f >= this.heap[parent]!.f) break
      const tmp = this.heap[i]!; this.heap[i] = this.heap[parent]!; this.heap[parent] = tmp
      i = parent
    }
  }

  private _sinkDown(i: number) {
    const n = this.heap.length
    while (true) {
      let smallest = i
      const l = 2 * i + 1, r = 2 * i + 2
      if (l < n && this.heap[l]!.f < this.heap[smallest]!.f) smallest = l
      if (r < n && this.heap[r]!.f < this.heap[smallest]!.f) smallest = r
      if (smallest === i) break
      const tmp = this.heap[i]!; this.heap[i] = this.heap[smallest]!; this.heap[smallest] = tmp
      i = smallest
    }
  }
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
  const cameFrom = new Map<number, number>()
  const closed = new Set<number>()

  gScore.set(startIdx, 0)
  const startF = manhattan(nodes[startIdx]!, end)

  const open = new MinHeap()
  open.push(startIdx, startF)

  const MAX_ITERATIONS = 5000
  let iterations = 0
  while (open.size > 0) {
    if (++iterations > MAX_ITERATIONS) return null // prevent browser freeze on dense diagrams
    const current = open.pop()
    if (closed.has(current)) continue // skip stale duplicate entries
    closed.add(current)

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

    const currentG = gScore.get(current) ?? Infinity

    for (const edge of adj.get(current) || []) {
      if (closed.has(edge.to)) continue

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
        const f = tentativeG + manhattan(nodes[edge.to]!, end)
        open.decreaseKey(edge.to, f)
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

// ─── Pipe Bundling ─────────────────────────────────────────────────

interface PipeInput {
  id: string
  points: Point[]
  strokeWidth?: number
}

interface OrthoSegment {
  pipeId: string
  axis: 'h' | 'v'     // horizontal or vertical
  coord: number         // the fixed coordinate (y for horizontal, x for vertical)
  min: number           // start of range on the other axis
  max: number           // end of range on the other axis
  pointIdxStart: number // index in the pipe's points array
  pointIdxEnd: number
}

/**
 * Post-process multiple routed pipes to bundle parallel overlapping segments.
 *
 * Detects orthogonal segments across all pipes that share the same axis and
 * coordinate (within tolerance) and have overlapping ranges. Offsets each pipe
 * in the bundle so they run side-by-side instead of stacking on top of each other.
 *
 * Returns a Map from pipe ID to adjusted point arrays. Pipes not needing adjustment
 * are omitted from the map.
 *
 * @param pipes - Array of pipes with their points and stroke widths
 * @param gap - Gap between bundled pipes in pixels (default 4)
 * @param tolerance - How close two segment coordinates must be to be considered parallel (default 1)
 */
export function bundleParallelPipes(
  pipes: PipeInput[],
  gap: number = 4,
  tolerance: number = 1
): Map<string, Point[]> {
  if (pipes.length < 2) return new Map()

  // Step 1: Extract all orthogonal segments from all pipes
  const segments: OrthoSegment[] = []
  for (const pipe of pipes) {
    for (let i = 0; i < pipe.points.length - 1; i++) {
      const a = pipe.points[i]!
      const b = pipe.points[i + 1]!
      if (a.x === b.x) {
        // Vertical segment
        segments.push({
          pipeId: pipe.id,
          axis: 'v',
          coord: a.x,
          min: Math.min(a.y, b.y),
          max: Math.max(a.y, b.y),
          pointIdxStart: i,
          pointIdxEnd: i + 1,
        })
      } else if (a.y === b.y) {
        // Horizontal segment
        segments.push({
          pipeId: pipe.id,
          axis: 'h',
          coord: a.y,
          min: Math.min(a.x, b.x),
          max: Math.max(a.x, b.x),
          pointIdxStart: i,
          pointIdxEnd: i + 1,
        })
      }
    }
  }

  // Step 2: Group segments by axis, then find overlapping clusters
  // Sort by axis + coord for efficient grouping
  const hSegs = segments.filter(s => s.axis === 'h').sort((a, b) => a.coord - b.coord)
  const vSegs = segments.filter(s => s.axis === 'v').sort((a, b) => a.coord - b.coord)

  // Collect offset adjustments per pipe per point
  // Map<pipeId, Map<pointIdx, {dx, dy}>>
  const adjustments = new Map<string, Map<number, { dx: number; dy: number }>>()

  function applyBundleOffsets(segs: OrthoSegment[], axis: 'h' | 'v') {
    // Find clusters of segments at similar coordinates with overlapping ranges
    let i = 0
    while (i < segs.length) {
      // Collect all segments within tolerance of segs[i].coord
      const cluster: OrthoSegment[] = [segs[i]!]
      let j = i + 1
      while (j < segs.length && Math.abs(segs[j]!.coord - segs[i]!.coord) <= tolerance) {
        cluster.push(segs[j]!)
        j++
      }

      if (cluster.length >= 2) {
        // Find segments with overlapping ranges (different pipes)
        // Group by overlapping ranges using pairwise check
        const overlapping = findOverlappingGroups(cluster)
        for (const group of overlapping) {
          if (group.length < 2) continue
          // Ensure we only bundle segments from different pipes
          const uniquePipes = new Set(group.map(s => s.pipeId))
          if (uniquePipes.size < 2) continue

          // Calculate offsets: center the bundle around the original coord
          const maxSw = Math.max(...group.map(s => {
            const pipe = pipes.find(p => p.id === s.pipeId)
            return pipe?.strokeWidth ?? 2
          }))
          const spacing = maxSw + gap

          for (let k = 0; k < group.length; k++) {
            const seg = group[k]!
            const offset = (k - (group.length - 1) / 2) * spacing

            if (!adjustments.has(seg.pipeId)) {
              adjustments.set(seg.pipeId, new Map())
            }
            const pipeAdj = adjustments.get(seg.pipeId)!

            // For horizontal segments, offset in Y; for vertical, offset in X
            const delta = axis === 'h' ? { dx: 0, dy: offset } : { dx: offset, dy: 0 }

            // Apply to both endpoints of this segment
            for (const idx of [seg.pointIdxStart, seg.pointIdxEnd]) {
              const existing = pipeAdj.get(idx)
              if (existing) {
                // Accumulate — a point may belong to multiple segments
                // Take the larger absolute offset per axis
                if (Math.abs(delta.dx) > Math.abs(existing.dx)) existing.dx = delta.dx
                if (Math.abs(delta.dy) > Math.abs(existing.dy)) existing.dy = delta.dy
              } else {
                pipeAdj.set(idx, { ...delta })
              }
            }
          }
        }
      }

      i = j
    }
  }

  applyBundleOffsets(hSegs, 'h')
  applyBundleOffsets(vSegs, 'v')

  // Step 3: Build adjusted point arrays
  const result = new Map<string, Point[]>()
  for (const [pipeId, pipeAdj] of adjustments) {
    const pipe = pipes.find(p => p.id === pipeId)
    if (!pipe) continue
    const adjusted = pipe.points.map((pt, idx) => {
      const adj = pipeAdj.get(idx)
      if (!adj) return pt
      return { x: pt.x + adj.dx, y: pt.y + adj.dy }
    })
    result.set(pipeId, adjusted)
  }

  return result
}

/** Find groups of segments with overlapping ranges */
function findOverlappingGroups(segments: OrthoSegment[]): OrthoSegment[][] {
  if (segments.length <= 1) return [segments]

  // Sort by min coordinate
  const sorted = [...segments].sort((a, b) => a.min - b.min)
  const groups: OrthoSegment[][] = []
  let current: OrthoSegment[] = [sorted[0]!]
  let currentMax = sorted[0]!.max

  for (let i = 1; i < sorted.length; i++) {
    const seg = sorted[i]!
    if (seg.min < currentMax) {
      // Overlaps with current group
      current.push(seg)
      currentMax = Math.max(currentMax, seg.max)
    } else {
      // Start new group
      if (current.length >= 2) groups.push(current)
      current = [seg]
      currentMax = seg.max
    }
  }
  if (current.length >= 2) groups.push(current)

  return groups
}
