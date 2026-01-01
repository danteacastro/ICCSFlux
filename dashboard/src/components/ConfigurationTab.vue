<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { ChannelType, ChannelConfig } from '../types'
import {
  THERMOCOUPLE_TYPES,
  VOLTAGE_RANGES,
  TERMINAL_CONFIGS,
  CURRENT_RANGES,
  RTD_TYPES,
  BRIDGE_CONFIGS,
  DEFAULT_THERMOCOUPLE_CONFIG,
  DEFAULT_VOLTAGE_INPUT_CONFIG,
  DEFAULT_CURRENT_INPUT_CONFIG,
  DEFAULT_RTD_CONFIG,
  DEFAULT_DIGITAL_INPUT_CONFIG,
  DEFAULT_DIGITAL_OUTPUT_CONFIG,
} from '../types/modules'
import { useMqtt } from '../composables/useMqtt'
import { useProjectManager } from '../composables/useProjectManager'

const store = useDashboardStore()

// MQTT connection - get from parent or create new
const mqtt = useMqtt()

// Project manager for export/import
const projectManager = useProjectManager()
const isExporting = ref(false)
const isReloading = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)

// Edit mode - only allow editing when explicitly enabled and not acquiring
const editMode = ref(false)
const canEdit = computed(() => editMode.value && !store.isAcquiring)

async function exportProject() {
  isExporting.value = true
  try {
    const result = await projectManager.downloadProject(store.systemName)
    if (result.success) {
      showFeedback('success', result.message)
    } else {
      showFeedback('error', result.message)
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Export failed')
  } finally {
    isExporting.value = false
  }
}

function triggerImport() {
  importFileInput.value?.click()
}

async function handleImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const result = await projectManager.loadProjectFromFile(file)
  if (result.success) {
    showFeedback('success', result.message)
  } else {
    showFeedback('error', result.message)
  }

  // Reset input so same file can be selected again
  input.value = ''
}

// Configuration dirty state tracking
const configDirty = ref(false)
const currentConfigName = ref('system.ini')

// Save As dialog state
const showSaveAsDialog = ref(false)
const saveAsFilename = ref('')

// Unsaved changes dialog state
const showUnsavedChangesDialog = ref(false)
const pendingAction = ref<(() => void) | null>(null)

// Mark configuration as dirty
function markDirty() {
  configDirty.value = true
}

// Check for unsaved changes before action
function checkUnsavedChanges(action: () => void) {
  if (configDirty.value) {
    pendingAction.value = action
    showUnsavedChangesDialog.value = true
  } else {
    action()
  }
}

// Handle unsaved changes dialog response
function handleUnsavedChanges(choice: 'save' | 'discard' | 'cancel') {
  showUnsavedChangesDialog.value = false
  if (choice === 'save') {
    saveToFile()
    if (pendingAction.value) {
      pendingAction.value()
    }
  } else if (choice === 'discard') {
    configDirty.value = false
    if (pendingAction.value) {
      pendingAction.value()
    }
  }
  // 'cancel' does nothing, just closes dialog
  pendingAction.value = null
}

// Add Channel Modal State
const showAddChannelModal = ref(false)
const newChannelForm = ref({
  name: '',
  physical_channel: '',
  channel_type: 'thermocouple' as ChannelType,
  display_name: '',
  unit: '',
  group: '',
  description: ''
})

// System Settings State
const showSystemSettings = ref(false)
const systemSettingsForm = ref({
  scan_rate_hz: 100,
  publish_rate_hz: 10
})

// Channel enable states (tracked separately for reactivity)
const channelEnabled = ref<Record<string, boolean>>({})

// Initialize enable states from store
function initializeEnableStates() {
  Object.keys(store.channels).forEach(name => {
    if (channelEnabled.value[name] === undefined) {
      channelEnabled.value[name] = true // Default to enabled
    }
  })
}

// Toggle channel enable state
function toggleChannelEnabled(channelName: string) {
  channelEnabled.value[channelName] = !channelEnabled.value[channelName]
  // Send update to backend
  if (mqtt.connected.value) {
    mqtt.updateChannelConfig(channelName, {
      enabled: channelEnabled.value[channelName]
    })
    markDirty()
  }
}

// Update a single channel field inline (for editable table cells)
function updateChannelField(channelName: string, field: string, value: any) {
  if (!canEdit.value) return
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  mqtt.updateChannelConfig(channelName, { [field]: value })
  markDirty()
}

// Add new channel
function openAddChannelModal() {
  newChannelForm.value = {
    name: '',
    physical_channel: '',
    channel_type: 'thermocouple',
    display_name: '',
    unit: '',
    group: '',
    description: ''
  }
  showAddChannelModal.value = true
}

function addNewChannel() {
  if (!newChannelForm.value.name) {
    showFeedback('error', 'Channel name is required')
    return
  }

  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  const config = {
    name: newChannelForm.value.name,
    physical_channel: newChannelForm.value.physical_channel || newChannelForm.value.name,
    channel_type: newChannelForm.value.channel_type,
    display_name: newChannelForm.value.display_name || newChannelForm.value.name,
    unit: newChannelForm.value.unit || getDefaultUnit(newChannelForm.value.channel_type),
    group: newChannelForm.value.group || 'Default',
    description: newChannelForm.value.description,
    enabled: true
  }

  mqtt.updateChannelConfig(newChannelForm.value.name, config)
  showFeedback('success', `Adding channel: ${newChannelForm.value.name}`)
  channelEnabled.value[newChannelForm.value.name] = true
  showAddChannelModal.value = false
  markDirty()
}

function getDefaultUnit(channelType: ChannelType): string {
  const units: Record<ChannelType, string> = {
    thermocouple: '°C',
    rtd: '°C',
    voltage: 'V',
    current: 'mA',
    strain: 'µε',
    iepe: 'g',
    counter: 'counts',
    resistance: 'Ω',
    digital_input: '',
    digital_output: '',
    analog_output: 'V'
  }
  return units[channelType] || ''
}

// Delete channel
function deleteChannel(channelName: string, event: Event) {
  event.stopPropagation()

  if (!confirm(`Delete channel "${channelName}"? This cannot be undone.`)) {
    return
  }

  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Send delete command to backend
  mqtt.sendCommand('config/channel/delete', { channel: channelName })
  showFeedback('info', `Deleting channel: ${channelName}...`)

  // Close config panel if this channel was selected
  if (selectedChannel.value === channelName) {
    closeConfigPanel()
  }

  // Remove from local enable state
  delete channelEnabled.value[channelName]
  markDirty()
}

// Reset counter to zero
function resetCounter(channelName: string) {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Send reset command to backend
  mqtt.resetCounter(channelName)
  showFeedback('info', `Resetting counter: ${channelName}`)
}

// Open system settings
function openSystemSettings() {
  systemSettingsForm.value = {
    scan_rate_hz: store.status?.scan_rate_hz || 100,
    publish_rate_hz: store.status?.publish_rate_hz || 10
  }
  showSystemSettings.value = true
}

function saveSystemSettings() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  mqtt.sendCommand('config/system/update', {
    scan_rate_hz: systemSettingsForm.value.scan_rate_hz,
    publish_rate_hz: systemSettingsForm.value.publish_rate_hz
  })
  showFeedback('info', 'Updating system settings...')
  showSystemSettings.value = false
}

// Discovery state
const isScanning = computed(() => mqtt.isScanning.value)
const discoveryChannels = computed(() => mqtt.discoveryChannels.value)
const showDiscoveryPanel = ref(false)
const selectedDiscoveryChannels = ref<string[]>([])

// Feedback messages
const feedbackMessage = ref<{ type: 'success' | 'error' | 'info', text: string } | null>(null)

function showFeedback(type: 'success' | 'error' | 'info', text: string, duration = 3000) {
  feedbackMessage.value = { type, text }
  setTimeout(() => {
    feedbackMessage.value = null
  }, duration)
}

// Device discovery
function scanDevices() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  showFeedback('info', 'Scanning for NI devices...')
  mqtt.scanDevices()
  showDiscoveryPanel.value = true
}

// Handle discovery result
mqtt.onDiscovery((result) => {
  if (result.success) {
    showFeedback('success', `Found ${result.devices?.length || 0} device(s)`)
  } else {
    showFeedback('error', result.error || 'Discovery failed')
  }
})

// Add discovered channels to config
function addSelectedChannels() {
  const channels = discoveryChannels.value.filter(ch =>
    selectedDiscoveryChannels.value.includes(ch.physical_channel)
  )

  if (channels.length === 0) {
    showFeedback('error', 'No channels selected')
    return
  }

  // Send to backend to add channels
  channels.forEach(ch => {
    mqtt.updateChannelConfig(ch.physical_channel, {
      name: ch.physical_channel,
      type: ch.measurement_type,
      description: ch.suggested_name,
      module: ch.module_name,
      enabled: true
    })
  })

  showFeedback('success', `Adding ${channels.length} channel(s)...`)
  selectedDiscoveryChannels.value = []
  showDiscoveryPanel.value = false
}

function toggleDiscoveryChannel(physicalChannel: string) {
  const idx = selectedDiscoveryChannels.value.indexOf(physicalChannel)
  if (idx >= 0) {
    selectedDiscoveryChannels.value.splice(idx, 1)
  } else {
    selectedDiscoveryChannels.value.push(physicalChannel)
  }
}

function selectAllDiscoveryChannels() {
  selectedDiscoveryChannels.value = discoveryChannels.value.map(ch => ch.physical_channel)
}

function deselectAllDiscoveryChannels() {
  selectedDiscoveryChannels.value = []
}

// Channel type tabs
const channelTypeTabs = [
  { id: 'all', label: 'ALL CHANNELS', icon: '⊞' },
  { id: 'current', label: 'CURRENT INPUT', icon: '〰' },
  { id: 'voltage', label: 'VOLTAGE INPUT', icon: '⚡' },
  { id: 'current_output', label: 'CURRENT OUTPUT', icon: '〰' },
  { id: 'voltage_output', label: 'VOLTAGE OUTPUT', icon: '↗' },
  { id: 'digital_input', label: 'DIGITAL INPUT', icon: '▢' },
  { id: 'digital_output', label: 'DIGITAL OUTPUT', icon: '▣' },
  { id: 'counter', label: 'COUNTER', icon: '#' },
  { id: 'thermocouple', label: 'THERMOCOUPLE', icon: '🌡' },
  { id: 'rtd', label: 'RTD', icon: '🌡' },
  { id: 'strain', label: 'STRAIN/BRIDGE', icon: '⚖' },
  { id: 'iepe', label: 'IEPE/ACCEL', icon: '〰' },
  { id: 'resistance', label: 'RESISTANCE', icon: 'Ω' },
]

const activeTypeTab = ref('all')
const searchQuery = ref('')
const selectedChannel = ref<string | null>(null)
const showConfigPanel = ref(false)

// Filtered channels based on active tab and search
const filteredChannels = computed(() => {
  let channels = Object.entries(store.channels)

  // Filter by type
  if (activeTypeTab.value !== 'all') {
    // Handle virtual output types (voltage_output and current_output filter analog_output)
    if (activeTypeTab.value === 'voltage_output') {
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'analog_output' &&
        (ch.ao_range?.includes('V') || !ch.ao_range?.includes('mA'))
      )
    } else if (activeTypeTab.value === 'current_output') {
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'analog_output' &&
        ch.ao_range?.includes('mA')
      )
    } else {
      channels = channels.filter(([_, ch]) => ch.channel_type === activeTypeTab.value)
    }
  }

  // Filter by search
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    channels = channels.filter(([name, ch]) =>
      name.toLowerCase().includes(query) ||
      ch.display_name?.toLowerCase().includes(query) ||
      ch.description?.toLowerCase().includes(query)
    )
  }

  return channels
})

// Get current value for a channel
function getCurrentValue(channelName: string): string {
  const value = store.values[channelName]
  if (!value) return '--'
  return value.value.toFixed(2)
}

// Get raw value (before scaling) for voltage/current inputs
function getRawValue(channelName: string): string {
  const value = store.values[channelName]
  if (!value) return '--'
  // Backend may provide raw_value; otherwise use main value
  const raw = value.raw_value ?? value.value
  return raw.toFixed(3)
}

// Get scaled value (after engineering unit conversion)
function getScaledValue(channelName: string): string {
  const value = store.values[channelName]
  const config = store.channels[channelName]
  if (!value) return '--'

  // Apply scaling based on config
  if (config?.scale_type === 'linear' && config.scale_slope !== undefined) {
    const scaled = value.value * config.scale_slope + (config.scale_offset || 0)
    return `${scaled.toFixed(2)} ${config.unit || ''}`
  } else if (config?.scale_type === 'map' && config.pre_scaled_min !== undefined) {
    const rawRange = (config.pre_scaled_max || 10) - (config.pre_scaled_min || 0)
    const scaledRange = (config.scaled_max || 100) - (config.scaled_min || 0)
    const normalized = (value.value - (config.pre_scaled_min || 0)) / rawRange
    const scaled = normalized * scaledRange + (config.scaled_min || 0)
    return `${scaled.toFixed(2)} ${config.unit || ''}`
  } else if (config?.four_twenty_scaling && config.eng_units_min !== undefined) {
    const normalized = (value.value - 4) / 16
    const scaled = normalized * ((config.eng_units_max || 100) - (config.eng_units_min || 0)) + (config.eng_units_min || 0)
    return `${scaled.toFixed(2)} ${config.unit || ''}`
  }

  // No scaling - show raw with unit
  return `${value.value.toFixed(2)} ${config?.unit || ''}`
}

// Get alarm status
function getAlarmStatus(channelName: string): 'normal' | 'warning' | 'alarm' {
  const value = store.values[channelName]
  if (!value) return 'normal'
  if (value.alarm) return 'alarm'
  if (value.warning) return 'warning'
  return 'normal'
}

// Format channel type for display
function formatChannelType(type: ChannelType): string {
  const typeMap: Record<ChannelType, string> = {
    thermocouple: 'TC',
    rtd: 'RTD',
    voltage: 'AI',
    current: 'mA',
    strain: 'STR',
    iepe: 'IEPE',
    counter: 'CTR',
    resistance: 'RES',
    digital_input: 'DI',
    digital_output: 'DO',
    analog_output: 'AO',
  }
  return typeMap[type] || type
}

// Channel configuration editing
const editingConfig = ref<{
  name: string
  newName: string
  config: ChannelConfig
  moduleConfig: any
} | null>(null)

function openChannelConfig(channelName: string) {
  const config = store.channels[channelName]
  if (!config) return

  selectedChannel.value = channelName
  showConfigPanel.value = true

  // Initialize module-specific config based on channel type with defaults + existing values
  let moduleConfig: any = {}
  switch (config.channel_type) {
    case 'thermocouple':
      moduleConfig = {
        ...DEFAULT_THERMOCOUPLE_CONFIG,
        // Load existing thermocouple config from backend
        tc_type: config.thermocouple_type || 'K',
        cjc_source: config.cjc_source || 'internal',
        units: config.unit || 'degC',
      }
      break
    case 'rtd':
      moduleConfig = { ...DEFAULT_RTD_CONFIG }
      break
    case 'voltage':
      moduleConfig = {
        ...DEFAULT_VOLTAGE_INPUT_CONFIG,
        // Load existing voltage config from backend
        range: config.voltage_range ? `${config.voltage_range}V` : '10V',
        scale_type: config.scale_type || 'none',
        scale_slope: config.scale_slope ?? 1.0,
        scale_offset: config.scale_offset ?? 0.0,
        pre_scaled_min: config.pre_scaled_min,
        pre_scaled_max: config.pre_scaled_max,
        scaled_min: config.scaled_min,
        scaled_max: config.scaled_max,
        scaled_units: config.unit,
      }
      break
    case 'current':
      moduleConfig = {
        ...DEFAULT_CURRENT_INPUT_CONFIG,
        // Load existing 4-20mA config from backend
        range: config.current_range_ma ? `${config.current_range_ma}mA` : '20mA',
        four_twenty_scaling: config.four_twenty_scaling ?? false,
        eng_units_min: config.eng_units_min,
        eng_units_max: config.eng_units_max,
        scaled_units: config.unit,
      }
      break
    case 'strain':
      moduleConfig = {
        bridge_config: 'full',
        nominal_resistance: 350,
        gage_factor: 2.0,
        excitation_voltage: 2.5,
        units: 'strain',
      }
      break
    case 'iepe':
      moduleConfig = {
        coupling: 'AC',
        excitation_current: 4,
        sensitivity: 100,
        units: 'g',
      }
      break
    case 'counter':
      moduleConfig = {
        mode: 'count_edges',
        edge: 'rising',
        initial_count: 0,
        count_direction: 'up',
      }
      break
    case 'resistance':
      moduleConfig = {
        wiring: '4-wire',
        excitation_current: 1000,
        range: '100',
      }
      break
    case 'digital_input':
      moduleConfig = {
        ...DEFAULT_DIGITAL_INPUT_CONFIG,
        // Load existing digital input config from backend
        invert: config.invert ?? false,
      }
      break
    case 'digital_output':
      moduleConfig = {
        ...DEFAULT_DIGITAL_OUTPUT_CONFIG,
        // Load existing digital output config from backend
        invert: config.invert ?? false,
        initial_state: config.default_state ?? false,
      }
      break
  }

  // Add common settings to moduleConfig
  moduleConfig.log = config.log ?? true
  moduleConfig.log_interval_ms = config.log_interval_ms ?? 1000
  moduleConfig.safety_action = config.safety_action || ''
  moduleConfig.safety_interlock = config.safety_interlock || ''

  editingConfig.value = {
    name: channelName,
    newName: channelName,
    config: { ...config },
    moduleConfig
  }
}

function closeConfigPanel() {
  showConfigPanel.value = false
  selectedChannel.value = null
  editingConfig.value = null
}

function saveChannelConfig() {
  if (!editingConfig.value) return

  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  const mc = editingConfig.value.moduleConfig
  const channelType = editingConfig.value.config.channel_type

  // Build the config payload combining general and module-specific settings
  const config: any = {
    // General settings
    description: editingConfig.value.config.description,
    units: mc.scaled_units || editingConfig.value.config.unit,
    low_limit: editingConfig.value.config.low_limit,
    high_limit: editingConfig.value.config.high_limit,
    low_warning: editingConfig.value.config.low_warning,
    high_warning: editingConfig.value.config.high_warning,

    // Logging settings
    log: mc.log,
    log_interval_ms: mc.log_interval_ms,

    // Safety settings
    safety_action: mc.safety_action || null,
    safety_interlock: mc.safety_interlock || null,
  }

  // Add thermocouple-specific settings
  if (channelType === 'thermocouple') {
    config.tc_type = mc.tc_type
    config.cjc_source = mc.cjc_source
  }

  // Add voltage input settings
  if (channelType === 'voltage') {
    // Parse voltage range from string like "10V" to number
    const rangeMatch = mc.range?.match(/^([\d.]+)/)
    if (rangeMatch) {
      config.voltage_range = parseFloat(rangeMatch[1])
    }
    config.scale_type = mc.scale_type
    config.scale_slope = mc.scale_slope
    config.scale_offset = mc.scale_offset
    config.pre_scaled_min = mc.pre_scaled_min
    config.pre_scaled_max = mc.pre_scaled_max
    config.scaled_min = mc.scaled_min
    config.scaled_max = mc.scaled_max
  }

  // Add current input settings
  if (channelType === 'current') {
    // Parse current range from string like "20mA" to number
    const rangeMatch = mc.range?.match(/^([\d.]+)/)
    if (rangeMatch) {
      config.current_range_ma = parseFloat(rangeMatch[1])
    }
    config.four_twenty_scaling = mc.four_twenty_scaling
    config.eng_units_min = mc.eng_units_min
    config.eng_units_max = mc.eng_units_max
  }

  // Add digital I/O settings
  if (channelType === 'digital_input' || channelType === 'digital_output') {
    config.invert = mc.invert
  }
  if (channelType === 'digital_output') {
    config.default_state = mc.initial_state
  }

  // Include new_name if renaming the channel
  const isRenaming = editingConfig.value.newName !== editingConfig.value.name
  if (isRenaming) {
    config.new_name = editingConfig.value.newName
    // Propagate rename to all localStorage references
    propagateChannelRename(editingConfig.value.name, editingConfig.value.newName)
  }

  // Send to backend via MQTT (use original name as the key)
  mqtt.updateChannelConfig(editingConfig.value.name, config)
  showFeedback('success', isRenaming
    ? `Renamed channel to ${editingConfig.value.newName}`
    : `Configuration saved for ${editingConfig.value.name}`)

  markDirty()
  closeConfigPanel()
}

// Propagate channel rename to all localStorage references
function propagateChannelRename(oldName: string, newName: string) {
  const systemId = store.systemId || 'default'

  // Update dashboard layout (widget channel references)
  const layoutKey = `nisystem-layout-${systemId}`
  const layoutData = localStorage.getItem(layoutKey)
  if (layoutData) {
    try {
      const layout = JSON.parse(layoutData)
      let updated = false
      for (const widget of layout.widgets || []) {
        if (widget.channel === oldName) {
          widget.channel = newName
          updated = true
        }
        if (widget.channels && Array.isArray(widget.channels)) {
          const idx = widget.channels.indexOf(oldName)
          if (idx !== -1) {
            widget.channels[idx] = newName
            updated = true
          }
        }
      }
      if (updated) {
        localStorage.setItem(layoutKey, JSON.stringify(layout))
        console.log(`Updated layout references: ${oldName} -> ${newName}`)
      }
    } catch (e) {
      console.error('Failed to update layout for channel rename:', e)
    }
  }

  // Update recording config
  const recConfigKey = 'nisystem-recording-config'
  const recConfig = localStorage.getItem(recConfigKey)
  if (recConfig) {
    try {
      const config = JSON.parse(recConfig)
      if (config.triggerChannel === oldName) {
        config.triggerChannel = newName
        localStorage.setItem(recConfigKey, JSON.stringify(config))
        console.log(`Updated recording trigger channel: ${oldName} -> ${newName}`)
      }
    } catch (e) {
      console.error('Failed to update recording config for channel rename:', e)
    }
  }

  // Update selected recording channels
  const recChannelsKey = 'nisystem-recording-channels'
  const recChannels = localStorage.getItem(recChannelsKey)
  if (recChannels) {
    try {
      const channels: string[] = JSON.parse(recChannels)
      const idx = channels.indexOf(oldName)
      if (idx !== -1) {
        channels[idx] = newName
        localStorage.setItem(recChannelsKey, JSON.stringify(channels))
        console.log(`Updated recording channels: ${oldName} -> ${newName}`)
      }
    } catch (e) {
      console.error('Failed to update recording channels for channel rename:', e)
    }
  }

  // Update scripts (channel references in formulas)
  updateStorageArrayReferences('nisystem-scripts', oldName, newName)
  updateStorageArrayReferences('nisystem-sequences', oldName, newName)
  updateStorageArrayReferences('nisystem-alarms', oldName, newName)
  updateStorageArrayReferences('nisystem-transformations', oldName, newName)
  updateStorageArrayReferences('nisystem-triggers', oldName, newName)

  // Update the dashboard store's widgets
  store.renameChannelInWidgets(oldName, newName)
}

// Helper to update channel references in stored arrays
function updateStorageArrayReferences(key: string, oldName: string, newName: string) {
  const data = localStorage.getItem(key)
  if (!data) return

  try {
    let items = JSON.parse(data)
    let updated = false

    // Replace channel references in string fields
    const replaceInString = (str: string): string => {
      if (typeof str !== 'string') return str
      // Replace channel name patterns like "channels.oldName" or "values['oldName']"
      return str
        .replace(new RegExp(`channels\\.${oldName}\\b`, 'g'), `channels.${newName}`)
        .replace(new RegExp(`values\\['${oldName}'\\]`, 'g'), `values['${newName}']`)
        .replace(new RegExp(`values\\["${oldName}"\\]`, 'g'), `values["${newName}"]`)
        .replace(new RegExp(`getChannel\\(['"]${oldName}['"]\\)`, 'g'), `getChannel('${newName}')`)
    }

    const processItem = (item: any): boolean => {
      let changed = false
      for (const prop of Object.keys(item)) {
        if (typeof item[prop] === 'string') {
          const newVal = replaceInString(item[prop])
          if (newVal !== item[prop]) {
            item[prop] = newVal
            changed = true
          }
        }
        if (item[prop] === oldName) {
          item[prop] = newName
          changed = true
        }
      }
      return changed
    }

    if (Array.isArray(items)) {
      for (const item of items) {
        if (processItem(item)) updated = true
      }
    }

    if (updated) {
      localStorage.setItem(key, JSON.stringify(items))
      console.log(`Updated ${key} for channel rename: ${oldName} -> ${newName}`)
    }
  } catch (e) {
    console.error(`Failed to update ${key} for channel rename:`, e)
  }
}

// Save all config to INI file
function saveToFile(filename?: string) {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  const targetFile = filename || currentConfigName.value
  mqtt.saveSystemConfig(targetFile)
  showFeedback('info', `Saving configuration to ${targetFile}...`)
  configDirty.value = false
  if (filename) {
    currentConfigName.value = filename
  }
}

// Reload config from disk (re-reads the INI file)
function reloadConfig() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  isReloading.value = true
  mqtt.sendCommand('config/reload', {})
  showFeedback('info', 'Reloading configuration from disk...')

  // Reset after a delay
  setTimeout(() => {
    isReloading.value = false
    showFeedback('success', 'Configuration reload requested')
  }, 1500)
}

// Open Save As dialog
function openSaveAsDialog() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  // Pre-fill with current name (without .ini extension for editing)
  const baseName = currentConfigName.value.replace('.ini', '')
  saveAsFilename.value = baseName
  showSaveAsDialog.value = true
}

// Save with new filename
function saveAsFile() {
  if (!saveAsFilename.value.trim()) {
    showFeedback('error', 'Please enter a filename')
    return
  }
  let filename = saveAsFilename.value.trim()
  // Ensure .ini extension
  if (!filename.endsWith('.ini')) {
    filename += '.ini'
  }
  saveToFile(filename)
  showSaveAsDialog.value = false
  saveAsFilename.value = ''
}

// Load config from file
const showLoadDialog = ref(false)
const availableConfigs = ref<string[]>([])
const selectedConfigFile = ref('')

function openLoadDialog() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  // Request list of available configs
  mqtt.sendCommand('config/list')
  showLoadDialog.value = true
}

function loadFromFile() {
  if (!selectedConfigFile.value) {
    showFeedback('error', 'No configuration selected')
    return
  }
  const doLoad = () => {
    mqtt.loadConfig(selectedConfigFile.value)
    showFeedback('info', `Loading configuration: ${selectedConfigFile.value}...`)
    currentConfigName.value = selectedConfigFile.value
    configDirty.value = false
    showLoadDialog.value = false
    selectedConfigFile.value = ''
  }
  checkUnsavedChanges(doLoad)
}

// Listen for config update responses
mqtt.onConfigUpdate((response) => {
  if (response.success) {
    showFeedback('success', response.message || 'Configuration updated')
  } else {
    showFeedback('error', response.error || 'Configuration update failed')
  }

  // Handle config list response
  if (response.configs) {
    availableConfigs.value = response.configs
  }
})

// Get column headers based on active tab
const tableColumns = computed(() => {
  const baseColumns = [
    { key: 'enable', label: 'EN', width: '40px' },
    { key: 'type', label: 'TYPE', width: '50px' },
    { key: 'tag', label: 'TAG', width: '100px' },
    { key: 'channel', label: 'CHANNEL', width: '200px' },
    { key: 'description', label: 'DESCRIPTION', width: '350px' },
  ]

  switch (activeTypeTab.value) {
    case 'thermocouple':
      return [
        ...baseColumns,
        { key: 'tc_type', label: 'TC TYPE', width: '70px' },
        { key: 'cjc', label: 'CJC', width: '60px' },
        { key: 'units', label: 'UNITS', width: '60px' },
        { key: 'value', label: 'TEMP', width: '100px' },
      ]
    case 'rtd':
      return [
        ...baseColumns,
        { key: 'rtd_type', label: 'RTD TYPE', width: '100px' },
        { key: 'wiring', label: 'WIRING', width: '70px' },
        { key: 'units', label: 'UNITS', width: '60px' },
        { key: 'value', label: 'TEMP', width: '100px' },
      ]
    case 'voltage':
      return [
        ...baseColumns,
        { key: 'range', label: 'RANGE', width: '70px' },
        { key: 'terminal', label: 'TERM', width: '70px' },
        { key: 'scale', label: 'SCALE', width: '70px' },
        { key: 'raw_value', label: 'RAW (V)', width: '80px' },
        { key: 'scaled_value', label: 'SCALED', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'current':
      return [
        ...baseColumns,
        { key: 'range', label: 'RANGE', width: '70px' },
        { key: 'terminal', label: 'TERM', width: '70px' },
        { key: 'scale', label: 'SCALE', width: '70px' },
        { key: 'raw_value', label: 'RAW (mA)', width: '80px' },
        { key: 'scaled_value', label: 'SCALED', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'strain':
      return [
        ...baseColumns,
        { key: 'bridge', label: 'BRIDGE', width: '80px' },
        { key: 'gage', label: 'GAGE FACTOR', width: '90px' },
        { key: 'excitation', label: 'EXCIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'iepe':
      return [
        ...baseColumns,
        { key: 'coupling', label: 'COUPLING', width: '70px' },
        { key: 'sensitivity', label: 'SENS (mV/g)', width: '90px' },
        { key: 'units', label: 'UNITS', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'counter':
      return [
        ...baseColumns,
        { key: 'mode', label: 'MODE', width: '100px' },
        { key: 'edge', label: 'EDGE', width: '70px' },
        { key: 'min_freq', label: 'MIN FREQ', width: '80px' },
        { key: 'max_freq', label: 'MAX FREQ', width: '80px' },
        { key: 'value', label: 'COUNT', width: '100px' },
        { key: 'reset', label: 'RESET', width: '60px' },
      ]
    case 'resistance':
      return [
        ...baseColumns,
        { key: 'wiring', label: 'WIRING', width: '70px' },
        { key: 'range', label: 'RANGE', width: '80px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'digital_input':
    case 'digital_output':
      return [
        ...baseColumns,
        { key: 'logic', label: 'LOGIC', width: '60px' },
        { key: 'invert', label: 'INV', width: '50px' },
        { key: 'state', label: 'STATE', width: '80px' },
      ]
    case 'voltage_output':
      return [
        ...baseColumns,
        { key: 'range', label: 'RANGE', width: '70px' },
        { key: 'scale', label: 'SCALE', width: '70px' },
        { key: 'raw_value', label: 'RAW (V)', width: '80px' },
        { key: 'scaled_value', label: 'SCALED', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'current_output':
      return [
        ...baseColumns,
        { key: 'range', label: 'RANGE', width: '70px' },
        { key: 'scale', label: 'SCALE', width: '70px' },
        { key: 'raw_value', label: 'RAW (mA)', width: '80px' },
        { key: 'scaled_value', label: 'SCALED', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'analog_output':
      return [
        ...baseColumns,
        { key: 'range', label: 'RANGE', width: '70px' },
        { key: 'scale', label: 'SCALE', width: '70px' },
        { key: 'raw_value', label: 'RAW', width: '80px' },
        { key: 'scaled_value', label: 'SCALED', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    default:
      return [
        ...baseColumns,
        { key: 'unit', label: 'UNITS', width: '60px' },
        { key: 'min', label: 'MIN', width: '60px' },
        { key: 'max', label: 'MAX', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
  }
})

// Initialize enable states on mount and when channels change
onMounted(() => {
  initializeEnableStates()
})

watch(() => Object.keys(store.channels), () => {
  initializeEnableStates()
})
</script>

<template>
  <div class="config-tab">
    <!-- Channel Type Tabs -->
    <div class="type-tabs">
      <button
        v-for="tab in channelTypeTabs"
        :key="tab.id"
        class="type-tab"
        :class="{ active: activeTypeTab === tab.id }"
        @click="activeTypeTab = tab.id"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        {{ tab.label }}
      </button>
    </div>

    <!-- Search and Actions Bar -->
    <div class="actions-bar">
      <div class="left-actions">
        <button class="action-btn add-btn" @click="openAddChannelModal">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add Channel
        </button>
        <div class="search-box">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search channels..."
            class="search-input"
          />
        </div>
        <button class="action-btn scan-btn" @click="scanDevices" :disabled="isScanning">
          <svg v-if="!isScanning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
          </svg>
          <span v-else class="spinner"></span>
          {{ isScanning ? 'Scanning...' : 'Scan Devices' }}
        </button>
        <button class="action-btn settings-btn" @click="openSystemSettings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
          Settings
        </button>
        <button
          class="action-btn edit-btn"
          :class="{ active: editMode }"
          @click="editMode = !editMode"
          :disabled="store.isAcquiring"
          :title="store.isAcquiring ? 'Stop acquisition to edit' : (editMode ? 'Exit edit mode' : 'Enter edit mode')"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          {{ editMode ? 'EDITING' : 'EDIT' }}
        </button>
        <button class="action-btn load-btn" @click="openLoadDialog">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Load
        </button>
        <button class="action-btn reload-btn" @click="reloadConfig" :disabled="isReloading" title="Reload configuration from disk">
          <svg v-if="!isReloading" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6"/>
            <path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          <span v-else class="spinner"></span>
          {{ isReloading ? 'Reloading...' : 'Reload' }}
        </button>
        <button class="action-btn save-btn" :class="{ dirty: configDirty }" @click="saveToFile()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
          </svg>
          Save
          <span v-if="configDirty" class="dirty-indicator">*</span>
        </button>
        <button class="action-btn" @click="openSaveAsDialog">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <line x1="12" y1="11" x2="12" y2="17"/>
            <line x1="9" y1="14" x2="15" y2="14"/>
          </svg>
          Save As
        </button>
        <div class="toolbar-divider"></div>
        <button class="action-btn export-btn" @click="exportProject" :disabled="isExporting">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          {{ isExporting ? 'Exporting...' : 'Export Project' }}
        </button>
        <button class="action-btn import-btn" @click="triggerImport">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Import Project
        </button>
        <input
          ref="importFileInput"
          type="file"
          accept=".json"
          style="display: none"
          @change="handleImportFile"
        />
      </div>
      <div class="right-info">
        <div class="channel-count">
          {{ filteredChannels.length }} channels
        </div>
        <div class="connection-status" :class="{ connected: mqtt.connected.value }">
          {{ mqtt.connected.value ? 'MQTT Connected' : 'MQTT Disconnected' }}
        </div>
      </div>
    </div>

    <!-- Feedback Message -->
    <Transition name="fade">
      <div v-if="feedbackMessage" class="feedback-message" :class="feedbackMessage.type">
        {{ feedbackMessage.text }}
      </div>
    </Transition>

    <div class="main-content">
      <!-- Channel Table -->
      <div class="table-container" :class="{ 'with-panel': showConfigPanel }">
        <table class="channel-table">
          <thead>
            <tr>
              <th
                v-for="col in tableColumns"
                :key="col.key"
                :style="{ width: col.width }"
              >
                {{ col.label }}
              </th>
              <th class="col-actions">CONFIG</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[name, config] in filteredChannels"
              :key="name"
              :class="['channel-row', getAlarmStatus(name), { selected: selectedChannel === name, disabled: channelEnabled[name] === false }]"
              @click="openChannelConfig(name)"
            >
              <td class="col-enable">
                <input
                  type="checkbox"
                  :checked="channelEnabled[name] !== false"
                  @click.stop
                  @change="toggleChannelEnabled(name)"
                />
              </td>
              <td class="col-type">
                <span class="type-badge" :class="config.channel_type">
                  {{ formatChannelType(config.channel_type) }}
                </span>
              </td>
              <!-- TAG - short name like TC101 -->
              <td class="col-tag editable-cell" @click.stop>
                <input
                  type="text"
                  :value="config.display_name || ''"
                  @blur="updateChannelField(name, 'display_name', ($event.target as HTMLInputElement).value)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                  class="inline-input"
                  :placeholder="name"
                  :disabled="!canEdit"
                />
              </td>
              <!-- CHANNEL - cDAQ physical location -->
              <td class="col-channel editable-cell" @click.stop>
                <input
                  type="text"
                  :value="config.physical_channel || ''"
                  @blur="updateChannelField(name, 'physical_channel', ($event.target as HTMLInputElement).value)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                  class="inline-input channel-input"
                  placeholder="cDAQ1Mod1/ai0"
                  :disabled="!canEdit"
                />
              </td>
              <!-- DESCRIPTION - long text -->
              <td class="col-description editable-cell" @click.stop>
                <input
                  type="text"
                  :value="config.description || ''"
                  @blur="updateChannelField(name, 'description', ($event.target as HTMLInputElement).value)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                  class="inline-input description-input"
                  placeholder="Description..."
                  :disabled="!canEdit"
                />
              </td>

              <!-- Type-specific columns with inline editing -->
              <template v-if="activeTypeTab === 'thermocouple'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.thermocouple_type || 'K'"
                    @change="updateChannelField(name, 'tc_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="tc in THERMOCOUPLE_TYPES" :key="tc.value" :value="tc.value">{{ tc.value }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.cjc_source || 'internal'"
                    @change="updateChannelField(name, 'cjc_source', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="internal">INT</option>
                    <option value="constant">CONST</option>
                    <option value="channel">EXT</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.unit || 'degC'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="degC">°C</option>
                    <option value="degF">°F</option>
                    <option value="K">K</option>
                  </select>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'rtd'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.rtd_type || 'Pt100'"
                    @change="updateChannelField(name, 'rtd_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="rtd in RTD_TYPES" :key="rtd.value" :value="rtd.value">{{ rtd.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.wiring || '4-wire'"
                    @change="updateChannelField(name, 'wiring', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="2-wire">2-wire</option>
                    <option value="3-wire">3-wire</option>
                    <option value="4-wire">4-wire</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.unit || 'degC'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="degC">°C</option>
                    <option value="degF">°F</option>
                    <option value="K">K</option>
                  </select>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'voltage'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.voltage_range ? `${config.voltage_range}V` : '10V'"
                    @change="updateChannelField(name, 'voltage_range', parseFloat(($event.target as HTMLSelectElement).value))"
                    :disabled="!canEdit"
                  >
                    <option v-for="r in VOLTAGE_RANGES" :key="r.value" :value="r.value">{{ r.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.terminal_config || 'differential'"
                    @change="updateChannelField(name, 'terminal_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">{{ t.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.scale_type || 'none'"
                    @change="updateChannelField(name, 'scale_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="none">None</option>
                    <option value="linear">Linear</option>
                    <option value="map">Map</option>
                  </select>
                </td>
                <td class="col-value raw">
                  {{ getRawValue(name) }}
                </td>
                <td class="col-value scaled">
                  {{ getScaledValue(name) }}
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || ''"
                    @blur="updateChannelField(name, 'unit', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                    placeholder="unit"
                  />
                </td>
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'current'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.current_range_ma ? `${config.current_range_ma}mA` : '20mA'"
                    @change="updateChannelField(name, 'current_range_ma', parseFloat(($event.target as HTMLSelectElement).value))"
                    :disabled="!canEdit"
                  >
                    <option v-for="r in CURRENT_RANGES" :key="r.value" :value="r.value">{{ r.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.terminal_config || 'differential'"
                    @change="updateChannelField(name, 'terminal_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">{{ t.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.scale_type || 'none'"
                    @change="updateChannelField(name, 'scale_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="none">None</option>
                    <option value="linear">Linear</option>
                    <option value="map">Map</option>
                    <option value="four_twenty">4-20mA</option>
                  </select>
                </td>
                <td class="col-value raw">
                  {{ getRawValue(name) }}
                </td>
                <td class="col-value scaled">
                  {{ getScaledValue(name) }}
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || ''"
                    @blur="updateChannelField(name, 'unit', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                    placeholder="unit"
                  />
                </td>
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'strain'">
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || 'mA'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                  />
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'strain'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.bridge_config || 'full'"
                    @change="updateChannelField(name, 'bridge_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="b in BRIDGE_CONFIGS" :key="b.value" :value="b.value">{{ b.label }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.gage_factor ?? 2.0"
                    @change="updateChannelField(name, 'gage_factor', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input"
                    step="0.01"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.excitation_voltage ?? 2.5"
                    @change="updateChannelField(name, 'excitation_voltage', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input"
                    step="0.1"
                    :disabled="!canEdit"
                  />V
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'iepe'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.coupling || 'AC'"
                    @change="updateChannelField(name, 'coupling', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="AC">AC</option>
                    <option value="DC">DC</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.sensitivity ?? 100"
                    @change="updateChannelField(name, 'sensitivity', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input"
                    step="1"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || 'g'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                  />
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'counter'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.counter_mode || 'count_edges'"
                    @change="updateChannelField(name, 'counter_mode', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="count_edges">Count</option>
                    <option value="frequency">Frequency</option>
                    <option value="period">Period</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.edge || 'rising'"
                    @change="updateChannelField(name, 'edge', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="rising">Rising</option>
                    <option value="falling">Falling</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.counter_min_freq"
                    @change="updateChannelField(name, 'counter_min_freq', parseFloat(($event.target as HTMLInputElement).value) || undefined)"
                    class="inline-input"
                    placeholder="0.1"
                    step="0.1"
                    min="0"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.counter_max_freq"
                    @change="updateChannelField(name, 'counter_max_freq', parseFloat(($event.target as HTMLInputElement).value) || undefined)"
                    class="inline-input"
                    placeholder="1000"
                    step="1"
                    min="0"
                    :disabled="!canEdit"
                  />
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'resistance'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.wiring || '4-wire'"
                    @change="updateChannelField(name, 'wiring', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="2-wire">2-wire</option>
                    <option value="3-wire">3-wire</option>
                    <option value="4-wire">4-wire</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.resistance_range || '1000'"
                    @change="updateChannelField(name, 'resistance_range', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="100">100Ω</option>
                    <option value="1000">1kΩ</option>
                    <option value="10000">10kΩ</option>
                    <option value="100000">100kΩ</option>
                  </select>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'digital_input' || activeTypeTab === 'digital_output'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.logic_level || '24V'"
                    @change="updateChannelField(name, 'logic_level', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="5V">5V TTL</option>
                    <option value="24V">24V</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="checkbox"
                    :checked="config.invert === true"
                    @change="updateChannelField(name, 'invert', ($event.target as HTMLInputElement).checked)"
                    :disabled="!canEdit"
                  />
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'voltage_output'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.ao_range || '10V'"
                    @change="updateChannelField(name, 'ao_range', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="5V">0-5V</option>
                    <option value="10V">0-10V</option>
                    <option value="pm10V">±10V</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.scale_type || 'none'"
                    @change="updateChannelField(name, 'scale_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="none">None</option>
                    <option value="linear">Linear</option>
                    <option value="map">Map</option>
                  </select>
                </td>
                <td class="col-value raw">
                  {{ getRawValue(name) }}
                </td>
                <td class="col-value scaled">
                  {{ getScaledValue(name) }}
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || ''"
                    @blur="updateChannelField(name, 'unit', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                    placeholder="unit"
                  />
                </td>
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'current_output'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.ao_range || '20mA'"
                    @change="updateChannelField(name, 'ao_range', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="20mA">0-20mA</option>
                    <option value="4-20mA">4-20mA</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.scale_type || 'none'"
                    @change="updateChannelField(name, 'scale_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="none">None</option>
                    <option value="linear">Linear</option>
                    <option value="map">Map</option>
                    <option value="four_twenty">4-20mA</option>
                  </select>
                </td>
                <td class="col-value raw">
                  {{ getRawValue(name) }}
                </td>
                <td class="col-value scaled">
                  {{ getScaledValue(name) }}
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || ''"
                    @blur="updateChannelField(name, 'unit', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                    placeholder="unit"
                  />
                </td>
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'analog_output'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.ao_range || '10V'"
                    @change="updateChannelField(name, 'ao_range', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="5V">0-5V</option>
                    <option value="10V">0-10V</option>
                    <option value="pm10V">±10V</option>
                    <option value="20mA">0-20mA</option>
                    <option value="4-20mA">4-20mA</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.scale_type || 'none'"
                    @change="updateChannelField(name, 'scale_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="none">None</option>
                    <option value="linear">Linear</option>
                    <option value="map">Map</option>
                    <option value="four_twenty">4-20mA</option>
                  </select>
                </td>
                <td class="col-value raw">
                  {{ getRawValue(name) }}
                </td>
                <td class="col-value scaled">
                  {{ getScaledValue(name) }}
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || ''"
                    @blur="updateChannelField(name, 'unit', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                    placeholder="unit"
                  />
                </td>
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || '-'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                  />
                </td>
                <td>{{ config.low_limit ?? '-' }}</td>
                <td>{{ config.high_limit ?? '-' }}</td>
              </template>

              <!-- Value column - only for tabs that don't have built-in value display -->
              <td
                v-if="!['voltage', 'current', 'voltage_output', 'current_output', 'analog_output'].includes(activeTypeTab)"
                class="col-value"
                :class="getAlarmStatus(name)"
              >
                <template v-if="config.channel_type === 'digital_input' || config.channel_type === 'digital_output'">
                  <span class="digital-state" :class="{ on: store.values[name]?.value }">
                    {{ store.values[name]?.value ? 'ON' : 'OFF' }}
                  </span>
                </template>
                <template v-else>
                  <span class="value">{{ getCurrentValue(name) }}</span>
                  <span class="unit">{{ config.unit }}</span>
                </template>
              </td>

              <!-- Reset button for counter channels -->
              <td v-if="activeTypeTab === 'counter'" class="col-reset">
                <button
                  class="reset-btn"
                  @click.stop="resetCounter(name)"
                  title="Reset counter to zero"
                  :disabled="!store.isConnected"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                    <path d="M3 3v5h5"/>
                  </svg>
                  0
                </button>
              </td>

              <td class="col-actions">
                <button class="config-btn" @click.stop="openChannelConfig(name)" title="Configure">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
                  </svg>
                </button>
                <button class="delete-btn" @click="deleteChannel(name, $event)" title="Delete">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>
              </td>
            </tr>
            <tr v-if="filteredChannels.length === 0" class="empty-row">
              <td :colspan="tableColumns.length + 1">
                <div class="empty-state">
                  <p v-if="searchQuery">No channels matching "{{ searchQuery }}"</p>
                  <p v-else>No channels configured</p>
                </div>
              </td>
            </tr>
            <!-- Add Channel Row -->
            <tr class="add-channel-row" @click="openAddChannelModal">
              <td :colspan="tableColumns.length + 1">
                <div class="add-channel-cell">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                  <span>Add Channel...</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Configuration Panel (Sidebar) -->
      <div class="config-panel" :class="{ visible: showConfigPanel }">
        <template v-if="editingConfig">
          <div class="panel-header">
            <h3>{{ editingConfig.config.display_name || editingConfig.name }}</h3>
            <button class="close-btn" @click="closeConfigPanel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="panel-content">
            <!-- Common Settings -->
            <div class="config-section">
              <h4>General</h4>
              <div class="form-row">
                <label>Channel Name</label>
                <input type="text" v-model="editingConfig.newName" />
                <span class="form-hint">Changing this will rename the channel</span>
              </div>
              <div class="form-row">
                <label>Physical Channel</label>
                <input
                  type="text"
                  v-model="editingConfig.moduleConfig.physical_channel"
                  placeholder="e.g., cDAQ1Mod1/ai0"
                />
                <span class="form-hint">NI-DAQmx hardware address</span>
              </div>
              <div class="form-row">
                <label>Display Label</label>
                <input type="text" v-model="editingConfig.config.display_name" />
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Units</label>
                  <input type="text" v-model="editingConfig.config.unit" />
                </div>
                <div class="form-row half">
                  <label>Group</label>
                  <input type="text" v-model="editingConfig.config.group" placeholder="Default" />
                </div>
              </div>
              <div class="form-row">
                <label>Description</label>
                <input type="text" v-model="editingConfig.config.description" />
              </div>
            </div>

            <!-- Display Options -->
            <div class="config-section">
              <h4>Display Options</h4>
              <div class="form-row checkbox-row">
                <label>
                  <input type="checkbox" v-model="editingConfig.config.chartable" />
                  Show in Charts
                </label>
              </div>
              <div class="form-row">
                <label>Chart Color</label>
                <div class="color-picker-row">
                  <input
                    type="color"
                    v-model="editingConfig.config.color"
                    class="color-input"
                  />
                  <input
                    type="text"
                    v-model="editingConfig.config.color"
                    placeholder="#60a5fa"
                    class="color-text"
                  />
                </div>
              </div>
              <div class="form-row">
                <label>Default Widget</label>
                <select v-model="editingConfig.config.widget">
                  <option value="">Auto (based on type)</option>
                  <option value="numeric">Numeric Display</option>
                  <option value="gauge">Gauge</option>
                  <option value="chart">Chart</option>
                  <option value="led">LED Indicator</option>
                  <option value="toggle">Toggle Switch</option>
                  <option value="setpoint">Setpoint Control</option>
                </select>
              </div>
            </div>

            <!-- Logging Settings -->
            <div class="config-section">
              <h4>Logging Settings</h4>
              <div class="form-row checkbox-row">
                <label>
                  <input type="checkbox" v-model="editingConfig.moduleConfig.log" />
                  Enable Data Logging
                </label>
              </div>
              <div class="form-row" v-if="editingConfig.moduleConfig.log">
                <label>Log Interval (ms)</label>
                <input type="number" v-model.number="editingConfig.moduleConfig.log_interval_ms" min="100" step="100" />
                <span class="form-hint">Minimum interval between logged samples</span>
              </div>
            </div>

            <!-- Safety Settings -->
            <div class="config-section">
              <h4>Safety Settings</h4>
              <div class="form-row">
                <label>Safety Action</label>
                <input
                  type="text"
                  v-model="editingConfig.moduleConfig.safety_action"
                  placeholder="e.g., emergency_shutdown"
                />
                <span class="form-hint">Action to trigger when limits exceeded</span>
              </div>
              <div class="form-row">
                <label>Safety Interlock</label>
                <input
                  type="text"
                  v-model="editingConfig.moduleConfig.safety_interlock"
                  placeholder="e.g., door_closed == true"
                />
                <span class="form-hint">Condition required for output control</span>
              </div>
            </div>

            <!-- Thermocouple-specific settings -->
            <template v-if="editingConfig.config.channel_type === 'thermocouple'">
              <div class="config-section">
                <h4>Thermocouple Settings</h4>
                <div class="form-row">
                  <label>TC Type</label>
                  <select v-model="editingConfig.moduleConfig.tc_type">
                    <option v-for="tc in THERMOCOUPLE_TYPES" :key="tc.value" :value="tc.value">
                      {{ tc.label }} ({{ tc.range }})
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Temperature Units</label>
                  <select v-model="editingConfig.moduleConfig.units">
                    <option value="C">Celsius (°C)</option>
                    <option value="F">Fahrenheit (°F)</option>
                    <option value="K">Kelvin (K)</option>
                    <option value="R">Rankine (°R)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>CJC Source</label>
                  <select v-model="editingConfig.moduleConfig.cjc_source">
                    <option value="internal">Internal (Built-in sensor)</option>
                    <option value="constant">Constant Value</option>
                    <option value="channel">External Channel</option>
                  </select>
                </div>
                <div class="form-row" v-if="editingConfig.moduleConfig.cjc_source === 'constant'">
                  <label>CJC Value</label>
                  <input type="number" v-model="editingConfig.moduleConfig.cjc_value" step="0.1" />
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.open_detect" />
                    Open Thermocouple Detection
                  </label>
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.auto_zero" />
                    Auto-Zero (Improved Accuracy)
                  </label>
                </div>
              </div>
            </template>

            <!-- Voltage Input settings -->
            <template v-if="editingConfig.config.channel_type === 'voltage'">
              <div class="config-section">
                <h4>Voltage Input Settings</h4>
                <div class="form-row">
                  <label>Input Range</label>
                  <select v-model="editingConfig.moduleConfig.range">
                    <option v-for="r in VOLTAGE_RANGES" :key="r.value" :value="r.value">
                      {{ r.label }}
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Terminal Configuration</label>
                  <select v-model="editingConfig.moduleConfig.terminal_config">
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">
                      {{ t.label }}
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Scaling Type</label>
                  <select v-model="editingConfig.moduleConfig.scale_type">
                    <option value="none">None (Raw Voltage)</option>
                    <option value="linear">Linear (y = mx + b)</option>
                    <option value="map">Map Range</option>
                  </select>
                </div>
                <template v-if="editingConfig.moduleConfig.scale_type === 'linear'">
                  <div class="form-row">
                    <label>Slope (m)</label>
                    <input type="number" v-model="editingConfig.moduleConfig.scale_slope" step="0.001" />
                  </div>
                  <div class="form-row">
                    <label>Offset (b)</label>
                    <input type="number" v-model="editingConfig.moduleConfig.scale_offset" step="0.001" />
                  </div>
                </template>
                <template v-if="editingConfig.moduleConfig.scale_type === 'map'">
                  <div class="form-row-group">
                    <div class="form-row half">
                      <label>Voltage Min</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.pre_scaled_min" />
                    </div>
                    <div class="form-row half">
                      <label>Voltage Max</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.pre_scaled_max" />
                    </div>
                  </div>
                  <div class="form-row-group">
                    <div class="form-row half">
                      <label>Scaled Min</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.scaled_min" />
                    </div>
                    <div class="form-row half">
                      <label>Scaled Max</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.scaled_max" />
                    </div>
                  </div>
                  <div class="form-row">
                    <label>Scaled Units</label>
                    <input type="text" v-model="editingConfig.moduleConfig.scaled_units" placeholder="e.g., PSI" />
                  </div>
                  <!-- Map Scaling Validation Preview -->
                  <div class="scaling-preview" v-if="editingConfig.moduleConfig.pre_scaled_min != null && editingConfig.moduleConfig.pre_scaled_max != null && editingConfig.moduleConfig.scaled_min != null && editingConfig.moduleConfig.scaled_max != null">
                    <h5>Scaling Preview</h5>
                    <div class="preview-row">
                      <span class="preview-label">{{ editingConfig.moduleConfig.pre_scaled_min }}V →</span>
                      <span class="preview-value">{{ editingConfig.moduleConfig.scaled_min }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">{{ ((editingConfig.moduleConfig.pre_scaled_min + editingConfig.moduleConfig.pre_scaled_max) / 2).toFixed(2) }}V →</span>
                      <span class="preview-value">{{ ((editingConfig.moduleConfig.scaled_min + editingConfig.moduleConfig.scaled_max) / 2).toFixed(2) }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">{{ editingConfig.moduleConfig.pre_scaled_max }}V →</span>
                      <span class="preview-value">{{ editingConfig.moduleConfig.scaled_max }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                  </div>
                </template>
                <!-- Linear Scaling Preview -->
                <template v-if="editingConfig.moduleConfig.scale_type === 'linear'">
                  <div class="scaling-preview">
                    <h5>Scaling Preview</h5>
                    <div class="preview-formula">
                      Formula: value = (raw × {{ editingConfig.moduleConfig.scale_slope }}) + {{ editingConfig.moduleConfig.scale_offset }}
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">1V →</span>
                      <span class="preview-value">{{ (1 * editingConfig.moduleConfig.scale_slope + editingConfig.moduleConfig.scale_offset).toFixed(3) }}</span>
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">5V →</span>
                      <span class="preview-value">{{ (5 * editingConfig.moduleConfig.scale_slope + editingConfig.moduleConfig.scale_offset).toFixed(3) }}</span>
                    </div>
                  </div>
                </template>
              </div>
            </template>

            <!-- Current Input settings -->
            <template v-if="editingConfig.config.channel_type === 'current'">
              <div class="config-section">
                <h4>Current Input Settings</h4>
                <div class="form-row">
                  <label>Input Range</label>
                  <select v-model="editingConfig.moduleConfig.range">
                    <option v-for="r in CURRENT_RANGES" :key="r.value" :value="r.value">
                      {{ r.label }}
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Shunt Location</label>
                  <select v-model="editingConfig.moduleConfig.shunt_location">
                    <option value="internal">Internal</option>
                    <option value="external">External</option>
                  </select>
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.four_twenty_scaling" />
                    Enable 4-20mA Scaling
                  </label>
                </div>
                <template v-if="editingConfig.moduleConfig.four_twenty_scaling">
                  <div class="scaling-info">
                    4mA = Min Value, 20mA = Max Value
                  </div>
                  <div class="form-row-group">
                    <div class="form-row half">
                      <label>Min Value (at 4mA)</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.eng_units_min" />
                    </div>
                    <div class="form-row half">
                      <label>Max Value (at 20mA)</label>
                      <input type="number" v-model.number="editingConfig.moduleConfig.eng_units_max" />
                    </div>
                  </div>
                  <div class="form-row">
                    <label>Engineering Units</label>
                    <input type="text" v-model="editingConfig.moduleConfig.scaled_units" placeholder="e.g., PSI, GPM" />
                  </div>
                  <!-- Scaling Validation Preview -->
                  <div class="scaling-preview" v-if="editingConfig.moduleConfig.eng_units_min != null && editingConfig.moduleConfig.eng_units_max != null">
                    <h5>Scaling Preview</h5>
                    <div class="preview-row">
                      <span class="preview-label">4mA →</span>
                      <span class="preview-value">{{ editingConfig.moduleConfig.eng_units_min }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">12mA →</span>
                      <span class="preview-value">{{ ((editingConfig.moduleConfig.eng_units_min + editingConfig.moduleConfig.eng_units_max) / 2).toFixed(2) }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                    <div class="preview-row">
                      <span class="preview-label">20mA →</span>
                      <span class="preview-value">{{ editingConfig.moduleConfig.eng_units_max }} {{ editingConfig.moduleConfig.scaled_units }}</span>
                    </div>
                    <div class="preview-formula">
                      Formula: value = {{ editingConfig.moduleConfig.eng_units_min }} + ((mA - 4) / 16) × {{ (editingConfig.moduleConfig.eng_units_max - editingConfig.moduleConfig.eng_units_min).toFixed(2) }}
                    </div>
                  </div>
                </template>
              </div>
            </template>

            <!-- RTD settings -->
            <template v-if="editingConfig.config.channel_type === 'rtd'">
              <div class="config-section">
                <h4>RTD Settings</h4>
                <div class="form-row">
                  <label>RTD Type</label>
                  <select v-model="editingConfig.moduleConfig.rtd_type">
                    <option v-for="rtd in RTD_TYPES" :key="rtd.value" :value="rtd.value">
                      {{ rtd.label }} (R₀={{ rtd.r0 }}Ω)
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Wiring Configuration</label>
                  <select v-model="editingConfig.moduleConfig.wiring">
                    <option value="2-wire">2-Wire</option>
                    <option value="3-wire">3-Wire</option>
                    <option value="4-wire">4-Wire (Best accuracy)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Temperature Units</label>
                  <select v-model="editingConfig.moduleConfig.units">
                    <option value="C">Celsius (°C)</option>
                    <option value="F">Fahrenheit (°F)</option>
                    <option value="K">Kelvin (K)</option>
                    <option value="R">Rankine (°R)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Resistance at 0°C (R₀)</label>
                  <input type="number" v-model="editingConfig.moduleConfig.r0" step="1" />
                </div>
                <div class="form-row">
                  <label>Excitation Current (µA)</label>
                  <select v-model="editingConfig.moduleConfig.excitation_current">
                    <option :value="500">500 µA</option>
                    <option :value="1000">1000 µA</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- Strain/Bridge settings -->
            <template v-if="editingConfig.config.channel_type === 'strain'">
              <div class="config-section">
                <h4>Strain/Bridge Settings</h4>
                <div class="form-row">
                  <label>Bridge Configuration</label>
                  <select v-model="editingConfig.moduleConfig.bridge_config">
                    <option v-for="bc in BRIDGE_CONFIGS" :key="bc.value" :value="bc.value">
                      {{ bc.label }}
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Nominal Resistance (Ω)</label>
                  <select v-model="editingConfig.moduleConfig.nominal_resistance">
                    <option :value="120">120 Ω</option>
                    <option :value="350">350 Ω</option>
                    <option :value="1000">1000 Ω</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Gage Factor</label>
                  <input type="number" v-model="editingConfig.moduleConfig.gage_factor" step="0.01" />
                </div>
                <div class="form-row">
                  <label>Excitation Voltage (V)</label>
                  <select v-model="editingConfig.moduleConfig.excitation_voltage">
                    <option :value="2.5">2.5 V</option>
                    <option :value="5">5 V</option>
                    <option :value="10">10 V</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Poisson Ratio (for quarter bridge)</label>
                  <input type="number" v-model="editingConfig.moduleConfig.poisson_ratio" step="0.01" />
                </div>
                <div class="form-row">
                  <label>Output Units</label>
                  <select v-model="editingConfig.moduleConfig.units">
                    <option value="strain">Strain (µε)</option>
                    <option value="mV_per_V">mV/V</option>
                    <option value="custom">Custom</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- IEPE/Accelerometer settings -->
            <template v-if="editingConfig.config.channel_type === 'iepe'">
              <div class="config-section">
                <h4>IEPE/Accelerometer Settings</h4>
                <div class="form-row">
                  <label>Input Coupling</label>
                  <select v-model="editingConfig.moduleConfig.coupling">
                    <option value="AC">AC Coupling (blocks DC offset)</option>
                    <option value="DC">DC Coupling</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Excitation Current (mA)</label>
                  <select v-model="editingConfig.moduleConfig.excitation_current">
                    <option :value="2">2 mA</option>
                    <option :value="4">4 mA (typical)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Sensitivity (mV/g)</label>
                  <input type="number" v-model="editingConfig.moduleConfig.sensitivity" step="0.1" />
                </div>
                <div class="form-row">
                  <label>Output Units</label>
                  <select v-model="editingConfig.moduleConfig.units">
                    <option value="g">Acceleration (g)</option>
                    <option value="m_s2">Acceleration (m/s²)</option>
                    <option value="mV">Raw Voltage (mV)</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- Counter settings -->
            <template v-if="editingConfig.config.channel_type === 'counter'">
              <div class="config-section">
                <h4>Counter/Timer Settings</h4>
                <div class="form-row">
                  <label>Measurement Mode</label>
                  <select v-model="editingConfig.moduleConfig.mode">
                    <option value="count_edges">Count Edges</option>
                    <option value="pulse_width">Pulse Width</option>
                    <option value="frequency">Frequency</option>
                    <option value="period">Period</option>
                    <option value="position">Position (Encoder)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Edge Detection</label>
                  <select v-model="editingConfig.moduleConfig.edge">
                    <option value="rising">Rising Edge</option>
                    <option value="falling">Falling Edge</option>
                    <option value="both">Both Edges</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Count Direction</label>
                  <select v-model="editingConfig.moduleConfig.count_direction">
                    <option value="up">Count Up</option>
                    <option value="down">Count Down</option>
                    <option value="external">External (A/B signal)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Initial Count</label>
                  <input type="number" v-model="editingConfig.moduleConfig.initial_count" />
                </div>
                <template v-if="editingConfig.moduleConfig.mode === 'position'">
                  <div class="form-row">
                    <label>Decoding Type</label>
                    <select v-model="editingConfig.moduleConfig.decoding_type">
                      <option value="X1">X1</option>
                      <option value="X2">X2</option>
                      <option value="X4">X4</option>
                      <option value="two_pulse">Two Pulse</option>
                    </select>
                  </div>
                  <div class="form-row">
                    <label>Pulses Per Revolution</label>
                    <input type="number" v-model="editingConfig.moduleConfig.pulses_per_revolution" />
                  </div>
                  <div class="form-row checkbox-row">
                    <label>
                      <input type="checkbox" v-model="editingConfig.moduleConfig.z_index_enable" />
                      Enable Z Index
                    </label>
                  </div>
                </template>
              </div>
            </template>

            <!-- Resistance settings -->
            <template v-if="editingConfig.config.channel_type === 'resistance'">
              <div class="config-section">
                <h4>Resistance Settings</h4>
                <div class="form-row">
                  <label>Wiring Configuration</label>
                  <select v-model="editingConfig.moduleConfig.wiring">
                    <option value="2-wire">2-Wire</option>
                    <option value="4-wire">4-Wire (Best accuracy)</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Measurement Range</label>
                  <select v-model="editingConfig.moduleConfig.range">
                    <option value="100">100 Ω</option>
                    <option value="1k">1 kΩ</option>
                    <option value="10k">10 kΩ</option>
                    <option value="100k">100 kΩ</option>
                    <option value="1M">1 MΩ</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Excitation Current (µA)</label>
                  <select v-model="editingConfig.moduleConfig.excitation_current">
                    <option :value="500">500 µA</option>
                    <option :value="1000">1000 µA</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- Digital I/O settings -->
            <template v-if="editingConfig.config.channel_type === 'digital_input'">
              <div class="config-section">
                <h4>Digital Input Settings</h4>
                <div class="form-row">
                  <label>Logic Level</label>
                  <select v-model="editingConfig.moduleConfig.logic_level">
                    <option value="TTL">TTL (5V)</option>
                    <option value="LVTTL">LVTTL (3.3V)</option>
                    <option value="24V">24V Industrial</option>
                    <option value="60V">60V</option>
                  </select>
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.invert" />
                    Invert Logic (Active Low)
                  </label>
                </div>
                <div class="form-row">
                  <label>Debounce Time (µs)</label>
                  <input type="number" v-model="editingConfig.moduleConfig.debounce_time" min="0" />
                </div>
              </div>
            </template>

            <template v-if="editingConfig.config.channel_type === 'digital_output'">
              <div class="config-section">
                <h4>Digital Output Settings</h4>
                <div class="form-row">
                  <label>Drive Type</label>
                  <select v-model="editingConfig.moduleConfig.drive_type">
                    <option value="sourcing">Sourcing (PNP)</option>
                    <option value="sinking">Sinking (NPN)</option>
                    <option value="relay">Relay</option>
                    <option value="SSR">Solid State Relay</option>
                  </select>
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.invert" />
                    Invert Logic
                  </label>
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.moduleConfig.initial_state" />
                    Initial State: ON
                  </label>
                </div>
              </div>
            </template>

            <!-- Alarm Settings -->
            <div class="config-section">
              <h4>Alarms & Limits</h4>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Low Alarm</label>
                  <input type="number" v-model="editingConfig.config.low_limit" />
                </div>
                <div class="form-row half">
                  <label>High Alarm</label>
                  <input type="number" v-model="editingConfig.config.high_limit" />
                </div>
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Low Warning</label>
                  <input type="number" v-model="editingConfig.config.low_warning" />
                </div>
                <div class="form-row half">
                  <label>High Warning</label>
                  <input type="number" v-model="editingConfig.config.high_warning" />
                </div>
              </div>
            </div>
          </div>

          <div class="panel-footer">
            <button class="btn btn-secondary" @click="closeConfigPanel">Cancel</button>
            <button class="btn btn-primary" @click="saveChannelConfig">Apply</button>
          </div>
        </template>
      </div>
    </div>

    <!-- Info Panel -->
    <div class="info-panel">
      <div class="info-item">
        <span class="info-label">Total Channels:</span>
        <span class="info-value">{{ Object.keys(store.channels).length }}</span>
      </div>
      <div class="info-item">
        <span class="info-label">Scan Rate:</span>
        <span class="info-value">{{ store.status?.scan_rate_hz || '--' }} Hz</span>
      </div>
      <div class="info-item">
        <span class="info-label">Publish Rate:</span>
        <span class="info-value">{{ store.status?.publish_rate_hz || '--' }} Hz</span>
      </div>
      <div class="info-item" v-if="store.status?.simulation_mode">
        <span class="info-label sim">SIMULATION MODE</span>
      </div>
    </div>

    <!-- Discovery Panel Modal -->
    <Transition name="modal">
      <div v-if="showDiscoveryPanel" class="discovery-overlay" @click.self="showDiscoveryPanel = false">
        <div class="discovery-panel">
          <div class="discovery-header">
            <h3>Device Discovery</h3>
            <button class="close-btn" @click="showDiscoveryPanel = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="discovery-content">
            <template v-if="isScanning">
              <div class="scanning-state">
                <div class="spinner large"></div>
                <p>Scanning for NI devices...</p>
              </div>
            </template>

            <template v-else-if="discoveryChannels.length > 0">
              <div class="discovery-toolbar">
                <span class="discovery-count">{{ discoveryChannels.length }} channels found</span>
                <div class="discovery-actions">
                  <button class="btn-link" @click="selectAllDiscoveryChannels">Select All</button>
                  <button class="btn-link" @click="deselectAllDiscoveryChannels">Deselect All</button>
                </div>
              </div>

              <div class="discovery-list">
                <div
                  v-for="channel in discoveryChannels"
                  :key="channel.physical_channel"
                  class="discovery-item"
                  :class="{ selected: selectedDiscoveryChannels.includes(channel.physical_channel) }"
                  @click="toggleDiscoveryChannel(channel.physical_channel)"
                >
                  <input
                    type="checkbox"
                    :checked="selectedDiscoveryChannels.includes(channel.physical_channel)"
                    @click.stop
                    @change="toggleDiscoveryChannel(channel.physical_channel)"
                  />
                  <div class="channel-info">
                    <div class="channel-physical">{{ channel.physical_channel }}</div>
                    <div class="channel-details">
                      <span class="type-badge" :class="channel.measurement_type">
                        {{ channel.measurement_type }}
                      </span>
                      <span class="module-name">{{ channel.module_name }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <template v-else>
              <div class="empty-discovery">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M12 6v6l4 2"/>
                </svg>
                <p>No devices found</p>
                <p class="hint">Make sure NI-DAQmx drivers are installed and devices are connected.</p>
              </div>
            </template>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showDiscoveryPanel = false">Cancel</button>
            <button class="btn btn-secondary" @click="scanDevices" :disabled="isScanning">
              Rescan
            </button>
            <button
              class="btn btn-primary"
              @click="addSelectedChannels"
              :disabled="selectedDiscoveryChannels.length === 0"
            >
              Add {{ selectedDiscoveryChannels.length }} Channel(s)
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Load Config Dialog -->
    <Transition name="modal">
      <div v-if="showLoadDialog" class="discovery-overlay" @click.self="showLoadDialog = false">
        <div class="load-dialog">
          <div class="discovery-header">
            <h3>Load Configuration</h3>
            <button class="close-btn" @click="showLoadDialog = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="load-dialog-content">
            <template v-if="availableConfigs.length > 0">
              <p class="load-hint">Select a configuration file to load:</p>
              <div class="config-list">
                <div
                  v-for="config in availableConfigs"
                  :key="config"
                  class="config-item"
                  :class="{ selected: selectedConfigFile === config }"
                  @click="selectedConfigFile = config"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                  </svg>
                  <span>{{ config }}</span>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="empty-discovery">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                </svg>
                <p>No configuration files found</p>
                <p class="hint">Save a configuration first to create a file.</p>
              </div>
            </template>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showLoadDialog = false">Cancel</button>
            <button
              class="btn btn-primary"
              @click="loadFromFile"
              :disabled="!selectedConfigFile"
            >
              Load Configuration
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Add Channel Modal -->
    <Transition name="modal">
      <div v-if="showAddChannelModal" class="discovery-overlay" @click.self="showAddChannelModal = false">
        <div class="add-channel-dialog">
          <div class="discovery-header">
            <h3>Add New Channel</h3>
            <button class="close-btn" @click="showAddChannelModal = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="add-channel-content">
            <div class="form-row">
              <label>Channel Type <span class="required">*</span></label>
              <select v-model="newChannelForm.channel_type">
                <option value="thermocouple">Thermocouple</option>
                <option value="rtd">RTD</option>
                <option value="voltage">Voltage Input</option>
                <option value="current">Current Input</option>
                <option value="strain">Strain/Bridge</option>
                <option value="iepe">IEPE/Accelerometer</option>
                <option value="counter">Counter</option>
                <option value="resistance">Resistance</option>
                <option value="digital_input">Digital Input</option>
                <option value="digital_output">Digital Output</option>
                <option value="analog_output">Analog Output</option>
              </select>
            </div>

            <div class="form-row">
              <label>Channel Name <span class="required">*</span></label>
              <input
                type="text"
                v-model="newChannelForm.name"
                placeholder="e.g., TC_Zone1"
              />
              <span class="form-hint">Unique identifier (no spaces)</span>
            </div>

            <div class="form-row">
              <label>Physical Channel</label>
              <input
                type="text"
                v-model="newChannelForm.physical_channel"
                placeholder="e.g., cDAQ1Mod1/ai0"
              />
              <span class="form-hint">NI-DAQmx hardware address</span>
            </div>

            <div class="form-row">
              <label>Display Label</label>
              <input
                type="text"
                v-model="newChannelForm.display_name"
                placeholder="e.g., Zone 1 Temperature"
              />
            </div>

            <div class="form-row-group">
              <div class="form-row half">
                <label>Units</label>
                <input
                  type="text"
                  v-model="newChannelForm.unit"
                  :placeholder="getDefaultUnit(newChannelForm.channel_type)"
                />
              </div>
              <div class="form-row half">
                <label>Group</label>
                <input
                  type="text"
                  v-model="newChannelForm.group"
                  placeholder="Default"
                />
              </div>
            </div>

            <div class="form-row">
              <label>Description</label>
              <input
                type="text"
                v-model="newChannelForm.description"
                placeholder="Optional description"
              />
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showAddChannelModal = false">Cancel</button>
            <button
              class="btn btn-primary"
              @click="addNewChannel"
              :disabled="!newChannelForm.name"
            >
              Add Channel
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- System Settings Modal -->
    <Transition name="modal">
      <div v-if="showSystemSettings" class="discovery-overlay" @click.self="showSystemSettings = false">
        <div class="settings-dialog">
          <div class="discovery-header">
            <h3>System Settings</h3>
            <button class="close-btn" @click="showSystemSettings = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="settings-content">
            <div class="settings-section">
              <h4>Acquisition Rates</h4>
              <div class="form-row">
                <label>Scan Rate (Hz)</label>
                <input
                  type="number"
                  v-model.number="systemSettingsForm.scan_rate_hz"
                  min="1"
                  max="10000"
                />
                <span class="form-hint">Hardware sampling rate</span>
              </div>
              <div class="form-row">
                <label>Publish Rate (Hz)</label>
                <input
                  type="number"
                  v-model.number="systemSettingsForm.publish_rate_hz"
                  min="1"
                  max="1000"
                />
                <span class="form-hint">MQTT publish rate</span>
              </div>
            </div>

            <div class="settings-info">
              <div class="info-row">
                <span class="info-label">Current Status:</span>
                <span class="info-value" :class="{ online: store.status?.status === 'online' }">
                  {{ store.status?.status || 'Unknown' }}
                </span>
              </div>
              <div class="info-row">
                <span class="info-label">Simulation Mode:</span>
                <span class="info-value">{{ store.status?.simulation_mode ? 'Yes' : 'No' }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">Total Channels:</span>
                <span class="info-value">{{ Object.keys(store.channels).length }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">Config Path:</span>
                <span class="info-value mono">{{ store.status?.config_path || '--' }}</span>
              </div>
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showSystemSettings = false">Cancel</button>
            <button class="btn btn-primary" @click="saveSystemSettings">
              Apply Settings
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Save As Dialog -->
    <Transition name="modal">
      <div v-if="showSaveAsDialog" class="discovery-overlay" @click.self="showSaveAsDialog = false">
        <div class="save-as-dialog">
          <div class="discovery-header">
            <h3>Save Configuration As</h3>
            <button class="close-btn" @click="showSaveAsDialog = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="save-as-content">
            <div class="form-row">
              <label>Filename</label>
              <div class="filename-input">
                <input
                  type="text"
                  v-model="saveAsFilename"
                  placeholder="config_name"
                  @keyup.enter="saveAsFile"
                />
                <span class="extension">.ini</span>
              </div>
              <span class="form-hint">Enter a name for the configuration file</span>
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showSaveAsDialog = false">Cancel</button>
            <button class="btn btn-primary" @click="saveAsFile" :disabled="!saveAsFilename.trim()">
              Save
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Unsaved Changes Dialog -->
    <Transition name="modal">
      <div v-if="showUnsavedChangesDialog" class="discovery-overlay">
        <div class="unsaved-dialog">
          <div class="discovery-header">
            <h3>Unsaved Changes</h3>
          </div>

          <div class="unsaved-content">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <p>You have unsaved configuration changes.</p>
            <p class="hint">Would you like to save before continuing?</p>
          </div>

          <div class="unsaved-footer">
            <button class="btn btn-secondary" @click="handleUnsavedChanges('discard')">
              Discard
            </button>
            <button class="btn btn-secondary" @click="handleUnsavedChanges('cancel')">
              Cancel
            </button>
            <button class="btn btn-primary" @click="handleUnsavedChanges('save')">
              Save
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.config-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0a0a14;
}

/* Channel Type Tabs */
.type-tabs {
  display: flex;
  gap: 2px;
  padding: 8px 16px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
  overflow-x: auto;
}

.type-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: #666;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

.type-tab:hover {
  background: #1a1a2e;
  color: #888;
}

.type-tab.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #60a5fa;
}

.tab-icon {
  font-size: 1rem;
}

/* Actions Bar */
.actions-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #666;
}

.search-input {
  background: transparent;
  border: none;
  color: #fff;
  font-size: 0.85rem;
  width: 200px;
  outline: none;
}

.search-input::placeholder {
  color: #555;
}

.channel-count {
  font-size: 0.75rem;
  color: #666;
}

/* Main Content */
.main-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Table Container */
.table-container {
  flex: 1;
  overflow: auto;
  padding: 0 16px;
  transition: flex 0.3s;
}

.table-container.with-panel {
  flex: 0.6;
}

.channel-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.75rem;
}

.channel-table th {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #0f0f1a;
  padding: 8px 6px;
  text-align: left;
  font-weight: 600;
  color: #888;
  border-bottom: 2px solid #2a2a4a;
  white-space: nowrap;
}

.channel-table th.col-actions {
  position: sticky;
  top: 0;
  right: 0;
  z-index: 20;
  background: #0f0f1a;
  text-align: center;
  width: 70px;
  min-width: 70px;
}

.channel-table td {
  padding: 6px;
  border-bottom: 1px solid #1a1a2e;
  color: #ccc;
}

.channel-table td.col-actions {
  position: sticky;
  right: 0;
  background: #0a0a14;
  text-align: center;
  width: 70px;
  min-width: 70px;
}

.channel-row:hover td.col-actions {
  background: #1a1a2e;
}

.channel-row.selected td.col-actions {
  background: #1e3a5f;
}

.channel-row {
  cursor: pointer;
  transition: background 0.2s;
}

.channel-row:hover {
  background: #1a1a2e;
}

.channel-row.selected {
  background: #1e3a5f;
}

.channel-row.warning {
  background: rgba(251, 191, 36, 0.1);
}

.channel-row.alarm {
  background: rgba(239, 68, 68, 0.15);
}

/* Column styling */
.col-enable { text-align: center; }
.col-tag { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; font-weight: 600; }
.col-actions { width: 50px; text-align: center; }

/* Type Badge */
.type-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
}

.type-badge.thermocouple { background: #7f1d1d; color: #fca5a5; }
.type-badge.rtd { background: #9f1239; color: #fda4af; }
.type-badge.voltage { background: #1e3a8a; color: #93c5fd; }
.type-badge.current { background: #4c1d95; color: #c4b5fd; }
.type-badge.strain { background: #713f12; color: #fde047; }
.type-badge.iepe { background: #365314; color: #bef264; }
.type-badge.counter { background: #1e1b4b; color: #a5b4fc; }
.type-badge.resistance { background: #3f3f46; color: #d4d4d8; }
.type-badge.digital_input { background: #14532d; color: #86efac; }
.type-badge.digital_output { background: #78350f; color: #fcd34d; }
.type-badge.analog_output { background: #0e7490; color: #67e8f9; }

/* Value Cell */
.col-value .value {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}

.col-value .unit {
  margin-left: 4px;
  font-size: 0.65rem;
  color: #666;
}

.col-value.warning .value { color: #fbbf24; }
.col-value.alarm .value { color: #ef4444; }

/* Raw/Scaled value columns */
.col-value.raw {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #9ca3af;
}

.col-value.scaled {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  color: #60a5fa;
}

.col-value.scaled.warning { color: #fbbf24; }
.col-value.scaled.alarm { color: #ef4444; }

.digital-state {
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 600;
  font-size: 0.7rem;
  background: #374151;
  color: #9ca3af;
}

.digital-state.on {
  background: #14532d;
  color: #22c55e;
}

/* Config Button */
.config-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.config-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

/* Inline Editable Cells */
.editable-cell {
  cursor: default;
}

.editable-cell select {
  background: #0f0f1a;
  border: 1px solid transparent;
  border-radius: 3px;
  color: #ccc;
  font-size: 0.75rem;
  padding: 2px 4px;
  cursor: pointer;
  max-width: 100%;
}

.editable-cell select:hover:not(:disabled) {
  border-color: #3b82f6;
}

.editable-cell select:focus {
  outline: none;
  border-color: #3b82f6;
  background: #1a1a2e;
}

.editable-cell select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inline-input {
  background: #0f0f1a;
  border: 1px solid transparent;
  border-radius: 3px;
  color: #ccc;
  font-size: 0.75rem;
  padding: 2px 4px;
  width: 100%;
}

.inline-input:hover:not(:disabled) {
  border-color: #3b82f6;
}

.inline-input:focus {
  outline: none;
  border-color: #3b82f6;
  background: #1a1a2e;
}

.inline-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inline-input[type="number"] {
  max-width: 70px;
}

/* Channel input - monospace for cDAQ paths */
.col-channel .inline-input {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
}

/* Description input - full width */
.col-description .inline-input {
  min-width: 280px;
}


.editable-cell input[type="checkbox"] {
  cursor: pointer;
}

.editable-cell input[type="checkbox"]:disabled {
  cursor: not-allowed;
}

.scaling-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
  background: #1e3a8a;
  color: #93c5fd;
}

.scaling-badge.off {
  background: #374151;
  color: #9ca3af;
}

/* Config Panel */
.config-panel {
  width: 0;
  overflow: hidden;
  background: #0f0f1a;
  border-left: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
  transition: width 0.3s;
}

.config-panel.visible {
  width: 380px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.panel-header h3 {
  margin: 0;
  font-size: 0.9rem;
  color: #fff;
}

.close-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
}

.close-btn:hover {
  color: #fff;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.config-section {
  margin-bottom: 20px;
}

.config-section h4 {
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #2a2a4a;
  font-size: 0.8rem;
  color: #60a5fa;
  text-transform: uppercase;
}

.form-row {
  margin-bottom: 12px;
}

.form-row label {
  display: block;
  font-size: 0.75rem;
  color: #888;
  margin-bottom: 4px;
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
}

.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: #3b82f6;
}

.input-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-row-group {
  display: flex;
  gap: 12px;
}

.form-row.half {
  flex: 1;
}

.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-row input[type="checkbox"] {
  width: auto;
  accent-color: #3b82f6;
}

.scaling-info {
  font-size: 0.7rem;
  color: #666;
  margin-bottom: 12px;
  padding: 8px;
  background: #1a1a2e;
  border-radius: 4px;
}

.scaling-preview {
  margin-top: 12px;
  padding: 12px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.scaling-preview h5 {
  margin: 0 0 8px 0;
  font-size: 0.75rem;
  color: #3b82f6;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.preview-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 0.8rem;
  border-bottom: 1px dashed #2a2a4a;
}

.preview-row:last-of-type {
  border-bottom: none;
}

.preview-label {
  color: #888;
  font-family: 'Fira Code', monospace;
}

.preview-value {
  color: #22c55e;
  font-weight: 600;
  font-family: 'Fira Code', monospace;
}

.preview-formula {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #2a2a4a;
  font-size: 0.7rem;
  color: #888;
  font-family: 'Fira Code', monospace;
}

.panel-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
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

/* Empty State */
.empty-row td {
  padding: 40px;
}

.empty-state {
  text-align: center;
  color: #555;
}

/* Add Channel Row */
.add-channel-row {
  cursor: pointer;
  transition: background 0.15s;
}

.add-channel-row:hover {
  background: #1a2a3a;
}

.add-channel-row td {
  border-bottom: none;
}

.add-channel-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  color: #60a5fa;
  font-size: 0.8rem;
}

.add-channel-cell svg {
  opacity: 0.7;
}

.add-channel-row:hover .add-channel-cell {
  color: #93c5fd;
}

.add-channel-row:hover .add-channel-cell svg {
  opacity: 1;
}

/* Info Panel */
.info-panel {
  display: flex;
  gap: 24px;
  padding: 8px 16px;
  background: #0f0f1a;
  border-top: 1px solid #2a2a4a;
}

.info-item {
  display: flex;
  gap: 6px;
  font-size: 0.75rem;
}

.info-label {
  color: #666;
}

.info-value {
  color: #888;
  font-weight: 500;
}

.info-label.sim {
  color: #fbbf24;
  background: #451a03;
  padding: 2px 6px;
  border-radius: 3px;
}

/* Checkbox styling */
input[type="checkbox"] {
  accent-color: #3b82f6;
}

/* Actions Bar Enhanced */
.actions-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.left-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.right-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover:not(:disabled) {
  background: #2a2a4a;
  color: #fff;
  border-color: #3b82f6;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.edit-btn {
  border-color: #3b82f6;
}

.edit-btn.active {
  background: #3b82f6;
  color: #fff;
  border-color: #3b82f6;
}

.edit-btn:hover:not(:disabled):not(.active) {
  border-color: #60a5fa;
  color: #60a5fa;
}

.scan-btn:hover:not(:disabled) {
  border-color: #22c55e;
  color: #22c55e;
}

.save-btn:hover:not(:disabled) {
  border-color: #3b82f6;
  color: #3b82f6;
}

.connection-status {
  font-size: 0.7rem;
  padding: 4px 8px;
  border-radius: 3px;
  background: #451a03;
  color: #fbbf24;
}

.connection-status.connected {
  background: #14532d;
  color: #22c55e;
}

/* Spinner */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #2a2a4a;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner.large {
  width: 32px;
  height: 32px;
  border-width: 3px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Feedback Message */
.feedback-message {
  padding: 8px 16px;
  font-size: 0.8rem;
  font-weight: 500;
  text-align: center;
}

.feedback-message.success {
  background: #14532d;
  color: #22c55e;
}

.feedback-message.error {
  background: #7f1d1d;
  color: #fca5a5;
}

.feedback-message.info {
  background: #1e3a5f;
  color: #60a5fa;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* Discovery Modal */
.discovery-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.discovery-panel {
  width: 600px;
  max-height: 80vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.discovery-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #2a2a4a;
}

.discovery-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
}

.discovery-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 200px;
}

.discovery-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.discovery-count {
  font-size: 0.8rem;
  color: #888;
}

.discovery-actions {
  display: flex;
  gap: 12px;
}

.btn-link {
  background: none;
  border: none;
  color: #60a5fa;
  font-size: 0.75rem;
  cursor: pointer;
}

.btn-link:hover {
  text-decoration: underline;
}

.discovery-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.discovery-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #1a1a2e;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.discovery-item:hover {
  background: #2a2a4a;
}

.discovery-item.selected {
  border-color: #3b82f6;
  background: #1e3a5f;
}

.discovery-item input[type="checkbox"] {
  width: 16px;
  height: 16px;
}

.channel-info {
  flex: 1;
}

.channel-physical {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  color: #fff;
  margin-bottom: 4px;
}

.channel-details {
  display: flex;
  align-items: center;
  gap: 8px;
}

.module-name {
  font-size: 0.7rem;
  color: #666;
}

.discovery-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 16px;
  border-top: 1px solid #2a2a4a;
}

.scanning-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
  color: #888;
}

.empty-discovery {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 8px;
  color: #555;
}

.empty-discovery .hint {
  font-size: 0.75rem;
  color: #444;
}

/* Modal transitions */
.modal-enter-active, .modal-leave-active {
  transition: opacity 0.3s;
}

.modal-enter-from, .modal-leave-to {
  opacity: 0;
}

.modal-enter-active .discovery-panel,
.modal-leave-active .discovery-panel {
  transition: transform 0.3s;
}

.modal-enter-from .discovery-panel,
.modal-leave-to .discovery-panel {
  transform: scale(0.95);
}

/* Load Button */
.load-btn:hover:not(:disabled) {
  border-color: #a855f7;
  color: #a855f7;
}

/* Load Dialog */
.load-dialog {
  width: 400px;
  max-height: 60vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.load-dialog-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 150px;
}

.load-hint {
  margin: 0 0 12px;
  font-size: 0.8rem;
  color: #888;
}

.config-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #1a1a2e;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  color: #ccc;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.config-item:hover {
  background: #2a2a4a;
}

.config-item.selected {
  border-color: #3b82f6;
  background: #1e3a5f;
  color: #fff;
}

.config-item svg {
  color: #666;
}

.config-item.selected svg {
  color: #60a5fa;
}

/* Add Channel Button */
.add-btn {
  background: #166534 !important;
  border-color: #22c55e !important;
  color: #22c55e !important;
}

.add-btn:hover:not(:disabled) {
  background: #14532d !important;
  color: #fff !important;
}

/* Settings Button */
.settings-btn:hover:not(:disabled) {
  border-color: #8b5cf6;
  color: #8b5cf6;
}

/* Delete Button in table */
.col-actions {
  display: flex;
  gap: 4px;
  justify-content: center;
}

.delete-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.delete-btn:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

/* Reset counter button */
.col-reset {
  text-align: center;
}

.reset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #1e3a5f;
  border: 1px solid #3b82f6;
  color: #93c5fd;
  cursor: pointer;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  transition: all 0.15s;
}

.reset-btn:hover:not(:disabled) {
  background: #3b82f6;
  color: #fff;
}

.reset-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Disabled channel row */
.channel-row.disabled {
  opacity: 0.5;
}

.channel-row.disabled td {
  color: #555;
}

/* Add Channel Dialog */
.add-channel-dialog {
  width: 500px;
  max-height: 80vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.add-channel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.required {
  color: #ef4444;
}

.form-hint {
  display: block;
  font-size: 0.7rem;
  color: #555;
  margin-top: 4px;
}

/* Settings Dialog */
.settings-dialog {
  width: 450px;
  max-height: 80vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.settings-section {
  margin-bottom: 20px;
}

.settings-section h4 {
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #2a2a4a;
  font-size: 0.8rem;
  color: #60a5fa;
  text-transform: uppercase;
}

.settings-info {
  background: #1a1a2e;
  border-radius: 4px;
  padding: 12px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 0.8rem;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-row .info-label {
  color: #666;
}

.info-row .info-value {
  color: #ccc;
}

.info-row .info-value.online {
  color: #22c55e;
}

.info-row .info-value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Color Picker */
.color-picker-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.color-input {
  width: 40px;
  height: 32px;
  padding: 2px;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  background: #1a1a2e;
  cursor: pointer;
}

.color-text {
  flex: 1;
  padding: 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
}

/* Dirty indicator */
.save-btn.dirty {
  border-color: #f59e0b;
}

.dirty-indicator {
  color: #f59e0b;
  font-weight: bold;
  margin-left: 2px;
}

/* Toolbar divider */
.toolbar-divider {
  width: 1px;
  height: 24px;
  background: #2a2a4a;
  margin: 0 8px;
}

/* Export/Import buttons */
.export-btn {
  background: linear-gradient(135deg, #1e3a5f 0%, #0f2744 100%);
  border-color: #3b82f6;
}

.export-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #2563eb 0%, #1e3a5f 100%);
}

.import-btn {
  background: linear-gradient(135deg, #1e3a5f 0%, #0f2744 100%);
  border-color: #8b5cf6;
}

.import-btn:hover {
  background: linear-gradient(135deg, #7c3aed 0%, #1e3a5f 100%);
}

/* Save As Dialog */
.save-as-dialog {
  width: 400px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.save-as-content {
  padding: 16px;
}

.filename-input {
  display: flex;
  align-items: center;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  overflow: hidden;
}

.filename-input input {
  flex: 1;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 0.9rem;
}

.filename-input input:focus {
  outline: none;
}

.filename-input .extension {
  padding: 8px 12px;
  background: #2a2a4a;
  color: #888;
  font-size: 0.9rem;
}

/* Unsaved Changes Dialog */
.unsaved-dialog {
  width: 400px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.unsaved-content {
  padding: 24px;
  text-align: center;
}

.unsaved-content svg {
  margin-bottom: 16px;
}

.unsaved-content p {
  margin: 0 0 8px;
  color: #fff;
  font-size: 0.95rem;
}

.unsaved-content .hint {
  color: #888;
  font-size: 0.85rem;
}

.unsaved-footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
  justify-content: flex-end;
}
</style>
