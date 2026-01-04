<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const mqtt = useMqtt()

// Props
const props = defineProps<{
  editMode: boolean
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
}>()

// REST API device state
interface RestEndpoint {
  name: string          // Channel name
  address: string       // API endpoint path
  data_type: string     // float32, int32, bool, string
  scale: number
  offset: number
  unit: string
  is_output: boolean
  response_key?: string // JSON path to value
}

interface RestDevice {
  name: string
  enabled: boolean
  base_url: string
  auth_type: 'none' | 'basic' | 'bearer' | 'api_key'
  username?: string
  password?: string
  bearer_token?: string
  api_key?: string
  api_key_header?: string
  poll_rate_ms: number
  timeout_s: number
  verify_ssl: boolean
  endpoints: RestEndpoint[]
}

const devices = ref<RestDevice[]>([])
const selectedDevice = ref<string | null>(null)
const showAddDeviceModal = ref(false)
const showEditDeviceModal = ref(false)
const showAddEndpointModal = ref(false)
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')

// Form state for add/edit device
const deviceForm = ref<RestDevice>({
  name: '',
  enabled: true,
  base_url: 'http://192.168.1.100',
  auth_type: 'none',
  username: '',
  password: '',
  bearer_token: '',
  api_key: '',
  api_key_header: 'X-API-Key',
  poll_rate_ms: 500,
  timeout_s: 5.0,
  verify_ssl: true,
  endpoints: []
})

// Form state for add endpoint
const endpointForm = ref<RestEndpoint>({
  name: '',
  address: '/api/v1/value',
  data_type: 'float32',
  scale: 1.0,
  offset: 0.0,
  unit: '',
  is_output: false,
  response_key: ''
})

// Connection status from backend
const connectionStatus = ref<Record<string, {
  connected: boolean
  state: string
  error_count: number
  last_error: string | null
  latency_ms: number
  channel_count: number
}>>({})

// Auth type options
const authTypes = [
  { value: 'none', label: 'No Authentication' },
  { value: 'basic', label: 'Basic Auth (Username/Password)' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'api_key', label: 'API Key' }
]

// Data type options
const dataTypes = [
  { value: 'float32', label: 'Float (32-bit)' },
  { value: 'int32', label: 'Integer (32-bit)' },
  { value: 'uint32', label: 'Unsigned Integer (32-bit)' },
  { value: 'bool', label: 'Boolean' },
  { value: 'string', label: 'String' }
]

// Initialize - load devices from backend status
onMounted(() => {
  subscribeToStatus()
})

function subscribeToStatus() {
  // Subscribe to data source status updates
  mqtt.subscribe('nisystem/datasource/status', (message: any) => {
    if (message && typeof message === 'object') {
      // Update connection status
      if (message.sources) {
        connectionStatus.value = message.sources
      }
      // Update devices list from sources
      updateDevicesFromStatus(message)
    }
  })

  // Subscribe to response messages
  mqtt.subscribe('nisystem/datasource/response', (message: any) => {
    if (message && typeof message === 'object') {
      showFeedback(message.success ? 'success' : 'error', message.message)
    }
  })

  // Request current status
  mqtt.sendCommand('datasource/list', {})
}

function updateDevicesFromStatus(status: any) {
  if (!status.sources) return

  devices.value = []
  for (const [name, sourceStatus] of Object.entries(status.sources as Record<string, any>)) {
    if (sourceStatus.type === 'rest_api') {
      // Get channels for this source
      const channels: RestEndpoint[] = []
      for (const [chName, chInfo] of Object.entries(status.channels || {})) {
        const ch = chInfo as any
        if (ch.source === name) {
          channels.push({
            name: chName,
            address: ch.address || '',
            data_type: ch.data_type || 'float32',
            scale: 1.0,
            offset: 0.0,
            unit: ch.unit || '',
            is_output: ch.is_output || false
          })
        }
      }

      devices.value.push({
        name,
        enabled: sourceStatus.enabled,
        base_url: '',  // Will be populated when editing
        auth_type: 'none',
        poll_rate_ms: 500,
        timeout_s: 5.0,
        verify_ssl: true,
        endpoints: channels
      })
    }
  }
}

function openAddDevice() {
  deviceForm.value = {
    name: '',
    enabled: true,
    base_url: 'http://192.168.1.100',
    auth_type: 'none',
    username: '',
    password: '',
    bearer_token: '',
    api_key: '',
    api_key_header: 'X-API-Key',
    poll_rate_ms: 500,
    timeout_s: 5.0,
    verify_ssl: true,
    endpoints: []
  }
  showAddDeviceModal.value = true
}

function openEditDevice(device: RestDevice) {
  deviceForm.value = { ...device, endpoints: [...device.endpoints] }
  showEditDeviceModal.value = true
}

function openAddEndpoint() {
  endpointForm.value = {
    name: '',
    address: '/api/v1/value',
    data_type: 'float32',
    scale: 1.0,
    offset: 0.0,
    unit: '',
    is_output: false,
    response_key: ''
  }
  showAddEndpointModal.value = true
}

function addEndpointToForm() {
  if (!endpointForm.value.name || !endpointForm.value.address) {
    showFeedback('error', 'Endpoint name and address are required')
    return
  }

  // Check for duplicate names
  if (deviceForm.value.endpoints.some(e => e.name === endpointForm.value.name)) {
    showFeedback('error', 'Endpoint name already exists')
    return
  }

  deviceForm.value.endpoints.push({ ...endpointForm.value })
  showAddEndpointModal.value = false
}

function removeEndpointFromForm(index: number) {
  deviceForm.value.endpoints.splice(index, 1)
}

async function addDevice() {
  if (!deviceForm.value.name) {
    showFeedback('error', 'Device name is required')
    return
  }

  if (!deviceForm.value.base_url) {
    showFeedback('error', 'Base URL is required')
    return
  }

  isLoading.value = true
  try {
    // Build connection config
    const connection: Record<string, any> = {
      base_url: deviceForm.value.base_url,
      auth_type: deviceForm.value.auth_type,
      verify_ssl: deviceForm.value.verify_ssl
    }

    if (deviceForm.value.auth_type === 'basic') {
      connection.username = deviceForm.value.username
      connection.password = deviceForm.value.password
    } else if (deviceForm.value.auth_type === 'bearer') {
      connection.bearer_token = deviceForm.value.bearer_token
    } else if (deviceForm.value.auth_type === 'api_key') {
      connection.api_key = deviceForm.value.api_key
      connection.api_key_header = deviceForm.value.api_key_header
    }

    // Build channels config
    const channels = deviceForm.value.endpoints.map(ep => ({
      name: ep.name,
      address: ep.address,
      data_type: ep.data_type,
      scale: ep.scale,
      offset: ep.offset,
      unit: ep.unit,
      is_output: ep.is_output
    }))

    // Send to backend
    mqtt.sendCommand('datasource/add', {
      name: deviceForm.value.name,
      type: 'rest_api',
      enabled: deviceForm.value.enabled,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s,
      connection,
      channels
    })

    showAddDeviceModal.value = false
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
    const connection: Record<string, any> = {
      base_url: deviceForm.value.base_url,
      auth_type: deviceForm.value.auth_type,
      verify_ssl: deviceForm.value.verify_ssl
    }

    if (deviceForm.value.auth_type === 'basic') {
      connection.username = deviceForm.value.username
      connection.password = deviceForm.value.password
    } else if (deviceForm.value.auth_type === 'bearer') {
      connection.bearer_token = deviceForm.value.bearer_token
    } else if (deviceForm.value.auth_type === 'api_key') {
      connection.api_key = deviceForm.value.api_key
      connection.api_key_header = deviceForm.value.api_key_header
    }

    const channels = deviceForm.value.endpoints.map(ep => ({
      name: ep.name,
      address: ep.address,
      data_type: ep.data_type,
      scale: ep.scale,
      offset: ep.offset,
      unit: ep.unit,
      is_output: ep.is_output
    }))

    mqtt.sendCommand('datasource/update', {
      name: deviceForm.value.name,
      type: 'rest_api',
      enabled: deviceForm.value.enabled,
      poll_rate_ms: deviceForm.value.poll_rate_ms,
      timeout_s: deviceForm.value.timeout_s,
      connection,
      channels
    })

    showEditDeviceModal.value = false
    emit('dirty')

  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to update device')
  } finally {
    isLoading.value = false
  }
}

async function deleteDevice(deviceName: string) {
  if (!confirm(`Delete REST API device "${deviceName}"? This will remove all associated channels.`)) {
    return
  }

  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/delete', { name: deviceName })
    if (selectedDevice.value === deviceName) {
      selectedDevice.value = null
    }
    emit('dirty')
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to delete device')
  } finally {
    isLoading.value = false
  }
}

async function testConnection(deviceName: string) {
  isLoading.value = true
  try {
    mqtt.sendCommand('datasource/test', { name: deviceName })
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to test connection')
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

// Format latency
function formatLatency(ms: number): string {
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<template>
  <div class="rest-api-config">
    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">🌐</span>
        REST API Data Sources
      </h3>
      <button
        v-if="editMode"
        class="add-btn"
        @click="openAddDevice"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        Add REST Source
      </button>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Device list -->
    <div v-if="devices.length === 0" class="empty-state">
      <p>No REST API sources configured</p>
      <p class="hint">Click "Add REST Source" to add an Opto22, custom API, or other REST endpoint</p>
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
          <span class="device-icon">🌐</span>
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
          <span class="info-tag">REST</span>
          <span class="info-value">{{ device.base_url || '(not configured)' }}</span>
          <span v-if="connectionStatus[device.name]?.latency_ms" class="info-latency">
            {{ formatLatency(connectionStatus[device.name].latency_ms) }}
          </span>
        </div>

        <!-- Expanded details when selected -->
        <div v-if="selectedDevice === device.name" class="device-details">
          <div class="detail-row">
            <span class="label">Status:</span>
            <span :class="['value', connectionStatus[device.name]?.connected ? 'connected' : 'disconnected']">
              {{ connectionStatus[device.name]?.state || 'Unknown' }}
            </span>
          </div>
          <div v-if="connectionStatus[device.name]?.last_error" class="detail-row error">
            <span class="label">Last Error:</span>
            <span class="value">{{ connectionStatus[device.name]?.last_error }}</span>
          </div>
          <div class="detail-row">
            <span class="label">Channels:</span>
            <span class="value">{{ connectionStatus[device.name]?.channel_count || device.endpoints.length }}</span>
          </div>

          <!-- Endpoints list -->
          <div v-if="device.endpoints.length > 0" class="endpoints-section">
            <h4>Endpoints</h4>
            <div class="endpoint-list">
              <div v-for="ep in device.endpoints" :key="ep.name" class="endpoint-item">
                <span class="ep-name">{{ ep.name }}</span>
                <span class="ep-address">{{ ep.address }}</span>
                <span class="ep-type">{{ ep.data_type }}</span>
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
      <div class="modal modal-wide">
        <div class="modal-header">
          <h3>Add REST API Source</h3>
          <button class="close-btn" @click="showAddDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Source Name</label>
            <input v-model="deviceForm.name" type="text" placeholder="e.g., Opto22_Main" />
          </div>

          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>Base URL</label>
              <input v-model="deviceForm.base_url" type="text" placeholder="http://192.168.1.100:8080" />
            </div>

            <div class="form-row">
              <label>Authentication</label>
              <select v-model="deviceForm.auth_type">
                <option v-for="opt in authTypes" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <!-- Basic Auth fields -->
            <template v-if="deviceForm.auth_type === 'basic'">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Username</label>
                  <input v-model="deviceForm.username" type="text" />
                </div>
                <div class="form-row half">
                  <label>Password</label>
                  <input v-model="deviceForm.password" type="password" />
                </div>
              </div>
            </template>

            <!-- Bearer Token field -->
            <template v-if="deviceForm.auth_type === 'bearer'">
              <div class="form-row">
                <label>Bearer Token</label>
                <input v-model="deviceForm.bearer_token" type="password" />
              </div>
            </template>

            <!-- API Key fields -->
            <template v-if="deviceForm.auth_type === 'api_key'">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>API Key</label>
                  <input v-model="deviceForm.api_key" type="password" />
                </div>
                <div class="form-row half">
                  <label>Header Name</label>
                  <input v-model="deviceForm.api_key_header" type="text" placeholder="X-API-Key" />
                </div>
              </div>
            </template>
          </div>

          <div class="form-group">
            <h4>Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Poll Rate (ms)</label>
                <input v-model.number="deviceForm.poll_rate_ms" type="number" min="50" max="60000" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout_s" type="number" min="1" max="60" step="0.5" />
              </div>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.verify_ssl" />
                Verify SSL Certificate
              </label>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.enabled" />
                Enable source
              </label>
            </div>
          </div>

          <!-- Endpoints section -->
          <div class="form-group">
            <div class="endpoints-header">
              <h4>Endpoints (Channels)</h4>
              <button class="add-endpoint-btn" @click="openAddEndpoint">+ Add Endpoint</button>
            </div>

            <div v-if="deviceForm.endpoints.length === 0" class="no-endpoints">
              No endpoints configured. Click "Add Endpoint" to add API endpoints.
            </div>

            <div v-else class="endpoint-list-config">
              <div v-for="(ep, index) in deviceForm.endpoints" :key="index" class="endpoint-config-item">
                <div class="ep-info">
                  <span class="ep-name">{{ ep.name }}</span>
                  <span class="ep-address">{{ ep.address }}</span>
                  <span class="ep-badges">
                    <span class="badge">{{ ep.data_type }}</span>
                    <span v-if="ep.is_output" class="badge output">OUTPUT</span>
                  </span>
                </div>
                <button class="remove-ep-btn" @click="removeEndpointFromForm(index)">&times;</button>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showAddDeviceModal = false">Cancel</button>
          <button class="btn primary" @click="addDevice" :disabled="isLoading || !deviceForm.name || !deviceForm.base_url">
            {{ isLoading ? 'Adding...' : 'Add Source' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Device Modal (same as add but for editing) -->
    <div v-if="showEditDeviceModal" class="modal-overlay" @click.self="showEditDeviceModal = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h3>Edit REST API Source: {{ deviceForm.name }}</h3>
          <button class="close-btn" @click="showEditDeviceModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <!-- Same form content as Add modal -->
          <div class="form-group">
            <h4>Connection</h4>
            <div class="form-row">
              <label>Base URL</label>
              <input v-model="deviceForm.base_url" type="text" placeholder="http://192.168.1.100:8080" />
            </div>

            <div class="form-row">
              <label>Authentication</label>
              <select v-model="deviceForm.auth_type">
                <option v-for="opt in authTypes" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <template v-if="deviceForm.auth_type === 'basic'">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Username</label>
                  <input v-model="deviceForm.username" type="text" />
                </div>
                <div class="form-row half">
                  <label>Password</label>
                  <input v-model="deviceForm.password" type="password" />
                </div>
              </div>
            </template>

            <template v-if="deviceForm.auth_type === 'bearer'">
              <div class="form-row">
                <label>Bearer Token</label>
                <input v-model="deviceForm.bearer_token" type="password" />
              </div>
            </template>

            <template v-if="deviceForm.auth_type === 'api_key'">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>API Key</label>
                  <input v-model="deviceForm.api_key" type="password" />
                </div>
                <div class="form-row half">
                  <label>Header Name</label>
                  <input v-model="deviceForm.api_key_header" type="text" />
                </div>
              </div>
            </template>
          </div>

          <div class="form-group">
            <h4>Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Poll Rate (ms)</label>
                <input v-model.number="deviceForm.poll_rate_ms" type="number" min="50" max="60000" />
              </div>
              <div class="form-row half">
                <label>Timeout (sec)</label>
                <input v-model.number="deviceForm.timeout_s" type="number" min="1" max="60" step="0.5" />
              </div>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.verify_ssl" />
                Verify SSL Certificate
              </label>
            </div>
            <div class="form-row checkbox-row">
              <label>
                <input type="checkbox" v-model="deviceForm.enabled" />
                Enable source
              </label>
            </div>
          </div>

          <div class="form-group">
            <div class="endpoints-header">
              <h4>Endpoints (Channels)</h4>
              <button class="add-endpoint-btn" @click="openAddEndpoint">+ Add Endpoint</button>
            </div>

            <div v-if="deviceForm.endpoints.length === 0" class="no-endpoints">
              No endpoints configured.
            </div>

            <div v-else class="endpoint-list-config">
              <div v-for="(ep, index) in deviceForm.endpoints" :key="index" class="endpoint-config-item">
                <div class="ep-info">
                  <span class="ep-name">{{ ep.name }}</span>
                  <span class="ep-address">{{ ep.address }}</span>
                  <span class="ep-badges">
                    <span class="badge">{{ ep.data_type }}</span>
                    <span v-if="ep.is_output" class="badge output">OUTPUT</span>
                  </span>
                </div>
                <button class="remove-ep-btn" @click="removeEndpointFromForm(index)">&times;</button>
              </div>
            </div>
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

    <!-- Add Endpoint Modal -->
    <div v-if="showAddEndpointModal" class="modal-overlay" @click.self="showAddEndpointModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Add Endpoint</h3>
          <button class="close-btn" @click="showAddEndpointModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Channel Name</label>
            <input v-model="endpointForm.name" type="text" placeholder="e.g., Temperature_1" />
          </div>

          <div class="form-row">
            <label>Endpoint Path</label>
            <input v-model="endpointForm.address" type="text" placeholder="/api/v1/analog/0/value" />
          </div>

          <div class="form-row">
            <label>Response JSON Path (optional)</label>
            <input v-model="endpointForm.response_key" type="text" placeholder="data.value" />
            <span class="hint">Path to value in JSON response, e.g., "data.value" or "result[0].temp"</span>
          </div>

          <div class="form-row-group">
            <div class="form-row half">
              <label>Data Type</label>
              <select v-model="endpointForm.data_type">
                <option v-for="opt in dataTypes" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <div class="form-row half">
              <label>Unit</label>
              <input v-model="endpointForm.unit" type="text" placeholder="e.g., °C, PSI" />
            </div>
          </div>

          <div class="form-row-group">
            <div class="form-row half">
              <label>Scale</label>
              <input v-model.number="endpointForm.scale" type="number" step="0.001" />
            </div>
            <div class="form-row half">
              <label>Offset</label>
              <input v-model.number="endpointForm.offset" type="number" step="0.001" />
            </div>
          </div>

          <div class="form-row checkbox-row">
            <label>
              <input type="checkbox" v-model="endpointForm.is_output" />
              Writable (output channel)
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showAddEndpointModal = false">Cancel</button>
          <button class="btn primary" @click="addEndpointToForm" :disabled="!endpointForm.name || !endpointForm.address">
            Add Endpoint
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rest-api-config {
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

.add-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.8rem;
  background: #10b981;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.add-btn:hover {
  background: #059669;
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
  border-color: #10b981;
}

.device-card.selected {
  border-color: #10b981;
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
  background: #10b981;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
  color: white;
}

.info-latency {
  margin-left: auto;
  color: #666;
  font-size: 0.75rem;
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

.endpoints-section {
  margin-top: 1rem;
}

.endpoints-section h4 {
  margin: 0 0 0.5rem 0;
  font-size: 0.85rem;
  color: #888;
}

.endpoint-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.endpoint-item {
  display: flex;
  gap: 0.5rem;
  font-size: 0.8rem;
  padding: 0.25rem 0.5rem;
  background: rgba(0,0,0,0.2);
  border-radius: 4px;
}

.ep-name {
  font-weight: 600;
  min-width: 100px;
}

.ep-address {
  color: #888;
  flex: 1;
}

.ep-type {
  color: #666;
  font-size: 0.75rem;
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

.modal.modal-wide {
  max-width: 650px;
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
  border-color: #10b981;
}

.form-row .hint {
  display: block;
  font-size: 0.75rem;
  color: #666;
  margin-top: 0.25rem;
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

.endpoints-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.endpoints-header h4 {
  margin: 0;
}

.add-endpoint-btn {
  padding: 0.25rem 0.5rem;
  background: #374151;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.75rem;
}

.add-endpoint-btn:hover {
  background: #4b5563;
}

.no-endpoints {
  text-align: center;
  padding: 1rem;
  color: #666;
  font-size: 0.85rem;
}

.endpoint-list-config {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.endpoint-config-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  background: rgba(0,0,0,0.2);
  border-radius: 4px;
}

.endpoint-config-item .ep-info {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.endpoint-config-item .ep-name {
  font-weight: 600;
}

.endpoint-config-item .ep-address {
  color: #888;
  font-size: 0.85rem;
}

.ep-badges {
  display: flex;
  gap: 0.25rem;
}

.badge {
  padding: 0.1rem 0.3rem;
  background: #374151;
  border-radius: 3px;
  font-size: 0.7rem;
}

.badge.output {
  background: #b45309;
}

.remove-ep-btn {
  background: none;
  border: none;
  color: #ef4444;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0.25rem;
}

.remove-ep-btn:hover {
  color: #f87171;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn.primary {
  background: #10b981;
  color: white;
}

.btn.primary:hover {
  background: #059669;
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
