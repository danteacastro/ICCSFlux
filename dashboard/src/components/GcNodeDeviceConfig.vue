<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { GCNodeConfig } from '../types'

const mqtt = useMqtt()

// Props
const props = defineProps<{
  editMode: boolean
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
}>()

// ============================================================
// State
// ============================================================

const discoveredNodes = ref<GCNodeConfig[]>([])
const selectedNodeId = ref<string | null>(null)
const showModal = ref(false)
const modalMode = ref<'add' | 'edit'>('add')
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error'>('success')
const activeSourceTab = ref<'file' | 'modbus' | 'serial' | 'analysis'>('file')

// Form state
const nodeForm = reactive<GCNodeConfig>({
  node_id: '',
  node_name: '',
  gc_type: '',
  vm_ip: '',
  connection_mode: 'direct',
  source_type: 'file',
  // File watcher
  file_watch_dir: '',
  file_pattern: '*.csv',
  parse_template: 'generic',
  column_mapping: {},
  // Modbus
  modbus_ip: '192.168.1.100',
  modbus_port: 502,
  modbus_slave_id: 1,
  modbus_registers: [],
  // Serial
  serial_port: 'COM3',
  serial_baudrate: 9600,
  serial_protocol: 'line',
  // Analysis engine
  analysis_method: '',
  analysis_components: {},
})

// Column mapping editing
const newMappingKey = ref('')
const newMappingValue = ref('')

// Modbus register editing
const newRegister = reactive({
  name: '',
  address: 0,
  register_type: 'holding',
  data_type: 'float32',
  unit: '',
})

// Analysis component editing
const newComponentName = ref('')
const newComponent = reactive({
  rt_expected: 0,
  rt_tolerance: 0.1,
  response_factor: 1.0,
  unit: 'mol%',
})

// ============================================================
// Lifecycle
// ============================================================

onMounted(() => {
  subscribeToGcStatus()
})

// ============================================================
// MQTT Discovery
// ============================================================

function subscribeToGcStatus() {
  mqtt.subscribe('nisystem/nodes/gc-+/status/system', (message: any) => {
    if (!message || typeof message !== 'object') return

    const nodeId = message.node_id || ''
    if (!nodeId) return

    const existing = discoveredNodes.value.find(n => n.node_id === nodeId)
    if (existing) {
      existing.status = message.status || 'online'
      existing.last_seen = Date.now()
      existing.last_analysis = message.last_analysis || existing.last_analysis
      existing.analysis_count = message.analysis_count ?? existing.analysis_count
      existing.gc_type = message.gc_type || existing.gc_type
      existing.node_name = message.node_name || existing.node_name
    } else {
      discoveredNodes.value.push({
        node_id: nodeId,
        node_name: message.node_name || nodeId,
        gc_type: message.gc_type || 'Unknown',
        vm_ip: message.vm_ip || '',
        connection_mode: message.connection_mode || 'direct',
        source_type: message.source_type || 'file',
        status: message.status || 'online',
        last_seen: Date.now(),
        last_analysis: message.last_analysis || '',
        analysis_count: message.analysis_count ?? 0,
      })
    }
  })
}

// ============================================================
// Computed
// ============================================================

const sortedNodes = computed(() => {
  return [...discoveredNodes.value].sort((a, b) => {
    // Online nodes first
    if (a.status === 'online' && b.status !== 'online') return -1
    if (a.status !== 'online' && b.status === 'online') return 1
    return a.node_id.localeCompare(b.node_id)
  })
})

const modbusRegisters = computed(() => nodeForm.modbus_registers || [])

const analysisComponentEntries = computed(() => {
  return Object.entries(nodeForm.analysis_components || {}).map(([name, comp]) => ({
    name,
    ...comp,
  }))
})

const columnMappingEntries = computed(() => {
  return Object.entries(nodeForm.column_mapping || {})
})

// ============================================================
// Modal Actions
// ============================================================

function openAddNode() {
  modalMode.value = 'add'
  resetForm()
  showModal.value = true
}

function openEditNode(node: GCNodeConfig) {
  modalMode.value = 'edit'
  Object.assign(nodeForm, JSON.parse(JSON.stringify(node)))
  activeSourceTab.value = node.source_type || 'file'
  showModal.value = true
}

function resetForm() {
  nodeForm.node_id = ''
  nodeForm.node_name = ''
  nodeForm.gc_type = ''
  nodeForm.vm_ip = ''
  nodeForm.connection_mode = 'direct'
  nodeForm.source_type = 'file'
  nodeForm.file_watch_dir = ''
  nodeForm.file_pattern = '*.csv'
  nodeForm.parse_template = 'generic'
  nodeForm.column_mapping = {}
  nodeForm.modbus_ip = '192.168.1.100'
  nodeForm.modbus_port = 502
  nodeForm.modbus_slave_id = 1
  nodeForm.modbus_registers = []
  nodeForm.serial_port = 'COM3'
  nodeForm.serial_baudrate = 9600
  nodeForm.serial_protocol = 'line'
  nodeForm.analysis_method = ''
  nodeForm.analysis_components = {}
  activeSourceTab.value = 'file'
}

function saveNode() {
  if (!nodeForm.node_id) {
    showFeedback('error', 'Node ID is required')
    return
  }
  if (!nodeForm.node_name) {
    showFeedback('error', 'Node Name is required')
    return
  }

  nodeForm.source_type = activeSourceTab.value

  if (modalMode.value === 'add') {
    if (discoveredNodes.value.some(n => n.node_id === nodeForm.node_id)) {
      showFeedback('error', 'A node with this ID already exists')
      return
    }
    discoveredNodes.value.push({
      ...JSON.parse(JSON.stringify(nodeForm)),
      status: 'unknown',
      last_seen: 0,
      analysis_count: 0,
    })
    showFeedback('success', `GC node "${nodeForm.node_name}" added`)
  } else {
    const idx = discoveredNodes.value.findIndex(n => n.node_id === nodeForm.node_id)
    if (idx >= 0) {
      const prev = discoveredNodes.value[idx]!
      discoveredNodes.value[idx] = {
        ...JSON.parse(JSON.stringify(nodeForm)),
        status: prev.status ?? 'unknown',
        last_seen: prev.last_seen ?? 0,
        analysis_count: prev.analysis_count ?? 0,
        last_analysis: prev.last_analysis ?? '',
      }
      showFeedback('success', `GC node "${nodeForm.node_name}" updated`)
    }
  }

  emit('dirty')
  showModal.value = false
}

function deleteNode(nodeId: string) {
  const node = discoveredNodes.value.find(n => n.node_id === nodeId)
  if (!node) return
  if (!confirm(`Delete GC node "${node.node_name}"?`)) return

  discoveredNodes.value = discoveredNodes.value.filter(n => n.node_id !== nodeId)
  if (selectedNodeId.value === nodeId) {
    selectedNodeId.value = null
  }
  emit('dirty')
  showFeedback('success', `GC node "${node.node_name}" deleted`)
}

// ============================================================
// Push Config
// ============================================================

async function pushConfig(node: GCNodeConfig) {
  isLoading.value = true
  showFeedback('success', `Pushing config to ${node.node_id}...`)

  try {
    mqtt.sendNodeCommand('config/push', {
      node_id: node.node_id,
      node_name: node.node_name,
      gc_type: node.gc_type,
      vm_ip: node.vm_ip,
      connection_mode: node.connection_mode,
      source_type: node.source_type,
      file_watch_dir: node.file_watch_dir,
      file_pattern: node.file_pattern,
      parse_template: node.parse_template,
      column_mapping: node.column_mapping,
      modbus_ip: node.modbus_ip,
      modbus_port: node.modbus_port,
      modbus_slave_id: node.modbus_slave_id,
      modbus_registers: node.modbus_registers,
      serial_port: node.serial_port,
      serial_baudrate: node.serial_baudrate,
      serial_protocol: node.serial_protocol,
      analysis_method: node.analysis_method,
      analysis_components: node.analysis_components,
    }, node.node_id)
    showFeedback('success', `Config pushed to ${node.node_id}`)
  } catch (e: any) {
    showFeedback('error', e.message || 'Failed to push config')
  } finally {
    isLoading.value = false
  }
}

// ============================================================
// Modbus Register helpers
// ============================================================

function addRegister() {
  if (!newRegister.name) return
  if (!nodeForm.modbus_registers) nodeForm.modbus_registers = []
  nodeForm.modbus_registers.push({ ...newRegister })
  newRegister.name = ''
  newRegister.address = 0
  newRegister.register_type = 'holding'
  newRegister.data_type = 'float32'
  newRegister.unit = ''
}

function removeRegister(index: number) {
  nodeForm.modbus_registers?.splice(index, 1)
}

// ============================================================
// Column Mapping helpers
// ============================================================

function addMapping() {
  if (!newMappingKey.value || !newMappingValue.value) return
  if (!nodeForm.column_mapping) nodeForm.column_mapping = {}
  nodeForm.column_mapping[newMappingKey.value] = newMappingValue.value
  newMappingKey.value = ''
  newMappingValue.value = ''
}

function removeMapping(key: string) {
  if (nodeForm.column_mapping) {
    delete nodeForm.column_mapping[key]
    // Force reactivity
    nodeForm.column_mapping = { ...nodeForm.column_mapping }
  }
}

// ============================================================
// Analysis Component helpers
// ============================================================

function addComponent() {
  if (!newComponentName.value) return
  if (!nodeForm.analysis_components) nodeForm.analysis_components = {}
  nodeForm.analysis_components[newComponentName.value] = { ...newComponent }
  newComponentName.value = ''
  newComponent.rt_expected = 0
  newComponent.rt_tolerance = 0.1
  newComponent.response_factor = 1.0
  newComponent.unit = 'mol%'
}

function removeComponent(name: string) {
  if (nodeForm.analysis_components) {
    delete nodeForm.analysis_components[name]
    nodeForm.analysis_components = { ...nodeForm.analysis_components }
  }
}

// ============================================================
// Feedback
// ============================================================

function showFeedback(type: 'success' | 'error', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
  setTimeout(() => {
    feedbackMessage.value = ''
  }, 3000)
}

function formatLastSeen(ts: number | undefined): string {
  if (!ts) return 'Never'
  const diff = Date.now() - ts
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  return new Date(ts).toLocaleTimeString()
}
</script>

<template>
  <div class="gc-config">
    <!-- Header -->
    <div class="section-header">
      <h3>
        <span class="icon">\u2697</span>
        GC Analyzer Nodes
      </h3>
      <div class="header-actions">
        <button
          v-if="editMode"
          class="add-btn"
          @click="openAddNode"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add GC Node
        </button>
      </div>
    </div>

    <!-- Feedback message -->
    <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
      {{ feedbackMessage }}
    </div>

    <!-- Empty state -->
    <div v-if="sortedNodes.length === 0" class="empty-state">
      <p>No GC analyzer nodes discovered</p>
      <p class="hint">GC nodes publish to nisystem/nodes/gc-*/status/system. Click "Add GC Node" to manually configure one.</p>
    </div>

    <!-- Node list -->
    <div v-else class="device-list">
      <div
        v-for="node in sortedNodes"
        :key="node.node_id"
        class="device-card"
        :class="{ selected: selectedNodeId === node.node_id }"
        @click="selectedNodeId = selectedNodeId === node.node_id ? null : node.node_id"
      >
        <div class="device-header">
          <span
            class="status-dot"
            :class="node.status"
            :title="node.status"
          ></span>
          <span class="device-name">{{ node.node_name || node.node_id }}</span>
          <span class="info-tag">{{ node.gc_type || 'GC' }}</span>
        </div>

        <div class="device-info">
          <span class="info-value">ID: {{ node.node_id }}</span>
          <span v-if="node.connection_mode === 'vm'" class="info-value">VM: {{ node.vm_ip }}</span>
          <span class="info-value">Source: {{ node.source_type }}</span>
        </div>

        <div class="device-meta">
          <span class="meta-item" v-if="node.last_analysis">Last analysis: {{ node.last_analysis }}</span>
          <span class="meta-item" v-if="node.analysis_count != null">Runs: {{ node.analysis_count }}</span>
          <span class="meta-item">Seen: {{ formatLastSeen(node.last_seen) }}</span>
        </div>

        <!-- Expanded details when selected -->
        <div v-if="selectedNodeId === node.node_id" class="device-details">
          <div class="device-actions">
            <button
              class="action-btn"
              @click.stop="pushConfig(node)"
              :disabled="isLoading"
              title="Push configuration to this GC node"
            >
              Push Config
            </button>
            <button
              v-if="editMode"
              class="action-btn"
              @click.stop="openEditNode(node)"
            >
              Edit
            </button>
            <button
              v-if="editMode"
              class="action-btn danger"
              @click.stop="deleteNode(node.node_id)"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add/Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h3>{{ modalMode === 'add' ? 'Add GC Node' : `Edit GC Node: ${nodeForm.node_name}` }}</h3>
          <button class="close-btn" @click="showModal = false">&times;</button>
        </div>

        <div class="modal-body">
          <!-- Basic Settings -->
          <div class="form-group">
            <h4>Basic Settings</h4>
            <div class="form-row-group">
              <div class="form-row half">
                <label>Node ID</label>
                <input
                  v-model="nodeForm.node_id"
                  type="text"
                  placeholder="gc-001"
                  :disabled="modalMode === 'edit'"
                />
              </div>
              <div class="form-row half">
                <label>Node Name</label>
                <input v-model="nodeForm.node_name" type="text" placeholder="GC Analyzer 1" />
              </div>
            </div>
            <div class="form-row-group">
              <div class="form-row half">
                <label>GC Type</label>
                <input v-model="nodeForm.gc_type" type="text" placeholder="e.g., Agilent 7890, ABB NGC" />
              </div>
              <div class="form-row half">
                <label>Connection Mode</label>
                <select v-model="nodeForm.connection_mode">
                  <option value="direct">Direct</option>
                  <option value="vm">VM (Virtual Machine)</option>
                </select>
              </div>
            </div>
            <div v-if="nodeForm.connection_mode === 'vm'" class="form-row">
              <label>VM IP Address</label>
              <input v-model="nodeForm.vm_ip" type="text" placeholder="192.168.1.50" />
            </div>
          </div>

          <!-- Source Type Tabs -->
          <div class="form-group">
            <h4>Data Source</h4>
            <div class="source-tabs">
              <button
                v-for="tab in (['file', 'modbus', 'serial', 'analysis'] as const)"
                :key="tab"
                class="source-tab"
                :class="{ active: activeSourceTab === tab }"
                @click="activeSourceTab = tab"
              >
                {{ tab === 'file' ? 'File' : tab === 'modbus' ? 'Modbus' : tab === 'serial' ? 'Serial' : 'Analysis' }}
              </button>
            </div>

            <!-- File Source -->
            <div v-if="activeSourceTab === 'file'" class="source-panel">
              <div class="form-row">
                <label>Watch Directory</label>
                <input v-model="nodeForm.file_watch_dir" type="text" placeholder="C:\GCData\results" />
              </div>
              <div class="form-row">
                <label>File Pattern</label>
                <input v-model="nodeForm.file_pattern" type="text" placeholder="*.csv" />
              </div>
              <div class="form-row">
                <label>Parse Template</label>
                <select v-model="nodeForm.parse_template">
                  <option value="generic">Generic CSV</option>
                  <option value="agilent">Agilent ChemStation</option>
                  <option value="abb_ngc">ABB NGC</option>
                </select>
              </div>

              <!-- Column Mapping -->
              <div class="sub-section">
                <label class="sub-label">Column Mapping</label>
                <table v-if="columnMappingEntries.length > 0" class="mini-table">
                  <thead>
                    <tr>
                      <th>File Column</th>
                      <th>Tag Name</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="[key, val] in columnMappingEntries" :key="key">
                      <td>{{ key }}</td>
                      <td>{{ val }}</td>
                      <td>
                        <button class="remove-btn" @click="removeMapping(key)" title="Remove">&times;</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div class="add-row">
                  <input v-model="newMappingKey" type="text" placeholder="Column name" class="add-input" />
                  <input v-model="newMappingValue" type="text" placeholder="Tag name" class="add-input" />
                  <button class="add-row-btn" @click="addMapping" :disabled="!newMappingKey || !newMappingValue">+</button>
                </div>
              </div>
            </div>

            <!-- Modbus Source -->
            <div v-if="activeSourceTab === 'modbus'" class="source-panel">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>IP Address</label>
                  <input v-model="nodeForm.modbus_ip" type="text" placeholder="192.168.1.100" />
                </div>
                <div class="form-row half">
                  <label>Port</label>
                  <input v-model.number="nodeForm.modbus_port" type="number" min="1" max="65535" />
                </div>
              </div>
              <div class="form-row">
                <label>Slave ID</label>
                <input v-model.number="nodeForm.modbus_slave_id" type="number" min="1" max="247" />
              </div>

              <!-- Register Table -->
              <div class="sub-section">
                <label class="sub-label">Registers</label>
                <table v-if="modbusRegisters.length > 0" class="mini-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Address</th>
                      <th>Type</th>
                      <th>Data</th>
                      <th>Unit</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(reg, idx) in modbusRegisters" :key="idx">
                      <td>{{ reg.name }}</td>
                      <td>{{ reg.address }}</td>
                      <td>{{ reg.register_type }}</td>
                      <td>{{ reg.data_type }}</td>
                      <td>{{ reg.unit }}</td>
                      <td>
                        <button class="remove-btn" @click="removeRegister(idx)" title="Remove">&times;</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div class="add-row">
                  <input v-model="newRegister.name" type="text" placeholder="Name" class="add-input" />
                  <input v-model.number="newRegister.address" type="number" placeholder="Addr" class="add-input narrow" />
                  <select v-model="newRegister.register_type" class="add-input narrow">
                    <option value="holding">Holding</option>
                    <option value="input">Input</option>
                  </select>
                  <select v-model="newRegister.data_type" class="add-input narrow">
                    <option value="int16">int16</option>
                    <option value="uint16">uint16</option>
                    <option value="int32">int32</option>
                    <option value="uint32">uint32</option>
                    <option value="float32">float32</option>
                    <option value="float64">float64</option>
                  </select>
                  <input v-model="newRegister.unit" type="text" placeholder="Unit" class="add-input narrow" />
                  <button class="add-row-btn" @click="addRegister" :disabled="!newRegister.name">+</button>
                </div>
              </div>
            </div>

            <!-- Serial Source -->
            <div v-if="activeSourceTab === 'serial'" class="source-panel">
              <div class="form-row-group">
                <div class="form-row half">
                  <label>Serial Port</label>
                  <input v-model="nodeForm.serial_port" type="text" placeholder="COM3" />
                </div>
                <div class="form-row half">
                  <label>Baud Rate</label>
                  <select v-model.number="nodeForm.serial_baudrate">
                    <option :value="4800">4800</option>
                    <option :value="9600">9600</option>
                    <option :value="19200">19200</option>
                    <option :value="38400">38400</option>
                    <option :value="57600">57600</option>
                    <option :value="115200">115200</option>
                  </select>
                </div>
              </div>
              <div class="form-row">
                <label>Protocol</label>
                <select v-model="nodeForm.serial_protocol">
                  <option value="line">Line-based (newline delimited)</option>
                  <option value="stx_etx">STX/ETX framing</option>
                  <option value="custom">Custom frame markers</option>
                </select>
              </div>
            </div>

            <!-- Analysis Engine Source -->
            <div v-if="activeSourceTab === 'analysis'" class="source-panel">
              <div class="form-row">
                <label>Analysis Method Name</label>
                <input v-model="nodeForm.analysis_method" type="text" placeholder="e.g., Natural_Gas_C6+" />
              </div>

              <!-- Component Table -->
              <div class="sub-section">
                <label class="sub-label">Components</label>
                <table v-if="analysisComponentEntries.length > 0" class="mini-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Expected RT</th>
                      <th>Tolerance</th>
                      <th>Resp. Factor</th>
                      <th>Unit</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="comp in analysisComponentEntries" :key="comp.name">
                      <td>{{ comp.name }}</td>
                      <td>{{ comp.rt_expected }}</td>
                      <td>{{ comp.rt_tolerance }}</td>
                      <td>{{ comp.response_factor }}</td>
                      <td>{{ comp.unit }}</td>
                      <td>
                        <button class="remove-btn" @click="removeComponent(comp.name)" title="Remove">&times;</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div class="add-row">
                  <input v-model="newComponentName" type="text" placeholder="Component" class="add-input" />
                  <input v-model.number="newComponent.rt_expected" type="number" step="0.01" placeholder="RT" class="add-input narrow" />
                  <input v-model.number="newComponent.rt_tolerance" type="number" step="0.01" placeholder="Tol" class="add-input narrow" />
                  <input v-model.number="newComponent.response_factor" type="number" step="0.01" placeholder="RF" class="add-input narrow" />
                  <select v-model="newComponent.unit" class="add-input narrow">
                    <option value="mol%">mol%</option>
                    <option value="ppm">ppm</option>
                    <option value="vol%">vol%</option>
                    <option value="wt%">wt%</option>
                  </select>
                  <button class="add-row-btn" @click="addComponent" :disabled="!newComponentName">+</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn secondary" @click="showModal = false">Cancel</button>
          <button
            class="btn primary"
            @click="saveNode"
            :disabled="isLoading || !nodeForm.node_id || !nodeForm.node_name"
          >
            {{ modalMode === 'add' ? 'Add Node' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gc-config {
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
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.add-btn:hover {
  background: var(--color-accent-dark);
}

.feedback {
  padding: 0.5rem 1rem;
  border-radius: 4px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.feedback.success {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.feedback.error {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary);
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

.device-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.online {
  background: #22c55e;
  box-shadow: 0 0 4px #22c55e;
}

.status-dot.offline {
  background: #6b7280;
}

.status-dot.unknown {
  background: #f59e0b;
}

.device-name {
  font-weight: 600;
  flex: 1;
}

.info-tag {
  background: var(--btn-secondary-bg);
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.75rem;
  font-weight: 600;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.4rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.device-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-tertiary, var(--text-secondary));
}

.meta-item {
  opacity: 0.8;
}

.device-details {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.device-actions {
  display: flex;
  gap: 0.5rem;
}

.action-btn {
  padding: 0.4rem 0.8rem;
  background: var(--btn-secondary-bg);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

.action-btn:hover {
  background: var(--btn-secondary-hover);
}

.action-btn.danger {
  background: var(--color-error-bg);
}

.action-btn.danger:hover {
  background: #991b1b;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal */
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

.modal.modal-wide {
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
  color: var(--text-secondary);
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

/* Form styles */
.form-group {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--bg-elevated);
  border-radius: 6px;
}

.form-group h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.form-row {
  margin-bottom: 0.75rem;
}

.form-row label {
  display: block;
  font-size: 0.85rem;
  color: var(--text-secondary);
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

.form-row input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-row-group {
  display: flex;
  gap: 1rem;
}

.form-row.half {
  flex: 1;
}

/* Source tabs */
.source-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 0.75rem;
  background: var(--bg-primary);
  border-radius: 4px;
  padding: 2px;
}

.source-tab {
  flex: 1;
  padding: 0.4rem 0.5rem;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 3px;
  font-size: 0.8rem;
  font-weight: 500;
  transition: all 0.15s;
}

.source-tab:hover {
  color: var(--text-bright, white);
}

.source-tab.active {
  background: var(--color-accent);
  color: white;
}

.source-panel {
  padding-top: 0.5rem;
}

/* Sub sections (tables) */
.sub-section {
  margin-top: 0.75rem;
}

.sub-label {
  display: block;
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  font-weight: 500;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin-bottom: 0.5rem;
}

.mini-table th {
  text-align: left;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-weight: 500;
}

.mini-table td {
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-bright, white);
}

.mini-table tr:last-child td {
  border-bottom: none;
}

.remove-btn {
  background: none;
  border: none;
  color: #ef4444;
  cursor: pointer;
  font-size: 1rem;
  padding: 0 0.25rem;
  line-height: 1;
}

.remove-btn:hover {
  color: #f87171;
}

.add-row {
  display: flex;
  gap: 0.25rem;
  align-items: center;
  margin-top: 0.25rem;
}

.add-input {
  flex: 1;
  padding: 0.35rem 0.5rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: white;
  font-size: 0.8rem;
}

.add-input.narrow {
  flex: 0.6;
  min-width: 0;
}

.add-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.add-row-btn {
  padding: 0.35rem 0.6rem;
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: bold;
  flex-shrink: 0;
}

.add-row-btn:hover {
  background: var(--color-accent-dark);
}

.add-row-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Buttons */
.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn.primary {
  background: var(--color-accent);
  color: white;
}

.btn.primary:hover {
  background: var(--color-accent-dark);
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.secondary {
  background: var(--btn-secondary-bg);
  color: white;
}

.btn.secondary:hover {
  background: var(--btn-secondary-hover);
}
</style>
