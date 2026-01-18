<script setup lang="ts">
/**
 * Correlation Rule Modal
 *
 * Creates/edits correlation rules for alarm root cause analysis.
 * Rules define which alarms should be grouped together when they
 * trigger within a time window.
 */
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import type { CorrelationRule } from '../types'

const props = defineProps<{
  visible: boolean
  rule?: CorrelationRule | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', rule: Omit<CorrelationRule, 'id'>): void
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const soe = mqtt.soe

// Form state
const formData = ref({
  name: '',
  description: '',
  triggerAlarmChannel: '',
  relatedAlarmChannels: [] as string[],
  timeWindowMs: 1000,
  rootCauseHint: '',
  enabled: true
})

// All channels that have alarm configs enabled
const alarmChannels = computed(() => {
  return Object.entries(store.channels)
    .filter(([_, cfg]) => cfg.alarm_enabled !== false)
    .map(([name, cfg]) => ({
      name,
      group: cfg.group,
      type: cfg.channel_type
    }))
})

// Available channels for related alarms (exclude trigger)
const availableRelatedChannels = computed(() => {
  return alarmChannels.value.filter(ch => ch.name !== formData.value.triggerAlarmChannel)
})

// Root cause hint options (selected related channels + trigger)
const rootCauseOptions = computed(() => {
  const options = [formData.value.triggerAlarmChannel, ...formData.value.relatedAlarmChannels]
  return options.filter(ch => ch)
})

// Watch for prop changes to populate form
watch(() => [props.visible, props.rule] as const, ([visible, rule]) => {
  if (visible) {
    if (rule) {
      // Editing existing rule
      formData.value = {
        name: rule.name,
        description: rule.description || '',
        triggerAlarmChannel: rule.triggerAlarm || '',
        relatedAlarmChannels: rule.relatedAlarms ? [...rule.relatedAlarms] : [],
        timeWindowMs: rule.timeWindowMs || 1000,
        rootCauseHint: rule.rootCauseHint || '',
        enabled: rule.enabled !== false
      }
    } else {
      // Creating new rule
      formData.value = {
        name: '',
        description: '',
        triggerAlarmChannel: '',
        relatedAlarmChannels: [],
        timeWindowMs: 1000,
        rootCauseHint: '',
        enabled: true
      }
    }
  }
}, { immediate: true })

function toggleRelatedChannel(channel: string) {
  const idx = formData.value.relatedAlarmChannels.indexOf(channel)
  if (idx >= 0) {
    formData.value.relatedAlarmChannels.splice(idx, 1)
    // Clear root cause hint if it was this channel
    if (formData.value.rootCauseHint === channel) {
      formData.value.rootCauseHint = ''
    }
  } else {
    formData.value.relatedAlarmChannels.push(channel)
  }
}

function isRelatedSelected(channel: string): boolean {
  return formData.value.relatedAlarmChannels.includes(channel)
}

function handleSave() {
  if (!formData.value.name.trim()) return
  if (!formData.value.triggerAlarmChannel) return
  if (formData.value.relatedAlarmChannels.length === 0) return

  emit('save', {
    name: formData.value.name,
    description: formData.value.description,
    triggerAlarm: formData.value.triggerAlarmChannel,
    relatedAlarms: formData.value.relatedAlarmChannels,
    timeWindowMs: formData.value.timeWindowMs,
    rootCauseHint: formData.value.rootCauseHint || undefined,
    enabled: formData.value.enabled
  })
  emit('close')
}

function handleClose() {
  emit('close')
}

// Validation
const isValid = computed(() => {
  return formData.value.name.trim() &&
         formData.value.triggerAlarmChannel &&
         formData.value.relatedAlarmChannels.length > 0
})
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="handleClose">
    <div class="modal-container">
      <!-- Header -->
      <div class="modal-header">
        <h3>
          <span class="header-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
            </svg>
          </span>
          {{ rule ? 'Edit' : 'Create' }} Correlation Rule
        </h3>
        <button class="close-btn" @click="handleClose">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="modal-body">
        <!-- Name -->
        <div class="form-row">
          <label class="form-label">Rule Name <span class="required">*</span></label>
          <input
            type="text"
            v-model="formData.name"
            class="form-input"
            placeholder="e.g., Pump Failure Cascade"
          />
        </div>

        <!-- Description -->
        <div class="form-row">
          <label class="form-label">Description</label>
          <textarea
            v-model="formData.description"
            class="form-input textarea"
            placeholder="Optional description of what this correlation detects..."
            rows="2"
          ></textarea>
        </div>

        <!-- Trigger Alarm -->
        <div class="form-row">
          <label class="form-label">
            Trigger Alarm <span class="required">*</span>
            <span class="form-hint inline">The primary alarm that starts correlation detection</span>
          </label>
          <select v-model="formData.triggerAlarmChannel" class="form-select">
            <option value="">Select trigger alarm...</option>
            <option v-for="ch in alarmChannels" :key="ch.name" :value="ch.name">
              {{ ch.name }}
              <template v-if="ch.group"> ({{ ch.group }})</template>
            </option>
          </select>
        </div>

        <!-- Related Alarms -->
        <div class="form-row">
          <label class="form-label">
            Related Alarms <span class="required">*</span>
            <span class="form-hint inline">Alarms that typically occur with the trigger</span>
          </label>
          <div class="channel-select-grid">
            <label
              v-for="ch in availableRelatedChannels"
              :key="ch.name"
              class="channel-option"
              :class="{ selected: isRelatedSelected(ch.name) }"
              @click="toggleRelatedChannel(ch.name)"
            >
              <span class="ch-name">{{ ch.name }}</span>
              <span v-if="ch.group" class="ch-group">{{ ch.group }}</span>
            </label>
          </div>
          <span v-if="formData.relatedAlarmChannels.length > 0" class="selected-count">
            {{ formData.relatedAlarmChannels.length }} selected
          </span>
        </div>

        <!-- Time Window -->
        <div class="form-row">
          <label class="form-label">
            Time Window
            <span class="form-hint inline">How close alarms must occur to be correlated</span>
          </label>
          <div class="input-with-unit">
            <input
              type="number"
              v-model.number="formData.timeWindowMs"
              class="form-input"
              min="100"
              step="100"
            />
            <span class="unit">ms</span>
          </div>
          <span class="form-hint">Default: 1000ms (1 second)</span>
        </div>

        <!-- Root Cause Hint -->
        <div class="form-row" v-if="rootCauseOptions.length > 0">
          <label class="form-label">
            Root Cause Hint
            <span class="form-hint inline">Which alarm is typically the root cause?</span>
          </label>
          <select v-model="formData.rootCauseHint" class="form-select">
            <option value="">Auto-detect (first alarm)</option>
            <option v-for="ch in rootCauseOptions" :key="ch" :value="ch">
              {{ ch }}
            </option>
          </select>
        </div>

        <!-- Enabled -->
        <div class="form-row enable-row">
          <label class="checkbox-label">
            <input type="checkbox" v-model="formData.enabled" />
            <span>Rule Enabled</span>
          </label>
        </div>
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="handleClose">Cancel</button>
        <button class="btn btn-primary" @click="handleSave" :disabled="!isValid">
          {{ rule ? 'Update' : 'Create' }} Rule
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
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
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #3a3a5a;
}

.modal-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 1.1rem;
  color: #fff;
}

.header-icon {
  color: #60a5fa;
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

.form-row.enable-row {
  flex-direction: row;
  align-items: center;
}

.form-label {
  font-size: 0.85rem;
  color: #aaa;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.required {
  color: #f87171;
}

.form-hint {
  font-size: 0.75rem;
  color: #666;
}

.form-hint.inline {
  font-weight: normal;
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

.form-input.textarea {
  resize: vertical;
  min-height: 60px;
}

.form-select {
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
  padding: 8px 12px;
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
}

.form-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.input-with-unit {
  display: flex;
  align-items: center;
  gap: 8px;
}

.input-with-unit .form-input {
  flex: 1;
  max-width: 150px;
}

.input-with-unit .unit {
  color: #888;
  font-size: 0.85rem;
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
  cursor: pointer;
}

/* Channel Select Grid */
.channel-select-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
  padding: 4px;
  background: #0d0d1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
}

.channel-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 10px;
  background: #1a1a2e;
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

.channel-option .ch-name {
  color: #ddd;
  font-family: 'JetBrains Mono', monospace;
}

.channel-option .ch-group {
  font-size: 0.65rem;
  color: #666;
}

.selected-count {
  font-size: 0.75rem;
  color: #60a5fa;
}

/* Buttons */
.btn {
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.btn-secondary {
  background: #3a3a5a;
  color: #ddd;
}

.btn-secondary:hover {
  background: #4a4a6a;
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

/* Scrollbar */
.channel-select-grid::-webkit-scrollbar {
  width: 6px;
}

.channel-select-grid::-webkit-scrollbar-track {
  background: #0d0d1a;
}

.channel-select-grid::-webkit-scrollbar-thumb {
  background: #3a3a5a;
  border-radius: 3px;
}
</style>
