<script setup lang="ts">
/**
 * Python Console Widget
 *
 * Interactive Python REPL widget that can be placed on the dashboard.
 * Sends commands to the backend via MQTT and displays results.
 *
 * Features:
 * - Persistent namespace (variables survive between commands)
 * - Command history (up/down arrows)
 * - Tab completion with dropdown
 * - Magic commands (%who, %whos, %reset, %time, %help)
 */
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  widgetId: string
  label?: string
}>()

const mqtt = useMqtt('nisystem')
const store = useDashboardStore()

// Command input
const commandInput = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const outputRef = ref<HTMLDivElement | null>(null)

// Command history
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)

// Output lines
interface OutputLine {
  type: 'input' | 'output' | 'error' | 'info'
  text: string
  timestamp: number
}
const outputLines = ref<OutputLine[]>([])

// Pending command (waiting for response)
const pendingCommand = ref<string | null>(null)

// Tab completion
interface Completion {
  text: string
  type: 'variable' | 'function' | 'api' | 'attribute' | 'keyword'
  start: number
  end: number
}
const completions = ref<Completion[]>([])
const showCompletions = ref(false)
const selectedCompletionIndex = ref(0)
const completionRequestPending = ref(false)

// Subscribe to console response and completion topics
let consoleResponseHandler: ((data: any) => void) | null = null
let completionHandler: ((data: any) => void) | null = null

onMounted(() => {
  // Subscribe to console responses
  consoleResponseHandler = (data: { success: boolean; result?: string; error?: string; output?: string }) => {
    if (pendingCommand.value) {
      // Add any captured output (print statements)
      if (data.output) {
        for (const line of data.output.split('\n')) {
          if (line) {
            outputLines.value.push({
              type: 'output',
              text: line,
              timestamp: Date.now()
            })
          }
        }
      }

      // Add result or error
      if (data.success) {
        if (data.result !== undefined && data.result !== 'None' && data.result !== '') {
          outputLines.value.push({
            type: 'output',
            text: data.result,
            timestamp: Date.now()
          })
        }
      } else {
        outputLines.value.push({
          type: 'error',
          text: data.error || 'Unknown error',
          timestamp: Date.now()
        })
      }

      pendingCommand.value = null
      scrollToBottom()
    }
  }

  // Subscribe to completion responses
  completionHandler = (data: { success: boolean; completions?: Completion[]; error?: string }) => {
    completionRequestPending.value = false
    if (data.success && data.completions && data.completions.length > 0) {
      completions.value = data.completions
      selectedCompletionIndex.value = 0
      showCompletions.value = true
    } else {
      hideCompletions()
    }
  }

  const unsubscribe1 = mqtt.subscribe('nisystem/nodes/+/console/result', consoleResponseHandler)
  const unsubscribe2 = mqtt.subscribe('nisystem/nodes/+/console/complete/result', completionHandler)

  // Add welcome message
  outputLines.value.push({
    type: 'info',
    text: '# Python Console - Type %help for available commands',
    timestamp: Date.now()
  })

  // Store unsubscribers for cleanup
  cleanupFns.push(unsubscribe1, unsubscribe2)
})

// Cleanup subscriptions on unmount (must be at top level, not nested inside onMounted)
const cleanupFns: (() => void)[] = []
onUnmounted(() => {
  cleanupFns.forEach(fn => fn())
})

function scrollToBottom() {
  nextTick(() => {
    if (outputRef.value) {
      outputRef.value.scrollTop = outputRef.value.scrollHeight
    }
  })
}

function executeCommand() {
  const cmd = commandInput.value.trim()
  if (!cmd) return

  hideCompletions()

  // Add to output
  outputLines.value.push({
    type: 'input',
    text: `>>> ${cmd}`,
    timestamp: Date.now()
  })

  // Add to history
  commandHistory.value.push(cmd)
  historyIndex.value = commandHistory.value.length

  // Send to backend
  pendingCommand.value = cmd
  mqtt.sendLocalCommand('console/execute', { code: cmd })

  // Clear input
  commandInput.value = ''
  scrollToBottom()
}

function requestCompletions() {
  if (completionRequestPending.value) return
  if (!mqtt.connected.value) return

  const text = commandInput.value
  const cursorPos = inputRef.value?.selectionStart ?? text.length

  completionRequestPending.value = true
  mqtt.sendLocalCommand('console/complete', {
    text,
    cursor_pos: cursorPos
  })
}

function hideCompletions() {
  showCompletions.value = false
  completions.value = []
  selectedCompletionIndex.value = 0
}

function applyCompletion(completion: Completion) {
  const text = commandInput.value
  // Replace the partial text with the completion
  const newText = text.slice(0, completion.start) + completion.text + text.slice(completion.end)
  commandInput.value = newText

  // Move cursor to end of inserted text
  nextTick(() => {
    if (inputRef.value) {
      const newPos = completion.start + completion.text.length
      inputRef.value.setSelectionRange(newPos, newPos)
      inputRef.value.focus()
    }
  })

  hideCompletions()
}

function handleKeydown(e: KeyboardEvent) {
  // Handle completion dropdown navigation
  if (showCompletions.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      selectedCompletionIndex.value = Math.min(selectedCompletionIndex.value + 1, completions.value.length - 1)
      return
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      selectedCompletionIndex.value = Math.max(selectedCompletionIndex.value - 1, 0)
      return
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const selected = completions.value[selectedCompletionIndex.value]
      if (selected) {
        applyCompletion(selected)
      }
      return
    } else if (e.key === 'Escape') {
      e.preventDefault()
      hideCompletions()
      return
    }
  }

  // Normal key handling
  if (e.key === 'Enter') {
    executeCommand()
  } else if (e.key === 'Tab') {
    e.preventDefault()
    requestCompletions()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (historyIndex.value > 0) {
      historyIndex.value--
      commandInput.value = commandHistory.value[historyIndex.value] || ''
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIndex.value < commandHistory.value.length - 1) {
      historyIndex.value++
      commandInput.value = commandHistory.value[historyIndex.value] || ''
    } else {
      historyIndex.value = commandHistory.value.length
      commandInput.value = ''
    }
  } else if (e.key === 'l' && e.ctrlKey) {
    e.preventDefault()
    clearOutput()
  } else if (e.key === 'Escape') {
    hideCompletions()
  }
}

function handleInput() {
  // Hide completions when input changes
  if (showCompletions.value) {
    hideCompletions()
  }
}

function clearOutput() {
  outputLines.value = [{
    type: 'info',
    text: '# Console cleared',
    timestamp: Date.now()
  }]
}

function focusInput() {
  inputRef.value?.focus()
}

function getCompletionTypeClass(type: string): string {
  switch (type) {
    case 'api': return 'comp-api'
    case 'function': return 'comp-function'
    case 'variable': return 'comp-variable'
    case 'attribute': return 'comp-attribute'
    case 'keyword': return 'comp-keyword'
    default: return ''
  }
}

// Limit output lines
watch(outputLines, (lines) => {
  if (lines.length > 500) {
    outputLines.value = lines.slice(-300)
  }
}, { deep: true })

const displayLabel = computed(() => props.label || 'Python Console')
</script>

<template>
  <div class="python-console-widget" @click="focusInput">
    <div class="console-header">
      <span class="console-title">{{ displayLabel }}</span>
      <button class="clear-btn" @click.stop="clearOutput" title="Clear (Ctrl+L)">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
        </svg>
      </button>
    </div>

    <div ref="outputRef" class="console-output">
      <div
        v-for="(line, idx) in outputLines"
        :key="idx"
        class="output-line"
        :class="line.type"
      >{{ line.text }}</div>

      <div v-if="pendingCommand" class="output-line pending">
        <span class="spinner"></span> Running...
      </div>
    </div>

    <div class="console-input-row">
      <span class="prompt">&gt;&gt;&gt;</span>
      <div class="input-wrapper">
        <input
          ref="inputRef"
          v-model="commandInput"
          type="text"
          class="command-input"
          placeholder="Python command... (Tab for completion)"
          @keydown="handleKeydown"
          @input="handleInput"
          :disabled="pendingCommand !== null || !mqtt.connected.value"
          spellcheck="false"
          autocomplete="off"
        />

        <!-- Completions dropdown -->
        <div v-if="showCompletions && completions.length > 0" class="completions-dropdown">
          <div
            v-for="(comp, idx) in completions"
            :key="comp.text"
            class="completion-item"
            :class="{ selected: idx === selectedCompletionIndex, [getCompletionTypeClass(comp.type)]: true }"
            @click.stop="applyCompletion(comp)"
            @mouseenter="selectedCompletionIndex = idx"
          >
            <span class="comp-text">{{ comp.text }}</span>
            <span class="comp-type">{{ comp.type }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.python-console-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  font-family: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
  font-size: 0.75rem;
  overflow: hidden;
}

.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--bg-widget);
  border-bottom: 1px solid var(--border-color);
}

.console-title {
  font-size: 0.65rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.clear-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  border-radius: 2px;
}

.clear-btn:hover {
  color: var(--text-secondary);
  background: var(--border-color);
}

.console-output {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
  min-height: 40px;
}

.output-line {
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-all;
}

.output-line.input {
  color: #60a5fa;
}

.output-line.output {
  color: #4ade80;
}

.output-line.error {
  color: #f87171;
}

.output-line.info {
  color: var(--text-muted);
  font-style: italic;
}

.output-line.pending {
  color: #fbbf24;
  display: flex;
  align-items: center;
  gap: 6px;
}

.spinner {
  width: 10px;
  height: 10px;
  border: 2px solid #fbbf24;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.console-input-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

.prompt {
  color: #60a5fa;
  font-weight: 600;
  flex-shrink: 0;
}

.input-wrapper {
  flex: 1;
  position: relative;
}

.command-input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: inherit;
  font-size: inherit;
  padding: 2px 0;
}

.command-input::placeholder {
  color: #444;
}

.command-input:disabled {
  opacity: 0.5;
}

/* Completions dropdown */
.completions-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-widget);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.3);
  z-index: 100;
  margin-bottom: 4px;
}

.completion-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  cursor: pointer;
  border-bottom: 1px solid var(--bg-gradient-elevated);
}

.completion-item:last-child {
  border-bottom: none;
}

.completion-item:hover,
.completion-item.selected {
  background: var(--bg-gradient-elevated);
}

.comp-text {
  color: #e2e8f0;
}

.comp-type {
  font-size: 0.6rem;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--border-color);
  color: var(--text-secondary);
}

/* Completion type colors */
.comp-api .comp-text { color: #60a5fa; }
.comp-api .comp-type { background: rgba(96, 165, 250, 0.2); color: #60a5fa; }

.comp-function .comp-text { color: #c084fc; }
.comp-function .comp-type { background: rgba(192, 132, 252, 0.2); color: #c084fc; }

.comp-variable .comp-text { color: #4ade80; }
.comp-variable .comp-type { background: rgba(74, 222, 128, 0.2); color: #4ade80; }

.comp-attribute .comp-text { color: #fbbf24; }
.comp-attribute .comp-type { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }

.comp-keyword .comp-text { color: #f472b6; }
.comp-keyword .comp-type { background: rgba(244, 114, 182, 0.2); color: #f472b6; }

/* Scrollbar styling */
.console-output::-webkit-scrollbar,
.completions-dropdown::-webkit-scrollbar {
  width: 6px;
}

.console-output::-webkit-scrollbar-track,
.completions-dropdown::-webkit-scrollbar-track {
  background: var(--bg-primary);
}

.console-output::-webkit-scrollbar-thumb,
.completions-dropdown::-webkit-scrollbar-thumb {
  background: var(--border-light);
  border-radius: 3px;
}

.console-output::-webkit-scrollbar-thumb:hover,
.completions-dropdown::-webkit-scrollbar-thumb:hover {
  background: var(--bg-knob-border);
}
</style>
