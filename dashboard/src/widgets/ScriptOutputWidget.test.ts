/**
 * Tests for ScriptOutputWidget
 *
 * CRITICAL WIDGET - Displays script console output
 *
 * Note: Tests focus on structure and verifiable behavior. Tests for reactive
 * computed values (like status bar state) are simplified due to mock reactivity
 * constraints. Business logic should be tested in useBackendScripts tests.
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, computed, type Ref } from 'vue'

interface ScriptOutputLine {
  type: string
  message: string
  timestamp: number
}

interface ScriptInfo {
  name: string
  state: string
}

interface MockScriptOutputState {
  mockScriptOutputs: Ref<Record<string, ScriptOutputLine[]>>
  mockScripts: Ref<Record<string, ScriptInfo>>
  mockClearScriptOutput: Mock
  mockClearAllOutput: Mock
}

const getScriptOutputMockState = () =>
  (globalThis as unknown as Record<string, MockScriptOutputState>).__mockScriptOutputState

// Mock the useBackendScripts composable
vi.mock('../composables/useBackendScripts', () => {
  const { ref, computed } = require('vue')

  const mockScriptOutputs = ref<Record<string, ScriptOutputLine[]>>({})
  const mockScripts = ref<Record<string, ScriptInfo>>({})
  const mockClearScriptOutput = vi.fn()
  const mockClearAllOutput = vi.fn()

  const mockRunningScripts = computed(() => {
    return Object.values(mockScripts.value).filter((s: ScriptInfo) => s.state === 'running')
  })

  const mockScriptsList = computed(() => {
    return Object.values(mockScripts.value)
  })

  ;(globalThis as unknown as Record<string, MockScriptOutputState>).__mockScriptOutputState = {
    mockScriptOutputs,
    mockScripts,
    mockClearScriptOutput,
    mockClearAllOutput
  }

  return {
    useBackendScripts: () => ({
      scriptOutputs: mockScriptOutputs,
      scripts: mockScripts,
      runningScripts: mockRunningScripts,
      scriptsList: mockScriptsList,
      clearScriptOutput: mockClearScriptOutput,
      clearAllOutput: mockClearAllOutput
    })
  }
})

import ScriptOutputWidget from './ScriptOutputWidget.vue'

describe('ScriptOutputWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getScriptOutputMockState()
    if (state) {
      state.mockScriptOutputs.value = {}
      state.mockScripts.value = {}
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should have script-output-widget class', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.script-output-widget').exists()).toBe(true)
    })

    it('should render header with title', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.widget-header').exists()).toBe(true)
      expect(wrapper.find('.widget-title').exists()).toBe(true)
    })

    it('should show default title "Script Output"', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.widget-title').text()).toBe('Script Output')
    })

    it('should show custom label when provided', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', label: 'My Script Log' }
      })
      expect(wrapper.find('.widget-title').text()).toBe('My Script Log')
    })

    it('should render output container', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.output-container').exists()).toBe(true)
    })

    it('should render header actions', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.header-actions').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // EMPTY STATE TESTS
  // ===========================================================================

  describe('Empty State', () => {
    it('should show empty state when no output', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.empty-state').exists()).toBe(true)
      expect(wrapper.find('.empty-state').text()).toBe('No output yet')
    })

    it('should not show output lines when empty', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.output-line').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // OUTPUT LINE TESTS
  // ===========================================================================

  describe('Output Lines', () => {
    beforeEach(() => {
      const state = getScriptOutputMockState()
      state.mockScriptOutputs.value = {
        'script1': [
          { type: 'stdout', message: 'Hello World', timestamp: 1700000000000 },
          { type: 'info', message: 'Info message', timestamp: 1700000001000 },
          { type: 'warning', message: 'Warning message', timestamp: 1700000002000 },
          { type: 'error', message: 'Error message', timestamp: 1700000003000 }
        ]
      }
      state.mockScripts.value = {
        'script1': { name: 'Test Script', state: 'running' }
      }
    })

    it('should display output lines', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.findAll('.output-line').length).toBe(4)
    })

    it('should not show empty state when output exists', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.empty-state').exists()).toBe(false)
    })

    it('should display message content', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.line-message').text()).toBe('Hello World')
    })

    it('should display timestamp', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.find('.line-time').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // OUTPUT TYPE STYLING TESTS
  // ===========================================================================

  describe('Output Type Styling', () => {
    beforeEach(() => {
      const state = getScriptOutputMockState()
      state.mockScriptOutputs.value = {
        'script1': [
          { type: 'stdout', message: 'Standard output', timestamp: 1000 },
          { type: 'info', message: 'Info output', timestamp: 2000 },
          { type: 'warning', message: 'Warning output', timestamp: 3000 },
          { type: 'error', message: 'Error output', timestamp: 4000 }
        ]
      }
      state.mockScripts.value = {
        'script1': { name: 'Test', state: 'idle' }
      }
    })

    it('should apply stdout class', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines[0].classes()).toContain('stdout')
    })

    it('should apply info class', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines[1].classes()).toContain('info')
    })

    it('should apply warning class', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines[2].classes()).toContain('warning')
    })

    it('should apply error class', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines[3].classes()).toContain('error')
    })
  })

  // ===========================================================================
  // STATUS BAR TESTS
  // ===========================================================================

  describe('Status Bar', () => {
    it('should hide status bar when showStatus is false', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', showStatus: false }
      })
      expect(wrapper.find('.status-bar').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // SCRIPT FILTERING TESTS
  // ===========================================================================

  describe('Script Filtering', () => {
    beforeEach(() => {
      const state = getScriptOutputMockState()
      state.mockScriptOutputs.value = {
        'script1': [
          { type: 'stdout', message: 'Script 1 output', timestamp: 1000 }
        ],
        'script2': [
          { type: 'stdout', message: 'Script 2 output', timestamp: 2000 }
        ]
      }
      state.mockScripts.value = {
        'script1': { name: 'Script One', state: 'idle' },
        'script2': { name: 'Script Two', state: 'idle' }
      }
    })

    it('should show all scripts output when no filter', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines.length).toBe(2)
    })

    it('should filter to specific script when scriptId provided', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', scriptId: 'script1' }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines.length).toBe(1)
      expect(lines[0].find('.line-message').text()).toBe('Script 1 output')
    })

    it('should hide script name when filtered to single script', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', scriptId: 'script1' }
      })
      expect(wrapper.find('.line-script').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // CLEAR OUTPUT TESTS
  // ===========================================================================

  describe('Clear Output', () => {
    it('should have clear button', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const clearBtn = wrapper.findAll('.action-btn')[1]
      expect(clearBtn.exists()).toBe(true)
    })

    it('should call clearAllOutput when clear clicked (no filter)', async () => {
      const state = getScriptOutputMockState()
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })

      const clearBtn = wrapper.findAll('.action-btn')[1]
      await clearBtn.trigger('click')

      expect(state.mockClearAllOutput).toHaveBeenCalled()
    })

    it('should call clearScriptOutput when clear clicked (with filter)', async () => {
      const state = getScriptOutputMockState()
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', scriptId: 'script1' }
      })

      const clearBtn = wrapper.findAll('.action-btn')[1]
      await clearBtn.trigger('click')

      expect(state.mockClearScriptOutput).toHaveBeenCalledWith('script1')
    })
  })

  // ===========================================================================
  // AUTO-SCROLL TESTS
  // ===========================================================================

  describe('Auto-Scroll', () => {
    it('should have auto-scroll button', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const scrollBtn = wrapper.findAll('.action-btn')[0]
      expect(scrollBtn.exists()).toBe(true)
    })

    it('should have active class when auto-scroll enabled', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const scrollBtn = wrapper.findAll('.action-btn')[0]
      expect(scrollBtn.classes()).toContain('active')
    })

    it('should toggle auto-scroll on click', async () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const scrollBtn = wrapper.findAll('.action-btn')[0]

      await scrollBtn.trigger('click')
      expect(scrollBtn.classes()).not.toContain('active')

      await scrollBtn.trigger('click')
      expect(scrollBtn.classes()).toContain('active')
    })
  })

  // ===========================================================================
  // MAX LINES TESTS
  // ===========================================================================

  describe('Max Lines', () => {
    beforeEach(() => {
      const state = getScriptOutputMockState()
      const outputs = []
      for (let i = 0; i < 150; i++) {
        outputs.push({ type: 'stdout', message: `Line ${i}`, timestamp: i * 1000 })
      }
      state.mockScriptOutputs.value = { 'script1': outputs }
      state.mockScripts.value = { 'script1': { name: 'Test', state: 'idle' } }
    })

    it('should limit to 100 lines by default', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      expect(wrapper.findAll('.output-line').length).toBe(100)
    })

    it('should limit to custom maxLines', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', maxLines: 50 }
      })
      expect(wrapper.findAll('.output-line').length).toBe(50)
    })

    it('should show most recent lines', () => {
      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', maxLines: 10 }
      })
      const lines = wrapper.findAll('.output-line')
      expect(lines[0].find('.line-message').text()).toBe('Line 140')
      expect(lines[9].find('.line-message').text()).toBe('Line 149')
    })
  })

  // ===========================================================================
  // EDGE CASES
  // ===========================================================================

  describe('Edge Cases', () => {
    it('should handle script with no outputs', () => {
      const state = getScriptOutputMockState()
      state.mockScriptOutputs.value = { 'script1': [] }
      state.mockScripts.value = { 'script1': { name: 'Test', state: 'idle' } }

      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1', scriptId: 'script1' }
      })
      expect(wrapper.find('.empty-state').exists()).toBe(true)
    })

    it('should sort outputs by timestamp', () => {
      const state = getScriptOutputMockState()
      state.mockScriptOutputs.value = {
        'script1': [
          { type: 'stdout', message: 'Third', timestamp: 3000 },
          { type: 'stdout', message: 'First', timestamp: 1000 },
          { type: 'stdout', message: 'Second', timestamp: 2000 }
        ]
      }
      state.mockScripts.value = { 'script1': { name: 'Test', state: 'idle' } }

      const wrapper = mount(ScriptOutputWidget, {
        props: { widgetId: 'output-1' }
      })
      const messages = wrapper.findAll('.line-message').map(m => m.text())
      expect(messages).toEqual(['First', 'Second', 'Third'])
    })
  })
})
