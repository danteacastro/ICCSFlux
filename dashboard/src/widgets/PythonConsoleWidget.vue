<script setup lang="ts">
/**
 * Python Console Widget
 *
 * Interactive Python REPL widget that can be placed on the dashboard.
 * Sends commands to the backend via MQTT and displays results.
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

// Subscribe to console response topic
let consoleResponseHandler: ((data: any) => void) | null = null

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

  const unsubscribe = mqtt.subscribe('nisystem/nodes/+/console/result', consoleResponseHandler)

  // Add welcome message
  outputLines.value.push({
    type: 'info',
    text: '# Python Console - Access tags, outputs, session',
    timestamp: Date.now()
  })

  // Clean up subscription on unmount
  onUnmounted(() => {
    unsubscribe()
  })
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

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    executeCommand()
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
      <input
        ref="inputRef"
        v-model="commandInput"
        type="text"
        class="command-input"
        placeholder="Python command..."
        @keydown="handleKeydown"
        :disabled="pendingCommand !== null || !mqtt.connected.value"
        spellcheck="false"
        autocomplete="off"
      />
    </div>
  </div>
</template>

<style scoped>
.python-console-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d1a;
  border-radius: 4px;
  border: 1px solid #2a2a4a;
  font-family: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
  font-size: 0.75rem;
  overflow: hidden;
}

.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a4a;
}

.console-title {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.clear-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  border-radius: 2px;
}

.clear-btn:hover {
  color: #aaa;
  background: #2a2a4a;
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
  color: #666;
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
  background: #0a0a14;
  border-top: 1px solid #2a2a4a;
}

.prompt {
  color: #60a5fa;
  font-weight: 600;
  flex-shrink: 0;
}

.command-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #fff;
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

/* Scrollbar styling */
.console-output::-webkit-scrollbar {
  width: 6px;
}

.console-output::-webkit-scrollbar-track {
  background: #0d0d1a;
}

.console-output::-webkit-scrollbar-thumb {
  background: #3a3a5a;
  border-radius: 3px;
}

.console-output::-webkit-scrollbar-thumb:hover {
  background: #4a4a6a;
}
</style>
