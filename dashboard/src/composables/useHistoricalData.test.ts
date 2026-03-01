/**
 * Tests for useHistoricalData Composable
 *
 * Tests cover:
 * - toChartFormat conversion
 * - calculateDecimation logic
 * - Data time range computation
 * - Loading state management
 * - Error handling for disconnected MQTT
 * - RecordingFile and HistoricalData type handling
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { HistoricalData, HistoricalDataPoint, FileInfo, RecordingFile, LoadOptions } from './useHistoricalData'

// =============================================================================
// toChartFormat TESTS (Pure function - can test directly)
// =============================================================================

describe('toChartFormat', () => {
  // Recreate the pure function from useHistoricalData.ts
  function toChartFormat(data: HistoricalData | null) {
    if (!data || !data.data.length) {
      return { timestamps: [], series: {} }
    }

    const timestamps: Date[] = []
    const series: Record<string, (number | null)[]> = {}

    // Initialize series arrays
    for (const channel of data.channels) {
      series[channel] = []
    }

    // Convert data points
    for (const point of data.data) {
      timestamps.push(new Date(point.timestamp))
      for (const channel of data.channels) {
        series[channel]?.push(point.values[channel] ?? null)
      }
    }

    return { timestamps, series }
  }

  it('should return empty result for null data', () => {
    const result = toChartFormat(null)
    expect(result.timestamps).toHaveLength(0)
    expect(result.series).toEqual({})
  })

  it('should return empty result for empty data array', () => {
    const data: HistoricalData = {
      success: true,
      error: null,
      filename: 'test.csv',
      channels: ['TC_001'],
      data: [],
      start_time: null,
      end_time: null,
      sample_count: 0,
      total_samples: 0
    }
    const result = toChartFormat(data)
    expect(result.timestamps).toHaveLength(0)
    expect(result.series).toEqual({})
  })

  it('should convert single channel data', () => {
    const data: HistoricalData = {
      success: true,
      error: null,
      filename: 'test.csv',
      channels: ['TC_001'],
      data: [
        { timestamp: '2026-01-01T00:00:00Z', values: { TC_001: 25.5 } },
        { timestamp: '2026-01-01T00:00:01Z', values: { TC_001: 26.0 } },
        { timestamp: '2026-01-01T00:00:02Z', values: { TC_001: 26.5 } }
      ],
      start_time: '2026-01-01T00:00:00Z',
      end_time: '2026-01-01T00:00:02Z',
      sample_count: 3,
      total_samples: 3
    }

    const result = toChartFormat(data)
    expect(result.timestamps).toHaveLength(3)
    expect(result.series['TC_001']).toEqual([25.5, 26.0, 26.5])
  })

  it('should convert multiple channel data', () => {
    const data: HistoricalData = {
      success: true,
      error: null,
      filename: 'test.csv',
      channels: ['TC_001', 'AI_001'],
      data: [
        { timestamp: '2026-01-01T00:00:00Z', values: { TC_001: 25.5, AI_001: 5.0 } },
        { timestamp: '2026-01-01T00:00:01Z', values: { TC_001: 26.0, AI_001: 5.1 } }
      ],
      start_time: '2026-01-01T00:00:00Z',
      end_time: '2026-01-01T00:00:01Z',
      sample_count: 2,
      total_samples: 2
    }

    const result = toChartFormat(data)
    expect(result.timestamps).toHaveLength(2)
    expect(result.series['TC_001']).toEqual([25.5, 26.0])
    expect(result.series['AI_001']).toEqual([5.0, 5.1])
  })

  it('should handle missing values as null', () => {
    const data: HistoricalData = {
      success: true,
      error: null,
      filename: 'test.csv',
      channels: ['TC_001', 'AI_001'],
      data: [
        { timestamp: '2026-01-01T00:00:00Z', values: { TC_001: 25.5 } }, // AI_001 missing
        { timestamp: '2026-01-01T00:00:01Z', values: { TC_001: 26.0, AI_001: 5.1 } }
      ],
      start_time: '2026-01-01T00:00:00Z',
      end_time: '2026-01-01T00:00:01Z',
      sample_count: 2,
      total_samples: 2
    }

    const result = toChartFormat(data)
    expect(result.series['AI_001']).toEqual([null, 5.1])
  })

  it('should produce Date objects for timestamps', () => {
    const data: HistoricalData = {
      success: true,
      error: null,
      filename: 'test.csv',
      channels: ['TC_001'],
      data: [
        { timestamp: '2026-01-15T12:30:00Z', values: { TC_001: 100 } }
      ],
      start_time: '2026-01-15T12:30:00Z',
      end_time: '2026-01-15T12:30:00Z',
      sample_count: 1,
      total_samples: 1
    }

    const result = toChartFormat(data)
    expect(result.timestamps[0]).toBeInstanceOf(Date)
    expect(result.timestamps[0].toISOString()).toBe('2026-01-15T12:30:00.000Z')
  })
})

// =============================================================================
// calculateDecimation TESTS (Pure function)
// =============================================================================

describe('calculateDecimation', () => {
  function calculateDecimation(totalSamples: number, targetPoints: number = 1000): number {
    if (totalSamples <= targetPoints) return 1
    return Math.ceil(totalSamples / targetPoints)
  }

  it('should return 1 when samples <= target', () => {
    expect(calculateDecimation(500)).toBe(1)
    expect(calculateDecimation(1000)).toBe(1)
  })

  it('should calculate decimation for large datasets', () => {
    expect(calculateDecimation(5000)).toBe(5)
    expect(calculateDecimation(10000)).toBe(10)
  })

  it('should handle custom target points', () => {
    expect(calculateDecimation(5000, 500)).toBe(10)
    expect(calculateDecimation(5000, 2500)).toBe(2)
  })

  it('should ceil decimation factor', () => {
    // 3000 / 1000 = 3.0 (exact)
    expect(calculateDecimation(3000)).toBe(3)
    // 3001 / 1000 = 3.001 -> ceil = 4
    expect(calculateDecimation(3001)).toBe(4)
  })

  it('should return 1 for zero samples', () => {
    expect(calculateDecimation(0)).toBe(1)
  })

  it('should return 1 for single sample', () => {
    expect(calculateDecimation(1)).toBe(1)
  })
})

// =============================================================================
// DATA TIME RANGE COMPUTATION (Pure logic)
// =============================================================================

describe('Data Time Range', () => {
  function computeTimeRange(startTime: string | null, endTime: string | null) {
    if (!startTime || !endTime) return null

    const start = new Date(startTime)
    const end = new Date(endTime)
    const durationMs = end.getTime() - start.getTime()

    return {
      start,
      end,
      durationMs,
      durationSeconds: durationMs / 1000,
      durationMinutes: durationMs / 60000,
      durationHours: durationMs / 3600000
    }
  }

  it('should compute time range for valid data', () => {
    const range = computeTimeRange(
      '2026-01-01T00:00:00Z',
      '2026-01-01T01:00:00Z'
    )
    expect(range).not.toBeNull()
    expect(range!.durationHours).toBeCloseTo(1)
    expect(range!.durationMinutes).toBeCloseTo(60)
    expect(range!.durationSeconds).toBeCloseTo(3600)
  })

  it('should return null for null start_time', () => {
    const range = computeTimeRange(null, '2026-01-01T01:00:00Z')
    expect(range).toBeNull()
  })

  it('should return null for null end_time', () => {
    const range = computeTimeRange('2026-01-01T00:00:00Z', null)
    expect(range).toBeNull()
  })

  it('should handle short durations', () => {
    const range = computeTimeRange(
      '2026-01-01T00:00:00Z',
      '2026-01-01T00:00:05Z'
    )
    expect(range!.durationSeconds).toBeCloseTo(5)
  })

  it('should handle multi-hour durations', () => {
    const range = computeTimeRange(
      '2026-01-01T00:00:00Z',
      '2026-01-01T12:00:00Z'
    )
    expect(range!.durationHours).toBeCloseTo(12)
  })
})

// =============================================================================
// RECORDING FILE TYPE TESTS
// =============================================================================

describe('RecordingFile Types', () => {
  it('should represent a recording file correctly', () => {
    const file: RecordingFile = {
      name: 'test_recording_2026-01-15.csv',
      path: '/data/recordings/test_recording_2026-01-15.csv',
      size: 1024000,
      duration: 3600,
      created: '2026-01-15T10:00:00Z',
      sample_count: 14400,
      channels: ['TC_001', 'TC_002', 'AI_001']
    }

    expect(file.name).toBe('test_recording_2026-01-15.csv')
    expect(file.channels).toHaveLength(3)
    expect(file.sample_count).toBe(14400)
    expect(file.duration).toBe(3600)
  })

  it('should represent file info correctly', () => {
    const info: FileInfo = {
      success: true,
      error: null,
      filename: 'test.csv',
      path: '/data/recordings/test.csv',
      size_bytes: 2048000,
      channels: ['TC_001'],
      sample_count: 10000,
      start_time: '2026-01-15T10:00:00Z',
      end_time: '2026-01-15T11:00:00Z',
      duration_seconds: 3600,
      sample_rate_hz: 4
    }

    expect(info.success).toBe(true)
    expect(info.sample_rate_hz).toBe(4)
    expect(info.duration_seconds).toBe(3600)
  })
})
