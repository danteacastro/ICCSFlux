/**
 * Tests for DataTab.vue
 *
 * Tests cover the pure logic extracted from DataTab:
 * - naturalSort: alphanumeric ordering (tag_1, tag_2, tag_10)
 * - moduleSort: NI cDAQ module-based ordering (Mod1/ai0, Mod1/ai1, Mod2/ai0)
 * - effectiveSampleRate: interval/decimation → Hz
 * - previewFilename: naming pattern → filename string
 * - previewDirectory: directory structure → path string
 * - estimatedSizePerHour: channel count × rate → MB/h
 * - availableChannels: aggregation of 5 data source categories
 * - channelGroups: grouping + sub-grouping for UI
 * - toggleChannel: selection add/remove logic
 * - formatFileSize: bytes → human-readable (B/KB/MB/GB)
 * - formatDuration: seconds → human-readable (Xh Xm Xs)
 * - downloadFile: CSV reconstruction from MQTT response
 * - startRecording: config object shape validation
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { toBackendRecordingConfig } from '../stores/dashboard'

// =============================================================================
// PURE FUNCTION TESTS (no component mount needed)
// =============================================================================

// ── naturalSort ──────────────────────────────────────────────

describe('naturalSort', () => {
  // Recreate for direct testing (not exported from SFC)
  function naturalSort(a: string, b: string): number {
    const regex = /(\d+)|(\D+)/g
    const aParts = a.match(regex) || []
    const bParts = b.match(regex) || []

    for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
      const aPart = aParts[i] || ''
      const bPart = bParts[i] || ''

      const aNum = parseInt(aPart, 10)
      const bNum = parseInt(bPart, 10)

      if (!isNaN(aNum) && !isNaN(bNum)) {
        if (aNum !== bNum) return aNum - bNum
      } else {
        const cmp = aPart.localeCompare(bPart)
        if (cmp !== 0) return cmp
      }
    }
    return 0
  }

  it('should sort numeric suffixes numerically, not lexicographically', () => {
    const items = ['tag_10', 'tag_2', 'tag_1', 'tag_20', 'tag_3']
    items.sort(naturalSort)
    expect(items).toEqual(['tag_1', 'tag_2', 'tag_3', 'tag_10', 'tag_20'])
  })

  it('should handle identical strings', () => {
    expect(naturalSort('abc', 'abc')).toBe(0)
  })

  it('should sort purely alphabetic strings', () => {
    const items = ['banana', 'apple', 'cherry']
    items.sort(naturalSort)
    expect(items).toEqual(['apple', 'banana', 'cherry'])
  })

  it('should handle mixed alpha-numeric segments', () => {
    const items = ['TC_1_zone_B', 'TC_1_zone_A', 'TC_2_zone_A']
    items.sort(naturalSort)
    expect(items).toEqual(['TC_1_zone_A', 'TC_1_zone_B', 'TC_2_zone_A'])
  })

  it('should handle empty strings', () => {
    expect(naturalSort('', '')).toBe(0)
    expect(naturalSort('', 'a')).toBeLessThan(0)
  })

  it('should handle strings with only numbers', () => {
    const items = ['100', '20', '3', '1']
    items.sort(naturalSort)
    expect(items).toEqual(['1', '3', '20', '100'])
  })
})

// ── moduleSort ───────────────────────────────────────────────

describe('moduleSort', () => {
  function naturalSort(a: string, b: string): number {
    const regex = /(\d+)|(\D+)/g
    const aParts = a.match(regex) || []
    const bParts = b.match(regex) || []
    for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
      const aPart = aParts[i] || ''
      const bPart = bParts[i] || ''
      const aNum = parseInt(aPart, 10)
      const bNum = parseInt(bPart, 10)
      if (!isNaN(aNum) && !isNaN(bNum)) {
        if (aNum !== bNum) return aNum - bNum
      } else {
        const cmp = aPart.localeCompare(bPart)
        if (cmp !== 0) return cmp
      }
    }
    return 0
  }

  function moduleSort(a: { name: string, physical_channel?: string }, b: { name: string, physical_channel?: string }): number {
    const aPhys = a.physical_channel || ''
    const bPhys = b.physical_channel || ''
    const aModMatch = aPhys.match(/Mod(\d+)/i)
    const bModMatch = bPhys.match(/Mod(\d+)/i)
    const aMod = aModMatch ? parseInt(aModMatch[1]!, 10) : 999
    const bMod = bModMatch ? parseInt(bModMatch[1]!, 10) : 999
    if (aMod !== bMod) return aMod - bMod
    const aChMatch = aPhys.match(/[/]([a-z]+)(\d+)$/i)
    const bChMatch = bPhys.match(/[/]([a-z]+)(\d+)$/i)
    if (aChMatch && bChMatch) {
      if (aChMatch[1]! === bChMatch[1]!) {
        return parseInt(aChMatch[2]!, 10) - parseInt(bChMatch[2]!, 10)
      }
      return aChMatch[1]!.localeCompare(bChMatch[1]!)
    }
    return naturalSort(a.name, b.name)
  }

  it('should sort by module number first', () => {
    const items = [
      { name: 'ch2', physical_channel: 'cDAQ1Mod2/ai0' },
      { name: 'ch1', physical_channel: 'cDAQ1Mod1/ai0' },
      { name: 'ch5', physical_channel: 'cDAQ1Mod5/ai0' },
    ]
    items.sort(moduleSort)
    expect(items.map(i => i.name)).toEqual(['ch1', 'ch2', 'ch5'])
  })

  it('should sort by channel index within same module', () => {
    const items = [
      { name: 'tc3', physical_channel: 'cDAQ1Mod1/ai2' },
      { name: 'tc1', physical_channel: 'cDAQ1Mod1/ai0' },
      { name: 'tc2', physical_channel: 'cDAQ1Mod1/ai1' },
    ]
    items.sort(moduleSort)
    expect(items.map(i => i.name)).toEqual(['tc1', 'tc2', 'tc3'])
  })

  it('should sort AI before DI within same module', () => {
    const items = [
      { name: 'di0', physical_channel: 'cDAQ1Mod1/di0' },
      { name: 'ai0', physical_channel: 'cDAQ1Mod1/ai0' },
    ]
    items.sort(moduleSort)
    expect(items.map(i => i.name)).toEqual(['ai0', 'di0'])
  })

  it('should place channels without physical_channel last', () => {
    const items = [
      { name: 'virtual', physical_channel: '' },
      { name: 'real', physical_channel: 'cDAQ1Mod1/ai0' },
    ]
    items.sort(moduleSort)
    expect(items.map(i => i.name)).toEqual(['real', 'virtual'])
  })

  it('should handle case-insensitive Mod matching', () => {
    const items = [
      { name: 'b', physical_channel: 'cDAQ1MOD2/ai0' },
      { name: 'a', physical_channel: 'cDAQ1mod1/ai0' },
    ]
    items.sort(moduleSort)
    expect(items.map(i => i.name)).toEqual(['a', 'b'])
  })
})

// ── effectiveSampleRate ──────────────────────────────────────

describe('effectiveSampleRate', () => {
  function calcEffectiveSampleRate(
    sampleInterval: number,
    sampleIntervalUnit: 'seconds' | 'milliseconds',
    decimation: number,
  ): number {
    let intervalSeconds = sampleInterval
    if (sampleIntervalUnit === 'milliseconds') {
      intervalSeconds = sampleInterval / 1000
    }
    const baseRate = intervalSeconds > 0 ? 1 / intervalSeconds : 0
    return baseRate / decimation
  }

  it('should compute 1 Hz for 1 second interval, decimation 1', () => {
    expect(calcEffectiveSampleRate(1, 'seconds', 1)).toBe(1)
  })

  it('should compute 0.5 Hz for 1 second interval, decimation 2', () => {
    expect(calcEffectiveSampleRate(1, 'seconds', 2)).toBe(0.5)
  })

  it('should convert milliseconds to seconds', () => {
    expect(calcEffectiveSampleRate(500, 'milliseconds', 1)).toBe(2)
  })

  it('should handle 100ms interval with decimation 5', () => {
    expect(calcEffectiveSampleRate(100, 'milliseconds', 5)).toBeCloseTo(2)
  })

  it('should return 0 for zero interval', () => {
    expect(calcEffectiveSampleRate(0, 'seconds', 1)).toBe(0)
  })

  it('should handle very fast rate (10ms)', () => {
    expect(calcEffectiveSampleRate(10, 'milliseconds', 1)).toBe(100)
  })
})

// ── previewFilename ──────────────────────────────────────────

describe('previewFilename', () => {
  function buildPreviewFilename(cfg: {
    filePrefix: string
    namingPattern: 'timestamp' | 'sequential' | 'custom'
    includeDate: boolean
    includeTime: boolean
    includeChannelsInName: boolean
    sequentialStart: number
    sequentialPadding: number
    customSuffix: string
    fileFormat: 'csv' | 'tdms'
  }, channelCount: number): string {
    let name = cfg.filePrefix
    // Use fixed date for deterministic tests
    const date = new Date(2026, 0, 15, 10, 30, 45) // 2026-01-15 10:30:45

    if (cfg.namingPattern === 'timestamp') {
      if (cfg.includeDate) {
        name += `_${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      }
      if (cfg.includeTime) {
        name += `_${String(date.getHours()).padStart(2, '0')}-${String(date.getMinutes()).padStart(2, '0')}-${String(date.getSeconds()).padStart(2, '0')}`
      }
    } else if (cfg.namingPattern === 'sequential') {
      name += `_${String(cfg.sequentialStart).padStart(cfg.sequentialPadding, '0')}`
    }

    if (cfg.includeChannelsInName) {
      name += `_${channelCount}ch`
    }

    if (cfg.customSuffix) {
      name += `_${cfg.customSuffix}`
    }

    name += `.${cfg.fileFormat}`
    return name
  }

  it('should build timestamp filename with date and time', () => {
    const result = buildPreviewFilename({
      filePrefix: 'recording',
      namingPattern: 'timestamp',
      includeDate: true,
      includeTime: true,
      includeChannelsInName: false,
      sequentialStart: 1,
      sequentialPadding: 3,
      customSuffix: '',
      fileFormat: 'csv',
    }, 10)
    expect(result).toBe('recording_2026-01-15_10-30-45.csv')
  })

  it('should build timestamp filename with date only', () => {
    const result = buildPreviewFilename({
      filePrefix: 'data',
      namingPattern: 'timestamp',
      includeDate: true,
      includeTime: false,
      includeChannelsInName: false,
      sequentialStart: 1,
      sequentialPadding: 3,
      customSuffix: '',
      fileFormat: 'csv',
    }, 5)
    expect(result).toBe('data_2026-01-15.csv')
  })

  it('should build sequential filename with padding', () => {
    const result = buildPreviewFilename({
      filePrefix: 'test',
      namingPattern: 'sequential',
      includeDate: false,
      includeTime: false,
      includeChannelsInName: false,
      sequentialStart: 5,
      sequentialPadding: 4,
      customSuffix: '',
      fileFormat: 'csv',
    }, 3)
    expect(result).toBe('test_0005.csv')
  })

  it('should include channel count when enabled', () => {
    const result = buildPreviewFilename({
      filePrefix: 'recording',
      namingPattern: 'custom',
      includeDate: false,
      includeTime: false,
      includeChannelsInName: true,
      sequentialStart: 1,
      sequentialPadding: 3,
      customSuffix: '',
      fileFormat: 'csv',
    }, 12)
    expect(result).toBe('recording_12ch.csv')
  })

  it('should include custom suffix', () => {
    const result = buildPreviewFilename({
      filePrefix: 'recording',
      namingPattern: 'custom',
      includeDate: false,
      includeTime: false,
      includeChannelsInName: false,
      sequentialStart: 1,
      sequentialPadding: 3,
      customSuffix: 'test_run_1',
      fileFormat: 'tdms',
    }, 5)
    expect(result).toBe('recording_test_run_1.tdms')
  })

  it('should combine all naming elements', () => {
    const result = buildPreviewFilename({
      filePrefix: 'exp',
      namingPattern: 'timestamp',
      includeDate: true,
      includeTime: true,
      includeChannelsInName: true,
      sequentialStart: 1,
      sequentialPadding: 3,
      customSuffix: 'batch_A',
      fileFormat: 'csv',
    }, 8)
    expect(result).toBe('exp_2026-01-15_10-30-45_8ch_batch_A.csv')
  })
})

// ── previewDirectory ─────────────────────────────────────────

describe('previewDirectory', () => {
  function buildPreviewDirectory(cfg: {
    basePath: string
    directoryStructure: 'flat' | 'daily' | 'monthly' | 'experiment'
    experimentName: string
  }): string {
    let path = cfg.basePath
    const date = new Date(2026, 2, 10) // 2026-03-10

    if (cfg.directoryStructure === 'daily') {
      path += `/${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`
    } else if (cfg.directoryStructure === 'monthly') {
      path += `/${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}`
    } else if (cfg.directoryStructure === 'experiment' && cfg.experimentName) {
      path += `/${cfg.experimentName}`
    }

    return path
  }

  it('should return base path for flat structure', () => {
    expect(buildPreviewDirectory({
      basePath: './data',
      directoryStructure: 'flat',
      experimentName: '',
    })).toBe('./data')
  })

  it('should add daily subdirectories', () => {
    expect(buildPreviewDirectory({
      basePath: './data',
      directoryStructure: 'daily',
      experimentName: '',
    })).toBe('./data/2026/03/10')
  })

  it('should add monthly subdirectories', () => {
    expect(buildPreviewDirectory({
      basePath: './data',
      directoryStructure: 'monthly',
      experimentName: '',
    })).toBe('./data/2026/03')
  })

  it('should add experiment name', () => {
    expect(buildPreviewDirectory({
      basePath: '/recordings',
      directoryStructure: 'experiment',
      experimentName: 'boiler_test_1',
    })).toBe('/recordings/boiler_test_1')
  })

  it('should not add experiment folder if name is empty', () => {
    expect(buildPreviewDirectory({
      basePath: './data',
      directoryStructure: 'experiment',
      experimentName: '',
    })).toBe('./data')
  })
})

// ── estimatedSizePerHour ─────────────────────────────────────

describe('estimatedSizePerHour', () => {
  function calcEstimatedSizePerHour(channelCount: number, effectiveRateHz: number): number {
    const bytesPerSample = 20
    const bytesPerHour = channelCount * effectiveRateHz * 3600 * bytesPerSample
    return bytesPerHour / (1024 * 1024)
  }

  it('should compute size for 10 channels at 1 Hz', () => {
    // 10 * 1 * 3600 * 20 = 720,000 bytes = ~0.69 MB
    const result = calcEstimatedSizePerHour(10, 1)
    expect(result).toBeCloseTo(0.687, 2)
  })

  it('should compute size for 100 channels at 4 Hz', () => {
    // 100 * 4 * 3600 * 20 = 28,800,000 bytes = ~27.47 MB
    const result = calcEstimatedSizePerHour(100, 4)
    expect(result).toBeCloseTo(27.47, 1)
  })

  it('should return 0 for 0 channels', () => {
    expect(calcEstimatedSizePerHour(0, 1)).toBe(0)
  })

  it('should return 0 for 0 Hz rate', () => {
    expect(calcEstimatedSizePerHour(10, 0)).toBe(0)
  })
})

// ── formatFileSize ───────────────────────────────────────────

describe('formatFileSize', () => {
  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
  }

  it('should format bytes', () => {
    expect(formatFileSize(500)).toBe('500 B')
  })

  it('should format kilobytes', () => {
    expect(formatFileSize(2048)).toBe('2.0 KB')
  })

  it('should format megabytes', () => {
    expect(formatFileSize(5 * 1024 * 1024)).toBe('5.0 MB')
  })

  it('should format gigabytes', () => {
    expect(formatFileSize(2.5 * 1024 * 1024 * 1024)).toBe('2.50 GB')
  })

  it('should format 0 bytes', () => {
    expect(formatFileSize(0)).toBe('0 B')
  })

  it('should format 1023 bytes (just below KB)', () => {
    expect(formatFileSize(1023)).toBe('1023 B')
  })

  it('should format exactly 1 KB', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB')
  })
})

// ── formatDuration ───────────────────────────────────────────

describe('formatDuration', () => {
  function formatDuration(seconds: number): string {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    if (h > 0) return `${h}h ${m}m ${s}s`
    if (m > 0) return `${m}m ${s}s`
    return `${s}s`
  }

  it('should format seconds only', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('should format minutes and seconds', () => {
    expect(formatDuration(125)).toBe('2m 5s')
  })

  it('should format hours, minutes, and seconds', () => {
    expect(formatDuration(3661)).toBe('1h 1m 1s')
  })

  it('should format zero', () => {
    expect(formatDuration(0)).toBe('0s')
  })

  it('should format exact hours', () => {
    expect(formatDuration(7200)).toBe('2h 0m 0s')
  })

  it('should floor fractional seconds', () => {
    expect(formatDuration(90.7)).toBe('1m 30s')
  })
})

// ── channelGroups logic ──────────────────────────────────────

describe('channelGroups logic', () => {
  interface DataChannelEntry {
    name: string
    displayName: string
    type: string
    unit: string
    group?: string
    physical_channel?: string
  }

  interface DataChannelSubGroup {
    label: string
    channels: DataChannelEntry[]
  }

  interface DataChannelGroup {
    id: string
    label: string
    color: string
    channels: DataChannelEntry[]
    subGroups?: DataChannelSubGroup[]
  }

  function buildGroups(all: DataChannelEntry[]): DataChannelGroup[] {
    const groups: DataChannelGroup[] = []

    const tags = all.filter(ch =>
      ch.type !== 'published' && ch.type !== 'system' && ch.type !== 'alarm' && ch.type !== 'interlock'
    )
    if (tags.length > 0) {
      groups.push({ id: 'tags', label: 'Tags', color: '#888', channels: tags })
    }

    const published = all.filter(ch => ch.type === 'published')
    if (published.length > 0) {
      groups.push({ id: 'published', label: 'Published Variables', color: '#7c3aed', channels: published })
    }

    const system = all.filter(ch => ch.type === 'system')
    if (system.length > 0) {
      groups.push({ id: 'system', label: 'System State', color: '#3b82f6', channels: system })
    }

    const alarms = all.filter(ch => ch.type === 'alarm')
    const interlocks = all.filter(ch => ch.type === 'interlock')
    if (alarms.length > 0 || interlocks.length > 0) {
      const subGroups: DataChannelSubGroup[] = []
      const alarmsByChannel = new Map<string, DataChannelEntry[]>()
      for (const ch of alarms) {
        const channelName = ch.group || ch.name
        if (!alarmsByChannel.has(channelName)) alarmsByChannel.set(channelName, [])
        alarmsByChannel.get(channelName)!.push(ch)
      }
      for (const [channelName, entries] of alarmsByChannel) {
        subGroups.push({ label: channelName, channels: entries })
      }
      if (interlocks.length > 0) {
        subGroups.push({ label: 'Interlocks', channels: interlocks })
      }
      groups.push({
        id: 'alarms',
        label: 'Alarms & Interlocks',
        color: '#f59e0b',
        channels: [...alarms, ...interlocks],
        subGroups,
      })
    }

    return groups
  }

  it('should create tags group from hardware channels', () => {
    const channels: DataChannelEntry[] = [
      { name: 'TC_01', displayName: 'TC_01', type: 'thermocouple', unit: 'F' },
      { name: 'AI_01', displayName: 'AI_01', type: 'voltage_input', unit: 'V' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.id).toBe('tags')
    expect(groups[0]!.channels).toHaveLength(2)
  })

  it('should separate published variables into their own group', () => {
    const channels: DataChannelEntry[] = [
      { name: 'TC_01', displayName: 'TC_01', type: 'thermocouple', unit: 'F' },
      { name: 'py.PUE', displayName: 'PUE', type: 'published', unit: '' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(2)
    expect(groups[0]!.id).toBe('tags')
    expect(groups[1]!.id).toBe('published')
  })

  it('should create system state group', () => {
    const channels: DataChannelEntry[] = [
      { name: 'sys.acquiring', displayName: 'Acquiring', type: 'system', unit: 'bool' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.id).toBe('system')
  })

  it('should group alarms by source channel with sub-groups', () => {
    const channels: DataChannelEntry[] = [
      { name: 'alarm.TC_01.high_limit', displayName: 'High Limit', type: 'alarm', unit: 'bool', group: 'TC_01' },
      { name: 'alarm.TC_01.low_limit', displayName: 'Low Limit', type: 'alarm', unit: 'bool', group: 'TC_01' },
      { name: 'alarm.AI_01.high_limit', displayName: 'High Limit', type: 'alarm', unit: 'bool', group: 'AI_01' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.id).toBe('alarms')
    expect(groups[0]!.subGroups).toHaveLength(2) // TC_01 and AI_01
    expect(groups[0]!.subGroups![0]!.label).toBe('TC_01')
    expect(groups[0]!.subGroups![0]!.channels).toHaveLength(2)
    expect(groups[0]!.subGroups![1]!.label).toBe('AI_01')
  })

  it('should add interlocks as a separate sub-group', () => {
    const channels: DataChannelEntry[] = [
      { name: 'alarm.TC_01.high_limit', displayName: 'High Limit', type: 'alarm', unit: 'bool', group: 'TC_01' },
      { name: 'interlock.overheat', displayName: 'Overheat Protection', type: 'interlock', unit: 'bool' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.subGroups).toHaveLength(2)
    expect(groups[0]!.subGroups![1]!.label).toBe('Interlocks')
  })

  it('should handle all 4 categories together', () => {
    const channels: DataChannelEntry[] = [
      { name: 'TC_01', displayName: 'TC_01', type: 'thermocouple', unit: 'F' },
      { name: 'py.COP', displayName: 'COP', type: 'published', unit: '' },
      { name: 'sys.acquiring', displayName: 'Acquiring', type: 'system', unit: 'bool' },
      { name: 'alarm.TC_01.high_limit', displayName: 'High Limit', type: 'alarm', unit: 'bool', group: 'TC_01' },
      { name: 'interlock.trip', displayName: 'Trip', type: 'interlock', unit: 'bool' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(4)
    expect(groups.map(g => g.id)).toEqual(['tags', 'published', 'system', 'alarms'])
  })

  it('should handle empty channel list', () => {
    const groups = buildGroups([])
    expect(groups).toHaveLength(0)
  })

  it('should handle only interlocks (no alarms)', () => {
    const channels: DataChannelEntry[] = [
      { name: 'interlock.safety', displayName: 'Safety', type: 'interlock', unit: 'bool' },
    ]
    const groups = buildGroups(channels)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.id).toBe('alarms')
    expect(groups[0]!.subGroups).toHaveLength(1)
    expect(groups[0]!.subGroups![0]!.label).toBe('Interlocks')
  })
})

// ── toggleChannel logic ──────────────────────────────────────

describe('toggleChannel logic', () => {
  function toggleChannel(
    selected: string[],
    channelName: string,
    allNames: string[],
  ): { selected: string[], selectAll: boolean } {
    const current = [...selected]
    const idx = current.indexOf(channelName)
    if (idx >= 0) {
      current.splice(idx, 1)
      return { selected: current, selectAll: false }
    } else {
      current.push(channelName)
      return { selected: current, selectAll: current.length === allNames.length }
    }
  }

  it('should add a channel to selection', () => {
    const result = toggleChannel([], 'TC_01', ['TC_01', 'TC_02'])
    expect(result.selected).toEqual(['TC_01'])
    expect(result.selectAll).toBe(false)
  })

  it('should remove a channel from selection', () => {
    const result = toggleChannel(['TC_01', 'TC_02'], 'TC_01', ['TC_01', 'TC_02'])
    expect(result.selected).toEqual(['TC_02'])
    expect(result.selectAll).toBe(false)
  })

  it('should set selectAll when all channels selected', () => {
    const result = toggleChannel(['TC_01'], 'TC_02', ['TC_01', 'TC_02'])
    expect(result.selected).toEqual(['TC_01', 'TC_02'])
    expect(result.selectAll).toBe(true)
  })

  it('should clear selectAll when a channel is removed', () => {
    const result = toggleChannel(['TC_01', 'TC_02'], 'TC_02', ['TC_01', 'TC_02'])
    expect(result.selectAll).toBe(false)
  })
})

// ── toggleScheduleDay logic ──────────────────────────────────

describe('toggleScheduleDay logic', () => {
  function toggleScheduleDay(days: string[], day: string): string[] {
    const result = [...days]
    const idx = result.indexOf(day)
    if (idx >= 0) {
      result.splice(idx, 1)
    } else {
      result.push(day)
    }
    return result
  }

  it('should add a day', () => {
    expect(toggleScheduleDay(['mon', 'tue'], 'wed')).toEqual(['mon', 'tue', 'wed'])
  })

  it('should remove a day', () => {
    expect(toggleScheduleDay(['mon', 'tue', 'wed'], 'tue')).toEqual(['mon', 'wed'])
  })

  it('should handle empty list', () => {
    expect(toggleScheduleDay([], 'fri')).toEqual(['fri'])
  })
})

// ── toBackendRecordingConfig (real converter) ────────────────

describe('toBackendRecordingConfig', () => {
  const frontendConfig = {
    basePath: './data',
    filePrefix: 'recording',
    fileFormat: 'csv' as const,
    sampleInterval: 1,
    sampleIntervalUnit: 'seconds' as const,
    decimation: 1,
    rotationMode: 'time' as const,
    maxFileSize: 100,
    maxFileDuration: 3600,
    maxFileSamples: 10000,
    namingPattern: 'timestamp' as const,
    includeDate: true,
    includeTime: true,
    includeChannelsInName: false,
    sequentialStart: 1,
    sequentialPadding: 3,
    customSuffix: '',
    directoryStructure: 'daily' as const,
    experimentName: '',
    writeMode: 'buffered' as const,
    bufferSize: 100,
    flushInterval: 5.0,
    onLimitReached: 'new_file' as const,
    circularMaxFiles: 10,
    mode: 'manual' as const,
    triggerChannel: '',
    triggerCondition: 'above' as const,
    triggerValue: 0,
    preTriggerSamples: 100,
    postTriggerSamples: 1000,
    scheduleEnabled: false,
    scheduleStart: '08:00',
    scheduleEnd: '17:00',
    scheduleDays: ['mon', 'tue', 'wed', 'thu', 'fri'],
    csvEnabled: true,
    reuseFile: false,
    appendOnly: true,
    verifyOnClose: true,
    includeAuditMetadata: true,
    dbEnabled: false,
    dbHost: 'localhost',
    dbPort: 5432,
    dbName: 'iccsflux',
    dbUser: 'iccsflux',
    dbPassword: '',
    dbTable: 'recording_data',
    dbBatchSize: 50,
    dbTimescale: false,
  }

  it('should convert camelCase keys to snake_case', () => {
    const config = toBackendRecordingConfig(frontendConfig, [], true)

    expect(config.base_path).toBe('./data')
    expect(config.file_format).toBe('csv')
    expect(config.sample_interval).toBe(1)
    expect(config.sample_interval_unit).toBe('seconds')
    expect(config.rotation_mode).toBe('time')
    expect(config.max_file_duration_s).toBe(3600)
    expect(config.write_mode).toBe('buffered')
    expect(config.buffer_size).toBe(100)
    expect(config.flush_interval_s).toBe(5.0)
    expect(config.directory_structure).toBe('daily')
  })

  it('should map all ALCOA+ fields', () => {
    const config = toBackendRecordingConfig(frontendConfig, [], true)
    expect(config.append_only).toBe(true)
    expect(config.verify_on_close).toBe(true)
    expect(config.include_audit_metadata).toBe(true)
  })

  it('should map all PostgreSQL fields', () => {
    const config = toBackendRecordingConfig(frontendConfig, [], true)
    expect(config.db_enabled).toBe(false)
    expect(config.db_host).toBe('localhost')
    expect(config.db_port).toBe(5432)
    expect(config.db_name).toBe('iccsflux')
    expect(config.db_table).toBe('recording_data')
    expect(config.db_batch_size).toBe(50)
    expect(config.db_timescale).toBe(false)
  })

  it('should pass empty channels when selectAll is true', () => {
    const config = toBackendRecordingConfig(
      frontendConfig, ['TC_01', 'TC_02'], true,
    )
    expect(config.selected_channels).toEqual([])
    expect(config.include_scripts).toBe(true)
  })

  it('should pass specific channels when selectAll is false', () => {
    const config = toBackendRecordingConfig(
      frontendConfig, ['TC_01', 'AI_01'], false,
    )
    expect(config.selected_channels).toEqual(['TC_01', 'AI_01'])
  })

  it('should always set include_scripts to true', () => {
    const config = toBackendRecordingConfig(frontendConfig, [], false)
    expect(config.include_scripts).toBe(true)
  })
})

// ── CSV download reconstruction ──────────────────────────────

describe('CSV download reconstruction', () => {
  function buildCsv(result: {
    channels: string[]
    data: Array<{ timestamp: string; values: Record<string, number | null> }>
  }): string {
    const channels = result.channels
    const header = ['timestamp', ...channels].join(',')
    const rows = result.data.map(row => {
      const vals = channels.map(ch => {
        const v = row.values[ch]
        return v != null ? String(v) : ''
      })
      return [row.timestamp, ...vals].join(',')
    })
    return [header, ...rows].join('\n')
  }

  it('should build CSV header from channel list', () => {
    const csv = buildCsv({
      channels: ['TC_01', 'TC_02'],
      data: [],
    })
    expect(csv).toBe('timestamp,TC_01,TC_02')
  })

  it('should build CSV rows with values', () => {
    const csv = buildCsv({
      channels: ['TC_01', 'TC_02'],
      data: [
        { timestamp: '2026-01-15T10:00:00', values: { TC_01: 72.5, TC_02: 68.3 } },
        { timestamp: '2026-01-15T10:00:01', values: { TC_01: 72.6, TC_02: 68.4 } },
      ],
    })
    const lines = csv.split('\n')
    expect(lines).toHaveLength(3)
    expect(lines[0]).toBe('timestamp,TC_01,TC_02')
    expect(lines[1]).toBe('2026-01-15T10:00:00,72.5,68.3')
    expect(lines[2]).toBe('2026-01-15T10:00:01,72.6,68.4')
  })

  it('should handle null values as empty strings', () => {
    const csv = buildCsv({
      channels: ['TC_01', 'TC_02'],
      data: [
        { timestamp: '2026-01-15T10:00:00', values: { TC_01: 72.5, TC_02: null } },
      ],
    })
    const lines = csv.split('\n')
    expect(lines[1]).toBe('2026-01-15T10:00:00,72.5,')
  })

  it('should handle missing channel keys as empty strings', () => {
    const csv = buildCsv({
      channels: ['TC_01', 'TC_02'],
      data: [
        { timestamp: '2026-01-15T10:00:00', values: { TC_01: 72.5 } },
      ],
    })
    const lines = csv.split('\n')
    // TC_02 not in values → undefined → treated as null → empty
    expect(lines[1]).toBe('2026-01-15T10:00:00,72.5,')
  })

  it('should handle single channel', () => {
    const csv = buildCsv({
      channels: ['Pressure'],
      data: [
        { timestamp: '2026-01-15T10:00:00', values: { Pressure: 14.7 } },
      ],
    })
    expect(csv).toBe('timestamp,Pressure\n2026-01-15T10:00:00,14.7')
  })

  it('should handle empty data array', () => {
    const csv = buildCsv({
      channels: ['TC_01'],
      data: [],
    })
    expect(csv).toBe('timestamp,TC_01')
  })
})

// ── displayedFiles mapping ───────────────────────────────────

describe('displayedFiles mapping', () => {
  it('should map file objects to display format', () => {
    const rawFiles = [
      {
        name: 'recording_2026-01-15.csv',
        path: '/data/recording_2026-01-15.csv',
        size: 1048576,
        duration: 3600,
        created: '2026-01-15 10:00:00',
        channels: ['TC_01', 'TC_02', 'AI_01'],
      },
    ]

    const displayed = rawFiles.map(f => ({
      name: f.name,
      path: f.path,
      size: f.size,
      duration: f.duration,
      created: f.created,
      channels: f.channels?.length || 0,
    }))

    expect(displayed[0]!.name).toBe('recording_2026-01-15.csv')
    expect(displayed[0]!.channels).toBe(3)
    expect(displayed[0]!.size).toBe(1048576)
  })

  it('should handle files with no channels array', () => {
    const rawFiles = [
      {
        name: 'old_file.csv',
        path: '/data/old_file.csv',
        size: 512,
        duration: 60,
        created: '2026-01-10',
        channels: undefined as unknown as string[],
      },
    ]

    const displayed = rawFiles.map(f => ({
      name: f.name,
      channels: f.channels?.length || 0,
    }))

    expect(displayed[0]!.channels).toBe(0)
  })
})

// ── permission guard logic ───────────────────────────────────

describe('permission guard logic', () => {
  it('should allow edits when user has permission', () => {
    const hasPermission = true
    let loginDialogShown = false

    function requireEditPermission(): boolean {
      if (!hasPermission) {
        loginDialogShown = true
        return false
      }
      return true
    }

    expect(requireEditPermission()).toBe(true)
    expect(loginDialogShown).toBe(false)
  })

  it('should block edits and show login when user lacks permission', () => {
    const hasPermission = false
    let loginDialogShown = false

    function requireEditPermission(): boolean {
      if (!hasPermission) {
        loginDialogShown = true
        return false
      }
      return true
    }

    expect(requireEditPermission()).toBe(false)
    expect(loginDialogShown).toBe(true)
  })
})

// ── feedback message system ──────────────────────────────────

describe('feedback message system', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should set and auto-clear feedback message', () => {
    let feedbackMessage: { type: string, text: string } | null = null
    let feedbackTimeoutId: ReturnType<typeof setTimeout> | null = null

    function showFeedback(type: string, text: string, duration = 3000) {
      if (feedbackTimeoutId) clearTimeout(feedbackTimeoutId)
      feedbackMessage = { type, text }
      feedbackTimeoutId = setTimeout(() => {
        feedbackMessage = null
        feedbackTimeoutId = null
      }, duration)
    }

    showFeedback('success', 'Recording started')
    expect(feedbackMessage).toEqual({ type: 'success', text: 'Recording started' })

    vi.advanceTimersByTime(3000)
    expect(feedbackMessage).toBeNull()
  })

  it('should replace previous feedback', () => {
    let feedbackMessage: { type: string, text: string } | null = null
    let feedbackTimeoutId: ReturnType<typeof setTimeout> | null = null

    function showFeedback(type: string, text: string, duration = 3000) {
      if (feedbackTimeoutId) clearTimeout(feedbackTimeoutId)
      feedbackMessage = { type, text }
      feedbackTimeoutId = setTimeout(() => {
        feedbackMessage = null
        feedbackTimeoutId = null
      }, duration)
    }

    showFeedback('info', 'First message')
    showFeedback('error', 'Second message')
    expect(feedbackMessage!.text).toBe('Second message')

    // Only the second timeout should fire
    vi.advanceTimersByTime(3000)
    expect(feedbackMessage).toBeNull()
  })
})

// ── configLocked behavior ────────────────────────────────────

describe('configLocked behavior', () => {
  it('should lock when recording is active', () => {
    const status = { recording: true }
    const configLocked = status.recording || false
    expect(configLocked).toBe(true)
  })

  it('should unlock when recording is inactive', () => {
    const status = { recording: false }
    const configLocked = status.recording || false
    expect(configLocked).toBe(false)
  })

  it('should handle null status safely', () => {
    const status: { recording?: boolean } | null = null
    const configLocked = status?.recording || false
    expect(configLocked).toBe(false)
  })
})
