<script setup lang="ts">
import { ref } from 'vue'
import { useFleetStore } from '../stores/fleet'
import { useFleetMqtt } from '../composables/useFleetMqtt'
import NodeConfigModal from './NodeConfigModal.vue'
import type { MonitorNode } from '../types'

const emit = defineEmits<{ close: [] }>()

const store = useFleetStore()
const mqtt = useFleetMqtt()

const showModal = ref(false)
const editingNode = ref<MonitorNode | null>(null)

function openAdd() {
  editingNode.value = null
  showModal.value = true
}

function openEdit(node: MonitorNode) {
  editingNode.value = node
  showModal.value = true
}

function handleSave(node: MonitorNode) {
  if (editingNode.value) {
    // Editing — disconnect old, update, reconnect if enabled
    mqtt.disconnectNode(node.id)
    store.updateNode(node.id, node)
    if (node.enabled) mqtt.connectNode(node)
  } else {
    // Adding
    store.addNode(node)
    if (node.enabled) mqtt.connectNode(node)
  }
  showModal.value = false
}

function handleRemove(id: string) {
  mqtt.disconnectNode(id)
  store.removeNode(id)
}

function toggleEnabled(node: MonitorNode) {
  const newEnabled = !node.enabled
  store.updateNode(node.id, { enabled: newEnabled })
  if (newEnabled) {
    mqtt.connectNode(node)
  } else {
    mqtt.disconnectNode(node.id)
  }
}
</script>

<template>
  <div class="settings">
    <div class="settings-header">
      <h2>Settings</h2>
      <button class="close-btn" @click="emit('close')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <div class="section">
      <div class="section-header">
        <h3>Monitored Nodes</h3>
        <button class="add-btn" @click="openAdd">+ Add Node</button>
      </div>

      <div v-if="store.nodes.length > 0" class="node-table">
        <div class="table-header">
          <span class="col-name">Name</span>
          <span class="col-host">Host</span>
          <span class="col-port">Port</span>
          <span class="col-status">Status</span>
          <span class="col-actions">Actions</span>
        </div>
        <div
          v-for="node in store.nodes"
          :key="node.id"
          class="table-row"
        >
          <span class="col-name">{{ node.name }}</span>
          <span class="col-host mono">{{ node.host }}</span>
          <span class="col-port mono">{{ node.port }}</span>
          <span class="col-status">
            <span class="status-dot" :class="store.nodeStates.get(node.id)?.connection.connected ? 'on' : 'off'"></span>
            {{ store.nodeStates.get(node.id)?.connection.connected ? 'Connected' : 'Offline' }}
          </span>
          <span class="col-actions">
            <button class="action-btn" @click="toggleEnabled(node)" :title="node.enabled ? 'Disable' : 'Enable'">
              {{ node.enabled ? 'Disable' : 'Enable' }}
            </button>
            <button class="action-btn" @click="openEdit(node)">Edit</button>
            <button class="action-btn danger" @click="handleRemove(node.id)">Remove</button>
          </span>
        </div>
      </div>

      <div v-else class="empty">
        <p>No nodes configured yet.</p>
        <p>Add a node by entering the IP address and MQTT credentials of an ICCSFlux portable build.</p>
        <p class="hint">Credentials are in each PC's <code>config/mqtt_credentials.json</code></p>
      </div>
    </div>

    <NodeConfigModal
      v-if="showModal"
      :node="editingNode"
      @save="handleSave"
      @cancel="showModal = false"
    />
  </div>
</template>

<style scoped>
.settings {
  padding: 1.25rem;
  max-width: 900px;
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}

.settings-header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0;
}

.close-btn {
  width: 2rem;
  height: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--btn-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  transition: all 0.15s;
}

.close-btn:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}

.section {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 1rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.section-header h3 {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0;
}

.add-btn {
  padding: 0.375rem 0.75rem;
  background: var(--color-accent);
  color: #fff;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
  transition: background 0.15s;
}

.add-btn:hover {
  background: var(--color-accent-dark);
}

.node-table {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.table-header, .table-row {
  display: grid;
  grid-template-columns: 1.5fr 1.5fr 0.5fr 1fr 1.5fr;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
}

.table-header {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border-color);
}

.table-row {
  font-size: 0.85rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
}

.table-row:last-child {
  border-bottom: none;
}

.col-actions {
  display: flex;
  gap: 0.375rem;
}

.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 0.25rem;
}

.status-dot.on { background: var(--color-success); }
.status-dot.off { background: var(--text-muted); }

.action-btn {
  padding: 0.2rem 0.5rem;
  background: var(--btn-bg);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: var(--text-secondary);
  font-size: 0.7rem;
  transition: all 0.15s;
}

.action-btn:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}

.action-btn.danger:hover {
  background: var(--color-error-bg);
  border-color: var(--color-error);
  color: var(--color-error);
}

.empty {
  text-align: center;
  padding: 2rem 1rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.empty p { margin: 0.375rem 0; }
.hint { font-size: 0.8rem; color: var(--text-dim); }
.hint code {
  background: var(--bg-surface);
  padding: 0.125rem 0.375rem;
  border-radius: 3px;
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
}
</style>
