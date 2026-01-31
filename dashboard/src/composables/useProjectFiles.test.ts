/**
 * Tests for Project Files Composable
 *
 * Tests cover:
 * - Script loading with ID preservation (bug fix)
 * - Script loading clears existing scripts first
 * - collectCurrentState includes channels
 * - Project data roundtrip (save/load preserves data)
 * - MQTT topic routing
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import type { ProjectData } from './useProjectFiles'

// Mock dependencies
const mockSendNodeCommand = vi.fn()
const mockSendLocalCommand = vi.fn()
const mockSendCommand = vi.fn()
const mockSubscribe = vi.fn()
const mockOnAlarm = vi.fn().mockReturnValue(() => {}) // Returns unsubscribe function
const mockSetOutput = vi.fn()
const mockConnected = { value: true }

// Mock MQTT with all methods used by composables
vi.mock('./useMqtt', () => ({
  useMqtt: () => ({
    sendNodeCommand: mockSendNodeCommand,
    sendLocalCommand: mockSendLocalCommand,
    sendCommand: mockSendCommand,
    subscribe: mockSubscribe,
    onAlarm: mockOnAlarm,
    setOutput: mockSetOutput,
    setAllOutputsSafe: vi.fn(),
    connected: mockConnected,
    systemStatus: { value: { acquiring: false, recording: false } },
    channelValues: { value: {} },
    channelConfigs: { value: {} },
    onConfigCurrent: vi.fn().mockReturnValue(() => {}),
    onSystemUpdate: vi.fn().mockReturnValue(() => {}),
  })
}))

// Mock dashboard store
const mockStoreChannels: Record<string, any> = {}
const mockSetLayout = vi.fn()
const mockGetLayout = vi.fn().mockReturnValue({
  widgets: [],
  gridColumns: 12,
  rowHeight: 50
})

vi.mock('../stores/dashboard', () => ({
  useDashboardStore: () => ({
    channels: mockStoreChannels,
    setLayout: mockSetLayout,
    getLayout: mockGetLayout,
    setChannels: vi.fn(),
    saveLayoutToStorage: vi.fn(),
    systemId: 'test-system'
  })
}))

// Mock Python scripts composable
const mockImportScripts = vi.fn()
const mockExportScripts = vi.fn().mockReturnValue([])

vi.mock('./usePythonScripts', () => ({
  usePythonScripts: () => ({
    importScripts: mockImportScripts,
    exportScripts: mockExportScripts
  })
}))

// Mock backend scripts composable
const mockAddScript = vi.fn()
const mockClearAllScripts = vi.fn()
const mockScriptsList = { value: [] }

vi.mock('./useBackendScripts', () => ({
  useBackendScripts: () => ({
    addScript: mockAddScript,
    clearAllScripts: mockClearAllScripts,
    scriptsList: mockScriptsList,
    scripts: { value: {} },
    runningScripts: { value: new Set() },
    scriptOutputs: { value: {} },
  })
}))

// Mock safety composable
vi.mock('./useSafety', () => ({
  useSafety: () => ({
    clearAllSafetyState: vi.fn(),
    loadAlarmConfigs: vi.fn(),
    loadInterlocks: vi.fn(),
    alarmConfigs: { value: {} },
    interlocks: { value: [] },
  })
}))

describe('useProjectFiles', () => {
  beforeEach(() => {
    vi.resetAllMocks()  // Reset call counts AND implementations
    vi.clearAllMocks()  // Clear any remaining state
    // Reset mock implementations that were cleared by resetAllMocks
    mockOnAlarm.mockReturnValue(() => {})
    mockGetLayout.mockReturnValue({
      widgets: [],
      gridColumns: 12,
      rowHeight: 50
    })
    mockExportScripts.mockReturnValue([])
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.resetAllMocks()
  })

  // ===========================================================================
  // SCRIPT LOADING WITH ID PRESERVATION (BUG FIX)
  // ===========================================================================

  describe('Script Loading - ID Preservation', () => {
    it('should pass script ID to backend when loading project', async () => {
      // Use real timers for async tests with internal setTimeout
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Test Project',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: {
          widgets: [],
          gridColumns: 12,
          rowHeight: 50
        },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: [],
          pythonScripts: [
            {
              id: 'dhw-draw-profile-abc123',
              name: 'DHW Draw Profile',
              code: 'print("test")',
              runMode: 'session',
              enabled: true
            }
          ]
        },
        recording: {
          config: {},
          selectedChannels: []
        },
        safety: {
          alarmConfigs: {},
          interlocks: []
        }
      }

      await projectFiles.applyProjectData(projectData)

      // Wait for debounce (200ms) to complete
      await new Promise(resolve => setTimeout(resolve, 250))

      // Should have cleared existing scripts first
      expect(mockClearAllScripts).toHaveBeenCalled()

      // Should have added script with original ID preserved
      expect(mockAddScript).toHaveBeenCalledWith({
        id: 'dhw-draw-profile-abc123',
        name: 'DHW Draw Profile',
        code: 'print("test")',
        description: '',
        runMode: 'session',
        enabled: true
      })
    })

    it('should clear backend scripts before loading new ones', async () => {
      // Use real timers for async tests with internal setTimeout
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Test Project',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: { widgets: [], gridColumns: 12, rowHeight: 50 },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: [],
          pythonScripts: [{ id: 'test-1', name: 'Test', code: 'x=1', enabled: true }]
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      await projectFiles.applyProjectData(projectData)

      // Clear should be called
      expect(mockClearAllScripts).toHaveBeenCalledTimes(1)

      // Wait for debounce (200ms) to complete
      await new Promise(resolve => setTimeout(resolve, 250))

      // Scripts should be added after debounce
      expect(mockAddScript).toHaveBeenCalledTimes(1)
    })

    it('should debounce script loading to prevent duplicates', async () => {
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Test',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: { widgets: [], gridColumns: 12, rowHeight: 50 },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: [],
          pythonScripts: [{ id: 'script-1', name: 'Script 1', code: 'a=1', enabled: true }]
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      // Call applyProjectData twice quickly (simulating project/loaded + project/current)
      // Don't await first call so second call can start immediately
      const p1 = projectFiles.applyProjectData(projectData)
      const p2 = projectFiles.applyProjectData(projectData)
      await Promise.all([p1, p2])

      // Wait for debounce (200ms) to complete
      await new Promise(resolve => setTimeout(resolve, 250))

      // Scripts should only be added ONCE due to debouncing
      expect(mockAddScript).toHaveBeenCalledTimes(1)
    })

    it('should handle run_mode field (snake_case from backend)', async () => {
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Test',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: { widgets: [], gridColumns: 12, rowHeight: 50 },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: [],
          pythonScripts: [{
            id: 'snake-case-script',
            name: 'Snake Case',
            code: 'b=2',
            run_mode: 'acquisition',  // snake_case from backend
            enabled: true
          }]
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      await projectFiles.applyProjectData(projectData)

      // Wait for debounce (200ms) to complete
      await new Promise(resolve => setTimeout(resolve, 250))

      expect(mockAddScript).toHaveBeenCalledWith(expect.objectContaining({
        runMode: 'acquisition'
      }))
    })
  })

  // ===========================================================================
  // COLLECT CURRENT STATE - CHANNEL PRESERVATION
  // ===========================================================================

  describe('collectCurrentState - Channel Preservation', () => {
    it('should include channels from store in collected state', async () => {
      vi.resetModules()

      // Setup mock store with channels
      mockStoreChannels['TC_01'] = {
        physical_channel: 'cDAQ1Mod1/ai0',
        channel_type: 'thermocouple',
        unit: 'F',
        thermocouple_type: 'K'
      }
      mockStoreChannels['AI_02'] = {
        physical_channel: 'cDAQ1Mod2/ai0',
        channel_type: 'voltage',
        unit: 'V',
        scale_slope: 1.0,
        scale_offset: 0.0
      }

      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const state = projectFiles.collectCurrentState()

      // Channels should be included
      expect(state.channels).toBeDefined()
      expect(state.channels!['TC_01']).toBeDefined()
      expect(state.channels!['TC_01'].physical_channel).toBe('cDAQ1Mod1/ai0')
      expect(state.channels!['AI_02']).toBeDefined()
    })

    it('should export Python scripts from backend scripts composable', async () => {
      vi.resetModules()

      // collectCurrentState uses backendScripts.scriptsList, not pythonScripts.exportScripts
      mockScriptsList.value = [
        { id: 'exported-1', name: 'Exported Script', code: 'z=1', runMode: 'manual', enabled: true }
      ]

      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const state = projectFiles.collectCurrentState()

      // Python scripts should come from backend scripts composable
      expect(state.scripts?.pythonScripts).toBeDefined()
      expect(state.scripts?.pythonScripts?.length).toBe(1)
      expect(state.scripts?.pythonScripts?.[0].name).toBe('Exported Script')

      // Clean up
      mockScriptsList.value = []
    })
  })

  // ===========================================================================
  // LAYOUT APPLICATION
  // ===========================================================================

  describe('Layout Application', () => {
    it('should apply layout with multi-page support', async () => {
      // Use real timers for async tests that await functions with setTimeout
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Multi-Page Project',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: {
          pages: [
            { id: 'page-1', name: 'Overview', widgets: [] },
            { id: 'page-2', name: 'Details', widgets: [] }
          ],
          currentPageId: 'page-1',
          gridColumns: 12,
          rowHeight: 50
        },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: []
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      // applyProjectData is async with internal setTimeout
      await projectFiles.applyProjectData(projectData)

      expect(mockSetLayout).toHaveBeenCalledWith(expect.objectContaining({
        pages: expect.arrayContaining([
          expect.objectContaining({ id: 'page-1', name: 'Overview' })
        ]),
        currentPageId: 'page-1'
      }))
    })

    it('should handle legacy single-page layout', async () => {
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '1.0',
        name: 'Legacy Project',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: {
          widgets: [{ id: 'w1', type: 'numeric', x: 0, y: 0, w: 2, h: 2 }],
          gridColumns: 12,
          rowHeight: 50
        },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: []
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      await projectFiles.applyProjectData(projectData)

      expect(mockSetLayout).toHaveBeenCalled()
    })
  })

  // ===========================================================================
  // SAFETY SETTINGS PERSISTENCE
  // ===========================================================================

  describe('Safety Settings', () => {
    it('should save alarm configs to localStorage', async () => {
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Safety Test',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: { widgets: [], gridColumns: 12, rowHeight: 50 },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: []
        },
        recording: { config: {}, selectedChannels: [] },
        safety: {
          alarmConfigs: {
            'TC_01': { hi_limit: 200, hihi_limit: 250 }
          },
          interlocks: [
            { id: 'interlock-1', name: 'Emergency Stop', enabled: true }
          ]
        }
      }

      await projectFiles.applyProjectData(projectData)

      // Should save to both v1 and v2 keys for compatibility
      const savedV1 = localStorage.getItem('nisystem-alarm-configs')
      const savedV2 = localStorage.getItem('nisystem-alarm-configs-v2')

      expect(savedV1).toBeDefined()
      expect(savedV2).toBeDefined()

      const parsedV2 = JSON.parse(savedV2!)
      expect(parsedV2['TC_01'].hi_limit).toBe(200)
    })
  })

  // ===========================================================================
  // RECORDING SETTINGS
  // ===========================================================================

  describe('Recording Settings', () => {
    it('should save recording config and selected channels', async () => {
      vi.useRealTimers()
      vi.resetModules()
      const { useProjectFiles } = await import('./useProjectFiles')
      const projectFiles = useProjectFiles()

      const projectData: ProjectData = {
        type: 'nisystem-project',
        version: '2.1',
        name: 'Recording Test',
        created: new Date().toISOString(),
        modified: new Date().toISOString(),
        layout: { widgets: [], gridColumns: 12, rowHeight: 50 },
        scripts: {
          calculatedParams: [],
          sequences: [],
          schedules: [],
          alarms: [],
          transformations: [],
          triggers: []
        },
        recording: {
          config: { format: 'csv', interval_seconds: 1 },
          selectedChannels: ['TC_01', 'TC_02', 'AI_01']
        },
        safety: { alarmConfigs: {}, interlocks: [] }
      }

      await projectFiles.applyProjectData(projectData)

      const savedConfig = JSON.parse(localStorage.getItem('nisystem-recording-config') || '{}')
      const savedChannels = JSON.parse(localStorage.getItem('nisystem-recording-channels') || '[]')

      expect(savedConfig.format).toBe('csv')
      expect(savedChannels).toContain('TC_01')
      expect(savedChannels.length).toBe(3)
    })
  })
})

// ===========================================================================
// ROUNDTRIP TESTS
// ===========================================================================

describe('Project Data Roundtrip', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.clearAllMocks()
    // Restore mock implementations
    mockOnAlarm.mockReturnValue(() => {})
    mockGetLayout.mockReturnValue({
      widgets: [],
      gridColumns: 12,
      rowHeight: 50
    })
    mockExportScripts.mockReturnValue([])
    localStorage.clear()
  })

  it('should preserve script IDs through save/load cycle', async () => {
    vi.resetModules()

    // Setup: backend scripts have specific IDs (collectCurrentState uses scriptsList)
    mockScriptsList.value = [
      { id: 'preserved-id-123', name: 'My Script', code: 'x=1', runMode: 'session', enabled: true }
    ]

    const { useProjectFiles } = await import('./useProjectFiles')
    const projectFiles = useProjectFiles()

    // Collect state (simulates "save")
    const collectedState = projectFiles.collectCurrentState()

    // Verify script ID is in collected state
    expect(collectedState.scripts?.pythonScripts?.[0].id).toBe('preserved-id-123')

    // Now apply that state back (simulates "load")
    const fullProjectData = {
      type: 'nisystem-project' as const,
      version: '2.1',
      name: 'Roundtrip Test',
      created: new Date().toISOString(),
      modified: new Date().toISOString(),
      layout: collectedState.layout || { widgets: [], gridColumns: 12, rowHeight: 50 },
      scripts: collectedState.scripts || {
        calculatedParams: [],
        sequences: [],
        schedules: [],
        alarms: [],
        transformations: [],
        triggers: []
      },
      recording: collectedState.recording || { config: {}, selectedChannels: [] },
      safety: collectedState.safety || { alarmConfigs: {}, interlocks: [] }
    }

    // applyProjectData is async with internal setTimeout - use real timers
    await projectFiles.applyProjectData(fullProjectData)

    // Wait for debounce (200ms) to complete
    await new Promise(resolve => setTimeout(resolve, 250))

    // Verify script was added with preserved ID
    expect(mockAddScript).toHaveBeenCalledWith(expect.objectContaining({
      id: 'preserved-id-123'
    }))

    // Clean up
    mockScriptsList.value = []
  })
})
