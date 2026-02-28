<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { ChannelType, ChannelConfig, NotificationSettings, NotificationTriggerRules, AlarmSeverityLevel } from '../types'
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
import { useAuth } from '../composables/useAuth'
import ModbusDeviceConfig from './ModbusDeviceConfig.vue'
import RestApiDeviceConfig from './RestApiDeviceConfig.vue'
import OpcUaDeviceConfig from './OpcUaDeviceConfig.vue'
import EtherNetIPDeviceConfig from './EtherNetIPDeviceConfig.vue'
import CompactFieldpointDeviceConfig from './CompactFieldpointDeviceConfig.vue'
import GcNodeDeviceConfig from './GcNodeDeviceConfig.vue'

const store = useDashboardStore()
const tagDeps = useTagDependencies()
const backendScripts = useBackendScripts()
const { isAdmin } = useAuth()

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
  alt_index_start?: number   // For combo modules: channel index where alt type starts (e.g., 8 for NI 9207 ai8+)
}

const NI_MODULE_TYPES: Record<string, ModuleTypeInfo> = {
  // ===== DIGITAL INPUT MODULES =====
  'NI 9375': { channel_type: 'digital_input', category: 'digital' },   // 16-ch DI + 16-ch DO combo
  'NI 9411': { channel_type: 'digital_input', category: 'digital' },   // 6-ch DI, differential
  'NI 9421': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, 24V sinking
  'NI 9422': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, 24-60V sinking
  'NI 9423': { channel_type: 'digital_input', category: 'digital' },   // 8-ch DI, TTL
  'NI 9425': { channel_type: 'digital_input', category: 'digital' },   // 32-ch DI, 24V sourcing (Spring)
  'NI 9426': { channel_type: 'digital_input', category: 'digital' },   // 32-ch DI, 24V sinking
  'NI 9435': { channel_type: 'digital_input', category: 'digital' },   // 4-ch universal DI

  // ===== DIGITAL OUTPUT MODULES =====
  'NI 9470': { channel_type: 'digital_output', category: 'digital' },  // 8-ch DO, 24V sourcing
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
  'NI 9201': { channel_type: 'voltage_input', category: 'voltage' },   // 8-ch ±10V
  'NI 9202': { channel_type: 'voltage_input', category: 'voltage' },   // 16-ch ±10V
  'NI 9205': { channel_type: 'voltage_input', category: 'voltage' },   // 32-ch ±10V
  'NI 9206': { channel_type: 'voltage_input', category: 'voltage' },   // 16-ch simultaneous ±10V
  'NI 9215': { channel_type: 'voltage_input', category: 'voltage' },   // 4-ch simultaneous ±10V
  'NI 9220': { channel_type: 'voltage_input', category: 'voltage' },   // 16-ch ±10V
  'NI 9221': { channel_type: 'voltage_input', category: 'voltage' },   // 8-ch ±60V
  'NI 9222': { channel_type: 'voltage_input', category: 'voltage' },   // 4-ch simultaneous ±10V
  'NI 9223': { channel_type: 'voltage_input', category: 'voltage' },   // 4-ch high-speed ±10V
  'NI 9229': { channel_type: 'voltage_input', category: 'voltage' },   // 4-ch ±60V isolated
  'NI 9239': { channel_type: 'voltage_input', category: 'voltage' },   // 4-ch ±10V universal

  // ===== ANALOG INPUT - CURRENT =====
  'NI 9203': { channel_type: 'current_input', category: 'current' },   // 8-ch ±20mA
  'NI 9208': { channel_type: 'current_input', category: 'current' },   // 16-ch ±20mA
  'NI 9227': { channel_type: 'current_input', category: 'current' },   // 8-ch ±20mA
  'NI 9246': { channel_type: 'current_input', category: 'current' },   // 3-phase current
  'NI 9247': { channel_type: 'current_input', category: 'current' },   // 3-phase current
  'NI 9253': { channel_type: 'current_input', category: 'current' },   // 8-ch ±20mA

  // ===== ANALOG INPUT - THERMOCOUPLE =====
  'NI 9210': { channel_type: 'thermocouple', category: 'thermocouple' }, // 4-ch TC
  'NI 9211': { channel_type: 'thermocouple', category: 'thermocouple' }, // 4-ch TC
  'NI 9212': { channel_type: 'thermocouple', category: 'thermocouple' }, // 8-ch TC
  'NI 9213': { channel_type: 'thermocouple', category: 'thermocouple' }, // 16-ch TC
  'NI 9214': { channel_type: 'thermocouple', category: 'thermocouple' }, // 16-ch isothermal TC

  // ===== ANALOG INPUT - RTD =====
  'NI 9216': { channel_type: 'rtd', category: 'rtd' },                 // 8-ch RTD
  'NI 9217': { channel_type: 'rtd', category: 'rtd' },                 // 4-ch RTD
  'NI 9226': { channel_type: 'rtd', category: 'rtd' },                 // 8-ch RTD

  // ===== ANALOG INPUT - STRAIN/BRIDGE =====
  'NI 9235': { channel_type: 'strain_input', category: 'strain' },     // 8-ch quarter-bridge
  'NI 9236': { channel_type: 'strain_input', category: 'strain' },     // 8-ch quarter-bridge
  'NI 9237': { channel_type: 'bridge_input', category: 'bridge' },     // 4-ch bridge

  // ===== ANALOG INPUT - IEPE/ACCELEROMETER =====
  'NI 9230': { channel_type: 'iepe_input', category: 'iepe' },         // 3-ch IEPE
  'NI 9231': { channel_type: 'iepe_input', category: 'iepe' },         // 8-ch IEPE
  'NI 9232': { channel_type: 'iepe_input', category: 'iepe' },         // 3-ch IEPE
  'NI 9233': { channel_type: 'iepe_input', category: 'iepe' },         // 4-ch IEPE
  'NI 9234': { channel_type: 'iepe_input', category: 'iepe' },         // 4-ch IEPE
  'NI 9250': { channel_type: 'iepe_input', category: 'iepe' },         // 2-ch IEPE
  'NI 9251': { channel_type: 'iepe_input', category: 'iepe' },         // 2-ch IEPE

  // ===== ANALOG INPUT - UNIVERSAL/MULTI =====
  'NI 9219': { channel_type: 'bridge_input', category: 'bridge' },     // 4-ch universal AI

  // ===== ANALOG OUTPUT - VOLTAGE =====
  'NI 9260': { channel_type: 'voltage_output', category: 'voltage' },   // 4-ch ±10V
  'NI 9262': { channel_type: 'voltage_output', category: 'voltage' },   // 2-ch ±100V
  'NI 9263': { channel_type: 'voltage_output', category: 'voltage' },   // 4-ch ±10V
  'NI 9264': { channel_type: 'voltage_output', category: 'voltage' },   // 16-ch ±10V
  'NI 9269': { channel_type: 'voltage_output', category: 'voltage' },   // 4-ch isolated ±10V

  // ===== ANALOG OUTPUT - CURRENT =====
  'NI 9265': { channel_type: 'current_output', category: 'current' },  // 4-ch 0-20mA
  'NI 9266': { channel_type: 'current_output', category: 'current' },  // 8-ch 0-20mA

  // ===== RELAY MODULES =====
  // Relay modules are digital outputs - NI-DAQmx treats them as DO channels
  'NI 9481': { channel_type: 'digital_output', category: 'relay' },    // 4-ch SPST relay
  'NI 9482': { channel_type: 'digital_output', category: 'relay' },    // 4-ch SPDT relay
  'NI 9485': { channel_type: 'digital_output', category: 'relay' },    // 8-ch SSR

  // ===== COUNTER MODULES =====
  'NI 9361': { channel_type: 'counter_input', category: 'counter' },   // 8-ch counter

  // ===== COMBO MODULES =====
  // NI 9207: 8 voltage + 8 current inputs (ai0-ai7 = voltage, ai8-ai15 = current)
  'NI 9207': {
    channel_type: 'voltage_input',
    category: 'voltage',
    alt_channel_type: 'current_input',
    alt_category: 'current',
    alt_index_start: 8
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
  if (channelName) {
    // Method 1: Split by channel prefix (e.g., "ai" vs "ci")
    if (moduleInfo.alt_prefix) {
      const channelMatch = channelName.match(/\/([a-z]+)\d+$/i)
      if (channelMatch && channelMatch[1]!.toLowerCase() === moduleInfo.alt_prefix.toLowerCase()) {
        return {
          channel_type: moduleInfo.alt_channel_type || moduleInfo.channel_type,
          category: moduleInfo.alt_category || moduleInfo.category
        }
      }
    }
    // Method 2: Split by channel index (e.g., NI 9207: ai0-ai7 = voltage, ai8-ai15 = current)
    if (moduleInfo.alt_index_start != null) {
      const indexMatch = channelName.match(/(\d+)$/)
      if (indexMatch && parseInt(indexMatch[1]!) >= moduleInfo.alt_index_start) {
        return {
          channel_type: moduleInfo.alt_channel_type || moduleInfo.channel_type,
          category: moduleInfo.alt_category || moduleInfo.category
        }
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
const isPopulating = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)

// Permission-based edit control (injected from App.vue)
const hasEditPermission = inject<{ value: boolean }>('canEditConfig', ref(true))
const showLoginDialog = inject<() => void>('showLoginDialog', () => {})

// Edit mode - only allow editing when explicitly enabled, has permission, and not acquiring
const editMode = ref(false)
const canEdit = computed(() => editMode.value && hasEditPermission.value && !store.isAcquiring)

// cRIO node IDs actually referenced by channels in this project
const referencedCrioNodeIds = computed(() => {
  const ids = new Set<string>()
  for (const ch of Object.values(store.channels)) {
    if (ch.source_type === 'crio' && ch.node_id) {
      ids.add(ch.node_id)
    }
  }
  return ids
})

// cRIO sync indicator - true if a referenced cRIO is out of sync
const hasCrioOutOfSync = computed(() => {
  if (referencedCrioNodeIds.value.size === 0 || store.status?.simulation_mode) return false
  const syncStatus = mqtt.crioSyncStatus.value
  for (const nodeId of referencedCrioNodeIds.value) {
    if (syncStatus[nodeId] === false) return true
  }
  return false
})

// Recompute local config hashes for each cRIO node when channels change.
// This lets the Push button detect local edits that haven't been pushed yet.
watch(
  () => JSON.stringify(store.channels),
  () => {
    if (referencedCrioNodeIds.value.size === 0) return

    // Build the same config payload shape that autoPushToRemoteNodes sends
    const channelConfigs = Object.values(store.channels || {})
    const configPayload = {
      channels: channelConfigs,
      scan_rate_hz: store.status?.scan_rate_hz || 4,
      publish_rate_hz: store.status?.publish_rate_hz || 4
    }
    const hash = mqtt.hashConfig(configPayload)

    // Update local hash for every referenced cRIO node
    for (const nodeId of referencedCrioNodeIds.value) {
      mqtt.updateLocalCrioHash(nodeId, hash)
    }
  },
  { immediate: true }
)

// Validation report
interface ValidationIssue {
  channel: string
  severity: 'error' | 'warning' | 'info'
  category: string
  message: string
  fix?: string  // Recommended fix action
}

interface ValidationReport {
  timestamp: string
  totalChannels: number
  validChannels: number
  issues: ValidationIssue[]
}

const showValidationModal = ref(false)
const validationReport = ref<ValidationReport | null>(null)
const isValidating = ref(false)

// Import preview
interface ImportAnalysis {
  newChannels: string[]
  overwriteChannels: string[]
  physicalChannelConflicts: Array<{channel: string, physicalChannel: string, conflictsWith: string[]}>
  totalChannels: number
  projectData: any
  file: File
}

const showImportPreview = ref(false)
const importAnalysis = ref<ImportAnalysis | null>(null)

// cRIO connection status - only for cRIO nodes referenced by project channels
// Hidden in simulation mode (no real hardware to track)
const crioStatus = computed(() => {
  const referenced = referencedCrioNodeIds.value
  if (referenced.size === 0 || store.status?.simulation_mode) {
    return { state: 'none' as const, message: '', details: '' }
  }

  const nodes = mqtt.getNodeList()
  const crioNodes = nodes.filter(n => referenced.has(n.nodeId))

  // Referenced cRIO nodes that haven't been discovered yet count as offline
  const discoveredIds = new Set(crioNodes.map(n => n.nodeId))
  const missingNodes = [...referenced].filter(id => !discoveredIds.has(id))

  // Check for offline nodes (no heartbeat in last 10 seconds)
  const now = Date.now()
  const offlineDiscovered = crioNodes.filter(n => !n.lastSeen || (now - n.lastSeen) > 10000)
  const totalOffline = offlineDiscovered.length + missingNodes.length

  if (totalOffline > 0) {
    const offlineIds = [...offlineDiscovered.map(n => n.nodeId), ...missingNodes]
    return {
      state: 'offline' as const,
      message: `${totalOffline} cRIO offline`,
      details: offlineIds.join(', ')
    }
  }

  // Check for out of sync nodes
  const syncStatus = mqtt.crioSyncStatus.value
  const outOfSyncNodes = crioNodes.filter(n => syncStatus[n.nodeId] === false)

  if (outOfSyncNodes.length > 0) {
    return {
      state: 'out-of-sync' as const,
      message: `${outOfSyncNodes.length} cRIO out of sync`,
      details: outOfSyncNodes.map(n => n.nodeId).join(', ')
    }
  }

  return {
    state: 'synced' as const,
    message: `${crioNodes.length} cRIO synced`,
    details: crioNodes.map(n => n.nodeId).join(', ')
  }
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

  try {
    // Read and parse the file
    const text = await file.text()
    const projectData = JSON.parse(text)

    // Analyze the import
    const analysis = analyzeImport(projectData, file)
    importAnalysis.value = analysis

    // Show preview modal
    showImportPreview.value = true
  } catch (e: any) {
    showFeedback('error', `Failed to read project file: ${e.message}`)
  }

  // Reset input so same file can be selected again
  input.value = ''
}

function analyzeImport(projectData: any, file: File): ImportAnalysis {
  // Import replaces the entire project — no conflict analysis against current config needed
  const importChannels = projectData.channels || {}
  const totalChannels = Object.keys(importChannels).length

  return {
    newChannels: Object.keys(importChannels),
    overwriteChannels: [],
    physicalChannelConflicts: [],
    totalChannels,
    projectData,
    file
  }
}

async function confirmImport() {
  if (!importAnalysis.value) return

  // Auto-export current config as backup before importing
  try {
    await projectManager.downloadProject(store.systemName)
    showFeedback('info', 'Created backup before import')
  } catch (e) {
    console.warn('Failed to create backup:', e)
  }

  // Proceed with import
  const result = await projectManager.loadProjectFromFile(importAnalysis.value.file)
  if (result.success) {
    showFeedback('success', result.message)
  } else {
    showFeedback('error', result.message)
  }

  // Close preview
  showImportPreview.value = false
  importAnalysis.value = null
}

function cancelImport() {
  showImportPreview.value = false
  importAnalysis.value = null
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
function getAvailablePhysicalChannels(): Array<{value: string, label: string, type: string, inUse: boolean}> {
  const sourceType = newChannelForm.value.source_type
  const nodeId = newChannelForm.value.node_id
  const channels: Array<{value: string, label: string, type: string, inUse: boolean}> = []

  // Build map of physical channels already assigned in current config
  const usedChannels = new Map<string, string>() // physical_channel -> tag_name
  for (const [tagName, config] of Object.entries(store.channels)) {
    if (config.physical_channel) {
      usedChannels.set(config.physical_channel, tagName)
    }
  }

  if (sourceType === 'cdaq') {
    // cDAQ: get channels from chassis/modules
    if (discoveryResult.value?.chassis) {
      for (const chassis of discoveryResult.value.chassis) {
        for (const module of chassis.modules || []) {
          for (const ch of module.channels || []) {
            const assignedTo = usedChannels.get(ch.name)
            const usageLabel = assignedTo ? ` [USED BY: ${assignedTo}]` : ''
            const chType = ch.channel_type || ch.type || ch.category || ''
            channels.push({
              value: ch.name,
              label: `${ch.name} (${chType})${usageLabel}`,
              type: chType,
              inUse: !!assignedTo
            })
          }
        }
      }
    }
    // Also check standalone devices
    if (discoveryResult.value?.standalone_devices) {
      for (const device of discoveryResult.value.standalone_devices) {
        for (const ch of device.channels || []) {
          const assignedTo = usedChannels.get(ch.name)
          const usageLabel = assignedTo ? ` [USED BY: ${assignedTo}]` : ''
          const chType = ch.channel_type || ch.type || ch.category || ''
          channels.push({
            value: ch.name,
            label: `${ch.name} (${chType})${usageLabel}`,
            type: chType,
            inUse: !!assignedTo
          })
        }
      }
    }
  } else if (sourceType === 'crio' && nodeId) {
    // cRIO: First try to get channels from cRIO-specific discovery (direct from cRIO node)
    const crioChannels = crioDiscoveryChannels.value[nodeId]
    if (crioChannels?.length) {
      for (const ch of crioChannels) {
        // Check both cRIO's in_use flag AND local config usage
        const assignedTo = usedChannels.get(ch.physical_channel)
        const isUsed = !!assignedTo || !!ch.in_use
        const usageLabel = assignedTo
          ? ` [USED BY: ${assignedTo}]`
          : (ch.in_use ? ' [IN USE]' : '')
        channels.push({
          value: ch.physical_channel,
          label: `${ch.physical_channel} (${ch.channel_type})${usageLabel}`,
          type: ch.channel_type,
          inUse: isUsed
        })
      }
    } else {
      // Fallback: get channels from DAQ service's discovery result (may be limited)
      const node = discoveryResult.value?.crio_nodes?.find((n: any) => n.node_id === nodeId)
      if (node?.modules) {
        for (const module of node.modules) {
          for (const ch of module.channels || []) {
            const assignedTo = usedChannels.get(ch.name)
            const usageLabel = assignedTo ? ` [USED BY: ${assignedTo}]` : ''
            const chType = ch.channel_type || ch.type || ch.category || ''
            channels.push({
              value: ch.name,
              label: `${ch.name} (${chType})${usageLabel}`,
              type: chType,
              inUse: !!assignedTo
            })
          }
        }
      }
    }
  } else if (sourceType === 'opto22' && nodeId) {
    // Opto22: get channels from selected node
    const node = discoveryResult.value?.opto22_nodes?.find((n: any) => n.node_id === nodeId)
    if (node?.modules) {
      for (const module of node.modules) {
        for (const ch of module.channels || []) {
          const assignedTo = usedChannels.get(ch.name)
          const usageLabel = assignedTo ? ` [USED BY: ${assignedTo}]` : ''
          const chType = ch.channel_type || ch.type || ch.category || ''
          channels.push({
            value: ch.name,
            label: `${ch.name} (${chType})${usageLabel}`,
            type: chType,
            inUse: !!assignedTo
          })
        }
      }
    }
  }

  return channels
}

// Get available physical channels filtered by channel type (for inline editing and add modal)
function getAvailablePhysicalChannelsForType(channelConfigOrType?: any): Array<{value: string, label: string, type: string, inUse: boolean}> {
  const allChannels = getAvailablePhysicalChannels()
  if (allChannels.length === 0) return []

  // Get channel type from config object or use as direct type string
  const channelType = typeof channelConfigOrType === 'string'
    ? channelConfigOrType
    : (channelConfigOrType?.channel_type || newChannelForm.value.channel_type)
  const compatibleTypes: string[] = []

  // Map channel type to compatible discovery types
  switch (channelType) {
    case 'voltage_input':
    case 'analog_input':
      compatibleTypes.push('analog_input', 'voltage_input', 'AI')
      break
    case 'thermocouple':
      compatibleTypes.push('thermocouple', 'TC', 'analog_input')
      break
    case 'rtd':
      compatibleTypes.push('rtd', 'RTD', 'analog_input')
      break
    case 'current_input':
      compatibleTypes.push('current_input', 'AI')
      break
    case 'digital_input':
      compatibleTypes.push('digital_input', 'DI')
      break
    case 'voltage_output':
    case 'analog_output':
      compatibleTypes.push('analog_output', 'voltage_output', 'AO')
      break
    case 'current_output':
      compatibleTypes.push('current_output', 'AO')
      break
    case 'digital_output':
      compatibleTypes.push('digital_output', 'DO')
      break
    case 'counter':
      compatibleTypes.push('counter', 'CTR')
      break
    default:
      // Unknown type - show all channels
      return allChannels
  }

  // Filter channels by compatible types
  return allChannels.filter(ch => {
    if (!ch.type) return false
    const chTypeLower = ch.type.toLowerCase()
    return compatibleTypes.some(type =>
      chTypeLower.includes(type.toLowerCase()) ||
      type.toLowerCase().includes(chTypeLower)
    )
  })
}

// Check if we have discovery data for the current source type
function hasDiscoveryData(): boolean {
  const sourceType = newChannelForm.value.source_type
  const nodeId = newChannelForm.value.node_id
  if (sourceType === 'cdaq') {
    return !!(discoveryResult.value?.chassis?.length || discoveryResult.value?.standalone_devices?.length)
  } else if (sourceType === 'crio') {
    // Check cRIO-specific discovery first, then fall back to DAQ discovery
    if (nodeId && crioDiscoveryChannels.value[nodeId]?.length) {
      return true
    }
    return !!discoveryResult.value?.crio_nodes?.length
  } else if (sourceType === 'opto22') {
    return !!discoveryResult.value?.opto22_nodes?.length
  }
  return false
}

// System Settings State
const showSystemSettings = ref(false)
const systemSettingsForm = ref({
  project_name: '',
  scan_rate_hz: 4,
  publish_rate_hz: 4,
  project_mode: 'cdaq' as 'cdaq' | 'crio' | 'opto22' | 'cfp',
  watchdog_output: {
    enabled: false,
    channel: '',
    frequency_hz: 1.0
  },
  confirm_output_changes: false,
  alarm_flood: {
    threshold: 10,
    window_s: 60
  },
  notifications: getDefaultNotificationSettings()
})

function getDefaultNotificationSettings(): NotificationSettings {
  return {
    twilio: {
      enabled: false,
      account_sid: '',
      auth_token: '',
      from_number: '',
      to_numbers: [],
      rules: getDefaultTriggerRules()
    },
    email: {
      enabled: false,
      smtp_host: '',
      smtp_port: 587,
      use_tls: true,
      username: '',
      password: '',
      from_address: '',
      to_addresses: [],
      rules: getDefaultTriggerRules()
    },
    cooldown_seconds: 300,
    daily_limit: 100,
    quiet_hours_enabled: false,
    quiet_hours_start: '22:00',
    quiet_hours_end: '06:00'
  }
}

function getDefaultTriggerRules(): NotificationTriggerRules {
  return {
    severities: ['critical', 'high'],
    event_types: ['triggered', 'alarm_flood'],
    groups: [],
    alarm_select_mode: 'all' as const,
    alarm_ids: []
  }
}

// Notification UI helpers
const notifTwilioToNumbers = computed({
  get: () => systemSettingsForm.value.notifications.twilio.to_numbers.join(', '),
  set: (val: string) => {
    systemSettingsForm.value.notifications.twilio.to_numbers = val.split(',').map(s => s.trim()).filter(Boolean)
  }
})

const notifEmailToAddresses = computed({
  get: () => systemSettingsForm.value.notifications.email.to_addresses.join(', '),
  set: (val: string) => {
    systemSettingsForm.value.notifications.email.to_addresses = val.split(',').map(s => s.trim()).filter(Boolean)
  }
})

const notifSendingTest = ref(false)

// Computed list of configured alarms for notification alarm selection
const configuredAlarmList = computed(() => {
  const configs = safety.alarmConfigs.value
  const result: { id: string; name: string; channel: string; severity: string; group: string }[] = []
  for (const [channel, config] of Object.entries(configs)) {
    if (config && config.enabled) {
      result.push({
        id: config.id || `alarm-${channel}`,
        name: config.name || channel,
        channel,
        severity: (config.severity as string) || 'medium',
        group: config.group || ''
      })
    }
  }
  return result.sort((a, b) => {
    const gCmp = a.group.localeCompare(b.group)
    return gCmp !== 0 ? gCmp : a.name.localeCompare(b.name)
  })
})

// Unique alarm groups from configured alarms
const alarmGroupList = computed(() => {
  const groups = new Set<string>()
  for (const alarm of configuredAlarmList.value) {
    if (alarm.group) groups.add(alarm.group)
  }
  return Array.from(groups).sort()
})

function toggleSeverity(rules: NotificationTriggerRules, sev: AlarmSeverityLevel) {
  const idx = rules.severities.indexOf(sev)
  if (idx >= 0) rules.severities.splice(idx, 1)
  else rules.severities.push(sev)
}

function toggleEventType(rules: NotificationTriggerRules, evt: string) {
  const idx = rules.event_types.indexOf(evt as any)
  if (idx >= 0) rules.event_types.splice(idx, 1)
  else rules.event_types.push(evt as any)
}

function toggleGroup(rules: NotificationTriggerRules, group: string) {
  const idx = rules.groups.indexOf(group)
  if (idx >= 0) rules.groups.splice(idx, 1)
  else rules.groups.push(group)
}

function toggleAlarmId(rules: NotificationTriggerRules, alarmId: string) {
  const idx = rules.alarm_ids.indexOf(alarmId)
  if (idx >= 0) rules.alarm_ids.splice(idx, 1)
  else rules.alarm_ids.push(alarmId)
}

function sendTestNotification(channel: 'twilio' | 'email') {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }
  notifSendingTest.value = true
  mqtt.sendNodeCommand('notifications/test', {
    channel,
    config: systemSettingsForm.value.notifications
  })
  const label = channel === 'twilio' ? 'SMS' : 'Email'
  showFeedback('info', `Sending test ${label}... Check your ${channel === 'twilio' ? 'phone' : 'inbox'}.`)
  setTimeout(() => { notifSendingTest.value = false }, 5000)
}

// Auto-Gen Widgets Modal State
const showAutoGenModal = ref(false)
const autoGenForm = ref({
  channelTypes: ['thermocouple', 'rtd', 'voltage_input', 'current_input', 'digital_input', 'digital_output', 'voltage_output', 'current_output'] as string[],
  widgetSize: 'compact' as 'compact' | 'normal' | 'large',
  columns: 4,
  onlyEnabled: true
})

// Available channel types for auto-gen selection
const availableChannelTypes = [
  // Temperature
  { id: 'thermocouple', label: 'Thermocouple (TC)', icon: '🌡' },
  { id: 'rtd', label: 'RTD', icon: '🌡' },
  // Analog Inputs
  { id: 'voltage_input', label: 'Voltage Input', icon: '⚡' },
  { id: 'current_input', label: 'Current Input', icon: '〰' },
  { id: 'strain_input', label: 'Strain Input', icon: '⚖' },
  { id: 'bridge_input', label: 'Bridge Input', icon: '⚖' },
  { id: 'iepe_input', label: 'IEPE/Accelerometer', icon: '📳' },
  { id: 'resistance_input', label: 'Resistance Input', icon: '🔌' },
  // Analog Outputs
  { id: 'voltage_output', label: 'Voltage Output', icon: '↗' },
  { id: 'current_output', label: 'Current Output', icon: '↗' },
  // Digital
  { id: 'digital_input', label: 'Digital Input', icon: '◯' },
  { id: 'digital_output', label: 'Digital Output', icon: '●' },
  // Counter/Timer
  { id: 'counter_input', label: 'Counter Input', icon: '⏱' },
  { id: 'frequency_input', label: 'Frequency Input', icon: '📊' },
  // Legacy (for backwards compatibility)
  { id: 'counter', label: 'Counter (Legacy)', icon: '⏱' },
  { id: 'strain', label: 'Strain (Legacy)', icon: '⚖' },
  { id: 'iepe', label: 'IEPE (Legacy)', icon: '📳' },
  { id: 'resistance', label: 'Resistance (Legacy)', icon: '🔌' },
  // Modbus
  { id: 'modbus_register', label: 'Modbus Register', icon: '📊' },
  { id: 'modbus_coil', label: 'Modbus Coil', icon: '🔘' },
  // Other
  { id: 'string', label: 'String', icon: '📝' }
]

// Batch Selection State - for multi-select operations
const selectedTableChannels = ref<Set<string>>(new Set())

// Computed: Check if all visible channels are selected
const allVisibleSelected = computed(() => {
  const visibleNames = filteredChannels.value.map(([name]) => name)
  return visibleNames.length > 0 && visibleNames.every(name => selectedTableChannels.value.has(name))
})

// Computed: Check if some visible channels are selected
const someVisibleSelected = computed(() => {
  const visibleNames = filteredChannels.value.map(([name]) => name)
  return visibleNames.some(name => selectedTableChannels.value.has(name)) && !allVisibleSelected.value
})

// Toggle all visible channels selection
function toggleSelectAll() {
  const visibleNames = filteredChannels.value.map(([name]) => name)
  if (allVisibleSelected.value) {
    // Deselect all
    visibleNames.forEach(name => selectedTableChannels.value.delete(name))
  } else {
    // Select all
    visibleNames.forEach(name => selectedTableChannels.value.add(name))
  }
}

// Toggle individual channel selection
function toggleChannelSelection(name: string, event: Event) {
  event.stopPropagation()
  if (selectedTableChannels.value.has(name)) {
    selectedTableChannels.value.delete(name)
  } else {
    selectedTableChannels.value.add(name)
  }
}

// Batch delete selected channels
function deleteSelectedChannels() {
  const count = selectedTableChannels.value.size
  if (count === 0) return

  const confirmed = window.confirm(
    `Delete ${count} selected channel(s)?\n\nThis cannot be undone.`
  )
  if (!confirmed) return

  // Capture and clear selection immediately to prevent re-entrancy
  const channelsToDelete = Array.from(selectedTableChannels.value)
  selectedTableChannels.value.clear()

  channelsToDelete.forEach(name => {
    deleteChannel(name)
  })
  showFeedback('success', `Deleted ${count} channel(s)`)
}

// Batch enable/disable selected channels
function toggleSelectedChannelsEnabled(enable: boolean) {
  const count = selectedTableChannels.value.size
  if (count === 0) return

  selectedTableChannels.value.forEach(name => {
    channelEnabled.value[name] = enable
  })

  const action = enable ? 'enabled' : 'disabled'
  showFeedback('success', `${count} channel(s) ${action}`)
}

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
    .filter(([_, config]) => config.channel_type === 'digital_output' || config.channel_type === 'voltage_output' || config.channel_type === 'current_output' || config.channel_type === 'analog_output')
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

// Handle tag rename from inline edit (wrapper for renameChannel)
function handleTagRename(oldName: string, newName: string) {
  if (!canEdit.value) return
  newName = newName.trim()
  // If unchanged or empty, do nothing (will revert on next render)
  if (!newName || newName === oldName) return
  renameChannel(oldName, newName)
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
      'voltage_input': 'voltage_input',
      'current_input': 'current_input',
      'voltage_output': 'voltage_output',
      'current_output': 'current_output',
      'digital_input': 'digital_input',
      'digital_output': 'digital_output',
      'counter': 'counter_input',
      'pulse_output': 'pulse_output',
      'strain': 'strain_input',
      'iepe': 'iepe_input',
      'modbus': 'modbus_register',
      'rest_api': 'voltage_input'
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

  // Always scan for hardware so the physical channel dropdown is populated
  if (!isScanning.value) {
    const mode = systemSettingsForm.value.project_mode || store.status?.project_mode || 'cdaq'
    mqtt.scanDevices(mode)
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

  // Check for duplicate physical channel
  const resolvedPhysical = physicalChannel || tagName
  for (const [existingTag, existingConfig] of Object.entries(store.channels)) {
    if (existingConfig.physical_channel === resolvedPhysical) {
      showFeedback('error', `Physical channel "${resolvedPhysical}" is already used by tag "${existingTag}"`)
      return
    }
  }

  const config: Record<string, any> = {
    name: tagName,  // TAG is the only identifier
    physical_channel: resolvedPhysical,
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

  // Add Modbus defaults for new Modbus channels so backend can parse them
  const ct = newChannelForm.value.channel_type
  if (ct === 'modbus_register') {
    config.modbus_register_type = 'holding'
    config.modbus_data_type = 'float32'
    config.modbus_byte_order = 'big'
    config.modbus_word_order = 'big'
    config.modbus_scale = 1.0
    config.modbus_offset = 0.0
    // Build physical_channel in modbus format if user entered a plain address
    if (resolvedPhysical && !resolvedPhysical.startsWith('modbus:')) {
      config.physical_channel = `modbus:holding:${resolvedPhysical}`
    }
  }
  if (ct === 'modbus_coil') {
    config.modbus_register_type = 'coil'
    // Build physical_channel in modbus format if user entered a plain address
    if (resolvedPhysical && !resolvedPhysical.startsWith('modbus:')) {
      config.physical_channel = `modbus:coil:${resolvedPhysical}`
    }
  }

  mqtt.updateChannelConfig(tagName, config)
  showFeedback('success', `Adding channel: ${tagName}`)
  channelEnabled.value[tagName] = true
  closeAddChannelModal()
  markDirty()
}

function closeAddChannelModal() {
  showAddChannelModal.value = false
}

function getDefaultUnit(channelType: ChannelType): string {
  const units: Record<ChannelType, string> = {
    thermocouple: '°C',
    rtd: '°C',
    voltage: 'V',
    current: 'mA',
    voltage_input: 'V',
    current_input: 'mA',
    analog_input: 'V',   // Generic analog input
    strain: 'µε',
    strain_input: 'µε',
    bridge_input: 'mV/V',
    iepe: 'g',
    iepe_input: 'g',
    resistance: 'Ω',
    resistance_input: 'Ω',
    counter: 'counts',
    counter_input: 'counts',
    counter_output: 'counts',
    frequency_input: 'Hz',
    pulse_output: 'Hz',
    digital_input: '',
    digital_output: '',
    voltage_output: 'V',
    current_output: 'mA',
    analog_output: 'V',  // Legacy
    modbus_register: '',
    modbus_coil: '',
    script: '',
    system: ''
  }
  return units[channelType] || ''
}

// Delete channel with dependency checking
function deleteChannel(channelName: string, event?: Event) {
  event?.stopPropagation()

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
  mqtt.sendNodeCommand('config/channel/delete', { channel: channelName })
  showFeedback('info', `Deleting channel: ${channelName}...`)

  // Close config panel if this channel was selected
  if (selectedChannel.value === channelName) {
    closeConfigPanel()
  }

  // Remove from local enable state
  delete channelEnabled.value[channelName]
  markDirty()
}

// Rename channel (change tag name)
function renameChannel(oldName: string, newName: string) {
  // Validate new name
  newName = newName.trim()
  if (!newName) {
    showFeedback('error', 'Tag name cannot be empty')
    return false
  }
  if (newName === oldName) {
    return false // No change
  }
  if (store.channels[newName]) {
    showFeedback('error', `Tag "${newName}" already exists`)
    return false
  }
  // Validate tag name format (alphanumeric + underscore/hyphen, starts with letter)
  if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(newName)) {
    showFeedback('error', 'Tag name must start with a letter and contain only letters, numbers, underscores, and hyphens')
    return false
  }

  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return false
  }

  // Get the current config
  const config = store.channels[oldName]
  if (!config) {
    showFeedback('error', `Channel "${oldName}" not found`)
    return false
  }

  // Create new channel with same config
  mqtt.createChannel(newName, { ...config })

  // Delete old channel
  mqtt.sendNodeCommand('config/channel/delete', { channel: oldName })

  // Update local enabled state
  if (channelEnabled.value[oldName] !== undefined) {
    channelEnabled.value[newName] = channelEnabled.value[oldName]
    delete channelEnabled.value[oldName]
  }

  // Update all references (widgets, alarms, scripts, etc.)
  propagateChannelRename(oldName, newName)

  // Update selected channel if it was the renamed one
  if (selectedChannel.value === oldName) {
    selectedChannel.value = newName
  }

  showFeedback('success', `Renamed "${oldName}" to "${newName}"`)
  markDirty()
  return true
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

// Validate entire configuration and generate report
function validateConfiguration() {
  isValidating.value = true
  const issues: ValidationIssue[] = []
  const channels = Object.entries(store.channels)

  try {
    // Track used physical channels to detect conflicts
    const physicalChannelMap = new Map<string, string[]>() // physical_channel -> tag_names[]

    for (const [tagName, config] of channels) {
      // Check 1: Required fields
      if (!tagName || tagName.trim() === '') {
        issues.push({
          channel: tagName || '(unnamed)',
          severity: 'error',
          category: 'Required Fields',
          message: 'Tag name is empty',
          fix: 'Click the tag name cell to rename the channel'
        })
      }

      if (!config.channel_type) {
        issues.push({
          channel: tagName,
          severity: 'error',
          category: 'Required Fields',
          message: 'Channel type is missing',
          fix: 'Open channel config and select a channel type (thermocouple, voltage, etc.)'
        })
      }

      if (!config.physical_channel || config.physical_channel.trim() === '') {
        issues.push({
          channel: tagName,
          severity: 'warning',
          category: 'Required Fields',
          message: 'Physical channel is not assigned',
          fix: 'Open channel config and assign a physical channel from discovered hardware'
        })
      } else {
        // Track physical channel usage
        const pc = config.physical_channel
        if (!physicalChannelMap.has(pc)) {
          physicalChannelMap.set(pc, [])
        }
        physicalChannelMap.get(pc)!.push(tagName)
      }

      // Check 2: Tag name format
      if (tagName && !/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(tagName)) {
        issues.push({
          channel: tagName,
          severity: 'error',
          category: 'Naming',
          message: 'Tag name must start with a letter and contain only letters, numbers, underscores, and hyphens',
          fix: 'Click the tag name cell to rename it (e.g., "TT-101" or "temp_boiler_01")'
        })
      }

      // Check 3: Range validation (min <= max)
      if (config.min_value !== undefined && config.max_value !== undefined) {
        if (Number(config.min_value) > Number(config.max_value)) {
          issues.push({
            channel: tagName,
            severity: 'error',
            category: 'Range',
            message: `Min value (${config.min_value}) is greater than max value (${config.max_value})`,
            fix: 'Open channel config and swap the Min/Max values, or correct the range'
          })
        }
      }

      // Check 4: Engineering unit validation
      if (config.eu_min !== undefined && config.eu_max !== undefined) {
        if (Number(config.eu_min) > Number(config.eu_max)) {
          issues.push({
            channel: tagName,
            severity: 'error',
            category: 'Engineering Units',
            message: `EU min (${config.eu_min}) is greater than EU max (${config.eu_max})`,
            fix: 'Open channel config and correct the EU Min/Max range under scaling settings'
          })
        }
      }

      // Check 5: Thermocouple type required
      if (config.channel_type === 'thermocouple' && !config.thermocouple_type) {
        issues.push({
          channel: tagName,
          severity: 'error',
          category: 'Type Configuration',
          message: 'Thermocouple type is required for thermocouple channels',
          fix: 'Select a TC type (K, J, T, E, etc.) from the TC Type column or open channel config'
        })
      }

      // Check 6: RTD type required
      if (config.channel_type === 'rtd' && !config.rtd_type) {
        issues.push({
          channel: tagName,
          severity: 'error',
          category: 'Type Configuration',
          message: 'RTD type is required for RTD channels',
          fix: 'Select an RTD type (Pt100, Pt1000, etc.) from the RTD Type column or open channel config'
        })
      }

      // Check 7: Source type validation
      if (config.source_type === 'crio' && !config.node_id) {
        issues.push({
          channel: tagName,
          severity: 'warning',
          category: 'Source Configuration',
          message: 'cRIO source selected but no node_id specified',
          fix: 'Open channel config and assign a cRIO node ID, or change source type to match project mode'
        })
      }

      // Check 8: Disabled channels notice
      if (config.enabled === false) {
        issues.push({
          channel: tagName,
          severity: 'info',
          category: 'Status',
          message: 'Channel is disabled',
          fix: 'Toggle the enable checkbox to re-enable this channel'
        })
      }

      // Check 9: Alarm configuration validation
      if (config.hi_alarm !== undefined && config.hihi_alarm !== undefined) {
        const hi = Number(config.hi_alarm)
        const hihi = Number(config.hihi_alarm)
        if (!isNaN(hi) && !isNaN(hihi) && hi > hihi) {
          issues.push({
            channel: tagName,
            severity: 'warning',
            category: 'Alarms',
            message: `HI alarm (${hi}) is greater than HIHI alarm (${hihi})`,
            fix: 'Open channel config and set HIHI higher than HI (HIHI should be the more critical limit)'
          })
        }
      }

      if (config.lo_alarm !== undefined && config.lolo_alarm !== undefined) {
        const lo = Number(config.lo_alarm)
        const lolo = Number(config.lolo_alarm)
        if (!isNaN(lo) && !isNaN(lolo) && lo < lolo) {
          issues.push({
            channel: tagName,
            severity: 'warning',
            category: 'Alarms',
            message: `LO alarm (${lo}) is less than LOLO alarm (${lolo})`,
            fix: 'Open channel config and set LOLO lower than LO (LOLO should be the more critical limit)'
          })
        }
      }
    }

    // Check 10: Physical channel conflicts (multiple tags using same physical channel)
    for (const [physicalChannel, tagNames] of physicalChannelMap.entries()) {
      if (tagNames.length > 1) {
        for (const tagName of tagNames) {
          issues.push({
            channel: tagName,
            severity: 'error',
            category: 'Physical Channel Conflict',
            message: `Physical channel "${physicalChannel}" is used by multiple tags: ${tagNames.join(', ')}`,
            fix: 'Open channel config for one of the conflicting tags and reassign to a different physical channel, or delete the duplicate'
          })
        }
      }
    }

    // Sort issues by severity (error > warning > info) then by channel name
    const severityOrder = { error: 0, warning: 1, info: 2 }
    issues.sort((a, b) => {
      const severityDiff = severityOrder[a.severity] - severityOrder[b.severity]
      if (severityDiff !== 0) return severityDiff
      return a.channel.localeCompare(b.channel)
    })

    // Generate report
    const errorCount = issues.filter(i => i.severity === 'error').length
    validationReport.value = {
      timestamp: new Date().toISOString(),
      totalChannels: channels.length,
      validChannels: channels.length - new Set(issues.map(i => i.channel)).size,
      issues
    }

    showValidationModal.value = true

    if (errorCount === 0) {
      showFeedback('success', `Validation complete: ${issues.length} issue(s) found`)
    } else {
      showFeedback('warning', `Validation found ${errorCount} error(s)`)
    }
  } finally {
    isValidating.value = false
  }
}

function closeValidationModal() {
  showValidationModal.value = false
}

// Open system settings
function openSystemSettings() {
  const wd = store.status?.watchdog_output
  systemSettingsForm.value = {
    project_name: projectFiles.currentProjectData.value?.name || projectFiles.currentProject.value?.replace('.json', '') || '',
    scan_rate_hz: store.status?.scan_rate_hz || 4,
    publish_rate_hz: store.status?.publish_rate_hz || 4,
    project_mode: (store.status?.project_mode as 'cdaq' | 'crio' | 'opto22' | 'cfp') || 'cdaq',
    watchdog_output: {
      enabled: wd?.enabled || false,
      channel: wd?.channel || '',
      frequency_hz: wd?.frequency_hz || 1.0
    },
    confirm_output_changes: (projectFiles.currentProjectData.value?.system as any)?.confirm_output_changes ?? false,
    alarm_flood: (projectFiles.currentProjectData.value?.safety as any)?.alarmFlood ?? { threshold: 10, window_s: 60 },
    notifications: (projectFiles.currentProjectData.value?.system as any)?.notifications ?? getDefaultNotificationSettings()
  }
  showSystemSettings.value = true
}

function saveSystemSettings() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Update project name if changed
  const newName = systemSettingsForm.value.project_name.trim()
  if (newName && projectFiles.currentProjectData.value && newName !== projectFiles.currentProjectData.value.name) {
    projectFiles.currentProjectData.value.name = newName
    projectFiles.markDirty()
  }

  // Persist project_mode into project data for saving
  const newMode = systemSettingsForm.value.project_mode
  if (projectFiles.currentProjectData.value) {
    if (!projectFiles.currentProjectData.value.system) {
      projectFiles.currentProjectData.value.system = {} as any
    }
    (projectFiles.currentProjectData.value.system as any).project_mode = newMode
    ;(projectFiles.currentProjectData.value.system as any).confirm_output_changes = systemSettingsForm.value.confirm_output_changes
    ;(projectFiles.currentProjectData.value.system as any).notifications = systemSettingsForm.value.notifications
    // Persist alarm flood settings in safety section
    if (!(projectFiles.currentProjectData.value as any).safety) {
      ;(projectFiles.currentProjectData.value as any).safety = {}
    }
    ;(projectFiles.currentProjectData.value as any).safety.alarmFlood = systemSettingsForm.value.alarm_flood
    projectFiles.markDirty()
  }

  // Send notification config to backend
  if (systemSettingsForm.value.notifications.twilio.enabled || systemSettingsForm.value.notifications.email.enabled) {
    mqtt.sendNodeCommand('notifications/config/update', systemSettingsForm.value.notifications)
  }

  // Warn if channels don't match the selected project mode
  const mismatchedChannels = Object.values(store.channels).filter(
    ch => ch.source_type && ch.source_type !== newMode
  )
  if (mismatchedChannels.length > 0) {
    showFeedback('warning', `${mismatchedChannels.length} channel(s) are configured for "${mismatchedChannels[0]!.source_type}" but project mode is "${newMode}". Update channels individually if needed.`)
  }

  mqtt.sendNodeCommand('config/system/update', {
    scan_rate_hz: systemSettingsForm.value.scan_rate_hz,
    publish_rate_hz: systemSettingsForm.value.publish_rate_hz,
    project_mode: systemSettingsForm.value.project_mode,
    watchdog_output: systemSettingsForm.value.watchdog_output,
    alarm_flood: systemSettingsForm.value.alarm_flood
  })
  showFeedback('info', 'Updating system settings...')
  showSystemSettings.value = false
}

// Open Auto-Gen Widgets modal
function autoGenerateWidgets() {
  // Reset form with all types selected by default
  autoGenForm.value.channelTypes = availableChannelTypes.map(t => t.id)
  showAutoGenModal.value = true
}

// Get count of channels matching current auto-gen filter
function getAutoGenChannelCount(): number {
  return Object.keys(store.channels).filter(name => {
    const ch = store.channels[name]
    if (!ch) return false
    if (autoGenForm.value.onlyEnabled && channelEnabled.value[name] === false) return false
    return autoGenForm.value.channelTypes.includes(ch.channel_type)
  }).length
}

// Execute auto-generation with current settings
function executeAutoGenWidgets() {
  const channelCount = getAutoGenChannelCount()

  if (channelCount === 0) {
    showFeedback('info', 'No channels match the selected filters')
    return
  }

  // Filter channels based on settings - receives ChannelConfig from store
  const selectedTypes = autoGenForm.value.channelTypes
  const onlyEnabled = autoGenForm.value.onlyEnabled
  const channelFilter = (ch: any) => {
    if (!ch) return false
    // Check if enabled (if onlyEnabled filter is active)
    if (onlyEnabled && channelEnabled.value[ch.name || ''] === false) return false
    // Check channel type
    return selectedTypes.includes(ch.channel_type)
  }

  const count = store.autoGenerateWidgets({
    widgetSize: autoGenForm.value.widgetSize,
    columns: autoGenForm.value.columns,
    channelFilter
  })

  showAutoGenModal.value = false
  showFeedback('success', `Created ${count} widgets! Go to Overview page to see them.`)
}

// Toggle channel type selection in auto-gen form
function toggleAutoGenType(typeId: string) {
  const idx = autoGenForm.value.channelTypes.indexOf(typeId)
  if (idx >= 0) {
    autoGenForm.value.channelTypes.splice(idx, 1)
  } else {
    autoGenForm.value.channelTypes.push(typeId)
  }
}

// Select/deselect all channel types in auto-gen form
function setAllAutoGenTypes(select: boolean) {
  if (select) {
    autoGenForm.value.channelTypes = availableChannelTypes.map(t => t.id)
  } else {
    autoGenForm.value.channelTypes = []
  }
}

// Discovery state
const isScanning = computed(() => mqtt.isScanning.value)
const discoveryChannels = computed(() => mqtt.discoveryChannels.value)
const discoveryResult = computed(() => mqtt.discoveryResult.value)
const crioDiscoveryChannels = computed(() => mqtt.crioDiscoveryChannels.value)
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
    if (usedPhysicalChannels.value[ch.name]) return
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
const feedbackMessage = ref<{ type: 'success' | 'error' | 'info' | 'warning', text: string } | null>(null)

function showFeedback(type: 'success' | 'error' | 'info' | 'warning', text: string, duration = 3000) {
  feedbackMessage.value = { type, text }
  setTimeout(() => {
    feedbackMessage.value = null
  }, duration)
}

// Device discovery - respects current project mode setting
function scanDevices() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Close any conflicting panels before opening discovery
  if (showConfigPanel.value) closeConfigPanel()
  if (showAddChannelModal.value) showAddChannelModal.value = false

  // Clear all local discovery state before starting new scan
  // This ensures subsequent scans show fresh results without stale selections
  selectedDiscoveryChannels.value = []
  expandedChassis.value = new Set()
  expandedModules.value = new Set()
  expandedCrioNodes.value = new Set()

  // Get current project mode from system settings or store status
  const mode = systemSettingsForm.value.project_mode || store.status?.project_mode || 'cdaq'
  const modeLabel = mode === 'cdaq' ? 'cDAQ' : mode === 'crio' ? 'cRIO' : mode === 'cfp' ? 'CFP' : 'Opto22'
  showFeedback('info', `Discovering ${modeLabel} devices...`)
  userClosedDiscovery.value = false
  mqtt.scanDevices(mode)
  showDiscoveryPanel.value = true
}

// Track whether the user explicitly closed the discovery panel
// so that a late-arriving backend result doesn't reopen it
const userClosedDiscovery = ref(false)

// Close discovery panel and cancel any pending scan
function closeDiscoveryPanel() {
  showDiscoveryPanel.value = false
  userClosedDiscovery.value = true
  mqtt.cancelScan()
}

// MQTT callback unsub functions (registered in onMounted, cleaned up in onBeforeUnmount)
let unsubDiscovery: (() => void) | null = null
let unsubCrioResponse: (() => void) | null = null
let unsubConfigUpdate: (() => void) | null = null
let unsubSystemUpdate: (() => void) | null = null

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
    .filter((ch) => ch.channel_type === 'digital_output')
    .map((ch) => ch.name)

  // Push config to cRIO
  mqtt.pushCrioConfig(node.node_id, {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 4,
    publish_rate_hz: store.status?.publish_rate_hz || 4
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
    .filter((ch) => ch.channel_type === 'digital_output')
    .map((ch) => ch.name)

  // Push config to Opto22 (uses same mechanism as cRIO)
  mqtt.pushCrioConfig(node.node_id, {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 4,
    publish_rate_hz: store.status?.publish_rate_hz || 4
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
    if (config.source_type === 'crio' && config.node_id) {
      crioNodeIds.add(config.node_id)
    } else if (config.source_type === 'opto22' && config.node_id) {
      opto22NodeIds.add(config.node_id)
    }
  }

  const totalNodes = crioNodeIds.size + opto22NodeIds.size
  if (totalNodes === 0) return  // No remote channels

  // Get current channel configs from store
  const channelConfigs = Object.values(store.channels || {})
  const scripts = backendScripts.scriptsList.value || []
  const safeStateOutputs = channelConfigs
    .filter((ch) => ch.channel_type === 'digital_output')
    .map((ch) => ch.name)

  const configPayload = {
    channels: channelConfigs,
    scripts: scripts,
    safe_state_outputs: safeStateOutputs,
    scan_rate_hz: store.status?.scan_rate_hz || 4,
    publish_rate_hz: store.status?.publish_rate_hz || 4
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
    current_input: 'mA',
    strain: 'STR',
    iepe: 'IEPE',
    counter: 'CTR',
    digital_input: 'DI',
    digital_output: 'DO',
    voltage_output: 'VO',
    current_output: 'CO',
    analog_output: 'AO',  // Legacy
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
    counter: { low: 0, high: 4294967295 },
    digital_input: { low: 0, high: 1 },
    digital_output: { low: 0, high: 1 },
    voltage_output: { low: -10, high: 10 },
    current_output: { low: 0, high: 20 },
    analog_output: { low: -10, high: 10 },  // Legacy
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
    voltage_output: 'Voltage Outputs',
    current_output: 'Current Outputs',
    analog_output: 'Analog Outputs',  // Legacy
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
      // Thermocouple defaults - Type K is most common
      thermocouple_type: category === 'thermocouple' ? 'K' : null,
      cjc_source: category === 'thermocouple' ? 'BUILT_IN' : null,
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

  // Show populating indicator
  isPopulating.value = true
  const channelCount = selectedChannels.length

  // Use bulk create for efficiency (sends all at once)
  mqtt.bulkCreateChannels(channelsToCreate)

  showFeedback('info', `Populating ${channelCount} channels...`)
  selectedDiscoveryChannels.value = []
  closeDiscoveryPanel()

  // Listen for the bulk create response to clear the indicator
  const unsubscribe = mqtt.onChannelCreated((created) => {
    isPopulating.value = false
    showFeedback('success', `${created.length} channel(s) populated and ready`)
    unsubscribe()
    markDirty()
  })

  // Safety timeout in case response never arrives
  setTimeout(() => {
    if (isPopulating.value) {
      isPopulating.value = false
      showFeedback('warning', 'Populate timed out — check channel list')
      unsubscribe()
    }
  }, 15000)
}

// Map physical channels to existing tag names (for discovery panel "in use" indicators)
const usedPhysicalChannels = computed(() => {
  const map: Record<string, string> = {}
  for (const [tagName, config] of Object.entries(store.channels)) {
    if (config.physical_channel) {
      map[config.physical_channel] = tagName
    }
  }
  return map
})

function toggleDiscoveryChannel(physicalChannel: string) {
  if (usedPhysicalChannels.value[physicalChannel]) return
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

  selectedDiscoveryChannels.value = allChannels.filter(ch => !usedPhysicalChannels.value[ch])
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
  if (store.isAcquiring) {
    showFeedback('error', 'Cannot apply config changes while acquisition is running')
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
interface ChannelTypeTab {
  id: string
  label: string
  icon: string
  fullName: string
  adminOnly?: boolean
  hidden?: boolean
  cfpOnly?: boolean
}

const channelTypeTabs: ChannelTypeTab[] = [
  { id: 'all', label: 'ALL', icon: '⊞', fullName: 'All Channels' },
  { id: 'thermocouple', label: 'TC', icon: '🌡', fullName: 'Thermocouple Analog Input' },
  { id: 'rtd', label: 'RTD', icon: '🌡', fullName: 'RTD Temperature Input' },
  { id: 'voltage_input', label: 'V-IN', icon: '⚡', fullName: 'Voltage Input' },
  { id: 'current_input', label: 'mA-IN', icon: '〰', fullName: 'Current Input (4-20mA)' },
  { id: 'voltage_output', label: 'V-OUT', icon: '↗', fullName: 'Voltage Output' },
  { id: 'current_output', label: 'mA-OUT', icon: '↗', fullName: 'Current Output (4-20mA)' },
  { id: 'digital_input', label: 'DI', icon: '▢', fullName: 'Digital Input' },
  { id: 'digital_output', label: 'DO', icon: '▣', fullName: 'Digital Output' },
  { id: 'counter', label: 'CTR', icon: '#', fullName: 'Counter/Timer Input' },
  { id: 'pulse_output', label: 'PLS', icon: '⏱', fullName: 'Pulse/Counter Output' },
  { id: 'strain', label: 'STR', icon: '⚖', fullName: 'Strain Gauge / Bridge Input' },
  { id: 'iepe', label: 'IEPE', icon: '〰', fullName: 'IEPE Accelerometer Input' },
  { id: 'modbus', label: 'MODBUS', icon: '🔌', fullName: 'Modbus TCP/RTU Device' },
  { id: 'rest_api', label: 'REST', icon: '🌐', fullName: 'REST API Device' },
  { id: 'opc_ua', label: 'OPC-UA', icon: '🔗', fullName: 'OPC-UA Server' },
  { id: 'ethernet_ip', label: 'AB PLC', icon: '🏭', fullName: 'Allen Bradley EtherNet/IP', hidden: true },
  { id: 'cfp', label: 'CFP', icon: '📦', fullName: 'Compact FieldPoint', cfpOnly: true },
  { id: 'gc', label: 'GC', icon: '\u2697', fullName: 'GC Analyzer' },
]

// Filter tabs - hide admin-only tabs from non-admins, show CFP tab only in CFP mode
const visibleTypeTabs = computed(() => {
  const mode = store.status?.project_mode || 'cdaq'
  return channelTypeTabs.filter(tab => {
    if (tab.hidden) return false
    if (tab.adminOnly && !isAdmin.value) return false
    if (tab.cfpOnly && mode !== 'cfp') return false
    return true
  })
})

// Get full name for current signal type
const activeTypeFullName = computed(() => {
  const tab = channelTypeTabs.find(t => t.id === activeTypeTab.value)
  return tab?.fullName || 'All Channels'
})

const activeTypeTab = ref('all')
const searchQuery = ref('')
const selectedChannel = ref<string | null>(null)
const showConfigPanel = ref(false)

// Sort channels by module first, then by channel index
// This ensures channels are grouped by physical hardware module
function moduleSort(a: [string, any], b: [string, any]): number {
  const aPhys = a[1].physical_channel || ''
  const bPhys = b[1].physical_channel || ''

  // Extract module number (e.g., "Mod1/ai0" -> 1, "cDAQ1Mod2/ai3" -> 2)
  const aModMatch = aPhys.match(/Mod(\d+)/i)
  const bModMatch = bPhys.match(/Mod(\d+)/i)
  const aMod = aModMatch ? parseInt(aModMatch[1], 10) : 999
  const bMod = bModMatch ? parseInt(bModMatch[1], 10) : 999

  // Sort by module first
  if (aMod !== bMod) return aMod - bMod

  // Then by channel index (ai0, ai1, ... ai10, etc.)
  const aChMatch = aPhys.match(/[/]([a-z]+)(\d+)$/i)
  const bChMatch = bPhys.match(/[/]([a-z]+)(\d+)$/i)
  if (aChMatch && bChMatch) {
    // Same channel type prefix (ai, di, ao, do)
    if (aChMatch[1] === bChMatch[1]) {
      return parseInt(aChMatch[2], 10) - parseInt(bChMatch[2], 10)
    }
    // Different type, sort alphabetically (ai before ao before di before do)
    return aChMatch[1].localeCompare(bChMatch[1])
  }

  // Fallback to natural sort on name
  return a[0].localeCompare(b[0])
}

// Filtered channels based on active tab and search
const filteredChannels = computed(() => {
  let channels = Object.entries(store.channels)

  // Filter by type
  if (activeTypeTab.value !== 'all') {
    if (activeTypeTab.value === 'cfp') {
      // CFP tab shows all channels with source_type 'cfp'
      channels = channels.filter(([_, ch]) => ch.source_type === 'cfp')
    } else if (activeTypeTab.value === 'modbus') {
      // Modbus tab shows both modbus_register and modbus_coil types (excludes CFP channels)
      channels = channels.filter(([_, ch]) =>
        (ch.channel_type === 'modbus_register' || ch.channel_type === 'modbus_coil') && ch.source_type !== 'cfp'
      )
    } else if (activeTypeTab.value === 'voltage_output') {
      // V-OUT: voltage_output channels (or legacy analog_output with voltage range)
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'voltage_output' ||
        (ch.channel_type === 'analog_output' && (ch.ao_range?.includes('V') || !ch.ao_range?.includes('mA')))
      )
    } else if (activeTypeTab.value === 'current_output') {
      // mA-OUT: current_output channels (or legacy analog_output with current range)
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'current_output' ||
        (ch.channel_type === 'analog_output' && ch.ao_range?.includes('mA'))
      )
    } else if (activeTypeTab.value === 'voltage_input') {
      // V-IN: voltage_input channels (or legacy 'voltage')
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'voltage_input' || ch.channel_type === 'voltage'
      )
    } else if (activeTypeTab.value === 'current_input') {
      // mA-IN: current_input channels (or legacy 'current')
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'current_input' || ch.channel_type === 'current'
      )
    } else if (activeTypeTab.value === 'counter') {
      // CTR: counter and counter_input are aliases
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'counter' || ch.channel_type === 'counter_input'
      )
    } else if (activeTypeTab.value === 'strain') {
      // STR: strain, strain_input, and bridge_input
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'strain' || ch.channel_type === 'strain_input' || ch.channel_type === 'bridge_input'
      )
    } else if (activeTypeTab.value === 'iepe') {
      // IEPE: iepe and iepe_input are aliases
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'iepe' || ch.channel_type === 'iepe_input'
      )
    } else if (activeTypeTab.value === 'pulse_output') {
      // PLS: pulse_output and frequency_input
      channels = channels.filter(([_, ch]) =>
        ch.channel_type === 'pulse_output' || ch.channel_type === 'frequency_input'
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

  // Sort by module first, then by channel index
  return channels.sort(moduleSort)
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

// Per-channel validation: returns error messages for inline indicator
function getChannelErrors(tagName: string, config: ChannelConfig): string[] {
  const errors: string[] = []

  // Missing channel type
  if (!config.channel_type) {
    errors.push('Channel type is missing')
  }

  // Invalid tag name format
  if (tagName && !/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(tagName)) {
    errors.push('Tag name must start with a letter and contain only letters, numbers, underscores, and hyphens')
  }

  // Range inversion (min > max)
  if (config.min_value !== undefined && config.max_value !== undefined) {
    if (Number(config.min_value) > Number(config.max_value)) {
      errors.push(`Min value (${config.min_value}) is greater than max value (${config.max_value})`)
    }
  }

  // EU range inversion
  if (config.eu_min !== undefined && config.eu_max !== undefined) {
    if (Number(config.eu_min) > Number(config.eu_max)) {
      errors.push(`EU min (${config.eu_min}) is greater than EU max (${config.eu_max})`)
    }
  }

  // Missing thermocouple type
  if (config.channel_type === 'thermocouple' && !config.thermocouple_type) {
    errors.push('Thermocouple type is required')
  }

  // Missing RTD type
  if (config.channel_type === 'rtd' && !config.rtd_type) {
    errors.push('RTD type is required')
  }

  // Physical channel conflict (same physical channel used by another tag)
  if (config.physical_channel) {
    for (const [otherTag, otherConfig] of Object.entries(store.channels)) {
      if (otherTag !== tagName && otherConfig.physical_channel === config.physical_channel) {
        errors.push(`Physical channel "${config.physical_channel}" also used by "${otherTag}"`)
        break
      }
    }
  }

  return errors
}

// Per-channel validation: returns warning messages for inline indicator
function getChannelWarnings(tagName: string, config: ChannelConfig): string[] {
  const warnings: string[] = []

  // Missing physical channel
  if (!config.physical_channel || config.physical_channel.trim() === '') {
    warnings.push('Physical channel is not assigned')
  }

  // Missing node_id for cRIO source
  if (config.source_type === 'crio' && !config.node_id) {
    warnings.push('cRIO source selected but no node_id specified')
  }

  // Disabled channel
  if (config.enabled === false) {
    warnings.push('Channel is disabled')
  }

  // Alarm ordering issues
  if (config.hi_alarm !== undefined && config.hihi_alarm !== undefined) {
    const hi = Number(config.hi_alarm)
    const hihi = Number(config.hihi_alarm)
    if (!isNaN(hi) && !isNaN(hihi) && hi > hihi) {
      warnings.push(`HI alarm (${hi}) is greater than HIHI alarm (${hihi})`)
    }
  }
  if (config.lo_alarm !== undefined && config.lolo_alarm !== undefined) {
    const lo = Number(config.lo_alarm)
    const lolo = Number(config.lolo_alarm)
    if (!isNaN(lo) && !isNaN(lolo) && lo < lolo) {
      warnings.push(`LO alarm (${lo}) is less than LOLO alarm (${lolo})`)
    }
  }

  return warnings
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
    voltage: 'VI',          // Voltage input
    current: 'CI',          // Current input (4-20mA, etc.)
    voltage_input: 'VI',    // Voltage input alias
    current_input: 'CI',    // Current input alias
    analog_input: 'AI',     // Generic analog input (when type unknown)
    strain: 'STR',
    strain_input: 'STR',
    bridge_input: 'BRG',
    iepe: 'IEPE',
    iepe_input: 'IEPE',
    resistance: 'RES',
    resistance_input: 'RES',
    counter: 'CTR',
    counter_input: 'CTR',
    counter_output: 'CTO',
    frequency_input: 'FREQ',
    pulse_output: 'PLS',
    digital_input: 'DI',
    digital_output: 'DO',
    voltage_output: 'VO',   // Voltage output
    current_output: 'CO',   // Current output
    analog_output: 'AO',    // Legacy
    modbus_register: 'MB',
    modbus_coil: 'MBC',
    script: 'SCR',
    system: 'SYS',
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

  // Close conflicting modals
  if (showAddChannelModal.value) showAddChannelModal.value = false

  selectedChannel.value = channelName
  showConfigPanel.value = true

  // Initialize module-specific config based on channel type with defaults + existing values
  let moduleConfig: any = {}
  switch (config.channel_type) {
    case 'thermocouple':
      moduleConfig = {
        ...DEFAULT_THERMOCOUPLE_CONFIG,
        // Load existing thermocouple config from backend
        tc_type: config.thermocouple_type || '',
        cjc_source: config.cjc_source || '',
        cjc_value: config.cjc_value ?? 25.0,
        units: config.unit || 'degC',
      }
      break
    case 'rtd':
      moduleConfig = {
        ...DEFAULT_RTD_CONFIG,
        // Load existing RTD config from backend
        rtd_type: config.rtd_type || DEFAULT_RTD_CONFIG.rtd_type,
        wiring: config.rtd_wiring || DEFAULT_RTD_CONFIG.wiring,
        excitation_current: config.rtd_current ? config.rtd_current * 1e6 : DEFAULT_RTD_CONFIG.excitation_current,
        units: config.unit || 'C',
      }
      break
    case 'voltage_input':
    case 'voltage':  // Legacy
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
    case 'current_input':
    case 'current':  // Legacy
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
    case 'strain_input':
      moduleConfig = {
        bridge_config: config.bridge_config || 'full',
        nominal_resistance: config.nominal_resistance ?? 350,
        gage_factor: config.gage_factor ?? 2.0,
        excitation_voltage: config.excitation_voltage ?? 2.5,
        units: config.unit || 'strain',
      }
      break
    case 'iepe':
    case 'iepe_input':
      moduleConfig = {
        coupling: config.coupling || 'AC',
        excitation_current: config.excitation_current ?? 4,
        sensitivity: config.sensitivity ?? 100,
        units: config.unit || 'g',
      }
      break
    case 'counter':
    case 'counter_input':
      moduleConfig = {
        mode: config.counter_mode || 'count_edges',
        edge: config.counter_edge || 'rising',
        initial_count: config.initial_count ?? 0,
        count_direction: config.direction || 'up',
      }
      break
    case 'resistance':
    case 'resistance_input':
      moduleConfig = {
        wiring: config.wiring || config.rtd_wiring || '2-wire',
        excitation_current_ma: config.excitation_current_ma ?? 1.0,
        resistance_range: config.resistance_range ?? 1000,
      }
      break
    case 'voltage_output':
    case 'analog_output':
      moduleConfig = {
        voltage_range_min: config.voltage_range_min ?? config.raw_min ?? -10,
        voltage_range_max: config.voltage_range_max ?? config.raw_max ?? 10,
        scaling_type: config.scaling_type || 'none',
        scale_slope: config.scale_slope ?? 1,
        scale_offset: config.scale_offset ?? 0,
        scaled_min: config.scaled_min ?? config.pre_scaled_min ?? -10,
        scaled_max: config.scaled_max ?? config.pre_scaled_max ?? 10,
      }
      break
    case 'current_output':
      moduleConfig = {
        current_range_ma_min: config.current_range_ma_min ?? 4,
        current_range_ma_max: config.current_range_ma_max ?? 20,
        four_twenty_scaling: config.four_twenty_scaling ?? true,
        scaled_min: config.scaled_min ?? config.eng_units_min ?? 0,
        scaled_max: config.scaled_max ?? config.eng_units_max ?? 100,
      }
      break
    case 'bridge_input':
      moduleConfig = {
        bridge_config: config.bridge_config || 'full',
        excitation_voltage: config.excitation_voltage ?? 2.5,
        nominal_resistance: config.nominal_resistance ?? 350,
        scaling_type: config.scaling_type || 'none',
        scale_slope: config.scale_slope ?? 1,
        scale_offset: config.scale_offset ?? 0,
      }
      break
    case 'frequency_input':
      moduleConfig = {
        min_frequency: config.min_frequency ?? 1,
        max_frequency: config.max_frequency ?? 100000,
        edge: config.edge || 'rising',
        filter_enable: config.filter_enable ?? false,
      }
      break
    case 'counter_output':
      moduleConfig = {
        initial_count: config.initial_count ?? 0,
        direction: config.direction || 'up',
      }
      break
    case 'pulse_output':
      moduleConfig = {
        frequency: config.pulse_frequency ?? 1000,
        duty_cycle: config.pulse_duty_cycle ?? 50,
        idle_state: config.idle_state || 'low',
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

// Close config panel when switching tabs if selected channel isn't in the new tab's filter
watch(() => activeTypeTab.value, () => {
  if (showConfigPanel.value && selectedChannel.value) {
    const stillVisible = filteredChannels.value.some(([name]) => name === selectedChannel.value)
    if (!stillVisible) {
      closeConfigPanel()
    }
  }
  // Clear table selections when switching tabs
  selectedTableChannels.value.clear()
})

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
    config.thermocouple_type = mc.tc_type
    config.cjc_source = mc.cjc_source
    if (mc.cjc_source === 'constant') {
      config.cjc_value = mc.cjc_value ?? 25.0
    }
    config.open_detect = mc.open_detect ?? true  // Open TC detection (default: enabled)
    config.auto_zero = mc.auto_zero ?? false
  }

  // Add RTD-specific settings
  if (channelType === 'rtd') {
    config.rtd_type = mc.rtd_type
    config.rtd_wiring = mc.wiring
    config.rtd_current = (mc.excitation_current || 1000) / 1e6  // µA to A
  }

  // Add voltage input settings
  if (channelType === 'voltage' || channelType === 'voltage_input') {
    // Parse voltage range from string like "10V" to number
    const rangeMatch = mc.range?.match(/^([\d.]+)/)
    if (rangeMatch) {
      config.voltage_range = parseFloat(rangeMatch[1])
    }
    config.terminal_config = mc.terminal_config ?? 'DEFAULT'
    config.scale_type = mc.scale_type
    config.scale_slope = mc.scale_slope
    config.scale_offset = mc.scale_offset
    config.pre_scaled_min = mc.pre_scaled_min
    config.pre_scaled_max = mc.pre_scaled_max
    config.scaled_min = mc.scaled_min
    config.scaled_max = mc.scaled_max
  }

  // Add current input settings
  if (channelType === 'current' || channelType === 'current_input') {
    // Parse current range from string like "20mA" to number
    const rangeMatch = mc.range?.match(/^([\d.]+)/)
    if (rangeMatch) {
      config.current_range_ma = parseFloat(rangeMatch[1])
    }
    config.terminal_config = mc.terminal_config ?? 'DEFAULT'
    config.shunt_resistor_loc = mc.shunt_location ?? 'internal'  // internal or external
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

  // Strain types — field names must match config_parser.py ChannelConfig
  if (['strain', 'strain_input'].includes(channelType)) {
    config.strain_config = mc.bridge_config  // UI: bridge_config → backend: strain_config
    config.strain_gage_factor = mc.gage_factor
    config.strain_excitation_voltage = mc.excitation_voltage
    config.strain_resistance = mc.nominal_resistance ?? 350.0
    if (mc.poisson_ratio != null) {
      config.poisson_ratio = mc.poisson_ratio
    }
  }

  // IEPE types — field names must match config_parser.py ChannelConfig
  if (['iepe', 'iepe_input'].includes(channelType)) {
    config.terminal_config = mc.terminal_config ?? 'DEFAULT'
    config.iepe_coupling = mc.coupling  // UI: coupling → backend: iepe_coupling
    config.iepe_sensitivity = mc.sensitivity  // UI: sensitivity → backend: iepe_sensitivity
    config.iepe_current = (mc.excitation_current || 4) / 1000  // UI: mA → backend: Amps
  }

  // Counter types
  if (['counter', 'counter_input'].includes(channelType)) {
    config.counter_mode = mc.mode
    config.counter_edge = mc.edge
    config.initial_count = mc.initial_count
    config.direction = mc.count_direction
    // Encoder-specific fields (position mode)
    if (mc.mode === 'position') {
      config.decoding_type = mc.decoding_type ?? 'X4'
      config.pulses_per_revolution = mc.pulses_per_revolution ?? 1024
      config.z_index_enable = mc.z_index_enable ?? false
    }
  }

  // Resistance types
  if (['resistance', 'resistance_input'].includes(channelType)) {
    config.wiring = mc.wiring
    config.excitation_current_ma = mc.excitation_current_ma
    config.resistance_range = mc.resistance_range
  }

  // Bridge input
  if (channelType === 'bridge_input') {
    config.bridge_config = mc.bridge_config
    config.excitation_voltage = mc.excitation_voltage
    config.nominal_resistance = mc.nominal_resistance
    config.scaling_type = mc.scaling_type
    config.scale_slope = mc.scale_slope
    config.scale_offset = mc.scale_offset
  }

  // Frequency input
  if (channelType === 'frequency_input') {
    config.min_frequency = mc.min_frequency
    config.max_frequency = mc.max_frequency
    config.edge = mc.edge
    config.filter_enable = mc.filter_enable
  }

  // Voltage output
  if (['voltage_output', 'analog_output'].includes(channelType)) {
    config.voltage_range_min = mc.voltage_range_min
    config.voltage_range_max = mc.voltage_range_max
    config.scaling_type = mc.scaling_type
    config.scale_slope = mc.scale_slope
    config.scale_offset = mc.scale_offset
    config.scaled_min = mc.scaled_min
    config.scaled_max = mc.scaled_max
  }

  // Current output
  if (channelType === 'current_output') {
    config.current_range_ma_min = mc.current_range_ma_min
    config.current_range_ma_max = mc.current_range_ma_max
    config.four_twenty_scaling = mc.four_twenty_scaling
    config.scaled_min = mc.scaled_min
    config.scaled_max = mc.scaled_max
  }

  // Counter output
  if (channelType === 'counter_output') {
    config.initial_count = mc.initial_count
    config.direction = mc.direction
  }

  // Pulse output
  if (channelType === 'pulse_output') {
    config.pulse_frequency = mc.frequency
    config.pulse_duty_cycle = mc.duty_cycle
    config.idle_state = mc.idle_state
  }

  // Modbus register
  if (channelType === 'modbus_register') {
    const ec = editingConfig.value.config
    config.modbus_register_type = ec.modbus_register_type || 'holding'
    config.modbus_slave_id = ec.modbus_slave_id || undefined
    config.modbus_address = ec.modbus_address ?? 0
    config.modbus_data_type = ec.modbus_data_type || 'float32'
    config.modbus_byte_order = ec.modbus_byte_order || 'big'
    config.modbus_word_order = ec.modbus_word_order || 'big'
    config.modbus_scale = ec.modbus_scale ?? 1.0
    config.modbus_offset = ec.modbus_offset ?? 0.0
    config.modbus_register_count = ec.modbus_register_count || undefined
    config.modbus_register_index = ec.modbus_register_index ?? 0
    // Build physical_channel from Modbus fields so backend can parse it
    config.physical_channel = `modbus:${config.modbus_register_type}:${config.modbus_address}`
  }

  // Modbus coil
  if (channelType === 'modbus_coil') {
    const ec = editingConfig.value.config
    config.modbus_register_type = ec.modbus_register_type || 'coil'
    config.modbus_slave_id = ec.modbus_slave_id || undefined
    config.modbus_address = ec.modbus_address ?? 0
    config.invert = ec.invert ?? false
    // Build physical_channel from Modbus fields
    config.physical_channel = `modbus:${config.modbus_register_type}:${config.modbus_address}`
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
  if (isSaving.value) return  // Guard against double-click
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
  if (isReloading.value) return  // Guard against double-click
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  // Warn if there are unsaved changes
  let confirmMessage = 'Reload configuration from disk?\n\nThis will discard any changes made in the backend that haven\'t been saved to disk.'

  if (configDirty.value) {
    confirmMessage = 'WARNING: You have unsaved changes!\n\nReloading will discard all unsaved changes in both the UI and backend.\n\nReload anyway?'
  }

  if (!confirm(confirmMessage)) {
    return
  }

  isReloading.value = true
  mqtt.sendNodeCommand('config/reload', {})
  showFeedback('info', 'Reloading configuration from disk...')

  // Reset dirty flag and reload delay
  setTimeout(() => {
    isReloading.value = false
    configDirty.value = false
    showFeedback('success', 'Configuration reloaded from disk')
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
  mqtt.sendNodeCommand('config/list')
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

// Config update handler (registered in onMounted via unsubConfigUpdate)
function handleConfigUpdateResponse(response: any) {
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
    availableConfigs.value = response.configs as unknown as string[]
  }
}

// Get column headers based on active tab
const tableColumns = computed(() => {
  const baseColumns: Array<{ key: string; label: string; width: string; align?: string }> = [
    { key: 'enable', label: 'EN', width: '40px' },
    { key: 'type', label: 'TYPE', width: '50px' },
    { key: 'tag', label: 'TAG', width: '100px' },
    { key: 'channel', label: 'CHANNEL', width: '150px' },
    { key: 'description', label: 'DESCRIPTION', width: '200px' },
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
    case 'voltage_input':
      return [
        ...baseColumns,
        { key: 'terminal_config', label: 'TERM', width: '70px' },
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'current_input':
      return [
        ...baseColumns,
        { key: 'terminal_config', label: 'TERM', width: '70px' },
        { key: 'raw_min', label: 'RAW MIN', width: '70px' },
        { key: 'raw_max', label: 'RAW MAX', width: '70px' },
        { key: 'scaled_min', label: 'SCALED MIN', width: '80px' },
        { key: 'scaled_max', label: 'SCALED MAX', width: '80px' },
        { key: 'unit', label: 'UNIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'strain':
    case 'strain_input':
      return [
        ...baseColumns,
        { key: 'bridge', label: 'BRIDGE', width: '80px' },
        { key: 'gage', label: 'GAGE FACTOR', width: '90px' },
        { key: 'excitation', label: 'EXCIT', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'iepe':
    case 'iepe_input':
      return [
        ...baseColumns,
        { key: 'terminal_config', label: 'TERM', width: '70px' },
        { key: 'coupling', label: 'COUPLING', width: '70px' },
        { key: 'sensitivity', label: 'SENS (mV/g)', width: '90px' },
        { key: 'units', label: 'UNITS', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'counter':
    case 'counter_input':
      return [
        ...baseColumns,
        { key: 'mode', label: 'MODE', width: '100px' },
        { key: 'edge', label: 'EDGE', width: '70px' },
        { key: 'min_freq', label: 'MIN FREQ', width: '80px' },
        { key: 'max_freq', label: 'MAX FREQ', width: '80px' },
        { key: 'value', label: 'COUNT', width: '100px' },
        { key: 'reset', label: 'RESET', width: '60px' },
      ]
    case 'pulse_output':
      return [
        ...baseColumns,
        { key: 'frequency', label: 'FREQ (Hz)', width: '100px' },
        { key: 'duty_cycle', label: 'DUTY %', width: '80px' },
        { key: 'idle_state', label: 'IDLE', width: '60px' },
        { key: 'value', label: 'VALUE', width: '100px' },
      ]
    case 'resistance':
    case 'resistance_input':
      return [
        ...baseColumns,
        { key: 'wiring', label: 'WIRING', width: '70px' },
        { key: 'range', label: 'RANGE (Ω)', width: '80px', align: 'center' },
        { key: 'value', label: 'VALUE', width: '100px', align: 'right' },
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
    case 'bridge_input':
      return [
        ...baseColumns,
        { key: 'bridge_config', label: 'BRIDGE', width: '70px', align: 'center' },
        { key: 'excitation_voltage', label: 'EXCIT (V)', width: '80px', align: 'center' },
        { key: 'value', label: 'VALUE', width: '100px', align: 'right' },
      ]
    case 'frequency_input':
      return [
        ...baseColumns,
        { key: 'edge', label: 'EDGE', width: '70px', align: 'center' },
        { key: 'min_frequency', label: 'MIN (Hz)', width: '80px', align: 'center' },
        { key: 'max_frequency', label: 'MAX (Hz)', width: '80px', align: 'center' },
        { key: 'value', label: 'VALUE', width: '100px', align: 'right' },
      ]
    case 'counter_output':
      return [
        ...baseColumns,
        { key: 'initial_count', label: 'INIT COUNT', width: '80px', align: 'center' },
        { key: 'direction', label: 'DIR', width: '60px', align: 'center' },
        { key: 'value', label: 'VALUE', width: '100px', align: 'right' },
      ]
    default:
      return [
        ...baseColumns,
        { key: 'unit', label: 'UNITS', width: '60px', align: 'center' },
        { key: 'min', label: 'MIN', width: '60px', align: 'center' },
        { key: 'max', label: 'MAX', width: '60px', align: 'center' },
        { key: 'value', label: 'VALUE', width: '100px', align: 'center' },
      ]
  }
})

// Initialize enable states on mount and when channels change
onMounted(() => {
  initializeEnableStates()

  // Register MQTT callbacks (capture unsub functions for cleanup)
  unsubDiscovery = mqtt.onDiscovery((result) => {
    console.log('[ConfigTab] onDiscovery callback fired:', result?.success, result?.total_channels)
    if (userClosedDiscovery.value) {
      console.debug('[ConfigTab] Ignoring discovery result - user closed panel')
      return
    }
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
      expandAllDiscovery()
    } else {
      showFeedback('error', result.error || result.message || 'Discovery failed')
    }
  })

  unsubCrioResponse = mqtt.onCrioResponse((result) => {
    if (result.success) {
      showFeedback('success', result.message || 'Config pushed to cRIO')
    } else {
      showFeedback('error', result.message || 'Failed to push config to cRIO')
    }
  })

  unsubConfigUpdate = mqtt.onConfigUpdate(handleConfigUpdateResponse)

  unsubSystemUpdate = mqtt.onSystemUpdate((result: any) => {
    if (result.success) {
      showFeedback('success', `System settings updated: Scan ${result.scan_rate_hz} Hz, Publish ${result.publish_rate_hz} Hz`)
    } else {
      showFeedback('error', `Failed to update system settings: ${result.error || 'Unknown error'}`)
    }
  })
})

// Cleanup on unmount: cancel scan + unregister all MQTT callbacks
onBeforeUnmount(() => {
  if (mqtt.isScanning.value) {
    mqtt.cancelScan()
  }
  showDiscoveryPanel.value = false
  if (unsubDiscovery) { unsubDiscovery(); unsubDiscovery = null }
  if (unsubCrioResponse) { unsubCrioResponse(); unsubCrioResponse = null }
  if (unsubConfigUpdate) { unsubConfigUpdate(); unsubConfigUpdate = null }
  if (unsubSystemUpdate) { unsubSystemUpdate(); unsubSystemUpdate = null }
})

watch(() => Object.keys(store.channels), () => {
  initializeEnableStates()
})

// Watch for cRIO node selection changes to trigger channel discovery
watch(
  () => [newChannelForm.value.source_type, newChannelForm.value.node_id],
  ([sourceType, nodeId]) => {
    // When cRIO node is selected and we don't have discovery data for it, request discovery
    if (sourceType === 'crio' && nodeId && !crioDiscoveryChannels.value[nodeId]) {
      console.log('[ConfigurationTab] Requesting cRIO channel discovery for:', nodeId)
      mqtt.requestCrioChannelDiscovery(nodeId)
    }
  }
)

// Watch for physical channel selection to auto-set channel type from discovery
watch(
  () => newChannelForm.value.physical_channel,
  (physicalChannel) => {
    if (!physicalChannel || physicalChannel === '__manual__') return

    // Look up the channel type from discovery data
    const availableChannels = getAvailablePhysicalChannels()
    const selectedChannel = availableChannels.find(ch => ch.value === physicalChannel)

    if (selectedChannel?.type) {
      // Map discovery types to form types
      const typeMapping: Record<string, string> = {
        'analog_input': 'voltage',
        'voltage_input': 'voltage',
        'current_input': 'current',
        'thermocouple': 'thermocouple',
        'rtd': 'rtd',
        'analog_output': 'voltage_output',
        'voltage_output': 'voltage_output',
        'current_output': 'current_output',
        'digital_input': 'digital_input',
        'digital_output': 'digital_output',
        'counter': 'counter',
        'strain': 'strain'
      }
      const mappedType = typeMapping[selectedChannel.type] || selectedChannel.type
      if (mappedType && mappedType !== newChannelForm.value.channel_type) {
        console.log(`[ConfigurationTab] Auto-setting channel type: ${selectedChannel.type} -> ${mappedType}`)
        newChannelForm.value.channel_type = mappedType as ChannelType
      }
    }
  }
)
</script>

<template>
  <div class="config-tab">
    <!-- Search and Actions Bar -->
    <div class="actions-bar">
      <div class="left-actions">
        <!-- Auto Discovery button -->
        <button class="action-btn primary" @click="scanDevices" :disabled="isScanning || !hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'Auto-discover hardware devices'" :class="{ 'no-permission': !hasEditPermission }">
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
        <button class="action-btn" @click="openSystemSettings" :disabled="!hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'System settings (scan rate, publish rate)'" :class="{ 'no-permission': !hasEditPermission }">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
          Settings
          <span v-if="!hasEditPermission" class="lock-badge">🔒</span>
        </button>
        <button class="action-btn accent" @click="autoGenerateWidgets" :disabled="!hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'Auto-generate widgets for all channels based on channel type'" :class="{ 'no-permission': !hasEditPermission }">
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
          :class="{ active: editMode, 'no-permission': !hasEditPermission }"
          @click="toggleEditMode"
          :disabled="store.isAcquiring"
          :title="!hasEditPermission ? 'Login required to edit (Operator+)' : (store.isAcquiring ? 'Stop acquisition to edit' : (editMode ? 'Exit edit mode' : 'Enter edit mode'))"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          {{ editMode ? 'EDITING' : 'Edit' }}
          <span v-if="!hasEditPermission" class="lock-badge">🔒</span>
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

        <div class="toolbar-divider"></div>

        <!-- Group 3: File Operations -->
        <button
          class="action-btn primary"
          :class="{ dirty: configDirty, 'no-permission': !hasEditPermission }"
          @click="saveToFile()"
          :disabled="isSaving || !hasEditPermission"
          :title="!hasEditPermission ? 'Requires Operator or higher' : (projectFiles.currentProject.value
            ? `Save to project: ${projectFiles.currentProject.value}`
            : 'Create new project and save')"
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
        <button class="action-btn icon-btn" @click="reloadConfig" :disabled="isReloading || !mqtt.connected.value || !hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'Reload configuration from disk (discard unsaved changes)'">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/>
            <polyline points="1 20 1 14 7 14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </button>
        <button class="action-btn icon-btn" @click="exportProject" :disabled="isExporting || !hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'Export: save a timestamped copy to config/projects/'">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M8 17H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-3"/>
            <polyline points="12 15 12 22"/>
            <polyline points="9 19 12 22 15 19"/>
          </svg>
        </button>
        <button class="action-btn icon-btn" @click="triggerImport" :disabled="!hasEditPermission" :title="!hasEditPermission ? 'Requires Operator or higher' : 'Import a project file'">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
        </button>
        <input
          ref="importFileInput"
          type="file"
          accept=".json"
          style="display: none"
          @change="handleImportFile"
        />
        <button class="action-btn icon-btn" @click="validateConfiguration" :disabled="isValidating" title="Validate all channel configurations">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 11l3 3L22 4"/>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
          </svg>
        </button>

        <div class="toolbar-divider"></div>

        <!-- Group 5: Push (blue - sends to hardware) -->
        <button
          class="action-btn accent"
          :class="{ 'out-of-sync': hasCrioOutOfSync, 'no-permission': !hasEditPermission }"
          @click="applyConfigChanges"
          :disabled="!mqtt.connected.value || !hasEditPermission"
          :title="!hasEditPermission ? 'Requires Operator or higher' : (hasCrioOutOfSync ? 'Push config to hardware (cRIO out of sync!)' : 'Push channel config to hardware')"
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
        <div v-if="store.status?.simulation_mode" class="sim-mode-indicator" title="Running in simulation mode - no real hardware">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
          SIM MODE
        </div>
        <div v-if="crioStatus.state !== 'none'" class="crio-status-indicator" :class="crioStatus.state" :title="crioStatus.details">
          <svg v-if="crioStatus.state === 'offline'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
          </svg>
          <svg v-else-if="crioStatus.state === 'out-of-sync'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          {{ crioStatus.message }}
        </div>
      </div>
    </div>

    <!-- Channel Type Tabs + Status Bar -->
    <div class="type-tabs-row">
      <div class="type-tabs">
        <button
          v-for="tab in visibleTypeTabs"
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

    <!-- Feedback Message -->
    <Transition name="fade">
      <div v-if="feedbackMessage" class="feedback-message" :class="feedbackMessage.type">
        {{ feedbackMessage.text }}
      </div>
    </Transition>

    <!-- Populating Channels Indicator -->
    <Transition name="fade">
      <div v-if="isPopulating" class="populating-banner">
        <span class="spinner"></span>
        Populating channels — configuring hardware...
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

      <!-- OPC-UA Device Configuration (shown when OPC-UA tab is active) -->
      <OpcUaDeviceConfig
        v-if="activeTypeTab === 'opc_ua'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

      <!-- EtherNet/IP Device Configuration (shown when AB PLC tab is active) -->
      <EtherNetIPDeviceConfig
        v-if="activeTypeTab === 'ethernet_ip'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

      <!-- Compact FieldPoint Configuration (admin only) -->
      <CompactFieldpointDeviceConfig
        v-if="activeTypeTab === 'cfp'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

      <!-- GC Analyzer Node Configuration -->
      <GcNodeDeviceConfig
        v-if="activeTypeTab === 'gc'"
        :edit-mode="editMode"
        @dirty="markDirty"
      />

      <!-- Channel Table -->
      <!-- Batch Action Bar - appears when channels are selected -->
      <div v-if="selectedTableChannels.size > 0" class="batch-action-bar">
        <span class="batch-count">{{ selectedTableChannels.size }} selected</span>
        <button class="btn btn-sm" @click="toggleSelectedChannelsEnabled(true)" :disabled="!canEdit" title="Enable selected channels">
          Enable
        </button>
        <button class="btn btn-sm" @click="toggleSelectedChannelsEnabled(false)" :disabled="!canEdit" title="Disable selected channels">
          Disable
        </button>
        <button class="btn btn-sm btn-danger" @click="deleteSelectedChannels" :disabled="!canEdit" title="Delete selected channels">
          Delete
        </button>
        <button class="btn btn-sm" @click="selectedTableChannels.clear()">
          Clear Selection
        </button>
      </div>

      <div class="table-container" :class="{ 'with-panel': showConfigPanel }">
        <table class="channel-table">
          <thead>
            <!-- Signal Type Header Row -->
            <tr v-if="!['modbus', 'rest_api', 'opc_ua', 'ethernet_ip'].includes(activeTypeTab)" class="signal-type-row">
              <th :colspan="tableColumns.length + 4" class="signal-type-header">
                {{ activeTypeFullName }}
              </th>
            </tr>
            <tr class="column-headers-row" :class="{ 'has-signal-row': !['modbus', 'rest_api', 'opc_ua', 'ethernet_ip'].includes(activeTypeTab) }">
              <th class="col-select">
                <input
                  type="checkbox"
                  :checked="allVisibleSelected"
                  :indeterminate="someVisibleSelected"
                  @change="toggleSelectAll"
                  title="Select all visible channels"
                />
              </th>
              <th
                v-for="col in tableColumns"
                :key="col.key"
                :style="`width: ${col.width}; text-align: ${col.align || 'left'}`"
              >
                {{ col.label }}
              </th>
              <th class="col-alarm">ALARM</th>
              <th class="col-status-indicators" title="Configuration errors and warnings"></th>
              <th class="col-actions">CONFIG</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="([name, config], idx) in filteredChannels"
              :key="name"
              :class="['channel-row', getAlarmStatus(name), { selected: selectedChannel === name, disabled: channelEnabled[name] === false, 'batch-selected': selectedTableChannels.has(name), 'even-row': idx % 2 === 1 }]"
              @click="openChannelConfig(name)"
            >
              <td class="col-select" @click.stop>
                <input
                  type="checkbox"
                  :checked="selectedTableChannels.has(name)"
                  @change="toggleChannelSelection(name, $event)"
                />
              </td>
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
              <!-- TAG - channel identifier (editable) -->
              <td class="col-tag editable-cell" @click.stop>
                <input
                  type="text"
                  :value="name"
                  @blur="handleTagRename(name, ($event.target as HTMLInputElement).value)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                  @keyup.escape="($event.target as HTMLInputElement).value = name; ($event.target as HTMLInputElement).blur()"
                  class="inline-input tag-input"
                  placeholder="tag_name"
                  :disabled="!canEdit"
                />
                <span v-if="config.source_type === 'crio'" class="source-badge crio" title="Remote cRIO node">cRIO</span>
                <span v-else-if="config.source_type === 'opto22'" class="source-badge opto22" title="Remote Opto22 node">Opto22</span>
              </td>
              <!-- CHANNEL - physical channel with dropdown when discovery available -->
              <td class="col-channel editable-cell" @click.stop>
                <select
                  v-if="getAvailablePhysicalChannelsForType(config).length > 0"
                  :value="config.physical_channel || ''"
                  @change="updateChannelField(name, 'physical_channel', ($event.target as HTMLSelectElement).value)"
                  class="inline-select channel-select"
                  :disabled="!canEdit"
                  :title="`${getAvailablePhysicalChannelsForType(config).length} compatible channels found`"
                >
                  <option value="">-- Select Channel --</option>
                  <option
                    v-for="ch in getAvailablePhysicalChannelsForType(config)"
                    :key="ch.value"
                    :value="ch.value"
                    :disabled="ch.inUse"
                    :class="{ 'option-in-use': ch.inUse }"
                  >
                    {{ ch.label }}
                  </option>
                </select>
                <input
                  v-else
                  type="text"
                  :value="config.physical_channel || ''"
                  @blur="updateChannelField(name, 'physical_channel', ($event.target as HTMLInputElement).value)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                  class="inline-input channel-input"
                  :placeholder="getPhysicalChannelHint(config.source_type || 'local')"
                  :disabled="!canEdit"
                  :title="getAvailablePhysicalChannels().length > 0 ? 'No compatible channels found - manual entry' : 'No discovery data - manual entry'"
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
                    :value="config.thermocouple_type || ''"
                    @change="updateChannelField(name, 'thermocouple_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                    :class="{ 'select-error': !config.thermocouple_type }"
                  >
                    <option v-if="!config.thermocouple_type" value="" disabled>-</option>
                    <option v-for="tc in THERMOCOUPLE_TYPES" :key="tc.value" :value="tc.value">{{ tc.value }}</option>
                  </select>
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.cjc_source || ''"
                    @change="updateChannelField(name, 'cjc_source', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                    :class="{ 'select-warning': !config.cjc_source }"
                  >
                    <option v-if="!config.cjc_source" value="" disabled>-</option>
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
                    :value="config.rtd_type || ''"
                    @change="updateChannelField(name, 'rtd_type', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                    :class="{ 'select-error': !config.rtd_type }"
                  >
                    <option v-if="!config.rtd_type" value="" disabled>-</option>
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
              <template v-else-if="activeTypeTab === 'voltage_input'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.terminal_config || 'DEFAULT'"
                    @change="updateChannelField(name, 'terminal_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">{{ t.label }}</option>
                  </select>
                </td>
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
              <template v-else-if="activeTypeTab === 'current_input'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.terminal_config || 'DEFAULT'"
                    @change="updateChannelField(name, 'terminal_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">{{ t.label }}</option>
                  </select>
                </td>
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
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
                </td>
              </template>
              <template v-else-if="activeTypeTab === 'iepe'">
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.terminal_config || 'DEFAULT'"
                    @change="updateChannelField(name, 'terminal_config', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">{{ t.label }}</option>
                  </select>
                </td>
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
                <td class="col-value" :class="getAlarmStatus(name)">
                  <span class="value">{{ getCurrentValue(name) }}</span>
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
              <template v-else-if="activeTypeTab === 'pulse_output'">
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.pulse_frequency || 1000"
                    @change="updateChannelField(name, 'pulse_frequency', parseFloat(($event.target as HTMLInputElement).value) || 1000)"
                    class="inline-input"
                    placeholder="1000"
                    step="1"
                    min="0.1"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <input
                    type="number"
                    :value="config.pulse_duty_cycle || 50"
                    @change="updateChannelField(name, 'pulse_duty_cycle', parseFloat(($event.target as HTMLInputElement).value) || 50)"
                    class="inline-input"
                    placeholder="50"
                    step="1"
                    min="0"
                    max="100"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="editable-cell" @click.stop>
                  <select
                    :value="config.pulse_idle_state || 'LOW'"
                    @change="updateChannelField(name, 'pulse_idle_state', ($event.target as HTMLSelectElement).value)"
                    :disabled="!canEdit"
                  >
                    <option value="LOW">LOW</option>
                    <option value="HIGH">HIGH</option>
                  </select>
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
                <td class="editable-cell col-numeric" @click.stop>
                  <input
                    type="text"
                    :value="config.unit || '-'"
                    @change="updateChannelField(name, 'units', ($event.target as HTMLInputElement).value)"
                    class="inline-input"
                    :disabled="!canEdit"
                  />
                </td>
                <td class="col-numeric" :class="{ 'limit-error': config.low_limit != null && config.high_limit != null && Number(config.low_limit) > Number(config.high_limit) }" :title="config.low_limit != null && config.high_limit != null && Number(config.low_limit) > Number(config.high_limit) ? 'Low limit is greater than high limit' : ''">{{ config.low_limit ?? '-' }}</td>
                <td class="col-numeric" :class="{ 'limit-error': config.low_limit != null && config.high_limit != null && Number(config.low_limit) > Number(config.high_limit) }" :title="config.low_limit != null && config.high_limit != null && Number(config.low_limit) > Number(config.high_limit) ? 'High limit is less than low limit' : ''">{{ config.high_limit ?? '-' }}</td>
              </template>

              <!-- Value column - only for tabs that don't have built-in value display -->
              <td
                v-if="!['voltage_input', 'current_input', 'voltage_output', 'current_output', 'analog_output'].includes(activeTypeTab)"
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

              <!-- Inline error/warning indicators -->
              <td class="col-status-indicators" @click.stop>
                <span
                  v-if="getChannelErrors(name, config).length > 0"
                  class="status-indicator-icon error-icon"
                  :title="getChannelErrors(name, config).join('\n')"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                </span>
                <span
                  v-if="getChannelWarnings(name, config).length > 0"
                  class="status-indicator-icon warning-icon"
                  :title="getChannelWarnings(name, config).join('\n')"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                </span>
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
              <td :colspan="tableColumns.length + 4">
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
              <td :colspan="tableColumns.length + 4">
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
              <td :colspan="tableColumns.length + 4">
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
                  <select v-model="editingConfig.moduleConfig.tc_type" :class="{ 'select-error': !editingConfig.moduleConfig.tc_type }">
                    <option v-if="!editingConfig.moduleConfig.tc_type" value="" disabled>- Select TC Type -</option>
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
                  <select v-model="editingConfig.moduleConfig.cjc_source" :class="{ 'select-warning': !editingConfig.moduleConfig.cjc_source }">
                    <option v-if="!editingConfig.moduleConfig.cjc_source" value="" disabled>- Select CJC Source -</option>
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
                  <label>Terminal Configuration</label>
                  <select v-model="editingConfig.moduleConfig.terminal_config">
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">
                      {{ t.label }}
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
                  <select v-model="editingConfig.moduleConfig.rtd_type" :class="{ 'select-error': !editingConfig.moduleConfig.rtd_type }">
                    <option v-if="!editingConfig.moduleConfig.rtd_type" value="" disabled>- Select RTD Type -</option>
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
                  <label>Terminal Configuration</label>
                  <select v-model="editingConfig.moduleConfig.terminal_config">
                    <option v-for="t in TERMINAL_CONFIGS" :key="t.value" :value="t.value">
                      {{ t.label }}
                    </option>
                  </select>
                </div>
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

            <!-- Pulse/Counter Output settings -->
            <template v-if="editingConfig.config.channel_type === 'pulse_output'">
              <div class="config-section">
                <h4>Pulse Output Settings</h4>
                <div class="form-row">
                  <label>Frequency (Hz)</label>
                  <input type="number" v-model.number="editingConfig.config.pulse_frequency" min="0.1" step="1" placeholder="1000" />
                </div>
                <div class="form-row">
                  <label>Duty Cycle (%)</label>
                  <input type="number" v-model.number="editingConfig.config.pulse_duty_cycle" min="0" max="100" step="1" placeholder="50" />
                </div>
                <div class="form-row">
                  <label>Idle State</label>
                  <select v-model="editingConfig.config.pulse_idle_state">
                    <option value="LOW">LOW</option>
                    <option value="HIGH">HIGH</option>
                  </select>
                </div>
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
                <div class="form-row">
                  <label>Relay Type</label>
                  <select v-model="editingConfig.config.relay_type">
                    <option value="none">None (Transistor)</option>
                    <option value="spst">SPST Relay</option>
                    <option value="spdt">SPDT Relay</option>
                    <option value="ssr">Solid State Relay</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Momentary Pulse (ms)</label>
                  <input
                    type="number"
                    v-model.number="editingConfig.config.momentary_pulse_ms"
                    min="0"
                    step="100"
                    placeholder="0 = latching"
                  />
                  <span class="form-hint">0 = latching (stays ON). >0 = auto-OFF after N ms</span>
                </div>
              </div>
            </template>

            <!-- Modbus Register settings (also shown for CFP channels which use Modbus transport) -->
            <template v-if="editingConfig.config.channel_type === 'modbus_register' || editingConfig.config.source_type === 'cfp'">
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
                  <input type="number" v-model="editingConfig.config.low_limit" :class="{ 'input-error': editingConfig.config.low_limit != null && editingConfig.config.high_limit != null && Number(editingConfig.config.low_limit) > Number(editingConfig.config.high_limit) }" />
                </div>
                <div class="form-row half">
                  <label>High Alarm</label>
                  <input type="number" v-model="editingConfig.config.high_limit" :class="{ 'input-error': editingConfig.config.low_limit != null && editingConfig.config.high_limit != null && Number(editingConfig.config.low_limit) > Number(editingConfig.config.high_limit) }" />
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
                <button class="btn btn-secondary" @click="closeDiscoveryPanel" style="margin-top: 1rem;">Cancel</button>
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
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name), 'in-use': usedPhysicalChannels[channel.name] }"
                          @click="!usedPhysicalChannels[channel.name] && toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            :disabled="!!usedPhysicalChannels[channel.name]"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.channel_type">{{ formatChannelType(channel.channel_type) }}</span>
                          <span v-if="usedPhysicalChannels[channel.name]" class="used-badge">{{ usedPhysicalChannels[channel.name] }}</span>
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
                      :class="{ selected: selectedDiscoveryChannels.includes(channel.name), 'in-use': usedPhysicalChannels[channel.name] }"
                      @click="!usedPhysicalChannels[channel.name] && toggleDiscoveryChannel(channel.name)"
                    >
                      <input
                        type="checkbox"
                        :checked="selectedDiscoveryChannels.includes(channel.name)"
                        :disabled="!!usedPhysicalChannels[channel.name]"
                        @click.stop
                        @change="toggleDiscoveryChannel(channel.name)"
                      />
                      <span class="channel-name">{{ channel.name }}</span>
                      <span class="type-badge" :class="channel.channel_type">{{ formatChannelType(channel.channel_type) }}</span>
                      <span v-if="usedPhysicalChannels[channel.name]" class="used-badge">{{ usedPhysicalChannels[channel.name] }}</span>
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
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name), 'in-use': usedPhysicalChannels[channel.name] }"
                          @click="!usedPhysicalChannels[channel.name] && toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            :disabled="!!usedPhysicalChannels[channel.name]"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.channel_type">{{ formatChannelType(channel.channel_type) }}</span>
                          <span v-if="usedPhysicalChannels[channel.name]" class="used-badge">{{ usedPhysicalChannels[channel.name] }}</span>
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
                          :class="{ selected: selectedDiscoveryChannels.includes(channel.name), 'in-use': usedPhysicalChannels[channel.name] }"
                          @click="!usedPhysicalChannels[channel.name] && toggleDiscoveryChannel(channel.name)"
                        >
                          <input
                            type="checkbox"
                            :checked="selectedDiscoveryChannels.includes(channel.name)"
                            :disabled="!!usedPhysicalChannels[channel.name]"
                            @click.stop
                            @change="toggleDiscoveryChannel(channel.name)"
                          />
                          <span class="channel-name">{{ channel.name }}</span>
                          <span class="type-badge" :class="channel.channel_type">{{ formatChannelType(channel.channel_type) }}</span>
                          <span v-if="usedPhysicalChannels[channel.name]" class="used-badge">{{ usedPhysicalChannels[channel.name] }}</span>
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
      <div v-if="showAddChannelModal" class="discovery-overlay" @click.self="closeAddChannelModal">
        <div class="add-channel-dialog">
          <div class="discovery-header">
            <h3>Add New Channel</h3>
            <button class="close-btn" @click="closeAddChannelModal">
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
                <option value="pulse_output">Pulse Output</option>
                <option value="resistance">Resistance</option>
                <option value="digital_input">Digital Input</option>
                <option value="digital_output">Digital Output</option>
                <option value="voltage_output">Voltage Output</option>
                <option value="current_output">Current Output</option>
                <option value="modbus_register">Modbus Register</option>
                <option value="modbus_coil">Modbus Coil</option>
              </select>
              <span v-if="activeTypeTab !== 'all'" class="form-hint">
                Pre-selected based on current view. Change if needed.
              </span>
            </div>

            <!-- Node Selector (for remote sources - only shown when project_mode is crio or opto22) -->
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
              <label>Physical Channel</label>
              <!-- Always show a dropdown for physical channel selection -->
              <select
                v-model="newChannelForm.physical_channel"
                class="physical-channel-select"
                :disabled="isScanning && getAvailablePhysicalChannelsForType().length === 0"
              >
                <option v-if="isScanning && getAvailablePhysicalChannelsForType().length === 0" value="" disabled>
                  Scanning for hardware...
                </option>
                <option v-else-if="getAvailablePhysicalChannelsForType().length === 0" value="" disabled>
                  No compatible channels found
                </option>
                <option v-else value="">-- Select channel --</option>
                <option
                  v-for="ch in getAvailablePhysicalChannelsForType()"
                  :key="ch.value"
                  :value="ch.value"
                  :disabled="ch.inUse"
                  :class="{ 'option-in-use': ch.inUse }"
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
              <!-- Hints -->
              <span class="form-hint" v-if="isScanning">
                Discovering hardware...
              </span>
              <span class="form-hint" v-else-if="getAvailablePhysicalChannelsForType().length > 0">
                {{ getAvailablePhysicalChannelsForType().length }} compatible {{ newChannelForm.channel_type }} channels found
              </span>
              <span class="form-hint" v-else-if="getAvailablePhysicalChannels().length > 0">
                No compatible {{ newChannelForm.channel_type }} channels.
                <button class="btn-link" @click="scanDevices">Re-scan</button>
              </span>
              <span class="form-hint" v-else>
                No hardware found.
                <button class="btn-link" @click="scanDevices">Re-scan</button>
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
            <button class="btn btn-secondary" @click="closeAddChannelModal">Cancel</button>
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
            <div class="settings-section" v-if="projectFiles.currentProject.value">
              <h4>Project</h4>
              <div class="form-row">
                <label>Project Title</label>
                <input
                  type="text"
                  v-model="systemSettingsForm.project_name"
                  placeholder="Enter project title"
                  maxlength="100"
                />
                <span class="form-hint">Display name shown in the control bar</span>
              </div>
            </div>

            <div class="settings-section">
              <h4>System Architecture</h4>
              <div class="form-row">
                <label>Project Mode</label>
                <select v-model="systemSettingsForm.project_mode" class="mode-select">
                  <option value="cdaq">cDAQ (PC is controller)</option>
                  <option value="crio">cRIO (cRIO is PLC)</option>
                  <option value="opto22">Opto22 (groov EPIC is PLC)</option>
                  <option value="cfp">CFP (CompactFieldPoint via Modbus)</option>
                </select>
                <span class="form-hint">
                  {{ systemSettingsForm.project_mode === 'cdaq'
                    ? 'PC handles all control logic locally'
                    : systemSettingsForm.project_mode === 'crio'
                      ? 'cRIO runs autonomously - PC is HMI only'
                      : systemSettingsForm.project_mode === 'cfp'
                        ? 'CompactFieldPoint I/O via Modbus — PC handles all control logic'
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

            <div class="settings-section">
              <h4>Watchdog Output</h4>
              <span class="form-hint" style="margin-bottom: 8px; display: block;">
                Toggles a digital output at a fixed rate so an external safety relay can detect the edge node is alive. Pushed to cRIO and Opto22 nodes.
              </span>
              <div class="form-row">
                <label>Enabled</label>
                <label class="toggle-label">
                  <input
                    type="checkbox"
                    v-model="systemSettingsForm.watchdog_output.enabled"
                  />
                  <span>{{ systemSettingsForm.watchdog_output.enabled ? 'Active' : 'Disabled' }}</span>
                </label>
              </div>
              <div class="form-row" v-if="systemSettingsForm.watchdog_output.enabled">
                <label>Output Channel</label>
                <select v-model="systemSettingsForm.watchdog_output.channel">
                  <option value="">-- Select Output --</option>
                  <option
                    v-for="ch in outputChannels"
                    :key="ch.name"
                    :value="ch.name"
                  >{{ ch.name }}</option>
                </select>
                <span class="form-hint">Digital output to pulse</span>
              </div>
              <div class="form-row" v-if="systemSettingsForm.watchdog_output.enabled">
                <label>Pulse Rate (Hz)</label>
                <input
                  type="number"
                  v-model.number="systemSettingsForm.watchdog_output.frequency_hz"
                  min="0.1"
                  max="10"
                  step="0.1"
                />
                <span class="form-hint">Toggle frequency (1 Hz = 1 full cycle/sec)</span>
              </div>
            </div>

            <div class="settings-section">
              <h4>Output Safety (ISA-101)</h4>
              <span class="form-hint" style="margin-bottom: 8px; display: block;">
                Require operator confirmation before energizing digital outputs and relays.
              </span>
              <div class="form-row">
                <label>Confirm Output Changes</label>
                <label class="toggle-label">
                  <input
                    type="checkbox"
                    v-model="systemSettingsForm.confirm_output_changes"
                  />
                  <span>{{ systemSettingsForm.confirm_output_changes ? 'Required' : 'Off' }}</span>
                </label>
              </div>
            </div>

            <div class="settings-section">
              <h4>Alarm Flood Detection (ISA-18.2)</h4>
              <span class="form-hint" style="margin-bottom: 8px; display: block;">
                Suppresses non-critical alarms when the alarm rate exceeds the threshold within the time window.
              </span>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Flood Threshold</label>
                  <input
                    type="number"
                    v-model.number="systemSettingsForm.alarm_flood.threshold"
                    min="2"
                    max="100"
                  />
                  <span class="form-hint">Alarms to trigger flood</span>
                </div>
                <div class="form-row half">
                  <label>Time Window (s)</label>
                  <input
                    type="number"
                    v-model.number="systemSettingsForm.alarm_flood.window_s"
                    min="10"
                    max="600"
                  />
                  <span class="form-hint">Detection window (seconds)</span>
                </div>
              </div>
            </div>

            <!-- ============================================ -->
            <!-- SMS Notifications (Twilio) -->
            <!-- ============================================ -->
            <div class="settings-section">
              <h4>SMS Notifications (Twilio)</h4>
              <div class="form-row">
                <label>Enable SMS</label>
                <label class="toggle-label">
                  <input type="checkbox" v-model="systemSettingsForm.notifications.twilio.enabled" />
                  <span>{{ systemSettingsForm.notifications.twilio.enabled ? 'Active' : 'Off' }}</span>
                </label>
              </div>

              <template v-if="systemSettingsForm.notifications.twilio.enabled">
                <!-- Connection -->
                <div class="form-row">
                  <label>Account SID</label>
                  <input type="text" v-model="systemSettingsForm.notifications.twilio.account_sid" placeholder="ACxxxxxxxxxx" />
                </div>
                <div class="form-row">
                  <label>Auth Token</label>
                  <input type="password" v-model="systemSettingsForm.notifications.twilio.auth_token" placeholder="Auth token" />
                </div>
                <div class="form-row">
                  <label>From Number</label>
                  <input type="text" v-model="systemSettingsForm.notifications.twilio.from_number" placeholder="+1234567890" />
                </div>
                <div class="form-row">
                  <label>To Numbers</label>
                  <input type="text" v-model="notifTwilioToNumbers" placeholder="+1234567890, +0987654321" />
                  <span class="form-hint">Comma-separated phone numbers</span>
                </div>

                <!-- Trigger Rules -->
                <h5 style="margin: 12px 0 6px; color: var(--text-secondary);">Trigger Rules</h5>
                <div class="form-row">
                  <label>Severity</label>
                  <div class="checkbox-group">
                    <label v-for="sev in (['critical', 'high', 'medium', 'low'] as const)" :key="sev" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.twilio.rules.severities.includes(sev)" @change="toggleSeverity(systemSettingsForm.notifications.twilio.rules, sev)" />
                      <span :class="'sev-' + sev">{{ sev.charAt(0).toUpperCase() + sev.slice(1) }}</span>
                    </label>
                  </div>
                </div>
                <div class="form-row">
                  <label>Events</label>
                  <div class="checkbox-group">
                    <label v-for="evt in [{ id: 'triggered', label: 'New Alarm' }, { id: 'cleared', label: 'Cleared' }, { id: 'acknowledged', label: 'Acknowledged' }, { id: 'alarm_flood', label: 'Alarm Flood' }]" :key="evt.id" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.twilio.rules.event_types.includes(evt.id as any)" @change="toggleEventType(systemSettingsForm.notifications.twilio.rules, evt.id)" />
                      <span>{{ evt.label }}</span>
                    </label>
                  </div>
                </div>
                <div class="form-row" v-if="alarmGroupList.length > 0">
                  <label>Groups</label>
                  <div class="checkbox-group">
                    <span class="form-hint" style="margin-bottom: 4px;">Empty = all groups</span>
                    <label v-for="grp in alarmGroupList" :key="grp" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.twilio.rules.groups.includes(grp)" @change="toggleGroup(systemSettingsForm.notifications.twilio.rules, grp)" />
                      <span>{{ grp }}</span>
                    </label>
                  </div>
                </div>

                <!-- Alarm selection -->
                <div class="form-row">
                  <label>Alarm Selection</label>
                  <select v-model="systemSettingsForm.notifications.twilio.rules.alarm_select_mode" class="mode-select">
                    <option value="all">All matching rules</option>
                    <option value="include_only">Only selected alarms</option>
                    <option value="exclude">All except excluded</option>
                  </select>
                </div>
                <div v-if="systemSettingsForm.notifications.twilio.rules.alarm_select_mode !== 'all'" class="alarm-select-list">
                  <div v-for="alarm in configuredAlarmList" :key="alarm.id" class="alarm-select-item">
                    <label class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.twilio.rules.alarm_ids.includes(alarm.id)" @change="toggleAlarmId(systemSettingsForm.notifications.twilio.rules, alarm.id)" />
                      <span>{{ alarm.name }}</span>
                      <span class="alarm-select-meta">{{ alarm.channel }} &middot; <span :class="'sev-' + alarm.severity">{{ alarm.severity }}</span></span>
                    </label>
                  </div>
                  <div v-if="configuredAlarmList.length === 0" class="form-hint">No enabled alarms configured</div>
                </div>

                <button class="btn btn-sm btn-secondary" style="margin-top: 8px;" @click="sendTestNotification('twilio')" :disabled="notifSendingTest">
                  {{ notifSendingTest ? 'Sending...' : 'Send Test SMS' }}
                </button>
              </template>
            </div>

            <!-- ============================================ -->
            <!-- Email Notifications (SMTP) -->
            <!-- ============================================ -->
            <div class="settings-section">
              <h4>Email Notifications (SMTP)</h4>
              <div class="form-row">
                <label>Enable Email</label>
                <label class="toggle-label">
                  <input type="checkbox" v-model="systemSettingsForm.notifications.email.enabled" />
                  <span>{{ systemSettingsForm.notifications.email.enabled ? 'Active' : 'Off' }}</span>
                </label>
              </div>

              <template v-if="systemSettingsForm.notifications.email.enabled">
                <!-- Connection -->
                <div class="form-row">
                  <label>SMTP Host</label>
                  <input type="text" v-model="systemSettingsForm.notifications.email.smtp_host" placeholder="smtp.gmail.com" />
                </div>
                <div class="form-row">
                  <label>SMTP Port</label>
                  <input type="number" v-model.number="systemSettingsForm.notifications.email.smtp_port" min="1" max="65535" />
                </div>
                <div class="form-row">
                  <label>Use TLS</label>
                  <label class="toggle-label">
                    <input type="checkbox" v-model="systemSettingsForm.notifications.email.use_tls" />
                    <span>{{ systemSettingsForm.notifications.email.use_tls ? 'Yes' : 'No' }}</span>
                  </label>
                </div>
                <div class="form-row">
                  <label>Username</label>
                  <input type="text" v-model="systemSettingsForm.notifications.email.username" placeholder="user@example.com" />
                </div>
                <div class="form-row">
                  <label>Password</label>
                  <input type="password" v-model="systemSettingsForm.notifications.email.password" placeholder="App password" />
                </div>
                <div class="form-row">
                  <label>From Address</label>
                  <input type="text" v-model="systemSettingsForm.notifications.email.from_address" placeholder="alerts@example.com" />
                </div>
                <div class="form-row">
                  <label>To Addresses</label>
                  <input type="text" v-model="notifEmailToAddresses" placeholder="admin@example.com, ops@example.com" />
                  <span class="form-hint">Comma-separated email addresses</span>
                </div>

                <!-- Trigger Rules -->
                <h5 style="margin: 12px 0 6px; color: var(--text-secondary);">Trigger Rules</h5>
                <div class="form-row">
                  <label>Severity</label>
                  <div class="checkbox-group">
                    <label v-for="sev in (['critical', 'high', 'medium', 'low'] as const)" :key="sev" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.email.rules.severities.includes(sev)" @change="toggleSeverity(systemSettingsForm.notifications.email.rules, sev)" />
                      <span :class="'sev-' + sev">{{ sev.charAt(0).toUpperCase() + sev.slice(1) }}</span>
                    </label>
                  </div>
                </div>
                <div class="form-row">
                  <label>Events</label>
                  <div class="checkbox-group">
                    <label v-for="evt in [{ id: 'triggered', label: 'New Alarm' }, { id: 'cleared', label: 'Cleared' }, { id: 'acknowledged', label: 'Acknowledged' }, { id: 'alarm_flood', label: 'Alarm Flood' }]" :key="evt.id" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.email.rules.event_types.includes(evt.id as any)" @change="toggleEventType(systemSettingsForm.notifications.email.rules, evt.id)" />
                      <span>{{ evt.label }}</span>
                    </label>
                  </div>
                </div>
                <div class="form-row" v-if="alarmGroupList.length > 0">
                  <label>Groups</label>
                  <div class="checkbox-group">
                    <span class="form-hint" style="margin-bottom: 4px;">Empty = all groups</span>
                    <label v-for="grp in alarmGroupList" :key="grp" class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.email.rules.groups.includes(grp)" @change="toggleGroup(systemSettingsForm.notifications.email.rules, grp)" />
                      <span>{{ grp }}</span>
                    </label>
                  </div>
                </div>

                <!-- Alarm selection -->
                <div class="form-row">
                  <label>Alarm Selection</label>
                  <select v-model="systemSettingsForm.notifications.email.rules.alarm_select_mode" class="mode-select">
                    <option value="all">All matching rules</option>
                    <option value="include_only">Only selected alarms</option>
                    <option value="exclude">All except excluded</option>
                  </select>
                </div>
                <div v-if="systemSettingsForm.notifications.email.rules.alarm_select_mode !== 'all'" class="alarm-select-list">
                  <div v-for="alarm in configuredAlarmList" :key="alarm.id" class="alarm-select-item">
                    <label class="checkbox-inline">
                      <input type="checkbox" :checked="systemSettingsForm.notifications.email.rules.alarm_ids.includes(alarm.id)" @change="toggleAlarmId(systemSettingsForm.notifications.email.rules, alarm.id)" />
                      <span>{{ alarm.name }}</span>
                      <span class="alarm-select-meta">{{ alarm.channel }} &middot; <span :class="'sev-' + alarm.severity">{{ alarm.severity }}</span></span>
                    </label>
                  </div>
                  <div v-if="configuredAlarmList.length === 0" class="form-hint">No enabled alarms configured</div>
                </div>

                <button class="btn btn-sm btn-secondary" style="margin-top: 8px;" @click="sendTestNotification('email')" :disabled="notifSendingTest">
                  {{ notifSendingTest ? 'Sending...' : 'Send Test Email' }}
                </button>
              </template>
            </div>

            <!-- ============================================ -->
            <!-- Notification Rate Limits -->
            <!-- ============================================ -->
            <div class="settings-section" v-if="systemSettingsForm.notifications.twilio.enabled || systemSettingsForm.notifications.email.enabled">
              <h4>Notification Limits</h4>
              <div class="form-row">
                <label>Cooldown (seconds)</label>
                <input type="number" v-model.number="systemSettingsForm.notifications.cooldown_seconds" min="60" max="3600" />
                <span class="form-hint">Minimum time between notifications for the same alarm</span>
              </div>
              <div class="form-row">
                <label>Daily Limit</label>
                <input type="number" v-model.number="systemSettingsForm.notifications.daily_limit" min="1" max="1000" />
                <span class="form-hint">Maximum notifications per day (resets at midnight)</span>
              </div>
              <div class="form-row">
                <label>Quiet Hours</label>
                <label class="toggle-label">
                  <input type="checkbox" v-model="systemSettingsForm.notifications.quiet_hours_enabled" />
                  <span>{{ systemSettingsForm.notifications.quiet_hours_enabled ? 'Active' : 'Off' }}</span>
                </label>
              </div>
              <template v-if="systemSettingsForm.notifications.quiet_hours_enabled">
                <div class="form-row">
                  <label>Start Time</label>
                  <input type="time" v-model="systemSettingsForm.notifications.quiet_hours_start" />
                </div>
                <div class="form-row">
                  <label>End Time</label>
                  <input type="time" v-model="systemSettingsForm.notifications.quiet_hours_end" />
                </div>
                <span class="form-hint">Critical alarms always send during quiet hours</span>
              </template>
            </div>

            <div class="settings-info">
              <div class="info-row">
                <span class="info-label">Status:</span>
                <span class="info-value" :class="{ online: store.status?.status === 'online' }">
                  {{ store.status?.status || 'Unknown' }}
                </span>
              </div>
              <div class="info-row">
                <span class="info-label">Channels:</span>
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

    <!-- Auto-Gen Widgets Modal -->
    <Transition name="modal">
      <div v-if="showAutoGenModal" class="discovery-overlay" @click.self="showAutoGenModal = false">
        <div class="settings-dialog" style="max-width: 520px;">
          <div class="discovery-header">
            <h3>Auto-Generate Widgets</h3>
            <button class="close-btn" @click="showAutoGenModal = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="settings-content">
            <div class="auto-gen-info">
              <strong>{{ getAutoGenChannelCount() }}</strong> channels match current filters.
              Widgets will be placed on the Overview page.
            </div>

            <div class="settings-section">
              <h4>Channel Types to Include</h4>
              <div class="type-checkbox-grid">
                <label class="type-checkbox-select-all">
                  <button
                    class="btn btn-sm"
                    @click="setAllAutoGenTypes(true)"
                  >Select All</button>
                  <button
                    class="btn btn-sm"
                    @click="setAllAutoGenTypes(false)"
                  >Clear All</button>
                </label>
                <label
                  v-for="type in availableChannelTypes"
                  :key="type.id"
                  class="type-checkbox"
                >
                  <input
                    type="checkbox"
                    :checked="autoGenForm.channelTypes.includes(type.id)"
                    @change="toggleAutoGenType(type.id)"
                  />
                  <span class="type-icon">{{ type.icon }}</span>
                  <span>{{ type.label }}</span>
                </label>
              </div>
            </div>

            <div class="settings-section">
              <h4>Options</h4>
              <div class="form-row">
                <label>
                  <input
                    type="checkbox"
                    v-model="autoGenForm.onlyEnabled"
                  />
                  Only include enabled channels
                </label>
              </div>
              <div class="form-row">
                <label>Widget Size</label>
                <select v-model="autoGenForm.widgetSize">
                  <option value="compact">Compact (small)</option>
                  <option value="normal">Normal</option>
                  <option value="large">Large</option>
                </select>
              </div>
              <div class="form-row">
                <label>Widgets per Row</label>
                <select v-model.number="autoGenForm.columns">
                  <option :value="2">2 columns</option>
                  <option :value="3">3 columns</option>
                  <option :value="4">4 columns</option>
                  <option :value="6">6 columns</option>
                  <option :value="8">8 columns</option>
                </select>
              </div>
            </div>
          </div>

          <div class="discovery-footer">
            <button class="btn btn-secondary" @click="showAutoGenModal = false">Cancel</button>
            <button
              class="btn btn-primary"
              @click="executeAutoGenWidgets"
              :disabled="getAutoGenChannelCount() === 0"
            >
              Generate {{ getAutoGenChannelCount() }} Widgets
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

    <!-- Validation Report Modal -->
    <Transition name="modal">
      <div v-if="showValidationModal" class="discovery-overlay" @click.self="closeValidationModal">
        <div class="validation-dialog">
          <div class="discovery-header">
            <h3>Configuration Validation Report</h3>
            <button class="close-btn" @click="closeValidationModal">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div v-if="validationReport" class="validation-content">
            <!-- Summary -->
            <div class="validation-summary">
              <div class="summary-stat">
                <span class="stat-label">Total Channels:</span>
                <span class="stat-value">{{ validationReport.totalChannels }}</span>
              </div>
              <div class="summary-stat">
                <span class="stat-label">Valid Channels:</span>
                <span class="stat-value success">{{ validationReport.validChannels }}</span>
              </div>
              <div class="summary-stat">
                <span class="stat-label">Channels with Issues:</span>
                <span class="stat-value warning">{{ validationReport.totalChannels - validationReport.validChannels }}</span>
              </div>
              <div class="summary-stat">
                <span class="stat-label">Total Issues:</span>
                <span class="stat-value">{{ validationReport.issues.length }}</span>
              </div>
            </div>

            <!-- Issue breakdown -->
            <div class="issue-breakdown">
              <div class="breakdown-stat error">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="15" y1="9" x2="9" y2="15"/>
                  <line x1="9" y1="9" x2="15" y2="15"/>
                </svg>
                {{ validationReport.issues.filter(i => i.severity === 'error').length }} Errors
              </div>
              <div class="breakdown-stat warning">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/>
                  <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                {{ validationReport.issues.filter(i => i.severity === 'warning').length }} Warnings
              </div>
              <div class="breakdown-stat info">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="12" y1="16" x2="12" y2="12"/>
                  <line x1="12" y1="8" x2="12.01" y2="8"/>
                </svg>
                {{ validationReport.issues.filter(i => i.severity === 'info').length }} Info
              </div>
            </div>

            <!-- Issues list -->
            <div v-if="validationReport.issues.length === 0" class="no-issues">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
              </svg>
              <p>No issues found!</p>
              <p class="hint">All {{ validationReport.totalChannels }} channels passed validation.</p>
            </div>

            <div v-else class="issues-list">
              <div
                v-for="(issue, idx) in validationReport.issues"
                :key="idx"
                class="issue-item"
                :class="issue.severity"
              >
                <div class="issue-icon">
                  <svg v-if="issue.severity === 'error'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="15" y1="9" x2="9" y2="15"/>
                    <line x1="9" y1="9" x2="15" y2="15"/>
                  </svg>
                  <svg v-else-if="issue.severity === 'warning'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="16" x2="12" y2="12"/>
                    <line x1="12" y1="8" x2="12.01" y2="8"/>
                  </svg>
                </div>
                <div class="issue-details">
                  <div class="issue-header">
                    <span class="issue-channel">{{ issue.channel }}</span>
                    <span class="issue-category">{{ issue.category }}</span>
                  </div>
                  <div class="issue-message">{{ issue.message }}</div>
                  <div v-if="issue.fix" class="issue-fix">Fix: {{ issue.fix }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="validation-footer">
            <button class="btn btn-primary" @click="closeValidationModal">Close</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Import Preview Modal -->
    <Transition name="modal">
      <div v-if="showImportPreview" class="discovery-overlay" @click.self="cancelImport">
        <div class="import-preview-dialog">
          <div class="discovery-header">
            <h3>Import Preview</h3>
            <button class="close-btn" @click="cancelImport">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div v-if="importAnalysis" class="import-preview-content">
            <!-- Summary -->
            <div class="import-summary">
              <div class="summary-header">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <div>
                  <h4>Importing {{ importAnalysis.totalChannels }} channel{{ importAnalysis.totalChannels !== 1 ? 's' : '' }}</h4>
                  <p class="summary-hint">Review the changes before confirming</p>
                </div>
              </div>

              <div class="import-stats">
                <div class="import-stat new">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19"/>
                    <line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                  {{ importAnalysis.totalChannels }} Channels
                </div>
              </div>
            </div>

            <!-- Info notice: import replaces everything -->
            <div class="import-warnings" v-if="Object.keys(store.channels).length > 0">
              <div class="warning-section">
                <div class="warning-header">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  <strong>Current project ({{ Object.keys(store.channels).length }} channels) will be replaced</strong>
                </div>
              </div>
            </div>

            <!-- Backup notice -->
            <div class="backup-notice">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
              A backup of your current configuration will be created before import
            </div>
          </div>

          <div class="import-preview-footer">
            <button class="btn btn-secondary" @click="cancelImport">Cancel</button>
            <button
              class="btn btn-primary"
              @click="confirmImport"
            >
              Confirm Import
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
  background: var(--bg-primary);
}

/* Signal Type Header Row - spans all columns, fixed in thead */
.signal-type-row .signal-type-header {
  text-align: left;
  font-size: 0.7rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 6px 8px;
  border-bottom: 1px solid var(--bg-widget);
}

/* Channel Type Tabs Row (tabs + status) */
.type-tabs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
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
  background: var(--bg-surface);
  color: var(--text-secondary);
}

.status-item.mqtt {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
}

.status-item.mqtt.connected {
  background: var(--indicator-success-bg);
  color: var(--indicator-success-text);
}

.theme-toggle-small {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: var(--bg-surface);
  border: 1px solid var(--bg-hover);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.theme-toggle-small:hover {
  background: var(--bg-hover);
  color: var(--text-bright);
}

.type-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--text-muted);
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

.type-tab:hover {
  background: var(--bg-widget);
  color: var(--text-secondary);
}

.type-tab.active {
  background: var(--color-accent-bg);
  border-color: var(--color-accent);
  color: var(--color-accent-light);
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
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-muted);
}

.search-input {
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 0.85rem;
  width: 200px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-dim);
}

/* Main Content */
.main-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Table Container — scrollable wrapper with sticky header */
.table-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 16px;
  transition: flex 0.3s;
  scrollbar-width: thin;
  scrollbar-color: var(--border-color) var(--bg-primary);
}

.table-container::-webkit-scrollbar {
  width: 8px;
}

.table-container::-webkit-scrollbar-track {
  background: var(--bg-primary);
}

.table-container::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 4px;
}

.table-container::-webkit-scrollbar-thumb:hover {
  background: var(--border-light);
}

.table-container.with-panel {
  flex: 0.6;
}

.channel-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.75rem;
  table-layout: fixed;
}

.channel-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
}

/* Signal type header row sticks at top */
.channel-table thead .signal-type-row th {
  z-index: 3;
}

/* Column headers offset below signal-type-row when it's present */
.channel-table thead .column-headers-row.has-signal-row th {
  top: 25px;
}

/* Column headers */
.column-headers-row th {
  background: var(--bg-secondary);
  padding: 8px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
}

/* When signal type row is present, column headers are offset via sticky top (see above) */

/* CONFIG column - normal column like the others */
.column-headers-row th.col-actions {
  text-align: center;
  width: 70px;
  min-width: 70px;
}

.channel-table td {
  padding: 6px;
  border-bottom: 1px solid var(--bg-widget);
  color: var(--text-bright);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* CONFIG data cells - normal column like the others */
.channel-table td.col-actions {
  text-align: center;
  width: 70px;
  min-width: 70px;
}

.channel-row {
  cursor: pointer;
}

.channel-row td {
  background: var(--bg-secondary);
  transition: background 0.15s;
}

.channel-row.even-row td {
  background: var(--bg-widget);
}

.channel-row:hover td {
  background: var(--bg-hover);
}

.channel-row.selected td {
  background: var(--color-accent-bg);
}

.channel-row.warning td {
  background: rgba(251, 191, 36, 0.1);
}

.channel-row.alarm td {
  background: rgba(239, 68, 68, 0.15);
}

/* Column styling */
.col-select { width: 32px; text-align: center; }
.col-enable { text-align: center; }
.col-tag { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; font-weight: 600; }
.col-actions { width: 50px; text-align: center; }

/* Batch selection styling */
.channel-row.batch-selected td {
  background: rgba(59, 130, 246, 0.15);
}

.channel-row.batch-selected:hover td {
  background: rgba(59, 130, 246, 0.25);
}

/* Batch action bar */
.batch-action-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border, #334155);
  border-radius: 6px;
  margin-bottom: 8px;
}

.batch-count {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-accent-light);
  margin-right: 8px;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 0.75rem;
  border-radius: 4px;
  background: var(--bg-hover);
  border: 1px solid var(--border, #475569);
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-sm:hover:not(:disabled) {
  background: var(--border-heavy);
  color: var(--text-primary, #e2e8f0);
}

.btn-sm.btn-danger {
  color: var(--color-error-light);
}

.btn-sm.btn-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.3);
}

.btn-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

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
  color: var(--color-success);
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.source-badge.opto22 {
  background: rgba(251, 191, 36, 0.2);
  color: var(--color-warning);
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

.type-badge.thermocouple { background: #1e3a8a; color: #93c5fd; }  /* Blue */
.type-badge.rtd { background: #134e4a; color: #5eead4; }            /* Teal */
.type-badge.voltage { background: #312e81; color: #a5b4fc; }        /* Indigo */
.type-badge.current { background: #4c1d95; color: #c4b5fd; }        /* Violet */
.type-badge.strain { background: #701a75; color: #f0abfc; }         /* Fuchsia */
.type-badge.iepe { background: #831843; color: #f9a8d4; }           /* Pink */
.type-badge.counter { background: var(--bg-surface); color: var(--text-secondary); }        /* Slate */
.type-badge.resistance { background: #3f3f46; color: #d4d4d8; }     /* Zinc */
.type-badge.digital_input { background: var(--indicator-success-bg); color: var(--indicator-success-text); }  /* Green */
.type-badge.digital_output { background: #064e3b; color: #6ee7b7; } /* Emerald */
.type-badge.voltage_output { background: #0c4a6e; color: #7dd3fc; } /* Sky */
.type-badge.current_output { background: #3b0764; color: #d8b4fe; } /* Purple */
.type-badge.analog_output { background: #0c4a6e; color: #7dd3fc; }  /* Sky (legacy) */
.type-badge.analog_input { background: #312e81; color: #a5b4fc; }   /* Indigo (same as voltage) */
.type-badge.voltage_input { background: #312e81; color: #a5b4fc; }  /* Indigo (same as voltage) */
.type-badge.current_input { background: #4c1d95; color: #c4b5fd; }  /* Violet (same as current) */

/* Numeric column centering (ALL tab) */
.channel-table td.col-numeric {
  text-align: center;
}
.channel-table td.col-numeric .inline-input {
  text-align: center;
}

/* Value Cell */
.channel-table td.col-value {
  text-align: center;
}
.col-value .value {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}

.col-value .unit {
  margin-left: 4px;
  font-size: 0.65rem;
  color: var(--text-muted);
}

.col-value.warning .value { color: #fbbf24; }
.col-value.alarm .value { color: var(--color-error); }

/* Raw/Scaled value columns */
.col-value.raw {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.col-value.scaled {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-accent-light);
}

.col-value.scaled.warning { color: #fbbf24; }
.col-value.scaled.alarm { color: var(--color-error); }

/* Error status styles for channel values */
.col-value.stale .value {
  color: var(--text-muted);
}

.col-value.disconnected .value {
  color: var(--color-warning);
  font-style: italic;
}

.col-value.open-tc .value {
  color: var(--color-error-dark);
  font-style: italic;
}

.col-value.overflow .value {
  color: var(--color-accent-light);
  font-style: italic;
}

/* Row-level error indicators */
.channel-row.stale td {
  background: rgba(107, 114, 128, 0.1);
}

.channel-row.disconnected td {
  background: rgba(249, 115, 22, 0.1);
}

.channel-row.disconnected {
  border-left: 3px solid var(--color-warning);
}

.channel-row.open-tc td {
  background: rgba(220, 38, 38, 0.1);
}

.channel-row.open-tc {
  border-left: 3px solid var(--color-error-dark);
}

.channel-row.overflow td {
  background: rgba(168, 85, 247, 0.1);
}

.channel-row.overflow {
  border-left: 3px solid var(--color-accent-light);
}

.digital-state {
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 600;
  font-size: 0.7rem;
  background: var(--btn-secondary-bg);
  color: var(--text-secondary);
}

.digital-state.on {
  background: var(--indicator-success-bg);
  color: var(--color-success);
}

/* Config Button */
.config-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.config-btn:hover {
  background: var(--border-color);
  color: var(--text-primary);
}

/* Inline Editable Cells */
.editable-cell {
  cursor: default;
}

.editable-cell select {
  background: var(--bg-secondary);
  border: 1px solid transparent;
  border-radius: 3px;
  color: var(--text-bright);
  font-size: 0.75rem;
  padding: 2px 4px;
  cursor: pointer;
  max-width: 100%;
}

.editable-cell select:hover:not(:disabled) {
  border-color: var(--color-accent);
}

.editable-cell select:focus {
  outline: none;
  border-color: var(--color-accent);
  background: var(--bg-widget);
}

.editable-cell select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inline-input {
  background: var(--bg-secondary);
  border: 1px solid transparent;
  border-radius: 3px;
  color: var(--text-bright);
  font-size: 0.75rem;
  padding: 2px 4px;
  width: 100%;
}

.inline-input.narrow {
  width: 60px;
  text-align: right;
}

.inline-input:hover:not(:disabled) {
  border-color: var(--color-accent);
}

.inline-input:focus {
  outline: none;
  border-color: var(--color-accent);
  background: var(--bg-widget);
}

.inline-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inline-input[type="number"] {
  max-width: 70px;
}

.inline-select {
  background: var(--bg-secondary);
  border: 1px solid transparent;
  border-radius: 3px;
  color: var(--text-bright);
  font-size: 0.75rem;
  padding: 2px 4px;
  width: 100%;
  cursor: pointer;
}

.inline-select:hover:not(:disabled) {
  border-color: var(--color-accent);
}

.inline-select:focus {
  outline: none;
  border-color: var(--color-accent);
  background: var(--bg-widget);
}

.inline-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inline-select option {
  background: var(--bg-widget);
  color: var(--text-bright);
}

.inline-select option:disabled,
.inline-select option.option-in-use {
  color: var(--text-dim);
  font-style: italic;
}

/* Channel select - monospace for cDAQ paths */
.col-channel .inline-select {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
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

/* Tag input - monospace for tag names */
.col-tag .inline-input {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-accent-light);
}

.col-tag .inline-input:focus {
  color: var(--color-accent-light);
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
  background: var(--color-accent-bg);
  color: var(--color-accent-light);
}

.scaling-badge.off {
  background: var(--btn-secondary-bg);
  color: var(--text-secondary);
}

/* Config Panel */
.config-panel {
  width: 0;
  overflow: hidden;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
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
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3 {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-primary);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
}

.close-btn:hover {
  color: var(--text-primary);
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
  border-bottom: 1px solid var(--border-color);
  font-size: 0.8rem;
  color: var(--color-accent-light);
  text-transform: uppercase;
}

.form-row {
  margin-bottom: 12px;
}

.form-row label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.85rem;
}

.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: var(--color-accent);
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
  accent-color: var(--color-accent);
}

.scaling-info {
  font-size: 0.7rem;
  color: var(--text-muted);
  margin-bottom: 12px;
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 4px;
}

.scaling-preview {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.scaling-preview h5 {
  margin: 0 0 8px 0;
  font-size: 0.75rem;
  color: var(--color-accent);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.preview-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 0.8rem;
  border-bottom: 1px dashed var(--border-color);
}

.preview-row:last-of-type {
  border-bottom: none;
}

.preview-label {
  color: var(--text-secondary);
  font-family: 'Fira Code', monospace;
}

.preview-value {
  color: var(--color-success);
  font-weight: 600;
  font-family: 'Fira Code', monospace;
}

.preview-formula {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
  font-size: 0.7rem;
  color: var(--text-secondary);
  font-family: 'Fira Code', monospace;
}

.panel-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
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
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: var(--btn-secondary-hover);
}

.btn-primary {
  background: var(--color-accent);
  color: var(--text-primary);
}

.btn-primary:hover {
  background: var(--color-accent-dark);
}

/* Empty State */
.empty-row td {
  padding: 40px;
}

.empty-state {
  text-align: center;
  color: var(--text-dim);
}

/* Add Channel Row */
.add-channel-row {
  cursor: pointer;
  transition: background 0.15s;
}

.add-channel-row:hover {
  background: var(--bg-hover);
}

.add-channel-row td {
  border-bottom: none;
}

.add-channel-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  color: var(--color-accent-light);
  font-size: 0.8rem;
}

.add-channel-cell svg {
  opacity: 0.7;
}

.add-channel-row:hover .add-channel-cell {
  color: var(--color-accent-light);
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
  color: var(--text-dim);
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
  background: var(--indicator-sim-bg);
  color: var(--color-warning);
  font-size: 0.75rem;
  font-weight: 500;
}

.sim-icon {
  font-size: 0.85rem;
}

/* Checkbox styling */
input[type="checkbox"] {
  accent-color: var(--color-accent);
}

/* Actions Bar Enhanced */
.actions-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
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
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
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
  background: var(--border-color);
  color: var(--text-primary);
  border-color: var(--color-accent);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Primary buttons (green) - constructive actions: Add, Save */
.action-btn.primary {
  background: #166534;
  border-color: var(--color-success);
  color: var(--text-primary);
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
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.action-btn.accent:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: var(--color-accent-light);
}

/* Out-of-sync indicator for Push button when cRIO config doesn't match */
.action-btn.out-of-sync {
  border-color: var(--color-warning-dark);
  animation: pulse-warning 2s infinite;
}

.action-btn.out-of-sync:hover:not(:disabled) {
  border-color: var(--color-warning);
}

.sync-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--color-warning-dark);
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
  background: var(--indicator-warning-bg);
  border-color: var(--color-warning-dark);
  color: var(--color-warning);
}

.action-btn.warning:hover:not(:disabled) {
  background: #92400e;
  border-color: var(--color-warning);
  color: #fef3c7;
}

/* Active state for toggle buttons */
.action-btn.active {
  background: var(--color-accent);
  color: var(--text-primary);
  border-color: var(--color-accent-light);
}

.action-btn.active:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

/* No permission state */
.action-btn.no-permission {
  opacity: 0.6;
  border-color: var(--text-muted);
}

.action-btn.no-permission:hover {
  border-color: var(--color-warning-dark);
  color: var(--color-warning-dark);
}

.lock-badge {
  font-size: 0.7rem;
  margin-left: 4px;
}

.sim-mode-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 3px;
  background: var(--indicator-warning-bg);
  color: var(--color-warning);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sim-mode-indicator svg {
  width: 14px;
  height: 14px;
  fill: currentColor;
}

.crio-status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.crio-status-indicator.synced {
  background: #064e3b;
  color: #34d399;
}

.crio-status-indicator.out-of-sync {
  background: var(--indicator-warning-bg);
  color: var(--color-warning);
}

.crio-status-indicator.offline {
  background: var(--indicator-danger-bg);
  color: var(--color-error-light);
}

.crio-status-indicator svg {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

/* Spinner */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border-color);
  border-top-color: var(--color-accent);
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
  background: var(--indicator-success-bg);
  color: var(--color-success);
}

.feedback-message.error {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
}

.feedback-message.info {
  background: var(--color-accent-bg);
  color: var(--color-accent-light);
}

.feedback-message.warning {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.populating-banner {
  padding: 10px 16px;
  font-size: 0.85rem;
  font-weight: 500;
  text-align: center;
  background: var(--color-accent-bg);
  color: var(--color-accent-light);
  border-bottom: 1px solid var(--color-accent-border);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.populating-banner .spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-accent-border);
  border-top-color: var(--color-accent-light);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
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
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.discovery-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.discovery-header h3 {
  margin: 0;
  font-size: 1rem;
  color: var(--text-primary);
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
  color: var(--text-secondary);
}

.discovery-actions {
  display: flex;
  gap: 12px;
}

.btn-link {
  background: none;
  border: none;
  color: var(--color-accent-light);
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
  border: 1px solid var(--color-accent);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}

.quick-populate-banner .banner-text {
  color: var(--text-bright);
  font-size: 0.85rem;
}

.quick-populate-banner .banner-text strong {
  color: var(--color-accent-light);
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
  background: var(--bg-widget);
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.discovery-item:hover {
  background: var(--border-color);
}

.discovery-item.selected {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
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
  color: var(--text-primary);
  margin-bottom: 4px;
}

.channel-details {
  display: flex;
  align-items: center;
  gap: 8px;
}

.module-name {
  font-size: 0.7rem;
  color: var(--text-muted);
}

.discovery-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 16px;
  border-top: 1px solid var(--border-color);
}

.scanning-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
  color: var(--text-secondary);
}

.empty-discovery {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 8px;
  color: var(--text-dim);
}

.empty-discovery .hint {
  font-size: 0.75rem;
  color: var(--text-dim);
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
  color: var(--color-warning);
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
  background: var(--bg-widget);
  border-radius: 6px;
  overflow: hidden;
}

.tree-module {
  background: var(--bg-elevated);
  border-radius: 4px;
  margin: 2px 0;
}

.tree-module.standalone {
  background: var(--bg-widget);
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
  background: var(--bg-elevated);
}

/* cRIO node styling - distinct from cDAQ chassis */
.tree-crio {
  background: var(--bg-armed);
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
  color: var(--indicator-success-text);
}

.device-badge.cdaq {
  background: #1e40af;
  color: var(--color-accent-light);
}

.crio-status {
  font-size: 0.7rem;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
}

.crio-status.online {
  background: #166534;
  color: var(--indicator-success-text);
}

.crio-status.offline {
  background: #991b1b;
  color: var(--indicator-danger-text);
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
  color: var(--text-secondary);
  border-top: 1px solid #2a4a2a;
}

.crio-ip {
  font-family: monospace;
  color: var(--color-accent-light);
}

.crio-serial {
  color: var(--text-secondary);
}

.crio-last-seen {
  color: var(--text-muted);
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
  color: var(--indicator-success-text);
}

.opto22-status.offline {
  background: #991b1b;
  color: var(--indicator-danger-text);
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
  color: var(--text-secondary);
  border-top: 1px solid #4a3a2a;
}

.opto22-ip {
  font-family: monospace;
  color: var(--color-warning);
}

.opto22-serial {
  color: var(--text-secondary);
}

.opto22-last-seen {
  color: var(--text-muted);
}

.btn-push-config {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #166534;
  color: var(--text-primary);
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
  background: var(--btn-secondary-bg);
  color: var(--text-muted);
  cursor: not-allowed;
}

.module-header {
  padding-left: 24px;
}

.tree-arrow {
  color: var(--text-muted);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.tree-arrow.expanded {
  transform: rotate(90deg);
}

.tree-icon {
  color: var(--color-accent-light);
  flex-shrink: 0;
}

.tree-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 0.85rem;
}

.tree-type {
  font-size: 0.75rem;
  color: var(--text-secondary);
  padding: 2px 6px;
  background: var(--border-color);
  border-radius: 3px;
}

.tree-desc {
  font-size: 0.75rem;
  color: var(--text-muted);
  flex: 1;
}

.tree-count {
  font-size: 0.7rem;
  color: var(--text-secondary);
  background: var(--border-color);
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
  border-left: 2px solid var(--color-accent);
}

.tree-channel.in-use {
  opacity: 0.4;
  cursor: default;
  pointer-events: none;
}

.tree-channel .used-badge {
  font-size: 0.65rem;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(234, 179, 8, 0.2);
  color: var(--color-warning-dark);
  border: 1px solid rgba(234, 179, 8, 0.3);
  white-space: nowrap;
}

.tree-channel input[type="checkbox"] {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.tree-channel .channel-name {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: var(--text-bright);
  min-width: 140px;
}

.tree-channel .channel-desc {
  font-size: 0.7rem;
  color: var(--text-muted);
  flex: 1;
}

.tree-header input[type="checkbox"] {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

/* Type badge colors by category */
.type-badge.thermocouple { background: var(--color-accent-dark); color: var(--text-primary); }     /* Blue */
.type-badge.rtd { background: #0d9488; color: var(--text-primary); }              /* Teal */
.type-badge.voltage { background: #4f46e5; color: var(--text-primary); }          /* Indigo */
.type-badge.current { background: #7c3aed; color: var(--text-primary); }          /* Violet */
.type-badge.strain { background: #c026d3; color: var(--text-primary); }           /* Fuchsia */
.type-badge.iepe { background: #db2777; color: var(--text-primary); }             /* Pink */
.type-badge.digital_input { background: #16a34a; color: var(--text-primary); }    /* Green */
.type-badge.digital_output { background: #059669; color: var(--text-primary); }   /* Emerald */
.type-badge.voltage_output { background: #0284c7; color: var(--text-primary); }   /* Sky */
.type-badge.current_output { background: #9333ea; color: var(--text-primary); }   /* Purple */
.type-badge.analog_output { background: #0284c7; color: var(--text-primary); }    /* Sky (legacy) */
.type-badge.counter { background: #475569; color: var(--text-primary); }          /* Slate */
.type-badge.analog_input { background: #4f46e5; color: var(--text-primary); }     /* Indigo (same as voltage) */
.type-badge.voltage_input { background: #4f46e5; color: var(--text-primary); }    /* Indigo (same as voltage) */
.type-badge.current_input { background: #7c3aed; color: var(--text-primary); }    /* Violet (same as current) */

/* Toolbar separator */
.discovery-actions .separator {
  color: var(--text-dim);
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
  border-color: var(--color-accent-light);
  color: var(--color-accent-light);
}

/* Load Dialog */
.load-dialog {
  width: 400px;
  max-height: 60vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
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
  color: var(--text-secondary);
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
  background: var(--bg-widget);
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-bright);
  font-size: 0.85rem;
  transition: all 0.2s;
}

.config-item:hover {
  background: var(--border-color);
}

.config-item.selected {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
  color: var(--text-primary);
}

.config-item svg {
  color: var(--text-muted);
}

.config-item.selected svg {
  color: var(--color-accent-light);
}

/* Delete Button in table - only for data cells, not header */
.channel-table td.col-actions {
  text-align: center;
  white-space: nowrap;
}

.delete-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.delete-btn:hover {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
}

/* Alarm column styling */
.col-alarm {
  text-align: center;
  width: 50px;
  min-width: 50px;
}

.channel-table th.col-alarm {
  background: var(--bg-secondary);
}

/* Inline error/warning status indicators */
.col-status-indicators {
  text-align: center;
  width: 46px;
  min-width: 46px;
  padding: 0 2px;
}

.channel-table th.col-status-indicators {
  background: var(--bg-secondary);
}

.status-indicator-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: default;
  padding: 2px;
  border-radius: 3px;
  vertical-align: middle;
}

.status-indicator-icon.error-icon {
  color: var(--color-error);
}

.status-indicator-icon.error-icon:hover {
  background: rgba(239, 68, 68, 0.15);
}

.status-indicator-icon.warning-icon {
  color: var(--color-warning-dark);
}

.status-indicator-icon.warning-icon:hover {
  background: rgba(234, 179, 8, 0.15);
}

/* Dropdown error/warning states for missing required values */
select.select-error {
  border-color: var(--color-error) !important;
  background-color: rgba(239, 68, 68, 0.1) !important;
  color: var(--color-error) !important;
}

select.select-warning {
  border-color: #eab308 !important;
  background-color: rgba(234, 179, 8, 0.1) !important;
  color: #eab308 !important;
}

/* Limit cells with inverted ranges (low > high) */
td.limit-error {
  color: var(--color-error) !important;
  background-color: rgba(239, 68, 68, 0.1) !important;
}

/* Config panel inputs with invalid values */
input.input-error {
  border-color: var(--color-error) !important;
  background-color: rgba(239, 68, 68, 0.1) !important;
  color: var(--color-error) !important;
}

.alarm-btn {
  position: relative;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.alarm-btn:hover {
  background: var(--bg-widget);
  color: var(--text-secondary);
}

/* Alarm disabled state */
.alarm-btn.disabled {
  color: var(--text-dim);
}

.alarm-btn.disabled:hover {
  border-color: var(--text-muted);
  color: var(--text-secondary);
}

/* Alarm enabled state - green glow */
.alarm-btn.enabled {
  color: var(--color-success);
  border-color: var(--color-success-dark);
  background: rgba(22, 163, 74, 0.1);
}

.alarm-btn.enabled:hover {
  background: rgba(22, 163, 74, 0.2);
}

/* Active warning - yellow */
.alarm-btn.active-warning {
  color: var(--color-warning-dark);
  border-color: var(--color-warning-dark);
  background: rgba(234, 179, 8, 0.15);
  animation: pulse-warning 1.5s infinite;
}

/* Active alarm - red */
.alarm-btn.active-alarm {
  color: var(--color-error);
  border-color: var(--color-error-dark);
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
  background: var(--color-success);
  border-radius: 50%;
}

.alarm-btn.active-warning .alarm-indicator {
  background: var(--color-warning-dark);
}

.alarm-btn.active-alarm .alarm-indicator {
  background: var(--color-error);
}

/* Reset counter button */
.col-reset {
  text-align: center;
}

.reset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--color-accent-bg);
  border: 1px solid var(--color-accent);
  color: var(--color-accent-light);
  cursor: pointer;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  transition: all 0.15s;
}

.reset-btn:hover:not(:disabled) {
  background: var(--color-accent);
  color: var(--text-primary);
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
  color: var(--text-dim);
}

/* Add Channel Dialog */
.add-channel-dialog {
  width: 500px;
  max-height: 80vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
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
  color: var(--color-error);
}

.form-hint {
  display: block;
  font-size: 0.7rem;
  color: var(--text-dim);
  margin-top: 4px;
}

.form-hint.alarm-hint {
  text-align: center;
  margin: 8px 0 12px 0;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  color: var(--text-secondary);
}

/* Physical Channel Select in Add Channel Modal */
.scanning-indicator {
  font-size: 0.75rem;
  color: var(--color-accent);
  font-weight: normal;
  margin-left: 6px;
}

.physical-channel-select {
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

.physical-channel-select:focus {
  border-color: var(--color-accent);
  outline: none;
}

/* Grey out used/assigned channels in dropdowns */
option.option-in-use {
  color: var(--text-dim) !important;
  font-style: italic;
}

select option:disabled {
  color: var(--text-dim);
  font-style: italic;
}

.manual-channel-input {
  margin-top: 8px;
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

.manual-channel-input:focus {
  border-color: var(--color-accent);
  outline: none;
}

.form-hint .btn-link {
  background: none;
  border: none;
  color: var(--color-accent);
  cursor: pointer;
  padding: 0;
  font-size: inherit;
  text-decoration: underline;
}

.form-hint .btn-link:hover {
  color: var(--color-accent-light);
}

/* Type hint banner in Add Channel modal */
.type-hint-banner {
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.type-hint-banner strong {
  color: var(--color-accent);
}

/* Settings Dialog */
.settings-dialog {
  width: 450px;
  max-height: 80vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
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
  border-bottom: 1px solid var(--border-color);
  font-size: 0.8rem;
  color: var(--color-accent-light);
  text-transform: uppercase;
}

/* Auto-Gen Widgets Modal */
.auto-gen-info {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 16px;
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
}

.auto-gen-info strong {
  color: var(--color-accent-light);
  font-size: 1.1em;
}

.type-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
}

.type-checkbox-select-all {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border, #334155);
}

.type-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-surface);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background 0.15s;
}

.type-checkbox:hover {
  background: var(--bg-hover);
}

.type-checkbox input {
  margin: 0;
}

.type-checkbox .type-icon {
  font-size: 1em;
}

.settings-info {
  background: var(--bg-widget);
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
  color: var(--text-muted);
}

.info-row .info-value {
  color: var(--text-bright);
}

.info-row .info-value.online {
  color: var(--color-success);
}

.info-row .info-value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.info-row .info-value.mode-crio {
  color: var(--color-warning-dark);
  font-weight: 500;
}

.mode-select {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

.mode-select:focus {
  outline: none;
  border-color: var(--color-accent);
}

/* Source and Node selectors in Add Channel modal */
.source-select,
.node-select {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

.source-select:focus,
.node-select:focus {
  outline: none;
  border-color: var(--color-accent);
}

.node-select option.offline {
  color: var(--text-secondary);
  font-style: italic;
}

/* Safety Actions Dialog */
.safety-actions-dialog {
  width: 550px;
  max-height: 85vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
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
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 16px;
}

.safety-auto-execute label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
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
  color: var(--color-accent-light);
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
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
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
  color: var(--text-primary);
  font-weight: 500;
  font-size: 0.9rem;
}

.action-type {
  color: var(--color-accent-light);
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
}

.action-desc {
  color: var(--text-secondary);
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
  border: 1px solid var(--border-color);
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: var(--border-color);
}

.btn-icon.btn-danger:hover {
  background: var(--color-error-dark);
  border-color: var(--color-error-dark);
}

.safety-action-form {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 16px;
}

.safety-action-form h4 {
  margin: 0 0 16px;
  color: var(--color-accent-light);
  font-size: 0.85rem;
  text-transform: uppercase;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 150px;
  overflow-y: auto;
  background: var(--bg-secondary);
  padding: 8px;
  border-radius: 4px;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.empty-state {
  color: var(--text-secondary);
  font-size: 0.85rem;
  text-align: center;
  padding: 24px;
  background: var(--bg-widget);
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
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-widget);
  cursor: pointer;
}

.color-text {
  flex: 1;
  padding: 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
}

/* Dirty indicator */
.dirty-indicator {
  color: var(--color-warning-dark);
  font-weight: bold;
  margin-left: 2px;
}

/* Toolbar divider */
.toolbar-divider {
  width: 1px;
  height: 24px;
  background: var(--border-color);
  margin: 0 8px;
}

/* Save As Dialog */
.save-as-dialog {
  width: 400px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.save-as-content {
  padding: 16px;
}

.dialog-message {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-bottom: 16px;
  line-height: 1.5;
}

.filename-input {
  display: flex;
  align-items: center;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.filename-input input {
  flex: 1;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.filename-input input:focus {
  outline: none;
}

.filename-input .extension {
  padding: 8px 12px;
  background: var(--border-color);
  color: var(--text-secondary);
  font-size: 0.9rem;
}

/* Unsaved Changes Dialog */
.unsaved-dialog {
  width: 400px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
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
  color: var(--text-primary);
  font-size: 0.95rem;
}

.unsaved-content .hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.unsaved-footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  justify-content: flex-end;
}

/* Validation Report Modal */
.validation-dialog {
  width: 800px;
  max-width: 90vw;
  max-height: 85vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.validation-content {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.validation-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
  padding: 16px;
  background: rgba(59, 130, 246, 0.05);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
}

.summary-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.stat-value.success {
  color: var(--color-success);
}

.stat-value.warning {
  color: var(--color-warning-dark);
}

.issue-breakdown {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
}

.breakdown-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 500;
}

.breakdown-stat.error {
  color: var(--color-error);
}

.breakdown-stat.warning {
  color: var(--color-warning-dark);
}

.breakdown-stat.info {
  color: var(--color-accent);
}

.no-issues {
  padding: 40px;
  text-align: center;
}

.no-issues svg {
  margin-bottom: 16px;
}

.no-issues p {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 1rem;
}

.no-issues .hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.issues-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.issue-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.2);
  border-left: 3px solid;
  border-radius: 4px;
}

.issue-item.error {
  border-left-color: var(--color-error);
  background: rgba(239, 68, 68, 0.05);
}

.issue-item.warning {
  border-left-color: var(--color-warning-dark);
  background: rgba(245, 158, 11, 0.05);
}

.issue-item.info {
  border-left-color: var(--color-accent);
  background: rgba(59, 130, 246, 0.05);
}

.issue-icon {
  flex-shrink: 0;
  padding-top: 2px;
}

.issue-item.error .issue-icon svg {
  stroke: var(--color-error);
}

.issue-item.warning .issue-icon svg {
  stroke: var(--color-warning-dark);
}

.issue-item.info .issue-icon svg {
  stroke: var(--color-accent);
}

.issue-details {
  flex: 1;
  min-width: 0;
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.issue-channel {
  font-weight: 600;
  color: var(--text-primary);
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
}

.issue-category {
  font-size: 0.7rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
}

.issue-message {
  color: var(--text-bright);
  font-size: 0.85rem;
  line-height: 1.4;
}

.issue-fix {
  color: #67e8f9;
  font-size: 0.8rem;
  line-height: 1.3;
  margin-top: 2px;
  font-style: italic;
}

.validation-footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  justify-content: flex-end;
}

/* Import Preview Modal */
.import-preview-dialog {
  width: 700px;
  max-width: 90vw;
  max-height: 85vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.import-preview-content {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.import-summary {
  background: rgba(59, 130, 246, 0.05);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 20px;
}

.summary-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
}

.summary-header svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.summary-header h4 {
  margin: 0 0 4px;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.summary-hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.import-stats {
  display: flex;
  gap: 12px;
}

.import-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
}

.import-stat.new {
  background: rgba(34, 197, 94, 0.1);
  color: var(--color-success);
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.import-stat.overwrite {
  background: rgba(245, 158, 11, 0.1);
  color: var(--color-warning-dark);
  border: 1px solid rgba(245, 158, 11, 0.2);
}

.import-stat.conflict {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.import-warnings {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.warning-section {
  padding: 12px;
  background: rgba(245, 158, 11, 0.05);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 6px;
}

.warning-section.conflict {
  background: rgba(239, 68, 68, 0.05);
  border-color: rgba(239, 68, 68, 0.3);
}

.warning-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  color: var(--color-warning-dark);
  font-size: 0.9rem;
}

.warning-section.conflict .warning-header {
  color: var(--color-error);
}

.channel-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.channel-tag {
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  font-size: 0.75rem;
  font-family: 'Courier New', monospace;
  color: var(--text-bright);
}

.channel-tag.more {
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.2);
  color: var(--color-accent);
  font-family: inherit;
}

.conflicts-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conflict-item {
  font-size: 0.85rem;
  color: var(--text-bright);
  line-height: 1.5;
}

.conflict-channel {
  font-weight: 600;
  color: var(--text-primary);
  font-family: 'Courier New', monospace;
}

.conflict-physical {
  font-weight: 500;
  color: var(--color-warning);
  font-family: 'Courier New', monospace;
}

.conflict-existing {
  font-weight: 500;
  color: var(--color-error);
  font-family: 'Courier New', monospace;
}

.backup-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: rgba(59, 130, 246, 0.05);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  font-size: 0.85rem;
  color: var(--color-accent);
}

.import-preview-footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  justify-content: flex-end;
}

.btn-danger {
  background: var(--indicator-danger-bg) !important;
  border-color: var(--color-error) !important;
  color: var(--color-error) !important;
}

.btn-danger:hover:not(:disabled) {
  background: #991b1b !important;
  border-color: #f87171 !important;
}

/* Project Manager Styles */
.current-project-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid var(--color-success);
  border-radius: 6px;
  color: #4ade80;
  margin-bottom: 24px;
}

.current-project-banner.no-project {
  background: rgba(251, 191, 36, 0.1);
  border-color: var(--color-warning);
  color: #fcd34d;
}

.current-project-banner svg {
  flex-shrink: 0;
}

.no-projects-message {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
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
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  transition: all 0.2s;
}

.project-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-light);
}

.project-item.active {
  background: rgba(59, 130, 246, 0.1);
  border-color: var(--color-accent);
}

.project-info {
  flex: 1;
  min-width: 0;
}

.project-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 0.95rem;
  margin-bottom: 4px;
}

.project-meta {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.btn-sm {
  padding: 4px 12px;
  font-size: 0.8rem;
}

/* Notification settings */
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.checkbox-inline {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}

.checkbox-inline input[type="checkbox"] {
  margin: 0;
}

.sev-critical { color: var(--color-error); font-weight: 600; }
.sev-high { color: #f97316; font-weight: 600; }
.sev-medium { color: #eab308; }
.sev-low { color: #22c55e; }

.alarm-select-list {
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  padding: 4px;
  margin-top: 4px;
}

.alarm-select-item {
  padding: 2px 4px;
  border-radius: 3px;
}

.alarm-select-item:hover {
  background: rgba(255,255,255,0.05);
}

.alarm-select-meta {
  margin-left: 8px;
  font-size: 0.75rem;
  color: var(--text-secondary);
}
</style>
