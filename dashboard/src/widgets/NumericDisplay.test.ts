/**
 * Tests for NumericDisplay Widget
 *
 * Tests cover:
 * - Rendering with different props
 * - Value display with formatting
 * - Stale data handling
 * - Alarm/warning states
 * - Compact and industrial modes
 * - Custom styling
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'
import type { ChannelConfig, ChannelValue } from '../types'

interface MockNumericState {
  mockChannels: Ref<Record<string, Partial<ChannelConfig>>>
  mockValues: Ref<Record<string, Partial<ChannelValue>>>
  mockIsAcquiring: Ref<boolean>
}

const getNumericMockState = () =>
  (globalThis as unknown as Record<string, MockNumericState>).__mockNumericState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'TC_001': { name: 'TC_001', unit: '°C' },
    'PRESS_001': { name: 'PRESS_001', unit: 'psi' }
  })

  const mockValues = ref({
    'TC_001': { value: 25.5, timestamp: Date.now() },
    'PRESS_001': { value: 100.0, timestamp: Date.now() }
  })

  const mockIsAcquiring = ref(true)

  ;(globalThis as unknown as Record<string, MockNumericState>).__mockNumericState = {
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

// Mock formatUnit utility
vi.mock('../utils/formatUnit', () => ({
  formatUnit: (unit: string) => unit || ''
}))

// Import after mocking
import NumericDisplay from './NumericDisplay.vue'

describe('NumericDisplay', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getNumericMockState()
    if (state) {
      state.mockIsAcquiring.value = true
      state.mockValues.value = {
        'TC_001': { value: 25.5, timestamp: Date.now() },
        'PRESS_001': { value: 100.0, timestamp: Date.now() }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render numeric-display class', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').exists()).toBe(true)
    })

    it('should show channel label', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.label').text()).toBe('TC_001')
    })

    it('should show custom label when provided', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', label: 'Temperature' }
      })
      expect(wrapper.find('.label').text()).toBe('Temperature')
    })
  })

  // ===========================================================================
  // VALUE DISPLAY TESTS
  // ===========================================================================

  describe('Value Display', () => {
    it('should display formatted value', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', decimals: 1 }
      })
      expect(wrapper.find('.value').text()).toBe('25.5')
    })

    it('should display value with default 2 decimals', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.value').text()).toBe('25.50')
    })

    it('should display unit', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.unit').text()).toBe('°C')
    })

    it('should hide unit when showUnit is false', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', showUnit: false }
      })
      // Unit should not be rendered
      expect(wrapper.find('.unit').exists()).toBe(false)
    })

    it('should hide label when showLabel is false', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', showLabel: false }
      })
      expect(wrapper.find('.label').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // STALE DATA TESTS
  // ===========================================================================

  describe('Stale Data', () => {
    it('should show -- when not acquiring', () => {
      const state = getNumericMockState()
      state.mockIsAcquiring.value = false

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.value').text()).toBe('--')
    })

    it('should show -- for stale timestamp', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: 25.5, timestamp: Date.now() - 10000 } // 10 seconds ago
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.value').text()).toBe('--')
    })

    it('should have stale class for stale data', () => {
      const state = getNumericMockState()
      state.mockIsAcquiring.value = false

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('stale')
    })
  })

  // ===========================================================================
  // ALARM/WARNING TESTS
  // ===========================================================================

  describe('Alarm States', () => {
    it('should have warning class when channel has warning', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: 25.5, timestamp: Date.now(), warning: true }
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('warning')
    })

    it('should have alarm class when channel has alarm', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: 25.5, timestamp: Date.now(), alarm: true }
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('alarm')
    })

    it('should have normal class for normal values', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('normal')
    })
  })

  // ===========================================================================
  // ERROR STATE TESTS
  // ===========================================================================

  describe('Error States', () => {
    it('should show NaN for disconnected channel', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: NaN, timestamp: Date.now(), disconnected: true }
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.value').text()).toBe('NaN')
    })

    it('should have disconnected class', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: NaN, timestamp: Date.now(), disconnected: true }
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('disconnected')
    })

    it('should show value string for open thermocouple', () => {
      const state = getNumericMockState()
      state.mockValues.value = {
        'TC_001': { value: NaN, timestamp: Date.now(), disconnected: true, valueString: 'Open TC' }
      }

      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001' }
      })
      expect(wrapper.find('.value').text()).toBe('Open TC')
    })
  })

  // ===========================================================================
  // MODE TESTS
  // ===========================================================================

  describe('Display Modes', () => {
    it('should accept compact prop (legacy - layout now CSS container queries)', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', compact: true }
      })
      expect(wrapper.find('.numeric-display').exists()).toBe(true)
    })

    it('should have industrial class in industrial mode', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', industrial: true }
      })
      expect(wrapper.find('.numeric-display').classes()).toContain('industrial')
    })

    it('should support both compact and industrial props', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', compact: true, industrial: true }
      })
      const classes = wrapper.find('.numeric-display').classes()
      expect(classes).toContain('industrial')
    })
  })

  // ===========================================================================
  // CUSTOM STYLING TESTS
  // ===========================================================================

  describe('Custom Styling', () => {
    it('should apply custom background color', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', backgroundColor: '#ff0000' }
      })
      const style = wrapper.find('.numeric-display').attributes('style')
      expect(style).toContain('--bg-widget')
    })

    it('should apply custom value color', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', valueColor: '#00ff00' }
      })
      const style = wrapper.find('.numeric-display').attributes('style')
      expect(style).toContain('--custom-value-color')
    })

    it('should apply style object backgroundColor', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'TC_001', style: { backgroundColor: '#0000ff' } }
      })
      const style = wrapper.find('.numeric-display').attributes('style')
      expect(style).toContain('--bg-widget')
    })
  })

  // ===========================================================================
  // UNKNOWN CHANNEL TESTS
  // ===========================================================================

  describe('Unknown Channel', () => {
    it('should show -- for unknown channel', () => {
      const wrapper = mount(NumericDisplay, {
        props: { channel: 'UNKNOWN_CHANNEL' }
      })
      expect(wrapper.find('.value').text()).toBe('--')
    })
  })
})
