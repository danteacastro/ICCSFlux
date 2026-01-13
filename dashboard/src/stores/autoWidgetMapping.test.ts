import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from './dashboard'
import type { ChannelType } from '../types'

describe('Auto-Widget Generation - Channel Type Mapping', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('should map ALL channel types to appropriate widgets', () => {
    const store = useDashboardStore()

    // Define test channels for EVERY channel type
    const testChannels: Record<string, { channel_type: ChannelType; expectedWidget: string }> = {
      // ========================================
      // ANALOG INPUTS → NUMERIC DISPLAY
      // ========================================
      'TC_01': { channel_type: 'thermocouple', expectedWidget: 'numeric' },
      'RTD_01': { channel_type: 'rtd', expectedWidget: 'numeric' },
      'AI_VOLT_01': { channel_type: 'voltage', expectedWidget: 'numeric' },
      'AI_CURR_01': { channel_type: 'current', expectedWidget: 'numeric' },
      'STRAIN_01': { channel_type: 'strain', expectedWidget: 'numeric' },
      'ACCEL_01': { channel_type: 'iepe', expectedWidget: 'numeric' },
      'RES_01': { channel_type: 'resistance', expectedWidget: 'numeric' },
      'MB_REG_01': { channel_type: 'modbus_register', expectedWidget: 'numeric' },
      'CTR_01': { channel_type: 'counter', expectedWidget: 'numeric' },

      // ========================================
      // DIGITAL INPUTS → LED INDICATOR
      // ========================================
      'DI_01': { channel_type: 'digital_input', expectedWidget: 'led' },
      'MB_COIL_01': { channel_type: 'modbus_coil', expectedWidget: 'led' },

      // ========================================
      // DIGITAL OUTPUTS → TOGGLE SWITCH
      // ========================================
      'DO_01': { channel_type: 'digital_output', expectedWidget: 'toggle' },

      // ========================================
      // ANALOG OUTPUTS → SETPOINT CONTROL
      // ========================================
      'AO_01': { channel_type: 'analog_output', expectedWidget: 'setpoint' },
    }

    // Set up channels in store
    const channelConfigs: any = {}
    for (const [name, config] of Object.entries(testChannels)) {
      channelConfigs[name] = {
        name,
        channel_type: config.channel_type,
        unit: 'unit',
        group: 'test',
        visible: true
      }
    }
    store.setChannels(channelConfigs)

    // Generate widgets
    const count = store.autoGenerateWidgets()

    // Verify correct number of widgets created
    expect(count).toBe(Object.keys(testChannels).length)

    // Verify each widget has the correct type
    const currentPage = store.pages.find(p => p.id === store.currentPageId)
    expect(currentPage).toBeDefined()

    for (const [channelName, config] of Object.entries(testChannels)) {
      const widget = currentPage!.widgets.find(w => w.channel === channelName)
      expect(widget, `Widget for ${channelName} (${config.channel_type}) should exist`).toBeDefined()
      expect(widget?.type, `Widget for ${channelName} (${config.channel_type})`).toBe(config.expectedWidget)
    }
  })

  it('should create correct widget sizes for each type', () => {
    const store = useDashboardStore()

    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp' },
      'DI_01': { name: 'DI_01', channel_type: 'digital_input', unit: '', group: 'digital' },
      'DO_01': { name: 'DO_01', channel_type: 'digital_output', unit: '', group: 'digital' },
      'AO_01': { name: 'AO_01', channel_type: 'analog_output', unit: 'V', group: 'output' },
    }
    store.setChannels(channelConfigs)

    store.autoGenerateWidgets({ widgetSize: 'normal' })

    const currentPage = store.pages.find(p => p.id === store.currentPageId)

    // Numeric display (thermocouple) - 3x1 in normal mode
    const tcWidget = currentPage!.widgets.find(w => w.channel === 'TC_01')
    expect(tcWidget?.w).toBe(3)
    expect(tcWidget?.h).toBe(1)

    // LED (digital_input) - 1x1 in normal mode
    const diWidget = currentPage!.widgets.find(w => w.channel === 'DI_01')
    expect(diWidget?.w).toBe(1)
    expect(diWidget?.h).toBe(1)

    // Toggle (digital_output) - 1x1 in normal mode
    const doWidget = currentPage!.widgets.find(w => w.channel === 'DO_01')
    expect(doWidget?.w).toBe(1)
    expect(doWidget?.h).toBe(1)

    // Setpoint (analog_output) - 2x1 in normal mode
    const aoWidget = currentPage!.widgets.find(w => w.channel === 'AO_01')
    expect(aoWidget?.w).toBe(2)
    expect(aoWidget?.h).toBe(1)
  })

  it('should arrange widgets in grid layout', () => {
    const store = useDashboardStore()

    // Create 10 channels to test multi-row layout
    const channelConfigs: any = {}
    for (let i = 1; i <= 10; i++) {
      channelConfigs[`TC_${i.toString().padStart(2, '0')}`] = {
        name: `TC_${i.toString().padStart(2, '0')}`,
        channel_type: 'thermocouple',
        unit: '°C',
        group: 'temp'
      }
    }
    store.setChannels(channelConfigs)

    store.autoGenerateWidgets({ columns: 4 })  // Uses default compact mode

    const currentPage = store.pages.find(p => p.id === store.currentPageId)
    const widgets = currentPage!.widgets

    // First row: 2 widgets (2w each, fits in 4 columns) - compact mode
    expect(widgets[0].x).toBe(0)
    expect(widgets[0].y).toBe(0)
    expect(widgets[0].w).toBe(2)
    expect(widgets[1].x).toBe(2)
    expect(widgets[1].y).toBe(0)
    expect(widgets[1].w).toBe(2)

    // Second row: 2 more widgets
    expect(widgets[2].x).toBe(0)
    expect(widgets[2].y).toBe(2)
    expect(widgets[3].x).toBe(2)
    expect(widgets[3].y).toBe(2)
  })

  it('should skip invisible channels', () => {
    const store = useDashboardStore()

    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp', visible: true },
      'TC_02': { name: 'TC_02', channel_type: 'thermocouple', unit: '°C', group: 'temp', visible: false },
      'TC_03': { name: 'TC_03', channel_type: 'thermocouple', unit: '°C', group: 'temp' }, // visible undefined = true
    }
    store.setChannels(channelConfigs)

    const count = store.autoGenerateWidgets()

    // Should only create widgets for TC_01 and TC_03 (2 widgets)
    expect(count).toBe(2)

    const currentPage = store.pages.find(p => p.id === store.currentPageId)
    expect(currentPage!.widgets.find(w => w.channel === 'TC_01')).toBeDefined()
    expect(currentPage!.widgets.find(w => w.channel === 'TC_02')).toBeUndefined()
    expect(currentPage!.widgets.find(w => w.channel === 'TC_03')).toBeDefined()
  })

  it('should handle different widget size presets', () => {
    const store = useDashboardStore()

    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp' },
    }
    store.setChannels(channelConfigs)

    // Test compact size
    store.autoGenerateWidgets({ widgetSize: 'compact' })
    let currentPage = store.pages.find(p => p.id === store.currentPageId)
    let widget = currentPage!.widgets[0]
    expect(widget.w).toBe(2)
    expect(widget.h).toBe(1)

    // Clear and test large size
    currentPage!.widgets = []
    store.autoGenerateWidgets({ widgetSize: 'large' })
    currentPage = store.pages.find(p => p.id === store.currentPageId)
    widget = currentPage!.widgets[0]
    expect(widget.w).toBe(3)
    expect(widget.h).toBe(2)
  })

  it('should set widget properties correctly', () => {
    const store = useDashboardStore()

    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp' },
    }
    store.setChannels(channelConfigs)

    store.autoGenerateWidgets()

    const currentPage = store.pages.find(p => p.id === store.currentPageId)
    const widget = currentPage!.widgets[0]

    expect(widget.channel).toBe('TC_01')
    expect(widget.label).toBe('TC_01')
    expect(widget.showUnit).toBe(true)
    expect(widget.decimals).toBe(2)
    expect(widget.type).toBe('numeric')
  })

  it('should return 0 when no visible channels exist', () => {
    const store = useDashboardStore()

    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp', visible: false },
      'TC_02': { name: 'TC_02', channel_type: 'thermocouple', unit: '°C', group: 'temp', visible: false },
    }
    store.setChannels(channelConfigs)

    const count = store.autoGenerateWidgets()

    expect(count).toBe(0)
  })

  it('should place widgets below existing widgets', () => {
    const store = useDashboardStore()

    // Add an existing widget at y=5
    const currentPage = store.pages.find(p => p.id === store.currentPageId)!
    currentPage.widgets.push({
      id: 'existing-widget',
      type: 'numeric',
      x: 0,
      y: 5,
      w: 2,
      h: 3
    })

    // Now auto-generate
    const channelConfigs: any = {
      'TC_01': { name: 'TC_01', channel_type: 'thermocouple', unit: '°C', group: 'temp' },
    }
    store.setChannels(channelConfigs)

    store.autoGenerateWidgets()

    // New widget should start at y=8 (5 + 3 from existing widget)
    const newWidget = currentPage.widgets.find(w => w.channel === 'TC_01')
    expect(newWidget?.y).toBe(8)
  })
})

describe('Auto-Widget Generation - Complete Channel Type Coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('should have explicit mapping for all 13 ChannelType enum values', () => {
    const store = useDashboardStore()

    // ALL 13 channel types from types/index.ts
    const allChannelTypes: ChannelType[] = [
      'thermocouple',
      'voltage',
      'current',
      'rtd',
      'strain',
      'iepe',
      'counter',
      'resistance',
      'digital_input',
      'digital_output',
      'analog_output',
      'modbus_register',
      'modbus_coil',
    ]

    const channelConfigs: any = {}
    allChannelTypes.forEach((type, index) => {
      channelConfigs[`CH_${index}`] = {
        name: `CH_${index}`,
        channel_type: type,
        unit: 'unit',
        group: 'test'
      }
    })

    store.setChannels(channelConfigs)

    // Should create widget for every channel type
    const count = store.autoGenerateWidgets()
    expect(count).toBe(allChannelTypes.length)

    // Verify no widget has 'undefined' or 'null' as type
    const currentPage = store.pages.find(p => p.id === store.currentPageId)!
    currentPage.widgets.forEach(widget => {
      expect(widget.type).toBeDefined()
      expect(widget.type).not.toBeNull()
    })
  })
})
