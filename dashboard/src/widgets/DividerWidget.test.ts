/**
 * Tests for DividerWidget
 *
 * Tests cover:
 * - Rendering with different props
 * - Horizontal/vertical orientation
 * - Label display
 * - Line color and style
 */

import { describe, it, expect } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'

import DividerWidget from './DividerWidget.vue'

describe('DividerWidget', () => {
  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(DividerWidget)
      expect(wrapper.exists()).toBe(true)
    })

    it('should render divider-widget class', () => {
      const wrapper = mount(DividerWidget)
      expect(wrapper.find('.divider-widget').exists()).toBe(true)
    })

    it('should render horizontal divider by default', () => {
      const wrapper = mount(DividerWidget)
      expect(wrapper.find('.divider-line.horizontal').exists()).toBe(true)
      expect(wrapper.find('.divider-line.vertical').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // ORIENTATION TESTS
  // ===========================================================================

  describe('Orientation', () => {
    it('should render horizontal divider when orientation is horizontal', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'horizontal' }
      })
      expect(wrapper.find('.divider-line.horizontal').exists()).toBe(true)
      expect(wrapper.find('.divider-line.vertical').exists()).toBe(false)
    })

    it('should render vertical divider when orientation is vertical', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'vertical' }
      })
      expect(wrapper.find('.divider-line.vertical').exists()).toBe(true)
      expect(wrapper.find('.divider-line.horizontal').exists()).toBe(false)
    })

    it('should add vertical class to container when vertical', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'vertical' }
      })
      expect(wrapper.find('.divider-widget').classes()).toContain('vertical')
    })

    it('should not have vertical class when horizontal', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'horizontal' }
      })
      expect(wrapper.find('.divider-widget').classes()).not.toContain('vertical')
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Label', () => {
    it('should not render label when not provided', () => {
      const wrapper = mount(DividerWidget)
      expect(wrapper.find('.divider-label').exists()).toBe(false)
    })

    it('should render label when provided', () => {
      const wrapper = mount(DividerWidget, {
        props: { label: 'Section' }
      })
      expect(wrapper.find('.divider-label').exists()).toBe(true)
      expect(wrapper.find('.divider-label').text()).toBe('Section')
    })

    it('should render label only in horizontal mode', () => {
      const wrapper = mount(DividerWidget, {
        props: { label: 'Section', orientation: 'horizontal' }
      })
      expect(wrapper.find('.divider-label').exists()).toBe(true)
    })

    it('should not render label in vertical mode', () => {
      const wrapper = mount(DividerWidget, {
        props: { label: 'Section', orientation: 'vertical' }
      })
      expect(wrapper.find('.divider-label').exists()).toBe(false)
    })

    it('should apply line color to label', () => {
      const wrapper = mount(DividerWidget, {
        props: { label: 'Section', style: { lineColor: '#ff0000' } }
      })
      const label = wrapper.find('.divider-label')
      expect(label.attributes('style')).toMatch(/color:\s*(#ff0000|rgb\(255,\s*0,\s*0\))/)
    })
  })

  // ===========================================================================
  // LINE COLOR TESTS
  // ===========================================================================

  describe('Line Color', () => {
    it('should use default blue color', () => {
      const wrapper = mount(DividerWidget)
      const line = wrapper.find('.divider-line.horizontal')
      expect(line.attributes('style')).toMatch(/border-top-color:\s*(#3b82f6|rgb\(59,\s*130,\s*246\))/)
    })

    it('should apply custom line color', () => {
      const wrapper = mount(DividerWidget, {
        props: { style: { lineColor: '#ff0000' } }
      })
      const line = wrapper.find('.divider-line.horizontal')
      expect(line.attributes('style')).toMatch(/border-top-color:\s*(#ff0000|rgb\(255,\s*0,\s*0\))/)
    })

    it('should apply line color to vertical divider', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'vertical', style: { lineColor: '#00ff00' } }
      })
      const line = wrapper.find('.divider-line.vertical')
      expect(line.attributes('style')).toMatch(/border-left-color:\s*(#00ff00|rgb\(0,\s*255,\s*0\))/)
    })
  })

  // ===========================================================================
  // LINE STYLE TESTS
  // ===========================================================================

  describe('Line Style', () => {
    it('should use solid style by default', () => {
      const wrapper = mount(DividerWidget)
      const line = wrapper.find('.divider-line.horizontal')
      expect(line.attributes('style')).toContain('border-top-style: solid')
    })

    it('should apply dashed line style', () => {
      const wrapper = mount(DividerWidget, {
        props: { style: { lineStyle: 'dashed' } }
      })
      const line = wrapper.find('.divider-line.horizontal')
      expect(line.attributes('style')).toContain('border-top-style: dashed')
    })

    it('should apply dotted line style', () => {
      const wrapper = mount(DividerWidget, {
        props: { style: { lineStyle: 'dotted' } }
      })
      const line = wrapper.find('.divider-line.horizontal')
      expect(line.attributes('style')).toContain('border-top-style: dotted')
    })

    it('should apply line style to vertical divider', () => {
      const wrapper = mount(DividerWidget, {
        props: { orientation: 'vertical', style: { lineStyle: 'dashed' } }
      })
      const line = wrapper.find('.divider-line.vertical')
      expect(line.attributes('style')).toContain('border-left-style: dashed')
    })
  })

  // ===========================================================================
  // COMBINED PROPS TESTS
  // ===========================================================================

  describe('Combined Props', () => {
    it('should apply all horizontal props together', () => {
      const wrapper = mount(DividerWidget, {
        props: {
          label: 'Test Section',
          orientation: 'horizontal',
          style: {
            lineColor: '#ff6600',
            lineStyle: 'dashed'
          }
        }
      })

      const line = wrapper.find('.divider-line.horizontal')
      const label = wrapper.find('.divider-label')

      expect(label.text()).toBe('Test Section')
      expect(line.attributes('style')).toMatch(/border-top-color:\s*(#ff6600|rgb\(255,\s*102,\s*0\))/)
      expect(line.attributes('style')).toContain('border-top-style: dashed')
    })

    it('should apply all vertical props together', () => {
      const wrapper = mount(DividerWidget, {
        props: {
          orientation: 'vertical',
          style: {
            lineColor: '#00ff00',
            lineStyle: 'dotted'
          }
        }
      })

      const widget = wrapper.find('.divider-widget')
      const line = wrapper.find('.divider-line.vertical')

      expect(widget.classes()).toContain('vertical')
      expect(line.attributes('style')).toMatch(/border-left-color:\s*(#00ff00|rgb\(0,\s*255,\s*0\))/)
      expect(line.attributes('style')).toContain('border-left-style: dotted')
    })
  })
})
