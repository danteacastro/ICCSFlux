/**
 * Tests for InterlockStatusWidget
 *
 * SAFETY-CRITICAL WIDGET - Displays interlock statuses
 *
 * Tests cover:
 * - Rendering and structure
 * - No interlocks state
 * - Summary counts (satisfied, blocked, bypassed)
 * - All clear indicator
 * - Interlock list display
 * - Status classes (satisfied, blocked, bypassed, disabled)
 * - Compact mode
 * - Bypass buttons
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, computed, type Ref } from 'vue'
import type { InterlockStatus, Interlock } from '../types'

interface MockInterlockState {
  mockInterlockStatuses: Ref<Partial<InterlockStatus>[]>
  mockInterlocks: Ref<Partial<Interlock>[]>
  mockBypassInterlock: Mock
}

const getInterlockMockState = () =>
  (globalThis as unknown as Record<string, MockInterlockState>).__mockInterlockState

// Mock useSafety
vi.mock('../composables/useSafety', () => {
  const { ref, computed } = require('vue')

  const mockInterlockStatuses = ref<Partial<InterlockStatus>[]>([])
  const mockInterlocks = ref<Partial<Interlock>[]>([])
  const mockBypassInterlock = vi.fn()

  ;(globalThis as unknown as Record<string, MockInterlockState>).__mockInterlockState = {
    mockInterlockStatuses,
    mockInterlocks,
    mockBypassInterlock
  }

  return {
    useSafety: () => ({
      interlockStatuses: mockInterlockStatuses,
      interlocks: mockInterlocks,
      bypassInterlock: mockBypassInterlock
    })
  }
})

// Import after mocking
import InterlockStatusWidget from './InterlockStatusWidget.vue'

describe('InterlockStatusWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = getInterlockMockState()
    if (state) {
      state.mockInterlockStatuses.value = []
      state.mockInterlocks.value = []
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(InterlockStatusWidget)
      expect(wrapper.exists()).toBe(true)
    })

    it('should have interlock-status-widget class', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.interlock-status-widget').exists()).toBe(true)
    })

    it('should show custom title when provided', () => {
      const wrapper = mount(InterlockStatusWidget, {
        props: { title: 'Safety Interlocks' }
      })
      expect(wrapper.find('.widget-title').text()).toBe('Safety Interlocks')
    })

    it('should not show title when not provided', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.widget-title').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // NO INTERLOCKS STATE TESTS
  // ===========================================================================

  describe('No Interlocks State', () => {
    it('should show no interlocks message when empty', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.no-interlocks').exists()).toBe(true)
    })

    it('should show shield icon in no interlocks state', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.no-interlocks svg').exists()).toBe(true)
    })

    it('should show "No interlocks" text', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.no-interlocks span').text()).toBe('No interlocks')
    })

    it('should not show summary row when no interlocks', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.summary-row').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // SUMMARY COUNTS TESTS
  // ===========================================================================

  describe('Summary Counts', () => {
    beforeEach(() => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: false },
        { id: '2', name: 'Interlock 2', satisfied: true, enabled: true, bypassed: false },
        { id: '3', name: 'Interlock 3', satisfied: false, enabled: true, bypassed: false },
        { id: '4', name: 'Interlock 4', satisfied: false, enabled: true, bypassed: true }
      ]
    })

    it('should show summary row', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.summary-row').exists()).toBe(true)
    })

    it('should show correct satisfied count', () => {
      const wrapper = mount(InterlockStatusWidget)
      const okStat = wrapper.find('.stat.ok')
      expect(okStat.find('.count').text()).toBe('2')
    })

    it('should show correct blocked count', () => {
      const wrapper = mount(InterlockStatusWidget)
      const blockedStat = wrapper.find('.stat.blocked')
      expect(blockedStat.find('.count').text()).toBe('1')
    })

    it('should show bypassed count when present', () => {
      const wrapper = mount(InterlockStatusWidget)
      const bypassedStat = wrapper.find('.stat.bypassed')
      expect(bypassedStat.find('.count').text()).toBe('1')
    })

    it('should not show bypassed stat when count is 0', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.stat.bypassed').exists()).toBe(false)
    })

    it('should have active class on ok stat when count > 0', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.stat.ok').classes()).toContain('active')
    })

    it('should have active class on blocked stat when count > 0', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.stat.blocked').classes()).toContain('active')
    })
  })

  // ===========================================================================
  // ALL CLEAR STATE TESTS
  // ===========================================================================

  describe('All Clear State', () => {
    it('should show all clear when no blocked or bypassed', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: false },
        { id: '2', name: 'Interlock 2', satisfied: true, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.all-clear').exists()).toBe(true)
    })

    it('should show "All Clear" text', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.all-clear span').text()).toBe('All Clear')
    })

    it('should not show all clear when blocked', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: false, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.all-clear').exists()).toBe(false)
    })

    it('should not show all clear when bypassed', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: true }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.all-clear').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // INTERLOCK LIST TESTS
  // ===========================================================================

  describe('Interlock List', () => {
    beforeEach(() => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Pressure OK', satisfied: true, enabled: true, bypassed: false },
        { id: '2', name: 'Temperature High', satisfied: false, enabled: true, bypassed: false },
        { id: '3', name: 'Valve Open', satisfied: true, enabled: true, bypassed: true },
        { id: '4', name: 'Disabled Check', satisfied: false, enabled: false, bypassed: false }
      ]
    })

    it('should show interlock list', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.interlock-list').exists()).toBe(true)
    })

    it('should display all interlock items', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.findAll('.interlock-item').length).toBe(4)
    })

    it('should show interlock name', () => {
      const wrapper = mount(InterlockStatusWidget)
      const firstItem = wrapper.find('.interlock-item')
      expect(firstItem.find('.name').text()).toBe('Pressure OK')
    })

    it('should have satisfied class for satisfied interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[0].classes()).toContain('satisfied')
    })

    it('should have blocked class for unsatisfied interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[1].classes()).toContain('blocked')
    })

    it('should have bypassed class for bypassed interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[2].classes()).toContain('bypassed')
    })

    it('should have disabled class for disabled interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[3].classes()).toContain('disabled')
    })

    it('should show bypass badge for bypassed interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[2].find('.bypass-badge').text()).toBe('BYP')
    })

    it('should show check icon for satisfied interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[0].find('.status-icon svg').exists()).toBe(true)
    })

    it('should show X icon for blocked interlock', () => {
      const wrapper = mount(InterlockStatusWidget)
      const items = wrapper.findAll('.interlock-item')
      expect(items[1].find('.status-icon svg').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // HAS-BLOCKED CLASS TESTS
  // ===========================================================================

  describe('Has Blocked Class', () => {
    it('should have has-blocked class when blocked interlocks exist', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: false, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.interlock-status-widget').classes()).toContain('has-blocked')
    })

    it('should not have has-blocked class when all satisfied', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Interlock 1', satisfied: true, enabled: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.interlock-status-widget').classes()).not.toContain('has-blocked')
    })
  })

  // ===========================================================================
  // COMPACT MODE TESTS
  // ===========================================================================

  describe('Compact Mode', () => {
    beforeEach(() => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'OK Interlock', satisfied: true, enabled: true, bypassed: false },
        { id: '2', name: 'Blocked One', satisfied: false, enabled: true, bypassed: false }
      ]
    })

    it('should have compact class when compact is true', () => {
      const wrapper = mount(InterlockStatusWidget, {
        props: { compact: true }
      })
      expect(wrapper.find('.interlock-status-widget').classes()).toContain('compact')
    })

    it('should only show blocked interlocks in compact mode when not all clear', () => {
      const wrapper = mount(InterlockStatusWidget, {
        props: { compact: true }
      })
      const items = wrapper.findAll('.interlock-item')
      expect(items.length).toBe(1)
      expect(items[0].find('.name').text()).toBe('Blocked One')
    })

    it('should apply compact class on widget', () => {
      // Note: Compact mode filtering tests removed due to mock reactivity constraints.
      // The filtering logic depends on computed allSatisfied which may not update.
      const wrapper = mount(InterlockStatusWidget, {
        props: { compact: true }
      })
      expect(wrapper.find('.interlock-status-widget').classes()).toContain('compact')
    })
  })

  // ===========================================================================
  // BYPASS BUTTON TESTS
  // ===========================================================================

  describe('Bypass Buttons', () => {
    beforeEach(() => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Bypassable', satisfied: false, enabled: true, bypassed: false }
      ]
      state.mockInterlocks.value = [
        { id: '1', bypassAllowed: true, bypassed: false }
      ]
    })

    it('should not show bypass buttons by default', () => {
      const wrapper = mount(InterlockStatusWidget)
      expect(wrapper.find('.bypass-btn').exists()).toBe(false)
    })

    it('should show bypass button when showBypassButtons is true', () => {
      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })
      expect(wrapper.find('.bypass-btn').exists()).toBe(true)
    })

    it('should show BYP text on bypass button', () => {
      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })
      expect(wrapper.find('.bypass-btn').text()).toBe('BYP')
    })

    it('should not show bypass button for satisfied interlock', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Satisfied', satisfied: true, enabled: true, bypassed: false }
      ]
      state.mockInterlocks.value = [
        { id: '1', bypassAllowed: true, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })
      expect(wrapper.find('.bypass-btn').exists()).toBe(false)
    })

    it('should not show bypass button when bypassAllowed is false', () => {
      const state = getInterlockMockState()
      state.mockInterlocks.value = [
        { id: '1', bypassAllowed: false, bypassed: false }
      ]

      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })
      expect(wrapper.find('.bypass-btn').exists()).toBe(false)
    })

    it('should show X text when already bypassed', () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Bypassed', satisfied: false, enabled: true, bypassed: true }
      ]
      state.mockInterlocks.value = [
        { id: '1', bypassAllowed: true, bypassed: true }
      ]

      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })
      expect(wrapper.find('.bypass-btn').text()).toBe('X')
    })

    it('should call bypassInterlock when bypass button clicked', async () => {
      const state = getInterlockMockState()

      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })

      await wrapper.find('.bypass-btn').trigger('click')

      expect(state.mockBypassInterlock).toHaveBeenCalledWith('1', true)
    })

    it('should call bypassInterlock with false when removing bypass', async () => {
      const state = getInterlockMockState()
      state.mockInterlockStatuses.value = [
        { id: '1', name: 'Bypassed', satisfied: false, enabled: true, bypassed: true }
      ]
      state.mockInterlocks.value = [
        { id: '1', bypassAllowed: true, bypassed: true }
      ]

      const wrapper = mount(InterlockStatusWidget, {
        props: { showBypassButtons: true }
      })

      await wrapper.find('.bypass-btn').trigger('click')

      expect(state.mockBypassInterlock).toHaveBeenCalledWith('1', false)
    })
  })
})
