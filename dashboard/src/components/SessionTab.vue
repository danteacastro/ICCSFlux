<script setup lang="ts">
import { ref, computed, inject, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { usePlayground } from '../composables/usePlayground'
import { useBackendScripts } from '../composables/useBackendScripts'
import { useMqtt } from '../composables/useMqtt'

const store = useDashboardStore()
const playground = usePlayground()
// Backend scripts - run on the server, not in the browser
const backendScripts = useBackendScripts()
const mqtt = useMqtt()

// Permission-based edit control (injected from App.vue)
const hasEditPermission = inject<{ value: boolean }>('canEditScripts', ref(true))

// Running Python scripts (from backend)
const runningScripts = computed(() => backendScripts.runningScripts.value)

const idleScripts = computed(() => {
  return backendScripts.scriptsList.value.filter(s => s.state !== 'running')
})

// Published variables (py.* channels from scripts)
const publishedVariables = computed(() => {
  const vars: Array<{ name: string; value: number | string }> = []
  for (const [name, val] of Object.entries(mqtt.channelValues.value)) {
    if (name.startsWith('py.')) {
      vars.push({ name: name.slice(3), value: val.value })
    }
  }
  vars.sort((a, b) => a.name.localeCompare(b.name))
  return vars
})

// All script outputs combined and sorted by timestamp
const allScriptOutputs = computed(() => {
  const outputs: Array<{ scriptId: string; type: string; message: string; timestamp: number }> = []
  for (const [scriptId, scriptOutputs] of Object.entries(backendScripts.scriptOutputs.value)) {
    for (const output of scriptOutputs) {
      outputs.push({ ...output, scriptId })
    }
  }
  return outputs.sort((a, b) => a.timestamp - b.timestamp)
})

// Get script name by ID
function getScriptName(scriptId: string): string {
  const script = backendScripts.scripts.value[scriptId]
  return script?.name || scriptId.slice(0, 8)
}

// Format duration
function formatDuration(ms: number | undefined): string {
  if (!ms) return '--'
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  if (hours > 0) {
    return `${hours}h ${minutes % 60}m ${seconds % 60}s`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}

// Get elapsed time for a script
function getScriptElapsed(scriptId: string): string {
  const script = backendScripts.scripts.value[scriptId]
  if (!script?.startedAt) return '--'
  const elapsed = Date.now() - script.startedAt
  return formatDuration(elapsed)
}

onMounted(() => {
  playground.refreshSessionStatus()
  // Request script list from backend
  backendScripts.requestScriptList()
})
</script>

<template>
  <div class="session-tab">
    <div class="tab-header">
      <div class="header-left">
        <h2>Session Monitor</h2>
        <p class="subtitle">Overview of all active scripts, jobs, and recording status</p>
      </div>
      <div class="header-status">
        <div class="status-pill" :class="{ active: store.isAcquiring }">
          <span class="status-dot" :class="{ active: store.isAcquiring }"></span>
          <span class="pill-label">Acquisition</span>
          <span class="pill-value">{{ store.isAcquiring ? 'Running' : 'Stopped' }}</span>
        </div>
        <div class="status-pill" :class="{ active: store.isRecording }">
          <span class="status-dot recording" :class="{ active: store.isRecording }"></span>
          <span class="pill-label">Recording</span>
          <span class="pill-value">{{ store.isRecording ? 'Recording' : 'Idle' }}</span>
        </div>
        <div class="status-pill" :class="{ active: playground.isSessionActive.value }">
          <span class="status-dot session" :class="{ active: playground.isSessionActive.value }"></span>
          <span class="pill-label">Session</span>
          <span class="pill-value">{{ playground.isSessionActive.value ? 'Active' : 'Inactive' }}</span>
        </div>
        <div class="status-pill elapsed-pill" v-if="playground.isSessionActive.value">
          <span class="pill-value elapsed">{{ playground.sessionElapsed.value }}</span>
        </div>
      </div>
    </div>

    <div class="session-grid">
      <!-- Published Variables Panel -->
      <div class="status-panel published-variables">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20V10"/>
            <path d="M18 20V4"/>
            <path d="M6 20v-4"/>
          </svg>
          Published Variables
          <span class="count-badge" v-if="publishedVariables.length > 0">{{ publishedVariables.length }}</span>
        </h3>
        <div class="values-grid" v-if="publishedVariables.length > 0">
          <div v-for="v in publishedVariables" :key="v.name" class="value-item">
            <span class="value-name">{{ v.name }}</span>
            <span class="value-number">{{ typeof v.value === 'number' ? v.value.toFixed(2) : v.value }}</span>
          </div>
        </div>
        <div class="empty-state" v-else>
          <p>No published variables</p>
          <p class="hint">Variables from running scripts will appear here</p>
        </div>
      </div>

      <!-- Running Scripts Panel -->
      <div class="status-panel running-scripts">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5,3 19,12 5,21 5,3"/>
          </svg>
          Running Scripts
          <span class="count-badge" v-if="runningScripts.length > 0">{{ runningScripts.length }}</span>
        </h3>

        <div class="scripts-list" v-if="runningScripts.length > 0">
          <div
            v-for="script in runningScripts"
            :key="script.id"
            class="script-item running"
          >
            <div class="script-info">
              <span class="script-name">{{ script.name }}</span>
              <span class="script-mode">{{ script.runMode }}</span>
            </div>
            <div class="script-stats">
              <span class="stat">
                <span class="stat-label">Elapsed:</span>
                <span class="stat-value">{{ getScriptElapsed(script.id) }}</span>
              </span>
              <span class="stat" v-if="script.iterations > 0">
                <span class="stat-label">Iterations:</span>
                <span class="stat-value">{{ script.iterations }}</span>
              </span>
            </div>
            <button
              class="btn btn-sm btn-danger"
              @click="backendScripts.stopScript(script.id)"
              :disabled="!hasEditPermission"
            >
              Stop
            </button>
          </div>
        </div>

        <div class="empty-state" v-else>
          <p>No scripts currently running</p>
        </div>
      </div>

      <!-- Available Scripts Panel -->
      <div class="status-panel idle-scripts">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="6" y="4" width="4" height="16"/>
            <rect x="14" y="4" width="4" height="16"/>
          </svg>
          Available Scripts
        </h3>

        <div class="scripts-list compact" v-if="idleScripts.length > 0">
          <div
            v-for="script in idleScripts"
            :key="script.id"
            class="script-item idle"
          >
            <div class="script-info">
              <span class="script-name">{{ script.name }}</span>
              <span class="script-mode">{{ script.runMode }}</span>
            </div>
            <span class="script-enabled" :class="{ enabled: script.enabled }">
              {{ script.enabled ? 'Enabled' : 'Disabled' }}
            </span>
            <button
              class="btn btn-sm btn-success"
              @click="backendScripts.startScript(script.id)"
              :disabled="!mqtt.connected.value || !script.enabled || !hasEditPermission"
            >
              Run
            </button>
          </div>
        </div>

        <div class="empty-state" v-else>
          <p>No scripts defined</p>
          <p class="hint">Create scripts in Python Playground</p>
        </div>
      </div>

    </div>

    <!-- Console Output - Full Width -->
    <div class="console-panel">
      <div class="console-header">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4,17 10,11 4,5"/>
            <line x1="12" y1="19" x2="20" y2="19"/>
          </svg>
          Console Output
        </h3>
      </div>

      <div class="console-output">
        <div
          v-for="(line, idx) in allScriptOutputs.slice(-50)"
          :key="idx"
          class="console-line"
          :class="line.type"
        >
          <span class="line-time">{{ new Date(line.timestamp).toLocaleTimeString() }}</span>
          <span class="line-source">[{{ getScriptName(line.scriptId) }}]</span>
          <span class="line-message">{{ line.message }}</span>
        </div>
        <div v-if="allScriptOutputs.length === 0" class="console-placeholder">
          Output from running scripts appears here
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-tab {
  padding: 1.5rem;
  height: 100%;
  overflow-y: auto;
}

.tab-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  gap: 1.5rem;
  flex-wrap: wrap;
}

.header-left h2 {
  margin: 0 0 0.25rem 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.subtitle {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

/* Inline Status Pills */
.header-status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.status-pill {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.status-pill.active {
  border-color: var(--color-success);
  color: var(--color-success);
}

.status-pill.active .pill-label {
  color: var(--color-success);
}

.pill-label {
  color: var(--text-secondary);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.pill-value {
  font-weight: 500;
}

.pill-value.elapsed {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  color: var(--color-success);
}

.elapsed-pill {
  border-color: var(--color-success);
}

.session-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
  gap: 1.25rem;
}

/* Status Panels */
.status-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1rem;
}

.status-panel h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 1rem 0;
  font-size: 1rem;
  color: var(--text-primary);
}

.count-badge {
  background: var(--color-accent);
  color: white;
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-weight: 600;
}

/* Status Dots */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}

.status-dot.active {
  background: var(--color-success);
  animation: pulse 1.5s infinite;
}

.status-dot.recording.active {
  background: var(--color-error);
}

.status-dot.session.active {
  background: #8b5cf6;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Scripts List */
.scripts-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.scripts-list.compact {
  gap: 0.5rem;
}

.script-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.script-item.running {
  border-color: var(--color-success);
  background: rgba(34, 197, 94, 0.05);
}

.script-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.script-name {
  font-weight: 500;
  color: var(--text-primary);
}

.script-mode {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-transform: capitalize;
}

.script-stats {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
}

.stat {
  display: flex;
  gap: 0.25rem;
}

.stat-label {
  color: var(--text-secondary);
}

.stat-value {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  color: var(--text-primary);
}

.script-enabled {
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  background: var(--text-muted);
  color: var(--text-bright);
}

.script-enabled.enabled {
  background: rgba(34, 197, 94, 0.2);
  color: var(--color-success);
}

/* Values Grid */
.values-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.5rem;
}

.value-item {
  display: flex;
  flex-direction: column;
  padding: 0.5rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.value-name {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.value-number {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-success);
}

.value-units {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

/* Console Panel - Full Width */
.console-panel {
  margin-top: 1.25rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
}

.console-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1rem;
  color: var(--text-primary);
}

.console-output {
  flex: 1;
  min-height: 150px;
  max-height: 300px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 0.85rem;
  background: var(--bg-primary);
  padding: 0.75rem;
  border-radius: 0 0 8px 8px;
}

.console-placeholder {
  color: var(--text-muted);
  font-style: italic;
  padding: 1rem;
  text-align: center;
}

.console-line {
  display: flex;
  gap: 0.75rem;
  padding: 0.2rem 0;
  line-height: 1.4;
}

.line-time {
  color: var(--text-dim);
  flex-shrink: 0;
  font-size: 0.8rem;
}

.line-source {
  color: #8b5cf6;
  font-weight: 500;
  flex-shrink: 0;
}

.line-message {
  color: var(--text-bright);
  word-break: break-all;
}

.console-line.error .line-message {
  color: var(--color-error);
}

.console-line.warning .line-message {
  color: var(--color-warning-dark);
}

.console-line.info .line-message {
  color: var(--color-accent);
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 1.5rem;
  color: var(--text-secondary);
}

.empty-state p {
  margin: 0.25rem 0;
}

.empty-state .hint {
  font-size: 0.8rem;
  opacity: 0.7;
}

/* Buttons */
.btn {
  padding: 0.4rem 0.75rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  font-size: 0.8rem;
  transition: background 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-sm {
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
}

.btn-success {
  background: var(--color-success);
  color: white;
}

.btn-success:hover:not(:disabled) {
  background: var(--color-success-dark);
}

.btn-danger {
  background: var(--color-error);
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: var(--color-error-dark);
}
</style>
