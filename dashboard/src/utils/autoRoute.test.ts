/**
 * Tests for A* auto-routing with binary heap optimization (#7.2)
 */
import { describe, it, expect } from 'vitest'
import { autoRoute } from './autoRoute'

describe('autoRoute', () => {
  it('should route between two ports with no obstacles', () => {
    const path = autoRoute(
      { x: 100, y: 100, direction: 'right' },
      { x: 300, y: 100, direction: 'left' },
      []
    )
    expect(path.length).toBeGreaterThanOrEqual(2)
    expect(path[0]).toEqual({ x: 100, y: 100 })
    expect(path[path.length - 1]).toEqual({ x: 300, y: 100 })
  })

  it('should produce an orthogonal path (only horizontal/vertical segments)', () => {
    const path = autoRoute(
      { x: 50, y: 50, direction: 'right' },
      { x: 250, y: 200, direction: 'left' },
      []
    )
    for (let i = 1; i < path.length; i++) {
      const prev = path[i - 1]!
      const curr = path[i]!
      const isHorizontal = prev.y === curr.y
      const isVertical = prev.x === curr.x
      expect(isHorizontal || isVertical).toBe(true)
    }
  })

  it('should route around a single obstacle', () => {
    const obstacle = { x: 150, y: 50, width: 100, height: 100 }
    const path = autoRoute(
      { x: 100, y: 100, direction: 'right' },
      { x: 300, y: 100, direction: 'left' },
      [obstacle]
    )
    expect(path.length).toBeGreaterThanOrEqual(2)
    // Path should not cross through the obstacle
    for (let i = 1; i < path.length; i++) {
      const prev = path[i - 1]!
      const curr = path[i]!
      // Check midpoint of each segment is not inside obstacle
      const mx = (prev.x + curr.x) / 2
      const my = (prev.y + curr.y) / 2
      const insideX = mx > obstacle.x && mx < obstacle.x + obstacle.width
      const insideY = my > obstacle.y && my < obstacle.y + obstacle.height
      // At least one axis should be outside the obstacle
      if (insideX && insideY) {
        // Allow points on the edge
        expect(
          mx === obstacle.x || mx === obstacle.x + obstacle.width ||
          my === obstacle.y || my === obstacle.y + obstacle.height
        ).toBe(true)
      }
    }
  })

  it('should handle same-y ports (horizontal line)', () => {
    const path = autoRoute(
      { x: 0, y: 100, direction: 'right' },
      { x: 200, y: 100, direction: 'left' },
      []
    )
    expect(path[0]!.y).toBe(100)
    expect(path[path.length - 1]!.y).toBe(100)
  })

  it('should handle same-x ports (vertical line)', () => {
    const path = autoRoute(
      { x: 100, y: 0, direction: 'bottom' },
      { x: 100, y: 200, direction: 'top' },
      []
    )
    expect(path[0]!.x).toBe(100)
    expect(path[path.length - 1]!.x).toBe(100)
  })

  it('should handle multiple obstacles', () => {
    const obstacles = [
      { x: 100, y: 50, width: 60, height: 60 },
      { x: 200, y: 50, width: 60, height: 60 },
    ]
    const path = autoRoute(
      { x: 50, y: 80, direction: 'right' },
      { x: 310, y: 80, direction: 'left' },
      obstacles
    )
    expect(path.length).toBeGreaterThanOrEqual(2)
    expect(path[0]).toEqual({ x: 50, y: 80 })
    expect(path[path.length - 1]).toEqual({ x: 310, y: 80 })
  })

  it('should simplify collinear points', () => {
    const path = autoRoute(
      { x: 0, y: 50, direction: 'right' },
      { x: 400, y: 50, direction: 'left' },
      []
    )
    // For a straight horizontal route with no obstacles, path should be minimal
    // (start, maybe stubs, end) - no unnecessary intermediate points on the same line
    for (let i = 2; i < path.length; i++) {
      const a = path[i - 2]!
      const b = path[i - 1]!
      const c = path[i]!
      const allSameX = a.x === b.x && b.x === c.x
      const allSameY = a.y === b.y && b.y === c.y
      expect(allSameX || allSameY).toBe(false) // no three collinear points
    }
  })

  it('should produce a fallback path when no clear route exists', () => {
    // Completely boxed in - should still return something
    const obstacles = [
      { x: 80, y: 80, width: 240, height: 40 },
    ]
    const path = autoRoute(
      { x: 100, y: 100, direction: 'right' },
      { x: 300, y: 100, direction: 'left' },
      obstacles
    )
    expect(path.length).toBeGreaterThanOrEqual(2)
  })
})
