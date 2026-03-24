<script setup lang="ts">
import { ref, computed } from 'vue'
import type { AcquisitionPipelineEvent, SystemHealth, SystemStatus } from '../types'

const props = defineProps<{
  health: SystemHealth | null
  events: AcquisitionPipelineEvent[]
  status: SystemStatus | null
  connected: boolean
  acquireCommandPending: boolean
  lastAcquireError: string | null
}>()

const expanded = ref(false)

// Overall health indicator color
const healthColor = computed(() => {
  if (!props.connected) return '#ef4444' // red
  if (!props.health) return '#6b7280' // gray (no data yet)

  const h = props.health
  const hasErrors = (h.scan_loop?.consecutive_errors ?? 0) > 0
    || !h.safety?.healthy
    || (h.channels?.nan_count ?? 0) > 0
  const hasCritical = (h.scan_loop?.consecutive_errors ?? 0) >= 5
    || (h.safety?.eval_failures ?? 0) >= 3

  if (hasCritical) return '#ef4444' // red
  if (hasErrors) return '#f59e0b' // yellow
  return '#22c55e' // green
})

// Pipeline stage text
const pipelineStage = computed(() => {
  if (props.acquireCommandPending) return 'PENDING...'
  if (!props.status) return 'OFFLINE'
  const state = props.status.acquisition_state || (props.status.acquiring ? 'running' : 'stopped')
  return state.toUpperCase()
})

const pipelineStageClass = computed(() => {
  if (props.acquireCommandPending) return 'stage-pending'
  if (!props.status) return 'stage-offline'
  const state = props.status.acquisition_state || (props.status.acquiring ? 'running' : 'stopped')
  if (state === 'running') return 'stage-running'
  if (state === 'initializing') return 'stage-init'
  return 'stage-stopped'
})

// Recent events (last 20)
const recentEvents = computed(() => props.events.slice(0, 20))

// Recent errors only
const recentErrors = computed(() => props.events.filter(e => e.severity === 'error').slice(0, 10))

function severityColor(severity: string) {
  if (severity === 'error') return '#ef4444'
  if (severity === 'warning') return '#f59e0b'
  return '#6b7280'
}

function formatTime(timestamp: string) {
  try {
    const d = new Date(timestamp)
    return d.toLocaleTimeString()
  } catch {
    return timestamp
  }
}

function formatEventName(event: string) {
  return event.replace(/_/g, ' ')
}

function healthDot(healthy: boolean | undefined) {
  return healthy === false ? '#ef4444' : healthy === true ? '#22c55e' : '#6b7280'
}
</script>

<template>
  <Teleport to="body">
    <!-- Mini indicator dot -->
    <div
      class="diag-mini"
      :style="{ backgroundColor: healthColor }"
      :title="'System Health: ' + pipelineStage"
      @click="expanded = !expanded"
    >
      <span v-if="acquireCommandPending" class="diag-spinner">&#8987;</span>
    </div>

    <!-- Error toast -->
    <div v-if="lastAcquireError" class="diag-error-toast">
      <span class="diag-error-icon">&#9888;</span>
      {{ lastAcquireError }}
    </div>

    <!-- Expanded panel -->
    <div v-if="expanded" class="diag-panel">
      <div class="diag-header">
        <span class="diag-title">Diagnostics</span>
        <button class="diag-close" @click="expanded = false">&times;</button>
      </div>

      <!-- Pipeline Stage -->
      <div class="diag-section">
        <div class="diag-label">Pipeline</div>
        <div :class="['diag-stage', pipelineStageClass]">{{ pipelineStage }}</div>
      </div>

      <!-- Health Indicators -->
      <div v-if="health" class="diag-section">
        <div class="diag-label">Health</div>
        <div class="diag-health-row">
          <span class="diag-dot" :style="{ backgroundColor: healthDot(health.scan_loop?.healthy) }" />
          <span>Scan Loop</span>
          <span v-if="health.scan_loop?.consecutive_errors" class="diag-badge-warn">
            {{ health.scan_loop.consecutive_errors }} errors
          </span>
        </div>
        <div class="diag-health-row">
          <span class="diag-dot" :style="{ backgroundColor: healthDot(health.hardware?.healthy) }" />
          <span>Hardware</span>
          <span v-if="health.hardware?.reader_died" class="diag-badge-err">DEAD</span>
        </div>
        <div class="diag-health-row">
          <span class="diag-dot" :style="{ backgroundColor: healthDot(health.safety?.healthy) }" />
          <span>Safety</span>
          <span v-if="health.safety?.eval_failures" class="diag-badge-warn">
            {{ health.safety.eval_failures }} failures
          </span>
        </div>
      </div>

      <!-- Channel Stats -->
      <div v-if="health" class="diag-section">
        <div class="diag-label">Channels</div>
        <div class="diag-stats">
          <span>Total: {{ health.channels?.total ?? 0 }}</span>
          <span :class="{ 'diag-badge-warn': (health.channels?.nan_count ?? 0) > 0 }">
            NaN: {{ health.channels?.nan_count ?? 0 }}
          </span>
          <span :class="{ 'diag-badge-warn': (health.channels?.stale_count ?? 0) > 0 }">
            Stale: {{ health.channels?.stale_count ?? 0 }}
          </span>
        </div>
      </div>

      <!-- Event Timeline -->
      <div class="diag-section">
        <div class="diag-label">Events ({{ events.length }})</div>
        <div class="diag-events">
          <div v-if="recentEvents.length === 0" class="diag-empty">No events yet</div>
          <div
            v-for="(evt, i) in recentEvents"
            :key="i"
            class="diag-event"
          >
            <span class="diag-event-dot" :style="{ backgroundColor: severityColor(evt.severity) }" />
            <span class="diag-event-time">{{ formatTime(evt.timestamp) }}</span>
            <span class="diag-event-name">{{ formatEventName(evt.event) }}</span>
            <span v-if="evt.details && Object.keys(evt.details).length" class="diag-event-detail">
              {{ JSON.stringify(evt.details).slice(0, 80) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Errors -->
      <div v-if="recentErrors.length > 0" class="diag-section">
        <div class="diag-label diag-label-err">Errors ({{ recentErrors.length }})</div>
        <div class="diag-events">
          <div
            v-for="(evt, i) in recentErrors"
            :key="'err-' + i"
            class="diag-event diag-event-err"
          >
            <span class="diag-event-time">{{ formatTime(evt.timestamp) }}</span>
            <span class="diag-event-name">{{ formatEventName(evt.event) }}</span>
            <span v-if="evt.details?.error" class="diag-event-detail">
              {{ String(evt.details.error).slice(0, 120) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.diag-mini {
  position: fixed;
  bottom: 16px;
  right: 16px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  cursor: pointer;
  z-index: 9999;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s;
}
.diag-mini:hover {
  transform: scale(1.3);
}
.diag-spinner {
  font-size: 12px;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.diag-error-toast {
  position: fixed;
  bottom: 48px;
  right: 16px;
  background: #991b1b;
  color: #fecaca;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  z-index: 9999;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  animation: slideIn 0.3s ease;
}
.diag-error-icon {
  margin-right: 6px;
}

.diag-panel {
  position: fixed;
  bottom: 48px;
  right: 16px;
  width: 360px;
  max-height: 70vh;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 8px;
  z-index: 9998;
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  font-size: 12px;
  color: #d4d4d4;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.diag-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #333;
  background: #252525;
  border-radius: 8px 8px 0 0;
}
.diag-title {
  font-weight: 600;
  font-size: 13px;
}
.diag-close {
  background: none;
  border: none;
  color: #888;
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
}
.diag-close:hover { color: #fff; }

.diag-section {
  padding: 8px 12px;
  border-bottom: 1px solid #2a2a2a;
}
.diag-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #888;
  margin-bottom: 4px;
}
.diag-label-err { color: #ef4444; }

.diag-stage {
  font-size: 14px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-block;
}
.stage-running { color: #22c55e; background: #14532d; }
.stage-init { color: #f59e0b; background: #451a03; }
.stage-stopped { color: #6b7280; background: #1f2937; }
.stage-pending { color: #60a5fa; background: #1e3a5f; }
.stage-offline { color: #ef4444; background: #450a0a; }

.diag-health-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
}
.diag-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.diag-stats {
  display: flex;
  gap: 12px;
}

.diag-badge-warn {
  color: #f59e0b;
  font-size: 11px;
}
.diag-badge-err {
  color: #ef4444;
  font-weight: 700;
  font-size: 11px;
}

.diag-events {
  max-height: 200px;
  overflow-y: auto;
}
.diag-empty {
  color: #555;
  font-style: italic;
  padding: 4px 0;
}
.diag-event {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 2px 0;
  font-size: 11px;
  border-bottom: 1px solid #1a1a1a;
}
.diag-event-err {
  color: #fca5a5;
}
.diag-event-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
}
.diag-event-time {
  color: #666;
  flex-shrink: 0;
  min-width: 65px;
}
.diag-event-name {
  color: #aaa;
  flex-shrink: 0;
}
.diag-event-detail {
  color: #555;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
