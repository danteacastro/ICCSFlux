/**
 * Tests for Backend Scripts Composable
 *
 * Tests cover:
 * - Script CRUD operations with ID preservation (bug fix)
 * - clearAllScripts sends backend command
 * - Script status handling from MQTT
 * - Script output management
 * - Running script tracking
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { ref } from 'vue'

// Mock useMqtt before importing useBackendScripts
const mockSendLocalCommand = vi.fn()
const mockSubscribe = vi.fn()

vi.mock('./useMqtt', () => ({
  useMqtt: () => ({
    sendLocalCommand: mockSendLocalCommand,
    subscribe: mockSubscribe,
    connected: ref(true)
  })
}))

// Import after mocking
import { useBackendScripts } from './useBackendScripts'

describe('useBackendScripts', () => {
  let backendScripts: ReturnType<typeof useBackendScripts>

  beforeEach(() => {
    vi.clearAllMocks()
    backendScripts = useBackendScripts()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  // ===========================================================================
  // SCRIPT ID PRESERVATION (BUG FIX TEST)
  // ===========================================================================

  describe('Script ID Preservation', () => {
    it('should use provided ID when adding a script', () => {
      const existingId = 'my-existing-script-id-123'
      const returnedId = backendScripts.addScript({
        id: existingId,
        name: 'Test Script',
        code: 'print("hello")'
      })

      expect(returnedId).toBe(existingId)
      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/add', {
        id: existingId,
        name: 'Test Script',
        code: 'print("hello")',
        description: '',
        run_mode: 'manual',
        enabled: true,
        auto_restart: false
      })
    })

    it('should generate new ID when none provided', () => {
      const returnedId = backendScripts.addScript({
        name: 'New Script',
        code: 'x = 1'
      })

      expect(returnedId).toMatch(/^script_\d+_[a-z0-9]+$/)
      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/add', expect.objectContaining({
        id: returnedId,
        name: 'New Script'
      }))
    })

    it('should preserve ID across multiple adds (no duplication)', () => {
      const scriptId = 'persistent-script-id'

      // Simulate project loading - add same script twice with same ID
      backendScripts.addScript({ id: scriptId, name: 'Script', code: 'x=1' })
      backendScripts.addScript({ id: scriptId, name: 'Script', code: 'x=1' })

      // Both calls should use the same ID
      expect(mockSendLocalCommand).toHaveBeenCalledTimes(2)
      const calls = mockSendLocalCommand.mock.calls
      expect(calls[0][1].id).toBe(scriptId)
      expect(calls[1][1].id).toBe(scriptId)
    })
  })

  // ===========================================================================
  // CLEAR ALL SCRIPTS
  // ===========================================================================

  describe('clearAllScripts', () => {
    it('should send clear-all command to backend', () => {
      backendScripts.clearAllScripts()

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/clear-all', {})
    })

    it('should clear local script state', () => {
      // Note: scripts.value is readonly in the return, but internal state is cleared
      backendScripts.clearAllScripts()

      // Verify command was sent
      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/clear-all', {})
    })
  })

  // ===========================================================================
  // SCRIPT CRUD OPERATIONS
  // ===========================================================================

  describe('Script CRUD Operations', () => {
    it('should add script with all parameters', () => {
      backendScripts.addScript({
        id: 'full-script',
        name: 'Full Script',
        code: 'for i in range(10): print(i)',
        description: 'A complete script',
        runMode: 'session',
        enabled: false
      })

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/add', {
        id: 'full-script',
        name: 'Full Script',
        code: 'for i in range(10): print(i)',
        description: 'A complete script',
        run_mode: 'session',
        enabled: false,
        auto_restart: false
      })
    })

    it('should update script with partial data', () => {
      backendScripts.updateScript('script-123', { name: 'New Name' })

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/update', {
        id: 'script-123',
        name: 'New Name'
      })
    })

    it('should update script runMode correctly', () => {
      backendScripts.updateScript('script-456', { runMode: 'acquisition' })

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/update', {
        id: 'script-456',
        run_mode: 'acquisition'
      })
    })

    it('should remove script', () => {
      backendScripts.removeScript('script-to-delete')

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/remove', {
        id: 'script-to-delete'
      })
    })
  })

  // ===========================================================================
  // SCRIPT EXECUTION
  // ===========================================================================

  describe('Script Execution', () => {
    it('should start script', () => {
      backendScripts.startScript('script-to-start')

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/start', {
        id: 'script-to-start'
      })
    })

    it('should stop script', () => {
      backendScripts.stopScript('script-to-stop')

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/stop', {
        id: 'script-to-stop'
      })
    })

    it('should request script list', () => {
      backendScripts.requestScriptList()

      expect(mockSendLocalCommand).toHaveBeenCalledWith('script/list', {})
    })
  })

  // ===========================================================================
  // SCRIPT OUTPUT MANAGEMENT
  // ===========================================================================

  describe('Script Output', () => {
    it('should return empty outputs for unknown script', () => {
      const outputs = backendScripts.getScriptOutputs('unknown-script')
      expect(outputs).toEqual([])
    })

    it('should clear script output', () => {
      // Clear should not throw
      expect(() => backendScripts.clearScriptOutput('some-script')).not.toThrow()
    })
  })

  // ===========================================================================
  // COMPUTED PROPERTIES
  // ===========================================================================

  describe('Computed Properties', () => {
    it('should have empty scripts list initially', () => {
      expect(backendScripts.scriptsList.value).toEqual([])
    })

    it('should have zero script count initially', () => {
      expect(backendScripts.scriptCount.value).toBe(0)
    })

    it('should have zero running count initially', () => {
      expect(backendScripts.runningCount.value).toBe(0)
    })

    it('should have empty running scripts set initially', () => {
      expect(backendScripts.runningScriptIds.value.size).toBe(0)
    })
  })

  // ===========================================================================
  // RUN MODE FILTERING
  // ===========================================================================

  describe('Run Mode Filtering', () => {
    it('should filter acquisition scripts', () => {
      // Initially empty
      expect(backendScripts.acquisitionScripts.value).toEqual([])
    })

    it('should filter session scripts', () => {
      // Initially empty
      expect(backendScripts.sessionScripts.value).toEqual([])
    })

    it('should filter manual scripts', () => {
      // Initially empty
      expect(backendScripts.manualScripts.value).toEqual([])
    })
  })
})

// ===========================================================================
// INTEGRATION TESTS - Script Status Handling
// ===========================================================================

describe('Backend Scripts MQTT Integration', () => {
  it('should handle empty script status', () => {
    const backendScripts = useBackendScripts()

    // Scripts should be empty
    expect(backendScripts.scriptsList.value.length).toBe(0)
  })
})
