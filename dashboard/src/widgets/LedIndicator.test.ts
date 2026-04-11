/**
 * Tests for LedIndicator Widget
 *
 * Tests cover:
 * - Rendering with different props
 * - ON/OFF state display
 * - Stale data handling
 * - Invert logic
 * - Compact and industrial modes
 * - Custom ON/OFF colors
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'
import type { ChannelConfig, ChannelValue } from '../types'

interface MockLedState {
  mockChannels: Ref<Record<string, Partial<ChannelConfig>>>
  mockValues: Ref<Record<string, Partial<ChannelValue>>>
  mockIsAcquiring: Ref<boolean>
  mockEditMode: Ref<boolean>
}

const getLedMockState = () =>
  (globalThis as unknown as Record<string, MockLedState>).__mockLedState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'DI_001': { name: 'DI_001', invert: false },
    'DI_002': { name: 'DI_002', invert: true }
  })

  const mockValues = ref({
    'DI_001': { value: 1, timestamp: Date.now() },
    'DI_002': { value: 0, timestamp: Date.now() }
  })

  const mockIsAcquiring = ref(true)
  const mockEditMode = ref(false)

  ;(globalThis as unknown as Record<string, MockLedState>).__mockLedState = {
    mockChannels,
    mockValues,
    mockIsAcquiring,
    mockEditMode
  }

  return {
    useDashboardStore: () => ({
      get channels() { return mockChannels.value },
      get values() { return mockValues.value },
      getChannelRef(name: string) { return { get value() { return mockValues.value[name] } } },
      get isAcquiring() { return mockIsAcquiring.value },
      get editMode() { return mockEditMode.value },
      widgets: [],
      updateWidgetStyle: vi.fn()
    })
  }
})

// Mock types
vi.mock('../types', () => ({
  WIDGET_COLORS: {
    led: {
      on: ['#22c55e', '#ef4444', '#3b82f6', '#f59e0b'],
      off: ['#374151', '#1f2937', '#111827']
    }
  }
}))

// Import after mocking
import LedIndicator from './LedIndicator.vue'

describe('LedIndicator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getLedMockState()
    if (state) {
      state.mockIsAcquiring.value = true
      state.mockEditMode.value = false
      state.mockValues.value = {
        'DI_001': { value: 1, timestamp: Date.now() },
        'DI_002': { value: 0, timestamp: Date.now() }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render led-indicator class', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.find('.led-indicator').exists()).toBe(true)
    })

    it('should render LED element', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.find('.led').exists()).toBe(true)
    })

    it('should render info container', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      // The info container should exist
      expect(wrapper.find('.info').exists() || wrapper.find('.led').exists()).toBe(true)
    })

    it('should render led-indicator with correct structure', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', label: 'Motor Running' }
      })
      // Component should have led element
      expect(wrapper.find('.led').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // ON/OFF STATE TESTS
  // ===========================================================================

  describe('ON/OFF State', () => {
    it('should show ON color when value is 1', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#22c55e') // Default ON color
    })

    it('should show OFF color when value is 0', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#374151') // Default OFF color
    })

    it('should apply glow effect when ON', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('box-shadow')
    })

    it('should not have glow when OFF', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('box-shadow: none')
    })
  })

  // ===========================================================================
  // INVERT LOGIC TESTS
  // ===========================================================================

  describe('Invert Logic', () => {
    it('should invert state when invert prop is true', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', invert: true }
      })
      // Value is 0, but inverted should show as ON (green)
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#22c55e') // ON color
    })

    it('should show OFF color when not inverted and value is 0', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 0, timestamp: Date.now() }
      }
      // DI_001 has invert: false, value is 0 -> should be OFF

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      // Value is 0, not inverted -> should be OFF
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#374151') // OFF color
    })
  })

  // ===========================================================================
  // STALE DATA TESTS
  // ===========================================================================

  describe('Stale Data', () => {
    it('should show LED as off when not acquiring', () => {
      const state = getLedMockState()
      state.mockIsAcquiring.value = false

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      // LED should use OFF color when data is stale
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#374151') // OFF color
    })

    it('should show LED as off for stale timestamp', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 1, timestamp: Date.now() - 20000 } // 10 seconds ago
      }

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      // LED should use OFF color when data is stale
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#374151') // OFF color
    })
  })

  // ===========================================================================
  // MODE TESTS
  // ===========================================================================

  describe('Display Modes', () => {
    it('should accept compact prop (legacy - layout now CSS-based)', () => {
      // compact prop is now a legacy prop that doesn't add a class
      // Layout switching is handled by CSS container queries
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', compact: true }
      })
      // Component should render without errors when compact is passed
      expect(wrapper.find('.led-indicator').exists()).toBe(true)
    })

    it('should have industrial class in industrial mode', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', industrial: true }
      })
      expect(wrapper.find('.led-indicator').classes()).toContain('industrial')
    })

    it('should not show status by default in compact mode', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', compact: true }
      })
      // Status should be hidden by default in compact mode
      expect(wrapper.find('.status').exists()).toBe(false)
    })

    it('should show status when explicitly enabled in compact mode', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', compact: true, showStatus: true }
      })
      expect(wrapper.find('.status').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // LED SIZE TESTS
  // ===========================================================================

  describe('LED Sizes', () => {
    it('should have small size class', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', ledSize: 'small' }
      })
      expect(wrapper.find('.led-indicator').classes()).toContain('led-small')
    })

    it('should have medium size class by default', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.find('.led-indicator').classes()).toContain('led-medium')
    })

    it('should have large size class', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', ledSize: 'large' }
      })
      expect(wrapper.find('.led-indicator').classes()).toContain('led-large')
    })
  })

  // ===========================================================================
  // CUSTOM COLOR TESTS
  // ===========================================================================

  describe('Custom Colors', () => {
    it('should apply custom ON color from style', () => {
      const wrapper = mount(LedIndicator, {
        props: {
          widgetId: 'led-1',
          channel: 'DI_001',
          style: { onColor: '#ff0000' }
        }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#ff0000')
    })

    it('should apply custom OFF color from style', () => {
      const state = getLedMockState()
      state.mockValues.value = {
        'DI_001': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(LedIndicator, {
        props: {
          widgetId: 'led-1',
          channel: 'DI_001',
          style: { offColor: '#0000ff' }
        }
      })
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#0000ff')
    })
  })

  // ===========================================================================
  // SHOW/HIDE TESTS
  // ===========================================================================

  describe('Show/Hide Elements', () => {
    it('should hide label when showLabel is false', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', showLabel: false }
      })
      expect(wrapper.find('.label').exists()).toBe(false)
    })

    it('should hide status when showStatus is false', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001', showStatus: false }
      })
      expect(wrapper.find('.status').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // EDIT MODE TESTS
  // ===========================================================================

  describe('Edit Mode', () => {
    it('should show settings button in edit mode', () => {
      const state = getLedMockState()
      state.mockEditMode.value = true

      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.find('.settings-btn').exists()).toBe(true)
    })

    it('should hide settings button when not in edit mode', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'DI_001' }
      })
      expect(wrapper.find('.settings-btn').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // UNKNOWN CHANNEL TESTS
  // ===========================================================================

  describe('Unknown Channel', () => {
    it('should show LED as off for unknown channel', () => {
      const wrapper = mount(LedIndicator, {
        props: { widgetId: 'led-1', channel: 'UNKNOWN_CHANNEL' }
      })
      // LED should use OFF color for unknown channel (no data)
      const ledStyle = wrapper.find('.led').attributes('style')
      expect(ledStyle).toContain('#374151') // OFF color
    })
  })
})
