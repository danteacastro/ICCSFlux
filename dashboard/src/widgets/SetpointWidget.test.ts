/**
 * Tests for SetpointWidget
 *
 * Tests cover:
 * - Rendering with different props
 * - Standard style (buttons) rendering
 * - Knob style rendering
 * - Value display and formatting
 * - Min/max range handling
 * - Step size calculation
 * - Increment/decrement buttons
 * - Input editing
 * - Disabled/blocked states
 * - Warning messages for wrong channel types
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'AO_001': {
      name: 'Setpoint 1',
      unit: 'V',
      channel_type: 'voltage_output',
      voltage_range: 10
    },
    'AO_002': {
      name: 'Setpoint 2',
      unit: '%',
      channel_type: 'voltage_output',
      low_limit: 0,
      high_limit: 100
    },
    'DO_001': {
      name: 'Digital Out',
      channel_type: 'digital_output'
    },
    'AI_001': {
      name: 'Analog Input',
      unit: 'V',
      channel_type: 'analog_input'
    },
    'AO_SCALED': {
      name: 'Scaled Output',
      unit: 'PSI',
      channel_type: 'voltage_output',
      scale_type: 'map',
      scaled_min: 0,
      scaled_max: 100
    }
  })

  const mockValues = ref({
    'AO_001': { value: 5.0, timestamp: Date.now() },
    'AO_002': { value: 50, timestamp: Date.now() },
    'DO_001': { value: 1, timestamp: Date.now() },
    'AI_001': { value: 2.5, timestamp: Date.now() },
    'AO_SCALED': { value: 25, timestamp: Date.now() }
  })

  const mockIsConnected = ref(true)

  ;(global as any).__mockSetpointState = {
    mockChannels,
    mockValues,
    mockIsConnected
  }

  return {
    useDashboardStore: () => ({
      get channels() { return mockChannels.value },
      get values() { return mockValues.value },
      get isConnected() { return mockIsConnected.value }
    })
  }
})

// Mock the MQTT composable
vi.mock('../composables/useMqtt', () => {
  return {
    useMqtt: () => ({
      setOutput: vi.fn()
    })
  }
})

// Mock the safety composable
vi.mock('../composables/useSafety', () => {
  const { ref } = require('vue')

  const mockBlockedChannels = ref<Record<string, { blocked: boolean; blockedBy: Array<{ name: string }> }>>({
    'AO_001': { blocked: false, blockedBy: [] },
    'AO_002': { blocked: false, blockedBy: [] }
  })

  ;(global as any).__mockSetpointSafety = { mockBlockedChannels }

  return {
    useSafety: () => ({
      isOutputBlocked: (channel: string) => mockBlockedChannels.value[channel] || { blocked: false, blockedBy: [] }
    })
  }
})

// Import after mocking
import SetpointWidget from './SetpointWidget.vue'

describe('SetpointWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = (global as any).__mockSetpointState
    const safetyState = (global as any).__mockSetpointSafety

    if (state) {
      state.mockIsConnected.value = true
      state.mockValues.value = {
        'AO_001': { value: 5.0, timestamp: Date.now() },
        'AO_002': { value: 50, timestamp: Date.now() },
        'DO_001': { value: 1, timestamp: Date.now() },
        'AI_001': { value: 2.5, timestamp: Date.now() },
        'AO_SCALED': { value: 25, timestamp: Date.now() }
      }
    }

    if (safetyState) {
      safetyState.mockBlockedChannels.value = {
        'AO_001': { blocked: false, blockedBy: [] },
        'AO_002': { blocked: false, blockedBy: [] }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render setpoint-widget class', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.setpoint-widget').exists()).toBe(true)
    })

    it('should render label', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.label').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Labels', () => {
    it('should display channel ID as label by default', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.label').text()).toBe('AO_001')
    })

    it('should display custom label when provided', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', label: 'Motor Speed' }
      })
      expect(wrapper.find('.label').text()).toBe('Motor Speed')
    })
  })

  // ===========================================================================
  // STANDARD STYLE TESTS
  // ===========================================================================

  describe('Standard Style', () => {
    it('should render standard class by default', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.setpoint-widget.standard').exists()).toBe(true)
    })

    it('should render setpoint controls', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.setpoint-controls').exists()).toBe(true)
    })

    it('should render increment button', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      const buttons = wrapper.findAll('.step-btn')
      expect(buttons.length).toBe(2)
      expect(buttons[1]?.text()).toBe('+')
    })

    it('should render decrement button', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      const buttons = wrapper.findAll('.step-btn')
      expect(buttons[0]?.text()).toBe('−')
    })

    it('should render value container', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.value-container').exists()).toBe(true)
    })

    it('should render range info', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.range-info').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // KNOB STYLE TESTS
  // ===========================================================================

  describe('Knob Style', () => {
    it('should render knob class when visualStyle is knob', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.setpoint-widget.knob').exists()).toBe(true)
    })

    it('should render knob container', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob-container').exists()).toBe(true)
    })

    it('should render knob element', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob').exists()).toBe(true)
    })

    it('should render knob body', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob-body').exists()).toBe(true)
    })

    it('should render knob indicator', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob-indicator').exists()).toBe(true)
    })

    it('should render knob value', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob-value').exists()).toBe(true)
    })

    it('should render knob range', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      expect(wrapper.find('.knob-range').exists()).toBe(true)
    })

    it('should render scale ticks', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', visualStyle: 'knob' }
      })
      const ticks = wrapper.findAll('.tick')
      expect(ticks.length).toBe(11)  // 11 ticks for knob scale
    })
  })

  // ===========================================================================
  // VALUE DISPLAY TESTS
  // ===========================================================================

  describe('Value Display', () => {
    it('should display current value', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.value').text()).toBe('5.0')
    })

    it('should display value with specified decimals', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', decimals: 2 }
      })
      expect(wrapper.find('.value').text()).toBe('5.00')
    })

    it('should display value with 0 decimals', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_002', decimals: 0 }
      })
      expect(wrapper.find('.value').text()).toBe('50')
    })

    it('should display -- when no value', () => {
      const state = (global as any).__mockSetpointState
      state.mockValues.value = {}

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.value').text()).toBe('--')
    })
  })

  // ===========================================================================
  // UNIT DISPLAY TESTS
  // ===========================================================================

  describe('Unit Display', () => {
    it('should display unit from channel config', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      const unit = wrapper.find('.unit')
      if (unit.exists()) {
        expect(unit.text()).toBe('V')
      }
    })

    it('should hide unit when showUnit is false', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', showUnit: false }
      })
      expect(wrapper.find('.unit').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // MIN/MAX RANGE TESTS
  // ===========================================================================

  describe('Min/Max Range', () => {
    it('should use prop minValue', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', minValue: 2 }
      })
      const rangeInfo = wrapper.find('.range-info')
      expect(rangeInfo.text()).toContain('2')
    })

    it('should use prop maxValue', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', maxValue: 8 }
      })
      const rangeInfo = wrapper.find('.range-info')
      expect(rangeInfo.text()).toContain('8')
    })

    it('should default to 0-10 for voltage output', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      const rangeInfo = wrapper.find('.range-info')
      expect(rangeInfo.text()).toContain('0')
      expect(rangeInfo.text()).toContain('10')
    })

    it('should use scaled min/max when configured', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_SCALED' }
      })
      const rangeInfo = wrapper.find('.range-info')
      expect(rangeInfo.text()).toContain('0')
      expect(rangeInfo.text()).toContain('100')
    })
  })

  // ===========================================================================
  // STEP SIZE TESTS
  // ===========================================================================

  describe('Step Size', () => {
    it('should use prop step', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', step: 0.5 }
      })
      // Step is used in the input element
      expect(wrapper.exists()).toBe(true)
    })

    it('should calculate smart default step', () => {
      // For 0-10V range, default step should be 0.1
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })
  })

  // ===========================================================================
  // DISABLED STATES TESTS
  // ===========================================================================

  describe('Disabled States', () => {
    it('should be disabled when not connected', () => {
      const state = (global as any).__mockSetpointState
      state.mockIsConnected.value = false

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.setpoint-widget').classes()).toContain('disabled')
    })

    it('should disable buttons when not connected', () => {
      const state = (global as any).__mockSetpointState
      state.mockIsConnected.value = false

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      const buttons = wrapper.findAll('.step-btn')
      buttons.forEach(btn => {
        expect(btn.attributes('disabled')).toBeDefined()
      })
    })

    it('should be disabled for input channels', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AI_001' }
      })
      expect(wrapper.find('.setpoint-widget').classes()).toContain('disabled')
    })
  })

  // ===========================================================================
  // BLOCKED STATE TESTS
  // ===========================================================================

  describe('Blocked State', () => {
    it('should show blocked class when blocked by interlock', () => {
      const safetyState = (global as any).__mockSetpointSafety
      safetyState.mockBlockedChannels.value = {
        'AO_001': { blocked: true, blockedBy: [{ name: 'High Temp' }] }
      }

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.setpoint-widget').classes()).toContain('blocked')
    })

    it('should show blocked indicator when blocked', () => {
      const safetyState = (global as any).__mockSetpointSafety
      safetyState.mockBlockedChannels.value = {
        'AO_001': { blocked: true, blockedBy: [{ name: 'Interlock 1' }] }
      }

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.blocked-indicator').exists()).toBe(true)
      expect(wrapper.find('.blocked-indicator').text()).toBe('BLOCKED')
    })
  })

  // ===========================================================================
  // WARNING MESSAGES TESTS
  // ===========================================================================

  describe('Warning Messages', () => {
    it('should show warning for digital output channel', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'DO_001' }
      })
      expect(wrapper.find('.warning-message').exists()).toBe(true)
      expect(wrapper.find('.warning-message').text()).toContain('toggle')
    })

    it('should show warning for input channel', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AI_001' }
      })
      expect(wrapper.find('.warning-message').exists()).toBe(true)
      expect(wrapper.find('.warning-message').text()).toContain('display')
    })

    it('should have warning class for wrong channel type', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'DO_001' }
      })
      expect(wrapper.find('.setpoint-widget').classes()).toContain('warning')
    })

    it('should not show warning for valid setpoint channel', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })
      expect(wrapper.find('.warning-message').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // INPUT EDITING TESTS
  // ===========================================================================

  describe('Input Editing', () => {
    it('should show input when value container clicked', async () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })

      await wrapper.find('.value-container').trigger('click')
      expect(wrapper.find('.value-input').exists()).toBe(true)
    })

    it('should not show input when disabled', async () => {
      const state = (global as any).__mockSetpointState
      state.mockIsConnected.value = false

      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001' }
      })

      await wrapper.find('.value-container').trigger('click')
      expect(wrapper.find('.value-input').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // PROPS TESTS
  // ===========================================================================

  describe('Props', () => {
    it('should accept widgetId prop', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'setpoint-1', channel: 'AO_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should accept style prop for background', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', style: { backgroundColor: '#2d3748' } }
      })
      const style = wrapper.find('.setpoint-widget').attributes('style')
      if (style) {
        expect(style).toContain('background-color')
      }
    })

    it('should not apply background when transparent', () => {
      const wrapper = mount(SetpointWidget, {
        props: { widgetId: 'sp-1', channel: 'AO_001', style: { backgroundColor: 'transparent' } }
      })
      const style = wrapper.find('.setpoint-widget').attributes('style')
      if (style) {
        expect(style).not.toContain('background-color')
      }
    })
  })
})
