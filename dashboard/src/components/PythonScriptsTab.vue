<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as monaco from 'monaco-editor'
import { usePythonScripts } from '../composables/usePythonScripts'
import { useBackendScripts } from '../composables/useBackendScripts'
import { useProjectFiles } from '../composables/useProjectFiles'
import { useDashboardStore } from '../stores/dashboard'
import type { PythonScript, ScriptOutput } from '../types/python-scripts'
import { SCRIPT_TEMPLATES, DEFAULT_SCRIPT_CODE } from '../types/python-scripts'

const store = useDashboardStore()
// Pyodide is still used for syntax validation
const pythonScripts = usePythonScripts()
// Backend scripts - actual execution happens server-side
const backendScripts = useBackendScripts()
// Project file management - for persisting scripts to project
const projectFiles = useProjectFiles()

// =============================================================================
// STATE
// =============================================================================

const selectedScriptId = ref<string | null>(null)
const showNewScriptModal = ref(false)
const showTemplatesModal = ref(false)
const showImportDataModal = ref(false)
const newScriptName = ref('')
const newScriptDescription = ref('')
const importVariableName = ref('data')

// File input ref
const fileInputRef = ref<HTMLInputElement | null>(null)

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
const validationSuccess = ref(false)
let validationSuccessTimeout: ReturnType<typeof setTimeout> | null = null

// =============================================================================
// COMPUTED
// =============================================================================

// Use backend scripts for the main script list
const selectedScript = computed(() =>
  selectedScriptId.value ? backendScripts.scripts.value[selectedScriptId.value] : null
)

// Running state comes from backend
const isScriptRunning = computed(() =>
  selectedScriptId.value ? backendScripts.runningScriptIds.value.has(selectedScriptId.value) : false
)

// Outputs come from backend
const currentScriptOutputs = computed(() =>
  selectedScriptId.value ? backendScripts.getScriptOutputs(selectedScriptId.value) : []
)

// Imported data still handled locally (could be synced later)
const currentScriptImportedData = computed(() =>
  selectedScriptId.value ? (pythonScripts.scripts.value[selectedScriptId.value]?.importedData || []) : []
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

      // ── Core API functions ─────────────────────────────────────────
      const apiFuncs = [
        // Publishing
        { name: 'publish', snippet: "publish('$1', $2, units='$3')", doc: 'Publish computed value to dashboard' },
        // Control flow
        { name: 'next_scan', snippet: 'next_scan()', doc: 'Wait for next scan cycle (matches scan rate)' },
        { name: 'wait_for', snippet: 'wait_for($1)', doc: 'Wait for N seconds (respects stop requests)' },
        { name: 'wait_until', snippet: 'wait_until(lambda: $1, timeout=$2)', doc: 'Wait until condition is true (returns False on timeout)' },
        { name: 'should_stop', snippet: 'should_stop()', doc: 'Check if script should exit (True when stop requested)' },
        // State persistence
        { name: 'persist', snippet: "persist('$1', $2)", doc: 'Save state to disk (survives restarts)' },
        { name: 'restore', snippet: "restore('$1', $2)", doc: 'Load saved state from disk (key, default)' },
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

      // ── Tags API ────────────────────────────────────────────────────
      const tagsMethods = [
        { name: 'tags.get', snippet: "tags.get('$1', $2)", doc: 'Read channel value with default (name, default=0.0)' },
        { name: 'tags.keys', snippet: 'tags.keys()', doc: 'List all available channel names' },
        { name: 'tags.age', snippet: "tags.age('$1')", doc: 'Seconds since last update for channel' },
        { name: 'tags.timestamp', snippet: "tags.timestamp('$1')", doc: 'Acquisition timestamp (Unix ms) for channel' },
        { name: 'tags.get_with_timestamp', snippet: "tags.get_with_timestamp('$1')", doc: 'Get (value, timestamp) tuple for channel' },
      ]

      for (const fn of tagsMethods) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Tags API',
          documentation: fn.doc,
          range
        })
      }

      // ── Outputs API ─────────────────────────────────────────────────
      const outputsMethods = [
        { name: 'outputs.set', snippet: "outputs.set('$1', $2)", doc: 'Set output channel value' },
        { name: 'outputs.claim', snippet: "outputs.claim('$1')", doc: 'Claim exclusive control of output channel' },
        { name: 'outputs.release', snippet: "outputs.release('$1')", doc: 'Release exclusive control of output channel' },
        { name: 'outputs.available', snippet: "outputs.available('$1')", doc: 'Check if output is available (not claimed by another script)' },
        { name: 'outputs.claimed_by', snippet: "outputs.claimed_by('$1')", doc: 'Get name of script that claimed this output' },
        { name: 'outputs.claims', snippet: 'outputs.claims()', doc: 'Get all current output claims' },
      ]

      for (const fn of outputsMethods) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Outputs API',
          documentation: fn.doc,
          range
        })
      }

      // ── Vars API (shared variables between scripts) ─────────────────
      const varsMethods = [
        { name: 'vars.set', snippet: "vars.set('$1', $2)", doc: 'Set shared variable (visible to all scripts)' },
        { name: 'vars.get', snippet: "vars.get('$1', $2)", doc: 'Get shared variable with default (name, default=0.0)' },
        { name: 'vars.reset', snippet: "vars.reset('$1')", doc: 'Reset variable to zero (numeric) or empty (string)' },
        { name: 'vars.delete', snippet: "vars.delete('$1')", doc: 'Remove shared variable' },
        { name: 'vars.keys', snippet: 'vars.keys()', doc: 'List all shared variable names' },
        { name: 'vars.flush', snippet: 'vars.flush()', doc: 'Force save pending variable changes to disk' },
      ]

      for (const fn of varsMethods) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Vars API',
          documentation: fn.doc,
          range
        })
      }

      // ── Session API ─────────────────────────────────────────────────
      const sessionProps = [
        { name: 'session.active', text: 'session.active', doc: 'True if test session is active', kind: 'prop' },
        { name: 'session.elapsed', text: 'session.elapsed', doc: 'Seconds since session started', kind: 'prop' },
        { name: 'session.recording', text: 'session.recording', doc: 'True if currently recording data', kind: 'prop' },
        { name: 'session.start', text: 'session.start()', doc: 'Start data acquisition', kind: 'method' },
        { name: 'session.stop', text: 'session.stop()', doc: 'Stop data acquisition', kind: 'method' },
        { name: 'session.start_recording', text: "session.start_recording(filename='$1')", doc: 'Start recording to file', kind: 'snippet' },
        { name: 'session.stop_recording', text: 'session.stop_recording()', doc: 'Stop recording', kind: 'method' },
        { name: 'session.now', text: 'session.now()', doc: 'Current timestamp (Unix ms)', kind: 'method' },
        { name: 'session.now_iso', text: 'session.now_iso()', doc: 'Current time as ISO 8601 string', kind: 'method' },
        { name: 'session.time_of_day', text: 'session.time_of_day()', doc: 'Current time as HH:MM:SS', kind: 'method' },
      ]

      for (const s of sessionProps) {
        const isSnippet = s.kind === 'snippet'
        suggestions.push({
          label: s.name,
          kind: s.kind === 'prop'
            ? monaco.languages.CompletionItemKind.Property
            : monaco.languages.CompletionItemKind.Method,
          insertText: s.text,
          ...(isSnippet ? { insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet } : {}),
          detail: 'Session API',
          documentation: s.doc,
          range
        })
      }

      // ── PID API ─────────────────────────────────────────────────────
      const pidMethods = [
        { name: 'pid.keys', snippet: 'pid.keys()', doc: 'List all PID loop IDs' },
        { name: 'pid.status', snippet: "pid.status('$1')", doc: 'Get PID loop status (setpoint, output, pv, error, mode)' },
        { name: 'pid.all_status', snippet: 'pid.all_status()', doc: 'Get status of all PID loops' },
        { name: 'pid.tune', snippet: "pid['$1'].tune(kp=$2, ki=$3, kd=$4)", doc: 'Tune PID gains' },
        { name: 'pid.setpoint', snippet: "pid['$1'].setpoint = $2", doc: 'Set PID loop setpoint' },
        { name: 'pid.auto', snippet: "pid['$1'].auto()", doc: 'Switch PID loop to automatic mode' },
        { name: 'pid.manual', snippet: "pid['$1'].manual()", doc: 'Switch PID loop to manual mode' },
        { name: 'pid.enable', snippet: "pid['$1'].enable()", doc: 'Enable PID loop' },
        { name: 'pid.disable', snippet: "pid['$1'].disable()", doc: 'Disable PID loop' },
      ]

      for (const fn of pidMethods) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'PID API',
          documentation: fn.doc,
          range
        })
      }

      // ── Time functions ──────────────────────────────────────────────
      const timeFuncs = [
        { name: 'now', snippet: 'now()', doc: 'Current Unix timestamp (seconds)' },
        { name: 'now_ms', snippet: 'now_ms()', doc: 'Current Unix timestamp (milliseconds)' },
        { name: 'now_iso', snippet: 'now_iso()', doc: 'Current time as ISO 8601 string' },
        { name: 'time_of_day', snippet: 'time_of_day()', doc: 'Current time as HH:MM:SS' },
        { name: 'elapsed_since', snippet: 'elapsed_since($1)', doc: 'Seconds elapsed since timestamp' },
        { name: 'format_timestamp', snippet: "format_timestamp($1, '$2')", doc: 'Format Unix timestamp with strftime pattern' },
      ]

      for (const fn of timeFuncs) {
        suggestions.push({
          label: fn.name,
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: fn.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Time function',
          documentation: fn.doc,
          range
        })
      }

      // ── Unit conversion functions ───────────────────────────────────
      const convFuncs = [
        { name: 'F_to_C', doc: 'Fahrenheit to Celsius' },
        { name: 'C_to_F', doc: 'Celsius to Fahrenheit' },
        { name: 'GPM_to_LPM', doc: 'Gallons/min to Liters/min' },
        { name: 'LPM_to_GPM', doc: 'Liters/min to Gallons/min' },
        { name: 'PSI_to_bar', doc: 'PSI to bar' },
        { name: 'bar_to_PSI', doc: 'bar to PSI' },
        { name: 'gal_to_L', doc: 'Gallons to Liters' },
        { name: 'L_to_gal', doc: 'Liters to Gallons' },
        { name: 'BTU_to_kJ', doc: 'BTU to kilojoules' },
        { name: 'kJ_to_BTU', doc: 'Kilojoules to BTU' },
        { name: 'lb_to_kg', doc: 'Pounds to kilograms' },
        { name: 'kg_to_lb', doc: 'Kilograms to pounds' },
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

      // ── Helper classes ──────────────────────────────────────────────
      const helpers = [
        { name: 'Counter', snippet: 'Counter(target=$1, window=$2, debounce=$3, auto_reset=$4)', doc: 'Universal counter: totalizer, batch, sliding window, debounce, duty cycle, run hours, cycle tracking, stopwatch' },
        { name: 'RateCalculator', snippet: 'RateCalculator(window_seconds=$1)', doc: 'Calculate rate of change over time window' },
        { name: 'Accumulator', snippet: 'Accumulator(initial=$1)', doc: 'Accumulate incremental changes with rollover handling' },
        { name: 'EdgeDetector', snippet: 'EdgeDetector(threshold=$1)', doc: 'Detect rising/falling edges on a signal' },
        { name: 'RollingStats', snippet: 'RollingStats(window_size=$1)', doc: 'Rolling statistics (mean, min, max, std)' },
        { name: 'Scheduler', snippet: 'Scheduler()', doc: 'Job scheduler for interval/cron/one-shot tasks' },
        { name: 'StateMachine', snippet: "StateMachine(initial_state='$1')", doc: 'Finite state machine for sequences' },
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

      // ── Counter properties & methods ────────────────────────────────
      const counterMembers = [
        { name: 'Counter.increment', snippet: '.increment($1)', doc: 'Add to count (default 1)' },
        { name: 'Counter.decrement', snippet: '.decrement($1)', doc: 'Subtract from count (default 1)' },
        { name: 'Counter.tick', snippet: '.tick()', doc: 'Record timestamped event (for sliding window rate)' },
        { name: 'Counter.update', snippet: '.update($1)', doc: 'Smart update: edge detect on bool, integrate on float rate' },
        { name: 'Counter.reset', snippet: '.reset()', doc: 'Reset count to 0 (total and cycles preserved)' },
        { name: 'Counter.set', snippet: '.set($1)', doc: 'Set count to specific value (tare/preset)' },
        { name: 'Counter.lap', snippet: ".lap('$1')", doc: 'Record named lap time' },
        { name: '.count', snippet: '.count', doc: 'Current count (resets with reset())' },
        { name: '.total', snippet: '.total', doc: 'Lifetime cumulative total (never auto-resets)' },
        { name: '.done', snippet: '.done', doc: 'True when count >= target' },
        { name: '.remaining', snippet: '.remaining', doc: 'How many left until target' },
        { name: '.batch', snippet: '.batch', doc: 'Batch number (times target reached with auto_reset)' },
        { name: '.window_count', snippet: '.window_count', doc: 'Events in sliding time window' },
        { name: '.rate', snippet: '.rate', doc: 'Events per second over sliding window' },
        { name: '.state', snippet: '.state', doc: 'Debounced boolean state' },
        { name: '.stable', snippet: '.stable', doc: 'True if debounce buffer is unanimous' },
        { name: '.duty', snippet: '.duty', doc: 'Duty cycle percentage (0-100) over window' },
        { name: '.run_time', snippet: '.run_time', doc: 'Cumulative seconds signal was ON' },
        { name: '.run_hours', snippet: '.run_hours', doc: 'Cumulative hours signal was ON' },
        { name: '.cycles', snippet: '.cycles', doc: 'Completed ON→OFF cycle count' },
        { name: '.cycle_avg', snippet: '.cycle_avg', doc: 'Mean cycle duration (seconds)' },
        { name: '.cycle_min', snippet: '.cycle_min', doc: 'Shortest cycle (seconds)' },
        { name: '.cycle_max', snippet: '.cycle_max', doc: 'Longest cycle (seconds)' },
        { name: '.elapsed', snippet: '.elapsed', doc: 'Seconds since creation or last reset' },
        { name: '.laps', snippet: '.laps', doc: 'Dict of {name: duration_seconds}' },
      ]

      for (const m of counterMembers) {
        suggestions.push({
          label: m.name,
          kind: m.name.startsWith('Counter.') ? monaco.languages.CompletionItemKind.Method : monaco.languages.CompletionItemKind.Property,
          insertText: m.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: 'Counter',
          documentation: m.doc,
          range
        })
      }

      return { suggestions }
    }
  })
}

// =============================================================================
// SCRIPT SELECTION
// =============================================================================

watch(selectedScriptId, (id) => {
  if (id && backendScripts.scripts.value[id] && editor) {
    const script = backendScripts.scripts.value[id]
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

  // Send to backend via MQTT
  const scriptId = backendScripts.addScript({
    name: newScriptName.value.trim(),
    code: DEFAULT_SCRIPT_CODE,
    description: newScriptDescription.value.trim(),
    runMode: 'manual',
    enabled: true
  })

  showNewScriptModal.value = false
  selectedScriptId.value = scriptId

  // Update editor with default code (matching createFromTemplate behavior)
  if (editor) {
    editor.setValue(DEFAULT_SCRIPT_CODE)
    lastSavedCode.value = DEFAULT_SCRIPT_CODE
    isDirty.value = false
  }

  // Persist to project file
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

function createFromTemplate(templateId: string) {
  const template = SCRIPT_TEMPLATES.find(t => t.id === templateId)
  if (!template) return

  // Send to backend via MQTT
  const scriptId = backendScripts.addScript({
    name: template.name,
    code: template.code,
    description: template.description,
    runMode: 'manual',
    enabled: true
  })

  showTemplatesModal.value = false
  selectedScriptId.value = scriptId

  // Update editor
  if (editor) {
    editor.setValue(template.code)
    lastSavedCode.value = template.code
    isDirty.value = false
  }

  // Persist to project file
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

async function saveScript() {
  if (!selectedScriptId.value || !editor) return

  const code = editor.getValue()

  // If script is running, use hot-reload to swap code without losing state
  // If not running, just update the code
  if (isScriptRunning.value) {
    // Hot-reload: stops, updates code, restarts - preserving persisted state
    backendScripts.reloadScript(selectedScriptId.value, code)
  } else {
    // Normal update: just saves the code
    backendScripts.updateScript(selectedScriptId.value, { code })
  }

  lastSavedCode.value = code
  isDirty.value = false

  // Persist to project file (small delay to ensure backend processes MQTT first)
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

async function deleteScript() {
  if (!selectedScriptId.value) return

  if (!confirm('Delete this script? This cannot be undone.')) {
    return
  }

  // Send delete to backend via MQTT
  backendScripts.removeScript(selectedScriptId.value)
  selectedScriptId.value = null

  if (editor) {
    editor.setValue('')
  }

  // Persist to project file (small delay to ensure backend processes MQTT first)
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

// =============================================================================
// SCRIPT EXECUTION (via backend)
// =============================================================================

async function toggleScript() {
  if (!selectedScriptId.value) return

  if (isScriptRunning.value) {
    // Stop script on backend
    backendScripts.stopScript(selectedScriptId.value)
  } else {
    // Save before running
    if (isDirty.value) {
      saveScript()
    }

    // Validate syntax before running (uses Pyodide for quick check)
    const code = editor?.getValue() || ''
    const result = await pythonScripts.validateScript(code)
    validationErrors.value = result.errors

    if (!result.valid) {
      // Show validation errors but allow running with warnings
      const hasErrors = result.errors.some(e => e.type === 'error')
      if (hasErrors) {
        return // Don't run if there are syntax errors
      }
    }

    // Start script on backend
    backendScripts.startScript(selectedScriptId.value)
  }
}

async function validateScript() {
  if (!editor) return

  isValidating.value = true
  validationErrors.value = []
  validationSuccess.value = false

  // Clear any pending success timeout
  if (validationSuccessTimeout) {
    clearTimeout(validationSuccessTimeout)
    validationSuccessTimeout = null
  }

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

    // Show success feedback if no errors
    if (result.valid && result.errors.length === 0) {
      validationSuccess.value = true
      // Auto-hide after 3 seconds
      validationSuccessTimeout = setTimeout(() => {
        validationSuccess.value = false
      }, 3000)
    }
  } finally {
    isValidating.value = false
  }
}

function updateRunMode(event: Event) {
  if (!selectedScriptId.value) return
  const target = event.target as HTMLSelectElement
  const mode = target.value as 'manual' | 'acquisition' | 'session'
  // Update run mode on backend
  backendScripts.updateScript(selectedScriptId.value, { runMode: mode })

  // Persist to project file
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

function updateAutoRestart(event: Event) {
  if (!selectedScriptId.value) return
  const target = event.target as HTMLInputElement
  // Update auto-restart on backend
  backendScripts.updateScript(selectedScriptId.value, { autoRestart: target.checked })

  // Persist to project file
  setTimeout(async () => {
    if (projectFiles.currentProject.value) {
      await projectFiles.saveNow()
    }
  }, 100)
}

function clearConsole() {
  if (selectedScriptId.value) {
    backendScripts.clearScriptOutput(selectedScriptId.value)
  }
}

// =============================================================================
// DATA IMPORT
// =============================================================================

function openImportDataModal() {
  if (!selectedScriptId.value) return
  importVariableName.value = 'data'
  showImportDataModal.value = true
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

async function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedScriptId.value) return

  try {
    const isExcel = file.name.endsWith('.xlsx') || file.name.endsWith('.xls')

    if (isExcel) {
      await pythonScripts.importExcelFile(selectedScriptId.value, file, importVariableName.value)
    } else {
      await pythonScripts.importCSVFile(selectedScriptId.value, file, importVariableName.value)
    }

    showImportDataModal.value = false
  } catch (error: any) {
    console.error('Failed to import file:', error)
  } finally {
    // Reset file input
    input.value = ''
  }
}

function removeImportedData(variableName: string) {
  if (!selectedScriptId.value) return
  if (confirm(`Remove imported data "${variableName}"?`)) {
    pythonScripts.removeImportedData(selectedScriptId.value, variableName)
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
  const script = backendScripts.scripts.value[id]
  if (script?.state === 'running') return '▶'
  if (script?.state === 'error') return '✕'
  return '○'
}

function getScriptStateClass(id: string): string {
  const script = backendScripts.scripts.value[id]
  if (script?.state === 'running') return 'state-running'
  if (script?.state === 'error') return 'state-error'
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
          v-for="script in backendScripts.scriptsList.value"
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

        <div v-if="backendScripts.scriptsList.value.length === 0" class="empty-state">
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

      <!-- Imported Data for Selected Script -->
      <div class="imported-section" v-if="currentScriptImportedData.length > 0">
        <h4>Imported Data</h4>
        <div class="imported-list">
          <div
            v-for="data in currentScriptImportedData"
            :key="data.variableName"
            class="imported-item"
          >
            <div class="imported-info">
              <span class="imported-name">{{ data.variableName }}</span>
              <span class="imported-meta">{{ data.data.length }} rows</span>
            </div>
            <button
              class="btn btn-sm btn-ghost btn-danger-text"
              @click="removeImportedData(data.variableName)"
              title="Remove"
            >×</button>
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
          <label class="auto-restart-label" title="Automatically restart the script if it times out">
            <input
              type="checkbox"
              :checked="selectedScript?.autoRestart || false"
              @change="updateAutoRestart"
            />
            <span>Auto-restart</span>
          </label>
          <button
            class="btn btn-secondary"
            @click="openImportDataModal"
            title="Import CSV/Excel data"
          >
            📊 Load Data
          </button>
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
            title="Scripts run on the backend server"
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

      <!-- Validation Success -->
      <div v-if="validationSuccess" class="validation-panel validation-success">
        <div class="validation-header">
          <span>✓ Script syntax is valid</span>
          <button class="btn btn-sm btn-ghost" @click="validationSuccess = false">×</button>
        </div>
      </div>

      <!-- Validation Errors -->
      <div v-if="validationErrors.length > 0" class="validation-panel validation-errors-panel">
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

      <!-- Pyodide Loading Status (only used for syntax validation) -->
      <div v-if="pythonScripts.isPyodideLoading.value" class="pyodide-loading">
        <div class="loading-spinner"></div>
        <span>Loading syntax validator... {{ pythonScripts.pyodideLoadMessage.value }}</span>
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
            <span v-if="output.lineNumber" class="console-line-num" title="Click to go to line">Line {{ output.lineNumber }}:</span>
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

    <!-- Import Data Modal -->
    <Teleport to="body">
      <div v-if="showImportDataModal" class="modal-overlay" @click.self="showImportDataModal = false">
        <div class="modal">
          <h3>Import Data</h3>
          <p class="modal-description">
            Import a CSV or Excel file to use in your script.
            The data will be available as a list of dictionaries.
          </p>
          <div class="form-group">
            <label>Variable Name</label>
            <input
              v-model="importVariableName"
              type="text"
              placeholder="data"
              pattern="[a-zA-Z_][a-zA-Z0-9_]*"
            />
            <p class="form-hint">Use this name to access the data in your script (e.g., <code>for row in data:</code>)</p>
          </div>
          <div class="import-dropzone" @click="triggerFileInput">
            <div class="dropzone-content">
              <span class="dropzone-icon">📁</span>
              <span class="dropzone-text">Click to select CSV or Excel file</span>
              <span class="dropzone-hint">.csv, .xlsx, .xls</span>
            </div>
          </div>
          <input
            ref="fileInputRef"
            type="file"
            accept=".csv,.xlsx,.xls"
            style="display: none"
            @change="handleFileSelect"
          />
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showImportDataModal = false">Cancel</button>
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

.auto-restart-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  margin-right: 8px;
  user-select: none;
}

.auto-restart-label input[type="checkbox"] {
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: #3b82f6;
}

.auto-restart-label:hover {
  color: var(--text-primary, #e0e0e0);
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
  font-size: 12px;
}

/* Error panel header (red) */
.validation-errors-panel .validation-header {
  background: #7f1d1d;
  color: #fca5a5;
}

/* Success panel header (green) */
.validation-success .validation-header {
  background: #14532d;
  color: #86efac;
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

.console-line-num {
  color: #f59e0b;
  font-weight: 600;
  cursor: pointer;
  padding: 0 4px;
  border-radius: 2px;
}

.console-line-num:hover {
  background: rgba(245, 158, 11, 0.2);
}

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

/* Imported Data Section */
.imported-section {
  border-top: 1px solid var(--border-color, #333);
  padding: 12px;
}

.imported-section h4 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
  text-transform: uppercase;
}

.imported-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.imported-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 6px 8px;
  background: var(--bg-tertiary, #0f172a);
  border-radius: 4px;
}

.imported-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.imported-name {
  color: #3b82f6;
  font-family: monospace;
}

.imported-meta {
  color: var(--text-tertiary, #6b7280);
  font-size: 11px;
}

/* Import Modal */
.modal-description {
  color: var(--text-secondary, #9ca3af);
  font-size: 13px;
  margin-bottom: 16px;
}

.form-hint {
  font-size: 11px;
  color: var(--text-tertiary, #6b7280);
  margin-top: 4px;
}

.form-hint code {
  background: var(--bg-tertiary, #0f172a);
  padding: 2px 4px;
  border-radius: 2px;
  font-family: monospace;
}

.import-dropzone {
  border: 2px dashed var(--border-color, #333);
  border-radius: 8px;
  padding: 32px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 16px;
}

.import-dropzone:hover {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.dropzone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
}

.dropzone-icon {
  font-size: 32px;
}

.dropzone-text {
  font-size: 14px;
  color: var(--text-primary, #e0e0e0);
}

.dropzone-hint {
  font-size: 12px;
  color: var(--text-tertiary, #6b7280);
}
</style>
