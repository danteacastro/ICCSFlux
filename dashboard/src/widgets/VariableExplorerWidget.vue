<script setup lang="ts">
/**
 * Variable Explorer Widget
 *
 * IPython-like Variable Explorer that displays user-defined variables
 * from the console's persistent namespace.
 *
 * Features:
 * - Lists all user-defined variables (name, type, value)
 * - Shows NumPy array shape and dtype
 * - Expandable preview for complex objects
 * - Auto-refresh when console state changes
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const props = defineProps<{
  widgetId: string
  label?: string
  autoRefresh?: boolean  // Auto-refresh on interval (default true)
  refreshInterval?: number  // Refresh interval in ms (default 2000)
}>()

const mqtt = useMqtt('nisystem')

// Variable data
interface Variable {
  name: string
  type: string
  value: string | number | any[] | null
  size: number | null
  shape: number[] | null
  dtype: string | null
}

const variables = ref<Variable[]>([])
const isLoading = ref(false)
const lastUpdate = ref<number | null>(null)
const error = ref<string | null>(null)

// Expanded variables (for viewing full content)
const expandedVars = ref<Set<string>>(new Set())

// Auto-refresh
const refreshTimerId = ref<number | null>(null)
const autoRefresh = computed(() => props.autoRefresh !== false)
const refreshInterval = computed(() => props.refreshInterval || 2000)

// Subscribe to variable response
let variablesHandler: ((data: any) => void) | null = null

onMounted(() => {
  // Subscribe to variables response
  variablesHandler = (data: { success: boolean; variables?: Variable[]; error?: string }) => {
    isLoading.value = false
    if (data.success && data.variables) {
      variables.value = data.variables
      lastUpdate.value = Date.now()
      error.value = null
    } else {
      error.value = data.error || 'Failed to fetch variables'
    }
  }

  mqtt.subscribe('nisystem/nodes/+/console/variables/result', variablesHandler)

  // Initial fetch
  requestVariables()

  // Setup auto-refresh
  if (autoRefresh.value) {
    refreshTimerId.value = window.setInterval(() => {
      requestVariables()
    }, refreshInterval.value)
  }
})

onUnmounted(() => {
  if (refreshTimerId.value !== null) {
    clearInterval(refreshTimerId.value)
  }
})

function requestVariables() {
  if (!mqtt.connected.value) return
  isLoading.value = true
  mqtt.sendLocalCommand('console/variables', {})
}

function toggleExpand(varName: string) {
  if (expandedVars.value.has(varName)) {
    expandedVars.value.delete(varName)
  } else {
    expandedVars.value.add(varName)
  }
}

function formatValue(v: Variable): string {
  if (v.value === null || v.value === undefined) {
    return '--'
  }
  if (typeof v.value === 'string') {
    return v.value
  }
  if (Array.isArray(v.value)) {
    return JSON.stringify(v.value)
  }
  return String(v.value)
}

function formatSize(v: Variable): string {
  if (v.shape) {
    return `[${v.shape.join(' x ')}]`
  }
  if (v.size !== null) {
    return `(${v.size})`
  }
  return ''
}

function getTypeClass(type: string): string {
  switch (type) {
    case 'int':
    case 'float':
      return 'type-number'
    case 'str':
      return 'type-string'
    case 'list':
    case 'tuple':
    case 'dict':
    case 'set':
      return 'type-collection'
    case 'ndarray':
      return 'type-array'
    case 'bool':
      return 'type-bool'
    default:
      return 'type-other'
  }
}

function resetNamespace() {
  mqtt.sendLocalCommand('console/reset', {})
  // Clear immediately for responsiveness
  variables.value = []
  expandedVars.value.clear()
}

const displayLabel = computed(() => props.label || 'Variable Explorer')
const hasVariables = computed(() => variables.value.length > 0)
</script>

<template>
  <div class="variable-explorer-widget">
    <div class="widget-header">
      <span class="widget-title">{{ displayLabel }}</span>
      <div class="header-actions">
        <span v-if="lastUpdate" class="last-update">
          {{ new Date(lastUpdate).toLocaleTimeString() }}
        </span>
        <button
          class="action-btn"
          @click="requestVariables"
          :disabled="isLoading"
          title="Refresh variables"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: isLoading }">
            <path d="M23 4v6h-6M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
          </svg>
        </button>
        <button
          class="action-btn danger"
          @click="resetNamespace"
          title="Reset namespace (clear all variables)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Variables Table -->
    <div class="variables-container">
      <div v-if="error" class="error-state">
        {{ error }}
      </div>

      <div v-else-if="!hasVariables" class="empty-state">
        <span class="empty-icon">{ }</span>
        <span>No user variables</span>
        <span class="hint">Define variables in the console</span>
      </div>

      <table v-else class="variables-table">
        <thead>
          <tr>
            <th class="col-name">Name</th>
            <th class="col-type">Type</th>
            <th class="col-size">Size</th>
            <th class="col-value">Value</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="v in variables"
            :key="v.name"
            class="variable-row"
            @click="toggleExpand(v.name)"
          >
            <td class="col-name">
              <span class="var-name">{{ v.name }}</span>
            </td>
            <td class="col-type">
              <span class="type-badge" :class="getTypeClass(v.type)">
                {{ v.type }}
              </span>
            </td>
            <td class="col-size">
              <span v-if="v.dtype" class="dtype">{{ v.dtype }}</span>
              <span class="size">{{ formatSize(v) }}</span>
            </td>
            <td class="col-value">
              <span
                class="value-preview"
                :class="{ expanded: expandedVars.has(v.name) }"
              >
                {{ formatValue(v) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div class="widget-footer">
      <span class="var-count">{{ variables.length }} variable{{ variables.length !== 1 ? 's' : '' }}</span>
      <span v-if="!mqtt.connected.value" class="disconnected">Disconnected</span>
    </div>
  </div>
</template>

<style scoped>
.variable-explorer-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d1a;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  font-family: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
  font-size: 0.7rem;
  overflow: hidden;
}

.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--bg-widget);
  border-bottom: 1px solid var(--border-color);
}

.widget-title {
  font-size: 0.65rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.last-update {
  font-size: 0.6rem;
  color: var(--text-dim);
}

.action-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 4px;
  display: flex;
  align-items: center;
  border-radius: 2px;
}

.action-btn:hover {
  color: #aaa;
  background: var(--border-color);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.danger:hover {
  color: var(--color-error-light);
  background: rgba(239, 68, 68, 0.1);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Variables Container */
.variables-container {
  flex: 1;
  overflow-y: auto;
  min-height: 40px;
}

.error-state {
  padding: 16px;
  text-align: center;
  color: var(--color-error-light);
  font-size: 0.75rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
  color: var(--text-dim);
  height: 100%;
}

.empty-icon {
  font-size: 1.5rem;
  margin-bottom: 8px;
  opacity: 0.5;
}

.hint {
  font-size: 0.6rem;
  color: #444;
  margin-top: 4px;
}

/* Table */
.variables-table {
  width: 100%;
  border-collapse: collapse;
}

.variables-table th {
  position: sticky;
  top: 0;
  background: #151525;
  padding: 4px 6px;
  text-align: left;
  font-size: 0.6rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  border-bottom: 1px solid var(--border-color);
}

.variables-table td {
  padding: 3px 6px;
  border-bottom: 1px solid #1f1f35;
  vertical-align: top;
}

.variable-row {
  cursor: pointer;
}

.variable-row:hover {
  background: rgba(255, 255, 255, 0.02);
}

.col-name {
  width: 30%;
}

.col-type {
  width: 15%;
}

.col-size {
  width: 15%;
}

.col-value {
  width: 40%;
}

.var-name {
  color: var(--color-accent-light);
  font-weight: 500;
}

/* Type badges */
.type-badge {
  display: inline-block;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.6rem;
  background: var(--bg-gradient-elevated);
  color: var(--text-secondary);
}

.type-number {
  background: rgba(74, 222, 128, 0.1);
  color: var(--color-success-light);
}

.type-string {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.type-collection {
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
}

.type-array {
  background: var(--color-accent-bg);
  color: var(--color-accent);
}

.type-bool {
  background: rgba(236, 72, 153, 0.1);
  color: #ec4899;
}

/* Size & dtype */
.dtype {
  color: var(--text-muted);
  font-size: 0.6rem;
  margin-right: 4px;
}

.size {
  color: var(--text-dim);
  font-size: 0.6rem;
}

/* Value */
.value-preview {
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
  max-width: 200px;
}

.value-preview.expanded {
  white-space: pre-wrap;
  word-break: break-word;
  max-width: none;
}

/* Footer */
.widget-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 8px;
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
  font-size: 0.6rem;
}

.var-count {
  color: var(--text-dim);
}

.disconnected {
  color: var(--color-error-light);
}

/* Scrollbar */
.variables-container::-webkit-scrollbar {
  width: 6px;
}

.variables-container::-webkit-scrollbar-track {
  background: #0d0d1a;
}

.variables-container::-webkit-scrollbar-thumb {
  background: var(--border-light);
  border-radius: 3px;
}

.variables-container::-webkit-scrollbar-thumb:hover {
  background: var(--bg-knob-border);
}
</style>
