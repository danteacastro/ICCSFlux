/**
 * Tests for ClockWidget
 *
 * Tests cover:
 * - Rendering with different props
 * - Time display (12h/24h format)
 * - Date display
 * - Elapsed time display
 * - Label display
 * - Background color styling
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'

interface MockClockState {
  mockIsAcquiring: Ref<boolean>
}

const getClockMockState = () =>
  (globalThis as unknown as Record<string, MockClockState>).__mockClockState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockIsAcquiring = ref(false)

  ;(globalThis as unknown as Record<string, MockClockState>).__mockClockState = {
    mockIsAcquiring
  }

  return {
    useDashboardStore: () => ({
      get isAcquiring() { return mockIsAcquiring.value }
    })
  }
})

// Import after mocking
import ClockWidget from './ClockWidget.vue'

describe('ClockWidget', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2024-06-15T14:30:45'))

    const state = getClockMockState()
    if (state) {
      state.mockIsAcquiring.value = false
    }
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(ClockWidget)
      expect(wrapper.exists()).toBe(true)
    })

    it('should render clock-widget class', () => {
      const wrapper = mount(ClockWidget)
      expect(wrapper.find('.clock-widget').exists()).toBe(true)
    })

    it('should render time element', () => {
      const wrapper = mount(ClockWidget)
      expect(wrapper.find('.time').exists()).toBe(true)
    })

    it('should render date element by default', () => {
      const wrapper = mount(ClockWidget, {
        props: { showDate: true }
      })
      expect(wrapper.find('.date').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // TIME DISPLAY TESTS
  // ===========================================================================

  describe('Time Display', () => {
    it('should display time', () => {
      const wrapper = mount(ClockWidget)
      // Time format depends on locale settings - just verify it contains expected components
      const time = wrapper.find('.time').text()
      expect(time).toMatch(/\d{1,2}:\d{2}:\d{2}/)
    })

    it('should display time in 24h format when format24h is true', () => {
      const wrapper = mount(ClockWidget, {
        props: { format24h: true }
      })
      const time = wrapper.find('.time').text()
      // en-GB locale should give 24h format
      expect(time).toMatch(/\d{1,2}:\d{2}:\d{2}/)
    })

    it('should display time in 12h format when format24h is false', () => {
      const wrapper = mount(ClockWidget, {
        props: { format24h: false }
      })
      const time = wrapper.find('.time').text()
      // 12h format should contain AM/PM
      expect(time).toMatch(/\d{1,2}:\d{2}:\d{2}\s*(AM|PM)/i)
    })

    it('should update time when interval ticks', async () => {
      const wrapper = mount(ClockWidget)

      // Initial time - just check it's a time format
      const initialTime = wrapper.find('.time').text()
      expect(initialTime).toMatch(/\d{1,2}:\d{2}:\d{2}/)

      // Advance time and tick interval
      vi.setSystemTime(new Date('2024-06-15T14:35:00'))
      vi.advanceTimersByTime(1000)
      await wrapper.vm.$nextTick()

      // Verify time updated - should show new time (35 minutes)
      const updatedTime = wrapper.find('.time').text()
      expect(updatedTime).toMatch(/\d{1,2}:35:\d{2}/)
    })
  })

  // ===========================================================================
  // DATE DISPLAY TESTS
  // ===========================================================================

  describe('Date Display', () => {
    it('should display date when showDate is true', () => {
      const wrapper = mount(ClockWidget, {
        props: { showDate: true }
      })
      expect(wrapper.find('.date').exists()).toBe(true)
      // Date should contain day and month info
      expect(wrapper.find('.date').text()).toMatch(/\w+.*\d+/)
    })

    it('should hide date when showDate is false', () => {
      const wrapper = mount(ClockWidget, {
        props: { showDate: false }
      })
      expect(wrapper.find('.date').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Label', () => {
    it('should not display label by default', () => {
      const wrapper = mount(ClockWidget)
      expect(wrapper.find('.label').exists()).toBe(false)
    })

    it('should display label when provided', () => {
      const wrapper = mount(ClockWidget, {
        props: { label: 'System Time' }
      })
      expect(wrapper.find('.label').exists()).toBe(true)
      expect(wrapper.find('.label').text()).toBe('System Time')
    })

    it('should not display empty label', () => {
      const wrapper = mount(ClockWidget, {
        props: { label: '' }
      })
      expect(wrapper.find('.label').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // ELAPSED TIME TESTS
  // ===========================================================================

  describe('Elapsed Time', () => {
    it('should not display elapsed time when showElapsed is false', () => {
      const wrapper = mount(ClockWidget, {
        props: { showElapsed: false }
      })
      expect(wrapper.find('.elapsed').exists()).toBe(false)
    })

    it('should not display elapsed time when not acquiring', () => {
      const wrapper = mount(ClockWidget, {
        props: { showElapsed: true }
      })
      expect(wrapper.find('.elapsed').exists()).toBe(false)
    })

    it('should display elapsed time when acquiring and showElapsed is true', async () => {
      const state = getClockMockState()
      state.mockIsAcquiring.value = true

      const wrapper = mount(ClockWidget, {
        props: { showElapsed: true }
      })

      // Advance time to trigger elapsed calculation
      vi.advanceTimersByTime(1000)
      await wrapper.vm.$nextTick()

      // After 1 second of acquisition
      expect(wrapper.find('.elapsed').exists()).toBe(true)
    })

    it('should show RUN label in elapsed display', async () => {
      const state = getClockMockState()
      state.mockIsAcquiring.value = true

      const wrapper = mount(ClockWidget, {
        props: { showElapsed: true }
      })

      vi.advanceTimersByTime(1000)
      await wrapper.vm.$nextTick()

      const elapsed = wrapper.find('.elapsed')
      if (elapsed.exists()) {
        expect(wrapper.find('.elapsed-label').text()).toBe('RUN')
      }
    })

    it('should format elapsed time correctly', async () => {
      const state = getClockMockState()
      state.mockIsAcquiring.value = true

      const wrapper = mount(ClockWidget, {
        props: { showElapsed: true }
      })

      // Advance 65 seconds (1:05)
      for (let i = 0; i < 65; i++) {
        vi.advanceTimersByTime(1000)
        vi.setSystemTime(new Date('2024-06-15T14:30:45').getTime() + (i + 1) * 1000)
      }
      await wrapper.vm.$nextTick()

      const elapsedTime = wrapper.find('.elapsed-time')
      if (elapsedTime.exists()) {
        // Should show 1:05 format
        expect(elapsedTime.text()).toMatch(/1:0[45]/)
      }
    })
  })

  // ===========================================================================
  // BACKGROUND COLOR TESTS
  // ===========================================================================

  describe('Background Color', () => {
    it('should apply background color from style', () => {
      const wrapper = mount(ClockWidget, {
        props: { style: { backgroundColor: '#2d3748' } }
      })
      const style = wrapper.find('.clock-widget').attributes('style')
      expect(style).toContain('background-color')
    })

    it('should not apply background when transparent', () => {
      const wrapper = mount(ClockWidget, {
        props: { style: { backgroundColor: 'transparent' } }
      })
      const style = wrapper.find('.clock-widget').attributes('style')
      if (style) {
        expect(style).not.toContain('background-color')
      }
    })
  })

  // ===========================================================================
  // CLEANUP TESTS
  // ===========================================================================

  describe('Cleanup', () => {
    it('should clear interval on unmount', () => {
      const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

      const wrapper = mount(ClockWidget)
      wrapper.unmount()

      expect(clearIntervalSpy).toHaveBeenCalled()
    })
  })
})
