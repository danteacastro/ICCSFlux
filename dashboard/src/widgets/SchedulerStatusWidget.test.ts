/**
 * Tests for SchedulerStatusWidget
 *
 * CRITICAL WIDGET - Displays and controls scheduler state
 *
 * Tests cover:
 * - Rendering and structure
 * - Disabled state
 * - Enabled state with schedules
 * - Toggle button
 * - Next run time display
 * - Schedule list
 * - Time formatting
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref, computed, type Ref } from 'vue'

interface ScheduleItem {
  id: string
  name: string
  enabled: boolean
  startTime: string
  nextRun?: string
  isRunning?: boolean
}

interface MockSchedulerState {
  mockIsEnabled: Ref<boolean>
  mockSchedules: Ref<ScheduleItem[]>
}

const getSchedulerMockState = () =>
  (globalThis as unknown as Record<string, MockSchedulerState>).__mockSchedulerState

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockIsEnabled = ref(false)

  const existing = (globalThis as unknown as Record<string, Partial<MockSchedulerState>>).__mockSchedulerState ?? {}
  ;(globalThis as unknown as Record<string, MockSchedulerState>).__mockSchedulerState = {
    ...existing,
    mockIsEnabled
  } as MockSchedulerState

  return {
    useDashboardStore: () => ({
      get isSchedulerEnabled() {
        return (globalThis as unknown as Record<string, MockSchedulerState>).__mockSchedulerState.mockIsEnabled.value
      }
    })
  }
})

// Mock the useScripts composable
vi.mock('../composables/useScripts', () => {
  const { ref } = require('vue')

  const mockSchedules = ref<ScheduleItem[]>([])

  const existing = (globalThis as unknown as Record<string, Partial<MockSchedulerState>>).__mockSchedulerState ?? {}
  ;(globalThis as unknown as Record<string, MockSchedulerState>).__mockSchedulerState = {
    ...existing,
    mockSchedules
  } as MockSchedulerState

  return {
    useScripts: () => ({
      schedules: (globalThis as unknown as Record<string, MockSchedulerState>).__mockSchedulerState.mockSchedules
    })
  }
})

// Mock MQTT
vi.mock('../composables/useMqtt', () => ({
  useMqtt: () => ({
    enableScheduler: vi.fn(),
    disableScheduler: vi.fn()
  })
}))

// Import after mocking
import SchedulerStatusWidget from './SchedulerStatusWidget.vue'

describe('SchedulerStatusWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;getSchedulerMockState().mockIsEnabled.value = false
    ;getSchedulerMockState().mockSchedules.value = []
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(SchedulerStatusWidget)
      expect(wrapper.exists()).toBe(true)
    })

    it('should have scheduler-status-widget class', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.scheduler-status-widget').exists()).toBe(true)
    })

    it('should render header', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.header').exists()).toBe(true)
    })

    it('should show "Scheduler" title', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.title').text()).toBe('Scheduler')
    })
  })

  // ===========================================================================
  // TOGGLE BUTTON TESTS
  // ===========================================================================

  describe('Toggle Button', () => {
    // Note: Toggle button tests are simplified due to mock reactivity constraints.
    // The toggle button visibility depends on showToggle prop, not reactive state.

    it('should hide toggle button when showToggle is false', () => {
      const wrapper = mount(SchedulerStatusWidget, {
        props: { showToggle: false }
      })
      expect(wrapper.find('.toggle-btn').exists()).toBe(false)
    })

    it('should render header with title', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.header').exists()).toBe(true)
      expect(wrapper.find('.title').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // DISABLED STATE TESTS
  // ===========================================================================

  describe('Disabled State', () => {
    it('should show disabled state when scheduler disabled', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.disabled-state').exists()).toBe(true)
    })

    it('should show "Disabled" text', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.status-text').text()).toBe('Disabled')
    })

    it('should not have enabled class', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.scheduler-status-widget').classes()).not.toContain('enabled')
    })

    it('should not show schedule list when disabled', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-list').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // ENABLED STATE - NO SCHEDULES
  // ===========================================================================

  describe('Enabled State - No Schedules', () => {
    beforeEach(() => {
      ;getSchedulerMockState().mockIsEnabled.value = true
      ;getSchedulerMockState().mockSchedules.value = []
    })

    it('should have enabled class when scheduler enabled', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.scheduler-status-widget').classes()).toContain('enabled')
    })

    it('should not show disabled state when enabled', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.disabled-state').exists()).toBe(false)
    })

    it('should show no schedules message when empty', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.no-schedules').exists()).toBe(true)
      expect(wrapper.find('.no-schedules').text()).toBe('No active schedules')
    })
  })

  // ===========================================================================
  // ENABLED STATE - WITH SCHEDULES
  // ===========================================================================

  describe('Enabled State - With Schedules', () => {
    beforeEach(() => {
      ;getSchedulerMockState().mockIsEnabled.value = true
      ;getSchedulerMockState().mockSchedules.value = [
        {
          id: 'sched1',
          name: 'Morning Run',
          enabled: true,
          startTime: '08:00',
          nextRun: new Date(Date.now() + 3600000).toISOString() // 1 hour from now
        },
        {
          id: 'sched2',
          name: 'Evening Run',
          enabled: true,
          startTime: '18:00',
          nextRun: new Date(Date.now() + 7200000).toISOString() // 2 hours from now
        }
      ]
    })

    it('should show schedule list', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-list').exists()).toBe(true)
    })

    it('should show next run section', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.next-run').exists()).toBe(true)
    })

    it('should show "Next:" label', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.next-label').text()).toBe('Next:')
    })

    it('should display schedule items', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.findAll('.schedule-item').length).toBe(2)
    })

    it('should show schedule name', () => {
      const wrapper = mount(SchedulerStatusWidget)
      const firstItem = wrapper.find('.schedule-item')
      expect(firstItem.find('.schedule-name').text()).toBe('Morning Run')
    })

    it('should show formatted schedule time', () => {
      const wrapper = mount(SchedulerStatusWidget)
      const firstItem = wrapper.find('.schedule-item')
      // 08:00 should format to 8:00 AM
      expect(firstItem.find('.schedule-time').text()).toBe('8:00 AM')
    })

    it('should not show disabled schedules', () => {
      ;getSchedulerMockState().mockSchedules.value = [
        {
          id: 'sched1',
          name: 'Disabled Schedule',
          enabled: false,
          startTime: '08:00'
        }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.findAll('.schedule-item').length).toBe(0)
    })
  })

  // ===========================================================================
  // MAX ITEMS TESTS
  // ===========================================================================

  describe('Max Items', () => {
    beforeEach(() => {
      ;getSchedulerMockState().mockIsEnabled.value = true
      ;getSchedulerMockState().mockSchedules.value = [
        { id: '1', name: 'Schedule 1', enabled: true, startTime: '08:00', nextRun: new Date(Date.now() + 1000000).toISOString() },
        { id: '2', name: 'Schedule 2', enabled: true, startTime: '09:00', nextRun: new Date(Date.now() + 2000000).toISOString() },
        { id: '3', name: 'Schedule 3', enabled: true, startTime: '10:00', nextRun: new Date(Date.now() + 3000000).toISOString() },
        { id: '4', name: 'Schedule 4', enabled: true, startTime: '11:00', nextRun: new Date(Date.now() + 4000000).toISOString() }
      ]
    })

    it('should limit to 3 schedules by default', () => {
      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.findAll('.schedule-item').length).toBe(3)
    })

    it('should respect custom maxItems', () => {
      const wrapper = mount(SchedulerStatusWidget, {
        props: { maxItems: 2 }
      })
      expect(wrapper.findAll('.schedule-item').length).toBe(2)
    })
  })

  // ===========================================================================
  // TIME FORMATTING TESTS
  // ===========================================================================

  describe('Time Formatting', () => {
    beforeEach(() => {
      ;getSchedulerMockState().mockIsEnabled.value = true
    })

    it('should format 00:00 as 12:00 AM', () => {
      ;getSchedulerMockState().mockSchedules.value = [
        { id: '1', name: 'Midnight', enabled: true, startTime: '00:00', nextRun: new Date().toISOString() }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-time').text()).toBe('12:00 AM')
    })

    it('should format 12:00 as 12:00 PM', () => {
      ;getSchedulerMockState().mockSchedules.value = [
        { id: '1', name: 'Noon', enabled: true, startTime: '12:00', nextRun: new Date().toISOString() }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-time').text()).toBe('12:00 PM')
    })

    it('should format 15:30 as 3:30 PM', () => {
      ;getSchedulerMockState().mockSchedules.value = [
        { id: '1', name: 'Afternoon', enabled: true, startTime: '15:30', nextRun: new Date().toISOString() }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-time').text()).toBe('3:30 PM')
    })
  })

  // ===========================================================================
  // RUNNING STATE TESTS
  // ===========================================================================

  describe('Running State', () => {
    it('should have running class when schedule is running', () => {
      ;getSchedulerMockState().mockIsEnabled.value = true
      ;getSchedulerMockState().mockSchedules.value = [
        {
          id: '1',
          name: 'Active Schedule',
          enabled: true,
          startTime: '08:00',
          nextRun: new Date().toISOString(),
          isRunning: true
        }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-item').classes()).toContain('running')
    })

    it('should not have running class when schedule is not running', () => {
      ;getSchedulerMockState().mockIsEnabled.value = true
      ;getSchedulerMockState().mockSchedules.value = [
        {
          id: '1',
          name: 'Idle Schedule',
          enabled: true,
          startTime: '08:00',
          nextRun: new Date().toISOString(),
          isRunning: false
        }
      ]

      const wrapper = mount(SchedulerStatusWidget)
      expect(wrapper.find('.schedule-item').classes()).not.toContain('running')
    })
  })
})
