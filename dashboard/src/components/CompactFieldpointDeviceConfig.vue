<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const mqtt = useMqtt()

// Props
const props = defineProps<{
  editMode: boolean
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
}>()

// =============================================================================
// CFP Module and Backplane Library
// =============================================================================

interface CFPModuleDefinition {
  channels: number
  registerType: 'input' | 'holding' | 'coil' | 'discrete'
  dataType: 'int16' | 'uint16' | 'float32' | 'bool'
  registersPerChannel: number
  unit: string
  description: string
  group: string
}

interface CFPBackplaneDefinition {
  slots: number
  tcp: boolean
  rtu: boolean
  description: string
}

const CFP_MODULES: Record<string, CFPModuleDefinition> = {
  'cFP-AI-110': {
    channels: 8,
    registerType: 'input',
    dataType: 'int16',
    registersPerChannel: 1,
    unit: 'V',
    description: '8ch +/-10V / +/-20mA',
    group: 'Analog Input'
  },
  'cFP-AI-111': {
    channels: 16,
    registerType: 'input',
    dataType: 'int16',
    registersPerChannel: 1,
    unit: 'V',
    description: '16ch +/-10V',
    group: 'Analog Input'
  },
  'cFP-AI-112': {
    channels: 8,
    registerType: 'input',
    dataType: 'int16',
    registersPerChannel: 1,
    unit: 'mA',
    description: '8ch 4-20mA',
    group: 'Current Input'
  },
  'cFP-TC-120': {
    channels: 8,
    registerType: 'input',
    dataType: 'float32',
    registersPerChannel: 2,
    unit: 'degC',
    description: '8ch Thermocouple',
    group: 'Temperature'
  },
  'cFP-RTD-122': {
    channels: 8,
    registerType: 'input',
    dataType: 'float32',
    registersPerChannel: 2,
    unit: 'degC',
    description: '8ch RTD',
    group: 'Temperature'
  },
  'cFP-DI-330': {
    channels: 8,
    registerType: 'discrete',
    dataType: 'bool',
    registersPerChannel: 1,
    unit: '',
    description: '8ch Universal DI',
    group: 'Digital Input'
  },
  'cFP-DI-301': {
    channels: 16,
    registerType: 'discrete',
    dataType: 'bool',
    registersPerChannel: 1,
    unit: '',
    description: '16ch 24V DI',
    group: 'Digital Input'
  },
  'cFP-DO-403': {
    channels: 8,
    registerType: 'coil',
    dataType: 'bool',
    registersPerChannel: 1,
    unit: '',
    description: '8ch Relay Output',
    group: 'Digital Output'
  },
  'cFP-DO-401': {
    channels: 16,
    registerType: 'coil',
    dataType: 'bool',
    registersPerChannel: 1,
    unit: '',
    description: '16ch 24V DO',
    group: 'Digital Output'
  },
  'cFP-RLY-421': {
    channels: 8,
    registerType: 'coil',
    dataType: 'bool',
    registersPerChannel: 1,
    unit: '',
    description: '8ch SPST Relay',
    group: 'Relay Output'
  },
  'cFP-AO-200': {
    channels: 8,
    registerType: 'holding',
    dataType: 'int16',
    registersPerChannel: 1,
    unit: 'mA',
    description: '8ch 0-20mA AO',
    group: 'Analog Output'
  },
  'cFP-AO-210': {
    channels: 8,
    registerType: 'holding',
    dataType: 'int16',
    registersPerChannel: 1,
    unit: 'V',
    description: '8ch +/-10V AO',
    group: 'Analog Output'
  }
}

const CFP_BACKPLANES: Record<string, CFPBackplaneDefinition> = {
  'cFP-1804': { slots: 4, tcp: true, rtu: false, description: '4-Slot Ethernet Backplane' },
  'cFP-1808': { slots: 8, tcp: true, rtu: false, description: '8-Slot Ethernet Backplane' },
  'cFP-2020': { slots: 8, tcp: true, rtu: true, description: '8-Slot Programmable Controller' },
  'cFP-2120': { slots: 8, tcp: true, rtu: true, description: '8-Slot High-Performance Controller' }
}

// Module options grouped by category
const MODULE_OPTIONS = computed(() => {
  const groups: Record<string, { model: string; description: string }[]> = {
    'Analog Input': [],
    'Current Input': [],
    'Temperature': [],
    'Digital Input': [],
    'Digital Output': [],
    'Relay Output': [],
    'Analog Output': []
  }

  for (const [model, def] of Object.entries(CFP_MODULES)) {
    const group = groups[def.group]
    if (group) {
      group.push({ model, description: def.description })
    }
  }

  return groups
})

// =============================================================================
// Device State
// =============================================================================

interface SlotConfig {
  slotNumber: number
  moduleModel: string | null
  channelPrefix: string
  enabled: boolean
}

interface CFPDevice {
  name: string
  backplaneModel: string
  connectionType: 'tcp' | 'rtu'
  ipAddress: string
  port: number
  serialPort: string
  baudrate: number
  parity: string
  timeout: number
  slaveId: number
  enabled: boolean
  slots: SlotConfig[]
}

const devices = ref<CFPDevice[]>([])
const selectedDevice = ref<string | null>(null)
const showAddDeviceModal = ref(false)
const showEditDeviceModal = ref(false)
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')
const generatingSlot = ref<number | null>(null)

// Connection status from backend
const connectionStatus = ref<Record<string, {
  connected: boolean
  error_count: number
  last_error: string | null
}>>({})

// Form state for add/edit
const deviceForm = ref<CFPDevice>({
  name: '',
  backplaneModel: 'cFP-1808',
  connectionType: 'tcp',
  ipAddress: '192.168.1.100',
  port: 502,
  serialPort: '/dev/ttyUSB0',
  baudrate: 9600,
  parity: 'E',
  timeout: 1.0,
  slaveId: 1,
  enabled: true,
  slots: []
})

// =============================================================================
// Computed
// =============================================================================

const currentBackplane = computed(() => CFP_BACKPLANES[deviceForm.value.backplaneModel])

const supportsRTU = computed(() => currentBackplane.value?.rtu ?? false)

// =============================================================================
// Methods
// =============================================================================

function initializeSlots(backplaneModel: string) {
  const backplane = CFP_BACKPLANES[backplaneModel]
  const slotCount = backplane?.slots || 8

  deviceForm.value.slots = Array.from({ length: slotCount }, (_, i) => ({
    slotNumber: i + 1,
    moduleModel: null,
    channelPrefix: `${deviceForm.value.name || 'CFP'}_S${i + 1}_`,
    enabled: true
  }))
}

function updateSlotPrefixes() {
  const baseName = deviceForm.value.name || 'CFP'
  deviceForm.value.slots.forEach((slot, i) => {
    slot.channelPrefix = `${baseName}_S${i + 1}_`
  })
}

/**
 * Calculate Modbus register address for a CFP channel
 * CFP Modbus addressing: Each slot starts at (slotNumber - 1) * 100
 */
function calculateRegisterAddress(slotNumber: number, channelIndex: number, registersPerChannel: number): number {
  const slotBase = (slotNumber - 1) * 100
  return slotBase + (channelIndex * registersPerChannel)
}

/**
 * Generate Modbus channels for a slot
 */
function generateChannelsForSlot(device: CFPDevice, slot: SlotConfig) {
  if (!slot.moduleModel) return []

  const module = CFP_MODULES[slot.moduleModel]
  if (!module) return []

  const channels = []

  for (let i = 0; i < module.channels; i++) {
    const registerAddress = calculateRegisterAddress(
      slot.slotNumber,
      i,
      module.registersPerChannel
    )

    const channelName = `${slot.channelPrefix}Ch${i}`
    const channelType = module.registerType === 'coil' || module.registerType === 'discrete'
      ? 'modbus_coil'
      : 'modbus_register'

    channels.push({
      name: channelName,
      channel_type: channelType,
      physical_channel: `modbus:${module.registerType}:${registerAddress}`,
      unit: module.unit,
      group: module.group,
      description: `${slot.moduleModel} Slot ${slot.slotNumber} Ch${i}`,
      visible: true,
      chartable: channelType === 'modbus_register',
      enabled: true,
      // Modbus-specific config
      chassis: device.name,
      connection: device.connectionType.toUpperCase(),
      ip_address: device.ipAddress,
      modbus_port: device.port,
      modbus_register_type: module.registerType,
      modbus_address: registerAddress,
      modbus_data_type: module.dataType,
      modbus_byte_order: 'big',
      modbus_word_order: 'big',
      modbus_slave_id: device.slaveId,
      modbus_scale: 1.0,
      modbus_offset: 0,
      // CFP metadata for identification
      cfp_device: device.name,
      cfp_slot: slot.slotNumber,
      cfp_module: slot.moduleModel
    })
  }

  return channels
}

async function addChannelsForSlot(device: CFPDevice, slotNumber: number) {
  const slot = device.slots.find(s => s.slotNumber === slotNumber)
  if (!slot || !slot.moduleModel) {
    showFeedback('error', 'Select a module for this slot first')
    return
  }

  isLoading.value = true
  generatingSlot.value = slotNumber

  try {
    const channels = generateChannelsForSlot(device, slot)

    if (channels.length === 0) {
      showFeedback('error', 'No channels to generate')
      return
    }

    // Add channels via MQTT
    for (const ch of channels) {
      mqtt.sendCommand('channel/add', ch)
    }

    showFeedback('success', `Added ${channels.length} channels for Slot ${slotNumber} (${slot.moduleModel})`)
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to add channels')
  } finally {
    isLoading.value = false
    generatingSlot.value = null
  }
}

function openAddDevice() {
  deviceForm.value = {
    name: '',
    backplaneModel: 'cFP-1808',
    connectionType: 'tcp',
    ipAddress: '192.168.1.100',
    port: 502,
    serialPort: '/dev/ttyUSB0',
    baudrate: 9600,
    parity: 'E',
    timeout: 1.0,
    slaveId: 1,
    enabled: true,
    slots: []
  }
  initializeSlots('cFP-1808')
  showAddDeviceModal.value = true
}

function openEditDevice(device: CFPDevice) {
  deviceForm.value = JSON.parse(JSON.stringify(device))
  showEditDeviceModal.value = true
}

async function addDevice() {
  if (!deviceForm.value.name) {
    showFeedback('error', 'Device name is required')
    return
  }

  if (devices.value.some(d => d.name === deviceForm.value.name)) {
    showFeedback('error', 'Device name already exists')
    return
  }

  isLoading.value = true
  try {
    // Register as Modbus device in backend
    mqtt.sendCommand('chassis/add', {
      name: deviceForm.value.name,
      type: 'cfp_backplane',
      connection: deviceForm.value.connectionType.toUpperCase(),
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ipAddress,
      modbus_port: deviceForm.value.port,
      serial: deviceForm.value.serialPort,
      modbus_baudrate: deviceForm.value.baudrate,
      modbus_parity: deviceForm.value.parity,
      modbus_timeout: deviceForm.value.timeout,
      modbus_slave_id: deviceForm.value.slaveId,
      // CFP metadata
      cfp_backplane_model: deviceForm.value.backplaneModel,
      cfp_slots: deviceForm.value.slots.length
    })

    devices.value.push(JSON.parse(JSON.stringify(deviceForm.value)))
    showAddDeviceModal.value = false
    showFeedback('success', `CFP device "${deviceForm.value.name}" added`)
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to add device')
  } finally {
    isLoading.value = false
  }
}

async function updateDevice() {
  isLoading.value = true
  try {
    mqtt.sendCommand('chassis/update', {
      name: deviceForm.value.name,
      type: 'cfp_backplane',
      connection: deviceForm.value.connectionType.toUpperCase(),
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ipAddress,
      modbus_port: deviceForm.value.port,
      serial: deviceForm.value.serialPort,
      modbus_baudrate: deviceForm.value.baudrate,
      modbus_parity: deviceForm.value.parity,
      modbus_timeout: deviceForm.value.timeout,
      modbus_slave_id: deviceForm.value.slaveId,
      cfp_backplane_model: deviceForm.value.backplaneModel
    })

    const idx = devices.value.findIndex(d => d.name === deviceForm.value.name)
    if (idx >= 0) {
      devices.value[idx] = JSON.parse(JSON.stringify(deviceForm.value))
    }

    showEditDeviceModal.value = false
    showFeedback('success', `Device "${deviceForm.value.name}" updated`)
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to update device')
  } finally {
    isLoading.value = false
  }
}

async function deleteDevice(deviceName: string) {
  if (!confirm(`Delete CFP device "${deviceName}"? This will not remove channels already created.`)) {
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('chassis/delete', { name: deviceName })
    devices.value = devices.value.filter(d => d.name !== deviceName)
    if (selectedDevice.value === deviceName) {
      selectedDevice.value = null
    }
    showFeedback('success', `Device "${deviceName}" deleted`)
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to delete device')
  } finally {
    isLoading.value = false
  }
}

async function testConnection(deviceName: string) {
  isLoading.value = true
  showFeedback('success', `Testing connection to ${deviceName}...`)

  try {
    const result = await mqtt.sendCommandWithAck('chassis/test', { name: deviceName }, 10000)

    if (result.success) {
      showFeedback('success', (result as any).message || 'Connection successful')
    } else {
      showFeedback('error', (result as any).message || result.error || 'Connection failed')
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Connection test timed out')
  } finally {
    isLoading.value = false
  }
}

function showFeedback(type: 'success' | 'error', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
  setTimeout(() => feedbackMessage.value = '', 4000)
}

function loadDevices() {
  // Scan channelConfigs for CFP devices
  const channelConfigs = mqtt.channelConfigs.value
  const foundDevices = new Map<string, CFPDevice>()

  for (const [_channelName, config] of Object.entries(channelConfigs)) {
    const cfpDevice = (config as any)?.cfp_device
    if (cfpDevice && !foundDevices.has(cfpDevice)) {
      // Reconstruct device from channel config
      const backplaneModel = (config as any)?.cfp_backplane_model || 'cFP-1808'
      const backplane = CFP_BACKPLANES[backplaneModel]

      foundDevices.set(cfpDevice, {
        name: cfpDevice,
        backplaneModel,
        connectionType: ((config as any)?.connection?.toLowerCase() || 'tcp') as 'tcp' | 'rtu',
        ipAddress: (config as any)?.ip_address || '',
        port: (config as any)?.modbus_port || 502,
        serialPort: (config as any)?.serial || '',
        baudrate: (config as any)?.modbus_baudrate || 9600,
        parity: (config as any)?.modbus_parity || 'E',
        timeout: (config as any)?.modbus_timeout || 1.0,
        slaveId: (config as any)?.modbus_slave_id || 1,
        enabled: true,
        slots: Array.from({ length: backplane?.slots || 8 }, (_, i) => ({
          slotNumber: i + 1,
          moduleModel: null,
          channelPrefix: `${cfpDevice}_S${i + 1}_`,
          enabled: true
        }))
      })
    }

    // Update slot info if we have it
    const cfpSlot = (config as any)?.cfp_slot
    const cfpModule = (config as any)?.cfp_module
    if (cfpDevice && cfpSlot && cfpModule) {
      const device = foundDevices.get(cfpDevice)
      if (device) {
        const slot = device.slots.find(s => s.slotNumber === cfpSlot)
        if (slot) {
          slot.moduleModel = cfpModule
        }
      }
    }
  }

  devices.value = Array.from(foundDevices.values())
}

function subscribeToStatus() {
  mqtt.subscribe('nisystem/modbus/status', (message: any) => {
    if (message && typeof message === 'object') {
      connectionStatus.value = message
    }
  })
}

// =============================================================================
// Watchers
// =============================================================================

watch(() => deviceForm.value.backplaneModel, (newModel) => {
  initializeSlots(newModel)
})

watch(() => deviceForm.value.name, () => {
  updateSlotPrefixes()
})

watch(() => mqtt.channelConfigs.value, () => {
  loadDevices()
}, { deep: true })

// =============================================================================
// Lifecycle
// =============================================================================

onMounted(() => {
  loadDevices()
  subscribeToStatus()
})
</script>

<template>
  <div class="cfp-config">
    <!-- Legacy Warning Banner -->
    <div class="legacy-warning">
      <span class="warning-icon">&#9888;</span>
      <div class="warning-content">
        <strong>LEGACY HARDWARE</strong>
        <p>Compact FieldPoint was discontinued by NI in 2018. This feature is provided for legacy system support only. Consider migrating to cDAQ or cRIO for new applications.</p>
      </div>
    </div>

    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">&#128230;</span>
        Compact FieldPoint Devices
      </h3>
      <button v-if="editMode" class="add-btn" @click="openAddDevice">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        Add CFP Device
      </button>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Empty state -->
    <div v-if="devices.length === 0" class="empty-state">
      <p>No Compact FieldPoint devices configured</p>
      <p class="hint">Click "Add CFP Device" to configure a legacy CFP backplane</p>
    </div>

    <!-- Device list -->
    <div v-else class="device-list">
      <div
        v-for="device in devices"
        :key="device.name"
        class="device-card"
        :class="{
          selected: selectedDevice === device.name,
          disabled: !device.enabled
        }"
        @click="selectedDevice = selectedDevice === device.name ? null : device.name"
      >
        <div class="device-header">
          <span class="device-icon">&#128230;</span>
          <span class="device-name">{{ device.name }}</span>
          <span class="backplane-badge">{{ device.backplaneModel }}</span>
          <span
            class="connection-status"
            :class="{
              connected: connectionStatus[device.name]?.connected,
              error: (connectionStatus[device.name]?.error_count ?? 0) > 0
            }"
          >
            {{ connectionStatus[device.name]?.connected ? '&#9679;' : '&#9675;' }}
          </span>
        </div>

        <div class="device-info">
          <template v-if="device.connectionType === 'tcp'">
            <span class="info-tag">TCP</span>
            <span class="info-value">{{ device.ipAddress }}:{{ device.port }}</span>
          </template>
          <template v-else>
            <span class="info-tag">RTU</span>
            <span class="info-value">{{ device.serialPort }} @ {{ device.baudrate }}</span>
          </template>
          <span class="info-tag slave">ID: {{ device.slaveId }}</span>
        </div>

        <!-- Expanded: Slot Configuration -->
        <div v-if="selectedDevice === device.name" class="device-details">
          <div class="slots-section">
            <h4>Module Slots</h4>
            <div class="slot-grid">
              <div
                v-for="slot in device.slots"
                :key="slot.slotNumber"
                class="slot-card"
                :class="{ occupied: slot.moduleModel, empty: !slot.moduleModel }"
              >
                <div class="slot-header">
                  <span class="slot-number">Slot {{ slot.slotNumber }}</span>
                  <span v-if="slot.moduleModel" class="module-badge">{{ slot.moduleModel }}</span>
                </div>

                <div class="slot-content">
                  <select
                    v-model="slot.moduleModel"
                    :disabled="!editMode"
                    class="module-select"
                    @click.stop
                  >
                    <option :value="null">-- Empty --</option>
                    <optgroup v-for="(modules, group) in MODULE_OPTIONS" :key="group" :label="group">
                      <option v-for="mod in modules" :key="mod.model" :value="mod.model">
                        {{ mod.model }} ({{ mod.description }})
                      </option>
                    </optgroup>
                  </select>

                  <div v-if="slot.moduleModel" class="module-info">
                    <span class="channel-count">
                      {{ CFP_MODULES[slot.moduleModel]?.channels }} channels
                    </span>
                  </div>

                  <div v-if="slot.moduleModel && editMode" class="slot-actions" @click.stop>
                    <input
                      v-model="slot.channelPrefix"
                      class="prefix-input"
                      placeholder="Prefix"
                      @click.stop
                    />
                    <button
                      class="add-channels-btn"
                      @click.stop="addChannelsForSlot(device, slot.slotNumber)"
                      :disabled="isLoading || generatingSlot === slot.slotNumber"
                    >
                      {{ generatingSlot === slot.slotNumber ? 'Adding...' : 'Add Channels' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="device-actions">
            <button class="action-btn" @click.stop="testConnection(device.name)" :disabled="isLoading">
              Test Connection
            </button>
            <button v-if="editMode" class="action-btn" @click.stop="openEditDevice(device)">
              Edit
            </button>
            <button v-if="editMode" class="action-btn danger" @click.stop="deleteDevice(device.name)">
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Device Modal -->
    <div v-if="showAddDeviceModal" class="modal-overlay" @click.self="showAddDeviceModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Add Compact FieldPoint Device</h3>
          <button class="close-btn" @click="showAddDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="modal-warning">
            &#9888; CFP hardware is legacy. Consider migrating to cDAQ or cRIO for new applications.
          </div>

          <div class="form-row">
            <label>Device Name</label>
            <input v-model="deviceForm.name" type="text" placeholder="e.g., CFP_Furnace1" />
          </div>

          <div class="form-row">
            <label>Backplane Model</label>
            <select v-model="deviceForm.backplaneModel">
              <option v-for="(def, model) in CFP_BACKPLANES" :key="model" :value="model">
                {{ model }} - {{ def.description }}
              </option>
            </select>
          </div>

          <div class="form-row">
            <label>Connection Type</label>
            <select v-model="deviceForm.connectionType">
              <option value="tcp">Modbus TCP (Ethernet)</option>
              <option value="rtu" :disabled="!supportsRTU">
                Modbus RTU (Serial){{ !supportsRTU ? ' - Not supported by this backplane' : '' }}
              </option>
            </select>
          </div>

          <!-- TCP Settings -->
          <template v-if="deviceForm.connectionType === 'tcp'">
            <div class="form-group">
              <h4>TCP Connection</h4>
              <div class="form-row">
                <label>IP Address</label>
                <input v-model="deviceForm.ipAddress" type="text" placeholder="192.168.1.100" />
              </div>
              <div class="form-row">
                <label>Port</label>
                <input v-model.number="deviceForm.port" type="number" min="1" max="65535" />
              </div>
            </div>
          </template>

          <!-- RTU Settings -->
          <template v-else>
            <div class="form-group">
              <h4>Serial Connection</h4>
              <div class="form-row">
                <label>Serial Port</label>
                <input v-model="deviceForm.serialPort" type="text" placeholder="/dev/ttyUSB0 or COM3" />
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Baud Rate</label>
                  <select v-model.number="deviceForm.baudrate">
                    <option :value="9600">9600</option>
                    <option :value="19200">19200</option>
                    <option :value="38400">38400</option>
                  </select>
                </div>
                <div class="form-row half">
                  <label>Parity</label>
                  <select v-model="deviceForm.parity">
                    <option value="N">None</option>
                    <option value="E">Even</option>
                    <option value="O">Odd</option>
                  </select>
                </div>
              </div>
            </div>
          </template>

          <div class="form-group">
            <h4>Modbus Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Slave ID</label>
                <input v-model.number="deviceForm.slaveId" type="number" min="1" max="247" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout" type="number" min="0.1" max="30" step="0.1" />
              </div>
            </div>
          </div>

          <div class="form-row checkbox-row">
            <label>
              <input type="checkbox" v-model="deviceForm.enabled" />
              Enable device
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showAddDeviceModal = false">Cancel</button>
          <button class="btn primary" @click="addDevice" :disabled="isLoading || !deviceForm.name">
            {{ isLoading ? 'Adding...' : 'Add Device' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Device Modal -->
    <div v-if="showEditDeviceModal" class="modal-overlay" @click.self="showEditDeviceModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Edit CFP Device: {{ deviceForm.name }}</h3>
          <button class="close-btn" @click="showEditDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Connection Type</label>
            <select v-model="deviceForm.connectionType">
              <option value="tcp">Modbus TCP (Ethernet)</option>
              <option value="rtu" :disabled="!supportsRTU">Modbus RTU (Serial)</option>
            </select>
          </div>

          <template v-if="deviceForm.connectionType === 'tcp'">
            <div class="form-group">
              <h4>TCP Connection</h4>
              <div class="form-row">
                <label>IP Address</label>
                <input v-model="deviceForm.ipAddress" type="text" />
              </div>
              <div class="form-row">
                <label>Port</label>
                <input v-model.number="deviceForm.port" type="number" />
              </div>
            </div>
          </template>

          <template v-else>
            <div class="form-group">
              <h4>Serial Connection</h4>
              <div class="form-row">
                <label>Serial Port</label>
                <input v-model="deviceForm.serialPort" type="text" />
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Baud Rate</label>
                  <select v-model.number="deviceForm.baudrate">
                    <option :value="9600">9600</option>
                    <option :value="19200">19200</option>
                    <option :value="38400">38400</option>
                  </select>
                </div>
                <div class="form-row half">
                  <label>Parity</label>
                  <select v-model="deviceForm.parity">
                    <option value="N">None</option>
                    <option value="E">Even</option>
                    <option value="O">Odd</option>
                  </select>
                </div>
              </div>
            </div>
          </template>

          <div class="form-group">
            <h4>Modbus Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Slave ID</label>
                <input v-model.number="deviceForm.slaveId" type="number" min="1" max="247" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout" type="number" min="0.1" max="30" step="0.1" />
              </div>
            </div>
          </div>

          <div class="form-row checkbox-row">
            <label>
              <input type="checkbox" v-model="deviceForm.enabled" />
              Enable device
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showEditDeviceModal = false">Cancel</button>
          <button class="btn primary" @click="updateDevice" :disabled="isLoading">
            {{ isLoading ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cfp-config {
  padding: 1rem;
  background: var(--bg-secondary, #1e1e1e);
  border-radius: 8px;
  margin-bottom: 1rem;
}

/* Legacy Warning */
.legacy-warning {
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: rgba(234, 179, 8, 0.15);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 6px;
  margin-bottom: 1rem;
}

.warning-icon {
  font-size: 1.5rem;
  color: #eab308;
}

.warning-content {
  flex: 1;
}

.warning-content strong {
  color: #eab308;
  font-size: 0.9rem;
}

.warning-content p {
  margin: 0.25rem 0 0 0;
  font-size: 0.8rem;
  color: #a3a3a3;
}

/* Section Header */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border-color, #333);
}

.section-header h3 {
  margin: 0;
  font-size: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-header .icon {
  font-size: 1.2rem;
}

.add-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.8rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.add-btn:hover {
  background: #2563eb;
}

/* Feedback */
.feedback {
  padding: 0.5rem 1rem;
  border-radius: 4px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.feedback.success {
  background: #14532d;
  color: #86efac;
}

.feedback.error {
  background: #7f1d1d;
  color: #fca5a5;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 2rem;
  color: #888;
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 0.5rem;
}

/* Device List */
.device-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.device-card {
  background: var(--bg-tertiary, #252525);
  border: 1px solid var(--border-color, #333);
  border-radius: 6px;
  padding: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.device-card:hover {
  border-color: #3b82f6;
}

.device-card.selected {
  border-color: #3b82f6;
  background: #1e293b;
}

.device-card.disabled {
  opacity: 0.5;
}

.device-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.device-icon {
  font-size: 1.1rem;
}

.device-name {
  font-weight: 600;
  flex: 1;
}

.backplane-badge {
  background: #374151;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #9ca3af;
}

.connection-status {
  font-size: 0.8rem;
}

.connection-status.connected {
  color: #22c55e;
}

.connection-status.error {
  color: #ef4444;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  font-size: 0.85rem;
  color: #888;
}

.info-tag {
  background: #374151;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.75rem;
  font-weight: 600;
}

.info-tag.slave {
  background: #1e3a5f;
  color: #60a5fa;
}

/* Device Details */
.device-details {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color, #333);
}

/* Slots Section */
.slots-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.9rem;
  color: #888;
}

.slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem;
}

.slot-card {
  background: var(--bg-primary, #121212);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  padding: 0.5rem;
}

.slot-card.occupied {
  border-color: #3b82f6;
}

.slot-card.empty {
  opacity: 0.7;
}

.slot-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.slot-number {
  font-weight: 600;
  font-size: 0.85rem;
}

.module-badge {
  background: #1e3a5f;
  color: #60a5fa;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
}

.slot-content {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.module-select {
  width: 100%;
  padding: 0.35rem;
  background: var(--bg-secondary, #1e1e1e);
  border: 1px solid var(--border-color, #333);
  border-radius: 3px;
  color: white;
  font-size: 0.75rem;
}

.module-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.module-info {
  font-size: 0.75rem;
  color: #888;
}

.channel-count {
  color: #60a5fa;
}

.slot-actions {
  display: flex;
  gap: 0.3rem;
  margin-top: 0.25rem;
}

.prefix-input {
  flex: 1;
  padding: 0.25rem 0.4rem;
  background: var(--bg-secondary, #1e1e1e);
  border: 1px solid var(--border-color, #333);
  border-radius: 3px;
  color: white;
  font-size: 0.7rem;
  min-width: 0;
}

.prefix-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.add-channels-btn {
  padding: 0.25rem 0.5rem;
  background: #22c55e;
  color: white;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.7rem;
  white-space: nowrap;
}

.add-channels-btn:hover {
  background: #16a34a;
}

.add-channels-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Device Actions */
.device-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.action-btn {
  padding: 0.4rem 0.8rem;
  background: #374151;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.action-btn:hover {
  background: #4b5563;
}

.action-btn.danger {
  background: #7f1d1d;
}

.action-btn.danger:hover {
  background: #991b1b;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--bg-secondary, #1e1e1e);
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid var(--border-color, #333);
}

.modal-header h3 {
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 1.5rem;
  cursor: pointer;
}

.close-btn:hover {
  color: white;
}

.modal-body {
  padding: 1rem;
}

.modal-warning {
  padding: 0.5rem 0.75rem;
  background: rgba(234, 179, 8, 0.15);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 4px;
  margin-bottom: 1rem;
  font-size: 0.8rem;
  color: #eab308;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 1rem;
  border-top: 1px solid var(--border-color, #333);
}

.form-group {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--bg-tertiary, #252525);
  border-radius: 6px;
}

.form-group h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.9rem;
  color: #888;
}

.form-row {
  margin-bottom: 0.75rem;
}

.form-row label {
  display: block;
  font-size: 0.85rem;
  color: #888;
  margin-bottom: 0.25rem;
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 0.5rem;
  background: var(--bg-primary, #121212);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  color: white;
}

.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: #3b82f6;
}

.form-row-group {
  display: flex;
  gap: 1rem;
}

.form-row.half {
  flex: 1;
}

.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.checkbox-row input[type="checkbox"] {
  width: auto;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}

.btn.primary {
  background: #3b82f6;
  color: white;
}

.btn.primary:hover {
  background: #2563eb;
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.secondary {
  background: #374151;
  color: white;
}

.btn.secondary:hover {
  background: #4b5563;
}
</style>
