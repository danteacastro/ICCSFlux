<script setup lang="ts">
import { ref, computed, onMounted, watch, inject } from 'vue'
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
import { useProjectFiles } from '../composables/useProjectFiles'
import { useTheme } from '../composables/useTheme'
import { useSafety } from '../composables/useSafety'
import { useTagDependencies } from '../composables/useTagDependencies'
import { useBackendScripts } from '../composables/useBackendScripts'
import ModbusDeviceConfig from './ModbusDeviceConfig.vue'
import RestApiDeviceConfig from './RestApiDeviceConfig.vue'

const store = useDashboardStore()
const tagDeps = useTagDependencies()
const backendScripts = useBackendScripts()

// =============================================================================
// NI Module Type Mapping
// =============================================================================
// Strict mapping of NI module product types to channel types.
// This is the authoritative source for determining channel types - we don't rely
// on backend data alone. The module's product_type determines the type.
//
// For combo modules (e.g., NI 9207 with both voltage and current inputs),
// use the channel's physical name (ai vs ci) to determine type.
// =============================================================================

interface ModuleTypeInfo {
  channel_type: string       // Primary channel type for this module
  category: string           // Category for grouping/defaults
  alt_channel_type?: string  // For combo modules: alternative type based on channel name
  alt_category?: string      // For combo modules: alternative category
  alt_prefix?: string        // For combo modules: channel prefix that uses alt type (e.g., "ci" for current)
}

const NI_MODULE_TYPES: Record<string, ModuleTypeInfo> = {
  // ===== DIGITAL INPUT MODULES =====
  'NI 9421': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, 24V sinking
  'NI 9422': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, 24-60V sinking
  'NI 9423': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, TTL
  'NI 9425': { channel_type: 'digital_input', category: 'digital' },   // 32-ch DI, 24V sourcing (Spring)
  'NI 9426': { channel_type: 'digital_input', category: 'digital' },   // 32-ch DI, 24V sinking
  'NI 9435': { channel_type: 'digital_input', category: 'digital' },   // 4-ch universal DI

  // ===== DIGITAL OUTPUT MODULES =====
  'NI 9472': { channel_type: 'digital_output', category: 'digital' },  // 8-ch DO, 24V sourcing
  'NI 9474': { channel_type: 'digital_output', category: 'digital' },  // 8-ch DO, 5-30V sourcing
  'NI 9475': { channel_type: 'digital_output', category: 'digital' },  // 8-ch DO, 60V sinking
  'NI 9476': { channel_type: 'digital_output', category: 'digital' },  // 32-ch DO, 24V sourcing
  'NI 9477': { channel_type: 'digital_output', category: 'digital' },  // 32-ch DO, 60V sinking
  'NI 9478': { channel_type: 'digital_output', category: 'digital' },  // 16-ch DO, 24V sourcing

  // ===== BIDIRECTIONAL DIGITAL I/O MODULES =====
  // For these, channel direction is determined by configuration, default to input
  'NI 9401': { channel_type: 'digital_input', category: 'digital' },   // 8-ch bidirectional DIO
  'NI 9402': { channel_type: 'digital_input', category: 'digital' },   // 4-ch bidirectional DIO
  'NI 9403': { channel_type: 'digital_input', category: 'digital' },   // 32-ch bidirectional TTL

  // ===== ANALOG INPUT - VOLTAGE =====
  'NI 9201': { channel_type: 'analog_input', category: 'voltage' },    // 8-ch ±10V
  'NI 9202': { channel_type: 'analog_input', category: 'voltage' },    // 16-ch ±10V
  'NI 9205': { channel_type: 'analog_input', category: 'voltage' },    // 32-ch ±10V
  'NI 9206': { channel_type: 'analog_input', category: 'voltage' },    // 16-ch simultaneous ±10V
  'NI 9215': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch simultaneous ±10V
  'NI 9220': { channel_type: 'analog_input', category: 'voltage' },    // 16-ch ±10V
  'NI 9221': { channel_type: 'analog_input', category: 'voltage' },    // 8-ch ±60V
  'NI 9222': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch simultaneous ±10V
  'NI 9223': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch high-speed ±10V
  'NI 9229': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch ±60V isolated
  'NI 9239': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch ±10V universal

  // ===== ANALOG INPUT - CURRENT =====
  'NI 9203': { channel_type: 'analog_input', category: 'current' },    // 8-ch ±20mA
  'NI 9208': { channel_type: 'analog_input', category: 'current' },    // 16-ch ±20mA

  // ===== ANALOG INPUT - THERMOCOUPLE =====
  'NI 9210': { channel_type: 'analog_input', category: 'thermocouple' }, // 4-ch TC
  'NI 9211': { channel_type: 'analog_input', category: 'thermocouple' }, // 4-ch TC
  'NI 9212': { channel_type: 'analog_input', category: 'thermocouple' }, // 8-ch TC
  'NI 9213': { channel_type: 'analog_input', category: 'thermocouple' }, // 16-ch TC
  'NI 9214': { channel_type: 'analog_input', category: 'thermocouple' }, // 16-ch isothermal TC

  // ===== ANALOG INPUT - RTD =====
  'NI 9216': { channel_type: 'analog_input', category: 'rtd' },        // 8-ch RTD
  'NI 9217': { channel_type: 'analog_input', category: 'rtd' },        // 4-ch RTD
  'NI 9226': { channel_type: 'analog_input', category: 'rtd' },        // 8-ch RTD

  // ===== ANALOG INPUT - STRAIN/BRIDGE =====
  'NI 9235': { channel_type: 'analog_input', category: 'strain' },     // 8-ch quarter-bridge
  'NI 9236': { channel_type: 'analog_input', category: 'strain' },     // 8-ch quarter-bridge
  'NI 9237': { channel_type: 'analog_input', category: 'bridge' },     // 4-ch bridge

  // ===== ANALOG INPUT - UNIVERSAL/MULTI =====
  'NI 9219': { channel_type: 'analog_input', category: 'voltage' },    // 4-ch universal AI

  // ===== ANALOG OUTPUT - VOLTAGE =====
  'NI 9260': { channel_type: 'analog_output', category: 'voltage' },   // 4-ch ±10V
  'NI 9262': { channel_type: 'analog_output', category: 'voltage' },   // 2-ch ±100V
  'NI 9263': { channel_type: 'analog_output', category: 'voltage' },   // 4-ch ±10V
  'NI 9264': { channel_type: 'analog_output', category: 'voltage' },   // 16-ch ±10V
  'NI 9269': { channel_type: 'analog_output', category: 'voltage' },   // 4-ch isolated ±10V

  // ===== ANALOG OUTPUT - CURRENT =====
  'NI 9265': { channel_type: 'analog_output', category: 'current_output' }, // 4-ch 0-20mA
  'NI 9266': { channel_type: 'analog_output', category: 'current_output' }, // 8-ch 0-20mA

  // ===== RELAY MODULES =====
  // Relay modules are digital outputs - NI-DAQmx treats them as DO channels
  'NI 9481': { channel_type: 'digital_output', category: 'relay' },    // 4-ch SPST relay
  'NI 9482': { channel_type: 'digital_output', category: 'relay' },    // 4-ch SPDT relay
  'NI 9485': { channel_type: 'digital_output', category: 'relay' },    // 8-ch SSR

  // ===== COMBO MODULES =====
  // NI 9207: 8 voltage + 8 current inputs (ai0-ai7 = voltage, ci0-ci7 = current)
  'NI 9207': {
    channel_type: 'analog_input',
    category: 'voltage',
    alt_channel_type: 'analog_input',
    alt_category: 'current',
    alt_prefix: 'ci'
  },
}

/**
 * Get channel type info from NI module product type.
 * This is the AUTHORITATIVE source for determining channel types.
 *
 * @param productType - Module product type (e.g., "NI 9472", "NI 9472 (Spring)")
 * @param channelName - Physical channel name (e.g., "Mod4/port0/line0", "Mod1/ai0", "Mod1/ci0")
 * @returns { channel_type, category } or null if module not recognized
 */
function getModuleChannelType(productType: string, channelName?: string): { channel_type: string, category: string } | null {
  // Extract base model number (e.g., "NI 9472" from "NI 9472 (Spring)")
  const match = productType.match(/^(NI\s*\d{4})/i)
  if (!match) return null

  const baseModel = match[1]!.replace(/\s+/g, ' ')  // Normalize spacing
  const moduleInfo = NI_MODULE_TYPES[baseModel]

  if (!moduleInfo) return null

  // Check if this is a combo module with alternate type
  if (moduleInfo.alt_prefix && channelName) {
    // Extract channel prefix (e.g., "ci" from "Mod1/ci0")
    const channelMatch = channelName.match(/\/([a-z]+)\d+$/i)
    if (channelMatch && channelMatch[1]!.toLowerCase() === moduleInfo.alt_prefix.toLowerCase()) {
      return {
        channel_type: moduleInfo.alt_channel_type || moduleInfo.channel_type,
        category: moduleInfo.alt_category || moduleInfo.category
      }
    }
  }

  return {
    channel_type: moduleInfo.channel_type,
    category: moduleInfo.category
  }
}

// MQTT connection - get from parent or create new
const mqtt = useMqtt()

// Theme toggle
const { theme, toggleTheme } = useTheme()

// Safety system - for safety action dropdown
const safety = useSafety()

// Project manager for export/import
const projectManager = useProjectManager()
const projectFiles = useProjectFiles()
const isExporting = ref(false)
const isReloading = ref(false)
const isSaving = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)

// Permission-based edit control (injected from App.vue)
const hasEditPermission = inject<{ value: boolean }>('canEditConfig', ref(true))
const showLoginDialog = inject<() => void>('showLoginDialog', () => {})

// Edit mode - only allow editing when explicitly enabled, has permission, and not acquiring
const editMode = ref(false)
const canEdit = computed(() => editMode.value && hasEditPermission.value && !store.isAcquiring)

// cRIO sync indicator - true if ANY cRIO is out of sync
const hasCrioOutOfSync = computed(() => {
  const syncStatus = mqtt.crioSyncStatus.value
  for (const nodeId in syncStatus) {
    if (!syncStatus[nodeId]) return true
  }
  return false
})

// Toggle edit mode with permission check
function toggleEditMode() {
  if (!hasEditPermission.value) {
    showLoginDialog()
    return
  }
  editMode.value = !editMode.value
}

// Limit colors toggle - show alarm/warning colors based on channel limits
const showLimitColors = ref(true)

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
const manualPhysicalChannel = ref('')  // For manual entry when "Enter manually" is selected
const newChannelForm = ref({
  name: '',
  physical_channel: '',
  channel_type: 'thermocouple' as ChannelType,
  // display_name removed - use name (TAG) everywhere
  unit: '',
  group: '',
  description: '',  // For tooltips/documentation only
  source_type: 'cdaq' as 'cdaq' | 'crio' | 'opto22',
  node_id: ''  // For cRIO/Opto22: which remote node
})

// Get physical channel placeholder based on source type
function getPhysicalChannelHint(sourceType: string): string {
  switch (sourceType) {
    case 'cdaq':
      return 'e.g., cDAQ1Mod1/ai0'
    case 'crio':
      return 'e.g., Mod1/ai0'
    case 'opto22':
      return 'e.g., analogInputs/0/ch0'
    default:
      return 'Physical channel address'
  }
}

// Get available nodes for selected source type
function getAvailableNodes(sourceType: string): Array<{id: string, name: string, status: string}> {
  if (sourceType === 'crio' && discoveryResult.value?.crio_nodes) {
    return discoveryResult.value.crio_nodes.map((n: any) => ({
      id: n.node_id,
      name: `${n.node_id} (${n.product_type})`,
      status: n.status
    }))
  }
  if (sourceType === 'opto22' && discoveryResult.value?.opto22_nodes) {
    return discoveryResult.value.opto22_nodes.map((n: any) => ({
      id: n.node_id,
      name: `${n.node_id} (${n.product_type})`,
      status: n.status
    }))
  }
  return []
}

// Get available physical channels from discovery for Add Channel dropdown
function getAvailablePhysicalChannels(): Array<{value: string, label: string, type: string}> {
  const sourceType = newChannelForm.value.source_type
  const nodeId = newChannelForm.value.node_id
  const channels: Array<{value: string, label: string, type: string}> = []

  if (sourceType === 'cdaq') {
    // cDAQ: get channels from chassis/modules
    if (discoveryResult.value?.chassis) {
      for (const chassis of discoveryResult.value.chassis) {
        for (const module of chassis.modules || []) {
          for (const ch of module.channels || []) {
            channels.push({
              value: ch.name,
              label: `${ch.name} (${ch.type})`,
              type: ch.type
            })
          }
        }
      }
    }
    // Also check standalone devices
    if (discoveryResult.value?.standalone_devices) {
      for (const device of discoveryResult.value.standalone_devices) {
        for (const ch of device.channels || []) {
          channels.push({
            value: ch.name,
            label: `${ch.name} (${ch.type})`,
            type: ch.type
          })
        }
      }
    }
  } else if (sourceType === 'crio' && nodeId) {
    // cRIO: get channels from selected node
    const node = discoveryResult.value?.crio_nodes?.find((n: any) => n.node_id === nodeId)
    if (node?.modules) {
      for (const module of node.modules) {
        for (const ch of module.channels || []) {
          channels.push({
            value: ch.name,
            label: `${ch.name} (${ch.type})`,
            type: ch.type
          })
        }
      }
    }
  } else if (sourceType === 'opto22' && nodeId) {
    // Opto22: get channels from selected node
    const node = discoveryResult.value?.opto22_nodes?.find((n: any) => n.node_id === nodeId)
    if (node?.modules) {
      for (const module of node.modules) {
        for (const ch of module.channels || []) {
          channels.push({
            value: ch.name,
            label: `${ch.name} (${ch.type})`,
            type: ch.type
          })
        }
      }
    }
  }

  return channels
}

// Check if we have discovery data for the current source type
function hasDiscoveryData(): boolean {
  const sourceType = newChannelForm.value.source_type
  if (sourceType === 'cdaq') {
    return !!(discoveryResult.value?.chassis?.length || discoveryResult.value?.standalone_devices?.length)
  } else if (sourceType === 'crio') {
    return !!discoveryResult.value?.crio_nodes?.length
  } else if (sourceType === 'opto22') {
    return !!discoveryResult.value?.opto22_nodes?.length
  }
  return false
}

// System Settings State
const showSystemSettings = ref(false)
const systemSettingsForm = ref({
  scan_rate_hz: 100,
  publish_rate_hz: 10,
  project_mode: 'cdaq' as 'cdaq' | 'crio' | 'opto22'
})

// Project Manager State
const showProjectManager = ref(false)

function openProjectManager() {
  // Request fresh project list from backend
  projectFiles.listProjects()
  showProjectManager.value = true
}

async function loadSelectedProject(filename: string) {
  const success = await projectFiles.loadProject(filename)
  if (success) {
    showFeedback('success', `Loaded project: ${filename}`)
    showProjectManager.value = false
    configDirty.value = false
  } else {
    showFeedback('error', `Failed to load project: ${filename}`)
  }
}

async function startNewProject() {
  if (configDirty.value) {
    if (!confirm('You have unsaved changes. Start a new project anyway?')) {
      return
    }
  }
  await projectFiles.newProject()
  showProjectManager.value = false
  showFeedback('success', 'Started fresh - all state cleared, ready to configure')
}

// Safety Actions Management State
const showSafetyActionsModal = ref(false)
const editingSafetyAction = ref<{
  id: string
  name: string
  description: string
  type: 'trip_system' | 'stop_session' | 'stop_recording' | 'set_output_safe' | 'run_sequence' | 'custom'
  enabled: boolean
  outputChannels: string[]
  safeValue: number
  analogSafeValue: number
  sequenceId: string
  mqttTopic: string
  mqttPayload: string
} | null>(null)
const isNewSafetyAction = ref(false)

function openSafetyActionsModal() {
  showSafetyActionsModal.value = true
}

function startNewSafetyAction() {
  editingSafetyAction.value = {
    id: `action-${Date.now()}`,
    name: '',
    description: '',
    type: 'trip_system',
    enabled: true,
    outputChannels: [],
    safeValue: 0,
    analogSafeValue: 0,
    sequenceId: '',
    mqttTopic: '',
    mqttPayload: '{}'
  }
  isNewSafetyAction.value = true
}

function editSafetyAction(actionId: string) {
  const action = safety.getSafetyAction(actionId)
  if (action) {
    editingSafetyAction.value = {
      id: actionId,
      name: action.name,
      description: action.description || '',
      type: action.type,
      enabled: action.enabled,
      outputChannels: action.outputChannels || [],
      safeValue: action.safeValue ?? 0,
      analogSafeValue: action.analogSafeValue ?? 0,
      sequenceId: action.sequenceId || '',
      mqttTopic: action.mqttTopic || '',
      mqttPayload: action.mqttPayload ? JSON.stringify(action.mqttPayload) : '{}'
    }
    isNewSafetyAction.value = false
  }
}

function saveSafetyAction() {
  if (!editingSafetyAction.value) return

  const action = editingSafetyAction.value
  let payload: any = {}
  try {
    payload = JSON.parse(action.mqttPayload || '{}')
  } catch { /* ignore */ }

  if (isNewSafetyAction.value) {
    safety.addSafetyAction({
      name: action.name,
      description: action.description,
      type: action.type,
      enabled: action.enabled,
      outputChannels: action.outputChannels,
      safeValue: action.safeValue,
      analogSafeValue: action.analogSafeValue,
      sequenceId: action.sequenceId,
      mqttTopic: action.mqttTopic,
      mqttPayload: payload
    })
  } else {
    safety.updateSafetyAction(action.id, {
      name: action.name,
      description: action.description,
      type: action.type,
      enabled: action.enabled,
      outputChannels: action.outputChannels,
      safeValue: action.safeValue,
      analogSafeValue: action.analogSafeValue,
      sequenceId: action.sequenceId,
      mqttTopic: action.mqttTopic,
      mqttPayload: payload
    })
  }

  editingSafetyAction.value = null
  showFeedback('success', `Safety action ${isNewSafetyAction.value ? 'created' : 'updated'}`)
}

function deleteSafetyAction(actionId: string) {
  if (confirm('Delete this safety action?')) {
    safety.removeSafetyAction(actionId)
    showFeedback('success', 'Safety action deleted')
  }
}

function cancelEditSafetyAction() {
  editingSafetyAction.value = null
}

// Get available output channels for safety action configuration
const outputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, config]) => config.channel_type === 'digital_output' || config.channel_type === 'analog_output')
    .map(([name, config]) => ({
      name,
      displayName: name,  // TAG is the only identifier
      type: config.channel_type
    }))
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
  // Default source_type based on project_mode
  const projectMode = store.status?.project_mode || 'cdaq'

  // Determine channel_type based on active tab
  // If on a specific type tab, pre-select that type
  let defaultChannelType: ChannelType = 'thermocouple'
  if (activeTypeTab.value !== 'all') {
    // Map tab IDs to channel types (most are 1:1, but handle special cases)
    const tabToType: Record<string, ChannelType> = {
      'thermocouple': 'thermocouple',
      'rtd': 'rtd',
      'voltage': 'voltage',
      'current': 'current',
      'voltage_output': 'analog_output',  // V-OUT uses analog_output type
      'current_output': 'analog_output',  // mA-OUT uses analog_output type
      'digital_input': 'digital_input',
      'digital_output': 'digital_output',
      'counter': 'counter',
      'strain': 'strain',
      'iepe': 'iepe',
      'modbus': 'modbus_register',  // Default to register for Modbus tab
      'rest_api': 'voltage'  // REST API doesn't have a specific type, default to voltage
    }
    defaultChannelType = tabToType[activeTypeTab.value] || 'thermocouple'
  }

  // Reset form
  manualPhysicalChannel.value = ''
  newChannelForm.value = {
    name: '',
    physical_channel: '',
    channel_type: defaultChannelType,
    // display_name removed - use name (TAG) everywhere
    unit: '',
    group: '',
    description: '',
    source_type: projectMode as 'cdaq' | 'crio' | 'opto22',
    node_id: ''
  }

  // Auto-select first available node for remote modes
  if (projectMode === 'crio' || projectMode === 'opto22') {
    const nodes = getAvailableNodes(projectMode)
    if (nodes.length > 0 && nodes[0]) {
      newChannelForm.value.node_id = nodes[0].id
    }
  }

  showAddChannelModal.value = true

  // Auto-scan for hardware if no discovery data exists
  if (!hasDiscoveryData() && !isScanning.value) {
    showFeedback('info', 'Scanning for available hardware...')
    mqtt.scanDevices()
  }
}

function addNewChannel() {
  if (!newChannelForm.value.name) {
    showFeedback('error', 'Channel name is required')
    return
  }

  // Check for duplicate TAG - tags must be unique project-wide
  const tagName = newChannelForm.value.name.trim()
  if (store.channels[tagName]) {
    showFeedback('error', `Tag "${tagName}" already exists. Tags must be unique across all nodes.`)
    return
  }

  // Check for collision with other nodes (multi-node systems)
  const collision = mqtt.checkChannelCollision(tagName)
  if (collision.collides) {
    showFeedback('error', `Tag "${tagName}" is already owned by node "${collision.owner}". Tags must be unique across all nodes.`)
    return
  }

  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Handle manual entry - use manualPhysicalChannel if "__manual__" was selected
  const physicalChannel = newChannelForm.value.physical_channel === '__manual__'
    ? manualPhysicalChannel.value
    : newChannelForm.value.physical_channel

  const config: Record<string, any> = {
    name: tagName,  // TAG is the only identifier
    physical_channel: physicalChannel || tagName,
    channel_type: newChannelForm.value.channel_type,
    // display_name removed - use name (TAG) everywhere
    unit: newChannelForm.value.unit || getDefaultUnit(newChannelForm.value.channel_type),
    group: newChannelForm.value.group || 'Default',
    description: newChannelForm.value.description,
    enabled: true,
    // Source tracking
    source_type: newChannelForm.value.source_type
  }

  // Add node_id for remote sources
  if (newChannelForm.value.source_type !== 'cdaq') {
    config.node_id = newChannelForm.value.node_id || ''
  }

  mqtt.updateChannelConfig(tagName, config)
  showFeedback('success', `Adding channel: ${tagName}`)
  channelEnabled.value[tagName] = true
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
    analog_output: 'V',
    modbus_register: '',
    modbus_coil: ''
  }
  return units[channelType] || ''
}

// Delete channel with dependency checking
function deleteChannel(channelName: string, event: Event) {
  event.stopPropagation()

  // Check for dependencies before deleting
  const refs = tagDeps.getTagReferences(channelName)
  let confirmMessage = `Delete channel "${channelName}"? This cannot be undone.`

  if (refs.length > 0) {
    const refSummary = refs.map(r => `  - ${r.type}: ${r.name} (${r.location})`).join('\n')
    confirmMessage = `WARNING: "${channelName}" is referenced in ${refs.length} place(s):\n\n${refSummary}\n\nDeleting this tag will break these references!\n\nDelete anyway?`
  }

  if (!confirm(confirmMessage)) {
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
    publish_rate_hz: store.status?.publish_rate_hz || 10,
    project_mode: (store.status?.project_mode as 'cdaq' | 'crio' | 'opto22') || 'cdaq'
  }
  showSystemSettings.value = true
}

function saveSystemSettings() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  mqtt.sendNodeCommand('config/system/update', {
    scan_rate_hz: systemSettingsForm.value.scan_rate_hz,
    publish_rate_hz: systemSettingsForm.value.publish_rate_hz,
    project_mode: systemSettingsForm.value.project_mode
  })
  showFeedback('info', 'Updating system settings...')
  showSystemSettings.value = false
}

// Auto-generate widgets
function autoGenerateWidgets() {
  const channelCount = Object.keys(store.channels).filter(name => {
    const ch = store.channels[name]
    return ch && ch.visible !== false
  }).length

  if (channelCount === 0) {
    showFeedback('info', 'No channels available to generate widgets')
    return
  }

  const confirmed = window.confirm(
    `This will create ${channelCount} widgets for all visible channels.\n\n` +
    'Widgets will be placed on the Overview page below existing widgets.\n\n' +
    'Continue?'
  )

  if (!confirmed) return

  const count = store.autoGenerateWidgets({
    widgetSize: 'compact',  // Can be 'compact', 'normal', or 'large'
    columns: 4              // Grid columns
  })

  showFeedback('success', `Created ${count} widgets! Go to Overview page to see them.`)
}

// Discovery state
const isScanning = computed(() => mqtt.isScanning.value)
const discoveryChannels = computed(() => mqtt.discoveryChannels.value)
const discoveryResult = computed(() => mqtt.discoveryResult.value)
const showDiscoveryPanel = ref(false)
const selectedDiscoveryChannels = ref<string[]>([])
const devicePrefix = ref('')  // Prefix to prepend to physical channels (e.g., "RIO0" for cRIO)

// Tree view expansion state
const expandedChassis = ref<Set<string>>(new Set())
const expandedModules = ref<Set<string>>(new Set())
const expandedCrioNodes = ref<Set<string>>(new Set())
const expandedOpto22Nodes = ref<Set<string>>(new Set())

// Toggle chassis expansion
function toggleChassis(chassisName: string) {
  if (expandedChassis.value.has(chassisName)) {
    expandedChassis.value.delete(chassisName)
  } else {
    expandedChassis.value.add(chassisName)
  }
  // Force reactivity
  expandedChassis.value = new Set(expandedChassis.value)
}

// Toggle module expansion
function toggleModule(moduleName: string) {
  if (expandedModules.value.has(moduleName)) {
    expandedModules.value.delete(moduleName)
  } else {
    expandedModules.value.add(moduleName)
  }
  // Force reactivity
  expandedModules.value = new Set(expandedModules.value)
}

// Toggle cRIO node expansion
function toggleCrioNode(nodeId: string) {
  if (expandedCrioNodes.value.has(nodeId)) {
    expandedCrioNodes.value.delete(nodeId)
  } else {
    expandedCrioNodes.value.add(nodeId)
  }
  // Force reactivity
  expandedCrioNodes.value = new Set(expandedCrioNodes.value)
}

// Toggle Opto22 node expansion
function toggleOpto22Node(nodeId: string) {
  if (expandedOpto22Nodes.value.has(nodeId)) {
    expandedOpto22Nodes.value.delete(nodeId)
  } else {
    expandedOpto22Nodes.value.add(nodeId)
  }
  // Force reactivity
  expandedOpto22Nodes.value = new Set(expandedOpto22Nodes.value)
}

// Expand all chassis, modules, cRIO nodes, and Opto22 nodes
function expandAllDiscovery() {
  if (discoveryResult.value?.chassis) {
    discoveryResult.value.chassis.forEach((chassis: any) => {
      expandedChassis.value.add(chassis.name)
      chassis.modules?.forEach((mod: any) => {
        expandedModules.value.add(mod.name)
      })
    })
    expandedChassis.value = new Set(expandedChassis.value)
    expandedModules.value = new Set(expandedModules.value)
  }
  // Also expand cRIO nodes
  if (discoveryResult.value?.crio_nodes) {
    discoveryResult.value.crio_nodes.forEach((node: any) => {
      expandedCrioNodes.value.add(node.node_id)
      node.modules?.forEach((mod: any) => {
        expandedModules.value.add(mod.name)
      })
    })
    expandedCrioNodes.value = new Set(expandedCrioNodes.value)
    expandedModules.value = new Set(expandedModules.value)
  }
  // Also expand Opto22 nodes
  if (discoveryResult.value?.opto22_nodes) {
    discoveryResult.value.opto22_nodes.forEach((node: any) => {
      expandedOpto22Nodes.value.add(node.node_id)
      node.modules?.forEach((mod: any) => {
        expandedModules.value.add(mod.name)
      })
    })
    expandedOpto22Nodes.value = new Set(expandedOpto22Nodes.value)
    expandedModules.value = new Set(expandedModules.value)
  }
}

// Collapse all
function collapseAllDiscovery() {
  expandedChassis.value = new Set()
  expandedModules.value = new Set()
  expandedCrioNodes.value = new Set()
  expandedOpto22Nodes.value = new Set()
}

// Select all channels in a module
function selectModuleChannels(module: any, select: boolean) {
  module.channels?.forEach((ch: any) => {
    const idx = selectedDiscoveryChannels.value.indexOf(ch.name)
    if (select && idx === -1) {
      selectedDiscoveryChannels.value.push(ch.name)
    } else if (!select && idx >= 0) {
      selectedDiscoveryChannels.value.splice(idx, 1)
    }
  })
}

// Check if all channels in a module are selected
function isModuleFullySelected(module: any): boolean {
  if (!module.channels?.length) return false
  return module.channels.every((ch: any) => selectedDiscoveryChannels.value.includes(ch.name))
}

// Check if some channels in a module are selected
function isModulePartiallySelected(module: any): boolean {
  if (!module.channels?.length) return false
  const selected = module.channels.filter((ch: any) => selectedDiscoveryChannels.value.includes(ch.name))
  return selected.length > 0 && selected.length < module.channels.length
}

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

  // Clear all local discovery state before starting new scan
  // This ensures subsequent scans show fresh results without stale selections
  selectedDiscoveryChannels.value = []
  expandedChassis.value = new Set()
  expandedModules.value = new Set()
  expandedCrioNodes.value = new Set()

  showFeedback('info', 'Discovering hardware devices...')
  mqtt.scanDevices()
  showDiscoveryPanel.value = true
}

// Close discovery panel and cancel any pending scan
function closeDiscoveryPanel() {
  showDiscoveryPanel.value = false
  mqtt.cancelScan()
}

// Handle discovery result
mqtt.onDiscovery((result) => {
  console.log('[ConfigTab] onDiscovery callback fired:', result?.success, result?.total_channels)
  if (result.success) {
    const totalChannels = result.total_channels || 0
    const chassisCount = result.chassis?.length || 0
    const crioCount = result.crio_nodes?.length || 0
    const opto22Count = result.opto22_nodes?.length || 0
    const parts = []
    if (chassisCount > 0) parts.push(`${chassisCount} cDAQ`)
    if (crioCount > 0) parts.push(`${crioCount} cRIO`)
    if (opto22Count > 0) parts.push(`${opto22Count} Opto22`)
    const deviceText = parts.length > 0 ? parts.join(', ') : 'No devices'
    showFeedback('success', `Found ${deviceText}, ${totalChannels} channels`)
    // Auto-expand all on successful discovery
    expandAllDiscovery()
  } else {
    showFeedback('error', result.error || result.message || 'Discovery failed')
  }
})

// Handle cRIO response (push config result)
mqtt.onCrioResponse((result) => {
  if (result.success) {
    showFeedback('success', result.message || 'Config pushed to cRIO')
  } else {
    showFeedback('error', result.message || 'Failed to push config to cRIO')
  }
})

// Push current project config to a cRIO node
function pushConfigToCrio(node: any) {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  if (node.status !== 'online') {
    showFeedback('error', `cRIO ${node.node_id} is offline`)
    return
  }

  // Get current channel configs from store
  const channelConfigs = Object.values(store.channels || {})

  // Get scripts from store (if available)
  const scripts = backendScripts.scriptsList.value || []

  // Get safe state outputs (all DO channels)
  const safeStateOutputs = channelConfigs
    .filter((ch: any) => ch.channel_type === 'digital_output')
    .map((ch: any) => ch.name)

  // Push config to cRIO
  mqtt.pushCrioConfig(node.node_id, {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 100,
    publish_rate_hz: store.status?.publish_rate_hz || 10
  })

  showFeedback('info', `Pushing config to ${node.node_id}...`)
}

// Push current project config to an Opto22 node
function pushConfigToOpto22(node: any) {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  if (node.status !== 'online') {
    showFeedback('error', `Opto22 ${node.node_id} is offline`)
    return
  }

  // Get current channel configs from store
  const channelConfigs = Object.values(store.channels || {})

  // Get scripts from store (if available)
  const scripts = backendScripts.scriptsList.value || []

  // Get safe state outputs (all DO channels)
  const safeStateOutputs = channelConfigs
    .filter((ch: any) => ch.channel_type === 'digital_output')
    .map((ch: any) => ch.name)

  // Push config to Opto22 (uses same mechanism as cRIO)
  mqtt.pushCrioConfig(node.node_id, {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 100,
    publish_rate_hz: store.status?.publish_rate_hz || 10
  })

  showFeedback('info', `Pushing config to ${node.node_id}...`)
}

// Auto-push config to all connected remote nodes (cRIO and Opto22)
// Called after successful save if there are remote channels in the project
function autoPushToRemoteNodes() {
  if (!mqtt.connected.value) return

  // Find all unique node IDs from channels with source_type === 'crio' or 'opto22'
  const crioNodeIds = new Set<string>()
  const opto22NodeIds = new Set<string>()
  for (const [_name, config] of Object.entries(store.channels)) {
    const ch = config as any
    if (ch.source_type === 'crio' && ch.node_id) {
      crioNodeIds.add(ch.node_id)
    } else if (ch.source_type === 'opto22' && ch.node_id) {
      opto22NodeIds.add(ch.node_id)
    }
  }

  const totalNodes = crioNodeIds.size + opto22NodeIds.size
  if (totalNodes === 0) return  // No remote channels

  // Get current channel configs from store
  const channelConfigs = Object.values(store.channels || {})
  const scripts = backendScripts.scriptsList.value || []
  const safeStateOutputs = channelConfigs
    .filter((ch: any) => ch.channel_type === 'digital_output')
    .map((ch: any) => ch.name)

  const configPayload = {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 100,
    publish_rate_hz: store.status?.publish_rate_hz || 10
  }

  let pushedCount = 0

  // Push to each cRIO node
  for (const nodeId of crioNodeIds) {
    const crioNode = discoveryResult.value?.crio_nodes?.find((n: any) => n.node_id === nodeId)
    if (crioNode && crioNode.status !== 'online') {
      console.log(`Skipping push to ${nodeId} - node is offline`)
      continue
    }
    mqtt.pushCrioConfig(nodeId, configPayload)
    console.log(`Auto-pushed config to cRIO: ${nodeId}`)
    pushedCount++
  }

  // Push to each Opto22 node
  for (const nodeId of opto22NodeIds) {
    const opto22Node = discoveryResult.value?.opto22_nodes?.find((n: any) => n.node_id === nodeId)
    if (opto22Node && opto22Node.status !== 'online') {
      console.log(`Skipping push to ${nodeId} - node is offline`)
      continue
    }
    mqtt.pushCrioConfig(nodeId, configPayload)  // Same push mechanism
    console.log(`Auto-pushed config to Opto22: ${nodeId}`)
    pushedCount++
  }

  if (pushedCount > 0) {
    const parts = []
    if (crioNodeIds.size > 0) parts.push(`${crioNodeIds.size} cRIO`)
    if (opto22NodeIds.size > 0) parts.push(`${opto22NodeIds.size} Opto22`)
    showFeedback('info', `Config pushed to ${parts.join(' + ')} node(s)`)
  }
}

// Generate smart channel name from physical channel
function generateSmartChannelName(physicalChannel: string, channelType: string, index: number): string {
  // Extract module number and channel index from physical channel
  // e.g., "cDAQ1Mod1/ai0" -> "TC_01" for thermocouple
  const match = physicalChannel.match(/Mod(\d+)\/([a-z]+)(\d+)/i)
  if (!match) return physicalChannel.replace(/[^a-zA-Z0-9_]/g, '_')

  const moduleNum = match[1]!
  const chanType = match[2]!.toLowerCase()
  const chanNum = parseInt(match[3]!)

  // Generate prefix based on measurement type
  const prefixes: Record<string, string> = {
    thermocouple: 'TC',
    rtd: 'RTD',
    voltage: 'AI',
    current: 'mA',
    strain: 'STR',
    iepe: 'IEPE',
    counter: 'CTR',
    digital_input: 'DI',
    digital_output: 'DO',
    analog_output: 'AO',
  }

  const prefix = prefixes[channelType] || chanType.toUpperCase()
  return `${prefix}_${String(chanNum + 1).padStart(2, '0')}`
}

// Get default limits based on channel type
function getDefaultLimits(channelType: string): { low: number, high: number, lowWarn?: number, highWarn?: number } {
  const limits: Record<string, { low: number, high: number, lowWarn?: number, highWarn?: number }> = {
    thermocouple: { low: 0, high: 500, lowWarn: 32, highWarn: 450 },
    rtd: { low: -50, high: 300, lowWarn: 0, highWarn: 250 },
    voltage: { low: -10, high: 10 },
    current: { low: 0, high: 20, lowWarn: 4, highWarn: 20 },
    strain: { low: -5000, high: 5000 },
    iepe: { low: -50, high: 50 },
    counter: { low: 0, high: 1000000 },
    digital_input: { low: 0, high: 1 },
    digital_output: { low: 0, high: 1 },
    analog_output: { low: -10, high: 10 },
  }
  return limits[channelType] || { low: 0, high: 100 }
}

// Get default group name based on module/type
function getDefaultGroupName(channelType: string, moduleName: string): string {
  const groupNames: Record<string, string> = {
    thermocouple: 'Temperature',
    rtd: 'Temperature',
    voltage: 'Analog Inputs',
    current: 'Current Inputs',
    strain: 'Strain Gauges',
    iepe: 'Vibration',
    counter: 'Counters',
    digital_input: 'Digital Inputs',
    digital_output: 'Digital Outputs',
    analog_output: 'Analog Outputs',
  }
  return groupNames[channelType] || moduleName || 'Ungrouped'
}

// Get the next available tag number (finds gaps or uses max+1)
function getNextTagNumber(): number {
  const existingTags = Object.keys(store.channels)
    .filter(name => /^tag_\d+$/.test(name))
    .map(name => parseInt(name.replace('tag_', ''), 10))
    .sort((a, b) => a - b)

  // Find first gap or use max+1
  let next = 0
  for (const num of existingTags) {
    if (num > next) break
    next = num + 1
  }
  return next
}

// Add discovered channels to config with simple tag_N naming
function addSelectedChannels() {
  // Collect all selected channels from hierarchical data
  const selectedChannels: any[] = []

  if (discoveryResult.value?.chassis) {
    for (const chassis of discoveryResult.value.chassis) {
      for (const module of chassis.modules || []) {
        for (const channel of module.channels || []) {
          if (selectedDiscoveryChannels.value.includes(channel.name)) {
            selectedChannels.push({
              ...channel,
              module_name: module.product_type,
              module_device: module.name,
              chassis_name: chassis.name
            })
          }
        }
      }
    }
  }

  // Also check standalone devices
  if (discoveryResult.value?.standalone_devices) {
    for (const device of discoveryResult.value.standalone_devices) {
      for (const channel of device.channels || []) {
        if (selectedDiscoveryChannels.value.includes(channel.name)) {
          selectedChannels.push({
            ...channel,
            module_name: device.product_type,
            module_device: device.name,
            chassis_name: ''
          })
        }
      }
    }
  }

  // Include cRIO node channels
  if (discoveryResult.value?.crio_nodes) {
    for (const node of discoveryResult.value.crio_nodes) {
      for (const module of node.modules || []) {
        for (const channel of module.channels || []) {
          if (selectedDiscoveryChannels.value.includes(channel.name)) {
            selectedChannels.push({
              ...channel,
              module_name: module.product_type,
              module_device: module.name,
              chassis_name: node.node_id,
              node_id: node.node_id,  // Track source cRIO node
              is_crio: true,
              is_opto22: false
            })
          }
        }
      }
    }
  }

  // Include Opto22 node channels
  if (discoveryResult.value?.opto22_nodes) {
    for (const node of discoveryResult.value.opto22_nodes) {
      for (const module of node.modules || []) {
        for (const channel of module.channels || []) {
          if (selectedDiscoveryChannels.value.includes(channel.name)) {
            selectedChannels.push({
              ...channel,
              module_name: module.product_type,
              module_device: module.name,
              chassis_name: node.node_id,
              node_id: node.node_id,  // Track source Opto22 node
              is_crio: false,
              is_opto22: true
            })
          }
        }
      }
    }
  }

  if (selectedChannels.length === 0) {
    showFeedback('error', 'No channels selected')
    return
  }

  // Get starting tag number
  let tagNum = getNextTagNumber()
  const startTagNum = tagNum

  // Build channel configs for bulk create
  const channelsToCreate: any[] = []

  selectedChannels.forEach((ch) => {
    const tagName = `tag_${tagNum}`
    tagNum++

    // STRICT module-based type lookup (authoritative source)
    // Use NI_MODULE_TYPES mapping to determine channel type from module product type
    // This is more reliable than trusting backend-reported channel_type
    let hwType: string  // Hardware type: analog_input, analog_output, digital_input, digital_output
    let category: string  // Measurement category: thermocouple, voltage, current_output, etc.
    const moduleTypeInfo = getModuleChannelType(ch.module_name || '', ch.name)

    if (moduleTypeInfo) {
      // Module recognized - use strict type mapping
      hwType = moduleTypeInfo.channel_type  // 'analog_input', 'analog_output', 'digital_input', 'digital_output'
      category = moduleTypeInfo.category  // 'thermocouple', 'voltage', 'current_output', 'digital', etc.
    } else {
      // Module not in mapping - fall back to backend-reported values
      // This handles unknown modules or non-NI hardware
      console.warn(`Unknown module type: ${ch.module_name} - using backend-reported type`)
      hwType = ch.channel_type || 'analog_input'
      category = ch.category || 'voltage'
    }

    // For display purposes (limits, groups, units), use category for analog, hw_type for digital
    const displayType = category === 'digital' ? hwType : category
    const limits = getDefaultLimits(displayType)
    const group = getDefaultGroupName(displayType, ch.module_name)
    const units = getDefaultUnit(displayType as ChannelType)

    channelsToCreate.push({
      name: tagName,  // TAG is the only identifier (tag_0, tag_1, etc.)
      physical_channel: ch.name,  // Physical channel like "cDAQ1Mod1/ai0"
      channel_type: hwType,  // Hardware type for backend (analog_output, digital_input, etc.)
      category: category,  // Measurement category (current_output, thermocouple, voltage, digital)
      description: `${ch.module_name} - ${ch.description || ch.name}`,
      module: ch.module_device,
      group: group,
      units: units,
      low_limit: limits.low,
      high_limit: limits.high,
      low_warning: limits.lowWarn,
      high_warning: limits.highWarn,
      log: true,
      log_interval_ms: 1000,
      enabled: true,
      // Source tracking (for multi-node systems)
      // For cRIO/Opto22: use node_id (e.g., "crio-001", "opto22-001")
      // For cDAQ: use chassis_name (e.g., "cDAQ-9189") for identification
      node_id: ch.is_crio || ch.is_opto22 ? ch.node_id : (ch.chassis_name || 'local'),
      source_type: ch.is_crio ? 'crio' : (ch.is_opto22 ? 'opto22' : 'cdaq'),
      // Chassis info for display
      chassis_name: ch.chassis_name || ''
    })

    channelEnabled.value[tagName] = true
  })

  // Use bulk create for efficiency (sends all at once)
  mqtt.bulkCreateChannels(channelsToCreate)

  showFeedback('success', `Added ${selectedChannels.length} channel(s) as tag_${startTagNum} through tag_${tagNum - 1}`)
  selectedDiscoveryChannels.value = []
  closeDiscoveryPanel()
  markDirty()
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
  // Select all channels from hierarchical data
  const allChannels: string[] = []

  if (discoveryResult.value?.chassis) {
    for (const chassis of discoveryResult.value.chassis) {
      for (const module of chassis.modules || []) {
        for (const channel of module.channels || []) {
          allChannels.push(channel.name)
        }
      }
    }
  }

  if (discoveryResult.value?.standalone_devices) {
    for (const device of discoveryResult.value.standalone_devices) {
      for (const channel of device.channels || []) {
        allChannels.push(channel.name)
      }
    }
  }

  // Include cRIO node channels
  if (discoveryResult.value?.crio_nodes) {
    for (const node of discoveryResult.value.crio_nodes) {
      for (const module of node.modules || []) {
        for (const channel of module.channels || []) {
          allChannels.push(channel.name)
        }
      }
    }
  }

  // Include Opto22 node channels
  if (discoveryResult.value?.opto22_nodes) {
    for (const node of discoveryResult.value.opto22_nodes) {
      for (const module of node.modules || []) {
        for (const channel of module.channels || []) {
          allChannels.push(channel.name)
        }
      }
    }
  }

  selectedDiscoveryChannels.value = allChannels
}

function deselectAllDiscoveryChannels() {
  selectedDiscoveryChannels.value = []
}

// Get total channel count from hierarchical data
function getTotalDiscoveryChannels(): number {
  let count = 0
  if (discoveryResult.value?.chassis) {
    for (const chassis of discoveryResult.value.chassis) {
      for (const module of chassis.modules || []) {
        count += module.channels?.length || 0
      }
    }
  }
  if (discoveryResult.value?.standalone_devices) {
    for (const device of discoveryResult.value.standalone_devices) {
      count += device.channels?.length || 0
    }
  }
  // Include cRIO node channels
  if (discoveryResult.value?.crio_nodes) {
    for (const node of discoveryResult.value.crio_nodes) {
      for (const module of node.modules || []) {
        count += module.channels?.length || 0
      }
    }
  }
  // Include Opto22 node channels
  if (discoveryResult.value?.opto22_nodes) {
    for (const node of discoveryResult.value.opto22_nodes) {
      for (const module of node.modules || []) {
        count += module.channels?.length || 0
      }
    }
  }
  return count
}

// Quick populate ALL discovered channels with tag_N naming (one-click setup)
function quickPopulateAllChannels() {
  const totalChannels = getTotalDiscoveryChannels()
  if (totalChannels === 0) {
    showFeedback('error', 'No channels to add')
    return
  }

  // Expand all, select all, and add them
  expandAllDiscovery()
  selectAllDiscoveryChannels()
  addSelectedChannels()
}

// Apply configuration changes and reinitialize DAQ tasks (without starting acquisition)
// This does NOT save to a project file - it just tells the backend to use the current channel config
function applyConfigChanges() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Send config/apply to backend - reinitialize hardware tasks with current channel config
  // This makes the backend start publishing with the current channel names/settings
  mqtt.sendNodeCommand('config/apply', {
    restart_acquisition: false  // Just reinitialize, don't start acquisition
  })

  // Also push to any cRIO nodes if present
  autoPushToRemoteNodes()

  // Save current widget layout to localStorage so it persists across page reloads
  store.saveLayoutToStorage()

  showFeedback('info', 'Applying configuration to hardware...')
  configDirty.value = false
}

// Channel type tabs - each type needs unique columns, so keep them separate
// Using shorter labels to reduce horizontal space
const channelTypeTabs = [
  { id: 'all', label: 'ALL', icon: '⊞' },
  { id: 'thermocouple', label: 'TC', icon: '🌡' },
  { id: 'rtd', label: 'RTD', icon: '🌡' },
  { id: 'voltage', label: 'V-IN', icon: '⚡' },
  { id: 'current', label: 'mA-IN', icon: '〰' },
  { id: 'voltage_output', label: 'V-OUT', icon: '↗' },
  { id: 'current_output', label: 'mA-OUT', icon: '↗' },
  { id: 'digital_input', label: 'DI', icon: '▢' },
  { id: 'digital_output', label: 'DO', icon: '▣' },
  { id: 'counter', label: 'CTR', icon: '#' },
  { id: 'strain', label: 'STR', icon: '⚖' },
  { id: 'iepe', label: 'IEPE', icon: '〰' },
  { id: 'modbus', label: 'MODBUS', icon: '🔌' },
  { id: 'rest_api', label: 'REST', icon: '🌐' },
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
    if (activeTypeTab.value === 'modbus') {
      // Modbus tab shows both modbus_register and modbus_coil types
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'modbus_register' || ch.channel_type === 'modbus_coil'
      )
    } else if (activeTypeTab.value === 'voltage_output') {
      // V-OUT: analog_output channels with voltage range
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'analog_output' &&
        (ch.ao_range?.includes('V') || !ch.ao_range?.includes('mA'))
      )
    } else if (activeTypeTab.value === 'current_output') {
      // mA-OUT: analog_output channels with current range
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
      ch.description?.toLowerCase().includes(query)  // Search name + description only
    )
  }

  return channels
})

// Get current value for a channel (shows error strings for problematic channels)
function getCurrentValue(channelName: string): string {
  const value = store.values[channelName]
  if (!value) return '--'

  // Check for specific error conditions (from backend validation)
  if (value.status === 'open_thermocouple' || value.openThermocouple) {
    return value.valueString || 'Open TC'
  }
  if (value.status === 'overflow' || value.overflow) {
    return value.valueString || 'Inf'
  }
  if (value.disconnected || value.quality === 'bad') {
    return value.valueString || 'NaN'
  }

  // Check for NaN/invalid numeric value
  if (typeof value.value !== 'number' || Number.isNaN(value.value)) {
    return value.valueString || 'NaN'
  }

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

// Get raw min value from channel config (for scaling display)
function getRawMin(channelName: string): string {
  const config = store.channels[channelName]
  if (!config) return '--'

  // For 4-20mA, raw min is always 4
  if (config.four_twenty_scaling) return '4 mA'

  // For map scaling, use pre_scaled_min
  if (config.scale_type === 'map' && config.pre_scaled_min !== undefined) {
    return `${config.pre_scaled_min}`
  }

  // For voltage/current, use the range
  if (config.channel_type === 'voltage') {
    const range = config.voltage_range ?? '±10V'
    if (typeof range === 'string' && range.includes('±')) return `-${range.replace('±', '').replace('V', '')} V`
    return '0 V'
  }
  if (config.channel_type === 'current') {
    return config.four_twenty_scaling ? '4 mA' : '0 mA'
  }

  return config.pre_scaled_min?.toString() || '0'
}

// Get raw max value from channel config
function getRawMax(channelName: string): string {
  const config = store.channels[channelName]
  if (!config) return '--'

  // For 4-20mA, raw max is always 20
  if (config.four_twenty_scaling) return '20 mA'

  // For map scaling, use pre_scaled_max
  if (config.scale_type === 'map' && config.pre_scaled_max !== undefined) {
    return `${config.pre_scaled_max}`
  }

  // For voltage, use the range
  if (config.channel_type === 'voltage') {
    const range = config.voltage_range ?? '±10V'
    if (typeof range === 'string') return range.replace('±', '').replace('V', '') + ' V'
    return `${range} V`
  }
  if (config.channel_type === 'current') {
    return '20 mA'
  }

  return config.pre_scaled_max?.toString() || '10'
}

// Get scaled min value from channel config (engineering units)
function getScaledMin(channelName: string): string {
  const config = store.channels[channelName]
  if (!config) return '--'

  // For 4-20mA scaling
  if (config.four_twenty_scaling && config.eng_units_min !== undefined) {
    return `${config.eng_units_min}`
  }

  // For map scaling
  if (config.scale_type === 'map' && config.scaled_min !== undefined) {
    return `${config.scaled_min}`
  }

  // For linear scaling (y = mx + b), scaled_min = m * raw_min + b
  if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
    const rawMin = parseFloat(getRawMin(channelName)) || 0
    return `${(rawMin * config.scale_slope + (config.scale_offset || 0)).toFixed(2)}`
  }

  return config.scaled_min?.toString() || config.eng_units_min?.toString() || '0'
}

// Get scaled max value from channel config (engineering units)
function getScaledMax(channelName: string): string {
  const config = store.channels[channelName]
  if (!config) return '--'

  // For 4-20mA scaling
  if (config.four_twenty_scaling && config.eng_units_max !== undefined) {
    return `${config.eng_units_max}`
  }

  // For map scaling
  if (config.scale_type === 'map' && config.scaled_max !== undefined) {
    return `${config.scaled_max}`
  }

  // For linear scaling (y = mx + b), scaled_max = m * raw_max + b
  if (config.scale_type === 'linear' && config.scale_slope !== undefined) {
    const rawMax = parseFloat(getRawMax(channelName)) || 10
    return `${(rawMax * config.scale_slope + (config.scale_offset || 0)).toFixed(2)}`
  }

  return config.scaled_max?.toString() || config.eng_units_max?.toString() || '100'
}

// Get channel status including errors and alarms
// Returns status class for styling the value cell
function getAlarmStatus(channelName: string): 'normal' | 'warning' | 'alarm' | 'stale' | 'disconnected' | 'open-tc' | 'overflow' {
  const value = store.values[channelName]

  // No data - stale/not connected
  if (!value) return 'stale'

  // Check for specific error conditions FIRST (these take precedence over alarms)
  if (value.status === 'open_thermocouple' || value.openThermocouple) {
    return 'open-tc'
  }
  if (value.status === 'overflow' || value.overflow) {
    return 'overflow'
  }
  if (value.disconnected || value.quality === 'bad') {
    return 'disconnected'
  }
  if (typeof value.value !== 'number' || Number.isNaN(value.value)) {
    return 'disconnected'
  }

  // Check alarm/warning only if limit colors enabled
  if (!showLimitColors.value) return 'normal'

  // Check if this channel has alarms enabled (ISA-18.2)
  const config = store.channels[channelName]
  if (config) {
    // If alarm_enabled is explicitly false, don't show alarm colors
    if (config.alarm_enabled === false) return 'normal'

    // Check if any alarm limits are actually configured
    // Without limits, there's nothing to alarm on
    // Use != null to check both undefined AND null
    const hasAlarmLimits = (
      config.hihi_limit != null ||
      config.lolo_limit != null ||
      config.high_limit != null ||
      config.low_limit != null
    )
    if (!hasAlarmLimits) return 'normal'
  } else {
    // No config at all means no alarm limits configured
    return 'normal'
  }

  if (value.alarm) return 'alarm'
  if (value.warning) return 'warning'
  return 'normal'
}

// Get alarm button class for the ALARM column
function getAlarmButtonClass(channelName: string, config: ChannelConfig): string {
  const classes = []

  if (config.alarm_enabled) {
    classes.push('enabled')
    // Show current alarm state
    const status = getAlarmStatus(channelName)
    if (status === 'alarm') classes.push('active-alarm')
    else if (status === 'warning') classes.push('active-warning')
  } else {
    classes.push('disabled')
  }

  return classes.join(' ')
}

// Get tooltip for alarm button
function getAlarmTooltip(channelName: string, config: ChannelConfig): string {
  if (!config.alarm_enabled) {
    return 'Click to configure alarms (currently disabled)'
  }

  const limits = []
  if (config.hihi_limit !== undefined) limits.push(`HiHi: ${config.hihi_limit}`)
  if (config.hi_limit !== undefined) limits.push(`Hi: ${config.hi_limit}`)
  if (config.lo_limit !== undefined) limits.push(`Lo: ${config.lo_limit}`)
  if (config.lolo_limit !== undefined) limits.push(`LoLo: ${config.lolo_limit}`)

  if (limits.length > 0) {
    return `Alarm enabled: ${limits.join(', ')}`
  }
  return 'Alarm enabled (no limits set)'
}

// Open channel config and scroll to alarm section
function openAlarmConfig(channelName: string) {
  openChannelConfig(channelName)
  // Scroll to alarm section after panel opens
  setTimeout(() => {
    const alarmSection = document.querySelector('.config-section h4')
    if (alarmSection) {
      // Find the "Alarm Configuration" heading
      const sections = document.querySelectorAll('.config-section h4')
      sections.forEach(section => {
        if (section.textContent === 'Alarm Configuration') {
          section.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      })
    }
  }, 100)
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
    modbus_register: 'MB',
    modbus_coil: 'MBC',
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

  // ISA-18.2 Alarm Configuration
  moduleConfig.alarm_enabled = config.alarm_enabled ?? false
  moduleConfig.hi_limit = config.hi_limit ?? config.high_limit  // Support legacy field name
  moduleConfig.lo_limit = config.lo_limit ?? config.low_limit   // Support legacy field name
  moduleConfig.hihi_limit = config.hihi_limit
  moduleConfig.lolo_limit = config.lolo_limit
  moduleConfig.alarm_priority = config.alarm_priority ?? 'medium'
  moduleConfig.alarm_deadband = config.alarm_deadband ?? 1.0
  moduleConfig.alarm_delay_sec = config.alarm_delay_sec ?? 0

  // Ensure color has a valid default (required for type="color" input)
  const configWithDefaults = {
    ...config,
    color: config.color || '#60a5fa'  // Default blue if not set
  }

  editingConfig.value = {
    name: channelName,
    newName: channelName,
    config: configWithDefaults,
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

    // Logging settings
    log: mc.log,
    log_interval_ms: mc.log_interval_ms,

    // Safety settings
    safety_action: mc.safety_action || null,
    safety_interlock: mc.safety_interlock || null,

    // ISA-18.2 Alarm Configuration
    alarm_enabled: mc.alarm_enabled ?? false,
    hi_limit: mc.hi_limit,
    lo_limit: mc.lo_limit,
    hihi_limit: mc.hihi_limit,
    lolo_limit: mc.lolo_limit,
    alarm_priority: mc.alarm_priority ?? 'medium',
    alarm_deadband: mc.alarm_deadband ?? 1.0,
    alarm_delay_sec: mc.alarm_delay_sec ?? 0,
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
  // Digital input alarm settings
  if (channelType === 'digital_input') {
    config.digital_alarm_enabled = mc.alarm_enabled ?? false
    config.digital_expected_state = mc.di_alarm_expected_state ? 'HIGH' : 'LOW'
    config.digital_debounce_ms = mc.di_alarm_debounce_ms ?? 100
    config.digital_invert = mc.di_alarm_invert ?? false
  }

  // Include new_name if renaming the channel
  const isRenaming = editingConfig.value.newName !== editingConfig.value.name
  if (isRenaming) {
    // Validate rename and check dependencies
    const validation = tagDeps.validateTagRename(editingConfig.value.name, editingConfig.value.newName)

    if (!validation.valid) {
      showFeedback('error', validation.warnings.join(', '))
      return
    }

    // Warn about affected references
    if (validation.affectedReferences.length > 0) {
      const refSummary = validation.affectedReferences
        .map(r => `  - ${r.type}: ${r.name}`)
        .join('\n')
      const proceed = confirm(
        `Renaming "${editingConfig.value.name}" to "${editingConfig.value.newName}" will affect ${validation.affectedReferences.length} reference(s):\n\n${refSummary}\n\nNote: Python scripts must be updated manually.\n\nProceed with rename?`
      )
      if (!proceed) return
    }

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

// Save configuration - to project if one is loaded, otherwise prompt to create one
async function saveToFile() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // If a project is loaded, save to the project
  const currentProject = projectFiles.currentProject.value
  if (currentProject) {
    isSaving.value = true
    try {
      const success = await projectFiles.saveProject(currentProject)
      if (success) {
        showFeedback('success', `Saved to project: ${currentProject}`)
        configDirty.value = false
        // Auto-push to any cRIO nodes if present
        autoPushToRemoteNodes()
      } else {
        showFeedback('error', 'Failed to save project')
      }
    } catch (e: any) {
      showFeedback('error', `Save failed: ${e.message || 'Unknown error'}`)
    } finally {
      isSaving.value = false
    }
    return
  }

  // No project loaded - prompt user to create one
  showCreateProjectDialog.value = true
}

// Create Project Dialog state
const showCreateProjectDialog = ref(false)
const newProjectName = ref('')

async function createAndSaveProject() {
  if (!newProjectName.value.trim()) {
    showFeedback('error', 'Please enter a project name')
    return
  }

  const filename = newProjectName.value.trim().replace(/\s+/g, '_') + '.json'
  isSaving.value = true

  try {
    const success = await projectFiles.saveProject(filename, newProjectName.value.trim())
    if (success) {
      showFeedback('success', `Created and saved project: ${filename}`)
      configDirty.value = false
      showCreateProjectDialog.value = false
      newProjectName.value = ''
      // Auto-push to any cRIO nodes if present
      autoPushToRemoteNodes()
    } else {
      showFeedback('error', 'Failed to create project')
    }
  } catch (e: any) {
    showFeedback('error', `Create project failed: ${e.message || 'Unknown error'}`)
  } finally {
    isSaving.value = false
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

// Open Save As dialog - commented out, button removed from UI
// function openSaveAsDialog() {
//   if (!mqtt.connected.value) {
//     showFeedback('error', 'Not connected to MQTT broker')
//     return
//   }
//   const baseName = currentConfigName.value.replace('.ini', '')
//   saveAsFilename.value = baseName
//   showSaveAsDialog.value = true
// }

// Save with new filename (legacy - now uses project system)
function saveAsFile() {
  if (!saveAsFilename.value.trim()) {
    showFeedback('error', 'Please enter a filename')
    return
  }
  // Use the project system for saving
  saveToFile()
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
  console.log('[ConfigTab] Config update response:', response)
  // Only show feedback for actual success/failure responses, not data responses
  // Data responses like { configs: [...] } don't have success field
  if (response.success === true) {
    showFeedback('success', response.message || 'Configuration updated')
  } else if (response.success === false || response.error) {
    // Log full response for debugging - this will appear in browser console
    console.error('[ConfigTab] Configuration update FAILED:', {
      success: response.success,
      message: response.message,
      error: response.error,
      fullResponse: response
    })
    // If there's a failed array with details, log each failure reason
    if (response.failed && Array.isArray(response.failed) && response.failed.length > 0) {
      console.error('[ConfigTab] Failed channels:')
      response.failed.forEach((f: { name?: string; error?: string }) => {
        console.error(`  - ${f.name || 'unknown'}: ${f.error || 'no reason'}`)
      })
    }
    // Backend sends 'message' field, not 'error' - use either
    const errorMsg = response.message || response.error || 'Configuration update failed (no details)'
    showFeedback('error', errorMsg)
  }
  // If neither success nor error, it's a data response - no feedback needed

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
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'current':
      return [
        ...baseColumns,
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
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
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'current_output':
      return [
        ...baseColumns,
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'analog_output':
      // Fallback for generic analog output (shouldn't be used with new tabs)
      return [
        ...baseColumns,
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
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

  // Register callback for system settings update response
  mqtt.onSystemUpdate((result: any) => {
    if (result.success) {
      showFeedback('success', `System settings updated: Scan ${result.scan_rate_hz} Hz, Publish ${result.publish_rate_hz} Hz`)
    } else {
      showFeedback('error', `Failed to update system settings: ${result.error || 'Unknown error'}`)
    }
  })
})

watch(() => Object.keys(store.channels), () => {
  initializeEnableStates()
})
</script>

<template>
  <div class="config-tab">
    <!-- Channel Type Tabs + Status Bar -->
    <div class="type-tabs-row">
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
      <div class="status-compact">
        <span class="status-item channels">{{ Object.keys(store.channels).length }} ch</span>
        <span class="status-item mqtt" :class="{ connected: mqtt.connected.value }">
          {{ mqtt.connected.value ? 'MQTT' : 'Disconnected' }}
        </span>
        <button class="theme-toggle-small" @click="toggleTheme" :title="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'">
          <svg v-if="theme === 'dark'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Search and Actions Bar -->
    <div class="actions-bar">
      <div class="left-actions">
        <!-- Auto Discovery button -->
        <button class="action-btn primary" @click="scanDevices" :disabled="isScanning" title="Auto-discover hardware devices">
          <svg v-if="!isScanning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
            <path d="M8 11h6M11 8v6"/>
          </svg>
          <span v-else class="spinner"></span>
          {{ isScanning ? 'Discovering...' : 'Auto Discovery' }}
        </button>

        <!-- Search -->
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

        <div class="toolbar-divider"></div>

        <!-- Group 2: View/Mode Toggles -->
        <button class="action-btn" @click="openProjectManager" title="Manage projects - load existing or start new">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          Projects
        </button>
        <button class="action-btn" @click="openSystemSettings" title="System settings (scan rate, publish rate)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
          Settings
        </button>
        <button class="action-btn accent" @click="autoGenerateWidgets" title="Auto-generate widgets for all channels based on channel type">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
          </svg>
          Auto-Gen Widgets
        </button>
        <button
          class="action-btn"
          :class="{ active: editMode, 'no-permission': !hasEditPermission.value }"
          @click="toggleEditMode"
          :disabled="store.isAcquiring"
          :title="!hasEditPermission.value ? 'Login required to edit (Operator+)' : (store.isAcquiring ? 'Stop acquisition to edit' : (editMode ? 'Exit edit mode' : 'Enter edit mode'))"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          {{ editMode ? 'EDITING' : 'Edit' }}
          <span v-if="!hasEditPermission.value" class="lock-badge">🔒</span>
        </button>
        <button
          class="action-btn"
          :class="{ active: showLimitColors }"
          @click="showLimitColors = !showLimitColors"
          title="Toggle alarm/warning colors based on channel limits"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 8v4"/>
            <path d="M12 16h.01"/>
          </svg>
          {{ showLimitColors ? 'Limits ON' : 'Limits' }}
        </button>

        <!-- Group 3: Safety (orange - draws attention) -->
        <button class="action-btn warning" @click="openSafetyActionsModal" title="Configure safety interlocks and actions">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Safety
        </button>

        <div class="toolbar-divider"></div>

        <!-- Group 4: File Operations -->
        <button
          class="action-btn primary"
          :class="{ dirty: configDirty }"
          @click="saveToFile()"
          :disabled="isSaving"
          :title="projectFiles.currentProject.value
            ? `Save to project: ${projectFiles.currentProject.value}`
            : 'Create new project and save'"
        >
          <svg v-if="!isSaving" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
          </svg>
          <span v-else class="spinner"></span>
          {{ isSaving ? 'Saving...' : 'Save' }}
          <span v-if="configDirty && !isSaving" class="dirty-indicator">*</span>
        </button>
        <button class="action-btn" @click="exportProject" :disabled="isExporting" title="Export project as .json file to your computer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          Export
        </button>
        <button class="action-btn" @click="triggerImport" title="Import project from a .json file on your computer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Import
        </button>
        <input
          ref="importFileInput"
          type="file"
          accept=".json"
          style="display: none"
          @change="handleImportFile"
        />

        <div class="toolbar-divider"></div>

        <!-- Group 5: Push (blue - sends to hardware) -->
        <button
          class="action-btn accent"
          :class="{ 'out-of-sync': hasCrioOutOfSync }"
          @click="applyConfigChanges"
          :disabled="!mqtt.connected.value"
          :title="hasCrioOutOfSync ? 'Push config to hardware (cRIO out of sync!)' : 'Push channel config to hardware'"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          Push
          <span v-if="hasCrioOutOfSync" class="sync-badge">!</span>
        </button>
      </div>
      <div class="right-info">
        <div v-if="projectFiles.currentProject.value" class="project-indicator" :title="`Project: ${projectFiles.currentProject.value}`">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          {{ projectFiles.currentProject.value.replace('.json', '') }}
        </div>
        <div v-if="store.status?.simulation_mode" class="sim-mode-indicator" title="Running in simulation mode - no real hardware">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
          SIM MODE
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
      <!-- Modbus Device Configuration (shown when MODBUS tab is active) -->
      <ModbusDeviceConfig
        v-if="activeTypeTab === 'modbus'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

      <!-- REST API Device Configuration (shown when REST tab is active) -->
      <RestApiDeviceConfig
        v-if="activeTypeTab === 'rest_api'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

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
              <th class="col-alarm">ALARM</th>
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
              <!-- TAG - channel identifier (read-only) -->
              <td class="col-tag">
                <span class="tag-display">{{ name }}</span>
                <span v-if="config.source_type === 'crio'" class="source-badge crio" title="Remote cRIO node">cRIO</span>
                <span v-else-if="config.source_type === 'opto22'" class="source-badge opto22" title="Remote Opto22 node">Opto22</span>
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
                  <input
                    type="text"
                    :value="config.pre_scaled_min ?? (typeof config.voltage_range === 'number' ? -Math.abs(config.voltage_range) : -10)"
                    @blur="updateChannelField(name, 'pre_scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_max ?? (config.voltage_range ?? 10)"
                    @blur="updateChannelField(name, 'pre_scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_min ?? config.eng_units_min ?? 0"
                    @blur="updateChannelField(name, 'scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_max ?? config.eng_units_max ?? 100"
                    @blur="updateChannelField(name, 'scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
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
                  <input
                    type="text"
                    :value="config.pre_scaled_min ?? (config.four_twenty_scaling ? 4 : 0)"
                    @blur="updateChannelField(name, 'pre_scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_max ?? 20"
                    @blur="updateChannelField(name, 'pre_scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_min ?? config.eng_units_min ?? 0"
                    @blur="updateChannelField(name, 'scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_max ?? config.eng_units_max ?? 100"
                    @blur="updateChannelField(name, 'scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
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
                  <input
                    type="text"
                    :value="config.pre_scaled_min ?? 0"
                    @blur="updateChannelField(name, 'pre_scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_max ?? 10"
                    @blur="updateChannelField(name, 'pre_scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_min ?? config.eng_units_min ?? 0"
                    @blur="updateChannelField(name, 'scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_max ?? config.eng_units_max ?? 100"
                    @blur="updateChannelField(name, 'scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
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
                  <input
                    type="text"
                    :value="config.pre_scaled_min ?? (config.ao_range === '4-20mA' ? 4 : 0)"
                    @blur="updateChannelField(name, 'pre_scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_max ?? 20"
                    @blur="updateChannelField(name, 'pre_scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_min ?? config.eng_units_min ?? 0"
                    @blur="updateChannelField(name, 'scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_max ?? config.eng_units_max ?? 100"
                    @blur="updateChannelField(name, 'scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
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
                <!-- Fallback for generic analog output -->
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_min ?? 0"
                    @blur="updateChannelField(name, 'pre_scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.pre_scaled_max ?? 10"
                    @blur="updateChannelField(name, 'pre_scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_min ?? config.eng_units_min ?? 0"
                    @blur="updateChannelField(name, 'scaled_min', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="text"
                    :value="config.scaled_max ?? config.eng_units_max ?? 100"
                    @blur="updateChannelField(name, 'scaled_max', parseFloat(($event.target as HTMLInputElement).value))"
                    class="inline-input narrow"
                    :disabled="!canEdit"
                  />
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

              <!-- ALARM column - shows alarm status and quick access -->
              <td class="col-alarm" @click.stop>
                <button
                  class="alarm-btn"
                  :class="getAlarmButtonClass(name, config)"
                  @click="openAlarmConfig(name)"
                  :title="getAlarmTooltip(name, config)"
                >
                  <!-- Bell icon -->
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                    <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                  </svg>
                  <span v-if="config.alarm_enabled" class="alarm-indicator"></span>
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
              <td :colspan="tableColumns.length + 2">
                <div class="empty-state">
                  <p v-if="searchQuery">No channels matching "{{ searchQuery }}"</p>
                  <p v-else>No channels configured</p>
                </div>
              </td>
            </tr>
            <!-- Add Channel Row (hidden on ALL tab) -->
            <tr
              v-if="activeTypeTab !== 'all'"
              class="add-channel-row"
              @click="openAddChannelModal"
            >
              <td :colspan="tableColumns.length + 2">
                <div class="add-channel-cell">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                  <span>Add Channel...</span>
                </div>
              </td>
            </tr>
            <!-- Hint row on ALL tab -->
            <tr v-else class="add-channel-hint-row">
              <td :colspan="tableColumns.length + 2">
                <div class="add-channel-hint">
                  Select a channel type tab (TC, V-IN, DO, etc.) to add channels
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
            <h3>{{ editingConfig.name }}</h3>
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
              <!-- display_name removed - TAG is the only identifier -->
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

            <!-- ISA-18.2 Alarm Configuration -->
            <div class="config-section">
              <h4>Alarm Configuration</h4>
              <div class="form-row checkbox-row">
                <label>
                  <input type="checkbox" v-model="editingConfig.moduleConfig.alarm_enabled" />
                  Enable Alarm Checking
                </label>
              </div>

              <template v-if="editingConfig.moduleConfig.alarm_enabled">
                <!-- Alarm Setpoints -->
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>HiHi Limit</label>
                    <input
                      type="number"
                      v-model.number="editingConfig.moduleConfig.hihi_limit"
                      step="any"
                      placeholder="Critical high"
                    />
                  </div>
                  <div class="form-row half">
                    <label>LoLo Limit</label>
                    <input
                      type="number"
                      v-model.number="editingConfig.moduleConfig.lolo_limit"
                      step="any"
                      placeholder="Critical low"
                    />
                  </div>
                </div>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Hi Limit</label>
                    <input
                      type="number"
                      v-model.number="editingConfig.moduleConfig.hi_limit"
                      step="any"
                      placeholder="Warning high"
                    />
                  </div>
                  <div class="form-row half">
                    <label>Lo Limit</label>
                    <input
                      type="number"
                      v-model.number="editingConfig.moduleConfig.lo_limit"
                      step="any"
                      placeholder="Warning low"
                    />
                  </div>
                </div>
                <span class="form-hint alarm-hint">HiHi/LoLo = Critical (red), Hi/Lo = Warning (yellow)</span>

                <!-- Alarm Options -->
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Priority</label>
                    <select v-model="editingConfig.moduleConfig.alarm_priority">
                      <option value="diagnostic">Diagnostic</option>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="critical">Critical</option>
                    </select>
                  </div>
                  <div class="form-row half">
                    <label>Deadband</label>
                    <input
                      type="number"
                      v-model.number="editingConfig.moduleConfig.alarm_deadband"
                      step="0.1"
                      min="0"
                      placeholder="1.0"
                    />
                  </div>
                </div>

                <div class="form-row">
                  <label>On-Delay (sec)</label>
                  <input
                    type="number"
                    v-model.number="editingConfig.moduleConfig.alarm_delay_sec"
                    step="0.1"
                    min="0"
                    placeholder="0"
                  />
                  <span class="form-hint">Delay before alarm triggers (prevents nuisance alarms)</span>
                </div>

                <!-- Safety System Integration (ISA-18.2) -->
                <div class="form-row">
                  <label>Safety Action</label>
                  <select v-model="editingConfig.moduleConfig.safety_action">
                    <option value="">None (visual-only alarm)</option>
                    <option
                      v-for="(action, actionId) in safety.safetyActions.value"
                      :key="actionId"
                      :value="actionId"
                    >
                      {{ action.name }} ({{ action.type }})
                    </option>
                  </select>
                  <span class="form-hint">Automatically execute when alarm triggers</span>
                </div>

                <!-- Digital Input Alarm Configuration -->
                <template v-if="editingConfig.config.channel_type === 'digital_input'">
                  <div class="form-row-group">
                    <div class="form-row half">
                      <label>Expected State</label>
                      <select v-model="editingConfig.moduleConfig.di_alarm_expected_state">
                        <option :value="true">HIGH (1) - Alarm on LOW</option>
                        <option :value="false">LOW (0) - Alarm on HIGH</option>
                      </select>
                    </div>
                    <div class="form-row half">
                      <label>DI Alarm Debounce (ms)</label>
                      <input
                        type="number"
                        v-model.number="editingConfig.moduleConfig.di_alarm_debounce_ms"
                        step="10"
                        min="0"
                        placeholder="100"
                      />
                    </div>
                  </div>
                  <div class="form-row checkbox-row">
                    <label>
                      <input type="checkbox" v-model="editingConfig.moduleConfig.di_alarm_invert" />
                      Invert DI for Alarm (NC sensor)
                    </label>
                    <span class="form-hint">Check for NC sensors where signal LOW = normal state</span>
                  </div>
                </template>
              </template>

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

            <!-- Modbus Register settings -->
            <template v-if="editingConfig.config.channel_type === 'modbus_register'">
              <div class="config-section">
                <h4>Modbus Settings</h4>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Register Type</label>
                    <select v-model="editingConfig.config.modbus_register_type">
                      <option value="holding">Holding Register (R/W)</option>
                      <option value="input">Input Register (R)</option>
                    </select>
                  </div>
                  <div class="form-row half">
                    <label>Slave/Unit ID</label>
                    <input type="number" v-model="editingConfig.config.modbus_slave_id" min="1" max="247" placeholder="From module" />
                  </div>
                </div>
                <div class="form-row">
                  <label>Register Address</label>
                  <input type="number" v-model="editingConfig.config.modbus_address" min="0" max="65535" />
                </div>
                <div class="form-row">
                  <label>Data Type</label>
                  <select v-model="editingConfig.config.modbus_data_type">
                    <option value="int16">Int16 (1 register)</option>
                    <option value="uint16">UInt16 (1 register)</option>
                    <option value="int32">Int32 (2 registers)</option>
                    <option value="uint32">UInt32 (2 registers)</option>
                    <option value="float32">Float32 (2 registers)</option>
                    <option value="float64">Float64 (4 registers)</option>
                  </select>
                </div>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Byte Order</label>
                    <select v-model="editingConfig.config.modbus_byte_order">
                      <option value="big">Big Endian</option>
                      <option value="little">Little Endian</option>
                    </select>
                  </div>
                  <div class="form-row half">
                    <label>Word Order</label>
                    <select v-model="editingConfig.config.modbus_word_order">
                      <option value="big">Big (Normal)</option>
                      <option value="little">Little (Swapped)</option>
                    </select>
                  </div>
                </div>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Scale Factor</label>
                    <input type="number" v-model="editingConfig.config.modbus_scale" step="any" />
                  </div>
                  <div class="form-row half">
                    <label>Offset</label>
                    <input type="number" v-model="editingConfig.config.modbus_offset" step="any" />
                  </div>
                </div>
                <div class="form-hint">Value = Raw * Scale + Offset</div>

                <!-- Batch Reading (Advanced) -->
                <h4 style="margin-top: 16px;">Batch Reading (Advanced)</h4>
                <div class="form-hint" style="margin-bottom: 8px;">
                  Read multiple registers in one transaction. Use when device requires atomic reads
                  or for efficiency when multiple channels share contiguous registers.
                </div>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Register Count</label>
                    <input type="number" v-model="editingConfig.config.modbus_register_count" min="1" max="125" placeholder="Auto" />
                  </div>
                  <div class="form-row half">
                    <label>Register Index</label>
                    <input type="number" v-model="editingConfig.config.modbus_register_index" min="0" placeholder="0" />
                  </div>
                </div>
                <div class="form-hint">
                  Index = position within batch where this channel's value starts (0-based).
                  Example: Read 13 registers, extract UINT16 at index 4 → registers[4].
                </div>
              </div>
            </template>

            <!-- Modbus Coil settings -->
            <template v-if="editingConfig.config.channel_type === 'modbus_coil'">
              <div class="config-section">
                <h4>Modbus Coil Settings</h4>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Coil Type</label>
                    <select v-model="editingConfig.config.modbus_register_type">
                      <option value="coil">Coil (R/W)</option>
                      <option value="discrete">Discrete Input (R)</option>
                    </select>
                  </div>
                  <div class="form-row half">
                    <label>Slave/Unit ID</label>
                    <input type="number" v-model="editingConfig.config.modbus_slave_id" min="1" max="247" placeholder="From module" />
                  </div>
                </div>
                <div class="form-row">
                  <label>Coil Address</label>
                  <input type="number" v-model="editingConfig.config.modbus_address" min="0" max="65535" />
                </div>
                <div class="form-row checkbox-row">
                  <label>
                    <input type="checkbox" v-model="editingConfig.config.invert" />
                    Invert Logic
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

    <!-- Simulation Mode Warning (only when active) -->
    <div v-if="store.status?.simulation_mode" class="sim-banner">
      <span class="sim-icon">⚠️</span> SIMULATION MODE - No real hardware connected
    </div>

    <!-- Discovery Panel Modal -->
    <Transition name="modal">
      <div v-if="showDiscoveryPanel" class="discovery-overlay" @click.self="closeDiscoveryPanel">
        <div class="discovery-panel">
          <div class="discovery-header">
            <h3>Device Discovery</h3>
            <button class="close-btn" @click="closeDiscoveryPanel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="discovery-content">
            <template v-if="isScanning">
              <div class="scanning-state">
                <div class="spinner large"></div>
                <p>Discovering hardware devices...</p>
              </div>
            </template>

            <template v-else-if="discoveryResult?.chassis?.length > 0 || discoveryResult?.standalone_devices?.length > 0 || discoveryResult?.crio_nodes?.length > 0 || discoveryResult?.opto22_nodes?.length > 0">
              <div class="discovery-toolbar">
                <span class="discovery-count">{{ getTotalDiscoveryChannels() }} channels found</span>
                <div class="discovery-actions">
                  <button class="btn-link" @click="expandAllDiscovery">Expand All</button>
                  <button class="btn-link" @click="collapseAllDiscovery">Collapse All</button>
                  <span class="separator">|</span>
                  <button class="btn-link" @click="selectAllDiscoveryChannels">Select All</button>
                  <button class="btn-link" @click="deselectAllDiscoveryChannels">Deselect All</button>
                </div>
              </div>

              <!-- Quick Populate Banner -->
              <div class="quick-populate-banner">
                <div class="banner-text">
                  <strong>Quick Setup:</strong> Add all channels as tag_0, tag_1, tag_2, etc.
                </div>
                <button class="btn btn-success" @click="quickPopulateAllChannels">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                  </svg>
                  Populate All ({{ getTotalDiscoveryChannels() }})
                </button>
              </div>

              <!-- Simulation Mode Banner -->
              <div v-if="discoveryResult?.simulation_mode" class="simulation-banner">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                <span>Simulation Mode - No real hardware detected</span>
              </div>

              <!-- Tree View -->
              <div class="discovery-tree">
                <!-- Chassis (cDAQ) -->
                <div v-for="chassis in discoveryResult.chassis" :key="chassis.name" class="tree-chassis">
                  <div class="tree-header chassis-header" @click="toggleChassis(chassis.name)">
                    <svg class="tree-arrow" :class="{ expanded: expandedChassis.has(chassis.name) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M8 5l8 7-8 7V5z"/>
                    </svg>
                    <svg class="tree-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                      <line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
                    </svg>
                    <span class="tree-name">{{ chassis.name }}</span>
                    <span class="device-badge cdaq">cDAQ</span>
                    <span class="tree-type">{{ chassis.product_type }}</span>
                    <span class="tree-count">{{ chassis.modules?.length || 0 }} modules</span>
                  </div>

                  <!-- Modules within Chassis -->
                  <div v-if="expandedChassis.has(chassis.name)" class="tree-children">
                    <div v-for="module in [...chassis.modules].sort((a, b) => a.slot - b.slot)" :key="module.name" class="tree-module">
                      <div class="tree-header module-header" @click="toggleModule(module.name)">
                        <svg class="tree-arrow" :class="{ expanded: expandedModules.has(module.name) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M8 5l8 7-8 7V5z"/>
                        </svg>
                        <input
                          type="checkbox"
                          :checked="isModuleFullySelected(module)"
                          :indeterminate="isModulePartiallySelected(module)"
                          @click.stop
                          @change="selectModuleChannels(module, ($event.target as HTMLInputElement).checked)"
                        />
                        <span class="tree-name">Slot {{ module.slot }}: {{ module.product_type }}</span>
                        <span class="tree-desc">{{ module.description }}</span>
                        <span class="tree-count">{{ module.channels?.length || 0 }} ch</span>
                      </div>

                      <!-- Channels within Module -->
                      <div v-if="expandedModules.has(module.name)" class="tree-children channel-list">
                        <div
                          v-for="channel in module.channels"
                          :key="channel.name"
                          class="tree-channel"
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name) }"
                          @click="toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.category">{{ channel.channel_type }}</span>
                          <span class="channel-desc">{{ channel.description }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Standalone Devices -->
                <div v-for="device in discoveryResult.standalone_devices" :key="device.name" class="tree-module standalone">
                  <div class="tree-header module-header" @click="toggleModule(device.name)">
                    <svg class="tree-arrow" :class="{ expanded: expandedModules.has(device.name) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M8 5l8 7-8 7V5z"/>
                    </svg>
                    <input
                      type="checkbox"
                      :checked="isModuleFullySelected(device)"
                      :indeterminate="isModulePartiallySelected(device)"
                      @click.stop
                      @change="selectModuleChannels(device, ($event.target as HTMLInputElement).checked)"
                    />
                    <span class="tree-name">{{ device.product_type }}</span>
                    <span class="tree-desc">{{ device.description }}</span>
                    <span class="tree-count">{{ device.channels?.length || 0 }} ch</span>
                  </div>

                  <!-- Channels -->
                  <div v-if="expandedModules.has(device.name)" class="tree-children channel-list">
                    <div
                      v-for="channel in device.channels"
                      :key="channel.name"
                      class="tree-channel"
                      :class="{ selected: selectedDiscoveryChannels.includes(channel.name) }"
                      @click="toggleDiscoveryChannel(channel.name)"
                    >
                      <input
                        type="checkbox"
                        :checked="selectedDiscoveryChannels.includes(channel.name)"
                        @click.stop
                        @change="toggleDiscoveryChannel(channel.name)"
                      />
                      <span class="channel-name">{{ channel.name }}</span>
                      <span class="type-badge" :class="channel.category">{{ channel.channel_type }}</span>
                      <span class="channel-desc">{{ channel.description }}</span>
                    </div>
                  </div>
                </div>

                <!-- cRIO Nodes (Remote CompactRIO devices) -->
                <div v-for="node in discoveryResult.crio_nodes" :key="node.node_id" class="tree-crio">
                  <div class="tree-header crio-header" @click="toggleCrioNode(node.node_id)">
                    <svg class="tree-arrow" :class="{ expanded: expandedCrioNodes.has(node.node_id) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M8 5l8 7-8 7V5z"/>
                    </svg>
                    <!-- cRIO icon (server/rack) -->
                    <svg class="tree-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="2" y="2" width="20" height="8" rx="2"/>
                      <rect x="2" y="14" width="20" height="8" rx="2"/>
                      <circle cx="6" cy="6" r="1" fill="currentColor"/>
                      <circle cx="6" cy="18" r="1" fill="currentColor"/>
                    </svg>
                    <span class="tree-name">{{ node.node_id }}</span>
                    <span class="device-badge crio">cRIO</span>
                    <span class="tree-type">{{ node.product_type }}</span>
                    <span class="crio-status" :class="node.status">{{ node.status }}</span>
                    <span class="tree-count">{{ node.modules?.length || 0 }} modules</span>
                    <button
                      class="btn-push-config"
                      @click.stop="pushConfigToCrio(node)"
                      :disabled="node.status !== 'online'"
                      :title="node.status !== 'online' ? 'Node is offline' : 'Push current project config to this cRIO'"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 5v14M5 12l7 7 7-7"/>
                      </svg>
                      Push
                    </button>
                  </div>

                  <!-- cRIO Info Bar -->
                  <div v-if="expandedCrioNodes.has(node.node_id)" class="crio-info-bar">
                    <span class="crio-ip">{{ node.ip_address }}</span>
                    <span class="crio-serial" v-if="node.serial_number">S/N: {{ node.serial_number }}</span>
                    <span class="crio-last-seen">Last seen: {{ node.last_seen }}</span>
                  </div>

                  <!-- Modules within cRIO -->
                  <div v-if="expandedCrioNodes.has(node.node_id)" class="tree-children">
                    <div v-for="module in [...node.modules].sort((a, b) => a.slot - b.slot)" :key="module.name" class="tree-module">
                      <div class="tree-header module-header" @click="toggleModule(module.name)">
                        <svg class="tree-arrow" :class="{ expanded: expandedModules.has(module.name) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M8 5l8 7-8 7V5z"/>
                        </svg>
                        <input
                          type="checkbox"
                          :checked="isModuleFullySelected(module)"
                          :indeterminate="isModulePartiallySelected(module)"
                          @click.stop
                          @change="selectModuleChannels(module, ($event.target as HTMLInputElement).checked)"
                        />
                        <span class="tree-name">Slot {{ module.slot }}: {{ module.product_type }}</span>
                        <span class="tree-desc">{{ module.description }}</span>
                        <span class="tree-count">{{ module.channels?.length || 0 }} ch</span>
                      </div>

                      <!-- Channels within Module -->
                      <div v-if="expandedModules.has(module.name)" class="tree-children channel-list">
                        <div
                          v-for="channel in module.channels"
                          :key="channel.name"
                          class="tree-channel"
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name) }"
                          @click="toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.category">{{ channel.channel_type }}</span>
                          <span class="channel-desc">{{ channel.description }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Opto22 Nodes (Remote groov EPIC/RIO devices) -->
                <div v-for="node in discoveryResult.opto22_nodes" :key="node.node_id" class="tree-opto22">
                  <div class="tree-header opto22-header" @click="toggleOpto22Node(node.node_id)">
                    <svg class="tree-arrow" :class="{ expanded: expandedOpto22Nodes.has(node.node_id) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M8 5l8 7-8 7V5z"/>
                    </svg>
                    <!-- Opto22 icon (groov style - rounded modern PLC) -->
                    <svg class="tree-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="3" y="4" width="18" height="16" rx="3"/>
                      <circle cx="7" cy="9" r="1.5" fill="currentColor"/>
                      <circle cx="12" cy="9" r="1.5" fill="currentColor"/>
                      <circle cx="17" cy="9" r="1.5" fill="currentColor"/>
                      <line x1="6" y1="15" x2="18" y2="15"/>
                    </svg>
                    <span class="tree-name">{{ node.node_id }}</span>
                    <span class="device-badge opto22">Opto22</span>
                    <span class="tree-type">{{ node.product_type }}</span>
                    <span class="opto22-status" :class="node.status">{{ node.status }}</span>
                    <span class="tree-count">{{ node.modules?.length || 0 }} modules</span>
                    <button
                      class="btn-push-config"
                      @click.stop="pushConfigToOpto22(node)"
                      :disabled="node.status !== 'online'"
                      :title="node.status !== 'online' ? 'Node is offline' : 'Push current project config to this Opto22'"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 5v14M5 12l7 7 7-7"/>
                      </svg>
                      Push
                    </button>
                  </div>

                  <!-- Opto22 Info Bar -->
                  <div v-if="expandedOpto22Nodes.has(node.node_id)" class="opto22-info-bar">
                    <span class="opto22-ip">{{ node.ip_address }}</span>
                    <span class="opto22-serial" v-if="node.serial_number">S/N: {{ node.serial_number }}</span>
                    <span class="opto22-last-seen">Last seen: {{ node.last_seen }}</span>
                  </div>

                  <!-- Modules within Opto22 -->
                  <div v-if="expandedOpto22Nodes.has(node.node_id)" class="tree-children">
                    <div v-for="module in [...node.modules].sort((a, b) => a.slot - b.slot)" :key="module.name" class="tree-module">
                      <div class="tree-header module-header" @click="toggleModule(module.name)">
                        <svg class="tree-arrow" :class="{ expanded: expandedModules.has(module.name) }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M8 5l8 7-8 7V5z"/>
                        </svg>
                        <input
                          type="checkbox"
                          :checked="isModuleFullySelected(module)"
                          :indeterminate="isModulePartiallySelected(module)"
                          @click.stop
                          @change="selectModuleChannels(module, ($event.target as HTMLInputElement).checked)"
                        />
                        <span class="tree-name">Slot {{ module.slot }}: {{ module.product_type }}</span>
                        <span class="tree-desc">{{ module.description }}</span>
                        <span class="tree-count">{{ module.channels?.length || 0 }} ch</span>
                      </div>

                      <!-- Channels within Module -->
                      <div v-if="expandedModules.has(module.name)" class="tree-children channel-list">
                        <div
                          v-for="channel in module.channels"
                          :key="channel.name"
                          class="tree-channel"
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name) }"
                          @click="toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.category">{{ channel.channel_type }}</span>
                          <span class="channel-desc">{{ channel.description }}</span>
                        </div>
                      </div>
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
            <button class="btn btn-secondary" @click="closeDiscoveryPanel">Cancel</button>
            <button class="btn btn-secondary" @click="scanDevices" :disabled="isScanning">
              {{ isScanning ? 'Discovering...' : 'Re-discover' }}
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
            <!-- Show type hint when on a specific tab -->
            <div v-if="activeTypeTab !== 'all'" class="type-hint-banner">
              Adding to: <strong>{{ channelTypeTabs.find(t => t.id === activeTypeTab)?.label }}</strong> channels
            </div>

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
                <option value="modbus_register">Modbus Register</option>
                <option value="modbus_coil">Modbus Coil</option>
              </select>
              <span v-if="activeTypeTab !== 'all'" class="form-hint">
                Pre-selected based on current view. Change if needed.
              </span>
            </div>

            <!-- Source Type Selection -->
            <div class="form-row">
              <label>Source Type</label>
              <select v-model="newChannelForm.source_type" class="source-select">
                <option value="cdaq">cDAQ (Local)</option>
                <option value="crio">cRIO (Remote)</option>
                <option value="opto22">Opto22 (Remote)</option>
              </select>
              <span class="form-hint">Hardware platform for this channel</span>
            </div>

            <!-- Node Selector (for remote sources) -->
            <div class="form-row" v-if="newChannelForm.source_type !== 'cdaq'">
              <label>Node</label>
              <select v-model="newChannelForm.node_id" class="node-select">
                <option value="" disabled>Select a node...</option>
                <option
                  v-for="node in getAvailableNodes(newChannelForm.source_type)"
                  :key="node.id"
                  :value="node.id"
                  :class="{ offline: node.status !== 'online' }"
                >
                  {{ node.name }} {{ node.status !== 'online' ? '(offline)' : '' }}
                </option>
              </select>
              <span class="form-hint" v-if="getAvailableNodes(newChannelForm.source_type).length === 0">
                No {{ newChannelForm.source_type === 'crio' ? 'cRIO' : 'Opto22' }} nodes discovered. Run Discovery first.
              </span>
              <span class="form-hint" v-else>
                Select target {{ newChannelForm.source_type === 'crio' ? 'cRIO' : 'Opto22' }} node
              </span>
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
              <label>
                Physical Channel
                <span v-if="isScanning" class="scanning-indicator">(scanning...)</span>
              </label>
              <!-- Show dropdown if discovery data available -->
              <template v-if="getAvailablePhysicalChannels().length > 0">
                <select v-model="newChannelForm.physical_channel" class="physical-channel-select">
                  <option value="">-- Select from discovered channels --</option>
                  <option
                    v-for="ch in getAvailablePhysicalChannels()"
                    :key="ch.value"
                    :value="ch.value"
                  >
                    {{ ch.label }}
                  </option>
                  <option value="__manual__">Enter manually...</option>
                </select>
                <!-- Manual entry shown when "Enter manually" selected -->
                <input
                  v-if="newChannelForm.physical_channel === '__manual__'"
                  type="text"
                  v-model="manualPhysicalChannel"
                  :placeholder="getPhysicalChannelHint(newChannelForm.source_type)"
                  class="manual-channel-input"
                />
              </template>
              <!-- Fallback to manual entry if no discovery data -->
              <template v-else>
                <input
                  type="text"
                  v-model="newChannelForm.physical_channel"
                  :placeholder="getPhysicalChannelHint(newChannelForm.source_type)"
                />
                <span class="form-hint" v-if="!isScanning">
                  No channels discovered.
                  <button class="btn-link" @click="mqtt.scanDevices()">Scan for hardware</button>
                </span>
              </template>
              <span class="form-hint" v-if="getAvailablePhysicalChannels().length > 0">
                {{ getAvailablePhysicalChannels().length }} channels available from discovery
              </span>
            </div>

            <!-- display_name removed - TAG is the only identifier -->

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
              <h4>System Architecture</h4>
              <div class="form-row">
                <label>Project Mode</label>
                <select v-model="systemSettingsForm.project_mode" class="mode-select">
                  <option value="cdaq">cDAQ (PC is controller)</option>
                  <option value="crio">cRIO (cRIO is PLC)</option>
                  <option value="opto22">Opto22 (groov EPIC is PLC)</option>
                </select>
                <span class="form-hint">
                  {{ systemSettingsForm.project_mode === 'cdaq'
                    ? 'PC handles all control logic locally'
                    : systemSettingsForm.project_mode === 'crio'
                      ? 'cRIO runs autonomously - PC is HMI only'
                      : 'groov EPIC/RIO runs autonomously - PC is HMI only' }}
                </span>
              </div>
            </div>

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
                <span class="info-label">Current Mode:</span>
                <span class="info-value" :class="{ 'mode-crio': store.status?.project_mode === 'crio' || store.status?.project_mode === 'opto22' }">
                  {{ store.status?.project_mode === 'crio' ? 'cRIO (PLC)'
                     : store.status?.project_mode === 'opto22' ? 'Opto22 (PLC)'
                     : 'cDAQ (Local)' }}
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

    <!-- Project Manager Dialog -->
    <Transition name="modal">
      <div v-if="showProjectManager" class="discovery-overlay" @click.self="showProjectManager = false">
        <div class="settings-dialog">
          <div class="discovery-header">
            <h3>Project Manager</h3>
            <button class="close-btn" @click="showProjectManager = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="settings-content">
            <!-- Current Project -->
            <div v-if="projectFiles.currentProject.value" class="current-project-banner">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
              <div>
                <strong>Current Project:</strong> {{ projectFiles.currentProject.value.replace('.json', '') }}
              </div>
            </div>
            <div v-else class="current-project-banner no-project">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              <div>No project loaded - start fresh or load an existing project</div>
            </div>

            <!-- New Project Button -->
            <div class="form-row">
              <button class="btn btn-primary" @click="startNewProject" style="width: 100%;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                Start New Project
              </button>
            </div>

            <!-- Available Projects -->
            <div class="form-row" style="margin-top: 24px;">
              <label>Available Projects</label>
              <div v-if="projectFiles.projects.value.length === 0" class="no-projects-message">
                No saved projects found. Create channels and click "Save" to create your first project.
              </div>
              <div v-else class="projects-list">
                <div
                  v-for="project in projectFiles.projects.value"
                  :key="project.filename"
                  class="project-item"
                  :class="{ active: project.filename === projectFiles.currentProject.value }"
                >
                  <div class="project-info">
                    <div class="project-name">{{ project.name }}</div>
                    <div class="project-meta">{{ project.modified }}</div>
                  </div>
                  <button
                    class="btn btn-secondary btn-sm"
                    @click="loadSelectedProject(project.filename)"
                    :disabled="project.filename === projectFiles.currentProject.value"
                  >
                    {{ project.filename === projectFiles.currentProject.value ? 'Current' : 'Load' }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showProjectManager = false">Close</button>
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

    <!-- Create Project Dialog -->
    <Transition name="modal">
      <div v-if="showCreateProjectDialog" class="discovery-overlay" @click.self="showCreateProjectDialog = false">
        <div class="save-as-dialog">
          <div class="discovery-header">
            <h3>Create New Project</h3>
            <button class="close-btn" @click="showCreateProjectDialog = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="save-as-content">
            <p class="dialog-message">No project is currently loaded. Create a new project to save your configuration.</p>
            <div class="form-row">
              <label>Project Name</label>
              <div class="filename-input">
                <input
                  type="text"
                  v-model="newProjectName"
                  placeholder="My Project"
                  @keyup.enter="createAndSaveProject"
                />
                <span class="extension">.json</span>
              </div>
              <span class="form-hint">Enter a name for your project</span>
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showCreateProjectDialog = false">Cancel</button>
            <button
              class="btn btn-primary"
              @click="createAndSaveProject"
              :disabled="!newProjectName.trim() || isSaving"
            >
              {{ isSaving ? 'Creating...' : 'Create & Save' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Safety Actions Modal -->
    <Transition name="modal">
      <div v-if="showSafetyActionsModal" class="discovery-overlay" @click.self="showSafetyActionsModal = false">
        <div class="safety-actions-dialog">
          <div class="discovery-header">
            <h3>Safety Actions (ISA-18.2)</h3>
            <button class="close-btn" @click="showSafetyActionsModal = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="safety-actions-content">
            <!-- Auto-Execute Toggle -->
            <div class="safety-auto-execute">
              <label>
                <input
                  type="checkbox"
                  :checked="safety.autoExecuteSafetyActions.value"
                  @change="safety.setAutoExecuteSafetyActions(($event.target as HTMLInputElement).checked)"
                />
                Auto-execute safety actions on alarm trigger
              </label>
              <span class="form-hint">When disabled, alarms will display but won't trigger automatic responses</span>
            </div>

            <!-- Actions List -->
            <div class="safety-actions-list" v-if="!editingSafetyAction">
              <div class="safety-actions-header">
                <h4>Configured Actions</h4>
                <button class="btn btn-primary btn-sm" @click="startNewSafetyAction">
                  + Add Action
                </button>
              </div>

              <div v-if="Object.keys(safety.safetyActions.value).length === 0" class="empty-state">
                No safety actions configured. Add one to link alarms to automatic responses.
              </div>

              <div v-else class="actions-table">
                <div
                  v-for="(action, actionId) in safety.safetyActions.value"
                  :key="actionId"
                  class="action-row"
                  :class="{ disabled: !action.enabled }"
                >
                  <div class="action-info">
                    <span class="action-name">{{ action.name }}</span>
                    <span class="action-type">{{ action.type }}</span>
                    <span v-if="action.description" class="action-desc">{{ action.description }}</span>
                  </div>
                  <div class="action-controls">
                    <button class="btn btn-icon" @click="editSafetyAction(actionId as string)" title="Edit">
                      ✏️
                    </button>
                    <button class="btn btn-icon btn-danger" @click="deleteSafetyAction(actionId as string)" title="Delete">
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Edit/Add Form -->
            <div class="safety-action-form" v-if="editingSafetyAction">
              <h4>{{ isNewSafetyAction ? 'New Safety Action' : 'Edit Safety Action' }}</h4>

              <div class="form-row">
                <label>Name</label>
                <input type="text" v-model="editingSafetyAction.name" placeholder="e.g., Emergency Shutdown" />
              </div>

              <div class="form-row">
                <label>Description</label>
                <input type="text" v-model="editingSafetyAction.description" placeholder="Optional description" />
              </div>

              <div class="form-row">
                <label>Action Type</label>
                <select v-model="editingSafetyAction.type">
                  <option value="trip_system">Trip System (all outputs to safe state)</option>
                  <option value="stop_session">Stop Test Session</option>
                  <option value="stop_recording">Stop Recording</option>
                  <option value="set_output_safe">Set Specific Outputs to Safe State</option>
                  <option value="run_sequence">Run Safety Sequence</option>
                  <option value="custom">Custom MQTT Action</option>
                </select>
              </div>

              <!-- Conditional fields based on type -->
              <template v-if="editingSafetyAction.type === 'set_output_safe'">
                <div class="form-row">
                  <label>Output Channels</label>
                  <div class="checkbox-list">
                    <label v-for="ch in outputChannels" :key="ch.name" class="checkbox-item">
                      <input
                        type="checkbox"
                        :value="ch.name"
                        v-model="editingSafetyAction.outputChannels"
                      />
                      {{ ch.displayName }} ({{ ch.type }})
                    </label>
                  </div>
                </div>
                <div class="form-row-group">
                  <div class="form-row half">
                    <label>Digital Safe Value</label>
                    <select v-model.number="editingSafetyAction.safeValue">
                      <option :value="0">OFF (0)</option>
                      <option :value="1">ON (1)</option>
                    </select>
                  </div>
                  <div class="form-row half">
                    <label>Analog Safe Value</label>
                    <input type="number" v-model.number="editingSafetyAction.analogSafeValue" step="0.1" />
                  </div>
                </div>
              </template>

              <template v-if="editingSafetyAction.type === 'run_sequence'">
                <div class="form-row">
                  <label>Sequence ID</label>
                  <input type="text" v-model="editingSafetyAction.sequenceId" placeholder="sequence_id" />
                </div>
              </template>

              <template v-if="editingSafetyAction.type === 'custom'">
                <div class="form-row">
                  <label>MQTT Topic</label>
                  <input type="text" v-model="editingSafetyAction.mqttTopic" placeholder="nisystem/custom/action" />
                </div>
                <div class="form-row">
                  <label>MQTT Payload (JSON)</label>
                  <textarea v-model="editingSafetyAction.mqttPayload" placeholder="{}" rows="3"></textarea>
                </div>
              </template>

              <div class="form-row checkbox-row">
                <label>
                  <input type="checkbox" v-model="editingSafetyAction.enabled" />
                  Enabled
                </label>
              </div>

              <div class="form-actions">
                <button class="btn btn-secondary" @click="cancelEditSafetyAction">Cancel</button>
                <button class="btn btn-primary" @click="saveSafetyAction">
                  {{ isNewSafetyAction ? 'Create' : 'Save' }}
                </button>
              </div>
            </div>
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

/* Channel Type Tabs Row (tabs + status) */
.type-tabs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.type-tabs {
  display: flex;
  gap: 2px;
  overflow-x: auto;
}

/* Compact Status Bar (right side of tabs) */
.status-compact {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.65rem;
}

.status-item {
  padding: 3px 8px;
  border-radius: 3px;
  font-weight: 500;
}

.status-item.channels {
  background: #1e293b;
  color: #94a3b8;
}

.status-item.mqtt {
  background: #7f1d1d;
  color: #fca5a5;
}

.status-item.mqtt.connected {
  background: #14532d;
  color: #86efac;
}

.theme-toggle-small {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}

.theme-toggle-small:hover {
  background: #334155;
  color: #e2e8f0;
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

/* Source Badge - indicates which node a channel comes from */
.source-badge {
  margin-left: 6px;
  padding: 1px 4px;
  font-size: 0.6rem;
  font-weight: 500;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.source-badge.crio {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.source-badge.opto22 {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.3);
}

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

/* Error status styles for channel values */
.col-value.stale .value {
  color: #666;
}

.col-value.disconnected .value {
  color: #f97316;
  font-style: italic;
}

.col-value.open-tc .value {
  color: #dc2626;
  font-style: italic;
}

.col-value.overflow .value {
  color: #a855f7;
  font-style: italic;
}

/* Row-level error indicators */
.channel-row.stale {
  background: rgba(107, 114, 128, 0.1);
}

.channel-row.disconnected {
  background: rgba(249, 115, 22, 0.1);
  border-left: 3px solid #f97316;
}

.channel-row.open-tc {
  background: rgba(220, 38, 38, 0.1);
  border-left: 3px solid #dc2626;
}

.channel-row.overflow {
  background: rgba(168, 85, 247, 0.1);
  border-left: 3px solid #a855f7;
}

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

.inline-input.narrow {
  width: 60px;
  text-align: right;
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

/* Add Channel Hint Row (ALL tab) */
.add-channel-hint-row td {
  border-bottom: none;
}

.add-channel-hint {
  padding: 10px 0;
  color: #555;
  font-size: 0.8rem;
  font-style: italic;
  text-align: center;
}

/* Simulation Mode Banner */
.sim-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 16px;
  background: #451a03;
  color: #fbbf24;
  font-size: 0.75rem;
  font-weight: 500;
}

.sim-icon {
  font-size: 0.85rem;
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
  gap: 8px;
  flex-wrap: wrap;
}

.right-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.7rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.action-btn.icon-btn {
  padding: 5px 8px;
}

.action-btn svg {
  flex-shrink: 0;
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

/* Primary buttons (green) - constructive actions: Add, Save */
.action-btn.primary {
  background: #166534;
  border-color: #22c55e;
  color: #fff;
}

.action-btn.primary:hover:not(:disabled) {
  background: #15803d;
  border-color: #4ade80;
}

.action-btn.primary.dirty {
  animation: pulse-dirty 1.5s ease-in-out infinite;
}

@keyframes pulse-dirty {
  0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); }
  50% { box-shadow: 0 0 8px 2px rgba(34, 197, 94, 0.6); }
}

/* Accent buttons (blue) - send to hardware: Apply */
.action-btn.accent {
  background: #1e40af;
  border-color: #3b82f6;
  color: #fff;
}

.action-btn.accent:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #60a5fa;
}

/* Out-of-sync indicator for Push button when cRIO config doesn't match */
.action-btn.out-of-sync {
  border-color: #f59e0b;
  animation: pulse-warning 2s infinite;
}

.action-btn.out-of-sync:hover:not(:disabled) {
  border-color: #fbbf24;
}

.sync-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f59e0b;
  color: #000;
  border-radius: 50%;
  width: 14px;
  height: 14px;
  font-size: 10px;
  font-weight: bold;
  margin-left: 4px;
}

@keyframes pulse-warning {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(245, 158, 11, 0); }
}

/* Warning buttons (orange) - safety/attention: Safety */
.action-btn.warning {
  background: #78350f;
  border-color: #f59e0b;
  color: #fbbf24;
}

.action-btn.warning:hover:not(:disabled) {
  background: #92400e;
  border-color: #fbbf24;
  color: #fef3c7;
}

/* Active state for toggle buttons */
.action-btn.active {
  background: #3b82f6;
  color: #fff;
  border-color: #60a5fa;
}

.action-btn.active:hover:not(:disabled) {
  background: #2563eb;
}

/* No permission state */
.action-btn.no-permission {
  opacity: 0.6;
  border-color: #6b7280;
}

.action-btn.no-permission:hover {
  border-color: #f59e0b;
  color: #f59e0b;
}

.lock-badge {
  font-size: 0.7rem;
  margin-left: 4px;
}

.project-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 3px;
  background: #1e3a5f;
  color: #60a5fa;
  text-transform: none;
  letter-spacing: 0.3px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-indicator svg {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

.sim-mode-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 3px;
  background: #78350f;
  color: #fbbf24;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sim-mode-indicator svg {
  width: 14px;
  height: 14px;
  fill: currentColor;
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

/* Quick Populate Banner */
.quick-populate-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 100%);
  border: 1px solid #3b82f6;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}

.quick-populate-banner .banner-text {
  color: #e0e0e0;
  font-size: 0.85rem;
}

.quick-populate-banner .banner-text strong {
  color: #60a5fa;
}

.btn-success {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #10b981;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-success:hover {
  background: #059669;
}

.smart-name-preview {
  color: #10b981;
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
  margin-left: 8px;
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

/* Simulation Mode Banner */
.simulation-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(251, 191, 36, 0.15);
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: 4px;
  color: #fbbf24;
  font-size: 0.8rem;
  margin-bottom: 12px;
}

/* Tree View Styles */
.discovery-tree {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tree-chassis {
  background: #1a1a2e;
  border-radius: 6px;
  overflow: hidden;
}

.tree-module {
  background: #1e1e32;
  border-radius: 4px;
  margin: 2px 0;
}

.tree-module.standalone {
  background: #1a1a2e;
  border-radius: 6px;
}

.tree-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.tree-header:hover {
  background: rgba(255, 255, 255, 0.05);
}

.chassis-header {
  background: #252540;
}

/* cRIO node styling - distinct from cDAQ chassis */
.tree-crio {
  background: #1a2e1a;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #2a4a2a;
}

.crio-header {
  background: #253525;
}

.crio-header:hover {
  background: #2a402a;
}

.device-badge {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.device-badge.crio {
  background: #166534;
  color: #86efac;
}

.device-badge.cdaq {
  background: #1e40af;
  color: #93c5fd;
}

.crio-status {
  font-size: 0.7rem;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
}

.crio-status.online {
  background: #166534;
  color: #86efac;
}

.crio-status.offline {
  background: #991b1b;
  color: #fca5a5;
}

.crio-status.unknown {
  background: #854d0e;
  color: #fde047;
}

.crio-info-bar {
  display: flex;
  gap: 16px;
  padding: 6px 12px 6px 44px;
  background: #1a2a1a;
  font-size: 0.75rem;
  color: #888;
  border-top: 1px solid #2a4a2a;
}

.crio-ip {
  font-family: monospace;
  color: #60a5fa;
}

.crio-serial {
  color: #888;
}

.crio-last-seen {
  color: #666;
}

/* Opto22 node styling - distinct orange/amber theme */
.tree-opto22 {
  background: #2e2a1a;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #4a3a2a;
}

.opto22-header {
  background: #352f25;
}

.opto22-header:hover {
  background: #403520;
}

.device-badge.opto22 {
  background: #92400e;
  color: #fcd34d;
}

.opto22-status {
  font-size: 0.7rem;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
}

.opto22-status.online {
  background: #166534;
  color: #86efac;
}

.opto22-status.offline {
  background: #991b1b;
  color: #fca5a5;
}

.opto22-status.unknown {
  background: #854d0e;
  color: #fde047;
}

.opto22-info-bar {
  display: flex;
  gap: 16px;
  padding: 6px 12px 6px 44px;
  background: #2a261a;
  font-size: 0.75rem;
  color: #888;
  border-top: 1px solid #4a3a2a;
}

.opto22-ip {
  font-family: monospace;
  color: #fbbf24;
}

.opto22-serial {
  color: #888;
}

.opto22-last-seen {
  color: #666;
}

.btn-push-config {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #166534;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  margin-left: auto;
  transition: background 0.2s;
}

.btn-push-config:hover:not(:disabled) {
  background: #15803d;
}

.btn-push-config:disabled {
  background: #374151;
  color: #6b7280;
  cursor: not-allowed;
}

.module-header {
  padding-left: 24px;
}

.tree-arrow {
  color: #666;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.tree-arrow.expanded {
  transform: rotate(90deg);
}

.tree-icon {
  color: #60a5fa;
  flex-shrink: 0;
}

.tree-name {
  font-weight: 600;
  color: #fff;
  font-size: 0.85rem;
}

.tree-type {
  font-size: 0.75rem;
  color: #888;
  padding: 2px 6px;
  background: #2a2a4a;
  border-radius: 3px;
}

.tree-desc {
  font-size: 0.75rem;
  color: #666;
  flex: 1;
}

.tree-count {
  font-size: 0.7rem;
  color: #888;
  background: #2a2a4a;
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: auto;
}

.tree-children {
  padding-left: 16px;
}

.tree-children.channel-list {
  padding: 4px 8px 8px 32px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tree-channel {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
  background: rgba(255, 255, 255, 0.02);
}

.tree-channel:hover {
  background: rgba(255, 255, 255, 0.05);
}

.tree-channel.selected {
  background: rgba(59, 130, 246, 0.15);
  border-left: 2px solid #3b82f6;
}

.tree-channel input[type="checkbox"] {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.tree-channel .channel-name {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #ddd;
  min-width: 140px;
}

.tree-channel .channel-desc {
  font-size: 0.7rem;
  color: #666;
  flex: 1;
}

.tree-header input[type="checkbox"] {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

/* Type badge colors by category */
.type-badge.thermocouple { background: #dc2626; color: #fff; }
.type-badge.rtd { background: #ea580c; color: #fff; }
.type-badge.voltage { background: #16a34a; color: #fff; }
.type-badge.current { background: #2563eb; color: #fff; }
.type-badge.strain { background: #7c3aed; color: #fff; }
.type-badge.iepe { background: #db2777; color: #fff; }
.type-badge.digital_input { background: #0891b2; color: #fff; }
.type-badge.digital_output { background: #059669; color: #fff; }
.type-badge.analog_output { background: #d97706; color: #fff; }
.type-badge.counter { background: #7c3aed; color: #fff; }

/* Toolbar separator */
.discovery-actions .separator {
  color: #444;
  margin: 0 4px;
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

/* Alarm column styling */
.col-alarm {
  text-align: center;
  width: 50px;
  min-width: 50px;
}

.channel-table th.col-alarm {
  background: #0f0f1a;
}

.alarm-btn {
  position: relative;
  background: transparent;
  border: 1px solid transparent;
  color: #555;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.alarm-btn:hover {
  background: #1a1a2e;
  color: #888;
}

/* Alarm disabled state */
.alarm-btn.disabled {
  color: #444;
}

.alarm-btn.disabled:hover {
  border-color: #666;
  color: #888;
}

/* Alarm enabled state - green glow */
.alarm-btn.enabled {
  color: #22c55e;
  border-color: #16a34a;
  background: rgba(22, 163, 74, 0.1);
}

.alarm-btn.enabled:hover {
  background: rgba(22, 163, 74, 0.2);
}

/* Active warning - yellow */
.alarm-btn.active-warning {
  color: #eab308;
  border-color: #ca8a04;
  background: rgba(234, 179, 8, 0.15);
  animation: pulse-warning 1.5s infinite;
}

/* Active alarm - red */
.alarm-btn.active-alarm {
  color: #ef4444;
  border-color: #dc2626;
  background: rgba(239, 68, 68, 0.15);
  animation: pulse-alarm 1s infinite;
}

@keyframes pulse-warning {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

@keyframes pulse-alarm {
  0%, 100% { opacity: 1; box-shadow: 0 0 8px rgba(239, 68, 68, 0.5); }
  50% { opacity: 0.8; box-shadow: 0 0 12px rgba(239, 68, 68, 0.8); }
}

/* Small dot indicator for enabled alarms */
.alarm-indicator {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 6px;
  height: 6px;
  background: #22c55e;
  border-radius: 50%;
}

.alarm-btn.active-warning .alarm-indicator {
  background: #eab308;
}

.alarm-btn.active-alarm .alarm-indicator {
  background: #ef4444;
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

.form-hint.alarm-hint {
  text-align: center;
  margin: 8px 0 12px 0;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  color: #888;
}

/* Physical Channel Select in Add Channel Modal */
.scanning-indicator {
  font-size: 0.75rem;
  color: #3b82f6;
  font-weight: normal;
  margin-left: 6px;
}

.physical-channel-select {
  width: 100%;
  padding: 8px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #e2e8f0;
  font-size: 0.85rem;
}

.physical-channel-select:focus {
  border-color: #3b82f6;
  outline: none;
}

.manual-channel-input {
  margin-top: 8px;
  width: 100%;
  padding: 8px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #e2e8f0;
  font-size: 0.85rem;
}

.manual-channel-input:focus {
  border-color: #3b82f6;
  outline: none;
}

.form-hint .btn-link {
  background: none;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  padding: 0;
  font-size: inherit;
  text-decoration: underline;
}

.form-hint .btn-link:hover {
  color: #60a5fa;
}

/* Type hint banner in Add Channel modal */
.type-hint-banner {
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 0.85rem;
  color: #94a3b8;
}

.type-hint-banner strong {
  color: #3b82f6;
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

.info-row .info-value.mode-crio {
  color: #f59e0b;
  font-weight: 500;
}

.mode-select {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #e5e5e5;
  font-size: 0.85rem;
}

.mode-select:focus {
  outline: none;
  border-color: #3b82f6;
}

/* Source and Node selectors in Add Channel modal */
.source-select,
.node-select {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #e5e5e5;
  font-size: 0.85rem;
}

.source-select:focus,
.node-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.node-select option.offline {
  color: #888;
  font-style: italic;
}

/* Safety Actions Dialog */
.safety-actions-dialog {
  width: 550px;
  max-height: 85vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.safety-actions-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.safety-auto-execute {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 16px;
}

.safety-auto-execute label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  font-size: 0.9rem;
}

.safety-actions-list {
  margin-top: 16px;
}

.safety-actions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.safety-actions-header h4 {
  margin: 0;
  color: #60a5fa;
  font-size: 0.85rem;
  text-transform: uppercase;
}

.actions-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 12px;
}

.action-row.disabled {
  opacity: 0.5;
}

.action-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.action-name {
  color: #fff;
  font-weight: 500;
  font-size: 0.9rem;
}

.action-type {
  color: #60a5fa;
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
}

.action-desc {
  color: #888;
  font-size: 0.8rem;
}

.action-controls {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  border: 1px solid #2a2a4a;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: #2a2a4a;
}

.btn-icon.btn-danger:hover {
  background: #dc2626;
  border-color: #dc2626;
}

.safety-action-form {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 16px;
}

.safety-action-form h4 {
  margin: 0 0 16px;
  color: #60a5fa;
  font-size: 0.85rem;
  text-transform: uppercase;
  padding-bottom: 8px;
  border-bottom: 1px solid #2a2a4a;
}

.checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 150px;
  overflow-y: auto;
  background: #0f0f1a;
  padding: 8px;
  border-radius: 4px;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  font-size: 0.85rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #2a2a4a;
}

.empty-state {
  color: #888;
  font-size: 0.85rem;
  text-align: center;
  padding: 24px;
  background: #1a1a2e;
  border-radius: 4px;
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

.dialog-message {
  color: #94a3b8;
  font-size: 0.85rem;
  margin-bottom: 16px;
  line-height: 1.5;
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

/* Project Manager Styles */
.current-project-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid #22c55e;
  border-radius: 6px;
  color: #4ade80;
  margin-bottom: 24px;
}

.current-project-banner.no-project {
  background: rgba(251, 191, 36, 0.1);
  border-color: #fbbf24;
  color: #fcd34d;
}

.current-project-banner svg {
  flex-shrink: 0;
}

.no-projects-message {
  padding: 24px;
  text-align: center;
  color: #888;
  font-size: 0.9rem;
  background: rgba(75, 85, 99, 0.1);
  border-radius: 6px;
  border: 1px dashed #4b5563;
}

.projects-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.project-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  transition: all 0.2s;
}

.project-item:hover {
  background: #242442;
  border-color: #3a3a5a;
}

.project-item.active {
  background: rgba(59, 130, 246, 0.1);
  border-color: #3b82f6;
}

.project-info {
  flex: 1;
  min-width: 0;
}

.project-name {
  font-weight: 600;
  color: #fff;
  font-size: 0.95rem;
  margin-bottom: 4px;
}

.project-meta {
  font-size: 0.8rem;
  color: #888;
}

.btn-sm {
  padding: 4px 12px;
  font-size: 0.8rem;
}
</style>
