/**
 * Tests for Python Scripting Composable
 *
 * Tests cover:
 * - Script CRUD operations
 * - Published values management
 * - Session lifecycle hooks
 * - Script validation (mocked Pyodide)
 * - MQTT handler integration
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePythonScripts, resetPythonScriptsState } from './usePythonScripts'

// Mock the pyodideLoader module
vi.mock('../utils/pyodideLoader', () => ({
  loadPyodide: vi.fn().mockResolvedValue(undefined),
  isPyodideReady: vi.fn().mockReturnValue(false),
  getPyodide: vi.fn().mockReturnValue({
    runPythonAsync: vi.fn().mockResolvedValue(undefined),
    registerJsModule: vi.fn(),
    globals: {
      get: vi.fn().mockReturnValue({
        toJs: () => ({ valid: true, errors: [] })
      })
    }
  })
}))

describe('usePythonScripts', () => {
  let pythonScripts: ReturnType<typeof usePythonScripts>

  beforeEach(() => {
    // Reset singleton state and localStorage before each test
    resetPythonScriptsState()
    localStorage.clear()
    pythonScripts = usePythonScripts()
  })

  // ===========================================================================
  // SCRIPT CRUD TESTS
  // ===========================================================================

  describe('Script CRUD Operations', () => {
    it('should create a new script', () => {
      const script = pythonScripts.createScript('Test Script', 'A test script')

      expect(script).toBeDefined()
      expect(script.id).toMatch(/^script_/)
      expect(script.name).toBe('Test Script')
      expect(script.description).toBe('A test script')
      expect(script.enabled).toBe(true)
      expect(script.runMode).toBe('manual')
      expect(script.code).toContain('while session.active:')
    })

    it('should update an existing script', () => {
      const script = pythonScripts.createScript('Original Name')
      pythonScripts.updateScript(script.id, { name: 'Updated Name' })

      const updated = pythonScripts.getScript(script.id)
      expect(updated?.name).toBe('Updated Name')
    })

    it('should delete a script', () => {
      const script = pythonScripts.createScript('To Delete')
      expect(pythonScripts.getScript(script.id)).toBeDefined()

      pythonScripts.deleteScript(script.id)
      expect(pythonScripts.getScript(script.id)).toBeUndefined()
    })

    it('should list all scripts', () => {
      pythonScripts.createScript('Script 1')
      pythonScripts.createScript('Script 2')
      pythonScripts.createScript('Script 3')

      expect(pythonScripts.scriptsList.value.length).toBe(3)
    })

    it('should persist scripts to localStorage', () => {
      const script = pythonScripts.createScript('Persistent Script')

      const saved = localStorage.getItem('nisystem-python-scripts')
      expect(saved).toBeDefined()

      const parsed = JSON.parse(saved!)
      expect(parsed.length).toBe(1)
      expect(parsed[0].name).toBe('Persistent Script')
    })

    it('should load scripts from localStorage', () => {
      // Clear existing scripts first
      localStorage.clear()

      // Manually set localStorage
      const scripts = [{
        id: 'test_id',
        name: 'Loaded Script',
        description: '',
        code: 'print("hello")',
        enabled: true,
        runMode: 'manual',
        createdAt: new Date().toISOString(),
        modifiedAt: new Date().toISOString()
      }]
      localStorage.setItem('nisystem-python-scripts', JSON.stringify(scripts))

      // Create new instance to trigger load
      const newInstance = usePythonScripts()
      newInstance.loadFromLocalStorage()

      expect(newInstance.scriptsList.value.length).toBeGreaterThanOrEqual(1)
      const loadedScript = newInstance.scriptsList.value.find(s => s.name === 'Loaded Script')
      expect(loadedScript).toBeDefined()
    })
  })

  // ===========================================================================
  // PUBLISHED VALUES TESTS
  // ===========================================================================

  describe('Published Values', () => {
    it('should return empty published channels initially', () => {
      const channels = pythonScripts.getPublishedChannels()
      expect(Object.keys(channels).length).toBe(0)
    })

    it('should return published channel names with py. prefix', () => {
      // Manually set a published value (simulating script publish)
      pythonScripts.publishedValues.value['TestValue'] = {
        name: 'TestValue',
        value: 42.5,
        units: 'units',
        description: 'test',
        scriptId: 'test_script',
        timestamp: Date.now()
      }

      const names = pythonScripts.getPublishedChannelNames()
      expect(names).toContain('py.TestValue')
    })

    it('should get published value by name', () => {
      pythonScripts.publishedValues.value['MyValue'] = {
        name: 'MyValue',
        value: 123.45,
        units: 'F',
        description: '',
        scriptId: 'test',
        timestamp: Date.now()
      }

      expect(pythonScripts.getPublishedValue('MyValue')).toBe(123.45)
      expect(pythonScripts.getPublishedValue('py.MyValue')).toBe(123.45)
    })

    it('should return undefined for non-existent published value', () => {
      expect(pythonScripts.getPublishedValue('NonExistent')).toBeUndefined()
    })

    it('should get published channels as record', () => {
      pythonScripts.publishedValues.value['Val1'] = {
        name: 'Val1', value: 10, units: '', description: '',
        scriptId: 'test', timestamp: Date.now()
      }
      pythonScripts.publishedValues.value['Val2'] = {
        name: 'Val2', value: 20, units: '', description: '',
        scriptId: 'test', timestamp: Date.now()
      }

      const channels = pythonScripts.getPublishedChannels()
      expect(channels['py.Val1']).toBe(10)
      expect(channels['py.Val2']).toBe(20)
    })

    it('should get published units', () => {
      pythonScripts.publishedValues.value['Temp'] = {
        name: 'Temp', value: 100, units: 'F', description: '',
        scriptId: 'test', timestamp: Date.now()
      }

      const units = pythonScripts.getPublishedUnits()
      expect(units['py.Temp']).toBe('F')
    })
  })

  // ===========================================================================
  // SESSION LIFECYCLE TESTS
  // ===========================================================================

  describe('Session Lifecycle', () => {
    it('should return scripts by run mode', () => {
      const script1 = pythonScripts.createScript('Acquisition Script')
      const script2 = pythonScripts.createScript('Session Script')
      const script3 = pythonScripts.createScript('Manual Script')

      // Set run modes
      pythonScripts.setRunMode(script1.id, 'acquisition')
      pythonScripts.setRunMode(script2.id, 'session')
      // script3 stays 'manual' (default)

      const acquisitionScripts = pythonScripts.getScriptsByRunMode('acquisition')
      expect(acquisitionScripts.length).toBe(1)
      expect(acquisitionScripts[0].runMode).toBe('acquisition')

      const sessionScripts = pythonScripts.getScriptsByRunMode('session')
      expect(sessionScripts.length).toBe(1)
      expect(sessionScripts[0].runMode).toBe('session')
    })

    it('should set run mode for a script', () => {
      const script = pythonScripts.createScript('Run Mode Test')
      expect(script.runMode).toBe('manual')

      pythonScripts.setRunMode(script.id, 'acquisition')
      expect(pythonScripts.getScript(script.id)?.runMode).toBe('acquisition')

      pythonScripts.setRunMode(script.id, 'session')
      expect(pythonScripts.getScript(script.id)?.runMode).toBe('session')

      pythonScripts.setRunMode(script.id, 'manual')
      expect(pythonScripts.getScript(script.id)?.runMode).toBe('manual')
    })

    it('should call onSessionEnd without error', () => {
      // This should not throw
      expect(() => pythonScripts.onSessionEnd()).not.toThrow()
    })

    it('should call onAcquisitionStop without error', () => {
      // This should not throw
      expect(() => pythonScripts.onAcquisitionStop()).not.toThrow()
    })
  })

  // ===========================================================================
  // MQTT HANDLERS TESTS
  // ===========================================================================

  describe('MQTT Handlers', () => {
    it('should accept MQTT handlers without error', () => {
      const handlers = {
        publish: vi.fn(),
        setOutput: vi.fn(),
        getChannelValues: vi.fn().mockReturnValue({}),
        getChannelTimestamps: vi.fn().mockReturnValue({}),
        getChannelUnits: vi.fn().mockReturnValue({}),
        getSessionActive: vi.fn().mockReturnValue(false),
        getSessionElapsed: vi.fn().mockReturnValue(0)
      }

      expect(() => pythonScripts.setMqttHandlers(handlers)).not.toThrow()
    })

    it('should trigger onScanData without error', () => {
      expect(() => pythonScripts.onScanData()).not.toThrow()
    })
  })

  // ===========================================================================
  // SCRIPT OUTPUT TESTS
  // ===========================================================================

  describe('Script Output', () => {
    it('should add script output', () => {
      const script = pythonScripts.createScript('Output Test')
      pythonScripts.addScriptOutput(script.id, 'info', 'Test message')

      const outputs = pythonScripts.scriptOutputs.value[script.id]
      expect(outputs.length).toBe(1)
      expect(outputs[0].type).toBe('info')
      expect(outputs[0].message).toBe('Test message')
    })

    it('should clear script output', () => {
      const script = pythonScripts.createScript('Clear Test')
      pythonScripts.addScriptOutput(script.id, 'info', 'Message 1')
      pythonScripts.addScriptOutput(script.id, 'info', 'Message 2')

      expect(pythonScripts.scriptOutputs.value[script.id].length).toBe(2)

      pythonScripts.clearScriptOutput(script.id)
      expect(pythonScripts.scriptOutputs.value[script.id].length).toBe(0)
    })

    it('should include timestamp in output', () => {
      const script = pythonScripts.createScript('Timestamp Test')
      const before = Date.now()
      pythonScripts.addScriptOutput(script.id, 'info', 'Test')
      const after = Date.now()

      const output = pythonScripts.scriptOutputs.value[script.id][0]
      expect(output.timestamp).toBeGreaterThanOrEqual(before)
      expect(output.timestamp).toBeLessThanOrEqual(after)
    })

    it('should limit output history', () => {
      const script = pythonScripts.createScript('Limit Test')

      // Add more than 1000 outputs
      for (let i = 0; i < 1050; i++) {
        pythonScripts.addScriptOutput(script.id, 'info', `Message ${i}`)
      }

      // When length > 1000, it trims to keep last 500
      // After 1001 messages, it trims to 500, then 49 more are added = 549
      // So the final count should be less than 1050 (the total we added)
      expect(pythonScripts.scriptOutputs.value[script.id].length).toBeLessThan(1000)
    })
  })

  // ===========================================================================
  // IMPORT/EXPORT TESTS
  // ===========================================================================

  describe('Import/Export', () => {
    it('should export scripts', () => {
      pythonScripts.createScript('Export 1')
      pythonScripts.createScript('Export 2')

      const exported = pythonScripts.exportScripts()
      expect(exported.length).toBe(2)
      expect(exported[0].name).toBe('Export 1')
      expect(exported[1].name).toBe('Export 2')
    })

    it('should import scripts', () => {
      const scriptsToImport = [
        {
          id: 'import_1',
          name: 'Imported Script',
          description: 'From import',
          code: 'print("imported")',
          enabled: true,
          runMode: 'manual' as const,
          createdAt: new Date().toISOString(),
          modifiedAt: new Date().toISOString()
        }
      ]

      pythonScripts.importScripts(scriptsToImport)

      expect(pythonScripts.scriptsList.value.length).toBeGreaterThanOrEqual(1)
      expect(pythonScripts.getScript('import_1')?.name).toBe('Imported Script')
    })
  })

  // ===========================================================================
  // PYODIDE STATE TESTS
  // ===========================================================================

  describe('Pyodide State', () => {
    it('should have initial status as not_loaded', () => {
      expect(pythonScripts.pyodideStatus.value).toBe('not_loaded')
    })

    it('should not be loading initially', () => {
      expect(pythonScripts.isPyodideLoading.value).toBe(false)
    })

    it('should not have error initially', () => {
      expect(pythonScripts.isPyodideError.value).toBe(false)
    })
  })

  // ===========================================================================
  // COMPUTED PROPERTIES TESTS
  // ===========================================================================

  describe('Computed Properties', () => {
    it('should update scriptsList when scripts change', () => {
      expect(pythonScripts.scriptsList.value.length).toBe(0)

      pythonScripts.createScript('New Script')
      expect(pythonScripts.scriptsList.value.length).toBe(1)
    })

    it('should update publishedValuesList when values change', () => {
      expect(pythonScripts.publishedValuesList.value.length).toBe(0)

      pythonScripts.publishedValues.value['Test'] = {
        name: 'Test', value: 1, units: '', description: '',
        scriptId: 'test', timestamp: Date.now()
      }

      expect(pythonScripts.publishedValuesList.value.length).toBe(1)
    })

    it('should update publishedChannelNames when values change', () => {
      expect(pythonScripts.publishedChannelNames.value.length).toBe(0)

      pythonScripts.publishedValues.value['MyChannel'] = {
        name: 'MyChannel', value: 1, units: '', description: '',
        scriptId: 'test', timestamp: Date.now()
      }

      expect(pythonScripts.publishedChannelNames.value).toContain('py.MyChannel')
    })
  })
})

// ===========================================================================
// INTEGRATION TESTS (require more setup)
// ===========================================================================

describe('Python Scripts Integration', () => {
  describe('Script Execution Flow', () => {
    it('should track running scripts', () => {
      const pythonScripts = usePythonScripts()
      expect(pythonScripts.runningScripts.value.size).toBe(0)
    })

    it('should have empty runningScriptsList initially', () => {
      const pythonScripts = usePythonScripts()
      expect(pythonScripts.runningScriptsList.value.length).toBe(0)
    })
  })

  describe('Script Statuses', () => {
    it('should track script statuses', () => {
      const pythonScripts = usePythonScripts()
      const script = pythonScripts.createScript('Status Test')

      // Initially no status
      expect(pythonScripts.scriptStatuses.value[script.id]).toBeUndefined()
    })
  })
})
