/**
 * Tests for SvgSymbolWidget
 *
 * Tests cover:
 * - Rendering with different props
 * - Symbol display and rotation
 * - Value display positions
 * - Label display
 * - Status states (active, stale, alarm, warning)
 * - Size variants
 * - Connection ports in edit mode
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'

// Mock the dashboard store
vi.mock('../stores/dashboard', () => {
  const { ref } = require('vue')

  const mockChannels = ref({
    'valve1': { name: 'Main Valve', unit: '', channel_type: 'digital_output' },
    'temp': { name: 'Temperature', unit: '°C' },
    'pump1': { name: 'Pump', unit: '', channel_type: 'digital_output' }
  })

  const mockValues = ref({
    'valve1': { value: 1, timestamp: Date.now() },
    'temp': { value: 75.5, timestamp: Date.now() },
    'pump1': { value: 0, timestamp: Date.now() }
  })

  const mockIsAcquiring = ref(true)
  const mockEditMode = ref(false)
  const mockPipeDrawingMode = ref(false)

  ;(global as any).__mockSymbolState = {
    mockChannels,
    mockValues,
    mockIsAcquiring,
    mockEditMode,
    mockPipeDrawingMode
  }

  return {
    useDashboardStore: () => ({
      get channels() { return mockChannels.value },
      get values() { return mockValues.value },
      get isAcquiring() { return mockIsAcquiring.value },
      get editMode() { return mockEditMode.value },
      get pipeDrawingMode() { return mockPipeDrawingMode.value }
    })
  }
})

// Mock symbols
vi.mock('../assets/symbols', () => ({
  SCADA_SYMBOLS: {
    solenoidValve: '<svg viewBox="0 0 64 64"><rect/></svg>',
    pump: '<svg viewBox="0 0 64 64"><circle/></svg>',
    tank: '<svg viewBox="0 0 64 64"><rect/></svg>'
  },
  SYMBOL_PORTS: {
    solenoidValve: [
      { id: 'in', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
      { id: 'out', x: 1, y: 0.5, direction: 'right', label: 'Outlet' }
    ],
    pump: [
      { id: 'in', x: 0.5, y: 1, direction: 'bottom' },
      { id: 'out', x: 0.5, y: 0, direction: 'top' }
    ]
  }
}))

// Import after mocking
import SvgSymbolWidget from './SvgSymbolWidget.vue'

describe('SvgSymbolWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const state = (global as any).__mockSymbolState

    if (state) {
      state.mockIsAcquiring.value = true
      state.mockEditMode.value = false
      state.mockPipeDrawingMode.value = false
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now() },
        'temp': { value: 75.5, timestamp: Date.now() },
        'pump1': { value: 0, timestamp: Date.now() }
      }
    }
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render without errors', () => {
      const wrapper = shallowMount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.exists()).toBe(true)
    })

    it('should render svg-symbol-widget class', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').exists()).toBe(true)
    })

    it('should render symbol container', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.symbol-container').exists()).toBe(true)
    })

    it('should render symbol element', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.symbol').exists()).toBe(true)
    })

    it('should render SVG inside symbol', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.symbol svg').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // LABEL TESTS
  // ===========================================================================

  describe('Labels', () => {
    it('should display channel ID as label by default', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.symbol-label').text()).toBe('valve1')
    })

    it('should display custom label when provided', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', label: 'Main Valve' }
      })
      expect(wrapper.find('.symbol-label').text()).toBe('Main Valve')
    })

    it('should hide label when showLabel is false', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', showLabel: false }
      })
      expect(wrapper.find('.symbol-label').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // VALUE DISPLAY TESTS
  // ===========================================================================

  describe('Value Display', () => {
    it('should display ON for digital output with value 1', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.value').text()).toBe('ON')
    })

    it('should display OFF for digital output with value 0', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.value').text()).toBe('OFF')
    })

    it('should display numeric value for analog channels', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'temp' }
      })
      expect(wrapper.find('.value').text()).toBe('75.5')
    })

    it('should display value with specified decimals', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'temp', decimals: 2 }
      })
      expect(wrapper.find('.value').text()).toBe('75.50')
    })

    it('should display -- when stale', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now() - 10000 }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.value').text()).toBe('--')
    })

    it('should hide value when showValue is false', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', showValue: false }
      })
      expect(wrapper.find('.value-display').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // VALUE POSITION TESTS
  // ===========================================================================

  describe('Value Position', () => {
    it('should show value at bottom by default', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.value-display.bottom').exists()).toBe(true)
    })

    it('should show value at top', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', valuePosition: 'top' }
      })
      expect(wrapper.find('.value-display.top').exists()).toBe(true)
    })

    it('should show value on left', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', valuePosition: 'left' }
      })
      expect(wrapper.find('.value-display.side').exists()).toBe(true)
    })

    it('should show value on right', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', valuePosition: 'right' }
      })
      expect(wrapper.find('.value-display.side').exists()).toBe(true)
    })

    it('should show value inside', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', valuePosition: 'inside' }
      })
      expect(wrapper.find('.value-display.inside').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // SIZE TESTS
  // ===========================================================================

  describe('Size Variants', () => {
    it('should apply medium size by default', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('medium')
    })

    it('should apply small size', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', size: 'small' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('small')
    })

    it('should apply large size', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', size: 'large' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('large')
    })
  })

  // ===========================================================================
  // ROTATION TESTS
  // ===========================================================================

  describe('Rotation', () => {
    it('should have no rotation by default', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      const symbol = wrapper.find('.symbol')
      const style = symbol.attributes('style')
      // No transform or undefined
      if (style) {
        expect(style).not.toContain('rotate')
      }
    })

    it('should apply 90 degree rotation', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', rotation: 90 }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('rotate(90deg)')
    })

    it('should apply 180 degree rotation', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', rotation: 180 }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('rotate(180deg)')
    })

    it('should apply 270 degree rotation', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', rotation: 270 }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('rotate(270deg)')
    })
  })

  // ===========================================================================
  // STATUS STATE TESTS
  // ===========================================================================

  describe('Status States', () => {
    it('should have active class when digital output is on', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('active')
    })

    it('should have normal class when digital output is off', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'pump1': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'pump1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('normal')
    })

    it('should have stale class when data is stale', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now() - 10000 }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('stale')
    })

    it('should have alarm class when in alarm', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now(), alarm: true }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('alarm')
    })

    it('should have warning class when in warning', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now(), warning: true }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.svg-symbol-widget').classes()).toContain('warning')
    })
  })

  // ===========================================================================
  // SYMBOL COLOR TESTS
  // ===========================================================================

  describe('Symbol Color', () => {
    it('should use green color when active', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('#22c55e')
    })

    it('should use blue color for normal state', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'pump1': { value: 0, timestamp: Date.now() }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'pump1' }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('#60a5fa')
    })

    it('should use red color for alarm', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now(), alarm: true }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('#ef4444')
    })

    it('should use yellow color for warning', () => {
      const state = (global as any).__mockSymbolState
      state.mockValues.value = {
        'valve1': { value: 1, timestamp: Date.now(), warning: true }
      }

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('#fbbf24')
    })

    it('should use custom accent color when provided', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', accentColor: '#ff00ff' }
      })
      const symbol = wrapper.find('.symbol')
      expect(symbol.attributes('style')).toContain('#ff00ff')
    })
  })

  // ===========================================================================
  // CONNECTION PORTS TESTS
  // ===========================================================================

  describe('Connection Ports', () => {
    it('should not show ports when not in edit mode', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', widgetId: 'widget-1' }
      })
      expect(wrapper.find('.connection-port').exists()).toBe(false)
    })

    it('should not show ports when in edit mode but not pipe drawing', () => {
      const state = (global as any).__mockSymbolState
      state.mockEditMode.value = true

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', widgetId: 'widget-1' }
      })
      expect(wrapper.find('.connection-port').exists()).toBe(false)
    })

    it('should show ports when in edit mode and pipe drawing mode', () => {
      const state = (global as any).__mockSymbolState
      state.mockEditMode.value = true
      state.mockPipeDrawingMode.value = true

      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', widgetId: 'widget-1' }
      })
      expect(wrapper.findAll('.connection-port').length).toBe(2)
    })
  })

  // ===========================================================================
  // SYMBOL TYPE TESTS
  // ===========================================================================

  describe('Symbol Type', () => {
    it('should render solenoidValve by default', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1' }
      })
      expect(wrapper.find('.symbol svg rect').exists()).toBe(true)
    })

    it('should render specified symbol type', () => {
      const wrapper = mount(SvgSymbolWidget, {
        props: { channel: 'valve1', symbol: 'pump' }
      })
      expect(wrapper.find('.symbol svg circle').exists()).toBe(true)
    })
  })
})
