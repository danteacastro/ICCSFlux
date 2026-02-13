<script setup lang="ts">
/**
 * GcOverviewWidget - Multi-GC Instrument Overview Dashboard
 *
 * Displays a summary of all GC instruments discovered via MQTT heartbeats.
 * Each GC node is shown as a card with:
 *   - Online/offline status dot
 *   - Current run info (run number, progress bar, elapsed time) or idle state
 *   - Queue depth and last analysis time
 *   - Start/stop run buttons
 *
 * Bottom section: combined run queue table from all nodes.
 *
 * MQTT Topics:
 *   - nisystem/nodes/+/heartbeat         (filter node_type === 'gc')
 *   - nisystem/nodes/+/gc/run_progress   (active run progress)
 *   - nisystem/nodes/+/gc/analysis       (last analysis info)
 *   - nisystem/nodes/+/gc/run_started    (mark node as running)
 *   - nisystem/nodes/+/gc/queue          (queue data for combined table)
 */
import { ref, computed, onUnmounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import type { WidgetConfig, GCRunProgress, GCAnalysisResult } from '../types'
import GcRunQueueModal from '../components/GcRunQueue.vue'

const props = defineProps<{
  widget: WidgetConfig
}>()

const mqtt = useMqtt('nisystem')

// ============================================================================
// GC Node State
// ============================================================================

interface GcNodeState {
  nodeId: string
  nodeName: string
  status: 'online' | 'offline'
  lastSeen: number
  gcType: string
  simulationMode: boolean
  // Run state
  running: boolean
  runNumber: number
  runElapsedS: number
  runDurationS: number
  runProgress: number
  runPoints: number
  maxVoltage: number
  lastVoltage: number
  // Queue
  queueDepth: number
  queueRuns: QueuedRun[]
  // Last analysis
  lastAnalysisTime: string | null
  lastAnalysisRunNumber: number | null
  lastAnalysisMethod: string | null
}

interface QueuedRun {
  run_id: string
  sample_id: string
  run_type: 'sample' | 'blank' | 'calibration' | 'check_standard'
  method: string
  port?: number
  priority?: number
  notes?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  node_id: string
}

const gcNodes = ref<Map<string, GcNodeState>>(new Map())
const selectedNodeId = ref<string | null>(null)
const showRunQueue = ref(false)

// Heartbeat stale threshold (15 seconds)
const STALE_THRESHOLD_MS = 15000

// ============================================================================
// MQTT Subscriptions
// ============================================================================

function extractNodeId(topic: string): string | null {
  const match = topic.match(/^nisystem\/nodes\/([^/]+)\//)
  return match ? match[1] ?? null : null
}

function ensureNode(nodeId: string): GcNodeState {
  if (!gcNodes.value.has(nodeId)) {
    gcNodes.value.set(nodeId, {
      nodeId,
      nodeName: nodeId,
      status: 'online',
      lastSeen: Date.now(),
      gcType: 'Unknown',
      simulationMode: false,
      running: false,
      runNumber: 0,
      runElapsedS: 0,
      runDurationS: 0,
      runProgress: 0,
      runPoints: 0,
      maxVoltage: 0,
      lastVoltage: 0,
      queueDepth: 0,
      queueRuns: [],
      lastAnalysisTime: null,
      lastAnalysisRunNumber: null,
      lastAnalysisMethod: null
    })
  }
  return gcNodes.value.get(nodeId)!
}

// Subscribe to heartbeat messages, filtering for GC nodes
const unsubHeartbeat = mqtt.subscribe<Record<string, unknown>>(
  'nisystem/nodes/+/heartbeat',
  (payload) => {
    if (payload.node_type !== 'gc') return
    const nodeId = (payload.node_id as string) || null
    if (!nodeId) return

    const node = ensureNode(nodeId)
    node.nodeName = (payload.node_name as string) || nodeId
    node.status = 'online'
    node.lastSeen = Date.now()
    node.gcType = (payload.gc_type as string) || node.gcType
    node.simulationMode = (payload.simulation_mode as boolean) || false

    // Some heartbeats include queue depth
    if (typeof payload.queue_depth === 'number') {
      node.queueDepth = payload.queue_depth
    }
    if (typeof payload.running === 'boolean') {
      node.running = payload.running
    }
    if (typeof payload.run_number === 'number') {
      node.runNumber = payload.run_number
    }

    // Trigger reactivity
    gcNodes.value = new Map(gcNodes.value)
  }
)

// Subscribe to run progress
const unsubProgress = mqtt.subscribe<GCRunProgress>(
  'nisystem/nodes/+/gc/run_progress',
  (payload) => {
    const nodeId = findNodeIdFromPayload(payload as unknown as Record<string, unknown>)
    if (!nodeId) return

    const node = ensureNode(nodeId)
    node.running = true
    node.runNumber = payload.run_number
    node.runElapsedS = payload.elapsed_s
    node.runPoints = payload.points
    node.maxVoltage = payload.max_voltage
    node.lastVoltage = payload.last_voltage

    // Estimate progress if duration is known
    if (node.runDurationS > 0) {
      node.runProgress = Math.min(100, (payload.elapsed_s / node.runDurationS) * 100)
    }

    node.lastSeen = Date.now()
    node.status = 'online'
    gcNodes.value = new Map(gcNodes.value)
  }
)

// Subscribe to analysis results
const unsubAnalysis = mqtt.subscribe<GCAnalysisResult>(
  'nisystem/nodes/+/gc/analysis',
  (payload) => {
    const nodeId = findNodeIdFromPayload(payload as unknown as Record<string, unknown>)
    if (!nodeId) return

    const node = ensureNode(nodeId)
    node.running = false
    node.runProgress = 0
    node.runElapsedS = 0
    node.lastAnalysisTime = payload.timestamp || new Date().toISOString()
    node.lastAnalysisRunNumber = payload.run_number
    node.lastAnalysisMethod = payload.method ?? null

    if (typeof payload.run_duration_s === 'number') {
      node.runDurationS = payload.run_duration_s
    }

    node.lastSeen = Date.now()
    node.status = 'online'
    gcNodes.value = new Map(gcNodes.value)
  }
)

// Subscribe to run started events
const unsubRunStarted = mqtt.subscribe<Record<string, unknown>>(
  'nisystem/nodes/+/gc/run_started',
  (payload) => {
    const nodeId = findNodeIdFromPayload(payload)
    if (!nodeId) return

    const node = ensureNode(nodeId)
    node.running = true
    node.runNumber = (payload.run_number as number) || node.runNumber + 1
    node.runElapsedS = 0
    node.runProgress = 0

    if (typeof payload.duration_s === 'number') {
      node.runDurationS = payload.duration_s
    }

    node.lastSeen = Date.now()
    node.status = 'online'
    gcNodes.value = new Map(gcNodes.value)
  }
)

// Subscribe to queue updates
const unsubQueue = mqtt.subscribe<Record<string, unknown>>(
  'nisystem/nodes/+/gc/queue',
  (payload) => {
    const nodeId = findNodeIdFromPayload(payload)
    if (!nodeId) return

    const node = ensureNode(nodeId)
    if (Array.isArray(payload.runs)) {
      node.queueRuns = (payload.runs as QueuedRun[]).map(r => ({
        ...r,
        node_id: nodeId
      }))
      node.queueDepth = node.queueRuns.filter(r => r.status === 'pending').length
    }

    node.lastSeen = Date.now()
    node.status = 'online'
    gcNodes.value = new Map(gcNodes.value)
  }
)

function findNodeIdFromPayload(payload: Record<string, unknown>): string | null {
  if (typeof payload.node_id === 'string') return payload.node_id
  // Fall back to first known GC node if only one exists
  if (gcNodes.value.size === 1) {
    return gcNodes.value.keys().next().value ?? null
  }
  return null
}

// ============================================================================
// Stale detection timer
// ============================================================================

const staleCheckInterval = setInterval(() => {
  const now = Date.now()
  let changed = false
  for (const [, node] of gcNodes.value) {
    if (node.status === 'online' && now - node.lastSeen > STALE_THRESHOLD_MS) {
      node.status = 'offline'
      node.running = false
      changed = true
    }
  }
  if (changed) {
    gcNodes.value = new Map(gcNodes.value)
  }
}, 5000)

// ============================================================================
// Computed Properties
// ============================================================================

const sortedNodes = computed(() => {
  return Array.from(gcNodes.value.values()).sort((a, b) => {
    // Online nodes first, then by name
    if (a.status !== b.status) return a.status === 'online' ? -1 : 1
    return a.nodeName.localeCompare(b.nodeName)
  })
})

const onlineCount = computed(() =>
  sortedNodes.value.filter(n => n.status === 'online').length
)

const offlineCount = computed(() =>
  sortedNodes.value.filter(n => n.status === 'offline').length
)

const totalNodes = computed(() => sortedNodes.value.length)

const combinedQueue = computed<QueuedRun[]>(() => {
  const allRuns: QueuedRun[] = []
  for (const node of gcNodes.value.values()) {
    for (const run of node.queueRuns) {
      allRuns.push({ ...run, node_id: node.nodeId })
    }
  }
  // Sort: running first, then pending, then completed
  const statusOrder: Record<string, number> = {
    running: 0,
    pending: 1,
    completed: 2,
    failed: 3,
    cancelled: 4
  }
  return allRuns.sort((a, b) => {
    const oa = statusOrder[a.status] ?? 5
    const ob = statusOrder[b.status] ?? 5
    return oa - ob
  })
})

// ============================================================================
// Actions
// ============================================================================

function startRun(nodeId: string) {
  mqtt.sendNodeCommand('commands/gc', { command: 'start_run' }, nodeId)
}

function stopRun(nodeId: string) {
  mqtt.sendNodeCommand('commands/gc', { command: 'stop_run' }, nodeId)
}

function openRunQueue(nodeId: string) {
  selectedNodeId.value = nodeId
  showRunQueue.value = true
}

function closeRunQueue() {
  showRunQueue.value = false
  selectedNodeId.value = null
}

// ============================================================================
// Formatting helpers
// ============================================================================

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTimeSince(timestamp: number): string {
  const delta = (Date.now() - timestamp) / 1000
  if (delta < 60) return `${Math.floor(delta)}s ago`
  if (delta < 3600) return `${Math.floor(delta / 60)}min ago`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`
  return `${Math.floor(delta / 86400)}d ago`
}

function formatAnalysisTime(isoTime: string | null): string {
  if (!isoTime) return '--'
  try {
    const d = new Date(isoTime)
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '--'
  }
}

function runTypeBadgeClass(runType: string): string {
  switch (runType) {
    case 'sample': return 'badge-sample'
    case 'blank': return 'badge-blank'
    case 'calibration': return 'badge-calibration'
    case 'check_standard': return 'badge-check-standard'
    default: return 'badge-sample'
  }
}

function runTypeLabel(runType: string): string {
  switch (runType) {
    case 'sample': return 'Sample'
    case 'blank': return 'Blank'
    case 'calibration': return 'Cal'
    case 'check_standard': return 'Check'
    default: return runType
  }
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'running': return 'status-running'
    case 'pending': return 'status-pending'
    case 'completed': return 'status-completed'
    case 'failed': return 'status-failed'
    case 'cancelled': return 'status-cancelled'
    default: return 'status-pending'
  }
}

// ============================================================================
// Cleanup
// ============================================================================

onUnmounted(() => {
  unsubHeartbeat()
  unsubProgress()
  unsubAnalysis()
  unsubRunStarted()
  unsubQueue()
  clearInterval(staleCheckInterval)
})
</script>

<template>
  <div class="gc-overview-widget">
    <!-- Header -->
    <div class="widget-header">
      <div class="header-title">
        <svg class="header-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 3h6v11a3 3 0 01-3 3h0a3 3 0 01-3-3V3z"/>
          <path d="M12 17v4"/>
          <path d="M8 21h8"/>
          <path d="M6 3h12"/>
        </svg>
        <span>GC Instruments</span>
      </div>
      <div class="header-counts">
        <span v-if="onlineCount > 0" class="count-online">{{ onlineCount }} online</span>
        <span v-if="offlineCount > 0" class="count-offline">{{ offlineCount }} offline</span>
        <span v-if="totalNodes === 0" class="count-empty">No GC nodes</span>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="totalNodes === 0" class="empty-state">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
        <path d="M9 3h6v11a3 3 0 01-3 3h0a3 3 0 01-3-3V3z"/>
        <path d="M12 17v4"/>
        <path d="M8 21h8"/>
        <path d="M6 3h12"/>
      </svg>
      <span>Waiting for GC node heartbeats...</span>
    </div>

    <!-- GC Node Cards -->
    <div v-else class="cards-container">
      <div
        v-for="node in sortedNodes"
        :key="node.nodeId"
        class="gc-card"
        :class="{
          online: node.status === 'online',
          offline: node.status === 'offline',
          running: node.running
        }"
        @click="openRunQueue(node.nodeId)"
      >
        <!-- Card Header -->
        <div class="card-header">
          <span class="card-name" :title="node.nodeId">{{ node.nodeName }}</span>
          <div class="card-status">
            <span class="status-dot" :class="node.status === 'online' ? 'dot-online' : 'dot-offline'"></span>
            <span class="status-label">{{ node.status === 'online' ? 'Online' : 'Offline' }}</span>
          </div>
        </div>

        <!-- Offline card content -->
        <template v-if="node.status === 'offline'">
          <div class="card-offline-info">
            <span class="offline-label">Last seen</span>
            <span class="offline-time">{{ formatTimeSince(node.lastSeen) }}</span>
          </div>
        </template>

        <!-- Online card content -->
        <template v-else>
          <!-- Running state: progress bar -->
          <template v-if="node.running">
            <div class="run-info">
              <span class="run-label">Run #{{ node.runNumber }}</span>
              <span class="run-elapsed">{{ formatElapsed(node.runElapsedS) }}<template v-if="node.runDurationS > 0">/{{ formatElapsed(node.runDurationS) }}</template></span>
            </div>
            <div class="progress-bar-track">
              <div
                class="progress-bar-fill"
                :style="{ width: `${Math.min(node.runProgress, 100)}%` }"
              ></div>
            </div>
            <div class="progress-pct">{{ Math.round(node.runProgress) }}%</div>
          </template>

          <!-- Idle state -->
          <template v-else>
            <div class="idle-info">
              <span class="idle-label">Idle</span>
              <div class="idle-details">
                <span v-if="node.queueDepth > 0" class="queue-badge">
                  Queue: {{ node.queueDepth }}
                </span>
                <span v-if="node.lastAnalysisTime" class="last-analysis">
                  Last: {{ formatAnalysisTime(node.lastAnalysisTime) }}
                </span>
              </div>
            </div>
          </template>

          <!-- Action buttons -->
          <div class="card-actions">
            <button
              v-if="node.running"
              class="btn-stop"
              @click.stop="stopRun(node.nodeId)"
              title="Stop current run"
            >
              Stop
            </button>
            <button
              v-else
              class="btn-start"
              @click.stop="startRun(node.nodeId)"
              title="Start a new run"
            >
              Start
            </button>
          </div>
        </template>

        <!-- GC type badge -->
        <div v-if="node.gcType && node.gcType !== 'Unknown'" class="gc-type-badge">
          {{ node.gcType }}
        </div>
        <div v-if="node.simulationMode" class="sim-badge">SIM</div>
      </div>
    </div>

    <!-- Combined Run Queue Table -->
    <div v-if="combinedQueue.length > 0" class="queue-section">
      <div class="queue-header">
        <span class="queue-title">Combined Run Queue</span>
        <span class="queue-count">{{ combinedQueue.length }} runs</span>
      </div>
      <div class="queue-table-wrapper">
        <table class="queue-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Node</th>
              <th>Sample</th>
              <th>Type</th>
              <th>Method</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(run, idx) in combinedQueue.slice(0, 20)"
              :key="run.run_id || idx"
              class="queue-row"
              :class="statusBadgeClass(run.status)"
            >
              <td class="col-idx">{{ idx + 1 }}</td>
              <td class="col-node">{{ gcNodes.get(run.node_id)?.nodeName || run.node_id }}</td>
              <td class="col-sample">{{ run.sample_id }}</td>
              <td class="col-type">
                <span class="run-type-badge" :class="runTypeBadgeClass(run.run_type)">
                  {{ runTypeLabel(run.run_type) }}
                </span>
              </td>
              <td class="col-method">{{ run.method }}</td>
              <td class="col-status">
                <span class="status-badge" :class="statusBadgeClass(run.status)">
                  {{ run.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="combinedQueue.length > 20" class="queue-overflow">
          +{{ combinedQueue.length - 20 }} more runs
        </div>
      </div>
    </div>

    <!-- Run Queue Modal (GcRunQueue component) -->
    <GcRunQueueModal
      v-if="showRunQueue && selectedNodeId"
      :node-id="selectedNodeId"
      :visible="showRunQueue"
      @close="closeRunQueue"
    />
  </div>
</template>


<style scoped>
.gc-overview-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--bg-widget, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2d2d44);
  gap: 8px;
  overflow: hidden;
}

/* ===== Header ===== */
.widget-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color, #2d2d44);
  flex-shrink: 0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 0.8rem;
  color: var(--text-primary, #e2e8f0);
}

.header-icon {
  color: var(--text-secondary, #94a3b8);
  flex-shrink: 0;
}

.header-counts {
  display: flex;
  gap: 8px;
  font-size: 0.65rem;
}

.count-online {
  color: var(--color-success, #22c55e);
}

.count-offline {
  color: var(--text-muted, #6b7280);
}

.count-empty {
  color: var(--text-muted, #6b7280);
  font-style: italic;
}

/* ===== Empty State ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 8px;
  color: var(--text-muted, #6b7280);
  font-size: 0.75rem;
}

/* ===== Card Container ===== */
.cards-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  overflow-y: auto;
  flex: 1;
  align-content: flex-start;
}

/* ===== GC Card ===== */
.gc-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  min-width: 140px;
  flex: 1 1 140px;
  max-width: 200px;
  background: var(--bg-secondary, #16162a);
  border-radius: 6px;
  border: 1px solid var(--border-color, #2d2d44);
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.gc-card:hover {
  border-color: var(--text-secondary, #94a3b8);
  box-shadow: 0 0 8px rgba(148, 163, 184, 0.1);
}

.gc-card.offline {
  opacity: 0.55;
}

.gc-card.running {
  border-color: var(--color-info, #3b82f6);
}

/* Card header */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 4px;
}

.card-name {
  font-weight: 600;
  font-size: 0.75rem;
  color: var(--text-primary, #e2e8f0);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-status {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot-online {
  background: var(--color-success, #22c55e);
  box-shadow: 0 0 4px var(--color-success, #22c55e);
}

.dot-offline {
  background: var(--text-muted, #6b7280);
}

.status-label {
  font-size: 0.55rem;
  text-transform: uppercase;
  color: var(--text-muted, #6b7280);
}

.gc-card.online .status-label {
  color: var(--color-success, #22c55e);
}

/* Offline info */
.card-offline-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 0;
}

.offline-label {
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
}

.offline-time {
  font-size: 0.7rem;
  color: var(--text-secondary, #94a3b8);
  font-family: 'JetBrains Mono', monospace;
}

/* Run info (active run) */
.run-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.run-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--color-info, #3b82f6);
}

.run-elapsed {
  font-size: 0.6rem;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-secondary, #94a3b8);
}

/* Progress bar */
.progress-bar-track {
  width: 100%;
  height: 6px;
  background: var(--bg-surface, #0f0f1a);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--color-info, #3b82f6);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-pct {
  font-size: 0.55rem;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-secondary, #94a3b8);
  text-align: right;
}

/* Idle info */
.idle-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.idle-label {
  font-size: 0.68rem;
  color: var(--text-muted, #6b7280);
}

.idle-details {
  display: flex;
  gap: 6px;
  align-items: center;
}

.queue-badge {
  font-size: 0.58rem;
  padding: 1px 5px;
  background: rgba(59, 130, 246, 0.15);
  color: var(--color-info, #3b82f6);
  border-radius: 3px;
  font-weight: 500;
}

.last-analysis {
  font-size: 0.55rem;
  color: var(--text-muted, #6b7280);
  font-family: 'JetBrains Mono', monospace;
}

/* Card actions */
.card-actions {
  display: flex;
  gap: 4px;
  margin-top: 2px;
}

.btn-start,
.btn-stop {
  flex: 1;
  padding: 3px 8px;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-start {
  background: var(--color-success, #22c55e);
  color: #fff;
}

.btn-start:hover {
  background: #16a34a;
}

.btn-stop {
  background: var(--color-error, #ef4444);
  color: #fff;
}

.btn-stop:hover {
  background: #dc2626;
}

/* GC Type / SIM badges */
.gc-type-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  font-size: 0.45rem;
  padding: 1px 4px;
  background: rgba(148, 163, 184, 0.15);
  color: var(--text-muted, #6b7280);
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.sim-badge {
  position: absolute;
  bottom: 4px;
  right: 4px;
  font-size: 0.45rem;
  padding: 1px 4px;
  background: #7c3aed;
  color: #fff;
  border-radius: 2px;
  font-weight: 700;
}

/* ===== Queue Section ===== */
.queue-section {
  flex-shrink: 0;
  border-top: 1px solid var(--border-color, #2d2d44);
  padding-top: 6px;
  max-height: 200px;
  display: flex;
  flex-direction: column;
}

.queue-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.queue-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.queue-count {
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
}

.queue-table-wrapper {
  overflow-y: auto;
  flex: 1;
}

.queue-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.62rem;
}

.queue-table th {
  position: sticky;
  top: 0;
  background: var(--bg-secondary, #16162a);
  color: var(--text-muted, #6b7280);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  font-size: 0.55rem;
  padding: 3px 6px;
  text-align: left;
  border-bottom: 1px solid var(--border-color, #2d2d44);
}

.queue-table td {
  padding: 3px 6px;
  color: var(--text-primary, #e2e8f0);
  border-bottom: 1px solid rgba(45, 45, 68, 0.5);
  white-space: nowrap;
}

.queue-row:hover {
  background: rgba(255, 255, 255, 0.03);
}

.col-idx {
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted, #6b7280);
  width: 24px;
}

.col-node {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-sample {
  font-family: 'JetBrains Mono', monospace;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-method {
  max-width: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Run type badges */
.run-type-badge {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.55rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.2px;
}

.badge-sample {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.badge-blank {
  background: rgba(107, 114, 128, 0.2);
  color: #9ca3af;
}

.badge-calibration {
  background: rgba(34, 197, 94, 0.2);
  color: #4ade80;
}

.badge-check-standard {
  background: rgba(249, 115, 22, 0.2);
  color: #fb923c;
}

/* Status badge */
.status-badge {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.52rem;
  font-weight: 600;
  text-transform: uppercase;
}

.status-running {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}

.status-pending {
  background: rgba(107, 114, 128, 0.15);
  color: #9ca3af;
}

.status-completed {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.status-failed {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.status-cancelled {
  background: rgba(249, 115, 22, 0.15);
  color: #fb923c;
}

.queue-overflow {
  text-align: center;
  padding: 4px;
  font-size: 0.58rem;
  color: var(--text-muted, #6b7280);
  font-style: italic;
}

/* ===== Light theme overrides ===== */
:root.light .gc-overview-widget {
  background: var(--bg-widget, #ffffff);
  border-color: var(--border-color, #e2e8f0);
}

:root.light .gc-card {
  background: var(--bg-secondary, #f8fafc);
  border-color: var(--border-color, #e2e8f0);
}

:root.light .gc-card:hover {
  border-color: var(--text-secondary, #64748b);
  box-shadow: 0 0 8px rgba(100, 116, 139, 0.1);
}

:root.light .card-name {
  color: var(--text-primary, #1e293b);
}

:root.light .queue-table th {
  background: var(--bg-secondary, #f8fafc);
  color: var(--text-muted, #94a3b8);
}

:root.light .queue-table td {
  color: var(--text-primary, #1e293b);
  border-bottom-color: var(--border-color, #e2e8f0);
}

:root.light .progress-bar-track {
  background: var(--bg-surface, #e2e8f0);
}

:root.light .gc-type-badge {
  background: rgba(100, 116, 139, 0.15);
  color: var(--text-muted, #94a3b8);
}

:root.light .sim-badge {
  background: #8b5cf6;
}

:root.light .queue-badge {
  background: rgba(59, 130, 246, 0.1);
}
</style>
