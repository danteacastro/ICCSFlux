/**
 * Tests for ToggleSwitch Widget
 *
 * Tests cover:
 * - Rendering with different props
 * - ON/OFF state display
 * - Toggle functionality
 * - Disabled states (not acquiring, blocked)
 * - Safety interlock blocking
 * - Custom labels and colors
 * - Stale data handling
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'
import type { ChannelConfig, ChannelValue } from '../types'

interface MockToggleState {
  mockChannels: Ref<Record<string, Partial<ChannelConfig>>>
  mockValues: Ref<Record<string, Partial<ChannelValue>>>
  mockIsAcquiring: Ref<boolean>
}

interface BlockedInfo {
  blocked: boolean
  blockedBy: Array<{ name: string, failedConditions: Array<{ condition: any, reason: string }> }>
}

interface MockToggleSafetyState {
  mockBlockedChannels: Ref<Record<string, BlockedInfo>>
}

const getToggleMockState = () =>
  (globalThis as unknown as Record<string, MockToggleState>).__mockToggleState
const getToggleSafetyState = () =>
  (globalThis as unknown as Record<string, MockToggleSafetyState>).__mockSafetyState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'DO_001': { name: 'Pump 1', invert: false },
    'DO_002': { name: 'Valve 2', invert: false }
  })

  const mockValues = ref({
    'DO_001': { value: 1, timestamp: Date.now() },
    'DO_002': { value: 0, timestamp: Date.now() }
  })

  const mockIsAcquiring = ref(true)

  ;(globalThis as unknown as Record<string, MockToggleState>).__mockToggleState = {
    mockChannels,
    mockValues,
    mockIsAcquiring
  }

  return {
    useDashboardStore: () => ({
      get channels() { return mockChannels.value },
      get values() { return mockValues.value },
      getChannelRef(name: string) { return { get value() { return mockValues.value[name] } } },
      get isAcquiring() { return mockIsAcquiring.value }
    })
  }
})

// Mock the safety composable
vi.mock('../composables/useSafety', () => {
  const { ref } = require('vue')

  const mockBlockedChannels = ref<Record<string, { blocked: boolean; blockedBy: Array<{ name: string }> }>>({
    'DO_001': { blocked: false, blockedBy: [] },
    'DO_002': { blocked: false, blockedBy: [] }
  })

  ;(globalThis as unknown as Record<string, MockToggleSafetyState>).__mockSafetyState = { mockBlockedChannels }

  return {
    useSafety: () => ({
      isOutputBlocked: (channel: string) => {
        return mockBlockedChannels.value[channel] || { blocked: false, blockedBy: [] }
      }
    })
  }
})

// Import after mocking
import ToggleSwitch from './ToggleSwitch.vue'

describe('ToggleSwitch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getToggleMockState()
    const safetyState = getToggleSafetyState()

    if (state) {
      state.mockIsAcquiring.value = true
      state.mockValues.value = {
        'DO_001': { value: 1, timestamp: Date.now() },
        'DO_002': { value: 0, timestamp: Date.now() }
      }
    }

    if (safetyState) {
      safetyState.mockBlockedChannels.value = {
        'DO_001': { blocked: false, blockedBy: [] },
        'DO_002': { blocked: false, blockedBy: [] }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render toggle-switch class', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.toggle-switch').exists()).toBe(true)
    })

    it('should render switch button', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.switch').exists()).toBe(true)
    })

    it('should render slider element', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.slider').exists()).toBe(true)
    })

    it('should render label', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.label').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // STATE TESTS
  // ===========================================================================

  describe('ON/OFF State', () => {
    it('should have on class when value is 1', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.switch').classes()).toContain('on')
    })

    it('should not have on class when value is 0', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_002' }
      })
      expect(wrapper.find('.switch').classes()).not.toContain('on')
    })

    it('should use ON color when on', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      const switchEl = wrapper.find('.switch')
      expect(switchEl.attributes('style')).toContain('background-color')
      expect(switchEl.attributes('style')).toContain('#22c55e') // default on color
    })

    it('should use OFF color when off', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_002' }
      })
      const switchEl = wrapper.find('.switch')
      expect(switchEl.attributes('style')).toContain('#4b5563') // default off color
    })

    it('should use custom ON color from style prop', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', style: { onColor: '#ef4444' } }
      })
      const switchEl = wrapper.find('.switch')
      expect(switchEl.attributes('style')).toContain('#ef4444')
    })

    it('should use custom OFF color from style prop', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_002', style: { offColor: '#1f2937' } }
      })
      const switchEl = wrapper.find('.switch')
      expect(switchEl.attributes('style')).toContain('#1f2937')
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Labels', () => {
    it('should display channel name from config', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })
      expect(wrapper.find('.label').text()).toBe('Pump 1')
    })

    it('should display custom label when provided', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', label: 'Custom Label' }
      })
      expect(wrapper.find('.label').text()).toBe('Custom Label')
    })

    it('should display onLabel when ON and onLabel provided', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', onLabel: 'Running', offLabel: 'Stopped' }
      })
      expect(wrapper.find('.label').text()).toBe('Running')
    })

    it('should display offLabel when OFF and offLabel provided', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_002', onLabel: 'Running', offLabel: 'Stopped' }
      })
      expect(wrapper.find('.label').text()).toBe('Stopped')
    })

    it('should fallback to channel ID if no config name', () => {
      const state = getToggleMockState()
      state.mockChannels.value = {}

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_003' }
      })
      expect(wrapper.find('.label').text()).toBe('DO_003')
    })
  })

  // ===========================================================================
  // TOGGLE FUNCTIONALITY TESTS
  // ===========================================================================

  describe('Toggle Functionality', () => {
    it('should emit change event when clicked', async () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      await wrapper.find('.switch').trigger('click')
      expect(wrapper.emitted('change')).toBeTruthy()
      expect(wrapper.emitted('change')![0]).toEqual([false]) // toggling from ON to OFF
    })

    it('should emit true when toggling from OFF to ON', async () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_002' }
      })

      await wrapper.find('.switch').trigger('click')
      expect(wrapper.emitted('change')![0]).toEqual([true])
    })

    it('should not emit when disabled', async () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', disabled: true }
      })

      await wrapper.find('.switch').trigger('click')
      expect(wrapper.emitted('change')).toBeFalsy()
    })

    it('should have disabled attribute when disabled', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', disabled: true }
      })
      expect(wrapper.find('.switch').attributes('disabled')).toBeDefined()
    })
  })

  // ===========================================================================
  // DISABLED STATES TESTS
  // ===========================================================================

  describe('Disabled States', () => {
    it('should be disabled when not acquiring', async () => {
      const state = getToggleMockState()
      state.mockIsAcquiring.value = false

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.toggle-switch').classes()).toContain('disabled')
      expect(wrapper.find('.switch').attributes('disabled')).toBeDefined()
    })

    it('should not emit when not acquiring', async () => {
      const state = getToggleMockState()
      state.mockIsAcquiring.value = false

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      await wrapper.find('.switch').trigger('click')
      expect(wrapper.emitted('change')).toBeFalsy()
    })

    it('should be enabled when acquiring and not disabled', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.toggle-switch').classes()).not.toContain('disabled')
      expect(wrapper.find('.switch').attributes('disabled')).toBeUndefined()
    })
  })

  // ===========================================================================
  // SAFETY INTERLOCK TESTS
  // ===========================================================================

  describe('Safety Interlocks', () => {
    it('should show blocked class when blocked by interlock', () => {
      const safetyState = getToggleSafetyState()
      safetyState.mockBlockedChannels.value = {
        'DO_001': { blocked: true, blockedBy: [{ name: 'High Temp Alarm', failedConditions: [{ condition: {}, reason: 'Temperature exceeded limit' }] }] }
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.toggle-switch').classes()).toContain('blocked')
    })

    it('should show lock indicator when blocked', () => {
      const safetyState = getToggleSafetyState()
      safetyState.mockBlockedChannels.value = {
        'DO_001': { blocked: true, blockedBy: [{ name: 'Interlock 1', failedConditions: [{ condition: {}, reason: 'Condition not met' }] }] }
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.interlock-overlay').exists()).toBe(true)
    })

    it('should not show lock indicator when not blocked', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.blocked-indicator').exists()).toBe(false)
    })

    it('should not emit when blocked', async () => {
      const safetyState = getToggleSafetyState()
      safetyState.mockBlockedChannels.value = {
        'DO_001': { blocked: true, blockedBy: [{ name: 'Safety Interlock', failedConditions: [{ condition: {}, reason: 'Safety condition not met' }] }] }
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      await wrapper.find('.switch').trigger('click')
      expect(wrapper.emitted('change')).toBeFalsy()
    })

    it('should have title with blocked reason', () => {
      const safetyState = getToggleSafetyState()
      safetyState.mockBlockedChannels.value = {
        'DO_001': { blocked: true, blockedBy: [{ name: 'High Temp Alarm', failedConditions: [{ condition: {}, reason: 'Temperature exceeded limit' }] }] }
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.toggle-switch').attributes('title')).toContain('Blocked')
      expect(wrapper.find('.toggle-switch').attributes('title')).toContain('High Temp Alarm')
    })
  })

  // ===========================================================================
  // STALE DATA TESTS
  // ===========================================================================

  describe('Stale Data', () => {
    it('should show OFF when data is stale', () => {
      const state = getToggleMockState()
      state.mockValues.value = {
        'DO_001': { value: 1, timestamp: Date.now() - 10000 } // 10 seconds old
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.switch').classes()).not.toContain('on')
    })

    it('should show OFF when no timestamp', () => {
      const state = getToggleMockState()
      state.mockValues.value = {
        'DO_001': { value: 1 } // no timestamp
      }

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.switch').classes()).not.toContain('on')
    })

    it('should show OFF when channel has no value', () => {
      const state = getToggleMockState()
      state.mockValues.value = {}

      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001' }
      })

      expect(wrapper.find('.switch').classes()).not.toContain('on')
    })
  })

  // ===========================================================================
  // PROPS TESTS
  // ===========================================================================

  describe('Props', () => {
    it('should accept widgetId prop', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { widgetId: 'switch-1', channel: 'DO_001' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should accept confirmOn prop without error', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', confirmOn: true }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should accept confirmOff prop without error', () => {
      const wrapper = mount(ToggleSwitch, {
        props: { channel: 'DO_001', confirmOff: true }
      })
      expect(wrapper.exists()).toBe(true)
    })
  })
})
