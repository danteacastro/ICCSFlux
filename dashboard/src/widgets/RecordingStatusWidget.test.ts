/**
 * Tests for RecordingStatusWidget
 *
 * CRITICAL WIDGET - Controls and displays recording session state
 *
 * Tests cover:
 * - Idle state display
 * - Recording state display
 * - Duration formatting
 * - Filename display and truncation
 * - Sample count formatting (K/M suffixes)
 * - File size formatting (B/KB/MB/GB)
 * - Recording mode display
 * - CSS class states
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockStatus = ref<any>(null)

  ;(global as any).__mockRecordingState = {
    mockStatus
  }

  return {
    useDashboardStore: () => ({
      get status() { return mockStatus.value }
    })
  }
})

// Import after mocking
import RecordingStatusWidget from './RecordingStatusWidget.vue'

describe('RecordingStatusWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = (global as any).__mockRecordingState
    if (state) {
      state.mockStatus.value = null
    }
  })

  // ===========================================================================
  // IDLE STATE TESTS
  // ===========================================================================

  describe('Idle State', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(RecordingStatusWidget)
      expect(wrapper.exists()).toBe(true)
    })

    it('should have recording-status-widget class', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.recording-status-widget').exists()).toBe(true)
    })

    it('should show IDLE indicator when not recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator .text').text()).toBe('IDLE')
    })

    it('should not have active class on indicator when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator').classes()).not.toContain('active')
    })

    it('should show "Not recording" message when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.idle-message').text()).toBe('Not recording')
    })

    it('should not have recording class when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.recording-status-widget').classes()).not.toContain('recording')
    })

    it('should not show duration when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.duration').exists()).toBe(false)
    })

    it('should not show filename when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.filename').exists()).toBe(false)
    })

    it('should not show stats when idle', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stats').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // RECORDING STATE TESTS
  // ===========================================================================

  describe('Recording State', () => {
    beforeEach(() => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_duration: '00:05:30',
        recording_filename: 'test_session.csv',
        recording_samples: 1500,
        recording_bytes: 256000,
        recording_mode: 'manual'
      }
    })

    it('should show REC indicator when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator .text').text()).toBe('REC')
    })

    it('should have active class on indicator when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator').classes()).toContain('active')
    })

    it('should have recording class on widget when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.recording-status-widget').classes()).toContain('recording')
    })

    it('should show duration when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.duration').text()).toBe('00:05:30')
    })

    it('should show filename when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.filename').text()).toBe('test_session.csv')
    })

    it('should show stats section when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stats').exists()).toBe(true)
    })

    it('should not show idle message when recording', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.idle-message').exists()).toBe(false)
    })

    it('should show recording mode', () => {
      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stat.mode .value').text()).toBe('manual')
    })
  })

  // ===========================================================================
  // DURATION FORMATTING TESTS
  // ===========================================================================

  describe('Duration Formatting', () => {
    it('should display duration from status', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_duration: '01:30:45',
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.duration').text()).toBe('01:30:45')
    })

    it('should show 00:00:00 when duration not set', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.duration').text()).toBe('00:00:00')
    })
  })

  // ===========================================================================
  // FILENAME TRUNCATION TESTS
  // ===========================================================================

  describe('Filename Truncation', () => {
    it('should display short filename as-is', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'short.csv',
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.filename').text()).toBe('short.csv')
    })

    it('should truncate long filename with ellipsis prefix', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'very_long_recording_filename_that_exceeds_25_chars.csv',
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      const filename = wrapper.find('.filename').text()
      expect(filename.startsWith('...')).toBe(true)
      expect(filename.length).toBeLessThanOrEqual(25)
    })

    it('should show -- when filename not set', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.filename').text()).toBe('--')
    })

    it('should have title attribute with full filename', () => {
      const state = (global as any).__mockRecordingState
      const fullFilename = 'very_long_recording_filename_that_exceeds_25_chars.csv'
      state.mockStatus.value = {
        recording: true,
        recording_filename: fullFilename,
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.filename').attributes('title')).toBe(fullFilename)
    })
  })

  // ===========================================================================
  // SAMPLE COUNT FORMATTING TESTS
  // ===========================================================================

  describe('Sample Count Formatting', () => {
    it('should display raw number for small counts', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 500,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      const samplesStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'samples')
      expect(samplesStat?.find('.value').text()).toBe('500')
    })

    it('should format thousands with K suffix', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 5000,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      const samplesStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'samples')
      expect(samplesStat?.find('.value').text()).toBe('5.0K')
    })

    it('should format millions with M suffix', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 2500000,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      const samplesStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'samples')
      expect(samplesStat?.find('.value').text()).toBe('2.5M')
    })

    it('should show -- when samples not set', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      const samplesStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'samples')
      expect(samplesStat?.find('.value').text()).toBe('--')
    })
  })

  // ===========================================================================
  // FILE SIZE FORMATTING TESTS
  // ===========================================================================

  describe('File Size Formatting', () => {
    it('should display bytes for small sizes', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 500
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      expect(sizeStat?.find('.value').text()).toBe('500 B')
    })

    it('should format kilobytes', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 5120  // 5 KB
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      expect(sizeStat?.find('.value').text()).toBe('5 KB')
    })

    it('should format megabytes', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 5242880  // 5 MB
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      expect(sizeStat?.find('.value').text()).toBe('5.0 MB')
    })

    it('should format gigabytes', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 2147483648  // 2 GB
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      expect(sizeStat?.find('.value').text()).toBe('2.00 GB')
    })

    it('should show -- when bytes not set', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      expect(sizeStat?.find('.value').text()).toBe('--')
    })
  })

  // ===========================================================================
  // RECORDING MODE TESTS
  // ===========================================================================

  describe('Recording Mode', () => {
    it('should display manual mode', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 1000,
        recording_mode: 'manual'
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stat.mode .value').text()).toBe('manual')
    })

    it('should display triggered mode', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 1000,
        recording_mode: 'triggered'
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stat.mode .value').text()).toBe('triggered')
    })

    it('should default to manual mode when not set', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 1000
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.stat.mode .value').text()).toBe('manual')
    })
  })

  // ===========================================================================
  // EDGE CASES
  // ===========================================================================

  describe('Edge Cases', () => {
    it('should handle null status', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = null

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator .text').text()).toBe('IDLE')
    })

    it('should handle undefined status', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = undefined

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator .text').text()).toBe('IDLE')
    })

    it('should handle recording: false explicitly', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: false
      }

      const wrapper = mount(RecordingStatusWidget)
      expect(wrapper.find('.indicator .text').text()).toBe('IDLE')
    })

    it('should handle zero samples (shows -- because 0 is falsy)', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 0,
        recording_bytes: 0
      }

      const wrapper = mount(RecordingStatusWidget)
      const samplesStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'samples')
      // Component treats 0 as falsy and returns '--'
      expect(samplesStat?.find('.value').text()).toBe('--')
    })

    it('should handle zero bytes (shows -- because 0 is falsy)', () => {
      const state = (global as any).__mockRecordingState
      state.mockStatus.value = {
        recording: true,
        recording_filename: 'test.csv',
        recording_samples: 100,
        recording_bytes: 0
      }

      const wrapper = mount(RecordingStatusWidget)
      const sizeStat = wrapper.findAll('.stat').find(s => s.find('.label').text() === 'size')
      // Component treats 0 as falsy and returns '--'
      expect(sizeStat?.find('.value').text()).toBe('--')
    })
  })
})
