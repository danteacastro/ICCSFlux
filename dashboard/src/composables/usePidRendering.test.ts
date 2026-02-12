/**
 * Tests for P&ID rendering utilities (pure functions)
 */
import { describe, it, expect } from 'vitest'
import {
  parseIsaLetters,
  parseIsaTagNumber,
  isInstrumentSymbol,
  getSymbolSvg,
  segmentIntersection,
  distanceToSegment,
  getPipeDisplayLabel,
} from './usePidRendering'

describe('ISA-5.1 Instrument Parsing', () => {
  it('should parse ISA letters from label', () => {
    expect(parseIsaLetters('PT-101')).toBe('PT')
    expect(parseIsaLetters('FIC-200A')).toBe('FIC')
    expect(parseIsaLetters('TE-001')).toBe('TE')
    expect(parseIsaLetters('LT_500')).toBe('LT')
  })

  it('should return empty string for non-ISA labels', () => {
    expect(parseIsaLetters('MyLabel')).toBe('')
    expect(parseIsaLetters('123')).toBe('')
    expect(parseIsaLetters('')).toBe('')
  })

  it('should parse tag numbers', () => {
    expect(parseIsaTagNumber('PT-101')).toBe('101')
    expect(parseIsaTagNumber('FIC-200A')).toBe('200A')
    expect(parseIsaTagNumber('TE_001')).toBe('001')
  })

  it('should return full label if no separator found', () => {
    expect(parseIsaTagNumber('NoTag')).toBe('NoTag')
  })

  it('should identify instrument symbols', () => {
    expect(isInstrumentSymbol('pressureTransducer')).toBe(true)
    expect(isInstrumentSymbol('flowMeter')).toBe(true)
    expect(isInstrumentSymbol('solenoidValve')).toBe(false)
    expect(isInstrumentSymbol('centrifugalPump')).toBe(false)
  })
})

describe('getSymbolSvg', () => {
  it('should return an SVG string for known symbol types', () => {
    const svg = getSymbolSvg('solenoidValve')
    expect(svg).toContain('<svg')
  })

  it('should return fallback for unknown type', () => {
    const svg = getSymbolSvg('nonexistent-type')
    expect(svg).toContain('<svg') // falls back to solenoidValve
  })

  it('should return custom symbol SVG when provided', () => {
    const custom = { 'my-custom': { svg: '<svg>custom</svg>' } }
    const svg = getSymbolSvg('my-custom', custom)
    expect(svg).toBe('<svg>custom</svg>')
  })

  it('should prefer custom symbols over built-in', () => {
    const custom = { solenoidValve: { svg: '<svg>overridden</svg>' } }
    const svg = getSymbolSvg('solenoidValve', custom)
    expect(svg).toBe('<svg>overridden</svg>')
  })
})

describe('segmentIntersection', () => {
  it('should detect perpendicular intersection', () => {
    const result = segmentIntersection(
      { x: 0, y: 5 }, { x: 10, y: 5 },
      { x: 5, y: 0 }, { x: 5, y: 10 }
    )
    expect(result).not.toBeNull()
    expect(result!.x).toBeCloseTo(5)
    expect(result!.y).toBeCloseTo(5)
  })

  it('should return null for parallel segments', () => {
    const result = segmentIntersection(
      { x: 0, y: 0 }, { x: 10, y: 0 },
      { x: 0, y: 5 }, { x: 10, y: 5 }
    )
    expect(result).toBeNull()
  })

  it('should return null for non-intersecting segments', () => {
    const result = segmentIntersection(
      { x: 0, y: 0 }, { x: 3, y: 0 },
      { x: 6, y: 1 }, { x: 10, y: 1 }
    )
    expect(result).toBeNull()
  })
})

describe('distanceToSegment', () => {
  it('should compute correct perpendicular distance', () => {
    expect(distanceToSegment(5, 4, 0, 0, 10, 0)).toBeCloseTo(4)
  })

  it('should compute distance to endpoint for projections outside segment', () => {
    expect(distanceToSegment(-3, 0, 0, 0, 10, 0)).toBeCloseTo(3)
  })
})

describe('getPipeDisplayLabel', () => {
  it('should return explicit label when set', () => {
    const pipe = { label: 'CW-101', medium: 'coolingWater' } as any
    expect(getPipeDisplayLabel(pipe)).toBe('CW-101')
  })

  it('should return medium abbreviation when no label', () => {
    const pipe = { medium: 'steam' } as any
    expect(getPipeDisplayLabel(pipe)).toBe('STM')
  })

  it('should return empty string when no label or medium', () => {
    const pipe = {} as any
    expect(getPipeDisplayLabel(pipe)).toBe('')
  })
})
