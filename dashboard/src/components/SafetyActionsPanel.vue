<script setup lang="ts">
/**
 * Safety Actions Panel
 *
 * Manages ISA-18.2 Safety Actions that can be triggered by alarms.
 * Action types:
 * - trip_system: Full system trip - all outputs to safe state
 * - stop_session: Stop test session only
 * - stop_recording: Stop recording only
 * - set_output_safe: Set specific outputs to safe values
 * - run_sequence: Run a safety sequence
 * - custom: Custom MQTT action
 */
import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useBackendScripts } from '../composables/useBackendScripts'
import type { SafetyAction, SafetyActionType } from '../types'

const store = useDashboardStore()
const safety = useSafety()
const backendScripts = useBackendScripts()

// Modal state
const showModal = ref(false)
const editingAction = ref<SafetyAction | null>(null)

// Form state
const formData = ref<Omit<SafetyAction, 'id'>>({
  name: '',
  description: '',
  type: 'trip_system',
  enabled: true,
  outputChannels: [],
  safeValue: 0,
  analogSafeValue: 0,
  sequenceId: '',
  mqttTopic: '',
  mqttPayload: {}
})

// Action types
const actionTypes: { value: SafetyActionType; label: string; description: string; icon: string }[] = [
  {
    value: 'trip_system',
    label: 'Trip System',
    description: 'Full system trip - all outputs to safe state, stop session',
    icon: '!'
  },
  {
    value: 'stop_session',
    label: 'Stop Session',
    description: 'Stop the current test session only',
    icon: '||'
  },
  {
    value: 'stop_recording',
    label: 'Stop Recording',
    description: 'Stop data recording only',
    icon: 'O'
  },
  {
    value: 'set_output_safe',
    label: 'Set Output Safe',
    description: 'Set specific output channels to safe values',
    icon: '=>'
  },
  {
    value: 'run_sequence',
    label: 'Run Sequence',
    description: 'Execute a safety sequence script',
    icon: '>'
  },
  {
    value: 'custom',
    label: 'Custom Action',
    description: 'Send custom MQTT command',
    icon: '*'
  }
]

// Get all safety actions
const actionList = computed(() => {
  return Object.values(safety.safetyActions.value)
})

// Digital output channels
const digitalOutputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'digital_output')
    .map(([name]) => name)
})

// Analog output channels
const analogOutputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'analog_output')
    .map(([name, cfg]) => ({ name, unit: cfg.unit }))
})

// All output channels for multi-select
const allOutputChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.channel_type === 'digital_output' || cfg.channel_type === 'analog_output')
    .map(([name, cfg]) => ({
      name,
      type: cfg.channel_type,
      unit: cfg.unit
    }))
})

// Available sequences
const availableSequences = computed(() => {
  return backendScripts.scriptsList.value.map(s => s.id)
})

function openCreateModal() {
  editingAction.value = null
  formData.value = {
    name: '',
    description: '',
    type: 'trip_system',
    enabled: true,
    outputChannels: [],
    safeValue: 0,
    analogSafeValue: 0,
    sequenceId: '',
    mqttTopic: '',
    mqttPayload: {}
  }
  showModal.value = true
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function openEditModal(action: any) {
  editingAction.value = { ...action } as SafetyAction
  formData.value = {
    name: action.name,
    description: action.description || '',
    type: action.type,
    enabled: action.enabled,
    outputChannels: action.outputChannels ? [...action.outputChannels] : [],
    safeValue: action.safeValue ?? 0,
    analogSafeValue: action.analogSafeValue ?? 0,
    sequenceId: action.sequenceId || '',
    mqttTopic: action.mqttTopic || '',
    mqttPayload: action.mqttPayload || {}
  }
  showModal.value = true
}

function saveAction() {
  if (!formData.value.name.trim()) return

  if (editingAction.value) {
    safety.updateSafetyAction(editingAction.value.id, formData.value)
  } else {
    safety.addSafetyAction(formData.value)
  }

  showModal.value = false
}

function deleteAction(id: string) {
  if (confirm('Delete this safety action?')) {
    safety.removeSafetyAction(id)
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toggleActionEnabled(action: any) {
  safety.updateSafetyAction(action.id, { enabled: !action.enabled })
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function testAction(action: any) {
  if (confirm(`Test execute safety action "${action.name}"?`)) {
    safety.executeSafetyAction(action.id, 'manual-test')
  }
}

function toggleChannel(channel: string) {
  const idx = formData.value.outputChannels?.indexOf(channel) ?? -1
  if (idx >= 0) {
    formData.value.outputChannels?.splice(idx, 1)
  } else {
    if (!formData.value.outputChannels) {
      formData.value.outputChannels = []
    }
    formData.value.outputChannels.push(channel)
  }
}

function isChannelSelected(channel: string): boolean {
  return formData.value.outputChannels?.includes(channel) ?? false
}

function getActionTypeInfo(type: SafetyActionType) {
  return actionTypes.find(t => t.value === type)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatLastTriggered(action: any): string {
  if (!action.lastTriggeredAt) return 'Never'
  const date = new Date(action.lastTriggeredAt)
  return date.toLocaleString()
}
</script>

<template>
  <div class="safety-actions-panel">
    <!-- Header -->
    <div class="panel-header">
      <h4>Safety Actions</h4>
      <button class="btn btn-sm btn-primary" @click="openCreateModal">
        + Add Action
      </button>
    </div>

    <!-- Actions List -->
    <div class="actions-list">
      <div v-if="actionList.length === 0" class="empty-state">
        <p>No safety actions defined</p>
        <p class="hint">Safety actions are automatic responses triggered by alarms</p>
      </div>

      <div
        v-for="action in actionList"
        :key="action.id"
        class="action-card"
        :class="{ disabled: !action.enabled }"
      >
        <div class="action-header">
          <div class="action-icon">
            {{ getActionTypeInfo(action.type)?.icon || '?' }}
          </div>
          <div class="action-info">
            <div class="action-name">{{ action.name }}</div>
            <div class="action-type">{{ getActionTypeInfo(action.type)?.label }}</div>
          </div>
          <label class="toggle-switch">
            <input
              type="checkbox"
              :checked="action.enabled"
              @change="toggleActionEnabled(action)"
            />
            <span class="slider"></span>
          </label>
        </div>

        <div v-if="action.description" class="action-description">
          {{ action.description }}
        </div>

        <!-- Type-specific details -->
        <div class="action-details">
          <template v-if="action.type === 'set_output_safe' && action.outputChannels?.length">
            <div class="detail-row">
              <span class="detail-label">Channels:</span>
              <span class="detail-value">
                {{ action.outputChannels.join(', ') }}
              </span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Safe Value:</span>
              <span class="detail-value">
                DO: {{ action.safeValue ?? 0 }}, AO: {{ action.analogSafeValue ?? 0 }}
              </span>
            </div>
          </template>

          <template v-if="action.type === 'run_sequence' && action.sequenceId">
            <div class="detail-row">
              <span class="detail-label">Sequence:</span>
              <span class="detail-value">{{ action.sequenceId }}</span>
            </div>
          </template>

          <template v-if="action.type === 'custom' && action.mqttTopic">
            <div class="detail-row">
              <span class="detail-label">Topic:</span>
              <span class="detail-value">{{ action.mqttTopic }}</span>
            </div>
          </template>

          <div class="detail-row last-triggered">
            <span class="detail-label">Last triggered:</span>
            <span class="detail-value">{{ formatLastTriggered(action) }}</span>
          </div>
        </div>

        <div class="action-actions">
          <button class="btn btn-xs btn-secondary" @click="openEditModal(action)">
            Edit
          </button>
          <button class="btn btn-xs btn-warning" @click="testAction(action)">
            Test
          </button>
          <button class="btn btn-xs btn-danger" @click="deleteAction(action.id)">
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal-container">
        <div class="modal-header">
          <h3>{{ editingAction ? 'Edit' : 'Create' }} Safety Action</h3>
          <button class="close-btn" @click="showModal = false">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div class="modal-body">
          <!-- Name -->
          <div class="form-row">
            <label class="form-label">Name</label>
            <input
              type="text"
              v-model="formData.name"
              class="form-input"
              placeholder="e.g., Emergency Stop"
            />
          </div>

          <!-- Description -->
          <div class="form-row">
            <label class="form-label">Description</label>
            <textarea
              v-model="formData.description"
              class="form-input textarea"
              placeholder="Optional description..."
              rows="2"
            ></textarea>
          </div>

          <!-- Action Type -->
          <div class="form-row">
            <label class="form-label">Action Type</label>
            <div class="action-type-options">
              <label
                v-for="opt in actionTypes"
                :key="opt.value"
                class="action-type-option"
                :class="{ selected: formData.type === opt.value }"
              >
                <input
                  type="radio"
                  :value="opt.value"
                  v-model="formData.type"
                />
                <div class="option-content">
                  <span class="option-icon">{{ opt.icon }}</span>
                  <div class="option-text">
                    <span class="option-label">{{ opt.label }}</span>
                    <span class="option-desc">{{ opt.description }}</span>
                  </div>
                </div>
              </label>
            </div>
          </div>

          <!-- Type-specific options -->

          <!-- Set Output Safe: Channel Selection -->
          <template v-if="formData.type === 'set_output_safe'">
            <div class="form-row">
              <label class="form-label">Output Channels</label>
              <div class="channel-select-grid">
                <label
                  v-for="ch in allOutputChannels"
                  :key="ch.name"
                  class="channel-option"
                  :class="{
                    selected: isChannelSelected(ch.name),
                    'is-do': ch.type === 'digital_output',
                    'is-ao': ch.type === 'analog_output'
                  }"
                  @click="toggleChannel(ch.name)"
                >
                  <span class="ch-type">{{ ch.type === 'digital_output' ? 'DO' : 'AO' }}</span>
                  <span class="ch-name">{{ ch.name }}</span>
                </label>
              </div>
            </div>

            <div class="form-row inline-row">
              <div class="inline-field">
                <label class="form-label">Digital Safe Value</label>
                <select v-model.number="formData.safeValue" class="form-select small">
                  <option :value="0">OFF (0)</option>
                  <option :value="1">ON (1)</option>
                </select>
              </div>
              <div class="inline-field">
                <label class="form-label">Analog Safe Value</label>
                <input
                  type="number"
                  v-model.number="formData.analogSafeValue"
                  class="form-input small"
                  step="0.1"
                />
              </div>
            </div>
          </template>

          <!-- Run Sequence: Sequence Selection -->
          <template v-if="formData.type === 'run_sequence'">
            <div class="form-row">
              <label class="form-label">Sequence Script</label>
              <select v-model="formData.sequenceId" class="form-select">
                <option value="">Select a sequence...</option>
                <option v-for="seq in availableSequences" :key="seq" :value="seq">
                  {{ seq }}
                </option>
              </select>
            </div>
          </template>

          <!-- Custom Action: MQTT Topic/Payload -->
          <template v-if="formData.type === 'custom'">
            <div class="form-row">
              <label class="form-label">MQTT Topic</label>
              <input
                type="text"
                v-model="formData.mqttTopic"
                class="form-input"
                placeholder="e.g., nisystem/command/custom"
              />
            </div>
            <div class="form-row">
              <label class="form-label">Payload (JSON)</label>
              <textarea
                v-model="formData.mqttPayload"
                class="form-input textarea code"
                placeholder='{"action": "custom"}'
                rows="3"
              ></textarea>
            </div>
          </template>

          <!-- Enabled -->
          <div class="form-row enable-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="formData.enabled" />
              <span>Enabled</span>
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showModal = false">Cancel</button>
          <button class="btn btn-primary" @click="saveAction" :disabled="!formData.name.trim()">
            {{ editingAction ? 'Update' : 'Create' }} Action
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.safety-actions-panel {
  background: #1a1a2e;
  border-radius: 8px;
  border: 1px solid #3a3a5a;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #0d0d1a;
  border-bottom: 1px solid #3a3a5a;
}

.panel-header h4 {
  margin: 0;
  font-size: 0.95rem;
  color: #fff;
}

.actions-list {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 400px;
  overflow-y: auto;
}

.empty-state {
  text-align: center;
  padding: 24px;
  color: #666;
}

.empty-state .hint {
  font-size: 0.8rem;
  margin-top: 4px;
}

/* Action Card */
.action-card {
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 6px;
  padding: 12px;
  transition: all 0.2s;
}

.action-card.disabled {
  opacity: 0.5;
}

.action-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.action-icon {
  width: 36px;
  height: 36px;
  background: rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #60a5fa;
  font-family: 'JetBrains Mono', monospace;
}

.action-info {
  flex: 1;
}

.action-name {
  font-weight: 500;
  color: #fff;
}

.action-type {
  font-size: 0.75rem;
  color: #888;
}

.action-description {
  margin-top: 8px;
  font-size: 0.8rem;
  color: #888;
}

.action-details {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #2a2a4a;
}

.detail-row {
  display: flex;
  gap: 8px;
  font-size: 0.8rem;
  margin-bottom: 4px;
}

.detail-label {
  color: #666;
}

.detail-value {
  color: #aaa;
  font-family: 'JetBrains Mono', monospace;
}

.last-triggered {
  margin-top: 8px;
  font-size: 0.75rem;
  color: #555;
}

.action-actions {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch .slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: #3a3a5a;
  border-radius: 20px;
  transition: 0.2s;
}

.toggle-switch .slider::before {
  content: '';
  position: absolute;
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background: #fff;
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .slider {
  background: #22c55e;
}

.toggle-switch input:checked + .slider::before {
  transform: translateX(16px);
}

/* Buttons */
.btn {
  padding: 8px 16px;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 0.8rem;
}

.btn-xs {
  padding: 4px 8px;
  font-size: 0.75rem;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: #3a3a5a;
  color: #ddd;
}

.btn-secondary:hover {
  background: #4a4a6a;
}

.btn-warning {
  background: #f59e0b;
  color: #000;
}

.btn-warning:hover {
  background: #d97706;
}

.btn-danger {
  background: #dc2626;
  color: #fff;
}

.btn-danger:hover {
  background: #b91c1c;
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
  padding: 20px;
}

.modal-container {
  background: #1a1a2e;
  border-radius: 8px;
  border: 1px solid #3a3a5a;
  width: 100%;
  max-width: 550px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #3a3a5a;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #fff;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 4px;
  display: flex;
  border-radius: 4px;
}

.close-btn:hover {
  color: #fff;
  background: #3a3a5a;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #3a3a5a;
}

/* Form Elements */
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row.inline-row {
  flex-direction: row;
  gap: 16px;
}

.inline-field {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row.enable-row {
  flex-direction: row;
  align-items: center;
}

.form-label {
  font-size: 0.85rem;
  color: #aaa;
}

.form-input {
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
  padding: 8px 12px;
  color: #fff;
  font-size: 0.9rem;
}

.form-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.form-input.small {
  max-width: 120px;
}

.form-input.textarea {
  resize: vertical;
  min-height: 60px;
}

.form-input.code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
}

.form-select {
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
  padding: 8px 12px;
  color: #fff;
  font-size: 0.9rem;
}

.form-select.small {
  max-width: 120px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #ddd;
}

.checkbox-label input {
  width: 16px;
  height: 16px;
}

/* Action Type Options */
.action-type-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-type-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-type-option input {
  display: none;
}

.action-type-option:hover {
  border-color: #555;
}

.action-type-option.selected {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.option-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.option-icon {
  width: 28px;
  height: 28px;
  background: #2a2a4a;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.8rem;
  color: #60a5fa;
  font-family: 'JetBrains Mono', monospace;
}

.option-text {
  display: flex;
  flex-direction: column;
}

.option-label {
  font-size: 0.9rem;
  color: #fff;
}

.option-desc {
  font-size: 0.75rem;
  color: #666;
}

/* Channel Select Grid */
.channel-select-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 150px;
  overflow-y: auto;
  padding: 4px;
}

.channel-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: all 0.2s;
}

.channel-option:hover {
  border-color: #555;
}

.channel-option.selected {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.channel-option .ch-type {
  font-size: 0.65rem;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: 600;
}

.channel-option.is-do .ch-type {
  background: rgba(34, 197, 94, 0.2);
  color: #4ade80;
}

.channel-option.is-ao .ch-type {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}

.channel-option .ch-name {
  color: #ddd;
  font-family: 'JetBrains Mono', monospace;
}

/* Scrollbar */
.actions-list::-webkit-scrollbar,
.channel-select-grid::-webkit-scrollbar {
  width: 6px;
}

.actions-list::-webkit-scrollbar-track,
.channel-select-grid::-webkit-scrollbar-track {
  background: #0d0d1a;
}

.actions-list::-webkit-scrollbar-thumb,
.channel-select-grid::-webkit-scrollbar-thumb {
  background: #3a3a5a;
  border-radius: 3px;
}
</style>
