<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import * as monaco from 'monaco-editor'
import type { FormulaBlock, FormulaBlockOutput } from '../types'

const props = defineProps<{
  modelValue: FormulaBlock | null
  channelNames: string[]
  variableNames: string[]
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [block: FormulaBlock]
  'save': [block: FormulaBlock]
  'cancel': []
  'validate': [code: string]
}>()

// Editor state
const editorContainer = ref<HTMLDivElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

// Form state
const blockName = ref('')
const blockDescription = ref('')
const code = ref('')
const outputs = ref<Record<string, FormulaBlockOutput>>({})
const enabled = ref(true)

// Validation state
const validationError = ref<string | null>(null)
const validationErrorLine = ref<number | null>(null)
const detectedOutputs = ref<string[]>([])

// Initialize form from modelValue
watch(() => props.modelValue, (block) => {
  if (block) {
    blockName.value = block.name
    blockDescription.value = block.description
    code.value = block.code
    outputs.value = { ...block.outputs }
    enabled.value = block.enabled
    validationError.value = block.lastError || null
    detectedOutputs.value = Object.keys(block.outputs)

    // Update editor content
    if (editor && editor.getValue() !== block.code) {
      editor.setValue(block.code)
    }
  } else {
    // New block
    blockName.value = ''
    blockDescription.value = ''
    code.value = ''
    outputs.value = {}
    enabled.value = true
    validationError.value = null
    detectedOutputs.value = []
    if (editor) {
      editor.setValue('')
    }
  }
}, { immediate: true })

// Build autocomplete suggestions
const suggestionItems = computed(() => {
  const items: Omit<monaco.languages.CompletionItem, 'range'>[] = []

  // Channel names
  for (const ch of props.channelNames) {
    items.push({
      label: ch,
      kind: monaco.languages.CompletionItemKind.Variable,
      insertText: ch,
      detail: 'Channel',
      documentation: 'Live channel value',
    })
  }

  // User variables
  for (const v of props.variableNames) {
    items.push({
      label: v,
      kind: monaco.languages.CompletionItemKind.Variable,
      insertText: v,
      detail: 'User Variable',
      documentation: 'User-defined variable value',
    })
  }

  // Math functions
  const mathFuncs = [
    { name: 'abs', doc: 'Absolute value' },
    { name: 'min', doc: 'Minimum of values: min(a, b, ...)' },
    { name: 'max', doc: 'Maximum of values: max(a, b, ...)' },
    { name: 'sum', doc: 'Sum of values: sum([a, b, ...])' },
    { name: 'sqrt', doc: 'Square root' },
    { name: 'pow', doc: 'Power: pow(base, exponent)' },
    { name: 'sin', doc: 'Sine (radians)' },
    { name: 'cos', doc: 'Cosine (radians)' },
    { name: 'tan', doc: 'Tangent (radians)' },
    { name: 'asin', doc: 'Arc sine' },
    { name: 'acos', doc: 'Arc cosine' },
    { name: 'atan', doc: 'Arc tangent' },
    { name: 'atan2', doc: 'Arc tangent of y/x: atan2(y, x)' },
    { name: 'log', doc: 'Natural logarithm' },
    { name: 'log10', doc: 'Base-10 logarithm' },
    { name: 'log2', doc: 'Base-2 logarithm' },
    { name: 'exp', doc: 'Exponential (e^x)' },
    { name: 'floor', doc: 'Floor (round down)' },
    { name: 'ceil', doc: 'Ceiling (round up)' },
    { name: 'round', doc: 'Round to nearest integer' },
    { name: 'pi', doc: 'Mathematical constant pi (3.14159...)' },
    { name: 'e', doc: 'Mathematical constant e (2.71828...)' },
    { name: 'degrees', doc: 'Convert radians to degrees' },
    { name: 'radians', doc: 'Convert degrees to radians' },
    { name: 'hypot', doc: 'Euclidean distance: hypot(x, y)' },
    { name: 'isnan', doc: 'Check if value is NaN' },
    { name: 'isinf', doc: 'Check if value is infinite' },
  ]

  for (const fn of mathFuncs) {
    items.push({
      label: fn.name,
      kind: monaco.languages.CompletionItemKind.Function,
      insertText: fn.name.includes('pi') || fn.name.includes('e') ? fn.name : fn.name + '($0)',
      insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
      detail: 'Math function',
      documentation: fn.doc,
    })
  }

  // Keywords
  const keywords = ['if', 'else', 'and', 'or', 'not', 'True', 'False', 'None']
  for (const kw of keywords) {
    items.push({
      label: kw,
      kind: monaco.languages.CompletionItemKind.Keyword,
      insertText: kw,
      detail: 'Keyword',
    })
  }

  return items
})

// Initialize Monaco editor
onMounted(() => {
  if (!editorContainer.value) return

  // Register custom language for formula blocks
  monaco.languages.register({ id: 'formula' })

  // Simple tokenizer based on Python
  monaco.languages.setMonarchTokensProvider('formula', {
    keywords: ['if', 'else', 'and', 'or', 'not', 'True', 'False', 'None'],
    operators: [
      '=', '>', '<', '!', '~', '?', ':', '==', '<=', '>=', '!=',
      '&&', '||', '++', '--', '+', '-', '*', '/', '&', '|', '^', '%',
    ],
    symbols: /[=><!~?:&|+\-*\/\^%]+/,

    tokenizer: {
      root: [
        // Comments
        [/#.*$/, 'comment'],
        // Numbers
        [/\d+\.?\d*([eE][\-+]?\d+)?/, 'number'],
        // Strings
        [/"([^"\\]|\\.)*$/, 'string.invalid'],
        [/'([^'\\]|\\.)*$/, 'string.invalid'],
        [/"/, 'string', '@string_double'],
        [/'/, 'string', '@string_single'],
        // Keywords
        [/[a-zA-Z_]\w*/, {
          cases: {
            '@keywords': 'keyword',
            '@default': 'identifier'
          }
        }],
        // Operators
        [/@symbols/, {
          cases: {
            '@operators': 'operator',
            '@default': ''
          }
        }],
        // Parentheses
        [/[{}()\[\]]/, '@brackets'],
        // Comma
        [/[,]/, 'delimiter'],
      ],
      string_double: [
        [/[^\\"]+/, 'string'],
        [/\\./, 'string.escape'],
        [/"/, 'string', '@pop']
      ],
      string_single: [
        [/[^\\']+/, 'string'],
        [/\\./, 'string.escape'],
        [/'/, 'string', '@pop']
      ]
    }
  })

  // Register autocomplete provider
  monaco.languages.registerCompletionItemProvider('formula', {
    provideCompletionItems: (model, position) => {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn
      }

      return {
        suggestions: suggestionItems.value.map(item => ({
          ...item,
          range
        }))
      }
    }
  })

  // Create editor
  editor = monaco.editor.create(editorContainer.value, {
    value: code.value,
    language: 'formula',
    theme: 'vs-dark',
    minimap: { enabled: false },
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Consolas', 'Monaco', monospace",
    lineNumbers: 'on',
    automaticLayout: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    tabSize: 2,
    readOnly: props.readonly,
    suggest: {
      showKeywords: true,
      showVariables: true,
      showFunctions: true,
    },
    quickSuggestions: true,
  })

  // Listen for content changes
  editor.onDidChangeModelContent(() => {
    code.value = editor?.getValue() || ''
    // Clear validation state on edit
    validationError.value = null
    validationErrorLine.value = null
  })

  // Update decorations when error line changes
  watch(validationErrorLine, (line) => {
    if (!editor) return

    if (line !== null) {
      editor.deltaDecorations([], [{
        range: new monaco.Range(line, 1, line, 1),
        options: {
          isWholeLine: true,
          className: 'error-line',
          glyphMarginClassName: 'error-glyph',
        }
      }])
    } else {
      editor.deltaDecorations(editor.getModel()?.getAllDecorations().map(d => d.id) || [], [])
    }
  })
})

onUnmounted(() => {
  editor?.dispose()
})

// Local validation (parse code to detect outputs)
function localValidate() {
  const lines = code.value.split('\n')
  const foundOutputs: string[] = []
  let error: string | null = null
  let errorLine: number | null = null

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]?.trim() ?? ''
    if (!line || line.startsWith('#')) continue

    // Look for assignment patterns: VAR_NAME = ...
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=/)
    if (match) {
      const varName = match[1] ?? ''
      if (varName && !['if', 'else', 'and', 'or', 'not', 'True', 'False', 'None'].includes(varName)) {
        if (!foundOutputs.includes(varName)) {
          foundOutputs.push(varName)
        }
      }
    }
  }

  if (foundOutputs.length === 0 && code.value.trim()) {
    error = 'No output variables detected. Use VAR_NAME = expression syntax.'
  }

  detectedOutputs.value = foundOutputs
  validationError.value = error
  validationErrorLine.value = errorLine

  // Ensure outputs dict has entries for detected outputs
  for (const out of foundOutputs) {
    if (!outputs.value[out]) {
      outputs.value[out] = { units: '', description: '' }
    }
  }
  // Remove outputs no longer in code
  for (const out of Object.keys(outputs.value)) {
    if (!foundOutputs.includes(out)) {
      delete outputs.value[out]
    }
  }

  return { valid: !error, outputs: foundOutputs, error }
}

// Save handler
function handleSave() {
  const validation = localValidate()
  if (!validation.valid) {
    return
  }

  const block: FormulaBlock = {
    id: props.modelValue?.id || `fb_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    name: blockName.value || 'Untitled Formula',
    description: blockDescription.value,
    code: code.value,
    enabled: enabled.value,
    outputs: outputs.value,
    lastError: undefined,
    lastValidated: new Date().toISOString(),
  }

  emit('save', block)
}

function handleCancel() {
  emit('cancel')
}

// Update output metadata
function updateOutputUnits(outputName: string, units: string) {
  if (outputs.value[outputName]) {
    outputs.value[outputName].units = units
  }
}

function updateOutputDescription(outputName: string, desc: string) {
  if (outputs.value[outputName]) {
    outputs.value[outputName].description = desc
  }
}
</script>

<template>
  <div class="formula-editor">
    <!-- Header -->
    <div class="editor-header">
      <div class="header-row">
        <input
          v-model="blockName"
          type="text"
          class="name-input"
          placeholder="Formula Block Name"
          :readonly="readonly"
        />
        <label class="enabled-toggle">
          <input v-model="enabled" type="checkbox" :disabled="readonly" />
          Enabled
        </label>
      </div>
      <input
        v-model="blockDescription"
        type="text"
        class="description-input"
        placeholder="Description (optional)"
        :readonly="readonly"
      />
    </div>

    <!-- Help Panel -->
    <details class="help-panel">
      <summary>Formula Syntax Help</summary>
      <div class="help-content">
        <p>Write Python-like expressions with assignments:</p>
        <pre># Conditional output (None = stale/NaN)
A_BAD_VALUE = PT102 - 70 if PT101 > PT102 + 3 else None

# Simple calculation
TEMP_F = TC101 * 1.8 + 32

# Boolean to numeric
SYSTEM_FAULT = 1 if (A_BAD_VALUE is not None) else 0

# Math functions
PRESSURE_AVG = (PT101 + PT102 + PT103) / 3
DISTANCE = sqrt(X**2 + Y**2)</pre>
        <p><strong>Available:</strong> Channels, user variables, math functions (abs, min, max, sqrt, sin, cos, log, etc.)</p>
      </div>
    </details>

    <!-- Monaco Editor -->
    <div class="editor-wrapper">
      <div ref="editorContainer" class="monaco-container"></div>
    </div>

    <!-- Validation Error -->
    <div v-if="validationError" class="validation-error">
      <span class="error-icon">!</span>
      {{ validationError }}
    </div>

    <!-- Detected Outputs -->
    <div v-if="detectedOutputs.length > 0" class="outputs-section">
      <h4>Output Variables ({{ detectedOutputs.length }})</h4>
      <div class="outputs-list">
        <div v-for="outName in detectedOutputs" :key="outName" class="output-row">
          <span class="output-name">{{ outName }}</span>
          <input
            :value="outputs[outName]?.units || ''"
            @input="(e) => updateOutputUnits(outName, (e.target as HTMLInputElement).value)"
            type="text"
            class="output-units"
            placeholder="Units"
            :readonly="readonly"
          />
          <input
            :value="outputs[outName]?.description || ''"
            @input="(e) => updateOutputDescription(outName, (e.target as HTMLInputElement).value)"
            type="text"
            class="output-desc"
            placeholder="Description"
            :readonly="readonly"
          />
        </div>
      </div>
    </div>

    <!-- Actions -->
    <div v-if="!readonly" class="editor-actions">
      <button class="btn-cancel" @click="handleCancel">Cancel</button>
      <button
        class="btn-save"
        @click="handleSave"
        :disabled="!code.trim() || !!validationError"
      >
        Save Formula Block
      </button>
    </div>
  </div>
</template>

<style scoped>
.formula-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.editor-header {
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.header-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.name-input {
  flex: 1;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 1rem;
  font-weight: 600;
}

.name-input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.description-input {
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 6px 12px;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.description-input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.enabled-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  color: var(--text-muted);
  cursor: pointer;
}

.enabled-toggle input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.help-panel {
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-elevated);
}

.help-panel summary {
  padding: 8px 12px;
  cursor: pointer;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.help-panel summary:hover {
  color: var(--text-muted);
}

.help-content {
  padding: 8px 12px 12px;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.help-content pre {
  background: var(--bg-primary);
  padding: 8px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 0.7rem;
  overflow-x: auto;
  margin: 8px 0;
  color: var(--color-accent-light);
}

.help-content p {
  margin: 4px 0;
}

.editor-wrapper {
  flex: 1;
  min-height: 200px;
}

.monaco-container {
  width: 100%;
  height: 100%;
  min-height: 200px;
}

.validation-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-error-bg);
  border-top: 1px solid var(--color-error);
  color: var(--color-error);
  font-size: 0.85rem;
}

.error-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  background: var(--color-error);
  color: var(--text-primary);
  border-radius: 50%;
  font-weight: bold;
  font-size: 0.75rem;
}

.outputs-section {
  padding: 12px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-elevated);
}

.outputs-section h4 {
  margin: 0 0 8px;
  font-size: 0.8rem;
  color: var(--text-secondary);
  text-transform: uppercase;
}

.outputs-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.output-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.output-name {
  min-width: 120px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  color: var(--color-success);
}

.output-units {
  width: 80px;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 4px 8px;
  color: var(--text-primary);
  font-size: 0.8rem;
}

.output-desc {
  flex: 1;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 4px 8px;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.output-units:focus,
.output-desc:focus {
  outline: none;
  border-color: var(--color-accent);
}

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-elevated);
}

.btn-cancel {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--text-muted);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.85rem;
}

.btn-cancel:hover {
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.btn-save {
  padding: 8px 20px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
}

.btn-save:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

.btn-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Monaco theme overrides */
:deep(.error-line) {
  background: var(--color-error-bg);
}

:deep(.error-glyph) {
  background: var(--color-error);
  border-radius: 50%;
  margin-left: 4px;
}
</style>
