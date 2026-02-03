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

// OPC-UA device state
interface OpcUaDevice {
  name: string
  enabled: boolean
  endpoint_url: string
  security_policy: string
  message_mode: string
  username: string
  password: string
  use_subscription: boolean
  subscription_interval_ms: number
  poll_rate_ms: number
  timeout_s: number
  namespace_uri: string
}

const devices = ref<OpcUaDevice[]>([])
const selectedDevice = ref<string | null>(null)
const showAddDeviceModal = ref(false)
const showEditDeviceModal = ref(false)
const showBrowseModal = ref(false)
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')

// Node browsing state
const browseDeviceName = ref('')
const browseNodeId = ref('ns=0;i=85')
const browseNodes = ref<any[]>([])
const browseHistory = ref<string[]>([])
const isBrowsing = ref(false)

// Form state for add/edit
const deviceForm = ref<OpcUaDevice>({
  name: '',
  enabled: true,
  endpoint_url: 'opc.tcp://localhost:4840',
  security_policy: 'None',
  message_mode: 'None',
  username: '',
  password: '',
  use_subscription: true,
  subscription_interval_ms: 100,
  poll_rate_ms: 100,
  timeout_s: 5.0,
  namespace_uri: ''
})

// Connection status from backend
const connectionStatus = ref<Record<string, {
  connected: boolean
  error_count: number
  last_error: string | null
  latency_ms: number
}>>({})

onMounted(() => {
  loadDevices()
  subscribeToStatus()
})

function loadDevices() {
  // Get data sources config from backend
  // For now, initialize empty - devices come from MQTT status
  devices.value = []
}

function subscribeToStatus() {
  mqtt.subscribe('nisystem/datasources/opcua/status', (message: any) => {
    if (message && typeof message === 'object') {
      connectionStatus.value = message
      // Update device list from status
      for (const [name, status] of Object.entries(message)) {
        const existingIdx = devices.value.findIndex(d => d.name === name)
        if (existingIdx < 0) {
          // Add device from status
          const s = status as Record<string, unknown>
          devices.value.push({
            name,
            enabled: true,
            endpoint_url: (s.endpoint_url as string) || '',
            security_policy: 'None',
            message_mode: 'None',
            username: '',
            password: '',
            use_subscription: true,
            subscription_interval_ms: 100,
            poll_rate_ms: 100,
            timeout_s: 5.0,
            namespace_uri: ''
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
    endpoint_url: 'opc.tcp://localhost:4840',
    security_policy: 'None',
    message_mode: 'None',
    username: '',
    password: '',
    use_subscription: true,
    subscription_interval_ms: 100,
    poll_rate_ms: 100,
    timeout_s: 5.0,
    namespace_uri: ''
  }
  showAddDeviceModal.value = true
}

function openEditDevice(device: OpcUaDevice) {
  deviceForm.value = { ...device }
  showEditDeviceModal.value = true
}

async function addDevice() {
  if (!deviceForm.value.name) {
    showFeedback('error', 'Device name is required')
    return
  }

  if (!deviceForm.value.endpoint_url) {
    showFeedback('error', 'Endpoint URL is required')
    return
  }

  if (devices.value.some(d => d.name === deviceForm.value.name)) {
    showFeedback('error', 'Device name already exists')
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/add', {
      type: 'opc_ua',
      name: deviceForm.value.name,
      enabled: deviceForm.value.enabled,
      endpoint_url: deviceForm.value.endpoint_url,
      security_policy: deviceForm.value.security_policy,
      message_mode: deviceForm.value.message_mode,
      username: deviceForm.value.username || null,
      password: deviceForm.value.password || null,
      use_subscription: deviceForm.value.use_subscription,
      subscription_interval_ms: deviceForm.value.subscription_interval_ms,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s,
      namespace_uri: deviceForm.value.namespace_uri || null
    })

    devices.value.push({ ...deviceForm.value })
    showAddDeviceModal.value = false
    showFeedback('success', `OPC-UA device "${deviceForm.value.name}" added`)
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
      type: 'opc_ua',
      name: deviceForm.value.name,
      enabled: deviceForm.value.enabled,
      endpoint_url: deviceForm.value.endpoint_url,
      security_policy: deviceForm.value.security_policy,
      message_mode: deviceForm.value.message_mode,
      username: deviceForm.value.username || null,
      password: deviceForm.value.password || null,
      use_subscription: deviceForm.value.use_subscription,
      subscription_interval_ms: deviceForm.value.subscription_interval_ms,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s,
      namespace_uri: deviceForm.value.namespace_uri || null
    })

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
  if (!confirm(`Delete OPC-UA device "${deviceName}"? This will remove all associated channels.`)) {
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/delete', { type: 'opc_ua', name: deviceName })
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
    const result = await mqtt.sendCommandWithAck('datasource/test', {
      type: 'opc_ua',
      name: deviceName
    }, 15000)

    if (result.success) {
      showFeedback('success', (result as DeviceCommandResult).message || `Connection to ${deviceName} successful`)
    } else {
      showFeedback('error', (result as DeviceCommandResult).message || result.error || `Connection to ${deviceName} failed`)
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Connection test timed out')
  } finally {
    isLoading.value = false
  }
}

async function openBrowser(deviceName: string) {
  browseDeviceName.value = deviceName
  browseNodeId.value = 'ns=0;i=85'
  browseNodes.value = []
  browseHistory.value = []
  showBrowseModal.value = true
  await browseNode('ns=0;i=85')
}

async function browseNode(nodeId: string) {
  isBrowsing.value = true
  browseNodeId.value = nodeId

  try {
    const result = await mqtt.sendCommandWithAck('datasource/opcua/browse', {
      name: browseDeviceName.value,
      node_id: nodeId
    }, 10000)

    const cmdResult = result as DeviceCommandResult
    if (result.success && Array.isArray(cmdResult.nodes)) {
      browseNodes.value = cmdResult.nodes
    } else {
      showFeedback('error', cmdResult.error || 'Browse failed')
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Browse timed out')
  } finally {
    isBrowsing.value = false
  }
}

function navigateToNode(node: any) {
  if (node.has_children) {
    browseHistory.value.push(browseNodeId.value)
    browseNode(node.node_id)
  }
}

function navigateBack() {
  if (browseHistory.value.length > 0) {
    const prevNodeId = browseHistory.value.pop()!
    browseNode(prevNodeId)
  }
}

function addNodeAsChannel(node: any) {
  // Would add this node as a channel - emit event or call MQTT
  mqtt.sendCommand('channel/add', {
    source_type: 'opc_ua',
    source_name: browseDeviceName.value,
    channel_name: node.browse_name || node.display_name,
    node_id: node.node_id,
    data_type: node.data_type || 'float32'
  })
  showFeedback('success', `Added channel: ${node.display_name}`)
}

function showFeedback(type: 'success' | 'error', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
  setTimeout(() => {
    feedbackMessage.value = ''
  }, 3000)
}
</script>

<template>
  <div class="opcua-config">
    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">&#128268;</span>
        OPC-UA Servers
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
          Add Server
        </button>
      </div>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Device list -->
    <div v-if="devices.length === 0" class="empty-state">
      <p>No OPC-UA servers configured</p>
      <p class="hint">Click "Add Server" to connect to an OPC-UA server</p>
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
          <span class="device-icon">&#128268;</span>
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
          <span class="info-tag">OPC-UA</span>
          <span class="info-value">{{ device.endpoint_url }}</span>
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
          <div class="detail-row">
            <span class="label">Security:</span>
            <span class="value">{{ device.security_policy }}</span>
          </div>
          <div class="detail-row">
            <span class="label">Mode:</span>
            <span class="value">{{ device.use_subscription ? 'Subscription' : 'Polling' }}</span>
          </div>

          <div class="device-actions">
            <button class="action-btn" @click.stop="testConnection(device.name)" :disabled="isLoading">
              Test Connection
            </button>
            <button class="action-btn" @click.stop="openBrowser(device.name)" :disabled="isLoading || !connectionStatus[device.name]?.connected">
              Browse Nodes
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
          <h3>Add OPC-UA Server</h3>
          <button class="close-btn" @click="showAddDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Server Name</label>
            <input v-model="deviceForm.name" type="text" placeholder="e.g., SCADA_Server" />
          </div>

          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>Endpoint URL</label>
              <input v-model="deviceForm.endpoint_url" type="text" placeholder="opc.tcp://hostname:4840" />
            </div>
            <div class="form-row">
              <label>Namespace URI (optional)</label>
              <input v-model="deviceForm.namespace_uri" type="text" placeholder="Auto-detect" />
            </div>
          </div>

          <div class="form-group">
            <h4>Security</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Security Policy</label>
                <select v-model="deviceForm.security_policy">
                  <option value="None">None</option>
                  <option value="Basic128Rsa15">Basic128Rsa15</option>
                  <option value="Basic256">Basic256</option>
                  <option value="Basic256Sha256">Basic256Sha256</option>
                </select>
              </div>
              <div class="form-row half">
                <label>Message Mode</label>
                <select v-model="deviceForm.message_mode">
                  <option value="None">None</option>
                  <option value="Sign">Sign</option>
                  <option value="SignAndEncrypt">Sign & Encrypt</option>
                </select>
              </div>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Username (optional)</label>
                <input v-model="deviceForm.username" type="text" placeholder="Anonymous" />
              </div>
              <div class="form-row half">
                <label>Password</label>
                <input v-model="deviceForm.password" type="password" />
              </div>
            </div>
          </div>

          <div class="form-group">
            <h4>Communication</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.use_subscription" />
                Use subscriptions (more efficient)
              </label>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label v-if="deviceForm.use_subscription">Subscription Interval (ms)</label>
                <label v-else>Poll Rate (ms)</label>
                <input
                  v-if="deviceForm.use_subscription"
                  v-model.number="deviceForm.subscription_interval_ms"
                  type="number"
                  min="10"
                  max="10000"
                />
                <input
                  v-else
                  v-model.number="deviceForm.poll_rate_ms"
                  type="number"
                  min="10"
                  max="10000"
                />
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
              Enable server
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showAddDeviceModal = false">Cancel</button>
          <button class="btn primary" @click="addDevice" :disabled="isLoading || !deviceForm.name">
            {{ isLoading ? 'Adding...' : 'Add Server' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Device Modal -->
    <div v-if="showEditDeviceModal" class="modal-overlay" @click.self="showEditDeviceModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Edit OPC-UA Server: {{ deviceForm.name }}</h3>
          <button class="close-btn" @click="showEditDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>Endpoint URL</label>
              <input v-model="deviceForm.endpoint_url" type="text" placeholder="opc.tcp://hostname:4840" />
            </div>
            <div class="form-row">
              <label>Namespace URI (optional)</label>
              <input v-model="deviceForm.namespace_uri" type="text" placeholder="Auto-detect" />
            </div>
          </div>

          <div class="form-group">
            <h4>Security</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Security Policy</label>
                <select v-model="deviceForm.security_policy">
                  <option value="None">None</option>
                  <option value="Basic128Rsa15">Basic128Rsa15</option>
                  <option value="Basic256">Basic256</option>
                  <option value="Basic256Sha256">Basic256Sha256</option>
                </select>
              </div>
              <div class="form-row half">
                <label>Message Mode</label>
                <select v-model="deviceForm.message_mode">
                  <option value="None">None</option>
                  <option value="Sign">Sign</option>
                  <option value="SignAndEncrypt">Sign & Encrypt</option>
                </select>
              </div>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Username (optional)</label>
                <input v-model="deviceForm.username" type="text" placeholder="Anonymous" />
              </div>
              <div class="form-row half">
                <label>Password</label>
                <input v-model="deviceForm.password" type="password" />
              </div>
            </div>
          </div>

          <div class="form-group">
            <h4>Communication</h4>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.use_subscription" />
                Use subscriptions (more efficient)
              </label>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label v-if="deviceForm.use_subscription">Subscription Interval (ms)</label>
                <label v-else>Poll Rate (ms)</label>
                <input
                  v-if="deviceForm.use_subscription"
                  v-model.number="deviceForm.subscription_interval_ms"
                  type="number"
                  min="10"
                  max="10000"
                />
                <input
                  v-else
                  v-model.number="deviceForm.poll_rate_ms"
                  type="number"
                  min="10"
                  max="10000"
                />
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
              Enable server
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

    <!-- Browse Nodes Modal -->
    <div v-if="showBrowseModal" class="modal-overlay" @click.self="showBrowseModal = false">
      <div class="modal wide">
        <div class="modal-header">
          <h3>Browse OPC-UA Nodes: {{ browseDeviceName }}</h3>
          <button class="close-btn" @click="showBrowseModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="browse-path">
            <button class="path-btn" @click="navigateBack" :disabled="browseHistory.length === 0 || isBrowsing">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              Back
            </button>
            <span class="current-path">{{ browseNodeId }}</span>
          </div>

          <div class="node-list" :class="{ loading: isBrowsing }">
            <div v-if="isBrowsing" class="loading-indicator">Loading...</div>
            <div v-else-if="browseNodes.length === 0" class="empty-browse">
              No child nodes found
            </div>
            <div
              v-else
              v-for="node in browseNodes"
              :key="node.node_id"
              class="node-item"
              :class="{ folder: node.has_children, variable: node.node_class === 'Variable' }"
              @dblclick="navigateToNode(node)"
            >
              <span class="node-icon">
                {{ node.has_children ? '&#128193;' : node.node_class === 'Variable' ? '&#128203;' : '&#128196;' }}
              </span>
              <div class="node-info">
                <span class="node-name">{{ node.display_name }}</span>
                <span class="node-details">
                  {{ node.node_id }}
                  <span v-if="node.data_type" class="data-type">{{ node.data_type }}</span>
                  <span v-if="node.value !== undefined" class="node-value">= {{ node.value }}</span>
                </span>
              </div>
              <button
                v-if="node.node_class === 'Variable'"
                class="add-channel-btn"
                @click.stop="addNodeAsChannel(node)"
                title="Add as channel"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
              </button>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showBrowseModal = false">Close</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.opcua-config {
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
  background: var(--bg-secondary, #1e1e1e);
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

/* Browse modal styles */
.browse-path {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 0.5rem;
  background: var(--bg-tertiary, #252525);
  border-radius: 4px;
}

.path-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.6rem;
  background: #374151;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.path-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.current-path {
  font-family: monospace;
  font-size: 0.85rem;
  color: #888;
}

.node-list {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
}

.node-list.loading {
  opacity: 0.5;
}

.loading-indicator,
.empty-browse {
  padding: 2rem;
  text-align: center;
  color: #888;
}

.node-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-color, #333);
  cursor: pointer;
}

.node-item:last-child {
  border-bottom: none;
}

.node-item:hover {
  background: var(--bg-tertiary, #252525);
}

.node-item.folder {
  cursor: pointer;
}

.node-icon {
  font-size: 1rem;
  min-width: 1.5rem;
  text-align: center;
}

.node-info {
  flex: 1;
  min-width: 0;
}

.node-name {
  display: block;
  font-weight: 500;
}

.node-details {
  display: block;
  font-size: 0.75rem;
  color: #888;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.data-type {
  display: inline-block;
  padding: 0.1rem 0.3rem;
  background: #374151;
  border-radius: 3px;
  margin-left: 0.5rem;
}

.node-value {
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
</style>
