/**
 * Tests for TitleLabel
 *
 * Tests cover:
 * - Rendering with different props
 * - Text display
 * - Font size classes
 * - Text alignment (horizontal and vertical)
 * - Text color and background color
 * - Edit mode functionality
 * - Settings button visibility
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockEditMode = ref(false)
  const mockUpdateWidget = vi.fn()
  const mockUpdateWidgetStyle = vi.fn()

  ;(global as any).__mockTitleState = {
    mockEditMode,
    mockUpdateWidget,
    mockUpdateWidgetStyle
  }

  return {
    useDashboardStore: () => ({
      get editMode() { return mockEditMode.value },
      updateWidget: mockUpdateWidget,
      updateWidgetStyle: mockUpdateWidgetStyle
    })
  }
})

// Mock Teleport
vi.mock('vue', async () => {
  const actual = await vi.importActual('vue')
  return {
    ...actual,
    Teleport: { template: '<div class="teleport-mock"><slot /></div>' }
  }
})

// Import after mocking
import TitleLabel from './TitleLabel.vue'

describe('TitleLabel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = (global as any).__mockTitleState
    if (state) {
      state.mockEditMode.value = false
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(TitleLabel, {
        props: { widgetId: 'title-1' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render title-label class', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').exists()).toBe(true)
    })

    it('should render default text when no text prop', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.label-text').text()).toBe('Title')
    })

    it('should render custom text', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Custom Title' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.label-text').text()).toBe('Custom Title')
    })
  })

  // ===========================================================================
  // FONT SIZE TESTS
  // ===========================================================================

  describe('Font Size', () => {
    it('should have medium class by default', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('text-md')
    })

    it('should apply small font size class', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { fontSize: 'small' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('text-sm')
    })

    it('should apply large font size class', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { fontSize: 'large' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('text-lg')
    })

    it('should apply xlarge font size class', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { fontSize: 'xlarge' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('text-xl')
    })
  })

  // ===========================================================================
  // ALIGNMENT TESTS
  // ===========================================================================

  describe('Alignment', () => {
    it('should have left horizontal alignment by default', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('align-left')
    })

    it('should apply center horizontal alignment', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { textAlign: 'center' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('align-center')
    })

    it('should apply right horizontal alignment', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { textAlign: 'right' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('align-right')
    })

    it('should have center vertical alignment by default', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('valign-center')
    })

    it('should apply top vertical alignment', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { verticalAlign: 'top' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('valign-top')
    })

    it('should apply bottom vertical alignment', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { verticalAlign: 'bottom' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.title-label').classes()).toContain('valign-bottom')
    })
  })

  // ===========================================================================
  // COLOR TESTS
  // ===========================================================================

  describe('Colors', () => {
    it('should apply text color from style', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { textColor: '#ff0000' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      const style = wrapper.find('.title-label').attributes('style')
      expect(style).toMatch(/color:\s*(#ff0000|rgb\(255,\s*0,\s*0\))/)
    })

    it('should apply background color from style', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { backgroundColor: '#2d3748' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      const style = wrapper.find('.title-label').attributes('style')
      expect(style).toContain('background-color')
    })

    it('should not apply transparent background', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', style: { backgroundColor: 'transparent' } },
        global: {
          stubs: { Teleport: true }
        }
      })
      const style = wrapper.find('.title-label').attributes('style')
      if (style) {
        expect(style).not.toContain('background-color')
      }
    })
  })

  // ===========================================================================
  // EDIT MODE TESTS
  // ===========================================================================

  describe('Edit Mode', () => {
    it('should not show settings button when not in edit mode', () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.settings-btn').exists()).toBe(false)
    })

    it('should show settings button in edit mode', () => {
      const state = (global as any).__mockTitleState
      state.mockEditMode.value = true

      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1' },
        global: {
          stubs: { Teleport: true }
        }
      })
      expect(wrapper.find('.settings-btn').exists()).toBe(true)
    })

    it('should show input on double click in edit mode', async () => {
      const state = (global as any).__mockTitleState
      state.mockEditMode.value = true

      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Edit Me' },
        global: {
          stubs: { Teleport: true }
        }
      })

      await wrapper.find('.title-label').trigger('dblclick')

      expect(wrapper.find('.edit-input').exists()).toBe(true)
      expect(wrapper.find('.label-text').exists()).toBe(false)
    })

    it('should not show input on double click when not in edit mode', async () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Edit Me' },
        global: {
          stubs: { Teleport: true }
        }
      })

      await wrapper.find('.title-label').trigger('dblclick')

      expect(wrapper.find('.edit-input').exists()).toBe(false)
      expect(wrapper.find('.label-text').exists()).toBe(true)
    })

    it('should call updateWidget on blur', async () => {
      const state = (global as any).__mockTitleState
      state.mockEditMode.value = true

      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Original' },
        global: {
          stubs: { Teleport: true }
        }
      })

      await wrapper.find('.title-label').trigger('dblclick')

      const input = wrapper.find('.edit-input')
      await input.setValue('Updated')
      await input.trigger('blur')

      expect(state.mockUpdateWidget).toHaveBeenCalledWith('title-1', {
        text: 'Updated',
        label: 'Updated',
        title: undefined
      })
    })

    it('should save on Enter key', async () => {
      const state = (global as any).__mockTitleState
      state.mockEditMode.value = true

      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Original' },
        global: {
          stubs: { Teleport: true }
        }
      })

      await wrapper.find('.title-label').trigger('dblclick')

      const input = wrapper.find('.edit-input')
      await input.setValue('Updated')
      await input.trigger('keydown', { key: 'Enter' })

      expect(state.mockUpdateWidget).toHaveBeenCalled()
    })

    it('should cancel on Escape key', async () => {
      const state = (global as any).__mockTitleState
      state.mockEditMode.value = true

      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Original' },
        global: {
          stubs: { Teleport: true }
        }
      })

      await wrapper.find('.title-label').trigger('dblclick')

      const input = wrapper.find('.edit-input')
      await input.trigger('keydown', { key: 'Escape' })

      expect(wrapper.find('.edit-input').exists()).toBe(false)
      expect(wrapper.find('.label-text').exists()).toBe(true)
      expect(state.mockUpdateWidget).not.toHaveBeenCalled()
    })
  })

  // ===========================================================================
  // TEXT UPDATE WATCH TESTS
  // ===========================================================================

  describe('Text Prop Watch', () => {
    it('should update internal text when prop changes', async () => {
      const wrapper = mount(TitleLabel, {
        props: { widgetId: 'title-1', text: 'Original' },
        global: {
          stubs: { Teleport: true }
        }
      })

      expect(wrapper.find('.label-text').text()).toBe('Original')

      await wrapper.setProps({ text: 'Updated' })

      expect(wrapper.find('.label-text').text()).toBe('Updated')
    })
  })
})
