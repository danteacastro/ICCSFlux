<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { DeviceCommandResult } from '../types'
import ModbusAddressChanger from './ModbusAddressChanger.vue'

const mqtt = useMqtt()

// Address changer modal
const showAddressChanger = ref(false)

// Props
const props = defineProps<{
  editMode: boolean
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
}>()

// Modbus devices state
interface ModbusDevice {
  name: string
  connection_type: 'tcp' | 'rtu'
  enabled: boolean
  // TCP settings
  ip_address: string
  port: number
  // RTU settings
  serial_port: string
  baudrate: number
  parity: string
  stopbits: number
  bytesize: number
  // Common settings
  timeout: number
  retries: number
}

const devices = ref<ModbusDevice[]>([])
const selectedDevice = ref<string | null>(null)
const showAddDeviceModal = ref(false)
const showEditDeviceModal = ref(false)
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')

// Form state for add/edit
const deviceForm = ref<ModbusDevice>({
  name: '',
  connection_type: 'tcp',
  enabled: true,
  ip_address: '192.168.1.100',
  port: 502,
  serial_port: '/dev/ttyUSB0',
  baudrate: 9600,
  parity: 'E',
  stopbits: 1,
  bytesize: 8,
  timeout: 1.0,
  retries: 3
})

// Connection status from backend
const connectionStatus = ref<Record<string, {
  connected: boolean
  error_count: number
  last_error: string | null
}>>({})


// Initialize - load devices from backend config
onMounted(() => {
  loadDevices()
  subscribeToStatus()
})

function loadDevices() {
  // Get chassis config from channelConfigs (published by DAQ service)
  const channelConfigs = mqtt.channelConfigs.value
  // Look for modbus-related chassis in the configs
  devices.value = []

  // Scan channelConfigs for modbus devices based on module/chassis info
  for (const [_channelName, config] of Object.entries(channelConfigs)) {
    const chassis = config?.chassis || ''
    const conn = config?.connection?.toUpperCase() || ''
    if (conn === 'TCP' || conn === 'RTU' || conn === 'MODBUS_TCP' || conn === 'MODBUS_RTU') {
      // Check if we already have this device
      if (!devices.value.some(d => d.name === chassis)) {
        devices.value.push({
          name: chassis || 'modbus_device',
          connection_type: conn.includes('RTU') ? 'rtu' : 'tcp',
          enabled: true,
          ip_address: config?.ip_address || '',
          port: config?.modbus_port || 502,
          serial_port: config?.serial || '',
          baudrate: config?.modbus_baudrate || 9600,
          parity: config?.modbus_parity || 'E',
          stopbits: config?.modbus_stopbits || 1,
          bytesize: config?.modbus_bytesize || 8,
          timeout: config?.modbus_timeout || 1.0,
          retries: config?.modbus_retries || 3
        })
      }
    }
  }
}

function subscribeToStatus() {
  // Subscribe to modbus connection status updates
  mqtt.subscribe('nisystem/modbus/status', (message: any) => {
    if (message && typeof message === 'object') {
      connectionStatus.value = message
    }
  })
}

function openAddDevice() {
  deviceForm.value = {
    name: '',
    connection_type: 'tcp',
    enabled: true,
    ip_address: '192.168.1.100',
    port: 502,
    serial_port: '/dev/ttyUSB0',
    baudrate: 9600,
    parity: 'E',
    stopbits: 1,
    bytesize: 8,
    timeout: 1.0,
    retries: 3
  }
  showAddDeviceModal.value = true
}

function openEditDevice(device: ModbusDevice) {
  deviceForm.value = { ...device }
  showEditDeviceModal.value = true
}

async function addDevice() {
  if (!deviceForm.value.name) {
    showFeedback('error', 'Device name is required')
    return
  }

  // Check for duplicate names
  if (devices.value.some(d => d.name === deviceForm.value.name)) {
    showFeedback('error', 'Device name already exists')
    return
  }

  isLoading.value = true
  try {
    // Send to backend via MQTT
    mqtt.sendCommand('chassis/add', {
      name: deviceForm.value.name,
      type: 'modbus_device',
      connection: deviceForm.value.connection_type.toUpperCase(),
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ip_address,
      modbus_port: deviceForm.value.port,
      serial: deviceForm.value.serial_port,
      modbus_baudrate: deviceForm.value.baudrate,
      modbus_parity: deviceForm.value.parity,
      modbus_stopbits: deviceForm.value.stopbits,
      modbus_bytesize: deviceForm.value.bytesize,
      modbus_timeout: deviceForm.value.timeout,
      modbus_retries: deviceForm.value.retries
    })

    // Add to local state
    devices.value.push({ ...deviceForm.value })
    showAddDeviceModal.value = false
    showFeedback('success', `Device "${deviceForm.value.name}" added`)
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
    // Send to backend via MQTT
    mqtt.sendCommand('chassis/update', {
      name: deviceForm.value.name,
      type: 'modbus_device',
      connection: deviceForm.value.connection_type.toUpperCase(),
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ip_address,
      modbus_port: deviceForm.value.port,
      serial: deviceForm.value.serial_port,
      modbus_baudrate: deviceForm.value.baudrate,
      modbus_parity: deviceForm.value.parity,
      modbus_stopbits: deviceForm.value.stopbits,
      modbus_bytesize: deviceForm.value.bytesize,
      modbus_timeout: deviceForm.value.timeout,
      modbus_retries: deviceForm.value.retries
    })

    // Update local state
    const index = devices.value.findIndex(d => d.name === deviceForm.value.name)
    if (index >= 0) {
      devices.value[index] = { ...deviceForm.value }
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
  if (!confirm(`Delete Modbus device "${deviceName}"? This will remove all associated channels.`)) {
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
    // Use sendCommandWithAck to wait for response
    const result = await mqtt.sendCommandWithAck('chassis/test', { name: deviceName }, 10000)

    if (result.success) {
      showFeedback('success', (result as DeviceCommandResult).message || `Connection to ${deviceName} successful`)
    } else {
      showFeedback('error', (result as DeviceCommandResult).message || result.error || `Connection to ${deviceName} failed`)
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Connection test timed out - check device settings')
  } finally {
    isLoading.value = false
  }
}

function showFeedback(type: 'success' | 'error', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
  setTimeout(() => {
    feedbackMessage.value = ''
  }, 3000)
}

// Watch for config updates from backend
watch(() => mqtt.channelConfigs.value, () => {
  loadDevices()
}, { deep: true })
</script>

<template>
  <div class="modbus-config">
    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">🔌</span>
        Modbus Devices
      </h3>
      <div class="header-actions">
        <button
          class="tool-btn"
          @click="showAddressChanger = true"
          title="Change device slave address"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          Address Changer
        </button>
        <button
          v-if="editMode"
          class="add-btn"
          @click="openAddDevice"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add Device
        </button>
      </div>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Device list -->
    <div v-if="devices.length === 0" class="empty-state">
      <p>No Modbus devices configured</p>
      <p class="hint">Click "Add Device" to add a Modbus TCP or RTU device</p>
    </div>

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
          <span class="device-icon">{{ device.connection_type === 'tcp' ? '🌐' : '📡' }}</span>
          <span class="device-name">{{ device.name }}</span>
          <span
            class="connection-status"
            :class="{
              connected: connectionStatus[device.name]?.connected,
              error: (connectionStatus[device.name]?.error_count ?? 0) > 0
            }"
          >
            {{ connectionStatus[device.name]?.connected ? '●' : '○' }}
          </span>
        </div>

        <div class="device-info">
          <template v-if="device.connection_type === 'tcp'">
            <span class="info-tag">TCP</span>
            <span class="info-value">{{ device.ip_address }}:{{ device.port }}</span>
          </template>
          <template v-else>
            <span class="info-tag">RTU</span>
            <span class="info-value">{{ device.serial_port }} @ {{ device.baudrate }}</span>
          </template>
        </div>

        <!-- Expanded details when selected -->
        <div v-if="selectedDevice === device.name" class="device-details">
          <div class="detail-row">
            <span class="label">Status:</span>
            <span :class="['value', connectionStatus[device.name]?.connected ? 'connected' : 'disconnected']">
              {{ connectionStatus[device.name]?.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>
          <div v-if="connectionStatus[device.name]?.last_error" class="detail-row error">
            <span class="label">Last Error:</span>
            <span class="value">{{ connectionStatus[device.name]?.last_error }}</span>
          </div>
          <div class="detail-row">
            <span class="label">Timeout:</span>
            <span class="value">{{ device.timeout }}s</span>
          </div>
          <div class="detail-row">
            <span class="label">Retries:</span>
            <span class="value">{{ device.retries }}</span>
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
          <h3>Add Modbus Device</h3>
          <button class="close-btn" @click="showAddDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Device Name</label>
            <input v-model="deviceForm.name" type="text" placeholder="e.g., PLC_Main" />
          </div>

          <div class="form-row">
            <label>Connection Type</label>
            <select v-model="deviceForm.connection_type">
              <option value="tcp">Modbus TCP (Ethernet)</option>
              <option value="rtu">Modbus RTU (Serial)</option>
            </select>
          </div>

          <!-- TCP Settings -->
          <template v-if="deviceForm.connection_type === 'tcp'">
            <div class="form-group">
              <h4>TCP Connection</h4>
              <div class="form-row">
                <label>IP Address</label>
                <input v-model="deviceForm.ip_address" type="text" placeholder="192.168.1.100" />
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
                <input v-model="deviceForm.serial_port" type="text" placeholder="/dev/ttyUSB0 or COM3" />
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Baud Rate</label>
                  <select v-model.number="deviceForm.baudrate">
                    <option :value="9600">9600</option>
                    <option :value="19200">19200</option>
                    <option :value="38400">38400</option>
                    <option :value="57600">57600</option>
                    <option :value="115200">115200</option>
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
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Data Bits</label>
                  <select v-model.number="deviceForm.bytesize">
                    <option :value="7">7</option>
                    <option :value="8">8</option>
                  </select>
                </div>
                <div class="form-row half">
                  <label>Stop Bits</label>
                  <select v-model.number="deviceForm.stopbits">
                    <option :value="1">1</option>
                    <option :value="2">2</option>
                  </select>
                </div>
              </div>
            </div>
          </template>

          <!-- Common Settings -->
          <div class="form-group">
            <h4>Communication Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout" type="number" min="0.1" max="30" step="0.1" />
              </div>
              <div class="form-row half">
                <label>Retries</label>
                <input v-model.number="deviceForm.retries" type="number" min="0" max="10" />
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

    <!-- Edit Device Modal (same as add but for editing) -->
    <div v-if="showEditDeviceModal" class="modal-overlay" @click.self="showEditDeviceModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Edit Modbus Device: {{ deviceForm.name }}</h3>
          <button class="close-btn" @click="showEditDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Connection Type</label>
            <select v-model="deviceForm.connection_type">
              <option value="tcp">Modbus TCP (Ethernet)</option>
              <option value="rtu">Modbus RTU (Serial)</option>
            </select>
          </div>

          <!-- TCP Settings -->
          <template v-if="deviceForm.connection_type === 'tcp'">
            <div class="form-group">
              <h4>TCP Connection</h4>
              <div class="form-row">
                <label>IP Address</label>
                <input v-model="deviceForm.ip_address" type="text" placeholder="192.168.1.100" />
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
                <input v-model="deviceForm.serial_port" type="text" placeholder="/dev/ttyUSB0 or COM3" />
              </div>
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Baud Rate</label>
                  <select v-model.number="deviceForm.baudrate">
                    <option :value="9600">9600</option>
                    <option :value="19200">19200</option>
                    <option :value="38400">38400</option>
                    <option :value="57600">57600</option>
                    <option :value="115200">115200</option>
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
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Data Bits</label>
                  <select v-model.number="deviceForm.bytesize">
                    <option :value="7">7</option>
                    <option :value="8">8</option>
                  </select>
                </div>
                <div class="form-row half">
                  <label>Stop Bits</label>
                  <select v-model.number="deviceForm.stopbits">
                    <option :value="1">1</option>
                    <option :value="2">2</option>
                  </select>
                </div>
              </div>
            </div>
          </template>

          <!-- Common Settings -->
          <div class="form-group">
            <h4>Communication Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout" type="number" min="0.1" max="30" step="0.1" />
              </div>
              <div class="form-row half">
                <label>Retries</label>
                <input v-model.number="deviceForm.retries" type="number" min="0" max="10" />
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

    <!-- Address Changer Modal -->
    <ModbusAddressChanger
      v-if="showAddressChanger"
      @close="showAddressChanger = false"
    />
  </div>
</template>

<style scoped>
.modbus-config {
  padding: 1rem;
  background: var(--bg-secondary, #1e1e1e);
  border-radius: 8px;
  margin-bottom: 1rem;
}

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

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.8rem;
  background: #374151;
  color: #d1d5db;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.tool-btn:hover {
  background: #4b5563;
  color: white;
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

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #888;
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 0.5rem;
}

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

.device-details {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color, #333);
}

.detail-row {
  display: flex;
  gap: 0.5rem;
  font-size: 0.85rem;
  margin-bottom: 0.3rem;
}

.detail-row .label {
  color: #888;
  min-width: 80px;
}

.detail-row .value.connected {
  color: #22c55e;
}

.detail-row .value.disconnected {
  color: #888;
}

.detail-row.error .value {
  color: #ef4444;
}

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
  font-size: 0.9rem;
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
