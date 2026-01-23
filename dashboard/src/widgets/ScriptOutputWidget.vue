<script setup lang="ts">
/**
 * Script Output Widget
 *
 * Dashboard widget that shows script console output - print statements,
 * errors, and status from backend Python scripts.
 *
 * Can show all scripts combined or filter to a specific script.
 */
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useBackendScripts } from '../composables/useBackendScripts'

const props = defineProps<{
  widgetId: string
  label?: string
  scriptId?: string  // Optional: filter to specific script (empty = all scripts)
  maxLines?: number  // Max lines to show (default 100)
  showStatus?: boolean  // Show script status bar (default true)
}>()

const backendScripts = useBackendScripts()
const outputRef = ref<HTMLDivElement | null>(null)
const autoScroll = ref(true)

const maxLines = computed(() => props.maxLines || 100)
const showStatus = computed(() => props.showStatus !== false)

// Get outputs - filtered by scriptId if specified, or all
const filteredOutputs = computed(() => {
  const outputs: Array<{ scriptId: string; scriptName: string; type: string; message: string; timestamp: number }> = []

  for (const [scriptId, scriptOutputs] of Object.entries(backendScripts.scriptOutputs.value)) {
    // Filter by scriptId if specified
    if (props.scriptId && scriptId !== props.scriptId) continue

    const script = backendScripts.scripts.value[scriptId]
    const scriptName = script?.name || scriptId.slice(0, 8)

    for (const output of scriptOutputs) {
      outputs.push({ ...output, scriptId, scriptName })
    }
  }

  // Sort by timestamp and limit
  return outputs
    .sort((a, b) => a.timestamp - b.timestamp)
    .slice(-maxLines.value)
})

// Get running scripts count or specific script status
const statusInfo = computed(() => {
  if (props.scriptId) {
    // Specific script status
    const script = backendScripts.scripts.value[props.scriptId]
    if (!script) return { text: 'Script not found', state: 'error' }
    return {
      text: `${script.name}: ${script.state}`,
      state: script.state,
      iterations: script.iterations,
      error: script.errorMessage
    }
  } else {
    // All scripts summary
    const running = backendScripts.runningScripts.value.length
    const total = backendScripts.scriptsList.value.length
    const errors = backendScripts.scriptsList.value.filter(s => s.state === 'error').length

    if (errors > 0) {
      return { text: `${running}/${total} running, ${errors} error(s)`, state: 'error' }
    }
    if (running > 0) {
      return { text: `${running}/${total} scripts running`, state: 'running' }
    }
    return { text: `${total} scripts (none running)`, state: 'idle' }
  }
})

// Format timestamp
function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

// Auto-scroll to bottom when new output arrives
watch(filteredOutputs, () => {
  if (autoScroll.value) {
    scrollToBottom()
  }
}, { deep: true })

function scrollToBottom() {
  nextTick(() => {
    if (outputRef.value) {
      outputRef.value.scrollTop = outputRef.value.scrollHeight
    }
  })
}

// Clear output
function clearOutput() {
  if (props.scriptId) {
    backendScripts.clearScriptOutput(props.scriptId)
  } else {
    backendScripts.clearAllOutput()
  }
}

// Toggle auto-scroll
function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  if (autoScroll.value) {
    scrollToBottom()
  }
}

const displayLabel = computed(() => {
  if (props.label) return props.label
  if (props.scriptId) {
    const script = backendScripts.scripts.value[props.scriptId]
    return script?.name || 'Script Output'
  }
  return 'Script Output'
})
</script>

<template>
  <div class="script-output-widget">
    <div class="widget-header">
      <span class="widget-title">{{ displayLabel }}</span>
      <div class="header-actions">
        <button
          class="action-btn"
          :class="{ active: autoScroll }"
          @click="toggleAutoScroll"
          title="Auto-scroll"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M19 12l-7 7-7-7"/>
          </svg>
        </button>
        <button class="action-btn" @click="clearOutput" title="Clear output">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Status Bar -->
    <div v-if="showStatus" class="status-bar" :class="statusInfo.state">
      <span class="status-indicator"></span>
      <span class="status-text">{{ statusInfo.text }}</span>
      <span v-if="statusInfo.iterations" class="iterations">{{ statusInfo.iterations }} iterations</span>
    </div>

    <!-- Output Log -->
    <div ref="outputRef" class="output-container">
      <div v-if="filteredOutputs.length === 0" class="empty-state">
        No output yet
      </div>
      <div
        v-for="(line, idx) in filteredOutputs"
        :key="idx"
        class="output-line"
        :class="line.type"
      >
        <span class="line-time">{{ formatTime(line.timestamp) }}</span>
        <span v-if="!scriptId" class="line-script">{{ line.scriptName }}</span>
        <span class="line-message">{{ line.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.script-output-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d1a;
  border-radius: 4px;
  border: 1px solid #2a2a4a;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 0.7rem;
  overflow: hidden;
}

.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a4a;
}

.widget-title {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 2px 4px;
  display: flex;
  align-items: center;
  border-radius: 2px;
}

.action-btn:hover {
  color: #aaa;
  background: #2a2a4a;
}

.action-btn.active {
  color: #60a5fa;
}

/* Status Bar */
.status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 0.65rem;
  border-bottom: 1px solid #2a2a4a;
}

.status-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #666;
}

.status-bar.running .status-indicator {
  background: #22c55e;
  box-shadow: 0 0 4px #22c55e;
  animation: pulse 1.5s ease-in-out infinite;
}

.status-bar.error .status-indicator {
  background: #ef4444;
  box-shadow: 0 0 4px #ef4444;
}

.status-bar.idle .status-indicator {
  background: #6b7280;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  color: #94a3b8;
  flex: 1;
}

.iterations {
  color: #666;
}

/* Output Container */
.output-container {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
  min-height: 40px;
}

.empty-state {
  color: #555;
  text-align: center;
  padding: 20px;
  font-style: italic;
}

.output-line {
  display: flex;
  gap: 6px;
  padding: 1px 4px;
  line-height: 1.4;
  border-radius: 2px;
}

.output-line:hover {
  background: rgba(255, 255, 255, 0.03);
}

.line-time {
  color: #555;
  flex-shrink: 0;
}

.line-script {
  color: #8b5cf6;
  flex-shrink: 0;
  max-width: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.line-message {
  color: #94a3b8;
  word-break: break-word;
  flex: 1;
}

/* Output types */
.output-line.stdout .line-message {
  color: #e2e8f0;
}

.output-line.info .line-message {
  color: #60a5fa;
}

.output-line.warning .line-message {
  color: #fbbf24;
}

.output-line.error .line-message {
  color: #f87171;
}

/* Scrollbar */
.output-container::-webkit-scrollbar {
  width: 6px;
}

.output-container::-webkit-scrollbar-track {
  background: #0d0d1a;
}

.output-container::-webkit-scrollbar-thumb {
  background: #3a3a5a;
  border-radius: 3px;
}

.output-container::-webkit-scrollbar-thumb:hover {
  background: #4a4a6a;
}
</style>
