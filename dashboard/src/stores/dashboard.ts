import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  ChannelConfig,
  ChannelValue,
  SystemStatus,
  WidgetConfig,
  LayoutConfig,
  WidgetType,
  WidgetStyle,
  DashboardPage,
  PipeConnection,
  PipePoint
} from '../types'

// Recording configuration interface
export interface RecordingConfig {
  basePath: string
  filePrefix: string
  fileFormat: 'csv' | 'tdms'
  sampleInterval: number
  sampleIntervalUnit: 'seconds' | 'milliseconds'
  decimation: number
  rotationMode: 'single' | 'time' | 'size' | 'samples' | 'session'
  maxFileSize: number
  maxFileDuration: number
  maxFileSamples: number
  namingPattern: 'timestamp' | 'sequential' | 'custom'
  includeDate: boolean
  includeTime: boolean
  includeChannelsInName: boolean
  sequentialStart: number
  sequentialPadding: number
  customSuffix: string
  directoryStructure: 'flat' | 'daily' | 'monthly' | 'experiment'
  experimentName: string
  writeMode: 'immediate' | 'buffered'
  bufferSize: number
  flushInterval: number
  onLimitReached: 'new_file' | 'stop' | 'circular'
  circularMaxFiles: number
  mode: 'manual' | 'triggered' | 'scheduled'
  triggerChannel: string
  triggerCondition: 'above' | 'below' | 'change'
  triggerValue: number
  preTriggerSamples: number
  postTriggerSamples: number
  scheduleEnabled: boolean
  scheduleStart: string
  scheduleEnd: string
  scheduleDays: string[]

  // ALCOA+ Data Integrity Settings
  appendOnly: boolean           // Make files read-only after recording stops
  verifyOnClose: boolean        // Create SHA-256 integrity files
  includeAuditMetadata: boolean // Include operator, timestamps, session info
}

const DEFAULT_RECORDING_CONFIG: RecordingConfig = {
  basePath: './data',
  filePrefix: 'recording',
  fileFormat: 'csv',
  sampleInterval: 1,
  sampleIntervalUnit: 'seconds',
  decimation: 1,
  rotationMode: 'single',
  maxFileSize: 100,
  maxFileDuration: 3600,
  maxFileSamples: 10000,
  namingPattern: 'timestamp',
  includeDate: true,
  includeTime: true,
  includeChannelsInName: false,
  sequentialStart: 1,
  sequentialPadding: 3,
  customSuffix: '',
  directoryStructure: 'flat',
  experimentName: '',
  writeMode: 'buffered',
  bufferSize: 100,
  flushInterval: 5.0,
  onLimitReached: 'new_file',
  circularMaxFiles: 10,
  mode: 'manual',
  triggerChannel: '',
  triggerCondition: 'above',
  triggerValue: 0,
  preTriggerSamples: 100,
  postTriggerSamples: 1000,
  scheduleEnabled: false,
  scheduleStart: '08:00',
  scheduleEnd: '17:00',
  scheduleDays: ['mon', 'tue', 'wed', 'thu', 'fri'],

  // ALCOA+ Data Integrity Settings (FDA 21 CFR Part 11 compliance)
  appendOnly: false,           // Off by default for development flexibility
  verifyOnClose: true,         // On by default - creates integrity checksums
  includeAuditMetadata: true   // On by default - includes operator attribution
}

export const useDashboardStore = defineStore('dashboard', () => {
  // System state
  const systemId = ref<string>('default')
  const systemName = ref<string>('DCFlux')
  const mqttPrefix = ref<string>('nisystem')

  // Channel data
  const channels = ref<Record<string, ChannelConfig>>({})
  const values = ref<Record<string, ChannelValue>>({})
  const status = ref<SystemStatus | null>(null)

  // Multi-page dashboard state
  const pages = ref<DashboardPage[]>([])
  const currentPageId = ref<string>('default')

  // Legacy: widgets ref for backward compatibility (maps to current page)
  const widgets = computed({
    get: () => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      if (!page && pages.value.length > 0) {
        // currentPageId doesn't match any page - auto-correct to first page
        console.warn('[STORE] currentPageId mismatch, correcting to first page')
        currentPageId.value = pages.value[0]!.id
        return pages.value[0]!.widgets || []
      }
      return page?.widgets || []
    },
    set: (newWidgets: WidgetConfig[]) => {
      const pageIndex = pages.value.findIndex(p => p.id === currentPageId.value)
      if (pageIndex !== -1) {
        pages.value[pageIndex]!.widgets = newWidgets
      }
    }
  })

  // Pipes for current page (P&ID connections)
  const pipes = computed({
    get: () => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      return page?.pipes || []
    },
    set: (newPipes: PipeConnection[]) => {
      const pageIndex = pages.value.findIndex(p => p.id === currentPageId.value)
      if (pageIndex !== -1) {
        if (!pages.value[pageIndex]!.pipes) {
          pages.value[pageIndex]!.pipes = []
        }
        pages.value[pageIndex]!.pipes = newPipes
      }
    }
  })

  // Pipe drawing mode state
  const pipeDrawingMode = ref(false)
  const pipeDrawingStart = ref<{ widgetId?: string; port?: string; point?: PipePoint } | null>(null)

  // Grid settings
  const gridColumns = ref(24)  // 24 columns for finer control (was 12)
  const rowHeight = ref(30)    // Smaller row height to match (was 60)
  const editMode = ref(false)

  // ========================================================================
  // RECORDING CONFIGURATION (Data tab)
  // ========================================================================
  const recordingConfig = ref<RecordingConfig>({ ...DEFAULT_RECORDING_CONFIG })
  const selectedRecordingChannels = ref<string[]>([])
  const selectAllRecordingChannels = ref(true)

  // Chart state (max 2 charts per page)
  const maxCharts = 2

  // Computed
  const channelsByGroup = computed(() => {
    const groups: Record<string, ChannelConfig[]> = {}

    Object.values(channels.value).forEach(ch => {
      const group = ch.group || 'Ungrouped'
      if (!groups[group]) groups[group] = []
      groups[group].push(ch)
    })

    return groups
  })

  // Visible channels only (for widget dropdowns)
  const visibleChannels = computed(() => {
    return Object.values(channels.value).filter(ch => ch.visible !== false)
  })

  const visibleChannelsByGroup = computed(() => {
    const groups: Record<string, ChannelConfig[]> = {}

    visibleChannels.value.forEach(ch => {
      const group = ch.group || 'Ungrouped'
      if (!groups[group]) groups[group] = []
      groups[group].push(ch)
    })

    return groups
  })

  const chartWidgets = computed(() =>
    widgets.value.filter(w => w.type === 'chart')
  )

  const canAddChart = computed(() =>
    chartWidgets.value.length < maxCharts
  )

  const isAcquiring = computed(() => status.value?.acquiring ?? false)
  const isRecording = computed(() => status.value?.recording ?? false)
  const isSchedulerEnabled = computed(() => status.value?.scheduler_enabled ?? false)
  const isConnected = computed(() => status.value?.status === 'online')

  // Actions
  function setChannels(channelConfigs: Record<string, ChannelConfig>) {
    channels.value = channelConfigs
  }

  function updateValues(newValues: Record<string, number>) {
    const timestamp = Date.now()

    Object.entries(newValues).forEach(([name, value]) => {
      const config = channels.value[name]

      values.value[name] = {
        name,
        value,
        timestamp,
        alarm: config ? checkAlarm(value, config) : false,
        warning: config ? checkWarning(value, config) : false
      }
    })
  }

  function checkAlarm(value: number, config: ChannelConfig): boolean {
    if (config.low_limit !== undefined && value < config.low_limit) return true
    if (config.high_limit !== undefined && value > config.high_limit) return true
    return false
  }

  function checkWarning(value: number, config: ChannelConfig): boolean {
    if (config.low_warning !== undefined && value < config.low_warning) return true
    if (config.high_warning !== undefined && value > config.high_warning) return true
    return false
  }

  // Update values from scripts (calculated params, transformations)
  function updateScriptValues(scriptValues: Record<string, { value: number; name: string }>) {
    const timestamp = Date.now()

    Object.entries(scriptValues).forEach(([name, data]) => {
      // Add to values so widgets can bind to them
      values.value[name] = {
        name,
        value: data.value,
        timestamp,
        alarm: false,
        warning: false
      }

      // Add virtual channel config if not exists
      if (!channels.value[name]) {
        channels.value[name] = {
          name,  // TAG is the only identifier
          channel_type: 'script',
          unit: '',
          group: 'Scripts',
          enabled: true
        } as any
      }
    })
  }

  function setStatus(newStatus: SystemStatus) {
    status.value = newStatus
  }

  function setSystemInfo(id: string, name: string, prefix: string) {
    systemId.value = id
    systemName.value = name
    mqttPrefix.value = prefix
  }

  // ========================================================================
  // PAGE MANAGEMENT
  // ========================================================================

  const currentPage = computed(() =>
    pages.value.find(p => p.id === currentPageId.value)
  )

  const sortedPages = computed(() =>
    [...pages.value].sort((a, b) => a.order - b.order)
  )

  function ensureDefaultPage() {
    if (pages.value.length === 0) {
      pages.value.push({
        id: 'default',
        name: 'Page 1',
        widgets: [],
        order: 0,
        createdAt: new Date().toISOString()
      })
      currentPageId.value = 'default'
    }
  }

  function addPage(name?: string): string {
    const id = `page-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const order = pages.value.length
    const pageName = name || `Page ${order + 1}`

    pages.value.push({
      id,
      name: pageName,
      widgets: [],
      order,
      createdAt: new Date().toISOString()
    })

    return id
  }

  function removePage(pageId: string) {
    // Can't remove last page
    if (pages.value.length <= 1) return false

    const index = pages.value.findIndex(p => p.id === pageId)
    if (index === -1) return false

    pages.value.splice(index, 1)

    // If we removed the current page, switch to first available
    if (currentPageId.value === pageId) {
      currentPageId.value = pages.value[0]?.id || 'default'
    }

    // Reorder remaining pages
    pages.value.forEach((p, i) => p.order = i)

    return true
  }

  function renamePage(pageId: string, newName: string) {
    const page = pages.value.find(p => p.id === pageId)
    if (page) {
      page.name = newName.trim() || `Page ${page.order + 1}`
    }
  }

  function switchPage(pageId: string) {
    if (pages.value.some(p => p.id === pageId)) {
      currentPageId.value = pageId
    }
  }

  function duplicatePage(pageId: string): string | null {
    const source = pages.value.find(p => p.id === pageId)
    if (!source) return null

    const id = `page-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const newWidgets = source.widgets.map(w => ({
      ...w,
      id: `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    }))

    pages.value.push({
      id,
      name: `${source.name} (copy)`,
      widgets: newWidgets,
      order: pages.value.length,
      createdAt: new Date().toISOString()
    })

    return id
  }

  function movePage(pageId: string, direction: 'up' | 'down') {
    const index = pages.value.findIndex(p => p.id === pageId)
    if (index === -1) return

    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= pages.value.length) return

    // Swap orders
    const currentPage = pages.value[index]
    const targetPage = pages.value[newIndex]
    if (!currentPage || !targetPage) return

    const temp = currentPage.order
    currentPage.order = targetPage.order
    targetPage.order = temp
  }

  // ========================================================================
  // WIDGET ACTIONS (operate on current page)
  // ========================================================================

  function addWidget(widget: Omit<WidgetConfig, 'id'>) {
    ensureDefaultPage()
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return null

    const id = `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

    // Check chart limit per page
    if (widget.type === 'chart' && !canAddChart.value) {
      console.warn('Maximum number of charts reached')
      return null
    }

    const newWidget: WidgetConfig = { id, ...widget }
    page.widgets.push(newWidget)
    return id
  }

  function removeWidget(widgetId: string) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return

    const index = page.widgets.findIndex(w => w.id === widgetId)
    if (index !== -1) {
      page.widgets.splice(index, 1)
    }
  }

  function moveWidgetToPage(widgetId: string, targetPageId: string): boolean {
    if (currentPageId.value === targetPageId) return false

    const sourcePage = pages.value.find(p => p.id === currentPageId.value)
    const targetPage = pages.value.find(p => p.id === targetPageId)
    if (!sourcePage || !targetPage) return false

    const widgetIndex = sourcePage.widgets.findIndex(w => w.id === widgetId)
    if (widgetIndex === -1) return false

    // Remove from source and add to target
    const [widget] = sourcePage.widgets.splice(widgetIndex, 1)
    if (widget) {
      // Reset position to avoid overlap on target page
      widget.x = 0
      widget.y = targetPage.widgets.reduce((maxY, w) => Math.max(maxY, w.y + w.h), 0)
      targetPage.widgets.push(widget)
    }

    return true
  }

  function copyWidgetToPage(widgetId: string, targetPageId: string): boolean {
    const sourcePage = pages.value.find(p => p.id === currentPageId.value)
    const targetPage = pages.value.find(p => p.id === targetPageId)
    if (!sourcePage || !targetPage) return false

    const widget = sourcePage.widgets.find(w => w.id === widgetId)
    if (!widget) return false

    // Create a copy with new ID
    const newWidget: WidgetConfig = {
      ...widget,
      id: `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      x: 0,
      y: targetPage.widgets.reduce((maxY, w) => Math.max(maxY, w.y + w.h), 0)
    }
    targetPage.widgets.push(newWidget)

    return true
  }

  function updateWidget(widgetId: string, updates: Partial<WidgetConfig>) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return

    const widget = page.widgets.find(w => w.id === widgetId)
    if (widget) {
      Object.assign(widget, updates)
    }
  }

  function updateWidgetPosition(widgetId: string, x: number, y: number, w: number, h: number) {
    updateWidget(widgetId, { x, y, w, h })
  }

  function setEditMode(enabled: boolean) {
    editMode.value = enabled
  }

  function toggleEditMode() {
    editMode.value = !editMode.value
  }

  // ========================================================================
  // PIPE/CONNECTION ACTIONS (P&ID routing)
  // ========================================================================

  function addPipe(pipe: Omit<PipeConnection, 'id'>): string {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return ''

    if (!page.pipes) {
      page.pipes = []
    }

    const id = `pipe-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const newPipe: PipeConnection = { id, ...pipe }
    page.pipes.push(newPipe)
    return id
  }

  function updatePipe(pipeId: string, updates: Partial<PipeConnection>) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page?.pipes) return

    const pipe = page.pipes.find(p => p.id === pipeId)
    if (pipe) {
      Object.assign(pipe, updates)
    }
  }

  function removePipe(pipeId: string) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page?.pipes) return

    const index = page.pipes.findIndex(p => p.id === pipeId)
    if (index !== -1) {
      page.pipes.splice(index, 1)
    }
  }

  function setPipeDrawingMode(enabled: boolean) {
    pipeDrawingMode.value = enabled
    if (!enabled) {
      pipeDrawingStart.value = null
    }
  }

  function startPipeDrawing(start: { widgetId?: string; port?: string; point?: PipePoint }) {
    pipeDrawingStart.value = start
  }

  function finishPipeDrawing(end: { widgetId?: string; port?: string; point?: PipePoint }) {
    if (!pipeDrawingStart.value) return

    // Create pipe with at least 2 points
    const startPoint = pipeDrawingStart.value.point || { x: 0, y: 0 }
    const endPoint = end.point || { x: 5, y: 5 }

    const newPipe: Omit<PipeConnection, 'id'> = {
      points: [startPoint, endPoint],
      startWidgetId: pipeDrawingStart.value.widgetId,
      startPort: pipeDrawingStart.value.port as PipeConnection['startPort'],
      endWidgetId: end.widgetId,
      endPort: end.port as PipeConnection['endPort'],
      color: '#60a5fa',
      strokeWidth: 3
    }

    addPipe(newPipe)
    pipeDrawingStart.value = null
    pipeDrawingMode.value = false
  }

  function cancelPipeDrawing() {
    pipeDrawingStart.value = null
  }

  // ========================================================================
  // LAYOUT PERSISTENCE (with multi-page support)
  // ========================================================================

  function getLayout(): LayoutConfig {
    return {
      system_id: systemId.value,
      widgets: currentPage.value?.widgets || [],  // Legacy: current page widgets
      gridColumns: gridColumns.value,
      rowHeight: rowHeight.value,
      pages: pages.value,
      currentPageId: currentPageId.value
    }
  }

  function setLayout(layout: LayoutConfig) {
    console.log('[DASHBOARD STORE] setLayout called with:', {
      gridColumns: layout.gridColumns,
      rowHeight: layout.rowHeight,
      hasPages: !!layout.pages && layout.pages.length > 0,
      pageCount: layout.pages?.length || 0,
      hasLegacyWidgets: !!layout.widgets && layout.widgets.length > 0,
      legacyWidgetCount: layout.widgets?.length || 0
    })

    gridColumns.value = layout.gridColumns
    rowHeight.value = layout.rowHeight

    // Handle multi-page layouts
    if (layout.pages && layout.pages.length > 0) {
      console.log('[DASHBOARD STORE] Setting multi-page layout with', layout.pages.length, 'pages')
      pages.value = layout.pages

      // Log each page
      layout.pages.forEach((page, idx) => {
        console.log(`[DASHBOARD STORE] Page ${idx}: ${page.name} (id: ${page.id}, widgets: ${page.widgets?.length || 0})`)
      })

      // Always start on Page 1 (first page by order), not last viewed page
      const firstPage = [...layout.pages].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))[0]
      currentPageId.value = firstPage?.id || layout.pages[0]!.id
      console.log('[DASHBOARD STORE] Current page set to:', currentPageId.value)
    } else if (layout.widgets && layout.widgets.length > 0) {
      // Legacy single-page layout - migrate to multi-page
      console.log('[DASHBOARD STORE] Migrating legacy single-page layout to multi-page (widgets:', layout.widgets.length, ')')
      pages.value = [{
        id: 'default',
        name: 'Page 1',
        widgets: layout.widgets,
        order: 0
      }]
      currentPageId.value = 'default'
    } else {
      // No pages and no widgets - create empty default page
      console.warn('[DASHBOARD STORE] ⚠️ No pages or widgets provided - creating empty default page')
      ensureDefaultPage()
    }

    console.log('[DASHBOARD STORE] ✅ Layout set successfully. Total pages:', pages.value.length)
    console.log('[DASHBOARD STORE] Current page widgets:', widgets.value.length)

    // Validation: Ensure we always have at least one page
    if (pages.value.length === 0) {
      console.error('[DASHBOARD STORE] ❌ CRITICAL: No pages after setLayout! Creating default page...')
      ensureDefaultPage()
    }
  }

  function saveLayoutToStorage() {
    const layout = getLayout()
    localStorage.setItem(`nisystem-layout-${systemId.value}`, JSON.stringify(layout))
  }

  function loadLayoutFromStorage(): boolean {
    const stored = localStorage.getItem(`nisystem-layout-${systemId.value}`)
    if (stored) {
      try {
        const layout = JSON.parse(stored) as LayoutConfig
        // Migration: Remove boolean props that default to true when set to false
        // This fixes checkboxes that saved false instead of leaving undefined
        const migrateWidgets = (widgetList: WidgetConfig[]) => {
          const propsToClean = [
            'showLabel', 'showUnit', 'showUnits', 'showValue',
            'showGrid', 'showLegend', 'yAxisAuto', 'showDate',
            'showToggle', 'showControls', 'showAckButton'
          ]
          widgetList.forEach(w => {
            propsToClean.forEach(prop => {
              if ((w as any)[prop] === false) {
                delete (w as any)[prop]
              }
            })
          })
        }

        if (layout.pages) {
          layout.pages.forEach(p => migrateWidgets(p.widgets))
        }
        if (layout.widgets) {
          migrateWidgets(layout.widgets)
        }

        setLayout(layout)
        return true
      } catch (e) {
        console.error('Failed to load layout:', e)
      }
    }
    return false
  }

  // Auto-generate layout from channel config
  function generateDefaultLayout() {
    // Ensure we have a default page
    ensureDefaultPage()

    // Clear current page widgets
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (page) {
      page.widgets = []
    }

    const groups = channelsByGroup.value
    let currentY = 0

    Object.entries(groups).forEach(([_groupName, groupChannels]) => {
      let x = 0
      let maxH = 1

      groupChannels.forEach(channel => {
        const widgetType = inferWidgetType(channel)
        const defaults = getWidgetDefaults(widgetType)

        // Wrap to next row if needed
        if (x + defaults.w > gridColumns.value) {
          x = 0
          currentY += maxH
          maxH = 1
        }

        addWidget({
          channel: channel.name,
          type: widgetType,
          x,
          y: currentY,
          w: defaults.w,
          h: defaults.h,
          label: channel.name  // TAG is the only identifier
        })

        x += defaults.w
        maxH = Math.max(maxH, defaults.h)
      })

      currentY += maxH
    })

    // Add one chart if there are chartable channels
    const chartableChannels = Object.values(channels.value)
      .filter(ch => ch.chartable || ch.channel_type === 'thermocouple' || ch.channel_type === 'voltage')
      .slice(0, 4)
      .map(ch => ch.name)

    if (chartableChannels.length > 0) {
      addWidget({
        type: 'chart',
        channels: chartableChannels,
        x: 8,
        y: 0,
        w: 4,
        h: 4,
        timeRange: 300
      })
    }
  }

  function inferWidgetType(channel: ChannelConfig): WidgetType {
    // Use explicit widget type if specified
    if (channel.widget) return channel.widget

    // Infer from channel type
    switch (channel.channel_type) {
      case 'digital_input':
        return 'led'
      case 'digital_output':
        return 'toggle'
      case 'analog_output':
        return 'setpoint'
      default:
        return 'numeric'
    }
  }

  // Widget defaults for 24-column grid (double the old 12-column values)
  // Row height is now 30px (was 60px), so h values stay same for same pixel height
  function getWidgetDefaults(type: WidgetType): { w: number; h: number } {
    const defaults: Record<WidgetType, { w: number; h: number }> = {
      numeric: { w: 2, h: 2 },      // 1 old cell = 2 new units
      gauge: { w: 4, h: 4 },        // 2 old cells = 4 new units
      led: { w: 2, h: 2 },          // 1 old cell
      chart: { w: 8, h: 6 },        // 4 old cells wide
      table: { w: 6, h: 4 },        // 3 old cells wide
      setpoint: { w: 3, h: 2 },     // 1.5 old cells - the sweet spot!
      toggle: { w: 2, h: 2 },       // 1 old cell
      title: { w: 4, h: 2 },        // 2 old cells
      sparkline: { w: 4, h: 2 },    // 2 old cells
      alarm_summary: { w: 4, h: 4 },
      recording_status: { w: 4, h: 4 },
      system_status: { w: 4, h: 4 },
      interlock_status: { w: 4, h: 4 },
      action_button: { w: 2, h: 2 },
      clock: { w: 4, h: 2 },
      divider: { w: 6, h: 2 },
      bar_graph: { w: 4, h: 2 },
      scheduler_status: { w: 4, h: 4 },
      svg_symbol: { w: 2, h: 2 },
      value_table: { w: 6, h: 8 },
      script_monitor: { w: 6, h: 8 }
    }
    return defaults[type] || { w: 2, h: 2 }
  }

  // Load preset layout from JSON file
  async function loadPresetLayout(layoutName: string): Promise<boolean> {
    try {
      // Fetch layout from config directory
      const response = await fetch(`/config/${layoutName}.json`)
      if (!response.ok) {
        console.error(`Failed to load preset layout: ${layoutName}`)
        return false
      }

      const layoutData = await response.json()

      // Validate required fields
      if (!layoutData.widgets || !Array.isArray(layoutData.widgets)) {
        console.error('Invalid layout format: missing widgets array')
        return false
      }

      // Apply the layout
      const layout: LayoutConfig = {
        system_id: layoutData.system_id || 'default',
        widgets: layoutData.widgets,
        gridColumns: layoutData.gridColumns || 24,
        rowHeight: layoutData.rowHeight || 30
      }

      setLayout(layout)
      saveLayoutToStorage()

      console.log(`Loaded preset layout: ${layoutData.name || layoutName}`)
      return true
    } catch (error) {
      console.error('Error loading preset layout:', error)
      return false
    }
  }

  // Widget style update
  function updateWidgetStyle(widgetId: string, style: Partial<WidgetStyle>) {
    const widget = widgets.value.find(w => w.id === widgetId)
    if (widget) {
      widget.style = { ...widget.style, ...style }
    }
  }

  // Chart channel management
  function addChannelToChart(chartId: string, channelName: string) {
    const chart = widgets.value.find(w => w.id === chartId && w.type === 'chart')
    if (chart) {
      if (!chart.channels) chart.channels = []
      if (!chart.channels.includes(channelName)) {
        chart.channels.push(channelName)
      }
    }
  }

  function removeChannelFromChart(chartId: string, channelName: string) {
    const chart = widgets.value.find(w => w.id === chartId && w.type === 'chart')
    if (chart && chart.channels) {
      const index = chart.channels.indexOf(channelName)
      if (index !== -1) {
        chart.channels.splice(index, 1)
      }
    }
  }

  // Rename channel references in all widgets
  function renameChannelInWidgets(oldName: string, newName: string) {
    for (const widget of widgets.value) {
      // Single-channel widgets
      if (widget.channel === oldName) {
        widget.channel = newName
      }
      // Multi-channel widgets (charts)
      if (widget.channels && Array.isArray(widget.channels)) {
        const idx = widget.channels.indexOf(oldName)
        if (idx !== -1) {
          widget.channels[idx] = newName
        }
      }
    }
  }

  // Find widgets that reference non-existent channels
  function findOrphanedWidgets(): WidgetConfig[] {
    const channelNames = new Set(Object.keys(channels.value))
    return widgets.value.filter(widget => {
      // Single-channel widgets
      if (widget.channel && !channelNames.has(widget.channel)) {
        return true
      }
      // Multi-channel widgets (charts) - orphaned if ALL channels are missing
      if (widget.channels && widget.channels.length > 0) {
        const allMissing = widget.channels.every(ch => !channelNames.has(ch))
        return allMissing
      }
      return false
    })
  }

  // Remove widget references to a deleted channel
  function handleChannelDeleted(channelName: string) {
    // Remove from single-channel widgets
    const toRemove: string[] = []

    for (const widget of widgets.value) {
      if (widget.channel === channelName) {
        toRemove.push(widget.id)
      }
      // Remove from multi-channel widgets (charts)
      if (widget.channels && Array.isArray(widget.channels)) {
        const idx = widget.channels.indexOf(channelName)
        if (idx !== -1) {
          widget.channels.splice(idx, 1)
          // If chart has no channels left, mark for removal
          if (widget.channels.length === 0) {
            toRemove.push(widget.id)
          }
        }
      }
    }

    // Remove orphaned widgets
    for (const id of toRemove) {
      removeWidget(id)
    }

    // Also remove from channel values
    if (values.value[channelName]) {
      delete values.value[channelName]
    }

    return toRemove.length
  }

  // Clean up all orphaned widgets
  function cleanupOrphanedWidgets(): number {
    const orphans = findOrphanedWidgets()
    for (const widget of orphans) {
      removeWidget(widget.id)
    }
    return orphans.length
  }

  // Clear all values (reset to boot state with "--" displays)
  function clearValues() {
    values.value = {}
  }

  // ========================================================================
  // RECORDING CONFIGURATION ACTIONS (Data tab)
  // ========================================================================

  const RECORDING_CONFIG_KEY = 'nisystem-recording-config'
  const RECORDING_CHANNELS_KEY = 'nisystem-recording-channels'

  function setRecordingConfig(config: Partial<RecordingConfig>) {
    Object.assign(recordingConfig.value, config)
  }

  function setSelectedRecordingChannels(channelNames: string[]) {
    selectedRecordingChannels.value = channelNames
  }

  function setSelectAllRecordingChannels(selectAll: boolean) {
    selectAllRecordingChannels.value = selectAll
  }

  function loadRecordingConfigFromStorage() {
    try {
      const savedConfig = localStorage.getItem(RECORDING_CONFIG_KEY)
      if (savedConfig) {
        const parsed = JSON.parse(savedConfig)
        Object.assign(recordingConfig.value, parsed)
      }

      const savedChannels = localStorage.getItem(RECORDING_CHANNELS_KEY)
      if (savedChannels) {
        selectedRecordingChannels.value = JSON.parse(savedChannels)
      }
    } catch (e) {
      console.error('[STORE] Failed to load recording config from localStorage:', e)
    }
  }

  function saveRecordingConfigToStorage() {
    try {
      localStorage.setItem(RECORDING_CONFIG_KEY, JSON.stringify(recordingConfig.value))
      localStorage.setItem(RECORDING_CHANNELS_KEY, JSON.stringify(selectedRecordingChannels.value))
    } catch (e) {
      console.error('[STORE] Failed to save recording config to localStorage:', e)
    }
  }

  // Auto-persist recording config changes (debounced)
  let recordingConfigPersistTimer: ReturnType<typeof setTimeout> | null = null

  function persistRecordingConfigDebounced() {
    if (recordingConfigPersistTimer) clearTimeout(recordingConfigPersistTimer)
    recordingConfigPersistTimer = setTimeout(() => {
      saveRecordingConfigToStorage()
    }, 500)
  }

  // Watch for changes and auto-persist
  watch(recordingConfig, persistRecordingConfigDebounced, { deep: true })
  watch(selectedRecordingChannels, persistRecordingConfigDebounced, { deep: true })
  watch(selectAllRecordingChannels, persistRecordingConfigDebounced)

  // Load on store creation
  loadRecordingConfigFromStorage()

  return {
    // State
    systemId,
    systemName,
    mqttPrefix,
    channels,
    values,
    status,
    widgets,
    gridColumns,
    rowHeight,
    editMode,
    maxCharts,

    // Multi-page state
    pages,
    currentPageId,
    currentPage,
    sortedPages,

    // Computed
    channelsByGroup,
    visibleChannels,
    visibleChannelsByGroup,
    chartWidgets,
    canAddChart,
    isAcquiring,
    isRecording,
    isSchedulerEnabled,
    isConnected,

    // Actions
    setChannels,
    updateValues,
    updateScriptValues,
    clearValues,
    setStatus,
    setSystemInfo,

    // Page management
    ensureDefaultPage,
    addPage,
    removePage,
    renamePage,
    switchPage,
    duplicatePage,
    movePage,

    // Layout
    addWidget,
    removeWidget,
    moveWidgetToPage,
    copyWidgetToPage,
    updateWidget,
    updateWidgetPosition,
    updateWidgetStyle,
    setEditMode,
    toggleEditMode,
    getLayout,
    setLayout,
    saveLayoutToStorage,
    loadLayoutFromStorage,
    generateDefaultLayout,
    loadPresetLayout,

    // Chart
    addChannelToChart,
    removeChannelFromChart,
    renameChannelInWidgets,

    // Channel lifecycle
    findOrphanedWidgets,
    handleChannelDeleted,
    cleanupOrphanedWidgets,

    // Pipes (P&ID connections)
    pipes,
    pipeDrawingMode,
    pipeDrawingStart,
    addPipe,
    updatePipe,
    removePipe,
    setPipeDrawingMode,
    startPipeDrawing,
    finishPipeDrawing,
    cancelPipeDrawing,

    // Recording configuration (Data tab)
    recordingConfig,
    selectedRecordingChannels,
    selectAllRecordingChannels,
    setRecordingConfig,
    setSelectedRecordingChannels,
    setSelectAllRecordingChannels,
    loadRecordingConfigFromStorage,
    saveRecordingConfigToStorage
  }
})
