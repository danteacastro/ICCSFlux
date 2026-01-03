<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as monaco from 'monaco-editor'
import { usePythonScripts } from '../composables/usePythonScripts'
import { useDashboardStore } from '../stores/dashboard'
import type { PythonScript, ScriptOutput } from '../types/python-scripts'
import { SCRIPT_TEMPLATES } from '../types/python-scripts'

const store = useDashboardStore()
const pythonScripts = usePythonScripts()

// =============================================================================
// STATE
// =============================================================================

const selectedScriptId = ref<string | null>(null)
const showNewScriptModal = ref(false)
const showTemplatesModal = ref(false)
const newScriptName = ref('')
const newScriptDescription = ref('')

// Editor
const editorContainer = ref<HTMLDivElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

// Dirty state (unsaved changes)
const isDirty = ref(false)
const lastSavedCode = ref('')

// Validation state
const validationErrors = ref<Array<{
  line: number
  column: number
  message: string
  type: 'error' | 'warning'
}>>([])
const isValidating = ref(false)

// =============================================================================
// COMPUTED
// =============================================================================

const selectedScript = computed(() =>
  selectedScriptId.value ? pythonScripts.scripts.value[selectedScriptId.value] : null
)

const isScriptRunning = computed(() =>
  selectedScriptId.value ? pythonScripts.runningScripts.value.has(selectedScriptId.value) : false
)

const currentScriptOutputs = computed(() =>
  selectedScriptId.value ? (pythonScripts.scriptOutputs.value[selectedScriptId.value] || []) : []
)

const channelNames = computed(() => Object.keys(store.values || {}))

// =============================================================================
// EDITOR SETUP
// =============================================================================

onMounted(() => {
  setupEditor()
  registerPythonLanguage()
})

onUnmounted(() => {
  editor?.dispose()
})

function setupEditor() {
  if (!editorContainer.value) return

  editor = monaco.editor.create(editorContainer.value, {
    value: '',
    language: 'python',
    theme: 'vs-dark',
    minimap: { enabled: false },
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Consolas', 'Monaco', monospace",
    lineNumbers: 'on',
    automaticLayout: true,
    wordWrap: 'on',
    tabSize: 4,
    scrollBeyondLastLine: false,
    suggest: {
      showKeywords: true,
      showVariables: true,
      showFunctions: true,
    },
    quickSuggestions: true,
  })

  // Track changes
  editor.onDidChangeModelContent(() => {
    if (selectedScript.value && editor) {
      const currentCode = editor.getValue()
      isDirty.value = currentCode !== lastSavedCode.value
    }
  })
}

function registerPythonLanguage() {
  // Register autocomplete provider for Python
  monaco.languages.registerCompletionItemProvider('python', {
    provideCompletionItems: (model, position) => {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn
      }

      const suggestions: monaco.languages.CompletionItem[] = []

      // Channel names (tags.*)
      for (const ch of channelNames.value) {
        suggestions.push({
          label: `tags.${ch}`,
          kind: monaco.languages.CompletionItemKind.Variable,
          insertText: `tags.${ch}`,
          detail: 'Channel value',
          documentation: `Read current value of ${ch}`,
          range
        })
      }

      // NISystem API functions
      const apiFuncs = [
        { name: 'publish', snippet: "publish('$1', $2, units='$3')", doc: 'Publish computed value' },
        { name: 'next_scan', snippet: 'await next_scan()', doc: 'Wait for next cDAQ scan cycle' },
        { name: 'wait_for', snippet: 'await wait_for($1)', doc: 'Wait for N seconds' },
        { name: 'wait_until', snippet: 'await wait_until(lambda: $1, timeout=$2)', doc: 'Wait until condition is true' },
        { name: 'outputs.set', snippet: "outputs.set('$1', $2)", doc: 'Set output value' },
      ]

      for (const fn of apiFuncs) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'NISystem API',
          documentation: fn.doc,
          range
        })
      }

      // Conversion functions
      const convFuncs = [
        { name: 'F_to_C', doc: 'Fahrenheit to Celsius' },
        { name: 'C_to_F', doc: 'Celsius to Fahrenheit' },
        { name: 'GPM_to_LPM', doc: 'Gallons/min to Liters/min' },
        { name: 'LPM_to_GPM', doc: 'Liters/min to Gallons/min' },
        { name: 'PSI_to_bar', doc: 'PSI to bar' },
        { name: 'bar_to_PSI', doc: 'bar to PSI' },
        { name: 'gal_to_L', doc: 'Gallons to Liters' },
        { name: 'L_to_gal', doc: 'Liters to Gallons' },
      ]

      for (const fn of convFuncs) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: fn.name + '($0)',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Unit conversion',
          documentation: fn.doc,
          range
        })
      }

      // Helper classes
      const helpers = [
        { name: 'RateCalculator', snippet: 'RateCalculator(window_seconds=$1)', doc: 'Calculate rate of change' },
        { name: 'Accumulator', snippet: 'Accumulator(initial=$1)', doc: 'Accumulate incremental changes' },
        { name: 'EdgeDetector', snippet: 'EdgeDetector(threshold=$1)', doc: 'Detect rising/falling edges' },
        { name: 'RollingStats', snippet: 'RollingStats(window_size=$1)', doc: 'Rolling statistics (mean, min, max, std)' },
      ]

      for (const h of helpers) {
        suggestions.push({
          label: h.name,
          kind: monaco.languages.CompletionItemKind.Class,
          insertText: h.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Helper class',
          documentation: h.doc,
          range
        })
      }

      // Built-in globals
      suggestions.push({
        label: 'session.active',
        kind: monaco.languages.CompletionItemKind.Property,
        insertText: 'session.active',
        detail: 'Session state',
        documentation: 'True if test session is active',
        range
      })

      suggestions.push({
        label: 'session.elapsed',
        kind: monaco.languages.CompletionItemKind.Property,
        insertText: 'session.elapsed',
        detail: 'Session state',
        documentation: 'Seconds since session started',
        range
      })

      return { suggestions }
    }
  })
}

// =============================================================================
// SCRIPT SELECTION
// =============================================================================

watch(selectedScriptId, (id) => {
  if (id && pythonScripts.scripts.value[id] && editor) {
    const script = pythonScripts.scripts.value[id]
    editor.setValue(script.code)
    lastSavedCode.value = script.code
    isDirty.value = false
  }
})

function selectScript(id: string) {
  // Check for unsaved changes
  if (isDirty.value && selectedScriptId.value) {
    if (!confirm('You have unsaved changes. Discard them?')) {
      return
    }
  }
  selectedScriptId.value = id
}

// =============================================================================
// SCRIPT CRUD
// =============================================================================

function openNewScriptModal() {
  newScriptName.value = ''
  newScriptDescription.value = ''
  showNewScriptModal.value = true
}

function createNewScript() {
  if (!newScriptName.value.trim()) return

  const script = pythonScripts.createScript(
    newScriptName.value.trim(),
    newScriptDescription.value.trim()
  )

  showNewScriptModal.value = false
  selectedScriptId.value = script.id
}

function createFromTemplate(templateId: string) {
  const template = SCRIPT_TEMPLATES.find(t => t.id === templateId)
  if (!template) return

  const script = pythonScripts.createScript(template.name, template.description)
  pythonScripts.updateScript(script.id, { code: template.code })

  showTemplatesModal.value = false
  selectedScriptId.value = script.id

  // Update editor
  if (editor) {
    editor.setValue(template.code)
    lastSavedCode.value = template.code
    isDirty.value = false
  }
}

function saveScript() {
  if (!selectedScriptId.value || !editor) return

  const code = editor.getValue()
  pythonScripts.updateScript(selectedScriptId.value, { code })
  lastSavedCode.value = code
  isDirty.value = false
}

function deleteScript() {
  if (!selectedScriptId.value) return

  if (!confirm('Delete this script? This cannot be undone.')) {
    return
  }

  pythonScripts.deleteScript(selectedScriptId.value)
  selectedScriptId.value = null

  if (editor) {
    editor.setValue('')
  }
}

// =============================================================================
// SCRIPT EXECUTION
// =============================================================================

async function toggleScript() {
  if (!selectedScriptId.value) return

  if (isScriptRunning.value) {
    pythonScripts.stopScript(selectedScriptId.value)
  } else {
    // Save before running
    if (isDirty.value) {
      saveScript()
    }

    // Validate before running
    const code = editor?.getValue() || ''
    const result = await pythonScripts.validateScript(code)
    validationErrors.value = result.errors

    if (!result.valid) {
      // Show validation errors but allow running with warnings
      const hasErrors = result.errors.some(e => e.type === 'error')
      if (hasErrors) {
        return // Don't run if there are errors
      }
    }

    await pythonScripts.startScript(selectedScriptId.value)
  }
}

async function validateScript() {
  if (!editor) return

  isValidating.value = true
  validationErrors.value = []

  try {
    const code = editor.getValue()
    const result = await pythonScripts.validateScript(code)
    validationErrors.value = result.errors

    // Add markers to Monaco editor
    const model = editor.getModel()
    if (model) {
      const markers = result.errors.map(err => ({
        severity: err.type === 'error'
          ? monaco.MarkerSeverity.Error
          : monaco.MarkerSeverity.Warning,
        message: err.message,
        startLineNumber: err.line,
        startColumn: err.column || 1,
        endLineNumber: err.line,
        endColumn: err.column ? err.column + 10 : 100
      }))
      monaco.editor.setModelMarkers(model, 'python-validation', markers)
    }
  } finally {
    isValidating.value = false
  }
}

function updateRunMode(event: Event) {
  if (!selectedScriptId.value) return
  const target = event.target as HTMLSelectElement
  const mode = target.value as 'manual' | 'acquisition' | 'session'
  pythonScripts.setRunMode(selectedScriptId.value, mode)
}

function clearConsole() {
  if (selectedScriptId.value) {
    pythonScripts.clearScriptOutput(selectedScriptId.value)
  }
}

// =============================================================================
// HELPERS
// =============================================================================

function formatTimestamp(ts: number): string {
  const date = new Date(ts)
  return date.toLocaleTimeString('en-US', { hour12: false })
}

function getOutputTypeClass(type: string): string {
  switch (type) {
    case 'error': return 'output-error'
    case 'warning': return 'output-warning'
    case 'info': return 'output-info'
    default: return 'output-stdout'
  }
}

function getScriptStateIcon(id: string): string {
  if (pythonScripts.runningScripts.value.has(id)) return '▶'
  const status = pythonScripts.scriptStatuses.value[id]
  if (status?.state === 'error') return '✕'
  return '○'
}

function getScriptStateClass(id: string): string {
  if (pythonScripts.runningScripts.value.has(id)) return 'state-running'
  const status = pythonScripts.scriptStatuses.value[id]
  if (status?.state === 'error') return 'state-error'
  return 'state-idle'
}
</script>

<template>
  <div class="python-scripts-container">
    <!-- SIDEBAR: Script List -->
    <div class="scripts-sidebar">
      <div class="sidebar-header">
        <h3>Scripts</h3>
        <div class="sidebar-actions">
          <button class="btn btn-sm btn-primary" @click="openNewScriptModal" title="New Script">
            +
          </button>
          <button class="btn btn-sm btn-secondary" @click="showTemplatesModal = true" title="Templates">
            📋
          </button>
        </div>
      </div>

      <div class="scripts-list">
        <div
          v-for="script in pythonScripts.scriptsList.value"
          :key="script.id"
          class="script-item"
          :class="{ selected: selectedScriptId === script.id }"
          @click="selectScript(script.id)"
        >
          <span class="script-state" :class="getScriptStateClass(script.id)">
            {{ getScriptStateIcon(script.id) }}
          </span>
          <span class="script-name">{{ script.name }}</span>
        </div>

        <div v-if="pythonScripts.scriptsList.value.length === 0" class="empty-state">
          No scripts yet.<br>
          Click + to create one.
        </div>
      </div>

      <!-- Published Values -->
      <div class="published-section" v-if="pythonScripts.publishedValuesList.value.length > 0">
        <h4>Published Values</h4>
        <div class="published-list">
          <div
            v-for="pv in pythonScripts.publishedValuesList.value"
            :key="pv.name"
            class="published-item"
          >
            <span class="pv-name">{{ pv.name }}</span>
            <span class="pv-value">{{ pv.value.toFixed(2) }}</span>
            <span class="pv-units">{{ pv.units }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- MAIN: Editor + Console -->
    <div class="editor-panel">
      <!-- Toolbar -->
      <div class="editor-toolbar" v-if="selectedScript">
        <div class="script-info">
          <span class="script-title">{{ selectedScript.name }}</span>
          <span v-if="isDirty" class="dirty-indicator">●</span>
        </div>
        <div class="toolbar-actions">
          <select
            class="run-mode-select"
            :value="selectedScript?.runMode || 'manual'"
            @change="updateRunMode"
            title="When this script should run"
          >
            <option value="manual">Manual</option>
            <option value="acquisition">Run with Acquisition</option>
            <option value="session">Run with Session</option>
          </select>
          <button
            class="btn btn-secondary"
            @click="validateScript"
            :disabled="pythonScripts.isPyodideLoading.value || isValidating"
          >
            {{ isValidating ? '...' : '✓ Validate' }}
          </button>
          <button
            class="btn"
            :class="isScriptRunning ? 'btn-danger' : 'btn-success'"
            @click="toggleScript"
            :disabled="pythonScripts.isPyodideLoading.value"
          >
            {{ isScriptRunning ? '■ Stop' : '▶ Run' }}
          </button>
          <button class="btn btn-secondary" @click="saveScript" :disabled="!isDirty">
            Save
          </button>
          <button class="btn btn-secondary btn-danger-text" @click="deleteScript">
            Delete
          </button>
        </div>
      </div>

      <!-- Validation Errors -->
      <div v-if="validationErrors.length > 0" class="validation-panel">
        <div class="validation-header">
          <span>{{ validationErrors.filter(e => e.type === 'error').length }} error(s), {{ validationErrors.filter(e => e.type === 'warning').length }} warning(s)</span>
          <button class="btn btn-sm btn-ghost" @click="validationErrors = []">×</button>
        </div>
        <div class="validation-errors">
          <div
            v-for="(err, idx) in validationErrors"
            :key="idx"
            class="validation-error"
            :class="err.type"
          >
            <span class="error-location">Line {{ err.line }}</span>
            <span class="error-message">{{ err.message }}</span>
          </div>
        </div>
      </div>

      <!-- Pyodide Loading Status -->
      <div v-if="pythonScripts.isPyodideLoading.value" class="pyodide-loading">
        <div class="loading-spinner"></div>
        <span>{{ pythonScripts.pyodideLoadMessage.value }}</span>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: pythonScripts.pyodideLoadProgress.value + '%' }"
          ></div>
        </div>
      </div>

      <!-- Editor -->
      <div class="editor-wrapper" v-show="selectedScript && !pythonScripts.isPyodideLoading.value">
        <div ref="editorContainer" class="monaco-container"></div>
      </div>

      <!-- Empty State -->
      <div v-if="!selectedScript" class="editor-empty">
        <p>Select a script from the sidebar or create a new one.</p>
      </div>

      <!-- Console -->
      <div class="console-panel" v-if="selectedScript">
        <div class="console-header">
          <span>Console</span>
          <button class="btn btn-sm btn-ghost" @click="clearConsole">Clear</button>
        </div>
        <div class="console-output">
          <div
            v-for="(output, idx) in currentScriptOutputs"
            :key="idx"
            class="console-line"
            :class="getOutputTypeClass(output.type)"
          >
            <span class="console-time">{{ formatTimestamp(output.timestamp) }}</span>
            <span class="console-type">[{{ output.type }}]</span>
            <span class="console-message">{{ output.message }}</span>
          </div>
          <div v-if="currentScriptOutputs.length === 0" class="console-empty">
            No output yet. Run the script to see output here.
          </div>
        </div>
      </div>
    </div>

    <!-- New Script Modal -->
    <Teleport to="body">
      <div v-if="showNewScriptModal" class="modal-overlay" @click.self="showNewScriptModal = false">
        <div class="modal">
          <h3>New Python Script</h3>
          <div class="form-group">
            <label>Name</label>
            <input
              v-model="newScriptName"
              type="text"
              placeholder="My Script"
              @keyup.enter="createNewScript"
            />
          </div>
          <div class="form-group">
            <label>Description (optional)</label>
            <input
              v-model="newScriptDescription"
              type="text"
              placeholder="What does this script do?"
            />
          </div>
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showNewScriptModal = false">Cancel</button>
            <button class="btn btn-primary" @click="createNewScript" :disabled="!newScriptName.trim()">
              Create
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Templates Modal -->
    <Teleport to="body">
      <div v-if="showTemplatesModal" class="modal-overlay" @click.self="showTemplatesModal = false">
        <div class="modal modal-lg">
          <h3>Script Templates</h3>
          <div class="templates-grid">
            <div
              v-for="template in SCRIPT_TEMPLATES"
              :key="template.id"
              class="template-card"
              @click="createFromTemplate(template.id)"
            >
              <h4>{{ template.name }}</h4>
              <p>{{ template.description }}</p>
              <span class="template-category">{{ template.category }}</span>
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showTemplatesModal = false">Close</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.python-scripts-container {
  display: flex;
  height: 100%;
  background: var(--bg-primary, #1a1a2e);
  color: var(--text-primary, #e0e0e0);
}

/* Sidebar */
.scripts-sidebar {
  width: 250px;
  min-width: 200px;
  border-right: 1px solid var(--border-color, #333);
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary, #16213e);
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border-bottom: 1px solid var(--border-color, #333);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.sidebar-actions {
  display: flex;
  gap: 4px;
}

.scripts-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.script-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.script-item:hover {
  background: var(--bg-hover, #1f2937);
}

.script-item.selected {
  background: var(--bg-active, #2563eb);
}

.script-state {
  font-size: 10px;
}

.state-running {
  color: #22c55e;
  animation: pulse 1s infinite;
}

.state-error {
  color: #ef4444;
}

.state-idle {
  color: #6b7280;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.script-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.empty-state {
  text-align: center;
  padding: 24px;
  color: var(--text-secondary, #9ca3af);
  font-size: 13px;
}

/* Published Values */
.published-section {
  border-top: 1px solid var(--border-color, #333);
  padding: 12px;
}

.published-section h4 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  text-transform: uppercase;
}

.published-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.published-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 8px;
  background: var(--bg-tertiary, #0f172a);
  border-radius: 4px;
}

.pv-name {
  flex: 1;
  color: var(--text-secondary, #9ca3af);
}

.pv-value {
  font-family: monospace;
  color: #22c55e;
}

.pv-units {
  color: var(--text-tertiary, #6b7280);
  font-size: 11px;
}

/* Editor Panel */
.editor-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color, #333);
  background: var(--bg-secondary, #16213e);
}

.script-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.script-title {
  font-weight: 600;
}

.dirty-indicator {
  color: #f59e0b;
  font-size: 20px;
  line-height: 1;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.run-mode-select {
  font-size: 12px;
  color: var(--text-primary, #e2e8f0);
  background: var(--bg-tertiary, #0f172a);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  padding: 4px 8px;
  cursor: pointer;
  margin-right: 8px;
}

.run-mode-select:hover {
  border-color: #3b82f6;
}

.run-mode-select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.run-mode-select option {
  background: var(--bg-secondary, #16213e);
  color: var(--text-primary, #e2e8f0);
}

/* Validation Panel */
.validation-panel {
  background: var(--bg-tertiary, #0f172a);
  border-bottom: 1px solid var(--border-color, #333);
  max-height: 150px;
  overflow-y: auto;
}

.validation-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #7f1d1d;
  color: #fca5a5;
  font-size: 12px;
}

.validation-errors {
  padding: 8px;
}

.validation-error {
  display: flex;
  gap: 12px;
  padding: 4px 8px;
  font-size: 12px;
  border-radius: 4px;
  margin-bottom: 4px;
}

.validation-error.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.validation-error.warning {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.error-location {
  font-family: monospace;
  min-width: 60px;
}

.error-message {
  flex: 1;
}

.pyodide-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  gap: 16px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color, #333);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-bar {
  width: 200px;
  height: 4px;
  background: var(--bg-tertiary, #0f172a);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  transition: width 0.3s;
}

.editor-wrapper {
  flex: 1;
  min-height: 200px;
}

.monaco-container {
  width: 100%;
  height: 100%;
}

.editor-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #9ca3af);
}

/* Console */
.console-panel {
  height: 200px;
  min-height: 100px;
  border-top: 1px solid var(--border-color, #333);
  display: flex;
  flex-direction: column;
  background: var(--bg-tertiary, #0f172a);
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  border-bottom: 1px solid var(--border-color, #333);
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
}

.console-output {
  flex: 1;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
  padding: 8px;
}

.console-line {
  display: flex;
  gap: 8px;
  padding: 2px 0;
}

.console-time {
  color: var(--text-tertiary, #6b7280);
}

.console-type {
  width: 60px;
  text-align: right;
}

.output-stdout .console-type { color: #9ca3af; }
.output-info .console-type { color: #3b82f6; }
.output-warning .console-type { color: #f59e0b; }
.output-error .console-type { color: #ef4444; }

.console-message {
  flex: 1;
  word-break: break-word;
}

.output-error .console-message { color: #ef4444; }

.console-empty {
  color: var(--text-tertiary, #6b7280);
  font-style: italic;
}

/* Buttons */
.btn {
  padding: 6px 12px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s;
}

.btn-sm {
  padding: 4px 8px;
  font-size: 12px;
}

.btn-primary {
  background: #3b82f6;
  color: white;
}

.btn-primary:hover { background: #2563eb; }
.btn-primary:disabled { background: #1e40af; opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: var(--bg-tertiary, #374151);
  color: var(--text-primary, #e0e0e0);
}

.btn-secondary:hover { background: var(--bg-hover, #4b5563); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-success {
  background: #22c55e;
  color: white;
}

.btn-success:hover { background: #16a34a; }

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover { background: #dc2626; }

.btn-danger-text {
  color: #ef4444;
}

.btn-ghost {
  background: transparent;
  color: var(--text-secondary, #9ca3af);
}

.btn-ghost:hover {
  background: var(--bg-hover, #1f2937);
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
  background: var(--bg-secondary, #16213e);
  border-radius: 8px;
  padding: 24px;
  min-width: 400px;
  max-width: 90vw;
}

.modal-lg {
  min-width: 600px;
}

.modal h3 {
  margin: 0 0 16px 0;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 4px;
  font-size: 13px;
  color: var(--text-secondary, #9ca3af);
}

.form-group input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  background: var(--bg-tertiary, #0f172a);
  color: var(--text-primary, #e0e0e0);
  font-size: 14px;
}

.form-group input:focus {
  outline: none;
  border-color: #3b82f6;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 24px;
}

/* Templates */
.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.template-card {
  padding: 16px;
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.template-card:hover {
  border-color: #3b82f6;
  background: var(--bg-hover, #1f2937);
}

.template-card h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
}

.template-card p {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
}

.template-category {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-tertiary, #0f172a);
  color: var(--text-tertiary, #6b7280);
}
</style>
