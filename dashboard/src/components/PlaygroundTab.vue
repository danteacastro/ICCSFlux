<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePlayground } from '../composables/usePlayground'
import { useScripts } from '../composables/useScripts'
import { useDashboardStore } from '../stores/dashboard'
import type { UserVariable, UserVariableType, ResetMode, EdgeType } from '../types'

const playground = usePlayground()
const scripts = useScripts()
const store = useDashboardStore()

// UI state
const showAddModal = ref(false)
const showConfigModal = ref(false)
const editingVariable = ref<UserVariable | null>(null)

// New variable form
const newVariable = ref({
  name: '',
  displayName: '',
  description: '',
  variableType: 'manual' as UserVariableType,
  value: 0,
  units: '',
  persistent: true,
  sourceChannel: '',
  edgeType: 'increment' as EdgeType,
  scaleFactor: 1,
  resetMode: 'manual' as ResetMode,
  resetTime: '00:00',
  resetElapsedS: 3600,
  formula: ''
})

// Available channels for source selection
const availableChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, ch]) => ch.visible !== false)
    .map(([name, ch]) => ({
      name,
      displayName: ch.display_name || name,
      unit: ch.unit,
      type: ch.channel_type
    }))
})

// Counter/digital channels for accumulator/counter types
const counterChannels = computed(() => {
  return availableChannels.value.filter(ch =>
    ch.type === 'counter' || ch.type === 'digital_input'
  )
})

// Numeric channels for stats types
const numericChannels = computed(() => {
  return availableChannels.value.filter(ch =>
    !['digital_output'].includes(ch.type)
  )
})

function openAddModal() {
  editingVariable.value = null
  newVariable.value = {
    name: '',
    displayName: '',
    description: '',
    variableType: 'manual',
    value: 0,
    units: '',
    persistent: true,
    sourceChannel: '',
    edgeType: 'increment',
    scaleFactor: 1,
    resetMode: 'manual',
    resetTime: '00:00',
    resetElapsedS: 3600,
    formula: ''
  }
  showAddModal.value = true
}

function openEditModal(variable: UserVariable) {
  editingVariable.value = variable
  newVariable.value = {
    name: variable.name,
    displayName: variable.displayName,
    description: (variable as any).description || '',
    variableType: variable.variableType,
    value: variable.value || 0,
    units: variable.units,
    persistent: variable.persistent,
    sourceChannel: variable.sourceChannel || '',
    edgeType: variable.edgeType || 'increment',
    scaleFactor: variable.scaleFactor || 1,
    resetMode: variable.resetMode,
    resetTime: variable.resetTime || '00:00',
    resetElapsedS: variable.resetElapsedS || 3600,
    formula: variable.formula || ''
  }
  showAddModal.value = true
}

function saveVariable() {
  // Validate required field
  if (!newVariable.value.name.trim()) {
    alert('Name (TAG) is required')
    return
  }

  const varData: Partial<UserVariable> & { description?: string } = {
    name: newVariable.value.name.trim(),
    displayName: newVariable.value.displayName.trim() || newVariable.value.name.trim(),
    description: newVariable.value.description.trim(),
    variableType: newVariable.value.variableType,
    units: newVariable.value.units,
    persistent: newVariable.value.persistent,
    resetMode: newVariable.value.resetMode
  }

  // For constant and manual types, include the initial value
  if (newVariable.value.variableType === 'constant' || newVariable.value.variableType === 'manual') {
    varData.value = newVariable.value.value
  }

  // Type-specific fields
  const typeInfo = playground.VARIABLE_TYPE_INFO[newVariable.value.variableType]
  if (typeInfo.requiresSource) {
    varData.sourceChannel = newVariable.value.sourceChannel
    varData.scaleFactor = newVariable.value.scaleFactor
  }

  if (newVariable.value.variableType === 'accumulator' || newVariable.value.variableType === 'counter') {
    varData.edgeType = newVariable.value.edgeType
  }

  if (typeInfo.supportsFormula) {
    varData.formula = newVariable.value.formula
  }

  if (newVariable.value.resetMode === 'time_of_day') {
    varData.resetTime = newVariable.value.resetTime
  } else if (newVariable.value.resetMode === 'elapsed') {
    varData.resetElapsedS = newVariable.value.resetElapsedS
  }

  if (editingVariable.value) {
    playground.updateVariable(editingVariable.value.id, varData)
  } else {
    playground.createVariable(varData)
  }

  showAddModal.value = false
}

function deleteVariable(variable: UserVariable) {
  if (confirm(`Delete variable "${variable.displayName}"?`)) {
    playground.deleteVariable(variable.id)
  }
}

function getVariableTypeIcon(type: UserVariableType): string {
  return playground.VARIABLE_TYPE_INFO[type]?.icon || '📊'
}

function getResetModeLabel(mode: ResetMode): string {
  return playground.RESET_MODE_INFO[mode]?.label || mode
}

// Session config form
const sessionConfig = ref({
  enableScheduler: true,
  startRecording: true,
  enableTriggers: true,
  resetVariables: [] as string[],
  runSequenceId: '' as string,
  stopSequenceId: '' as string,
  enableTriggerIds: [] as string[],
  enableScheduleIds: [] as string[]
})

function openConfigModal() {
  const config = playground.testSession.value.config
  sessionConfig.value = {
    enableScheduler: config.enableScheduler,
    startRecording: config.startRecording,
    enableTriggers: config.enableTriggers,
    resetVariables: [...(config.resetVariables || [])],
    runSequenceId: config.runSequenceId || '',
    stopSequenceId: config.stopSequenceId || '',
    enableTriggerIds: (config as any).enableTriggerIds || [],
    enableScheduleIds: (config as any).enableScheduleIds || []
  }
  showConfigModal.value = true
}

function saveSessionConfig() {
  playground.updateSessionConfig(sessionConfig.value)
  showConfigModal.value = false
}

// Available items from Scripts tab
const availableSequences = computed(() => scripts.sequences.value.filter(s => s.enabled))
const availableTriggers = computed(() => scripts.triggers.value.filter(t => t.enabled))
const availableSchedules = computed(() => scripts.schedules.value.filter(s => s.enabled))

onMounted(() => {
  playground.refreshVariables()
  playground.refreshSessionStatus()
})
</script>

<template>
  <div class="playground-tab">
    <!-- Header -->
    <div class="tab-header">
      <h2>Data Playground</h2>
      <button class="btn btn-primary" @click="openAddModal">
        + Add Variable
      </button>
    </div>

    <!-- Test Session Panel -->
    <div class="session-panel" :class="{ active: playground.isSessionActive.value }">
      <div class="session-header">
        <h3>Test Session</h3>
        <span class="session-status">
          <span class="status-dot" :class="{ active: playground.isSessionActive.value }"></span>
          {{ playground.isSessionActive.value ? 'Running' : 'Idle' }}
        </span>
      </div>

      <div class="session-info" v-if="playground.isSessionActive.value">
        <div class="elapsed-time">{{ playground.sessionElapsed.value }}</div>
        <div class="session-meta">
          Started: {{ playground.testSession.value.startedAt?.split('T')[1]?.split('.')[0] || '--' }}
          by {{ playground.testSession.value.startedBy || 'user' }}
        </div>
      </div>

      <div class="session-controls">
        <button
          class="btn btn-success"
          @click="playground.startTestSession()"
          :disabled="playground.isSessionActive.value || !store.isAcquiring"
          :title="!store.isAcquiring ? 'Start acquisition first' : ''"
        >
          Start Session
        </button>
        <button
          class="btn btn-danger"
          @click="playground.stopTestSession()"
          :disabled="!playground.isSessionActive.value"
        >
          Stop Session
        </button>
        <button class="btn btn-secondary" @click="openConfigModal">
          Configure
        </button>
      </div>

      <div class="session-hint" v-if="!store.isAcquiring">
        Start acquisition before starting a test session
      </div>
    </div>

    <!-- Variables Table -->
    <div class="variables-section">
      <div class="section-header">
        <h3>User Variables</h3>
        <div class="section-actions">
          <button class="btn btn-sm" @click="playground.resetAllVariables()">
            Reset All
          </button>
          <button class="btn btn-sm" @click="playground.refreshVariables()">
            Refresh
          </button>
        </div>
      </div>

      <div class="variables-table" v-if="playground.variablesList.value.length > 0">
        <table>
          <thead>
            <tr>
              <th>Tag</th>
              <th>Type</th>
              <th>Value</th>
              <th>Source</th>
              <th>Reset</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="variable in playground.variablesList.value" :key="variable.id">
              <td class="name-cell">
                <span class="var-icon">{{ getVariableTypeIcon(variable.variableType) }}</span>
                <span class="var-name">{{ variable.displayName }}</span>
              </td>
              <td class="type-cell">
                {{ playground.VARIABLE_TYPE_INFO[variable.variableType]?.label }}
              </td>
              <td class="value-cell">
                <span class="value">{{ playground.formatValue(variable) }}</span>
                <span class="units" v-if="variable.units">{{ variable.units }}</span>
              </td>
              <td class="source-cell">
                {{ variable.sourceChannel || '-' }}
              </td>
              <td class="reset-cell">
                {{ getResetModeLabel(variable.resetMode) }}
              </td>
              <td class="actions-cell">
                <button
                  v-if="variable.variableType === 'timer'"
                  class="btn btn-xs"
                  @click="variable.timerRunning ? playground.stopTimer(variable.id) : playground.startTimer(variable.id)"
                >
                  {{ variable.timerRunning ? 'Stop' : 'Start' }}
                </button>
                <button class="btn btn-xs" @click="playground.resetVariable(variable.id)">
                  Reset
                </button>
                <button class="btn btn-xs" @click="openEditModal(variable)">
                  Edit
                </button>
                <button class="btn btn-xs btn-danger" @click="deleteVariable(variable)">
                  Delete
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="empty-state" v-else>
        <p>No user variables defined yet.</p>
        <p>Click "Add Variable" to create accumulators, counters, timers, and more.</p>
      </div>
    </div>

    <!-- Add/Edit Variable Modal -->
    <Teleport to="body">
      <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
        <div class="modal variable-modal">
          <h3>{{ editingVariable ? 'Edit Variable' : 'Add Variable' }}</h3>

          <div class="form-grid">
            <div class="form-group">
              <label>Name (TAG) <span class="required">*</span></label>
              <input v-model="newVariable.name" placeholder="e.g., GallonsTotal" required />
              <small class="hint">Unique identifier for the variable</small>
            </div>

            <div class="form-group">
              <label>Display Name</label>
              <input v-model="newVariable.displayName" placeholder="e.g., Total Gallons" />
            </div>

            <div class="form-group full-width">
              <label>Description</label>
              <input v-model="newVariable.description" placeholder="e.g., Running total of gallons dispensed" />
            </div>

            <div class="form-group">
              <label>Type</label>
              <select v-model="newVariable.variableType">
                <option v-for="(info, type) in playground.VARIABLE_TYPE_INFO" :key="type" :value="type">
                  {{ info.icon }} {{ info.label }}
                </option>
              </select>
              <small class="hint">{{ playground.VARIABLE_TYPE_INFO[newVariable.variableType]?.description }}</small>
            </div>

            <div class="form-group">
              <label>Units</label>
              <input v-model="newVariable.units" placeholder="e.g., gal, counts, sec" />
            </div>

            <!-- Value (for constant and manual types) -->
            <div class="form-group" v-if="newVariable.variableType === 'constant' || newVariable.variableType === 'manual'">
              <label>Value</label>
              <input type="number" v-model.number="newVariable.value" step="any" />
              <small class="hint" v-if="newVariable.variableType === 'constant'">Fixed value - use variable name in formulas</small>
              <small class="hint" v-else>Initial value (can be changed later)</small>
            </div>

            <!-- Source channel (for types that need it) -->
            <div class="form-group" v-if="playground.VARIABLE_TYPE_INFO[newVariable.variableType]?.requiresSource">
              <label>Source Channel</label>
              <select v-model="newVariable.sourceChannel">
                <option value="">-- Select --</option>
                <option
                  v-for="ch in (newVariable.variableType === 'accumulator' || newVariable.variableType === 'counter' ? counterChannels : numericChannels)"
                  :key="ch.name"
                  :value="ch.name"
                >
                  {{ ch.displayName }} ({{ ch.unit }})
                </option>
              </select>
            </div>

            <!-- Edge type (for accumulator/counter) -->
            <div class="form-group" v-if="newVariable.variableType === 'accumulator' || newVariable.variableType === 'counter'">
              <label>Edge Type</label>
              <select v-model="newVariable.edgeType">
                <option v-for="(info, type) in playground.EDGE_TYPE_INFO" :key="type" :value="type">
                  {{ info.label }}
                </option>
              </select>
              <small class="hint">{{ playground.EDGE_TYPE_INFO[newVariable.edgeType]?.description }}</small>
            </div>

            <!-- Scale factor -->
            <div class="form-group" v-if="playground.VARIABLE_TYPE_INFO[newVariable.variableType]?.requiresSource">
              <label>Scale Factor</label>
              <input type="number" v-model.number="newVariable.scaleFactor" step="0.001" />
              <small class="hint">Multiply each increment by this value</small>
            </div>

            <!-- Formula (for expression types) -->
            <div class="form-group full-width" v-if="playground.VARIABLE_TYPE_INFO[newVariable.variableType]?.supportsFormula">
              <label>Formula</label>
              <input v-model="newVariable.formula" placeholder="e.g., TC101 * 1.8 + 32" />
              <small class="hint">Use channel names as variables</small>
            </div>

            <div class="form-group">
              <label>Reset Mode</label>
              <select v-model="newVariable.resetMode">
                <option v-for="(info, mode) in playground.RESET_MODE_INFO" :key="mode" :value="mode">
                  {{ info.label }}
                </option>
              </select>
              <small class="hint">{{ playground.RESET_MODE_INFO[newVariable.resetMode]?.description }}</small>
            </div>

            <!-- Time of day reset -->
            <div class="form-group" v-if="newVariable.resetMode === 'time_of_day'">
              <label>Reset Time</label>
              <input type="time" v-model="newVariable.resetTime" />
            </div>

            <!-- Elapsed reset -->
            <div class="form-group" v-if="newVariable.resetMode === 'elapsed'">
              <label>Reset After (seconds)</label>
              <input type="number" v-model.number="newVariable.resetElapsedS" min="1" />
            </div>

            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" v-model="newVariable.persistent" />
                Persist across restarts
              </label>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showAddModal = false">Cancel</button>
            <button class="btn btn-primary" @click="saveVariable" :disabled="!newVariable.name">
              {{ editingVariable ? 'Save' : 'Create' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Session Config Modal -->
    <Teleport to="body">
      <div v-if="showConfigModal" class="modal-overlay" @click.self="showConfigModal = false">
        <div class="modal config-modal">
          <h3>Test Session Configuration</h3>
          <p class="config-subtitle">Select what gets activated when you start/stop a test session</p>

          <!-- Basic Options -->
          <div class="config-section">
            <h4>Session Behavior</h4>
            <div class="config-options">
              <label class="checkbox-label">
                <input type="checkbox" v-model="sessionConfig.startRecording" />
                <span>Start data recording</span>
              </label>
              <label class="checkbox-label">
                <input type="checkbox" v-model="sessionConfig.enableScheduler" />
                <span>Enable scheduler</span>
              </label>
            </div>
          </div>

          <!-- Sequences Section -->
          <div class="config-section">
            <h4>Sequences</h4>
            <div class="config-grid" v-if="availableSequences.length > 0">
              <div class="config-field">
                <label>Run on Start:</label>
                <select v-model="sessionConfig.runSequenceId">
                  <option value="">None</option>
                  <option v-for="seq in availableSequences" :key="seq.id" :value="seq.id">
                    {{ seq.name }}
                  </option>
                </select>
              </div>
              <div class="config-field">
                <label>Run on Stop:</label>
                <select v-model="sessionConfig.stopSequenceId">
                  <option value="">None</option>
                  <option v-for="seq in availableSequences" :key="seq.id" :value="seq.id">
                    {{ seq.name }}
                  </option>
                </select>
              </div>
            </div>
            <div class="empty-hint" v-else>
              No sequences configured. Create sequences in the Scripts tab.
            </div>
          </div>

          <!-- Triggers Section -->
          <div class="config-section">
            <h4>Triggers to Enable</h4>
            <div class="checkbox-grid" v-if="availableTriggers.length > 0">
              <label
                v-for="trigger in availableTriggers"
                :key="trigger.id"
                class="checkbox-label"
              >
                <input
                  type="checkbox"
                  :checked="sessionConfig.enableTriggerIds.includes(trigger.id)"
                  @change="(e: Event) => {
                    const target = e.target as HTMLInputElement
                    if (target.checked) {
                      sessionConfig.enableTriggerIds.push(trigger.id)
                    } else {
                      sessionConfig.enableTriggerIds = sessionConfig.enableTriggerIds.filter(id => id !== trigger.id)
                    }
                  }"
                />
                <span>{{ trigger.name }}</span>
              </label>
            </div>
            <div class="empty-hint" v-else>
              No triggers configured. Create triggers in the Scripts tab.
            </div>
          </div>

          <!-- Schedules Section -->
          <div class="config-section">
            <h4>Schedules to Enable</h4>
            <div class="checkbox-grid" v-if="availableSchedules.length > 0">
              <label
                v-for="schedule in availableSchedules"
                :key="schedule.id"
                class="checkbox-label"
              >
                <input
                  type="checkbox"
                  :checked="sessionConfig.enableScheduleIds.includes(schedule.id)"
                  @change="(e: Event) => {
                    const target = e.target as HTMLInputElement
                    if (target.checked) {
                      sessionConfig.enableScheduleIds.push(schedule.id)
                    } else {
                      sessionConfig.enableScheduleIds = sessionConfig.enableScheduleIds.filter(id => id !== schedule.id)
                    }
                  }"
                />
                <span>{{ schedule.name }}</span>
              </label>
            </div>
            <div class="empty-hint" v-else>
              No schedules configured. Create schedules in the Scripts tab.
            </div>
          </div>

          <!-- Variables Reset Section -->
          <div class="config-section">
            <h4>Variables to Reset on Start</h4>
            <div class="checkbox-grid" v-if="playground.variablesList.value.length > 0">
              <label
                v-for="variable in playground.variablesList.value"
                :key="variable.id"
                class="checkbox-label"
              >
                <input
                  type="checkbox"
                  :checked="sessionConfig.resetVariables.includes(variable.id)"
                  @change="(e: Event) => {
                    const target = e.target as HTMLInputElement
                    if (target.checked) {
                      sessionConfig.resetVariables.push(variable.id)
                    } else {
                      sessionConfig.resetVariables = sessionConfig.resetVariables.filter(id => id !== variable.id)
                    }
                  }"
                />
                <span>{{ variable.displayName }}</span>
              </label>
            </div>
            <div class="empty-hint" v-else>
              No variables defined yet.
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showConfigModal = false">Cancel</button>
            <button class="btn btn-primary" @click="saveSessionConfig">Save Configuration</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.playground-tab {
  padding: 1rem;
  max-width: 1400px;
  margin: 0 auto;
}

.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.tab-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

/* Session Panel */
.session-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1.5rem;
}

.session-panel.active {
  border-color: var(--color-success);
  box-shadow: 0 0 10px rgba(34, 197, 94, 0.2);
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.session-header h3 {
  margin: 0;
  font-size: 1.1rem;
}

.session-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-muted);
}

.status-dot.active {
  background: var(--color-success);
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.session-info {
  text-align: center;
  margin: 1rem 0;
}

.elapsed-time {
  font-size: 2rem;
  font-weight: 600;
  font-family: monospace;
  color: var(--color-success);
}

.session-meta {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.session-controls {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
}

.session-hint {
  text-align: center;
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-top: 0.75rem;
  font-style: italic;
}

/* Variables Section */
.variables-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
}

.section-actions {
  display: flex;
  gap: 0.5rem;
}

/* Variables Table */
.variables-table {
  overflow-x: auto;
}

.variables-table table {
  width: 100%;
  border-collapse: collapse;
}

.variables-table th,
.variables-table td {
  padding: 0.75rem;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
}

.variables-table th {
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.85rem;
  text-transform: uppercase;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.var-icon {
  font-size: 1.2rem;
}

.var-name {
  font-weight: 500;
}

.value-cell .value {
  font-family: monospace;
  font-weight: 600;
  font-size: 1.1rem;
}

.value-cell .units {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-left: 0.25rem;
}

.type-cell,
.source-cell,
.reset-cell {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.actions-cell {
  display: flex;
  gap: 0.25rem;
}

.actions-cell .btn {
  color: var(--text-primary);
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--text-secondary);
}

.empty-state p {
  margin: 0.5rem 0;
}

/* Modal Styles */
.modal-overlay {
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

.modal {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 1.5rem;
  width: 90%;
  max-width: 600px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal h3 {
  margin: 0 0 1rem 0;
  font-size: 1.25rem;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-group.full-width {
  grid-column: 1 / -1;
}

.form-group label {
  font-weight: 500;
  font-size: 0.9rem;
}

.form-group input,
.form-group select {
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.form-group .hint {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 200px;
  overflow-y: auto;
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

/* Button styles */
.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.btn-success {
  background: var(--color-success);
  color: white;
}

.btn-danger {
  background: var(--color-danger);
  color: white;
}

.required {
  color: var(--color-danger);
}

.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.85rem;
}

.btn-xs {
  padding: 0.2rem 0.4rem;
  font-size: 0.8rem;
}

/* Config Modal Styles */
.config-modal {
  max-width: 700px;
}

.config-subtitle {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin: -0.5rem 0 1.5rem 0;
}

.config-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.config-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.95rem;
  color: var(--text-primary);
  font-weight: 600;
}

.config-options {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.config-field label {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.config-field select {
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem;
}

.checkbox-grid .checkbox-label {
  padding: 0.5rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  transition: border-color 0.2s;
}

.checkbox-grid .checkbox-label:hover {
  border-color: var(--color-primary);
}

.checkbox-grid .checkbox-label input:checked + span {
  color: var(--color-primary);
  font-weight: 500;
}

.empty-hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-style: italic;
  padding: 0.5rem;
  background: var(--bg-primary);
  border-radius: 4px;
  text-align: center;
}
</style>
