/**
 * Tests for BarGraphWidget
 *
 * Tests cover:
 * - Rendering with different visual styles (bar, tank, thermometer)
 * - Value display and formatting
 * - Bar percentage calculation
 * - Min/max range handling
 * - Orientation (horizontal/vertical)
 * - Alarm/warning states
 * - Stale data handling
 * - Unit display
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'
import type { ChannelConfig, ChannelValue } from '../types'

interface MockBarState {
  mockChannels: Ref<Record<string, Partial<ChannelConfig>>>
  mockValues: Ref<Record<string, Partial<ChannelValue>>>
  mockIsAcquiring: Ref<boolean>
}

const getBarMockState = () =>
  (globalThis as unknown as Record<string, MockBarState>).__mockBarState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'temp': { name: 'Temperature', unit: '°C', low_limit: 0, high_limit: 100 },
    'pressure': { name: 'Pressure', unit: 'PSI' },
    'no_limits': { name: 'No Limits' }
  })

  const mockValues = ref({
    'temp': { value: 50, timestamp: Date.now() },
    'pressure': { value: 75, timestamp: Date.now() },
    'no_limits': { value: 25, timestamp: Date.now() }
  })

  const mockIsAcquiring = ref(true)

  ;(globalThis as unknown as Record<string, MockBarState>).__mockBarState = {
    mockChannels,
    mockValues,
    mockIsAcquiring
  }

  return {
    useDashboardStore: () => ({
      get channels() { return mockChannels.value },
      get values() { return mockValues.value },
      get isAcquiring() { return mockIsAcquiring.value }
    })
  }
})

// Import after mocking
import BarGraphWidget from './BarGraphWidget.vue'

describe('BarGraphWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getBarMockState()

    if (state) {
      state.mockIsAcquiring.value = true
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now() },
        'pressure': { value: 75, timestamp: Date.now() },
        'no_limits': { value: 25, timestamp: Date.now() }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render bar-graph-widget class', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-graph-widget').exists()).toBe(true)
    })

    it('should render label', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.label').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // VISUAL STYLE TESTS
  // ===========================================================================

  describe('Visual Styles', () => {
    it('should render bar style by default', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-container').exists()).toBe(true)
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('bar')
    })

    it('should render tank style', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank' }
      })
      expect(wrapper.find('.tank-container').exists()).toBe(true)
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('tank')
    })

    it('should render thermometer style', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.thermo-container').exists()).toBe(true)
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('thermometer')
    })

    it('should force vertical orientation for tank style', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('vertical')
    })

    it('should force vertical orientation for thermometer style', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('vertical')
    })
  })

  // ===========================================================================
  // ORIENTATION TESTS
  // ===========================================================================

  describe('Orientation', () => {
    it('should default to horizontal orientation', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-container.vertical').exists()).toBe(false)
    })

    it('should apply vertical orientation', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', orientation: 'vertical' }
      })
      expect(wrapper.find('.bar-container.vertical').exists()).toBe(true)
    })

    it('should apply horizontal orientation', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', orientation: 'horizontal' }
      })
      expect(wrapper.find('.bar-container.vertical').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Labels', () => {
    it('should display channel ID as label by default', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.label').text()).toBe('temp')
    })

    it('should display custom label when provided', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', label: 'Tank Temperature' }
      })
      expect(wrapper.find('.label').text()).toBe('Tank Temperature')
    })
  })

  // ===========================================================================
  // VALUE DISPLAY TESTS
  // ===========================================================================

  describe('Value Display', () => {
    it('should render value display element in bar mode', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'bar', showValue: true }
      })
      expect(wrapper.find('.value-display').exists()).toBe(true)
    })

    it('should hide value when showValue is false', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'bar', showValue: false }
      })
      expect(wrapper.find('.value-display').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // BAR FILL TESTS
  // ===========================================================================

  describe('Bar Fill', () => {
    it('should render bar fill element', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-fill').exists()).toBe(true)
    })

    it('should set correct width for horizontal bar', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      const style = barFill.attributes('style')
      // Value 50 in range 0-100 = 50%
      expect(style).toContain('width: 50%')
    })

    it('should set correct height for vertical bar', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', orientation: 'vertical' }
      })
      const barFill = wrapper.find('.bar-fill')
      const style = barFill.attributes('style')
      expect(style).toContain('height: 50%')
    })

    it('should cap at 100% when value exceeds max', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 150, timestamp: Date.now() }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      const style = barFill.attributes('style')
      expect(style).toContain('width: 100%')
    })

    it('should show 0% when value below min', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: -50, timestamp: Date.now() }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      const style = barFill.attributes('style')
      expect(style).toContain('width: 0%')
    })
  })

  // ===========================================================================
  // MIN/MAX RANGE TESTS
  // ===========================================================================

  describe('Min/Max Range', () => {
    it('should display range labels', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const rangeLabels = wrapper.find('.range-labels')
      expect(rangeLabels.exists()).toBe(true)
      expect(rangeLabels.text()).toContain('0')
      expect(rangeLabels.text()).toContain('100')
    })

    it('should use prop minValue over channel config', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', minValue: 10 }
      })
      const rangeLabels = wrapper.find('.range-labels')
      expect(rangeLabels.text()).toContain('10')
    })

    it('should use prop maxValue over channel config', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', maxValue: 200 }
      })
      const rangeLabels = wrapper.find('.range-labels')
      expect(rangeLabels.text()).toContain('200')
    })

    it('should default to 0-100 when no limits', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'no_limits' }
      })
      const rangeLabels = wrapper.find('.range-labels')
      expect(rangeLabels.text()).toContain('0')
      expect(rangeLabels.text()).toContain('100')
    })
  })

  // ===========================================================================
  // STATUS STATE TESTS
  // ===========================================================================

  describe('Status States', () => {
    it('should have normal class by default', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('normal')
    })

    it('should have alarm class when in alarm', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now(), alarm: true }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('alarm')
    })

    it('should have warning class when in warning', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now(), warning: true }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('warning')
    })

    it('should have stale class when data is stale', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now() - 10000 }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.bar-graph-widget').classes()).toContain('stale')
    })

    it('should use alarm color for bar fill', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now(), alarm: true }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      expect(barFill.attributes('style')).toContain('#ef4444')
    })

    it('should use warning color for bar fill', () => {
      const state = getBarMockState()
      state.mockValues.value = {
        'temp': { value: 50, timestamp: Date.now(), warning: true }
      }

      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      expect(barFill.attributes('style')).toContain('#fbbf24')
    })

    it('should use normal green color for bar fill', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp' }
      })
      const barFill = wrapper.find('.bar-fill')
      expect(barFill.attributes('style')).toContain('#4ade80')
    })
  })

  // ===========================================================================
  // TANK STYLE SPECIFIC TESTS
  // ===========================================================================

  describe('Tank Style', () => {
    it('should render tank body', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank' }
      })
      expect(wrapper.find('.tank-body').exists()).toBe(true)
    })

    it('should render tank liquid', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank' }
      })
      expect(wrapper.find('.tank-liquid').exists()).toBe(true)
    })

    it('should render tank graduations', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank' }
      })
      expect(wrapper.find('.tank-graduations').exists()).toBe(true)
      expect(wrapper.findAll('.graduation').length).toBe(5)
    })

    it('should show tank value display', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'tank', showValue: true }
      })
      expect(wrapper.find('.tank-value').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // THERMOMETER STYLE SPECIFIC TESTS
  // ===========================================================================

  describe('Thermometer Style', () => {
    it('should render thermo tube', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.thermo-tube').exists()).toBe(true)
    })

    it('should render thermo bulb', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.thermo-bulb').exists()).toBe(true)
    })

    it('should render thermo mercury', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.thermo-mercury').exists()).toBe(true)
    })

    it('should render thermo graduations', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer' }
      })
      expect(wrapper.find('.thermo-graduations').exists()).toBe(true)
    })

    it('should show thermo value display', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', visualStyle: 'thermometer', showValue: true }
      })
      expect(wrapper.find('.thermo-value').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // BACKGROUND COLOR TESTS
  // ===========================================================================

  describe('Background Color', () => {
    it('should apply background color from style', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', style: { backgroundColor: '#2d3748' } }
      })
      expect(wrapper.find('.bar-graph-widget').attributes('style')).toContain('background-color')
    })

    it('should not apply background when transparent', () => {
      const wrapper = mount(BarGraphWidget, {
        props: { channel: 'temp', style: { backgroundColor: 'transparent' } }
      })
      const style = wrapper.find('.bar-graph-widget').attributes('style')
      if (style) {
        expect(style).not.toContain('background-color')
      }
    })
  })
})
