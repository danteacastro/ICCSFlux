/**
 * Tests for shared pipe rendering utilities (#7.5)
 */
import { describe, it, expect } from 'vitest'
import { distanceToSegment, PIPE_DASH_PATTERNS } from './pipeRendering'

describe('distanceToSegment', () => {
  it('should return 0 for a point on the segment', () => {
    expect(distanceToSegment(5, 0, 0, 0, 10, 0)).toBeCloseTo(0)
  })

  it('should return distance for a point perpendicular to segment', () => {
    // Point (5, 3) perpendicular distance to segment (0,0)→(10,0) = 3
    expect(distanceToSegment(5, 3, 0, 0, 10, 0)).toBeCloseTo(3)
  })

  it('should return distance to nearest endpoint when projection is outside segment', () => {
    // Point (-5, 0) is before the segment (0,0)→(10,0)
    expect(distanceToSegment(-5, 0, 0, 0, 10, 0)).toBeCloseTo(5)
    // Point (15, 0) is after the segment
    expect(distanceToSegment(15, 0, 0, 0, 10, 0)).toBeCloseTo(5)
  })

  it('should handle vertical segments', () => {
    expect(distanceToSegment(3, 5, 0, 0, 0, 10)).toBeCloseTo(3)
  })

  it('should handle zero-length segments', () => {
    expect(distanceToSegment(3, 4, 0, 0, 0, 0)).toBeCloseTo(5) // distance to origin
  })

  it('should handle diagonal segments', () => {
    // Point (0, 1) to segment (0,0)→(1,1), distance = 1/sqrt(2)
    const d = distanceToSegment(0, 1, 0, 0, 1, 1)
    expect(d).toBeCloseTo(Math.sqrt(2) / 2)
  })
})

describe('PIPE_DASH_PATTERNS', () => {
  it('should have solid pattern as empty string', () => {
    expect(PIPE_DASH_PATTERNS.solid).toBe('')
  })

  it('should have standard dash patterns', () => {
    expect(PIPE_DASH_PATTERNS.dashed).toBe('8,4')
    expect(PIPE_DASH_PATTERNS.dotted).toBe('2,4')
    expect(PIPE_DASH_PATTERNS.dashDot).toBe('8,4,2,4')
    expect(PIPE_DASH_PATTERNS.longDash).toBe('16,6')
  })
})
