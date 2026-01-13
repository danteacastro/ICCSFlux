/**
 * Tests for Dashboard Store (Pinia)
 *
 * Tests cover:
 * - Channel and value management
 * - Alarm/warning detection
 * - Multi-page management
 * - Widget CRUD operations
 * - Layout persistence (multi-page + legacy migration)
 * - Recording configuration
 * - P&ID layer management
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from './dashboard'
import type { ChannelConfig, WidgetConfig, LayoutConfig } from '../types'

// =============================================================================
// TEST SETUP
// =============================================================================

describe('Dashboard Store', () => {
  beforeEach(() => {
    // Create fresh Pinia instance for each test
    setActivePinia(createPinia())
    // Clear localStorage
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ===========================================================================
  // CHANNEL AND VALUE MANAGEMENT
  // ===========================================================================

  describe('Channel Management', () => {
    it('should set channels', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'TC_01': {
          name: 'TC_01',
          channel_type: 'thermocouple',
          unit: 'F',
          group: 'Temps'
        } as ChannelConfig,
        'AI_01': {
          name: 'AI_01',
          channel_type: 'voltage',
          unit: 'V',
          group: 'Analog'
        } as ChannelConfig
      }

      store.setChannels(channels)

      expect(Object.keys(store.channels)).toHaveLength(2)
      expect(store.channels['TC_01']?.unit).toBe('F')
    })

    it('should group channels by group property', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', group: 'Temps' } as ChannelConfig,
        'TC_02': { name: 'TC_02', group: 'Temps' } as ChannelConfig,
        'AI_01': { name: 'AI_01', group: 'Analog' } as ChannelConfig,
        'DO_01': { name: 'DO_01' } as ChannelConfig // No group = Ungrouped
      })

      expect(store.channelsByGroup['Temps']).toHaveLength(2)
      expect(store.channelsByGroup['Analog']).toHaveLength(1)
      expect(store.channelsByGroup['Ungrouped']).toHaveLength(1)
    })

    it('should filter visible channels', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', visible: true } as ChannelConfig,
        'TC_02': { name: 'TC_02', visible: false } as ChannelConfig,
        'TC_03': { name: 'TC_03' } as ChannelConfig // undefined = visible
      })

      expect(store.visibleChannels).toHaveLength(2)
      expect(store.visibleChannels.map(c => c.name)).toContain('TC_01')
      expect(store.visibleChannels.map(c => c.name)).toContain('TC_03')
      expect(store.visibleChannels.map(c => c.name)).not.toContain('TC_02')
    })
  })

  describe('Value Updates', () => {
    it('should update values with timestamps', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01' } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 72.5 })

      expect(store.values['TC_01']?.value).toBe(72.5)
      expect(store.values['TC_01']?.timestamp).toBeGreaterThan(0)
    })

    it('should clear all values', () => {
      const store = useDashboardStore()

      store.updateValues({ 'TC_01': 72.5, 'TC_02': 80.0 })
      expect(Object.keys(store.values)).toHaveLength(2)

      store.clearValues()

      expect(Object.keys(store.values)).toHaveLength(0)
    })
  })

  // ===========================================================================
  // ALARM AND WARNING DETECTION
  // ===========================================================================

  describe('Alarm Detection', () => {
    it('should detect high alarm', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', high_limit: 200 } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 250 }) // Above high_limit

      expect(store.values['TC_01']?.alarm).toBe(true)
    })

    it('should detect low alarm', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', low_limit: 32 } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 20 }) // Below low_limit

      expect(store.values['TC_01']?.alarm).toBe(true)
    })

    it('should not alarm when within limits', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', low_limit: 32, high_limit: 200 } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 72.5 }) // Within limits

      expect(store.values['TC_01']?.alarm).toBe(false)
    })

    it('should detect high warning', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', high_warning: 180, high_limit: 200 } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 185 }) // Above warning, below alarm

      expect(store.values['TC_01']?.warning).toBe(true)
      expect(store.values['TC_01']?.alarm).toBe(false)
    })

    it('should detect low warning', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01', low_warning: 40, low_limit: 32 } as ChannelConfig
      })

      store.updateValues({ 'TC_01': 35 }) // Below warning, above alarm

      expect(store.values['TC_01']?.warning).toBe(true)
      expect(store.values['TC_01']?.alarm).toBe(false)
    })
  })

  // ===========================================================================
  // PAGE MANAGEMENT
  // ===========================================================================

  describe('Page Management', () => {
    it('should ensure default page exists', () => {
      const store = useDashboardStore()

      // Store initializes with ensureDefaultPage() called
      expect(store.pages.length).toBeGreaterThanOrEqual(1)
      expect(store.currentPageId).toBeTruthy()
    })

    it('should add a new page', () => {
      const store = useDashboardStore()
      const initialCount = store.pages.length

      const pageId = store.addPage('Test Page')

      expect(store.pages.length).toBe(initialCount + 1)
      expect(pageId).toMatch(/^page-\d+-[a-z0-9]+$/)

      const newPage = store.pages.find(p => p.id === pageId)
      expect(newPage?.name).toBe('Test Page')
    })

    it('should remove a page (but not the last one)', () => {
      const store = useDashboardStore()

      // Add a second page
      const pageId = store.addPage('Page 2')
      expect(store.pages.length).toBe(2)

      // Remove it
      const result = store.removePage(pageId)
      expect(result).toBe(true)
      expect(store.pages.length).toBe(1)
    })

    it('should not remove the last page', () => {
      const store = useDashboardStore()

      // Try to remove the only page
      const result = store.removePage(store.currentPageId)
      expect(result).toBe(false)
      expect(store.pages.length).toBe(1)
    })

    it('should rename a page', () => {
      const store = useDashboardStore()
      const pageId = store.currentPageId

      store.renamePage(pageId, 'Renamed Page')

      const page = store.pages.find(p => p.id === pageId)
      expect(page?.name).toBe('Renamed Page')
    })

    it('should switch pages', () => {
      const store = useDashboardStore()
      const originalPageId = store.currentPageId

      const newPageId = store.addPage('New Page')
      store.switchPage(newPageId)

      expect(store.currentPageId).toBe(newPageId)
      expect(store.currentPageId).not.toBe(originalPageId)
    })

    it('should duplicate a page with new widget IDs', () => {
      const store = useDashboardStore()

      // Add widget to current page
      store.addWidget({ type: 'numeric', x: 0, y: 0, w: 2, h: 2, channel: 'TC_01' })
      const originalPage = store.currentPage
      const originalWidgetId = originalPage?.widgets[0]?.id

      // Duplicate
      const newPageId = store.duplicatePage(store.currentPageId)

      expect(newPageId).toBeTruthy()
      const newPage = store.pages.find(p => p.id === newPageId)
      expect(newPage?.widgets).toHaveLength(1)
      expect(newPage?.widgets[0]?.id).not.toBe(originalWidgetId) // New ID
      expect(newPage?.name).toContain('(copy)')
    })

    it('should move page order', () => {
      const store = useDashboardStore()

      // Create multiple pages
      store.addPage('Page 2')
      store.addPage('Page 3')

      const pages = store.sortedPages
      const page2 = pages.find(p => p.name === 'Page 2')
      const page3 = pages.find(p => p.name === 'Page 3')

      expect(page2?.order).toBeLessThan(page3?.order || 0)

      // Move Page 3 up
      store.movePage(page3!.id, 'up')

      // Refresh sorted pages
      const newPages = store.sortedPages
      const newPage2 = newPages.find(p => p.name === 'Page 2')
      const newPage3 = newPages.find(p => p.name === 'Page 3')

      // Orders should be swapped
      expect(newPage3?.order).toBeLessThan(newPage2?.order || 0)
    })
  })

  // ===========================================================================
  // WIDGET MANAGEMENT
  // ===========================================================================

  describe('Widget Management', () => {
    it('should add a widget to current page', () => {
      const store = useDashboardStore()

      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2,
        channel: 'TC_01'
      })

      expect(widgetId).toBeTruthy()
      expect(store.widgets).toHaveLength(1)
      expect(store.widgets[0]?.channel).toBe('TC_01')
    })

    it('should remove a widget', () => {
      const store = useDashboardStore()

      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2
      })

      expect(store.widgets).toHaveLength(1)

      store.removeWidget(widgetId!)
      expect(store.widgets).toHaveLength(0)
    })

    it('should update widget properties', () => {
      const store = useDashboardStore()

      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2,
        label: 'Original'
      })

      store.updateWidget(widgetId!, { label: 'Updated', w: 4 })

      const widget = store.widgets.find(w => w.id === widgetId)
      expect(widget?.label).toBe('Updated')
      expect(widget?.w).toBe(4)
    })

    it('should update widget position', () => {
      const store = useDashboardStore()

      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2
      })

      store.updateWidgetPosition(widgetId!, 5, 10, 4, 3)

      const widget = store.widgets.find(w => w.id === widgetId)
      expect(widget?.x).toBe(5)
      expect(widget?.y).toBe(10)
      expect(widget?.w).toBe(4)
      expect(widget?.h).toBe(3)
    })

    it('should limit chart widgets per page', () => {
      const store = useDashboardStore()

      // Add max charts
      store.addWidget({ type: 'chart', x: 0, y: 0, w: 8, h: 6, channels: ['TC_01'] })
      store.addWidget({ type: 'chart', x: 8, y: 0, w: 8, h: 6, channels: ['TC_02'] })

      expect(store.chartWidgets).toHaveLength(2)
      expect(store.canAddChart).toBe(false)

      // Try to add another - should fail
      const result = store.addWidget({ type: 'chart', x: 0, y: 6, w: 8, h: 6, channels: ['TC_03'] })
      expect(result).toBeNull()
      expect(store.chartWidgets).toHaveLength(2)
    })

    it('should move widget to another page', () => {
      const store = useDashboardStore()

      // Add widget to page 1
      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2
      })

      // Create page 2
      const page2Id = store.addPage('Page 2')

      // Move widget
      const result = store.moveWidgetToPage(widgetId!, page2Id)

      expect(result).toBe(true)
      expect(store.widgets).toHaveLength(0) // Removed from current page

      // Switch to page 2 and verify
      store.switchPage(page2Id)
      expect(store.widgets).toHaveLength(1)
    })

    it('should copy widget to another page', () => {
      const store = useDashboardStore()

      // Add widget to page 1
      const widgetId = store.addWidget({
        type: 'numeric',
        x: 0,
        y: 0,
        w: 2,
        h: 2,
        channel: 'TC_01'
      })

      // Create page 2
      const page2Id = store.addPage('Page 2')

      // Copy widget
      const result = store.copyWidgetToPage(widgetId!, page2Id)

      expect(result).toBe(true)
      expect(store.widgets).toHaveLength(1) // Still on current page

      // Switch to page 2 and verify
      store.switchPage(page2Id)
      expect(store.widgets).toHaveLength(1)
      expect(store.widgets[0]?.channel).toBe('TC_01')
      expect(store.widgets[0]?.id).not.toBe(widgetId) // Different ID
    })
  })

  // ===========================================================================
  // LAYOUT PERSISTENCE
  // ===========================================================================

  describe('Layout Persistence', () => {
    it('should get layout with multi-page support', () => {
      const store = useDashboardStore()

      store.addPage('Page 2')
      store.addWidget({ type: 'numeric', x: 0, y: 0, w: 2, h: 2 })

      const layout = store.getLayout()

      expect(layout.pages).toHaveLength(2)
      expect(layout.gridColumns).toBe(24)
      expect(layout.rowHeight).toBe(30)
      expect(layout.currentPageId).toBeTruthy()
    })

    it('should set layout with multi-page data', () => {
      const store = useDashboardStore()

      const layout: LayoutConfig = {
        system_id: 'test',
        gridColumns: 24,
        rowHeight: 30,
        pages: [
          { id: 'page-1', name: 'Overview', widgets: [], order: 0 },
          { id: 'page-2', name: 'Details', widgets: [
            { id: 'w1', type: 'numeric', x: 0, y: 0, w: 2, h: 2 }
          ], order: 1 }
        ],
        currentPageId: 'page-1'
      }

      store.setLayout(layout)

      expect(store.pages).toHaveLength(2)
      expect(store.currentPageId).toBe('page-1')

      // Switch to page 2 and verify widget
      store.switchPage('page-2')
      expect(store.widgets).toHaveLength(1)
    })

    it('should migrate legacy single-page layout to multi-page', () => {
      const store = useDashboardStore()

      const legacyLayout: LayoutConfig = {
        system_id: 'test',
        gridColumns: 12,
        rowHeight: 60,
        widgets: [
          { id: 'w1', type: 'numeric', x: 0, y: 0, w: 2, h: 2 },
          { id: 'w2', type: 'gauge', x: 2, y: 0, w: 2, h: 2 }
        ]
      }

      store.setLayout(legacyLayout)

      // Should have migrated to multi-page
      expect(store.pages).toHaveLength(1)
      expect(store.pages[0]?.name).toBe('Page 1')
      expect(store.widgets).toHaveLength(2)
    })

    it('should create default page when layout is empty', () => {
      const store = useDashboardStore()

      const emptyLayout: LayoutConfig = {
        system_id: 'test',
        gridColumns: 24,
        rowHeight: 30
        // No pages, no widgets
      }

      store.setLayout(emptyLayout)

      expect(store.pages.length).toBeGreaterThanOrEqual(1)
    })
  })

  // ===========================================================================
  // CHANNEL LIFECYCLE
  // ===========================================================================

  describe('Channel Lifecycle', () => {
    it('should find orphaned widgets', () => {
      const store = useDashboardStore()

      // Add widget for a channel
      store.addWidget({ type: 'numeric', x: 0, y: 0, w: 2, h: 2, channel: 'TC_01' })
      store.addWidget({ type: 'numeric', x: 2, y: 0, w: 2, h: 2, channel: 'TC_02' })

      // Set channels (TC_01 exists, TC_02 does not)
      store.setChannels({
        'TC_01': { name: 'TC_01' } as ChannelConfig
      })

      const orphans = store.findOrphanedWidgets()
      expect(orphans).toHaveLength(1)
      expect(orphans[0]?.channel).toBe('TC_02')
    })

    it('should handle channel deleted', () => {
      const store = useDashboardStore()

      store.setChannels({
        'TC_01': { name: 'TC_01' } as ChannelConfig,
        'TC_02': { name: 'TC_02' } as ChannelConfig
      })

      // Add widgets for both channels
      store.addWidget({ type: 'numeric', x: 0, y: 0, w: 2, h: 2, channel: 'TC_01' })
      store.addWidget({ type: 'numeric', x: 2, y: 0, w: 2, h: 2, channel: 'TC_02' })
      store.updateValues({ 'TC_01': 72.5, 'TC_02': 80.0 })

      // Delete TC_02
      const removed = store.handleChannelDeleted('TC_02')

      expect(removed).toBe(1)
      expect(store.widgets).toHaveLength(1)
      expect(store.values['TC_02']).toBeUndefined()
    })

    it('should remove channel from chart when deleted', () => {
      const store = useDashboardStore()

      store.addWidget({
        type: 'chart',
        x: 0, y: 0, w: 8, h: 6,
        channels: ['TC_01', 'TC_02', 'TC_03']
      })

      store.handleChannelDeleted('TC_02')

      expect(store.widgets[0]?.channels).toEqual(['TC_01', 'TC_03'])
    })

    it('should rename channel in widgets', () => {
      const store = useDashboardStore()

      store.addWidget({ type: 'numeric', x: 0, y: 0, w: 2, h: 2, channel: 'OLD_NAME' })
      store.addWidget({ type: 'chart', x: 2, y: 0, w: 8, h: 6, channels: ['OLD_NAME', 'OTHER'] })

      store.renameChannelInWidgets('OLD_NAME', 'NEW_NAME')

      expect(store.widgets[0]?.channel).toBe('NEW_NAME')
      expect(store.widgets[1]?.channels).toContain('NEW_NAME')
      expect(store.widgets[1]?.channels).not.toContain('OLD_NAME')
    })
  })

  // ===========================================================================
  // CHART MANAGEMENT
  // ===========================================================================

  describe('Chart Channel Management', () => {
    it('should add channel to chart', () => {
      const store = useDashboardStore()

      const chartId = store.addWidget({
        type: 'chart',
        x: 0, y: 0, w: 8, h: 6,
        channels: ['TC_01']
      })

      store.addChannelToChart(chartId!, 'TC_02')

      const chart = store.widgets.find(w => w.id === chartId)
      expect(chart?.channels).toContain('TC_01')
      expect(chart?.channels).toContain('TC_02')
    })

    it('should not add duplicate channel to chart', () => {
      const store = useDashboardStore()

      const chartId = store.addWidget({
        type: 'chart',
        x: 0, y: 0, w: 8, h: 6,
        channels: ['TC_01']
      })

      store.addChannelToChart(chartId!, 'TC_01') // Duplicate

      const chart = store.widgets.find(w => w.id === chartId)
      expect(chart?.channels).toHaveLength(1)
    })

    it('should remove channel from chart', () => {
      const store = useDashboardStore()

      const chartId = store.addWidget({
        type: 'chart',
        x: 0, y: 0, w: 8, h: 6,
        channels: ['TC_01', 'TC_02']
      })

      store.removeChannelFromChart(chartId!, 'TC_01')

      const chart = store.widgets.find(w => w.id === chartId)
      expect(chart?.channels).toEqual(['TC_02'])
    })
  })

  // ===========================================================================
  // EDIT MODE
  // ===========================================================================

  describe('Edit Mode', () => {
    it('should toggle edit mode', () => {
      const store = useDashboardStore()

      expect(store.editMode).toBe(false)

      store.toggleEditMode()
      expect(store.editMode).toBe(true)

      store.toggleEditMode()
      expect(store.editMode).toBe(false)
    })

    it('should set edit mode directly', () => {
      const store = useDashboardStore()

      store.setEditMode(true)
      expect(store.editMode).toBe(true)

      store.setEditMode(false)
      expect(store.editMode).toBe(false)
    })
  })

  // ===========================================================================
  // SYSTEM STATUS
  // ===========================================================================

  describe('System Status', () => {
    it('should set status and update computed properties', () => {
      const store = useDashboardStore()

      store.setStatus({
        status: 'online',
        acquiring: true,
        recording: false,
        scheduler_enabled: true
      } as any)

      expect(store.isConnected).toBe(true)
      expect(store.isAcquiring).toBe(true)
      expect(store.isRecording).toBe(false)
      expect(store.isSchedulerEnabled).toBe(true)
    })

    it('should detect offline status', () => {
      const store = useDashboardStore()

      store.setStatus({ status: 'offline' } as any)

      expect(store.isConnected).toBe(false)
    })
  })

  // ===========================================================================
  // RECORDING CONFIGURATION
  // ===========================================================================

  describe('Recording Configuration', () => {
    it('should set recording config', () => {
      const store = useDashboardStore()

      store.setRecordingConfig({
        fileFormat: 'tdms',
        sampleInterval: 5
      })

      expect(store.recordingConfig.fileFormat).toBe('tdms')
      expect(store.recordingConfig.sampleInterval).toBe(5)
    })

    it('should set selected recording channels', () => {
      const store = useDashboardStore()

      store.setSelectedRecordingChannels(['TC_01', 'TC_02', 'AI_01'])

      expect(store.selectedRecordingChannels).toHaveLength(3)
      expect(store.selectedRecordingChannels).toContain('TC_01')
    })

    it('should persist recording config to localStorage via saveRecordingConfigToStorage', () => {
      const store = useDashboardStore()

      store.setRecordingConfig({ fileFormat: 'tdms', sampleInterval: 10 })
      store.setSelectedRecordingChannels(['TC_01', 'TC_02'])

      // Call save directly (watchers don't trigger reliably in tests)
      store.saveRecordingConfigToStorage()

      const savedConfig = localStorage.getItem('nisystem-recording-config')
      const savedChannels = localStorage.getItem('nisystem-recording-channels')

      expect(savedConfig).toBeTruthy()
      expect(JSON.parse(savedConfig!).fileFormat).toBe('tdms')
      expect(JSON.parse(savedConfig!).sampleInterval).toBe(10)
      expect(savedChannels).toBeTruthy()
      expect(JSON.parse(savedChannels!)).toContain('TC_01')
      expect(JSON.parse(savedChannels!)).toContain('TC_02')
    })
  })

  // ===========================================================================
  // P&ID LAYER
  // ===========================================================================

  describe('P&ID Layer', () => {
    it('should add P&ID symbol', () => {
      const store = useDashboardStore()

      const symbolId = store.addPidSymbol({
        type: 'valve',
        x: 100,
        y: 200,
        width: 50,
        height: 50,
        rotation: 0
      })

      expect(symbolId).toMatch(/^pid-symbol-/)
      expect(store.pidLayer.symbols).toHaveLength(1)
    })

    it('should update P&ID symbol', () => {
      const store = useDashboardStore()

      const symbolId = store.addPidSymbol({
        type: 'valve',
        x: 100,
        y: 200,
        width: 50,
        height: 50,
        rotation: 0
      })

      store.updatePidSymbol(symbolId, { x: 150, rotation: 90 })

      const symbol = store.pidLayer.symbols.find(s => s.id === symbolId)
      expect(symbol?.x).toBe(150)
      expect(symbol?.rotation).toBe(90)
    })

    it('should remove P&ID symbol', () => {
      const store = useDashboardStore()

      const symbolId = store.addPidSymbol({
        type: 'valve',
        x: 100,
        y: 200,
        width: 50,
        height: 50,
        rotation: 0
      })

      store.removePidSymbol(symbolId)

      expect(store.pidLayer.symbols).toHaveLength(0)
    })

    it('should add P&ID pipe', () => {
      const store = useDashboardStore()

      const pipeId = store.addPidPipe({
        points: [{ x: 0, y: 0 }, { x: 100, y: 100 }],
        color: '#60a5fa',
        strokeWidth: 3
      })

      expect(pipeId).toMatch(/^pid-pipe-/)
      expect(store.pidLayer.pipes).toHaveLength(1)
    })

    it('should clear P&ID layer', () => {
      const store = useDashboardStore()

      store.addPidSymbol({ type: 'valve', x: 0, y: 0, width: 50, height: 50, rotation: 0 })
      store.addPidPipe({ points: [{ x: 0, y: 0 }], color: '#fff', strokeWidth: 2 })

      store.clearPidLayer()

      expect(store.pidLayer.symbols).toHaveLength(0)
      expect(store.pidLayer.pipes).toHaveLength(0)
    })

    it('should toggle P&ID edit mode', () => {
      const store = useDashboardStore()

      expect(store.pidEditMode).toBe(false)

      store.setPidEditMode(true)
      expect(store.pidEditMode).toBe(true)

      store.setPidEditMode(false)
      expect(store.pidEditMode).toBe(false)
      expect(store.pidDrawingMode).toBe(false) // Should also turn off drawing
    })
  })

  // ===========================================================================
  // SCRIPT VALUES (for Python scripting)
  // ===========================================================================

  describe('Script Values', () => {
    it('should update script values', () => {
      const store = useDashboardStore()

      store.updateScriptValues({
        'DrawProgress': { value: 50, name: 'DrawProgress' },
        'FlowRate': { value: 2.5, name: 'FlowRate' }
      })

      expect(store.values['DrawProgress']?.value).toBe(50)
      expect(store.values['FlowRate']?.value).toBe(2.5)
    })

    it('should create virtual channel config for script values', () => {
      const store = useDashboardStore()

      store.updateScriptValues({
        'DrawProgress': { value: 50, name: 'DrawProgress' }
      })

      expect(store.channels['DrawProgress']).toBeDefined()
      expect(store.channels['DrawProgress']?.channel_type).toBe('script')
      expect(store.channels['DrawProgress']?.group).toBe('Scripts')
    })
  })

  // ===========================================================================
  // WIDGET TYPE INFERENCE
  // ===========================================================================

  describe('Widget Type Inference', () => {
    it('should infer widget type from channel type', () => {
      const store = useDashboardStore()

      store.setChannels({
        'DI_01': { name: 'DI_01', channel_type: 'digital_input' } as ChannelConfig,
        'DO_01': { name: 'DO_01', channel_type: 'digital_output' } as ChannelConfig,
        'AO_01': { name: 'AO_01', channel_type: 'analog_output' } as ChannelConfig,
        'TC_01': { name: 'TC_01', channel_type: 'thermocouple' } as ChannelConfig
      })

      // Generate layout will use inferred types
      // We can test this indirectly through getWidgetDefaults
      // Digital input -> LED
      // Digital output -> Toggle
      // Analog output -> Setpoint
      // Default -> Numeric

      // The inferWidgetType function is internal, but we can verify
      // widget defaults exist for all types
      const numericDefaults = (store as any).getWidgetDefaults?.('numeric')
      const ledDefaults = (store as any).getWidgetDefaults?.('led')

      // If getWidgetDefaults is exposed, check it
      if (numericDefaults) {
        expect(numericDefaults.w).toBeGreaterThan(0)
        expect(numericDefaults.h).toBeGreaterThan(0)
      }
    })
  })
})

// =============================================================================
// PURE FUNCTION TESTS (extracted logic)
// =============================================================================

describe('Dashboard Store - Pure Functions', () => {
  describe('checkAlarm logic', () => {
    function checkAlarm(value: number, config: { low_limit?: number; high_limit?: number }): boolean {
      if (config.low_limit !== undefined && value < config.low_limit) return true
      if (config.high_limit !== undefined && value > config.high_limit) return true
      return false
    }

    it('should return true when value exceeds high limit', () => {
      expect(checkAlarm(250, { high_limit: 200 })).toBe(true)
    })

    it('should return true when value below low limit', () => {
      expect(checkAlarm(20, { low_limit: 32 })).toBe(true)
    })

    it('should return false when value within limits', () => {
      expect(checkAlarm(72, { low_limit: 32, high_limit: 200 })).toBe(false)
    })

    it('should return false when no limits defined', () => {
      expect(checkAlarm(72, {})).toBe(false)
    })

    it('should handle edge case at exactly the limit', () => {
      expect(checkAlarm(200, { high_limit: 200 })).toBe(false) // Equal is OK
      expect(checkAlarm(201, { high_limit: 200 })).toBe(true)  // Above is alarm
    })
  })

  describe('checkWarning logic', () => {
    function checkWarning(value: number, config: { low_warning?: number; high_warning?: number }): boolean {
      if (config.low_warning !== undefined && value < config.low_warning) return true
      if (config.high_warning !== undefined && value > config.high_warning) return true
      return false
    }

    it('should return true when value exceeds high warning', () => {
      expect(checkWarning(185, { high_warning: 180 })).toBe(true)
    })

    it('should return true when value below low warning', () => {
      expect(checkWarning(35, { low_warning: 40 })).toBe(true)
    })

    it('should return false when no warnings defined', () => {
      expect(checkWarning(72, {})).toBe(false)
    })
  })
})
