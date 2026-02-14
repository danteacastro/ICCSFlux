<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { NodeInfo } from '../types'

const mqtt = useMqtt()

const nodes = computed(() => Array.from(mqtt.knownNodes.value.values()))
const expandedNodeId = ref<string | null>(null)
const showSetupPanel = ref(false)
const setupMode = ref<'cdaq' | 'crio' | 'opto22' | 'gc'>('cdaq')
const showBridgeSetup = ref(false)
const peerIp = ref('192.168.1.2')
const bridgeConfigOutput = ref('')

// Create Instance form (cDAQ only)
const newNodeId = ref('')
const newNodeName = ref('')
const newSimulationMode = ref(true)
const createStatus = ref<'idle' | 'creating' | 'success' | 'error'>('idle')
const createMessage = ref('')
const createLaunchCmd = ref('')
let createCleanup: (() => void) | null = null

// Bridge status (from MQTT subscription)
const bridgeStatus = ref<'unknown' | 'connected' | 'disconnected'>('unknown')
let bridgeCleanup: (() => void) | null = null

onMounted(() => {
  // Subscribe to bridge status topic
  bridgeCleanup = mqtt.subscribe('nisystem/bridge/status', (payload: any) => {
    if (payload?.status === '1' || payload?.connected) {
      bridgeStatus.value = 'connected'
    } else {
      bridgeStatus.value = 'disconnected'
    }
  }) as any
})

onUnmounted(() => {
  if (bridgeCleanup && typeof bridgeCleanup === 'function') bridgeCleanup()
})

function toggleExpand(nodeId: string) {
  expandedNodeId.value = expandedNodeId.value === nodeId ? null : nodeId
}

function getNodeTypeLabel(node: NodeInfo): string {
  switch (node.nodeType) {
    case 'crio': return 'cRIO'
    case 'opto22': return 'Opto22'
    case 'gc': return 'GC'
    default: return 'cDAQ'
  }
}

function getModeLabel(node: NodeInfo): string {
  if (node.nodeType === 'crio') return 'cRIO is PLC'
  if (node.nodeType === 'opto22') return 'Opto22 is PLC'
  if (node.nodeType === 'gc') return 'Analysis'
  if (node.projectMode === 'crio') return 'HMI for cRIO'
  if (node.projectMode === 'opto22') return 'HMI for Opto22'
  return 'PC is PLC'
}

function getStateLabel(node: NodeInfo): string {
  if (node.recording) return 'Recording'
  if (node.acquiring) return 'Acquiring'
  return 'Idle'
}

function getTimeSince(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.floor(minutes / 60)}h ago`
}

function createInstance() {
  if (!newNodeId.value.trim()) return

  createStatus.value = 'creating'
  createMessage.value = 'Creating config...'
  createLaunchCmd.value = ''

  // Subscribe for response
  if (createCleanup) createCleanup()
  createCleanup = mqtt.subscribe('nisystem/nodes/+/system/create-instance/response', (payload: any) => {
    if (payload.success) {
      createStatus.value = 'success'
      createMessage.value = `Config created: ${payload.config_path}`
      createLaunchCmd.value = payload.launch_command
    } else {
      createStatus.value = 'error'
      createMessage.value = payload.error || 'Failed to create instance'
    }
    if (createCleanup) { createCleanup(); createCleanup = null }
  }) as any

  mqtt.sendNodeCommand('system/create-instance', {
    node_id: newNodeId.value.trim(),
    node_name: newNodeName.value.trim() || newNodeId.value.trim(),
    simulation_mode: newSimulationMode.value,
  })

  // Timeout fallback
  setTimeout(() => {
    if (createStatus.value === 'creating') {
      createStatus.value = 'error'
      createMessage.value = 'Timeout — no response from backend'
      if (createCleanup) { createCleanup(); createCleanup = null }
    }
  }, 5000)
}

function getSetupInstructions(): { title: string; steps: string[] } {
  switch (setupMode.value) {
    case 'cdaq':
      return {
        title: 'Add cDAQ Node',
        steps: [
          'Install ICCSFlux on the new PC',
          'Edit config/system.ini: set project_mode=cdaq, unique node_id (e.g. node-002), mqtt_broker=<this-PC-IP>',
          'Connect cDAQ chassis to the new PC via USB',
          'Run start.bat — the node will auto-register here',
        ]
      }
    case 'crio':
      return {
        title: 'Add cRIO Node',
        steps: [
          'Connect cRIO to the plant network (192.168.1.x)',
          'On this PC, run: deploy_crio_v2.bat <crio-ip> <broker-ip>',
          'The deploy script installs the cRIO node software and configures MQTT',
          'cRIO will auto-register as crio-XXX once connected',
        ]
      }
    case 'opto22':
      return {
        title: 'Add Opto22 Node',
        steps: [
          'Connect Opto22 groov EPIC/RIO to the plant network',
          'In groov Manage: configure MQTT publish with broker IP and credentials',
          'Deploy opto22_node to the EPIC: scp + configure config.json with node_id and broker',
          'Node will auto-register as opto22-XXX once connected',
        ]
      }
    case 'gc':
      return {
        title: 'Add GC Node',
        steps: [
          'Install gc_node on the PC connected to the GC instrument',
          'Configure gc_config.json: set gc_type, connection settings, node_id (e.g. gc-001)',
          'Set mqtt_broker to this PC\'s IP address',
          'Start gc_node — it will auto-register as gc-XXX',
        ]
      }
  }
}

function generateBridgeConfig() {
  // Generate the bridge config snippet for the peer PC
  bridgeConfigOutput.value =
    `# Peer bridge config — paste into the OTHER PC's mosquitto.conf\n` +
    `# Then restart Mosquitto on that PC.\n` +
    `\n` +
    `connection peer-bridge\n` +
    `address ${peerIp.value}:8883\n` +
    `topic # both 2\n` +
    `bridge_cafile config/tls/ca.crt\n` +
    `bridge_certfile config/tls/server.crt\n` +
    `bridge_keyfile config/tls/server.key\n` +
    `remote_username backend\n` +
    `remote_password <COPY_FROM_config/mqtt_credentials.json>\n` +
    `cleansession true\n` +
    `start_type automatic\n` +
    `restart_timeout 5\n` +
    `notifications true\n` +
    `notification_topic nisystem/bridge/status\n`
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
}

// Refresh node list display periodically
const refreshKey = ref(0)
let refreshInterval: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  refreshInterval = setInterval(() => { refreshKey.value++ }, 5000)
})
onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="node-manager" :key="refreshKey">
    <div class="panel-header">
      <h3>Nodes</h3>
      <div class="header-actions">
        <button class="btn-secondary" @click="showBridgeSetup = !showBridgeSetup">
          {{ showBridgeSetup ? 'Hide Bridge Setup' : 'Setup Peer Bridge' }}
        </button>
        <button class="btn-primary" @click="showSetupPanel = !showSetupPanel">
          {{ showSetupPanel ? 'Cancel' : '+ Setup New Node' }}
        </button>
      </div>
    </div>

    <!-- Bridge Setup Panel -->
    <div v-if="showBridgeSetup" class="setup-panel bridge-panel">
      <h4>Dual-PC Redundancy (Mosquitto Bridge)</h4>
      <p class="setup-desc">
        Both PCs run full ICCSFlux instances. The bridge syncs all MQTT topics bidirectionally.
        Both PCs see all nodes and record simultaneously. Only one side needs to initiate.
      </p>

      <div class="bridge-status-row">
        <span class="bridge-label">Bridge Status:</span>
        <span :class="['bridge-status', bridgeStatus]">
          {{ bridgeStatus === 'connected' ? 'Connected' : bridgeStatus === 'disconnected' ? 'Disconnected' : 'Not configured' }}
        </span>
      </div>

      <div class="field-row">
        <label>Peer PC Plant LAN IP</label>
        <input v-model="peerIp" type="text" placeholder="192.168.1.2" spellcheck="false" />
        <button class="btn-secondary" @click="generateBridgeConfig">Generate Config</button>
      </div>

      <div v-if="bridgeConfigOutput" class="config-output">
        <div class="config-header">
          <span>Paste this into the OTHER PC's config/mosquitto.conf:</span>
          <button class="btn-copy" @click="copyToClipboard(bridgeConfigOutput)">Copy</button>
        </div>
        <pre>{{ bridgeConfigOutput }}</pre>
        <p class="config-note">
          Replace &lt;COPY_FROM_config/mqtt_credentials.json&gt; with the 'backend' password
          from this PC's config/mqtt_credentials.json. Then restart Mosquitto on the peer PC.
        </p>
      </div>
    </div>

    <!-- New Node Setup Panel -->
    <div v-if="showSetupPanel" class="setup-panel">
      <div class="setup-mode-selector">
        <button
          v-for="mode in (['cdaq', 'crio', 'opto22', 'gc'] as const)"
          :key="mode"
          :class="['mode-btn', { active: setupMode === mode }]"
          @click="setupMode = mode"
        >
          {{ mode === 'cdaq' ? 'cDAQ' : mode === 'crio' ? 'cRIO' : mode === 'opto22' ? 'Opto22' : 'GC' }}
        </button>
      </div>

      <!-- cDAQ: Create Instance form -->
      <div v-if="setupMode === 'cdaq'" class="create-instance-form">
        <h4>Create cDAQ Instance</h4>
        <p class="setup-desc">
          Creates a config file for a new DAQ service instance on this PC.
          Each instance runs independently with its own channels, safety, and recording.
        </p>
        <div class="form-fields">
          <div class="field-row">
            <label>Node ID</label>
            <input v-model="newNodeId" type="text" placeholder="node-002" spellcheck="false" />
          </div>
          <div class="field-row">
            <label>Node Name</label>
            <input v-model="newNodeName" type="text" placeholder="Lab B Sensors" spellcheck="false" />
          </div>
          <div class="field-row">
            <label>Simulation</label>
            <label class="toggle-label">
              <input v-model="newSimulationMode" type="checkbox" />
              <span>{{ newSimulationMode ? 'On' : 'Off' }}</span>
            </label>
          </div>
        </div>
        <div class="form-actions">
          <button
            class="btn-primary"
            @click="createInstance"
            :disabled="!newNodeId.trim() || createStatus === 'creating'"
          >
            {{ createStatus === 'creating' ? 'Creating...' : 'Create Instance' }}
          </button>
        </div>
        <div v-if="createMessage" class="create-result" :class="createStatus">
          {{ createMessage }}
        </div>
        <div v-if="createLaunchCmd" class="launch-command">
          <div class="config-header">
            <span>Launch with:</span>
            <button class="btn-copy" @click="copyToClipboard(createLaunchCmd)">Copy</button>
          </div>
          <pre>{{ createLaunchCmd }}</pre>
        </div>
      </div>

      <!-- Other modes: step-by-step instructions -->
      <div v-else class="setup-instructions">
        <h4>{{ getSetupInstructions().title }}</h4>
        <ol>
          <li v-for="(step, i) in getSetupInstructions().steps" :key="i">{{ step }}</li>
        </ol>
      </div>
    </div>

    <!-- Node Table -->
    <div v-if="nodes.length === 0" class="empty-state">
      <div class="empty-icon">🖥️</div>
      <p>No nodes detected</p>
      <p class="empty-hint">Start a DAQ service, cRIO, Opto22, or GC node to see it here. Nodes auto-register via MQTT.</p>
    </div>

    <table v-else class="data-table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Node ID</th>
          <th>Name</th>
          <th>Type</th>
          <th>Mode</th>
          <th>State</th>
          <th>Channels</th>
          <th>Last Seen</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="node in nodes" :key="node.nodeId">
          <tr
            class="node-row"
            :class="{ expanded: expandedNodeId === node.nodeId }"
            @click="toggleExpand(node.nodeId)"
          >
            <td>
              <span :class="['status-dot', node.status]"></span>
            </td>
            <td class="mono">{{ node.nodeId }}</td>
            <td>{{ node.nodeName || '-' }}</td>
            <td>
              <span :class="['type-badge', 'type-' + (node.nodeType || 'daq')]">
                {{ getNodeTypeLabel(node) }}
              </span>
            </td>
            <td>{{ getModeLabel(node) }}</td>
            <td>
              <span :class="['state-badge', getStateLabel(node).toLowerCase()]">
                {{ getStateLabel(node) }}
              </span>
            </td>
            <td>{{ node.channelCount ?? '-' }}</td>
            <td>{{ getTimeSince(node.lastSeen) }}</td>
          </tr>

          <!-- Expanded Detail Row -->
          <tr v-if="expandedNodeId === node.nodeId" class="detail-row">
            <td colspan="8">
              <div class="node-detail">
                <div class="detail-grid">
                  <div class="detail-item">
                    <span class="detail-label">Node ID</span>
                    <span class="detail-value mono">{{ node.nodeId }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">Type</span>
                    <span class="detail-value">{{ getNodeTypeLabel(node) }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">Mode</span>
                    <span class="detail-value">{{ getModeLabel(node) }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">Status</span>
                    <span :class="['detail-value', 'status-text-' + node.status]">{{ node.status }}</span>
                  </div>
                  <div v-if="node.channelCount != null" class="detail-item">
                    <span class="detail-label">Channels</span>
                    <span class="detail-value">{{ node.channelCount }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">Simulation</span>
                    <span class="detail-value">{{ node.simulationMode ? 'Yes' : 'No' }}</span>
                  </div>
                  <div v-if="node.safetyState" class="detail-item">
                    <span class="detail-label">Safety State</span>
                    <span :class="['detail-value', 'safety-' + node.safetyState]">{{ node.safetyState }}</span>
                  </div>
                  <div v-if="node.configSynced === false" class="detail-item">
                    <span class="detail-label">Config Sync</span>
                    <span class="detail-value sync-warning">Out of sync</span>
                  </div>
                </div>

                <!-- Mode-specific details -->
                <div v-if="node.nodeType === 'crio' || node.nodeType === 'opto22'" class="detail-note">
                  {{ node.nodeType === 'crio' ? 'cRIO' : 'Opto22' }} runs safety independently — survives PC disconnection.
                </div>
                <div v-if="node.nodeType === 'daq' && (node.projectMode === 'cdaq' || !node.projectMode)" class="detail-note">
                  PC is PLC — reads hardware directly, runs safety and scripts locally.
                </div>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.node-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-primary,
.btn-secondary {
  padding: 6px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
}

.btn-primary {
  background: var(--accent-primary);
  color: #fff;
  border-color: var(--accent-primary);
}

.btn-primary:hover { filter: brightness(1.1); }

.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-primary);
}

.btn-secondary:hover { background: var(--bg-hover); }

/* Setup panels */
.setup-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 6px;
  padding: 16px;
}

.setup-panel h4 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.setup-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 12px;
  line-height: 1.5;
}

.setup-mode-selector {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.mode-btn {
  padding: 5px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg-primary);
  color: var(--text-secondary);
  border: 1px solid var(--border-primary);
}

.mode-btn.active {
  background: var(--accent-primary);
  color: #fff;
  border-color: var(--accent-primary);
}

.setup-instructions ol {
  margin: 8px 0 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.8;
}

/* Bridge setup */
.bridge-panel {
  border-color: var(--accent-primary);
}

.bridge-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
}

.bridge-label {
  color: var(--text-secondary);
}

.bridge-status {
  font-weight: 600;
}

.bridge-status.connected { color: #22c55e; }
.bridge-status.disconnected { color: #ef4444; }
.bridge-status.unknown { color: var(--text-tertiary); }

.field-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.field-row label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.field-row input {
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  width: 160px;
}

.field-row input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.config-output {
  margin-top: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 4px;
  overflow: hidden;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-primary);
  font-size: 11px;
  color: var(--text-secondary);
}

.btn-copy {
  padding: 3px 10px;
  font-size: 11px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 3px;
  color: var(--text-primary);
  cursor: pointer;
}

.btn-copy:hover { background: var(--bg-hover); }

.config-output pre {
  margin: 0;
  padding: 12px;
  font-size: 11px;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  color: var(--text-primary);
  line-height: 1.6;
  overflow-x: auto;
}

.config-note {
  padding: 8px 12px;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-primary);
  line-height: 1.5;
  margin: 0;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 36px;
  margin-bottom: 12px;
}

.empty-state p {
  margin: 4px 0;
  font-size: 14px;
}

.empty-hint {
  font-size: 12px !important;
  color: var(--text-tertiary);
}

/* Node table */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-primary);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.data-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color, var(--border-primary));
  color: var(--text-primary);
}

.node-row {
  cursor: pointer;
}

.node-row:hover {
  background: var(--bg-hover);
}

.node-row.expanded {
  background: var(--bg-secondary);
}

.mono {
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  font-size: 12px;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.online { background: #22c55e; }
.status-dot.offline { background: #ef4444; }
.status-dot.unknown { background: #eab308; }

.type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
}

.type-daq { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.type-crio { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.type-opto22 { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.type-gc { background: rgba(251, 146, 60, 0.15); color: #fb923c; }

.state-badge {
  font-size: 11px;
  font-weight: 500;
}

.state-badge.recording { color: #3b82f6; }
.state-badge.acquiring { color: #22c55e; }
.state-badge.idle { color: var(--text-tertiary); }

/* Detail row */
.detail-row td {
  padding: 0;
  background: var(--bg-secondary);
}

.node-detail {
  padding: 16px 20px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.detail-label {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.detail-value {
  font-size: 13px;
  color: var(--text-primary);
}

.status-text-online { color: #22c55e; }
.status-text-offline { color: #ef4444; }
.sync-warning { color: #eab308; }
.safety-warning { color: #eab308; }
.safety-tripped { color: #ef4444; font-weight: 600; }
.safety-emergency { color: #ef4444; font-weight: 700; }

.detail-note {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  border-left: 3px solid var(--accent-primary);
}

/* Create Instance form */
.create-instance-form h4 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.form-fields {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}

.toggle-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
}

.form-actions {
  margin-bottom: 10px;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.create-result {
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 8px;
}

.create-result.success {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.create-result.error {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.create-result.creating {
  color: var(--text-secondary);
  background: var(--bg-primary);
}

.launch-command {
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 4px;
  overflow: hidden;
}

.launch-command pre {
  margin: 0;
  padding: 10px 12px;
  font-size: 12px;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  color: var(--text-primary);
  overflow-x: auto;
}
</style>
