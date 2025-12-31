import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  ChannelConfig,
  ChannelValue,
  SystemStatus,
  WidgetConfig,
  LayoutConfig,
  WidgetType,
  WidgetStyle
} from '../types'

export const useDashboardStore = defineStore('dashboard', () => {
  // System state
  const systemId = ref<string>('default')
  const systemName = ref<string>('NISystem')
  const mqttPrefix = ref<string>('nisystem')

  // Channel data
  const channels = ref<Record<string, ChannelConfig>>({})
  const values = ref<Record<string, ChannelValue>>({})
  const status = ref<SystemStatus | null>(null)

  // Layout state
  const widgets = ref<WidgetConfig[]>([])
  const gridColumns = ref(12)
  const rowHeight = ref(60)
  const editMode = ref(false)

  // Chart state (max 2 charts)
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
  function updateScriptValues(scriptValues: Record<string, { value: number; name: string; displayName: string }>) {
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
          name,
          display_name: data.displayName,
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

  // Layout actions
  function addWidget(widget: Omit<WidgetConfig, 'id'>) {
    const id = `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

    // Check chart limit
    if (widget.type === 'chart' && !canAddChart.value) {
      console.warn('Maximum number of charts reached')
      return null
    }

    const newWidget: WidgetConfig = { id, ...widget }
    widgets.value.push(newWidget)
    return id
  }

  function removeWidget(widgetId: string) {
    const index = widgets.value.findIndex(w => w.id === widgetId)
    if (index !== -1) {
      widgets.value.splice(index, 1)
    }
  }

  function updateWidget(widgetId: string, updates: Partial<WidgetConfig>) {
    const widget = widgets.value.find(w => w.id === widgetId)
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

  // Layout persistence
  function getLayout(): LayoutConfig {
    return {
      system_id: systemId.value,
      widgets: [...widgets.value],
      gridColumns: gridColumns.value,
      rowHeight: rowHeight.value
    }
  }

  function setLayout(layout: LayoutConfig) {
    widgets.value = [...layout.widgets]
    gridColumns.value = layout.gridColumns
    rowHeight.value = layout.rowHeight
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
    widgets.value = []

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
          label: channel.display_name || channel.name
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

  function getWidgetDefaults(type: WidgetType): { w: number; h: number } {
    const defaults: Record<WidgetType, { w: number; h: number }> = {
      numeric: { w: 1, h: 1 },
      gauge: { w: 2, h: 2 },
      led: { w: 1, h: 1 },
      chart: { w: 4, h: 3 },
      table: { w: 3, h: 2 },
      setpoint: { w: 2, h: 1 },
      toggle: { w: 1, h: 1 },
      title: { w: 2, h: 1 },
      sparkline: { w: 2, h: 1 },
      alarm_summary: { w: 2, h: 2 },
      recording_status: { w: 2, h: 2 },
      system_status: { w: 2, h: 2 },
      interlock_status: { w: 2, h: 2 },
      multi_channel_table: { w: 2, h: 3 },
      action_button: { w: 1, h: 1 },
      clock: { w: 2, h: 1 },
      divider: { w: 3, h: 1 },
      bar_graph: { w: 2, h: 1 },
      scheduler_status: { w: 2, h: 2 },
      sequence_status: { w: 2, h: 2 }
    }
    return defaults[type] || { w: 1, h: 1 }
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

  // Clear all values (reset to boot state with "--" displays)
  function clearValues() {
    values.value = {}
  }

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

    // Computed
    channelsByGroup,
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

    // Layout
    addWidget,
    removeWidget,
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

    // Chart
    addChannelToChart,
    removeChannelFromChart,
    renameChannelInWidgets
  }
})
