<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import { useMqtt } from '../composables/useMqtt'
import { useBackendScripts } from '../composables/useBackendScripts'
import { formatUnit } from '../utils/formatUnit'
import type { WidgetConfig, WidgetStyle, ButtonAction, ButtonActionType, SystemCommandType, ChartPlotStyle } from '../types'
import { WIDGET_COLORS } from '../types'
import { SYMBOL_INFO, type ScadaSymbolType } from '../assets/symbols'

// Default chart colors (same as TrendChart)
const CHART_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
  '#a855f7', '#14b8a6', '#f97316', '#6366f1'
]

const props = defineProps<{
  widgetId: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const store = useDashboardStore()
const scripts = useScripts()
const mqtt = useMqtt()
const backendScripts = useBackendScripts()

// Local copy of widget for editing
const localWidget = ref<Partial<WidgetConfig>>({})

// Get the current widget
const widget = computed(() => {
  if (!props.widgetId) return null
  return store.widgets.find(w => w.id === props.widgetId) || null
})

// Initialize local copy when widget changes
watch(() => props.widgetId, () => {
  if (widget.value) {
    localWidget.value = { ...widget.value }
    // Initialize boolean toggles to true if undefined (matches component defaults)
    if (localWidget.value.showLabel === undefined) localWidget.value.showLabel = true
    if (localWidget.value.showUnit === undefined) localWidget.value.showUnit = true
    if (localWidget.value.showValue === undefined) localWidget.value.showValue = true
    // Initialize style object for widgets that use it (title, led, divider, etc.)
    if (!localWidget.value.style) {
      localWidget.value.style = {}
    }
  }
}, { immediate: true })

// Widget type info
const widgetType = computed(() => widget.value?.type || 'numeric')

// System state channels (sys.*) - always available from backend
// These record system state for context when reviewing data
const SYSTEM_CHANNELS: [string, any][] = [
  ['sys.acquiring', { name: 'sys.acquiring', channel_type: 'system', units: 'bool', description: 'Acquisition active (1/0)' }],
  ['sys.session_active', { name: 'sys.session_active', channel_type: 'system', units: 'bool', description: 'Test session active (1/0)' }],
  ['sys.recording', { name: 'sys.recording', channel_type: 'system', units: 'bool', description: 'Recording active (1/0)' }],
]

// Extract publish() channel names from Python scripts
// This allows widgets to be configured with py.* channels before scripts run
const scriptPublishChannels = computed(() => {
  const channels = new Set<string>()

  // Parse each script's code for publish('name', ...) calls
  for (const script of backendScripts.scriptsList.value) {
    if (!script.code) continue

    // Match publish('name', ...) or publish("name", ...)
    // Handles: publish('ActiveOutput', value), publish("CycleCount", cycle)
    const publishRegex = /publish\s*\(\s*['"]([^'"]+)['"]/g
    let match
    while ((match = publishRegex.exec(script.code)) !== null) {
      channels.add(`py.${match[1]}`)
    }
  }

  return channels
})

// Available channels based on widget type
// Includes: hardware channels, system state channels (sys.*), and script channels (py.*)
const availableChannels = computed(() => {
  const wt = widgetType.value

  // Start with hardware channels from config
  const hardwareChannels = Object.entries(store.channels).filter(([_, ch]) => {
    if (wt === 'toggle') return ch.channel_type === 'digital_output'
    if (wt === 'led') return true // LEDs can work with any channel
    return true
  })

  // System channels (always available, skip for toggle widgets)
  const systemChannels: [string, any][] = wt === 'toggle' ? [] : [...SYSTEM_CHANNELS]

  // Collect script-published channels from two sources:
  // 1. Parsed from script code (available before scripts run)
  // 2. Active channelValues (for any py.* not caught by parsing)
  const scriptChannelNames = new Set<string>(scriptPublishChannels.value)

  // Also include any active py.* channels from channelValues
  for (const name of Object.keys(mqtt.channelValues.value)) {
    if (name.startsWith('py.')) {
      scriptChannelNames.add(name)
    }
  }

  // Build script channel entries
  const scriptChannels: [string, any][] = []
  for (const name of scriptChannelNames) {
    // Skip for toggle widgets (py.* are not digital outputs)
    if (wt === 'toggle') continue
    // Create a minimal config object for display
    scriptChannels.push([name, {
      name,
      channel_type: 'script',
      units: '',
      description: 'Script-published value'
    }])
  }

  // Sort script channels alphabetically
  scriptChannels.sort((a, b) => a[0].localeCompare(b[0]))

  // Combine: hardware channels first, then system channels, then script channels
  return [...hardwareChannels, ...systemChannels, ...scriptChannels]
})

// Digital output channels for button action
const digitalOutputChannels = computed(() => {
  return Object.entries(store.channels).filter(([_, ch]) =>
    ch.channel_type === 'digital_output'
  )
})

// Available sequences for script_run action
const availableSequences = computed(() => scripts.sequences.value)

// Group symbols by category for the select dropdown
const symbolsByCategory = computed(() => {
  const grouped: Record<string, [ScadaSymbolType, { label: string; category: string }][]> = {}
  for (const [key, info] of Object.entries(SYMBOL_INFO) as [ScadaSymbolType, { label: string; category: string }][]) {
    const category = info.category
    if (!grouped[category]) {
      grouped[category] = []
    }
    grouped[category]!.push([key, info])
  }
  return grouped
})

// Button action type options
const buttonActionTypes: { value: ButtonActionType; label: string }[] = [
  { value: 'mqtt_publish', label: 'MQTT Publish' },
  { value: 'digital_output', label: 'Digital Output' },
  { value: 'script_run', label: 'Run Sequence' },
  { value: 'system_command', label: 'System Command' }
]

// System command options
const systemCommands: { value: SystemCommandType; label: string }[] = [
  { value: 'acquisition_start', label: 'Start Acquisition' },
  { value: 'acquisition_stop', label: 'Stop Acquisition' },
  { value: 'recording_start', label: 'Start Recording' },
  { value: 'recording_stop', label: 'Stop Recording' },
  { value: 'alarm_acknowledge_all', label: 'Acknowledge All Alarms' },
  { value: 'latch_reset_all', label: 'Reset All Latched' }
]

// Initialize button action if not present
function ensureButtonAction(): ButtonAction {
  if (!localWidget.value.buttonAction) {
    localWidget.value.buttonAction = { type: 'system_command' }
  }
  return localWidget.value.buttonAction
}

// Update button action property
function updateButtonAction<K extends keyof ButtonAction>(key: K, value: ButtonAction[K]) {
  const action = ensureButtonAction()
  action[key] = value
}

// Toggle channel in channels array (for value_table, charts)
function toggleChannel(channelName: string, add: boolean) {
  if (!localWidget.value.channels) {
    localWidget.value.channels = []
  }
  if (add && !localWidget.value.channels.includes(channelName)) {
    localWidget.value.channels.push(channelName)
  } else if (!add) {
    localWidget.value.channels = localWidget.value.channels.filter(c => c !== channelName)
  }
}

// Save changes
function save() {
  if (!props.widgetId || !localWidget.value) return
  store.updateWidget(props.widgetId, localWidget.value)
  emit('close')
}

// Cancel without saving
function cancel() {
  emit('close')
}

// Update style property
function updateStyle(key: keyof WidgetStyle, value: string) {
  if (!localWidget.value.style) {
    localWidget.value.style = {}
  }
  ;(localWidget.value.style as Record<string, string>)[key] = value
}

// ============================================
// Chart Plot Style Helpers
// ============================================

// Get plot style for a channel
function getPlotStyle(channel: string): ChartPlotStyle {
  const styles = localWidget.value.plotStyles || []
  const existing = styles.find(s => s.channel === channel)
  if (existing) return existing

  // Create default style with indexed color
  const idx = localWidget.value.channels?.indexOf(channel) ?? 0
  return {
    channel,
    color: CHART_COLORS[idx % CHART_COLORS.length] || '#4ade80',
    lineWidth: 1.5,
    lineStyle: 'solid',
    showMarkers: false,
    markerStyle: 'circle',
    yAxisId: 0,
    visible: true
  }
}

// Update plot style for a channel
function updatePlotStyle(channel: string, updates: Partial<ChartPlotStyle>) {
  if (!localWidget.value.plotStyles) {
    localWidget.value.plotStyles = []
  }

  const idx = localWidget.value.plotStyles.findIndex(s => s.channel === channel)
  if (idx >= 0) {
    // Merge updates into existing style (existing style has all required fields)
    const existing = localWidget.value.plotStyles[idx]
    if (existing) {
      Object.assign(existing, updates)
    }
  } else {
    // Create new entry with all required fields
    const channelIdx = localWidget.value.channels?.indexOf(channel) ?? 0
    const newStyle: ChartPlotStyle = {
      channel,
      color: CHART_COLORS[channelIdx % CHART_COLORS.length] || '#4ade80',
      lineWidth: 1.5,
      lineStyle: 'solid',
      showMarkers: false,
      markerStyle: 'circle',
      yAxisId: 0,
      visible: true
    }
    // Apply updates (already have defaults for all required fields)
    Object.assign(newStyle, updates)
    localWidget.value.plotStyles.push(newStyle)
  }
}

// Get selected channels for chart
const selectedChartChannels = computed(() => {
  return localWidget.value.channels || []
})
</script>

<template>
  <Teleport to="body">
    <div v-if="widgetId" class="modal-overlay" @click.self="cancel">
      <div class="modal widget-config-modal">
        <div class="modal-header">
          <h3>Configure {{ widgetType }} Widget</h3>
          <button class="close-btn" @click="cancel">×</button>
        </div>

        <div class="modal-body">
          <!-- Common: Custom Label (overrides TAG display) -->
          <div class="form-group">
            <label>Custom Label</label>
            <input
              type="text"
              v-model="localWidget.label"
              placeholder="Leave empty to show TAG"
            />
          </div>

          <!-- Channel selection (for single-channel widgets) -->
          <div v-if="['numeric', 'gauge', 'led', 'toggle', 'setpoint', 'sparkline', 'svg_symbol'].includes(widgetType)" class="form-group">
            <label>Channel</label>
            <select v-model="localWidget.channel">
              <option value="">-- Select Channel --</option>
              <option v-for="[name, config] in availableChannels" :key="name" :value="name">
                {{ name }} ({{ formatUnit(config.unit) || 'no unit' }})
              </option>
            </select>
          </div>

          <!-- Numeric/Gauge specific -->
          <template v-if="['numeric', 'gauge'].includes(widgetType)">
            <div class="form-group">
              <label>Decimal Places</label>
              <input
                type="number"
                v-model.number="localWidget.decimals"
                min="0"
                max="6"
              />
            </div>
            <div class="form-row">
              <div class="form-group half checkbox">
                <label>
                  <input type="checkbox" v-model="localWidget.showLabel" />
                  Show Tag
                </label>
              </div>
              <div class="form-group half checkbox">
                <label>
                  <input type="checkbox" v-model="localWidget.showUnit" />
                  Show Unit
                </label>
              </div>
            </div>
          </template>

          <!-- Compact/Industrial mode (numeric, led, value_table) -->
          <template v-if="['numeric', 'led', 'value_table'].includes(widgetType)">
            <div class="config-section">
              <div class="section-header">Display Mode</div>
              <div class="form-row">
                <div class="form-group half checkbox">
                  <label>
                    <input
                      type="checkbox"
                      v-model="localWidget.compact"
                    />
                    Compact
                  </label>
                </div>
                <div class="form-group half checkbox">
                  <label>
                    <input
                      type="checkbox"
                      v-model="localWidget.industrial"
                    />
                    Industrial Style
                  </label>
                </div>
              </div>
            </div>
          </template>

          <!-- Value Table specific -->
          <template v-if="widgetType === 'value_table'">
            <div class="form-group">
              <label>Channels</label>
              <div class="channel-checkboxes">
                <label v-for="[name, config] in availableChannels" :key="name" class="channel-checkbox">
                  <input
                    type="checkbox"
                    :checked="localWidget.channels?.includes(name)"
                    @change="toggleChannel(name, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ name }}</span>
                </label>
              </div>
            </div>
            <div class="form-group">
              <label>Decimal Places</label>
              <input type="number" v-model.number="localWidget.decimals" min="0" max="6" />
            </div>
            <div class="form-row">
              <div class="form-group half checkbox">
                <label>
                  <input type="checkbox" v-model="localWidget.showUnits" />
                  Show Units
                </label>
              </div>
              <div class="form-group half checkbox">
                <label>
                  <input type="checkbox" v-model="localWidget.showStatus" />
                  Show Status
                </label>
              </div>
            </div>
          </template>

          <!-- Chart specific -->
          <template v-if="widgetType === 'chart'">
            <!-- Update Mode (LabVIEW-style) -->
            <div class="config-section">
              <div class="section-header">Chart Mode</div>
              <div class="form-group">
                <label>Update Mode</label>
                <select v-model="localWidget.updateMode">
                  <option value="strip">Strip Chart (scrolling)</option>
                  <option value="scope">Scope Chart (clear & restart)</option>
                  <option value="sweep">Sweep Chart (moving line)</option>
                </select>
                <span class="hint">How data is displayed as it updates</span>
              </div>
            </div>

            <!-- X-Axis Settings -->
            <div class="config-section">
              <div class="section-header">X-Axis (Time)</div>
              <div class="form-group">
                <label>Time Range (seconds)</label>
                <input
                  type="number"
                  v-model.number="localWidget.timeRange"
                  min="10"
                  max="3600"
                />
                <span class="hint">How much history to display</span>
              </div>
              <div class="form-group">
                <label>History Buffer Size</label>
                <input
                  type="number"
                  v-model.number="localWidget.historySize"
                  min="100"
                  max="10000"
                  placeholder="1024"
                />
                <span class="hint">Max data points to keep (default 1024)</span>
              </div>
            </div>

            <!-- Y-Axis Settings -->
            <div class="config-section">
              <div class="section-header">Y-Axis</div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.yAxisAuto"
                  />
                  Auto-scale
                </label>
              </div>
              <template v-if="localWidget.yAxisAuto === false">
                <div class="form-row">
                  <div class="form-group half">
                    <label>Min</label>
                    <input type="number" v-model.number="localWidget.yAxisMin" step="any" />
                  </div>
                  <div class="form-group half">
                    <label>Max</label>
                    <input type="number" v-model.number="localWidget.yAxisMax" step="any" />
                  </div>
                </div>
              </template>
            </div>

            <!-- Display Options -->
            <div class="config-section">
              <div class="section-header">Display Options</div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showGrid"
                  />
                  Show Grid Lines
                </label>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showLegend"
                  />
                  Show Legend
                </label>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showDigitalDisplay"
                  />
                  Show Digital Display
                </label>
                <span class="hint">Display current values in header</span>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showScrollbar"
                  />
                  Show History Scrollbar
                </label>
                <span class="hint">Navigate through historical data</span>
              </div>
            </div>

            <!-- Channels -->
            <div class="config-section">
              <div class="section-header">Channels</div>
              <div class="form-group">
                <div class="channel-checklist">
                  <label v-for="[name, config] in availableChannels" :key="name" class="channel-item">
                    <input
                      type="checkbox"
                      :checked="localWidget.channels?.includes(name as string)"
                      @change="(e) => {
                        const checked = (e.target as HTMLInputElement).checked
                        if (!localWidget.channels) localWidget.channels = []
                        if (checked && !localWidget.channels.includes(name as string)) {
                          localWidget.channels.push(name as string)
                        } else if (!checked) {
                          localWidget.channels = localWidget.channels.filter(c => c !== name)
                        }
                      }"
                    />
                    <span>{{ name }}</span>
                  </label>
                </div>
              </div>
            </div>

            <!-- Per-Channel Styling (only shows selected channels) -->
            <div v-if="selectedChartChannels.length > 0" class="config-section">
              <div class="section-header">Channel Styling</div>
              <div class="channel-style-list">
                <div
                  v-for="channel in selectedChartChannels"
                  :key="channel"
                  class="channel-style-row"
                >
                  <div class="channel-style-preview" :style="{ backgroundColor: getPlotStyle(channel).color }"></div>
                  <span class="channel-style-name">{{ channel }}</span>

                  <div class="channel-style-controls">
                    <!-- Color picker -->
                    <label class="color-picker-label" title="Line Color">
                      <input
                        type="color"
                        :value="getPlotStyle(channel).color"
                        @input="(e) => updatePlotStyle(channel, { color: (e.target as HTMLInputElement).value })"
                        class="color-picker"
                      />
                    </label>

                    <!-- Line width -->
                    <select
                      :value="getPlotStyle(channel).lineWidth || 1.5"
                      @change="(e) => updatePlotStyle(channel, { lineWidth: parseFloat((e.target as HTMLSelectElement).value) })"
                      class="line-width-select"
                      title="Line Width"
                    >
                      <option :value="0.5">Thin</option>
                      <option :value="1">Normal</option>
                      <option :value="1.5">Medium</option>
                      <option :value="2">Thick</option>
                      <option :value="3">Bold</option>
                    </select>

                    <!-- Visibility toggle -->
                    <button
                      type="button"
                      class="visibility-btn"
                      :class="{ hidden: getPlotStyle(channel).visible === false }"
                      @click="updatePlotStyle(channel, { visible: getPlotStyle(channel).visible === false })"
                      :title="getPlotStyle(channel).visible === false ? 'Show' : 'Hide'"
                    >
                      <svg v-if="getPlotStyle(channel).visible !== false" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                        <circle cx="12" cy="12" r="3"/>
                      </svg>
                      <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/>
                        <line x1="1" y1="1" x2="23" y2="23"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- LED specific -->
          <template v-if="widgetType === 'led'">
            <div class="form-group">
              <label>On Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.led.on"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.onColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('onColor', color)"
                />
              </div>
            </div>
            <div class="form-group">
              <label>Off Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.led.off"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.offColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('offColor', color)"
                />
              </div>
            </div>
          </template>

          <!-- Title specific -->
          <template v-if="widgetType === 'title'">
            <div class="form-group">
              <label>Font Size</label>
              <select
                :value="localWidget.style?.fontSize || 'medium'"
                @change="updateStyle('fontSize', ($event.target as HTMLSelectElement).value)"
              >
                <option value="small">Small</option>
                <option value="medium">Medium</option>
                <option value="large">Large</option>
                <option value="xlarge">Extra Large</option>
              </select>
            </div>
            <div class="form-group">
              <label>Text Align</label>
              <select
                :value="localWidget.style?.textAlign || 'left'"
                @change="updateStyle('textAlign', ($event.target as HTMLSelectElement).value)"
              >
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </div>
            <div class="form-group">
              <label>Text Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.text"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.textColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('textColor', color)"
                />
              </div>
            </div>
            <div class="form-group">
              <label>Background</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.background"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.backgroundColor === color, transparent: color === 'transparent' }"
                  :style="{ backgroundColor: color === 'transparent' ? '#333' : color }"
                  @click="updateStyle('backgroundColor', color)"
                >
                  <span v-if="color === 'transparent'" class="transparent-icon">∅</span>
                </button>
              </div>
            </div>
          </template>

          <!-- Action Button specific -->
          <template v-if="widgetType === 'action_button'">
            <!-- Action Type -->
            <div class="form-group">
              <label>Action Type</label>
              <select
                :value="localWidget.buttonAction?.type || 'system_command'"
                @change="updateButtonAction('type', ($event.target as HTMLSelectElement).value as ButtonActionType)"
              >
                <option v-for="opt in buttonActionTypes" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <!-- MQTT Publish options -->
            <template v-if="localWidget.buttonAction?.type === 'mqtt_publish'">
              <div class="form-group">
                <label>Topic</label>
                <input
                  type="text"
                  :value="localWidget.buttonAction?.topic || ''"
                  @input="updateButtonAction('topic', ($event.target as HTMLInputElement).value)"
                  placeholder="nisystem/command/..."
                />
              </div>
              <div class="form-group">
                <label>Payload</label>
                <input
                  type="text"
                  :value="localWidget.buttonAction?.payload || ''"
                  @input="updateButtonAction('payload', ($event.target as HTMLInputElement).value)"
                  placeholder="Message payload"
                />
              </div>
            </template>

            <!-- Digital Output options -->
            <template v-if="localWidget.buttonAction?.type === 'digital_output'">
              <div class="form-group">
                <label>Output Channel</label>
                <select
                  :value="localWidget.buttonAction?.channel || ''"
                  @change="updateButtonAction('channel', ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">-- Select Channel --</option>
                  <option v-for="[name, config] in digitalOutputChannels" :key="name" :value="name">
                    {{ name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>Set Value</label>
                <select
                  :value="localWidget.buttonAction?.setValue ?? 1"
                  @change="updateButtonAction('setValue', Number(($event.target as HTMLSelectElement).value))"
                >
                  <option :value="1">ON (1)</option>
                  <option :value="0">OFF (0)</option>
                </select>
              </div>
              <div class="form-group">
                <label>Pulse Duration (ms)</label>
                <input
                  type="number"
                  :value="localWidget.buttonAction?.pulseMs || 0"
                  @input="updateButtonAction('pulseMs', Number(($event.target as HTMLInputElement).value))"
                  min="0"
                  placeholder="0 = stay on"
                />
                <p class="hint">0 = permanent, otherwise reverts after duration</p>
              </div>
            </template>

            <!-- Script Run options -->
            <template v-if="localWidget.buttonAction?.type === 'script_run'">
              <div class="form-group">
                <label>Sequence</label>
                <select
                  :value="localWidget.buttonAction?.sequenceId || ''"
                  @change="updateButtonAction('sequenceId', ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">-- Select Sequence --</option>
                  <option v-for="seq in availableSequences" :key="seq.id" :value="seq.id">
                    {{ seq.name }}
                  </option>
                </select>
                <p v-if="availableSequences.length === 0" class="hint">No sequences defined yet</p>
              </div>
            </template>

            <!-- System Command options -->
            <template v-if="localWidget.buttonAction?.type === 'system_command'">
              <div class="form-group">
                <label>Command</label>
                <select
                  :value="localWidget.buttonAction?.command || ''"
                  @change="updateButtonAction('command', ($event.target as HTMLSelectElement).value as SystemCommandType)"
                >
                  <option value="">-- Select Command --</option>
                  <option v-for="cmd in systemCommands" :key="cmd.value" :value="cmd.value">
                    {{ cmd.label }}
                  </option>
                </select>
              </div>
            </template>

            <!-- Confirmation required -->
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.requireConfirmation" />
                Require Confirmation
              </label>
              <p class="hint">Shows YES/NO before executing</p>
            </div>

            <!-- Button Color -->
            <div class="form-group">
              <label>Button Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.button"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.buttonColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="localWidget.buttonColor = color"
                />
              </div>
            </div>
          </template>

          <!-- Clock specific -->
          <template v-if="widgetType === 'clock'">
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showDate" />
                Show Date
              </label>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showElapsed" />
                Show Run Elapsed Time
              </label>
              <p class="hint">Shows elapsed time when acquisition is running</p>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.format24h" />
                24-Hour Format
              </label>
            </div>
          </template>

          <!-- Gauge specific -->
          <template v-if="widgetType === 'gauge'">
            <div class="form-group">
              <label>Min Value</label>
              <input
                type="number"
                v-model.number="localWidget.minValue"
                placeholder="Auto from channel limits"
              />
              <p class="hint">Leave empty to use channel low limit</p>
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input
                type="number"
                v-model.number="localWidget.maxValue"
                placeholder="Auto from channel limits"
              />
              <p class="hint">Leave empty to use channel high limit</p>
            </div>
          </template>

          <!-- Setpoint specific -->
          <template v-if="widgetType === 'setpoint'">
            <div class="form-group">
              <label>Min Value</label>
              <input type="number" v-model.number="localWidget.minValue" placeholder="0" />
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input type="number" v-model.number="localWidget.maxValue" placeholder="100" />
            </div>
            <div class="form-group">
              <label>Step Size</label>
              <input type="number" v-model.number="localWidget.step" placeholder="1" min="0.001" step="0.1" />
            </div>
          </template>

          <!-- Bar Graph specific -->
          <template v-if="widgetType === 'bar_graph'">
            <div class="form-group">
              <label>Orientation</label>
              <select v-model="localWidget.orientation">
                <option value="horizontal">Horizontal</option>
                <option value="vertical">Vertical</option>
              </select>
            </div>
            <div class="form-group">
              <label>Min Value</label>
              <input type="number" v-model.number="localWidget.minValue" placeholder="Auto" />
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input type="number" v-model.number="localWidget.maxValue" placeholder="Auto" />
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showValue" />
                Show Value
              </label>
            </div>
          </template>

          <!-- Divider specific -->
          <template v-if="widgetType === 'divider'">
            <div class="form-group">
              <label>Orientation</label>
              <select v-model="localWidget.orientation">
                <option value="horizontal">Horizontal</option>
                <option value="vertical">Vertical</option>
              </select>
            </div>
            <div class="form-group">
              <label>Line Style</label>
              <select v-model="localWidget.lineStyle">
                <option value="solid">Solid</option>
                <option value="dashed">Dashed</option>
                <option value="dotted">Dotted</option>
              </select>
            </div>
            <div class="form-group">
              <label>Line Color</label>
              <div class="color-options">
                <button
                  v-for="color in ['#3b82f6', '#22c55e', '#fbbf24', '#ef4444', '#888888', '#ffffff']"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.lineColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="localWidget.lineColor = color"
                />
              </div>
            </div>
          </template>

          <!-- SVG Symbol specific -->
          <template v-if="widgetType === 'svg_symbol'">
            <div class="form-group">
              <label>Symbol Type</label>
              <select v-model="localWidget.symbol">
                <option value="">-- Select Symbol --</option>
                <optgroup v-for="(symbols, category) in symbolsByCategory" :key="category" :label="category">
                  <option v-for="[key, info] in symbols" :key="key" :value="key">
                    {{ info.label }}
                  </option>
                </optgroup>
              </select>
            </div>
            <div class="form-row">
              <div class="form-group half">
                <label>Symbol Size</label>
                <select v-model="localWidget.symbolSize">
                  <option value="small">Small</option>
                  <option value="medium">Medium</option>
                  <option value="large">Large</option>
                </select>
              </div>
              <div class="form-group half">
                <label>Rotation</label>
                <select v-model.number="localWidget.rotation">
                  <option :value="0">0° (default)</option>
                  <option :value="90">90° (clockwise)</option>
                  <option :value="180">180° (flip)</option>
                  <option :value="270">270° (counter-clockwise)</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>Value Position</label>
              <select v-model="localWidget.valuePosition">
                <option value="bottom">Below Symbol</option>
                <option value="top">Above Symbol</option>
                <option value="left">Left of Symbol</option>
                <option value="right">Right of Symbol</option>
                <option value="inside">Inside Symbol</option>
              </select>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showValue" />
                Show Value
              </label>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showLabel" />
                Show Label
              </label>
            </div>
            <div class="form-group">
              <label>Decimal Places</label>
              <input type="number" v-model.number="localWidget.decimals" min="0" max="6" />
            </div>
            <div class="form-group">
              <label>Accent Color (optional)</label>
              <div class="color-options">
                <button
                  class="color-btn"
                  :class="{ selected: !localWidget.accentColor }"
                  style="background: linear-gradient(45deg, #60a5fa, #22c55e);"
                  @click="localWidget.accentColor = undefined"
                  title="Auto (status-based)"
                />
                <button
                  v-for="color in ['#60a5fa', '#22c55e', '#fbbf24', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#ffffff']"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.accentColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="localWidget.accentColor = color"
                />
              </div>
              <p class="hint">Leave auto for status-based coloring</p>
            </div>
          </template>

          <!-- Script Monitor specific -->
          <template v-if="widgetType === 'script_monitor'">
            <div class="config-section">
              <div class="section-header">Display Options</div>
              <div class="form-row">
                <div class="form-group half">
                  <label>Columns</label>
                  <select v-model.number="localWidget.columns">
                    <option :value="1">1 Column</option>
                    <option :value="2">2 Columns</option>
                    <option :value="3">3 Columns</option>
                  </select>
                </div>
                <div class="form-group half checkbox" style="padding-top: 20px;">
                  <label>
                    <input type="checkbox" v-model="localWidget.compact" />
                    Compact Mode
                  </label>
                </div>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input type="checkbox" v-model="localWidget.showTimestamp" />
                  Show Timestamp
                </label>
              </div>
            </div>

            <div class="config-section">
              <div class="section-header">Monitor Items</div>
              <p class="hint">Add tags to monitor (e.g., py.Recipe_Step, Temperature_1)</p>

              <div v-if="localWidget.items && localWidget.items.length > 0" class="monitor-items-list">
                <div
                  v-for="(item, idx) in localWidget.items"
                  :key="idx"
                  class="monitor-item-config"
                >
                  <div class="monitor-item-header">
                    <span class="item-tag">{{ item.tag || 'New Item' }}</span>
                    <button
                      type="button"
                      class="btn-icon btn-danger-text"
                      @click="localWidget.items?.splice(idx, 1)"
                      title="Remove"
                    >×</button>
                  </div>
                  <div class="monitor-item-fields">
                    <div class="form-group">
                      <label>Tag</label>
                      <input type="text" v-model="item.tag" placeholder="py.Recipe_Step" />
                    </div>
                    <div class="form-row">
                      <div class="form-group half">
                        <label>Label</label>
                        <input type="text" v-model="item.label" placeholder="Display name" />
                      </div>
                      <div class="form-group half">
                        <label>Unit</label>
                        <input type="text" v-model="item.unit" placeholder="°C, %, etc." />
                      </div>
                    </div>
                    <div class="form-row">
                      <div class="form-group half">
                        <label>Format</label>
                        <select v-model="item.format">
                          <option value="number">Number</option>
                          <option value="integer">Integer</option>
                          <option value="percent">Percent</option>
                          <option value="status">Status (ON/OFF)</option>
                          <option value="text">Text</option>
                        </select>
                      </div>
                      <div class="form-group half">
                        <label>Decimals</label>
                        <input type="number" v-model.number="item.decimals" min="0" max="6" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <button
                type="button"
                class="btn btn-secondary btn-add-item"
                @click="() => {
                  if (!localWidget.items) localWidget.items = []
                  localWidget.items.push({ tag: '', format: 'number', decimals: 2 })
                }"
              >
                + Add Item
              </button>
            </div>
          </template>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancel">Cancel</button>
          <button class="btn btn-primary" @click="save">Save</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.widget-config-modal {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  min-width: 360px;
  max-width: 480px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.modal-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
  text-transform: capitalize;
}

.modal-header .close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.modal-header .close-btn:hover {
  color: #fff;
}

.modal-body {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 4px;
}

.form-group.checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  cursor: pointer;
}

.form-group input[type="text"],
.form-group input[type="number"],
.form-group select {
  width: 100%;
  padding: 8px 12px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.9rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #3b82f6;
}

.channel-checklist {
  max-height: 200px;
  overflow-y: auto;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 8px;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  color: #ccc;
  cursor: pointer;
}

.channel-item:hover {
  color: #fff;
}

.channel-checkboxes {
  max-height: 180px;
  overflow-y: auto;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.channel-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.8rem;
  color: #aaa;
}

.channel-checkbox:hover {
  background: #1a1a2e;
  color: #fff;
}

.channel-checkbox input {
  margin: 0;
}

.color-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.color-btn {
  width: 32px;
  height: 32px;
  border: 2px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.color-btn:hover {
  transform: scale(1.1);
}

.color-btn.selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);
}

.color-btn.transparent {
  background: repeating-linear-gradient(
    45deg,
    #333,
    #333 4px,
    #444 4px,
    #444 8px
  ) !important;
}

.transparent-icon {
  color: #888;
  font-size: 1rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover {
  background: #4b5563;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}

.hint {
  font-size: 0.7rem;
  color: #666;
  margin-top: 4px;
  font-style: italic;
}

/* Config sections for organized settings */
.config-section {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #2a2a4a;
}

.config-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
}

.section-header {
  font-size: 0.75rem;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

/* Form row for side-by-side inputs */
.form-row {
  display: flex;
  gap: 12px;
}

.form-group.half {
  flex: 1;
  margin-bottom: 12px;
}

/* Channel Styling Section */
.channel-style-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.channel-style-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: #0f0f1a;
  border-radius: 4px;
  border: 1px solid #2a2a4a;
}

.channel-style-preview {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.channel-style-name {
  flex: 1;
  font-size: 0.85rem;
  color: #ccc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.channel-style-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.color-picker-label {
  display: flex;
  cursor: pointer;
}

.color-picker {
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: 0;
}

.color-picker::-webkit-color-swatch {
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

.line-width-select {
  width: auto;
  padding: 4px 6px;
  font-size: 0.75rem;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 3px;
  color: #ccc;
}

.visibility-btn {
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  transition: all 0.15s;
}

.visibility-btn:hover {
  color: #fff;
  background: #2a2a4a;
}

.visibility-btn.hidden {
  color: #666;
}

.visibility-btn.hidden:hover {
  color: #ef4444;
}

/* Script Monitor Item Config */
.monitor-items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.monitor-item-config {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  overflow: hidden;
}

.monitor-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a4a;
}

.item-tag {
  font-size: 0.85rem;
  font-weight: 500;
  color: #4ade80;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}

.monitor-item-fields {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.monitor-item-fields .form-group {
  margin-bottom: 0;
}

.monitor-item-fields .form-row {
  margin-bottom: 0;
}

.btn-add-item {
  width: 100%;
  margin-top: 8px;
}

.btn-icon {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  transition: all 0.15s;
}

.btn-icon:hover {
  background: rgba(239, 68, 68, 0.2);
}
</style>
