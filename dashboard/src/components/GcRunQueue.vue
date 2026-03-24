<script setup lang="ts">
/**
 * GcRunQueue - Queue Management Modal/Panel for a Specific GC Node
 *
 * Features:
 *   1. Queue list: reorderable list of pending runs (drag to reorder)
 *   2. Add run form: sample_id, run_type, method, port, notes
 *   3. Batch import: paste CSV data, parse into runs
 *   4. Auto-insert settings: auto-blank every N, auto-cal every N
 *   5. Actions: start queue, pause queue, clear queue
 *   6. MQTT commands for all queue operations
 *
 * MQTT Commands (via sendNodeCommand):
 *   - queue_add: Add single run
 *   - queue_batch: Add multiple runs
 *   - queue_cancel: Cancel a specific run
 *   - queue_clear: Clear entire queue
 *   - queue_get: Request current queue
 *   - queue_reorder: Move run to new position
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const props = defineProps<{
  nodeId: string
  visible: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const mqtt = useMqtt('nisystem')

// ============================================================================
// Queue State
// ============================================================================

interface QueuedRun {
  run_id: string
  sample_id: string
  run_type: 'sample' | 'blank' | 'calibration' | 'check_standard'
  method: string
  port: number
  priority: number
  notes: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
}

const queueRuns = ref<QueuedRun[]>([])
const activeTab = ref<'queue' | 'add' | 'batch' | 'settings'>('queue')
const isLoading = ref(false)

// Drag state
const dragIndex = ref<number | null>(null)
const dragOverIndex = ref<number | null>(null)

// ============================================================================
// Add Run Form
// ============================================================================

const newRun = ref({
  sample_id: '',
  run_type: 'sample' as 'sample' | 'blank' | 'calibration' | 'check_standard',
  method: '',
  port: 1,
  notes: ''
})

const runTypeOptions = [
  { value: 'sample', label: 'Sample' },
  { value: 'blank', label: 'Blank' },
  { value: 'calibration', label: 'Calibration' },
  { value: 'check_standard', label: 'Check Standard' }
] as const

function addRun() {
  if (!newRun.value.sample_id.trim()) return

  mqtt.sendNodeCommand('commands/gc', {
    command: 'queue_add',
    sample_id: newRun.value.sample_id.trim(),
    run_type: newRun.value.run_type,
    method_name: newRun.value.method.trim(),
    port: newRun.value.port,
    notes: newRun.value.notes.trim()
  }, props.nodeId)

  // Reset form (keep method and port for convenience)
  newRun.value.sample_id = ''
  newRun.value.notes = ''

  // Switch back to queue view
  activeTab.value = 'queue'

  // Request updated queue
  requestQueue()
}

function isFormValid(): boolean {
  return newRun.value.sample_id.trim().length > 0
}

// ============================================================================
// Batch Import
// ============================================================================

const batchCsvText = ref('')
const batchParseResult = ref<{
  runs: Array<{
    sample_id: string
    run_type: string
    method: string
    port: number
    notes: string
  }>
  errors: string[]
} | null>(null)

function parseBatchCsv() {
  const lines = batchCsvText.value
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.length > 0 && !l.startsWith('#'))

  const runs: Array<{
    sample_id: string
    run_type: string
    method: string
    port: number
    notes: string
  }> = []
  const errors: string[] = []

  lines.forEach((line, idx) => {
    const parts = line.split(',').map(p => p.trim())

    if (parts.length < 1) {
      errors.push(`Line ${idx + 1}: Empty line`)
      return
    }

    const sampleId = parts[0] || ''
    if (!sampleId) {
      errors.push(`Line ${idx + 1}: Missing sample_id`)
      return
    }

    const runType = parts[1] || 'sample'
    const validTypes = ['sample', 'blank', 'calibration', 'check_standard']
    if (!validTypes.includes(runType)) {
      errors.push(`Line ${idx + 1}: Invalid run_type "${runType}" (valid: ${validTypes.join(', ')})`)
      return
    }

    const method = parts[2] || ''
    const port = parseInt(parts[3] || '1', 10) || 1
    const notes = parts[4] || ''

    runs.push({ sample_id: sampleId, run_type: runType, method, port, notes })
  })

  batchParseResult.value = { runs, errors }
}

function submitBatch() {
  if (!batchParseResult.value || batchParseResult.value.runs.length === 0) return

  mqtt.sendNodeCommand('commands/gc', {
    command: 'queue_batch',
    runs: batchParseResult.value.runs.map(r => ({
      sample_id: r.sample_id,
      run_type: r.run_type,
      method_name: r.method,
      port: r.port,
      notes: r.notes
    }))
  }, props.nodeId)

  // Clear batch form
  batchCsvText.value = ''
  batchParseResult.value = null
  activeTab.value = 'queue'
  requestQueue()
}

function clearBatchParse() {
  batchParseResult.value = null
}

// ============================================================================
// Auto-Insert Settings
// ============================================================================

const autoSettings = ref({
  autoBlankEnabled: false,
  autoBlankEveryN: 10,
  autoCalEnabled: false,
  autoCalEveryN: 20,
  defaultMethod: ''
})

function saveAutoSettings() {
  mqtt.sendNodeCommand('commands/gc', {
    command: 'queue_auto_settings',
    auto_blank_enabled: autoSettings.value.autoBlankEnabled,
    auto_blank_every_n: autoSettings.value.autoBlankEveryN,
    auto_cal_enabled: autoSettings.value.autoCalEnabled,
    auto_cal_every_n: autoSettings.value.autoCalEveryN,
    default_method: autoSettings.value.defaultMethod
  }, props.nodeId)
}

// ============================================================================
// Queue Actions
// ============================================================================

function requestQueue() {
  isLoading.value = true
  mqtt.sendNodeCommand('commands/gc', { command: 'queue_get' }, props.nodeId)
  // Loading will be cleared when we receive the queue response
  setTimeout(() => { isLoading.value = false }, 3000)
}

function cancelRun(runId: string) {
  mqtt.sendNodeCommand('commands/gc', { command: 'queue_cancel', run_id: runId }, props.nodeId)
  requestQueue()
}

function clearQueue() {
  if (!confirm('Clear all pending runs from the queue?')) return
  mqtt.sendNodeCommand('commands/gc', { command: 'queue_clear' }, props.nodeId)
  requestQueue()
}

function startQueue() {
  mqtt.sendNodeCommand('commands/gc', { command: 'start_run' }, props.nodeId)
}

function pauseQueue() {
  mqtt.sendNodeCommand('commands/gc', { command: 'pause_queue' }, props.nodeId)
}

// ============================================================================
// Drag & Reorder
// ============================================================================

function onDragStart(index: number, event: DragEvent) {
  dragIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index: number, event: DragEvent) {
  event.preventDefault()
  dragOverIndex.value = index
}

function onDragLeave() {
  dragOverIndex.value = null
}

function onDrop(targetIndex: number, event: DragEvent) {
  event.preventDefault()
  if (dragIndex.value === null || dragIndex.value === targetIndex) {
    dragIndex.value = null
    dragOverIndex.value = null
    return
  }

  const run = pendingRuns.value[dragIndex.value]
  if (run) {
    mqtt.sendNodeCommand('commands/gc', {
      command: 'queue_reorder',
      run_id: run.run_id,
      new_position: targetIndex
    }, props.nodeId)

    // Optimistic local reorder
    const items = [...pendingRuns.value]
    const [removed] = items.splice(dragIndex.value, 1)
    items.splice(targetIndex, 0, removed!)
    // Update the queue
    queueRuns.value = [
      ...queueRuns.value.filter(r => r.status !== 'pending'),
      ...items
    ]
  }

  dragIndex.value = null
  dragOverIndex.value = null
}

function onDragEnd() {
  dragIndex.value = null
  dragOverIndex.value = null
}

// ============================================================================
// MQTT Subscription for Queue Updates
// ============================================================================

const unsubQueue = mqtt.subscribe<Record<string, unknown>>(
  `nisystem/nodes/+/gc/queue`,
  (payload) => {
    const payloadNodeId = payload.node_id as string
    if (payloadNodeId !== props.nodeId) return

    if (Array.isArray(payload.runs)) {
      queueRuns.value = (payload.runs as QueuedRun[]).map(r => ({
        run_id: r.run_id || `run-${Math.random().toString(36).slice(2, 8)}`,
        sample_id: r.sample_id || '',
        run_type: r.run_type || 'sample',
        method: r.method || '',
        port: r.port || 1,
        priority: r.priority || 0,
        notes: r.notes || '',
        status: r.status || 'pending'
      }))
      isLoading.value = false
    }
  }
)

// ============================================================================
// Computed
// ============================================================================

const pendingRuns = computed(() =>
  queueRuns.value.filter(r => r.status === 'pending')
)

const runningRun = computed(() =>
  queueRuns.value.find(r => r.status === 'running')
)

const completedRuns = computed(() =>
  queueRuns.value.filter(r => r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled')
)

const totalPending = computed(() => pendingRuns.value.length)

// ============================================================================
// Formatting
// ============================================================================

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
    case 'check_standard': return 'Check Std'
    default: return runType
  }
}

// ============================================================================
// Lifecycle
// ============================================================================

onMounted(() => {
  requestQueue()
})

onUnmounted(() => {
  unsubQueue()
})

// Re-request queue when nodeId changes
watch(() => props.nodeId, () => {
  requestQueue()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="gc-queue-overlay" @click.self="emit('close')">
      <div class="gc-queue-modal">
        <!-- Modal Header -->
        <div class="modal-header">
          <div class="modal-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 3h6v11a3 3 0 01-3 3h0a3 3 0 01-3-3V3z"/>
              <path d="M12 17v4"/>
              <path d="M8 21h8"/>
              <path d="M6 3h12"/>
            </svg>
            <span>Run Queue - {{ nodeId }}</span>
            <span class="pending-count" v-if="totalPending > 0">{{ totalPending }} pending</span>
          </div>
          <button class="close-btn" @click="emit('close')" title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Tab Bar -->
        <div class="tab-bar">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'queue' }"
            @click="activeTab = 'queue'"
          >Queue</button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'add' }"
            @click="activeTab = 'add'"
          >Add Run</button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'batch' }"
            @click="activeTab = 'batch'"
          >Batch Import</button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'settings' }"
            @click="activeTab = 'settings'"
          >Auto-Insert</button>
        </div>

        <!-- Tab Content -->
        <div class="modal-body">
          <!-- ===== Queue Tab ===== -->
          <div v-if="activeTab === 'queue'" class="tab-content">
            <!-- Queue actions bar -->
            <div class="queue-actions">
              <button class="action-btn btn-start" @click="startQueue" :disabled="totalPending === 0">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                Start
              </button>
              <button class="action-btn btn-pause" @click="pauseQueue">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6zm8-14v14h4V5z"/></svg>
                Pause
              </button>
              <button class="action-btn btn-clear" @click="clearQueue" :disabled="totalPending === 0">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                Clear
              </button>
              <button class="action-btn btn-refresh" @click="requestQueue">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35A7.96 7.96 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                Refresh
              </button>
            </div>

            <!-- Loading -->
            <div v-if="isLoading" class="loading-state">
              Loading queue...
            </div>

            <!-- Currently running -->
            <div v-if="runningRun" class="running-section">
              <div class="section-label">CURRENTLY RUNNING</div>
              <div class="running-row">
                <span class="run-type-badge badge-running">Running</span>
                <span class="run-sample">{{ runningRun.sample_id }}</span>
                <span class="run-type-badge" :class="runTypeBadgeClass(runningRun.run_type)">
                  {{ runTypeLabel(runningRun.run_type) }}
                </span>
                <span class="run-method">{{ runningRun.method }}</span>
              </div>
            </div>

            <!-- Pending runs (draggable) -->
            <div class="section-label" v-if="pendingRuns.length > 0">
              PENDING ({{ pendingRuns.length }}) - drag to reorder
            </div>
            <div class="pending-list" v-if="pendingRuns.length > 0">
              <div
                v-for="(run, idx) in pendingRuns"
                :key="run.run_id"
                class="queue-item"
                :class="{
                  dragging: dragIndex === idx,
                  'drag-over': dragOverIndex === idx
                }"
                draggable="true"
                @dragstart="onDragStart(idx, $event)"
                @dragover="onDragOver(idx, $event)"
                @dragleave="onDragLeave"
                @drop="onDrop(idx, $event)"
                @dragend="onDragEnd"
              >
                <span class="drag-handle" title="Drag to reorder">
                  <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor">
                    <circle cx="2" cy="2" r="1"/>
                    <circle cx="6" cy="2" r="1"/>
                    <circle cx="2" cy="6" r="1"/>
                    <circle cx="6" cy="6" r="1"/>
                    <circle cx="2" cy="10" r="1"/>
                    <circle cx="6" cy="10" r="1"/>
                  </svg>
                </span>
                <span class="item-idx">{{ idx + 1 }}</span>
                <span class="item-sample">{{ run.sample_id }}</span>
                <span class="run-type-badge" :class="runTypeBadgeClass(run.run_type)">
                  {{ runTypeLabel(run.run_type) }}
                </span>
                <span class="item-method">{{ run.method }}</span>
                <span v-if="run.port" class="item-port">P{{ run.port }}</span>
                <span v-if="run.notes" class="item-notes" :title="run.notes">{{ run.notes }}</span>
                <button class="cancel-btn" @click="cancelRun(run.run_id)" title="Cancel run">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12"/>
                  </svg>
                </button>
              </div>
            </div>

            <!-- Empty state -->
            <div v-if="!isLoading && pendingRuns.length === 0 && !runningRun" class="empty-queue">
              <span>Queue is empty</span>
              <button class="link-btn" @click="activeTab = 'add'">Add a run</button>
            </div>

            <!-- Completed runs (collapsed) -->
            <details v-if="completedRuns.length > 0" class="completed-section">
              <summary class="section-label clickable">
                COMPLETED ({{ completedRuns.length }})
              </summary>
              <div
                v-for="run in completedRuns.slice(0, 10)"
                :key="run.run_id"
                class="queue-item completed"
              >
                <span class="item-idx">--</span>
                <span class="item-sample">{{ run.sample_id }}</span>
                <span class="run-type-badge" :class="runTypeBadgeClass(run.run_type)">
                  {{ runTypeLabel(run.run_type) }}
                </span>
                <span class="item-method">{{ run.method }}</span>
                <span class="status-tag" :class="'tag-' + run.status">{{ run.status }}</span>
              </div>
            </details>
          </div>

          <!-- ===== Add Run Tab ===== -->
          <div v-if="activeTab === 'add'" class="tab-content">
            <div class="form-section">
              <div class="form-group">
                <label class="form-label">Sample ID *</label>
                <input
                  v-model="newRun.sample_id"
                  type="text"
                  class="form-input"
                  placeholder="e.g., SAM-001"
                  @keydown.enter="addRun"
                />
              </div>

              <div class="form-group">
                <label class="form-label">Run Type</label>
                <select v-model="newRun.run_type" class="form-select">
                  <option v-for="opt in runTypeOptions" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
              </div>

              <div class="form-group">
                <label class="form-label">Method</label>
                <input
                  v-model="newRun.method"
                  type="text"
                  class="form-input"
                  placeholder="e.g., NG_Extended"
                />
              </div>

              <div class="form-group">
                <label class="form-label">Port</label>
                <input
                  v-model.number="newRun.port"
                  type="number"
                  class="form-input"
                  min="1"
                  max="16"
                />
              </div>

              <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea
                  v-model="newRun.notes"
                  class="form-textarea"
                  placeholder="Optional notes"
                  rows="2"
                ></textarea>
              </div>

              <button
                class="submit-btn"
                :disabled="!isFormValid()"
                @click="addRun"
              >
                Add to Queue
              </button>
            </div>
          </div>

          <!-- ===== Batch Import Tab ===== -->
          <div v-if="activeTab === 'batch'" class="tab-content">
            <div class="form-section">
              <div class="form-group">
                <label class="form-label">Paste CSV Data</label>
                <div class="csv-hint">
                  Format: sample_id,run_type,method,port,notes (one per line)
                </div>
                <textarea
                  v-model="batchCsvText"
                  class="form-textarea csv-input"
                  placeholder="SAM-001,sample,NG,1,First sample&#10;BLK-001,blank,NG,1,&#10;CAL-001,calibration,NG,1,Level 1"
                  rows="8"
                ></textarea>
              </div>

              <div class="batch-actions">
                <button
                  class="action-btn btn-parse"
                  :disabled="!batchCsvText.trim()"
                  @click="parseBatchCsv"
                >
                  Parse CSV
                </button>
                <button
                  v-if="batchParseResult"
                  class="action-btn btn-clear-parse"
                  @click="clearBatchParse"
                >
                  Clear
                </button>
              </div>

              <!-- Parse result preview -->
              <div v-if="batchParseResult" class="parse-result">
                <div v-if="batchParseResult.errors.length > 0" class="parse-errors">
                  <div class="error-label">Errors:</div>
                  <div v-for="(err, idx) in batchParseResult.errors" :key="idx" class="error-line">
                    {{ err }}
                  </div>
                </div>

                <div v-if="batchParseResult.runs.length > 0" class="parse-preview">
                  <div class="preview-label">
                    {{ batchParseResult.runs.length }} runs parsed:
                  </div>
                  <div class="preview-list">
                    <div v-for="(run, idx) in batchParseResult.runs.slice(0, 20)" :key="idx" class="preview-item">
                      <span class="item-idx">{{ idx + 1 }}</span>
                      <span class="item-sample">{{ run.sample_id }}</span>
                      <span class="run-type-badge" :class="runTypeBadgeClass(run.run_type)">
                        {{ runTypeLabel(run.run_type) }}
                      </span>
                      <span class="item-method">{{ run.method }}</span>
                    </div>
                    <div v-if="batchParseResult.runs.length > 20" class="preview-overflow">
                      +{{ batchParseResult.runs.length - 20 }} more
                    </div>
                  </div>

                  <button
                    class="submit-btn"
                    @click="submitBatch"
                  >
                    Add {{ batchParseResult.runs.length }} Runs to Queue
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- ===== Auto-Insert Settings Tab ===== -->
          <div v-if="activeTab === 'settings'" class="tab-content">
            <div class="form-section">
              <div class="setting-row">
                <label class="toggle-label">
                  <input
                    type="checkbox"
                    v-model="autoSettings.autoBlankEnabled"
                    class="toggle-checkbox"
                  />
                  <span class="toggle-text">Auto-insert blank every</span>
                </label>
                <input
                  v-model.number="autoSettings.autoBlankEveryN"
                  type="number"
                  class="form-input inline-input"
                  min="1"
                  max="100"
                  :disabled="!autoSettings.autoBlankEnabled"
                />
                <span class="setting-suffix">runs</span>
              </div>

              <div class="setting-row">
                <label class="toggle-label">
                  <input
                    type="checkbox"
                    v-model="autoSettings.autoCalEnabled"
                    class="toggle-checkbox"
                  />
                  <span class="toggle-text">Auto-insert calibration every</span>
                </label>
                <input
                  v-model.number="autoSettings.autoCalEveryN"
                  type="number"
                  class="form-input inline-input"
                  min="1"
                  max="100"
                  :disabled="!autoSettings.autoCalEnabled"
                />
                <span class="setting-suffix">runs</span>
              </div>

              <div class="form-group">
                <label class="form-label">Default Method Override</label>
                <input
                  v-model="autoSettings.defaultMethod"
                  type="text"
                  class="form-input"
                  placeholder="Leave blank to use per-run method"
                />
              </div>

              <button class="submit-btn" @click="saveAutoSettings">
                Save Settings
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* ===== Overlay ===== */
.gc-queue-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

/* ===== Modal ===== */
.gc-queue-modal {
  background: var(--bg-widget, #1a1a2e);
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 8px;
  width: 580px;
  max-width: 95vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

/* ===== Header ===== */
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #2d2d44);
  flex-shrink: 0;
}

.modal-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-primary, #e2e8f0);
}

.pending-count {
  font-size: 0.65rem;
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.15);
  color: var(--color-info, #3b82f6);
  border-radius: 10px;
  font-weight: 500;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-muted, #6b7280);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary, #e2e8f0);
}

/* ===== Tab Bar ===== */
.tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border-color, #2d2d44);
  padding: 0 12px;
  flex-shrink: 0;
}

.tab-btn {
  padding: 8px 14px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted, #6b7280);
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.tab-btn:hover {
  color: var(--text-secondary, #94a3b8);
}

.tab-btn.active {
  color: var(--color-info, #3b82f6);
  border-bottom-color: var(--color-info, #3b82f6);
}

/* ===== Modal Body ===== */
.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ===== Queue Actions ===== */
.queue-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color, #2d2d44);
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 4px;
  background: var(--bg-secondary, #16162a);
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  transition: background 0.15s;
}

.action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-start { color: var(--color-success, #22c55e); border-color: var(--color-success, #22c55e); }
.btn-pause { color: #f59e0b; border-color: #f59e0b; }
.btn-clear { color: var(--color-error, #ef4444); border-color: var(--color-error, #ef4444); }
.btn-refresh { color: var(--text-secondary, #94a3b8); }
.btn-parse { color: var(--color-info, #3b82f6); border-color: var(--color-info, #3b82f6); }
.btn-clear-parse { color: var(--text-muted, #6b7280); }

/* ===== Section Labels ===== */
.section-label {
  font-size: 0.58rem;
  font-weight: 700;
  color: var(--text-muted, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 6px;
  margin-bottom: 4px;
}

.section-label.clickable {
  cursor: pointer;
}

.section-label.clickable:hover {
  color: var(--text-secondary, #94a3b8);
}

/* ===== Running Section ===== */
.running-section {
  padding: 6px 0;
}

.running-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: rgba(59, 130, 246, 0.08);
  border-radius: 4px;
  border-left: 3px solid var(--color-info, #3b82f6);
}

.badge-running {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  animation: pulse-running 1.5s infinite;
}

@keyframes pulse-running {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.run-sample {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: var(--text-primary, #e2e8f0);
  font-weight: 500;
}

.run-method {
  font-size: 0.62rem;
  color: var(--text-muted, #6b7280);
}

/* ===== Queue Items ===== */
.pending-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: var(--bg-secondary, #16162a);
  border-radius: 4px;
  border: 1px solid transparent;
  transition: background 0.1s, border-color 0.1s;
}

.queue-item:hover {
  background: rgba(255, 255, 255, 0.03);
}

.queue-item.dragging {
  opacity: 0.4;
}

.queue-item.drag-over {
  border-color: var(--color-info, #3b82f6);
  background: rgba(59, 130, 246, 0.05);
}

.queue-item.completed {
  opacity: 0.5;
}

.drag-handle {
  cursor: grab;
  color: var(--text-muted, #6b7280);
  flex-shrink: 0;
  padding: 0 2px;
}

.drag-handle:active {
  cursor: grabbing;
}

.item-idx {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
  width: 18px;
  text-align: right;
  flex-shrink: 0;
}

.item-sample {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
  color: var(--text-primary, #e2e8f0);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-method {
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
  max-width: 80px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-port {
  font-size: 0.55rem;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted, #6b7280);
  padding: 1px 4px;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 2px;
  flex-shrink: 0;
}

.item-notes {
  font-size: 0.55rem;
  color: var(--text-dim, #4b5563);
  max-width: 60px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-style: italic;
}

.cancel-btn {
  background: none;
  border: none;
  color: var(--text-muted, #6b7280);
  cursor: pointer;
  padding: 2px;
  border-radius: 3px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.cancel-btn:hover {
  background: rgba(239, 68, 68, 0.15);
  color: var(--color-error, #ef4444);
}

/* Run type badges */
.run-type-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.55rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.2px;
  flex-shrink: 0;
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

/* Status tags for completed */
.status-tag {
  font-size: 0.5rem;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: 600;
  text-transform: uppercase;
  flex-shrink: 0;
}

.tag-completed { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.tag-failed { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.tag-cancelled { background: rgba(249, 115, 22, 0.15); color: #fb923c; }

/* Empty state */
.empty-queue {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: var(--text-muted, #6b7280);
  font-size: 0.75rem;
}

.link-btn {
  background: none;
  border: none;
  color: var(--color-info, #3b82f6);
  cursor: pointer;
  font-size: 0.7rem;
  text-decoration: underline;
}

.link-btn:hover {
  color: #60a5fa;
}

/* Loading */
.loading-state {
  text-align: center;
  padding: 16px;
  color: var(--text-muted, #6b7280);
  font-size: 0.7rem;
}

/* Completed section */
.completed-section {
  margin-top: 4px;
}

.completed-section summary {
  list-style: none;
}

.completed-section summary::-webkit-details-marker {
  display: none;
}

/* ===== Form Styles ===== */
.form-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-label {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.form-input,
.form-select,
.form-textarea {
  padding: 6px 10px;
  background: var(--bg-secondary, #16162a);
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 4px;
  color: var(--text-primary, #e2e8f0);
  font-size: 0.75rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  border-color: var(--color-info, #3b82f6);
}

.form-select {
  cursor: pointer;
}

.form-textarea {
  resize: vertical;
  min-height: 40px;
}

.csv-input {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
}

.csv-hint {
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
  font-style: italic;
  margin-bottom: 2px;
}

.submit-btn {
  padding: 8px 16px;
  background: var(--color-info, #3b82f6);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.submit-btn:hover:not(:disabled) {
  background: #2563eb;
}

.submit-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== Batch Parse Results ===== */
.batch-actions {
  display: flex;
  gap: 6px;
}

.parse-result {
  margin-top: 8px;
}

.parse-errors {
  padding: 6px 8px;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 4px;
  margin-bottom: 8px;
}

.error-label {
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--color-error, #ef4444);
  margin-bottom: 4px;
}

.error-line {
  font-size: 0.6rem;
  color: #f87171;
  padding: 1px 0;
}

.parse-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.preview-label {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--color-success, #22c55e);
}

.preview-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 150px;
  overflow-y: auto;
}

.preview-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  background: var(--bg-secondary, #16162a);
  border-radius: 3px;
  font-size: 0.62rem;
}

.preview-overflow {
  text-align: center;
  font-size: 0.6rem;
  color: var(--text-muted, #6b7280);
  font-style: italic;
  padding: 4px;
}

/* ===== Auto-Insert Settings ===== */
.setting-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.toggle-checkbox {
  width: 14px;
  height: 14px;
  accent-color: var(--color-info, #3b82f6);
  cursor: pointer;
}

.toggle-text {
  font-size: 0.72rem;
  color: var(--text-primary, #e2e8f0);
}

.inline-input {
  width: 50px;
  text-align: center;
}

.setting-suffix {
  font-size: 0.68rem;
  color: var(--text-muted, #6b7280);
}

/* ===== Light Theme ===== */
:root.light .gc-queue-overlay {
  background: rgba(0, 0, 0, 0.35);
}

:root.light .gc-queue-modal {
  background: var(--bg-widget, #ffffff);
  border-color: var(--border-color, #e2e8f0);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

:root.light .queue-item {
  background: var(--bg-secondary, #f8fafc);
}

:root.light .form-input,
:root.light .form-select,
:root.light .form-textarea {
  background: var(--bg-secondary, #f8fafc);
  border-color: var(--border-color, #e2e8f0);
  color: var(--text-primary, #1e293b);
}

:root.light .action-btn {
  background: var(--bg-secondary, #f8fafc);
  border-color: var(--border-color, #e2e8f0);
}

:root.light .running-row {
  background: rgba(59, 130, 246, 0.05);
}
</style>
