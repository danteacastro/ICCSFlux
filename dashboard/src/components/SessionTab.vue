<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { usePlayground } from '../composables/usePlayground'
import { useBackendScripts } from '../composables/useBackendScripts'
import { useMqtt } from '../composables/useMqtt'

const store = useDashboardStore()
const playground = usePlayground()
// Backend scripts - run on the server, not in the browser
const backendScripts = useBackendScripts()
const mqtt = useMqtt()

// Running Python scripts (from backend)
const runningScripts = computed(() => backendScripts.runningScripts.value)

const idleScripts = computed(() => {
  return backendScripts.scriptsList.value.filter(s => s.state !== 'running')
})

// Backend connection status
const backendStatus = computed(() => {
  if (!mqtt.connected.value) return 'Disconnected'
  return 'Connected'
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
      <h2>Session Monitor</h2>
      <p class="subtitle">Overview of all active scripts, jobs, and recording status</p>
    </div>

    <div class="session-grid">
      <!-- System Status Panel -->
      <div class="status-panel system-status">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12,6 12,12 16,14"/>
          </svg>
          System Status
        </h3>
        <div class="status-grid">
          <div class="status-item">
            <span class="status-label">Acquisition</span>
            <span class="status-value" :class="{ active: store.isAcquiring }">
              <span class="status-dot" :class="{ active: store.isAcquiring }"></span>
              {{ store.isAcquiring ? 'Running' : 'Stopped' }}
            </span>
          </div>
          <div class="status-item">
            <span class="status-label">Recording</span>
            <span class="status-value" :class="{ active: store.isRecording }">
              <span class="status-dot recording" :class="{ active: store.isRecording }"></span>
              {{ store.isRecording ? 'Recording' : 'Idle' }}
            </span>
          </div>
          <div class="status-item">
            <span class="status-label">Test Session</span>
            <span class="status-value" :class="{ active: playground.isSessionActive.value }">
              <span class="status-dot session" :class="{ active: playground.isSessionActive.value }"></span>
              {{ playground.isSessionActive.value ? 'Active' : 'Inactive' }}
            </span>
          </div>
          <div class="status-item" v-if="playground.isSessionActive.value">
            <span class="status-label">Session Elapsed</span>
            <span class="status-value elapsed">{{ playground.sessionElapsed.value }}</span>
          </div>
        </div>
      </div>

      <!-- Backend Script Runtime Panel -->
      <div class="status-panel backend-status">
        <h3>
          <span class="python-icon">🐍</span>
          Script Runtime (Backend)
        </h3>
        <div class="status-grid">
          <div class="status-item">
            <span class="status-label">Backend Status</span>
            <span class="status-value" :class="{ active: mqtt.connected.value }">
              <span class="status-dot" :class="{ active: mqtt.connected.value }"></span>
              {{ backendStatus }}
            </span>
          </div>
          <div class="status-item">
            <span class="status-label">Active Scripts</span>
            <span class="status-value count">{{ runningScripts.length }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">Total Scripts</span>
            <span class="status-value count">{{ backendScripts.scriptsList.value.length }}</span>
          </div>
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
            >
              Stop
            </button>
          </div>
        </div>

        <div class="empty-state" v-else>
          <p>No scripts currently running</p>
        </div>
      </div>

      <!-- Script Info Panel -->
      <div class="status-panel script-info-panel">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="16" x2="12" y2="12"/>
            <line x1="12" y1="8" x2="12.01" y2="8"/>
          </svg>
          Script Execution
        </h3>

        <div class="info-content">
          <div class="info-item">
            <span class="info-icon">&#9888;</span>
            <span class="info-text">Scripts run on the <strong>backend</strong> (DAQ service), not in the browser.</span>
          </div>
          <div class="info-item">
            <span class="info-icon">&#9654;</span>
            <span class="info-text"><strong>Acquisition</strong> scripts auto-start when acquisition begins.</span>
          </div>
          <div class="info-item">
            <span class="info-icon">&#9654;</span>
            <span class="info-text"><strong>Session</strong> scripts auto-start when a test session begins.</span>
          </div>
          <div class="info-item">
            <span class="info-icon">&#9654;</span>
            <span class="info-text"><strong>Manual</strong> scripts must be started explicitly.</span>
          </div>
        </div>
      </div>

      <!-- Idle Scripts Panel -->
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
              :disabled="!mqtt.connected.value || !script.enabled"
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

      <!-- Console Output Panel -->
      <div class="status-panel console-output">
        <h3>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4,17 10,11 4,5"/>
            <line x1="12" y1="19" x2="20" y2="19"/>
          </svg>
          Recent Console Output
        </h3>

        <div class="console-lines" v-if="allScriptOutputs.length > 0">
          <div
            v-for="(line, idx) in allScriptOutputs.slice(-20)"
            :key="idx"
            class="console-line"
            :class="line.type"
          >
            <span class="line-time">{{ new Date(line.timestamp).toLocaleTimeString() }}</span>
            <span class="line-script">[{{ getScriptName(line.scriptId) }}]</span>
            <span class="line-message">{{ line.message }}</span>
          </div>
        </div>

        <div class="empty-state" v-else>
          <p>No console output</p>
          <p class="hint">Output from running scripts appears here</p>
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
  margin-bottom: 1.5rem;
}

.tab-header h2 {
  margin: 0 0 0.25rem 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.subtitle {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
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
  background: var(--color-primary);
  color: white;
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-weight: 600;
}

.python-icon {
  font-size: 1.1rem;
}

/* Status Grid */
.status-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

.status-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.status-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.status-value {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.status-value.active {
  color: var(--color-success);
}

.status-value.count {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-primary);
}

.status-value.elapsed {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 1.1rem;
  color: var(--color-success);
}

/* Status Dots */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #666;
}

.status-dot.active {
  background: var(--color-success);
  animation: pulse 1.5s infinite;
}

.status-dot.recording.active {
  background: #ef4444;
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
  background: #666;
  color: #ccc;
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

/* Console Output */
.console-output {
  grid-column: span 2;
}

@media (max-width: 800px) {
  .console-output {
    grid-column: span 1;
  }
}

.console-lines {
  max-height: 200px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 0.8rem;
  background: #0a0a14;
  border-radius: 4px;
  padding: 0.5rem;
}

.console-line {
  display: flex;
  gap: 0.75rem;
  padding: 0.15rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.console-line:last-child {
  border-bottom: none;
}

.line-time {
  color: #666;
  flex-shrink: 0;
}

.line-script {
  color: #8b5cf6;
  font-weight: 500;
  flex-shrink: 0;
}

.line-message {
  color: #ccc;
  word-break: break-all;
}

.console-line.error .line-message {
  color: #ef4444;
}

.console-line.warning .line-message {
  color: #f59e0b;
}

.console-line.info .line-message {
  color: #3b82f6;
}

/* Info Panel */
.info-content {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.info-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.info-icon {
  flex-shrink: 0;
  width: 1.2rem;
  text-align: center;
}

.info-text strong {
  color: var(--text-primary);
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
  background: #16a34a;
}

.btn-danger {
  background: var(--color-danger);
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}
</style>
