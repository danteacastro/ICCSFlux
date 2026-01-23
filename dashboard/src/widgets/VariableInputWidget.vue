<script setup lang="ts">
/**
 * Variable Input Widget
 *
 * Allows operators to input values for user variables (constants, manual values)
 * directly from the dashboard. Useful for script parameters, setpoints, etc.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  widgetId: string
  label?: string
  variableId?: string       // Specific variable to show (single mode)
  variableIds?: string[]    // Multiple variables to show (list mode)
  showAllManual?: boolean   // Show all manual/constant variables
  compact?: boolean         // Compact layout
  style?: WidgetStyle
}>()

const mqtt = useMqtt('nisystem')
const store = useDashboardStore()

// Local state
interface UserVariable {
  id: string
  name: string
  displayName: string
  variableType: string
  value: number
  units: string
  description?: string
}

const variables = ref<UserVariable[]>([])
const editingVar = ref<string | null>(null)
const inputValues = ref<Record<string, string>>({})
const isLoading = ref(false)

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

// Filter variables based on props
const displayVariables = computed(() => {
  if (props.variableId) {
    // Single variable mode
    return variables.value.filter(v => v.id === props.variableId)
  }
  if (props.variableIds?.length) {
    // Multiple specific variables
    return variables.value.filter(v => props.variableIds!.includes(v.id))
  }
  if (props.showAllManual) {
    // Show all manual/constant types
    return variables.value.filter(v =>
      v.variableType === 'manual' || v.variableType === 'constant'
    )
  }
  // Default: show all editable types
  return variables.value.filter(v =>
    ['manual', 'constant'].includes(v.variableType)
  )
})

const displayLabel = computed(() => props.label || 'Variables')

// Subscribe to variable updates - track unsubscribe functions
let unsubscribeConfig: (() => void) | null = null
let unsubscribeValues: (() => void) | null = null

onMounted(() => {
  // Subscribe to variable config
  unsubscribeConfig = mqtt.subscribe('nisystem/status/user_variables/config', (data: { variables?: UserVariable[] }) => {
    if (data.variables) {
      variables.value = data.variables
      // Initialize input values
      for (const v of data.variables) {
        if (inputValues.value[v.id] === undefined) {
          inputValues.value[v.id] = String(v.value)
        }
      }
    }
  })

  // Subscribe to variable values
  unsubscribeValues = mqtt.subscribe('nisystem/status/user_variables/values', (data: Record<string, number>) => {
    for (const [id, value] of Object.entries(data)) {
      const variable = variables.value.find(v => v.id === id)
      if (variable) {
        variable.value = value
        // Update input if not currently editing
        if (editingVar.value !== id) {
          inputValues.value[id] = String(value)
        }
      }
    }
  })

  // Request initial data
  mqtt.sendCommand('variables/list', {})
})

onUnmounted(() => {
  if (unsubscribeConfig) {
    unsubscribeConfig()
  }
  if (unsubscribeValues) {
    unsubscribeValues()
  }
})

function startEdit(varId: string) {
  editingVar.value = varId
  const variable = variables.value.find(v => v.id === varId)
  if (variable) {
    inputValues.value[varId] = String(variable.value)
  }
}

function cancelEdit() {
  if (editingVar.value) {
    const variable = variables.value.find(v => v.id === editingVar.value)
    if (variable) {
      inputValues.value[editingVar.value] = String(variable.value)
    }
  }
  editingVar.value = null
}

function submitValue(varId: string) {
  const inputVal = inputValues.value[varId] ?? ''
  const numValue = parseFloat(inputVal)

  if (isNaN(numValue)) {
    // Reset to current value
    const variable = variables.value.find(v => v.id === varId)
    if (variable) {
      inputValues.value[varId] = String(variable.value)
    }
    editingVar.value = null
    return
  }

  // Send to backend
  mqtt.sendCommand('variables/set', {
    id: varId,
    value: numValue
  })

  editingVar.value = null
}

function handleKeydown(event: KeyboardEvent, varId: string) {
  if (event.key === 'Enter') {
    submitValue(varId)
  } else if (event.key === 'Escape') {
    cancelEdit()
  }
}

function formatValue(value: number, units?: string): string {
  const formatted = Number.isInteger(value) ? value.toString() : value.toFixed(3)
  return units ? `${formatted} ${units}` : formatted
}
</script>

<template>
  <div class="variable-input-widget" :class="{ compact }" :style="containerStyle">
    <div class="header">
      <span class="title">{{ displayLabel }}</span>
      <span class="count">({{ displayVariables.length }})</span>
    </div>

    <div class="variables-list" v-if="displayVariables.length > 0">
      <div
        v-for="variable in displayVariables"
        :key="variable.id"
        class="variable-row"
        :class="{ editing: editingVar === variable.id }"
      >
        <div class="var-info">
          <span class="var-name">{{ variable.displayName || variable.name }}</span>
          <span v-if="variable.units" class="var-units">({{ variable.units }})</span>
        </div>

        <!-- Display mode -->
        <div v-if="editingVar !== variable.id" class="var-value" @click="startEdit(variable.id)">
          <span class="value-text">{{ formatValue(variable.value, variable.units) }}</span>
          <span class="edit-hint">click to edit</span>
        </div>

        <!-- Edit mode -->
        <div v-else class="var-edit">
          <input
            type="number"
            v-model="inputValues[variable.id]"
            @keydown="handleKeydown($event, variable.id)"
            @blur="submitValue(variable.id)"
            ref="inputRef"
            autofocus
          />
          <div class="edit-buttons">
            <button class="btn-ok" @click="submitValue(variable.id)" title="Apply">OK</button>
            <button class="btn-cancel" @click="cancelEdit" title="Cancel">X</button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <span>No variables configured</span>
      <span class="hint">Add manual/constant variables in Variables tab</span>
    </div>
  </div>
</template>

<style scoped>
.variable-input-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
}

.title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.count {
  font-size: 0.65rem;
  color: #6b7280;
}

.variables-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.variable-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 4px;
  transition: background 0.15s;
}

.variable-row:hover {
  background: rgba(255, 255, 255, 0.06);
}

.variable-row.editing {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.var-info {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.var-name {
  font-size: 0.8rem;
  color: #e5e7eb;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.var-units {
  font-size: 0.65rem;
  color: #6b7280;
}

.var-value {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  transition: background 0.15s;
}

.var-value:hover {
  background: rgba(255, 255, 255, 0.1);
}

.var-value:hover .edit-hint {
  opacity: 1;
}

.value-text {
  font-size: 0.85rem;
  font-weight: 600;
  color: #60a5fa;
  font-family: 'JetBrains Mono', monospace;
}

.edit-hint {
  font-size: 0.55rem;
  color: #6b7280;
  opacity: 0;
  transition: opacity 0.15s;
}

.var-edit {
  display: flex;
  align-items: center;
  gap: 4px;
}

.var-edit input {
  width: 80px;
  padding: 4px 6px;
  background: #1f2937;
  border: 1px solid #3b82f6;
  border-radius: 3px;
  color: #fff;
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', monospace;
  text-align: right;
}

.var-edit input:focus {
  outline: none;
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.edit-buttons {
  display: flex;
  gap: 2px;
}

.btn-ok,
.btn-cancel {
  padding: 3px 6px;
  border: none;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-ok {
  background: #22c55e;
  color: #fff;
}

.btn-ok:hover {
  background: #16a34a;
}

.btn-cancel {
  background: #6b7280;
  color: #fff;
}

.btn-cancel:hover {
  background: #4b5563;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #6b7280;
  font-size: 0.75rem;
}

.empty-state .hint {
  font-size: 0.65rem;
  color: #4b5563;
}

/* Compact mode */
.compact .header {
  margin-bottom: 4px;
  padding-bottom: 4px;
}

.compact .variable-row {
  padding: 4px 6px;
}

.compact .var-name {
  font-size: 0.7rem;
}

.compact .value-text {
  font-size: 0.75rem;
}
</style>
