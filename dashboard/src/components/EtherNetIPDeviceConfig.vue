<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { DeviceCommandResult } from '../types'

const mqtt = useMqtt()

// Props
const props = defineProps<{
  editMode: boolean
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
}>()

// EtherNet/IP device state
interface EtherNetIPDevice {
  name: string
  enabled: boolean
  ip_address: string
  slot: number
  plc_type: string
  init_tags: boolean
  init_program_tags: boolean
  use_batch_read: boolean
  poll_rate_ms: number
  timeout_s: number
}

const devices = ref<EtherNetIPDevice[]>([])
const selectedDevice = ref<string | null>(null)
const showAddDeviceModal = ref(false)
const showEditDeviceModal = ref(false)
const showTagBrowserModal = ref(false)
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')

// Tag browsing state
const browseDeviceName = ref('')
const tagList = ref<any[]>([])
const tagFilter = ref('')
const isBrowsing = ref(false)

// Form state for add/edit
const deviceForm = ref<EtherNetIPDevice>({
  name: '',
  enabled: true,
  ip_address: '192.168.1.1',
  slot: 0,
  plc_type: 'controllogix',
  init_tags: true,
  init_program_tags: false,
  use_batch_read: true,
  poll_rate_ms: 100,
  timeout_s: 5.0
})

// Connection status from backend
const connectionStatus = ref<Record<string, {
  connected: boolean
  error_count: number
  last_error: string | null
  latency_ms: number
}>>({})

// PLC info for connected devices
const plcInfo = ref<Record<string, any>>({})

onMounted(() => {
  loadDevices()
  subscribeToStatus()
})

function loadDevices() {
  // Initialize empty - devices come from MQTT status
  devices.value = []
}

function subscribeToStatus() {
  mqtt.subscribe('nisystem/datasources/ethernetip/status', (message: any) => {
    if (message && typeof message === 'object') {
      connectionStatus.value = message
      // Update device list from status
      for (const [name, status] of Object.entries(message)) {
        const existingIdx = devices.value.findIndex(d => d.name === name)
        if (existingIdx < 0) {
          const s = status as Record<string, unknown>
          devices.value.push({
            name,
            enabled: true,
            ip_address: (s.ip_address as string) || '',
            slot: (s.slot as number) || 0,
            plc_type: (s.plc_type as string) || 'controllogix',
            init_tags: true,
            init_program_tags: false,
            use_batch_read: true,
            poll_rate_ms: 100,
            timeout_s: 5.0
          })
        }
      }
    }
  })
}

function openAddDevice() {
  deviceForm.value = {
    name: '',
    enabled: true,
    ip_address: '192.168.1.1',
    slot: 0,
    plc_type: 'controllogix',
    init_tags: true,
    init_program_tags: false,
    use_batch_read: true,
    poll_rate_ms: 100,
    timeout_s: 5.0
  }
  showAddDeviceModal.value = true
}

function openEditDevice(device: EtherNetIPDevice) {
  deviceForm.value = { ...device }
  showEditDeviceModal.value = true
}

async function addDevice() {
  if (!deviceForm.value.name) {
    showFeedback('error', 'Device name is required')
    return
  }

  if (!deviceForm.value.ip_address) {
    showFeedback('error', 'IP address is required')
    return
  }

  if (devices.value.some(d => d.name === deviceForm.value.name)) {
    showFeedback('error', 'Device name already exists')
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/add', {
      type: 'ethernet_ip',
      name: deviceForm.value.name,
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ip_address,
      slot: deviceForm.value.slot,
      plc_type: deviceForm.value.plc_type,
      init_tags: deviceForm.value.init_tags,
      init_program_tags: deviceForm.value.init_program_tags,
      use_batch_read: deviceForm.value.use_batch_read,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s
    })

    devices.value.push({ ...deviceForm.value })
    showAddDeviceModal.value = false
    showFeedback('success', `PLC "${deviceForm.value.name}" added`)
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
    mqtt.sendCommand('datasource/update', {
      type: 'ethernet_ip',
      name: deviceForm.value.name,
      enabled: deviceForm.value.enabled,
      ip_address: deviceForm.value.ip_address,
      slot: deviceForm.value.slot,
      plc_type: deviceForm.value.plc_type,
      init_tags: deviceForm.value.init_tags,
      init_program_tags: deviceForm.value.init_program_tags,
      use_batch_read: deviceForm.value.use_batch_read,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s
    })

    const index = devices.value.findIndex(d => d.name === deviceForm.value.name)
    if (index >= 0) {
      devices.value[index] = { ...deviceForm.value }
    }
    showEditDeviceModal.value = false
    showFeedback('success', `PLC "${deviceForm.value.name}" updated`)
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to update device')
  } finally {
    isLoading.value = false
  }
}

async function deleteDevice(deviceName: string) {
  if (!confirm(`Delete PLC "${deviceName}"? This will remove all associated channels.`)) {
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/delete', { type: 'ethernet_ip', name: deviceName })
    devices.value = devices.value.filter(d => d.name !== deviceName)
    if (selectedDevice.value === deviceName) {
      selectedDevice.value = null
    }
    showFeedback('success', `PLC "${deviceName}" deleted`)
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
    const result = await mqtt.sendCommandWithAck('datasource/test', {
      type: 'ethernet_ip',
      name: deviceName
    }, 15000)

    if (result.success) {
      // Store PLC info if returned
      const cmdResult = result as DeviceCommandResult
      if (cmdResult.plc_info) {
        plcInfo.value[deviceName] = cmdResult.plc_info
      }
      showFeedback('success', cmdResult.message || `Connection to ${deviceName} successful`)
    } else {
      showFeedback('error', (result as DeviceCommandResult).message || result.error || `Connection to ${deviceName} failed`)
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Connection test timed out')
  } finally {
    isLoading.value = false
  }
}

async function openTagBrowser(deviceName: string) {
  browseDeviceName.value = deviceName
  tagList.value = []
  tagFilter.value = ''
  showTagBrowserModal.value = true
  await loadTags()
}

async function loadTags() {
  isBrowsing.value = true

  try {
    const result = await mqtt.sendCommandWithAck('datasource/ethernetip/tags', {
      name: browseDeviceName.value
    }, 30000)

    const cmdResult = result as DeviceCommandResult
    if (result.success && Array.isArray(cmdResult.tags)) {
      tagList.value = cmdResult.tags
    } else {
      showFeedback('error', cmdResult.error || 'Failed to load tags')
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Tag list timed out')
  } finally {
    isBrowsing.value = false
  }
}

const filteredTags = computed(() => {
  if (!tagFilter.value) return tagList.value
  const filter = tagFilter.value.toLowerCase()
  return tagList.value.filter(tag =>
    (tag.name && tag.name.toLowerCase().includes(filter)) ||
    tag.data_type?.toLowerCase().includes(filter)
  )
})

function addTagAsChannel(tag: any) {
  mqtt.sendCommand('channel/add', {
    source_type: 'ethernet_ip',
    source_name: browseDeviceName.value,
    channel_name: tag.name,
    tag_name: tag.name,
    data_type: tag.data_type || 'REAL'
  })
  showFeedback('success', `Added channel: ${tag.name}`)
}

function showFeedback(type: 'success' | 'error', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
  setTimeout(() => {
    feedbackMessage.value = ''
  }, 3000)
}

import { computed } from 'vue'
</script>

<template>
  <div class="ethernet-ip-config">
    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">&#128376;</span>
        Allen Bradley PLCs
      </h3>
      <div class="header-actions">
        <button
          v-if="editMode"
          class="add-btn"
          @click="openAddDevice"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add PLC
        </button>
      </div>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Device list -->
    <div v-if="devices.length === 0" class="empty-state">
      <p>No Allen Bradley PLCs configured</p>
      <p class="hint">Click "Add PLC" to connect to a ControlLogix or CompactLogix PLC</p>
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
          <span class="device-icon">&#128376;</span>
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
          <span class="info-tag">{{ device.plc_type.toUpperCase() }}</span>
          <span class="info-value">{{ device.ip_address }} / Slot {{ device.slot }}</span>
        </div>

        <!-- Expanded details when selected -->
        <div v-if="selectedDevice === device.name" class="device-details">
          <div class="detail-row">
            <span class="label">Status:</span>
            <span :class="['value', connectionStatus[device.name]?.connected ? 'connected' : 'disconnected']">
              {{ connectionStatus[device.name]?.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>
          <div v-if="connectionStatus[device.name]?.latency_ms" class="detail-row">
            <span class="label">Latency:</span>
            <span class="value">{{ connectionStatus[device.name]?.latency_ms.toFixed(1) }} ms</span>
          </div>
          <div v-if="connectionStatus[device.name]?.last_error" class="detail-row error">
            <span class="label">Last Error:</span>
            <span class="value">{{ connectionStatus[device.name]?.last_error }}</span>
          </div>

          <!-- PLC Info if available -->
          <template v-if="plcInfo[device.name]">
            <div class="detail-row">
              <span class="label">Product:</span>
              <span class="value">{{ plcInfo[device.name].product_name }}</span>
            </div>
            <div class="detail-row">
              <span class="label">Revision:</span>
              <span class="value">{{ plcInfo[device.name].revision }}</span>
            </div>
            <div class="detail-row">
              <span class="label">Serial:</span>
              <span class="value">{{ plcInfo[device.name].serial_number }}</span>
            </div>
          </template>

          <div class="detail-row">
            <span class="label">Mode:</span>
            <span class="value">{{ device.use_batch_read ? 'Batch Read' : 'Individual' }}</span>
          </div>
          <div class="detail-row">
            <span class="label">Poll Rate:</span>
            <span class="value">{{ device.poll_rate_ms }} ms</span>
          </div>

          <div class="device-actions">
            <button class="action-btn" @click.stop="testConnection(device.name)" :disabled="isLoading">
              Test Connection
            </button>
            <button class="action-btn" @click.stop="openTagBrowser(device.name)" :disabled="isLoading || !connectionStatus[device.name]?.connected">
              Browse Tags
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
          <h3>Add Allen Bradley PLC</h3>
          <button class="close-btn" @click="showAddDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Device Name</label>
            <input v-model="deviceForm.name" type="text" placeholder="e.g., Main_PLC" />
          </div>

          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>IP Address</label>
              <input v-model="deviceForm.ip_address" type="text" placeholder="192.168.1.1" />
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>PLC Type</label>
                <select v-model="deviceForm.plc_type">
                  <option value="controllogix">ControlLogix</option>
                  <option value="compactlogix">CompactLogix</option>
                  <option value="micro800">Micro800</option>
                </select>
              </div>
              <div class="form-row half">
                <label>Slot Number</label>
                <input v-model.number="deviceForm.slot" type="number" min="0" max="16" />
              </div>
            </div>
          </div>

          <div class="form-group">
            <h4>Tag Discovery</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.init_tags" />
                Read controller tags on connect
              </label>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.init_program_tags" />
                Also read program-scoped tags
              </label>
            </div>
          </div>

          <div class="form-group">
            <h4>Communication</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.use_batch_read" />
                Use batch reads (more efficient)
              </label>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Poll Rate (ms)</label>
                <input v-model.number="deviceForm.poll_rate_ms" type="number" min="10" max="10000" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout_s" type="number" min="1" max="60" step="0.5" />
              </div>
            </div>
          </div>

          <div class="form-row checkbox-row">
            <label>
              <input type="checkbox" v-model="deviceForm.enabled" />
              Enable PLC
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showAddDeviceModal = false">Cancel</button>
          <button class="btn primary" @click="addDevice" :disabled="isLoading || !deviceForm.name">
            {{ isLoading ? 'Adding...' : 'Add PLC' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Device Modal -->
    <div v-if="showEditDeviceModal" class="modal-overlay" @click.self="showEditDeviceModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Edit PLC: {{ deviceForm.name }}</h3>
          <button class="close-btn" @click="showEditDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>IP Address</label>
              <input v-model="deviceForm.ip_address" type="text" placeholder="192.168.1.1" />
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>PLC Type</label>
                <select v-model="deviceForm.plc_type">
                  <option value="controllogix">ControlLogix</option>
                  <option value="compactlogix">CompactLogix</option>
                  <option value="micro800">Micro800</option>
                </select>
              </div>
              <div class="form-row half">
                <label>Slot Number</label>
                <input v-model.number="deviceForm.slot" type="number" min="0" max="16" />
              </div>
            </div>
          </div>

          <div class="form-group">
            <h4>Tag Discovery</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.init_tags" />
                Read controller tags on connect
              </label>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.init_program_tags" />
                Also read program-scoped tags
              </label>
            </div>
          </div>

          <div class="form-group">
            <h4>Communication</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.use_batch_read" />
                Use batch reads (more efficient)
              </label>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Poll Rate (ms)</label>
                <input v-model.number="deviceForm.poll_rate_ms" type="number" min="10" max="10000" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout_s" type="number" min="1" max="60" step="0.5" />
              </div>
            </div>
          </div>

          <div class="form-row checkbox-row">
            <label>
              <input type="checkbox" v-model="deviceForm.enabled" />
              Enable PLC
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

    <!-- Tag Browser Modal -->
    <div v-if="showTagBrowserModal" class="modal-overlay" @click.self="showTagBrowserModal = false">
      <div class="modal wide">
        <div class="modal-header">
          <h3>Browse Tags: {{ browseDeviceName }}</h3>
          <button class="close-btn" @click="showTagBrowserModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="tag-search">
            <input
              v-model="tagFilter"
              type="text"
              placeholder="Filter tags..."
              class="search-input"
            />
            <button class="refresh-btn" @click="loadTags" :disabled="isBrowsing">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 4v6h-6M1 20v-6h6"/>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
              </svg>
              Refresh
            </button>
          </div>

          <div class="tag-list" :class="{ loading: isBrowsing }">
            <div v-if="isBrowsing" class="loading-indicator">Loading tags...</div>
            <div v-else-if="filteredTags.length === 0" class="empty-browse">
              {{ tagFilter ? 'No tags match filter' : 'No tags found' }}
            </div>
            <div
              v-else
              v-for="tag in filteredTags"
              :key="tag.name"
              class="tag-item"
              :class="{ array: tag.dim > 0 }"
            >
              <span class="tag-icon">
                {{ tag.dim > 0 ? '&#128194;' : '&#128203;' }}
              </span>
              <div class="tag-info">
                <span class="tag-name">{{ tag.name }}</span>
                <span class="tag-details">
                  <span class="data-type">{{ tag.data_type }}</span>
                  <span v-if="tag.dim > 0" class="array-info">[{{ tag.dim }}]</span>
                  <span v-if="tag.value !== undefined" class="tag-value">= {{ tag.value }}</span>
                </span>
              </div>
              <button
                class="add-channel-btn"
                @click.stop="addTagAsChannel(tag)"
                title="Add as channel"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
              </button>
            </div>
          </div>

          <div class="tag-count">
            {{ filteredTags.length }} of {{ tagList.length }} tags
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showTagBrowserModal = false">Close</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ethernet-ip-config {
  padding: 1rem;
  background: var(--bg-secondary);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border-color);
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
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
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
  border-top: 1px solid var(--border-color);
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
  flex-wrap: wrap;
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
  background: var(--bg-secondary);
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal.wide {
  max-width: 700px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
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
  border-top: 1px solid var(--border-color);
}

.form-group {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--bg-elevated);
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
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
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

/* Tag browser styles */
.tag-search {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.search-input {
  flex: 1;
  padding: 0.5rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: white;
}

.search-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.5rem 0.75rem;
  background: #374151;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.refresh-btn:hover {
  background: #4b5563;
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tag-list {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.tag-list.loading {
  opacity: 0.5;
}

.loading-indicator,
.empty-browse {
  padding: 2rem;
  text-align: center;
  color: #888;
}

.tag-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.tag-item:last-child {
  border-bottom: none;
}

.tag-item:hover {
  background: var(--bg-elevated);
}

.tag-icon {
  font-size: 1rem;
  min-width: 1.5rem;
  text-align: center;
}

.tag-info {
  flex: 1;
  min-width: 0;
}

.tag-name {
  display: block;
  font-weight: 500;
  font-family: monospace;
}

.tag-details {
  display: block;
  font-size: 0.75rem;
  color: #888;
}

.data-type {
  display: inline-block;
  padding: 0.1rem 0.3rem;
  background: #374151;
  border-radius: 3px;
}

.array-info {
  margin-left: 0.3rem;
  color: #f59e0b;
}

.tag-value {
  color: #22c55e;
  margin-left: 0.5rem;
}

.add-channel-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.3rem;
  background: #22c55e;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.add-channel-btn:hover {
  background: #16a34a;
}

.tag-count {
  padding: 0.5rem;
  text-align: center;
  font-size: 0.8rem;
  color: #888;
  border-top: 1px solid var(--border-color);
}
</style>
