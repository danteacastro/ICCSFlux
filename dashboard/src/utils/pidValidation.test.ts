/**
 * Tests for P&ID connection validation (#5.2)
 */
import { describe, it, expect } from 'vitest'
import { validatePidLayer } from './pidValidation'
import type { PidLayerData } from '../types'

function makeLayer(overrides: Partial<PidLayerData> = {}): PidLayerData {
  return {
    symbols: [],
    pipes: [],
    textAnnotations: [],
    guides: [],
    groups: [],
    layerInfos: [],
    ...overrides,
  } as PidLayerData
}

describe('validatePidLayer', () => {
  it('should return no issues for an empty layer', () => {
    const issues = validatePidLayer(makeLayer())
    expect(issues).toHaveLength(0)
  })

  it('should detect dangling pipes with no connections on either end', () => {
    const layer = makeLayer({
      pipes: [{
        id: 'pipe-1',
        points: [{ x: 0, y: 0 }, { x: 100, y: 100 }],
        color: '#60a5fa',
        strokeWidth: 2,
      }] as any[],
    })
    const issues = validatePidLayer(layer)
    const dangling = issues.filter(i => i.type === 'dangling-pipe')
    expect(dangling.length).toBeGreaterThanOrEqual(1)
    expect(dangling[0]!.severity).toBe('error')
  })

  it('should detect dangling pipe with only start connected', () => {
    const layer = makeLayer({
      symbols: [{
        id: 'sym-1', type: 'solenoidValve', x: 0, y: 0, width: 60, height: 60,
      }] as any[],
      pipes: [{
        id: 'pipe-1',
        points: [{ x: 30, y: 30 }, { x: 200, y: 200 }],
        startSymbolId: 'sym-1',
        startPortId: 'inlet',
        color: '#60a5fa',
        strokeWidth: 2,
      }] as any[],
    })
    const issues = validatePidLayer(layer)
    const dangling = issues.filter(i => i.type === 'dangling-pipe')
    expect(dangling.length).toBeGreaterThanOrEqual(1)
    expect(dangling[0]!.severity).toBe('warning')
    expect(dangling[0]!.message).toContain('end')
  })

  it('should detect dangling pipe with only end connected', () => {
    const layer = makeLayer({
      symbols: [{
        id: 'sym-1', type: 'solenoidValve', x: 200, y: 200, width: 60, height: 60,
      }] as any[],
      pipes: [{
        id: 'pipe-1',
        points: [{ x: 0, y: 0 }, { x: 230, y: 230 }],
        endSymbolId: 'sym-1',
        endPortId: 'outlet',
        color: '#60a5fa',
        strokeWidth: 2,
      }] as any[],
    })
    const issues = validatePidLayer(layer)
    const dangling = issues.filter(i => i.type === 'dangling-pipe')
    expect(dangling.length).toBeGreaterThanOrEqual(1)
    expect(dangling[0]!.message).toContain('start')
  })

  it('should not flag fully connected pipes as dangling', () => {
    const layer = makeLayer({
      symbols: [
        { id: 'sym-1', type: 'solenoidValve', x: 0, y: 0, width: 60, height: 60 },
        { id: 'sym-2', type: 'solenoidValve', x: 200, y: 0, width: 60, height: 60 },
      ] as any[],
      pipes: [{
        id: 'pipe-1',
        points: [{ x: 60, y: 30 }, { x: 200, y: 30 }],
        startSymbolId: 'sym-1',
        startPortId: 'outlet',
        endSymbolId: 'sym-2',
        endPortId: 'inlet',
        color: '#60a5fa',
        strokeWidth: 2,
      }] as any[],
    })
    const issues = validatePidLayer(layer)
    const dangling = issues.filter(i => i.type === 'dangling-pipe')
    expect(dangling).toHaveLength(0)
  })

  it('should return unique issue IDs', () => {
    const layer = makeLayer({
      pipes: [
        { id: 'p1', points: [{ x: 0, y: 0 }, { x: 10, y: 10 }] },
        { id: 'p2', points: [{ x: 20, y: 20 }, { x: 30, y: 30 }] },
      ] as any[],
    })
    const issues = validatePidLayer(layer)
    const ids = issues.map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
