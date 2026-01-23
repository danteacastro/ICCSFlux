/**
 * Tests for Project Manager Composable
 *
 * Tests cover:
 * - Project file creation (v2 format)
 * - State collection from localStorage
 * - State application to localStorage
 * - Legacy bundle migration
 * - Project format detection
 * - Config file management
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { ref } from 'vue'

// Mock dashboard store
const mockStoreChannels: Record<string, any> = {}
const mockGetLayout = vi.fn().mockReturnValue({
  pages: [{ id: 'default', name: 'Page 1', widgets: [], order: 0 }],
  currentPageId: 'default',
  gridColumns: 24,
  rowHeight: 30
})
const mockSetLayout = vi.fn()
const mockSaveLayoutToStorage = vi.fn()

vi.mock('../stores/dashboard', () => ({
  useDashboardStore: () => ({
    channels: mockStoreChannels,
    getLayout: mockGetLayout,
    setLayout: mockSetLayout,
    saveLayoutToStorage: mockSaveLayoutToStorage,
    systemId: 'test-system',
    systemName: 'Test System'
  })
}))

// Mock MQTT
const mockConnected = ref(true)
const mockSendCommand = vi.fn()
const mockSendLocalCommand = vi.fn()
const mockOnConfigCurrent = vi.fn().mockReturnValue(() => {})
const mockSetAllOutputsSafe = vi.fn()

vi.mock('./useMqtt', () => ({
  useMqtt: () => ({
    connected: mockConnected,
    sendCommand: mockSendCommand,
    sendLocalCommand: mockSendLocalCommand,
    onConfigCurrent: mockOnConfigCurrent,
    setAllOutputsSafe: mockSetAllOutputsSafe
  })
}))

// Mock useProjectFiles
const mockCurrentProjectData = ref(null)

vi.mock('./useProjectFiles', () => ({
  useProjectFiles: () => ({
    currentProjectData: mockCurrentProjectData
  })
}))

// Import after mocking
import { useProjectManager } from './useProjectManager'

describe('useProjectManager', () => {
  let projectManager: ReturnType<typeof useProjectManager>

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()

    // Reset mock store
    Object.keys(mockStoreChannels).forEach(key => delete mockStoreChannels[key])

    projectManager = useProjectManager()
  })

  afterEach(() => {
    localStorage.clear()
  })

  // ===========================================================================
  // PROJECT FILE CREATION TESTS
  // ===========================================================================

  describe('Project File Creation', () => {
    it('should create a project file with default values', () => {
      const project = projectManager.createProjectFile()

      expect(project.version).toBe('2.0')
      expect(project.type).toBe('nisystem-project')
      expect(project.name).toBe('Test System')
      expect(project.createdAt).toBeDefined()
      expect(project.modifiedAt).toBeDefined()
    })

    it('should use provided name and description', () => {
      const project = projectManager.createProjectFile('My Project', 'A test project')

      expect(project.name).toBe('My Project')
      expect(project.description).toBe('A test project')
    })

    it('should include layout from store', () => {
      const project = projectManager.createProjectFile()

      expect(project.layout).toBeDefined()
      expect(project.layout.pages).toEqual([{ id: 'default', name: 'Page 1', widgets: [], order: 0 }])
      expect(project.layout.gridColumns).toBe(24)
      expect(project.layout.rowHeight).toBe(30)
    })

    it('should include channels from store', () => {
      mockStoreChannels['TC_01'] = {
        physical_channel: 'cDAQ1Mod1/ai0',
        channel_type: 'thermocouple',
        unit: 'F'
      }

      const project = projectManager.createProjectFile()

      expect(project.channels).toBeDefined()
      expect(project.channels!['TC_01']).toBeDefined()
      expect(project.channels!['TC_01'].physical_channel).toBe('cDAQ1Mod1/ai0')
    })
  })

  // ===========================================================================
  // STATE COLLECTION TESTS
  // ===========================================================================

  describe('State Collection', () => {
    it('should collect scripts from localStorage', () => {
      localStorage.setItem('nisystem-scripts', JSON.stringify([{ id: '1', name: 'Script 1' }]))
      localStorage.setItem('nisystem-sequences', JSON.stringify([{ id: '2', name: 'Sequence 1' }]))

      const state = projectManager.collectAllState()

      expect(state.scripts.calculatedParams).toEqual([{ id: '1', name: 'Script 1' }])
      expect(state.scripts.sequences).toEqual([{ id: '2', name: 'Sequence 1' }])
    })

    it('should collect recording config from localStorage', () => {
      localStorage.setItem('nisystem-recording-config', JSON.stringify({ format: 'csv' }))
      localStorage.setItem('nisystem-recording-channels', JSON.stringify(['TC_01', 'TC_02']))

      const state = projectManager.collectAllState()

      expect(state.recording.config).toEqual({ format: 'csv' })
      expect(state.recording.selectedChannels).toEqual(['TC_01', 'TC_02'])
    })

    it('should collect safety settings from localStorage', () => {
      localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify({
        TC_01: { hi_limit: 200, lo_limit: 50 }
      }))
      localStorage.setItem('nisystem-interlocks', JSON.stringify([
        { id: 'interlock-1', name: 'E-Stop' }
      ]))

      const state = projectManager.collectAllState()

      expect(state.safety.alarmConfigs).toEqual({ TC_01: { hi_limit: 200, lo_limit: 50 } })
      expect(state.safety.interlocks).toEqual([{ id: 'interlock-1', name: 'E-Stop' }])
    })

    it('should return empty arrays/objects for missing localStorage items', () => {
      const state = projectManager.collectAllState()

      expect(state.scripts.calculatedParams).toEqual([])
      expect(state.scripts.sequences).toEqual([])
      expect(state.recording.selectedChannels).toEqual([])
      expect(state.safety.interlocks).toEqual([])
    })
  })

  // ===========================================================================
  // STATE APPLICATION TESTS
  // ===========================================================================

  describe('State Application', () => {
    it('should apply layout to store', () => {
      const data = {
        layout: {
          pages: [{ id: 'page-1', name: 'Overview', widgets: [] }],
          currentPageId: 'page-1',
          gridColumns: 12,
          rowHeight: 50
        },
        scripts: { calculatedParams: [], sequences: [], schedules: [], triggers: [], transformations: [], functionBlocks: [], drawPatterns: { patterns: [], history: [] }, stateMachines: [], watchdogs: [], reportTemplates: [], scheduledReports: [], pythonScripts: [] },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [], alarms: [] }
      }

      projectManager.applyAllState(data)

      expect(mockSetLayout).toHaveBeenCalled()
      expect(mockSaveLayoutToStorage).toHaveBeenCalled()
    })

    it('should save scripts to localStorage', () => {
      const data = {
        layout: { pages: [], currentPageId: 'default', gridColumns: 24, rowHeight: 30 },
        scripts: {
          calculatedParams: [{ id: 'calc-1', name: 'Calc 1' }],
          sequences: [{ id: 'seq-1', name: 'Seq 1' }],
          schedules: [],
          triggers: [],
          transformations: [],
          functionBlocks: [],
          drawPatterns: { patterns: [], history: [] },
          stateMachines: [],
          watchdogs: [],
          reportTemplates: [],
          scheduledReports: [],
          pythonScripts: []
        },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [], alarms: [] }
      }

      projectManager.applyAllState(data)

      expect(JSON.parse(localStorage.getItem('nisystem-scripts')!)).toEqual([{ id: 'calc-1', name: 'Calc 1' }])
      expect(JSON.parse(localStorage.getItem('nisystem-sequences')!)).toEqual([{ id: 'seq-1', name: 'Seq 1' }])
    })

    it('should save safety settings to localStorage', () => {
      const data = {
        layout: { pages: [], currentPageId: 'default', gridColumns: 24, rowHeight: 30 },
        scripts: { calculatedParams: [], sequences: [], schedules: [], triggers: [], transformations: [], functionBlocks: [], drawPatterns: { patterns: [], history: [] }, stateMachines: [], watchdogs: [], reportTemplates: [], scheduledReports: [], pythonScripts: [] },
        recording: { config: {}, selectedChannels: [] },
        safety: {
          alarmConfigs: { TC_01: { hi_limit: 100 } },
          interlocks: [{ id: 'int-1', enabled: true }],
          alarms: []
        }
      }

      projectManager.applyAllState(data)

      expect(JSON.parse(localStorage.getItem('nisystem-alarm-configs-v2')!)).toEqual({ TC_01: { hi_limit: 100 } })
      expect(JSON.parse(localStorage.getItem('nisystem-interlocks')!)).toEqual([{ id: 'int-1', enabled: true }])
    })
  })

  // ===========================================================================
  // CONFIG FILE MANAGEMENT TESTS
  // ===========================================================================

  describe('Config File Management', () => {
    it('should have default config file', () => {
      expect(projectManager.getConfigFile()).toBe('system.ini')
    })

    it('should allow setting config file', () => {
      projectManager.setConfigFile('custom.ini')
      expect(projectManager.getConfigFile()).toBe('custom.ini')
    })

    it('should include config file in project', () => {
      projectManager.setConfigFile('test_config.ini')
      const project = projectManager.createProjectFile()

      expect(project.configFile).toBe('test_config.ini')
    })
  })

  // ===========================================================================
  // PROJECT IMPORT TESTS
  // ===========================================================================

  describe('Project Import', () => {
    it('should reject invalid project format', async () => {
      const result = await projectManager.importProject({ invalid: true })

      expect(result.success).toBe(false)
      expect(result.message).toBe('Invalid project file format')
    })

    it('should set outputs safe before import', async () => {
      const validProject = {
        version: '2.0',
        type: 'nisystem-project',
        name: 'Test',
        configFile: 'system.ini',
        layout: { pages: [], currentPageId: 'default', gridColumns: 24, rowHeight: 30 },
        scripts: { calculatedParams: [], sequences: [], schedules: [], triggers: [], transformations: [], functionBlocks: [], drawPatterns: { patterns: [], history: [] }, stateMachines: [], watchdogs: [], reportTemplates: [], scheduledReports: [], pythonScripts: [] },
        recording: { config: {}, selectedChannels: [] },
        safety: { alarmConfigs: {}, interlocks: [], alarms: [] }
      }

      // Mock window.location.reload
      const originalLocation = window.location
      delete (window as any).location
      window.location = { ...originalLocation, reload: vi.fn() } as any

      await projectManager.importProject(validProject)

      expect(mockSetAllOutputsSafe).toHaveBeenCalledWith('project_import')

      // Restore
      window.location = originalLocation
    })
  })

  // ===========================================================================
  // API COMPLETENESS TESTS
  // ===========================================================================

  describe('API Completeness', () => {
    it('should export all expected methods', () => {
      expect(typeof projectManager.createProjectFile).toBe('function')
      expect(typeof projectManager.downloadProject).toBe('function')
      expect(typeof projectManager.importProject).toBe('function')
      expect(typeof projectManager.loadProjectFromFile).toBe('function')
      expect(typeof projectManager.setConfigFile).toBe('function')
      expect(typeof projectManager.getConfigFile).toBe('function')
      expect(typeof projectManager.exportFullBackup).toBe('function')
      expect(typeof projectManager.downloadFullBackup).toBe('function')
      expect(typeof projectManager.collectAllState).toBe('function')
      expect(typeof projectManager.applyAllState).toBe('function')
    })

    it('should export reactive refs', () => {
      expect(projectManager.currentConfigFile).toBeDefined()
      expect(projectManager.pendingConfigRequest).toBeDefined()
    })
  })
})
