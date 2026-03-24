<script setup lang="ts">
import type { SystemStatus, HeartbeatData } from '../types'
import { formatUptime } from '../utils/formatters'

const props = defineProps<{
  status: SystemStatus | null
  heartbeat: HeartbeatData | null
}>()
</script>

<template>
  <section class="section">
    <h3 class="section-title">System Status</h3>
    <div v-if="status" class="grid">
      <div class="field">
        <span class="label">State</span>
        <span class="value" :class="status.acquiring ? 'text-green' : ''">
          {{ status.acquisition_state ?? (status.acquiring ? 'Running' : 'Stopped') }}
        </span>
      </div>
      <div class="field">
        <span class="label">Mode</span>
        <span class="value">{{ status.project_mode ?? '--' }}</span>
      </div>
      <div class="field">
        <span class="label">Channels</span>
        <span class="value mono">{{ status.channel_count }}</span>
      </div>
      <div class="field">
        <span class="label">Scan Rate</span>
        <span class="value mono">{{ status.scan_rate_hz }} Hz</span>
      </div>
      <div class="field">
        <span class="label">Publish Rate</span>
        <span class="value mono">{{ status.publish_rate_hz }} Hz</span>
      </div>
      <div class="field">
        <span class="label">Uptime</span>
        <span class="value mono">{{ heartbeat?.uptime_seconds != null ? formatUptime(heartbeat.uptime_seconds) : '--' }}</span>
      </div>
      <div class="field">
        <span class="label">Recording</span>
        <span class="value" :class="status.recording ? 'text-green' : ''">
          {{ status.recording ? 'Active' : 'Off' }}
          <template v-if="status.recording && status.recording_duration"> ({{ status.recording_duration }})</template>
        </span>
      </div>
      <div class="field">
        <span class="label">Simulation</span>
        <span class="value" :class="status.simulation_mode ? 'text-yellow' : ''">
          {{ status.simulation_mode ? 'Yes' : 'No' }}
        </span>
      </div>
      <div v-if="status.sequences_active != null" class="field">
        <span class="label">Sequences</span>
        <span class="value mono">{{ status.sequences_active }}/{{ status.sequences_total ?? '?' }}</span>
      </div>
      <div v-if="status.session_active" class="field">
        <span class="label">Session</span>
        <span class="value text-green">Active</span>
      </div>
      <div v-if="heartbeat?.thread_health" class="field">
        <span class="label">Threads</span>
        <span class="value">
          <span :class="heartbeat.thread_health.scan ? 'text-green' : 'text-red'">Scan</span>
          <span :class="heartbeat.thread_health.publish ? 'text-green' : 'text-red'">Pub</span>
          <span :class="heartbeat.thread_health.heartbeat ? 'text-green' : 'text-red'">HB</span>
        </span>
      </div>
    </div>
    <div v-else class="no-data">No status data received</div>
  </section>
</template>

<style scoped>
.section {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 1rem;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 0.75rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.625rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.label {
  font-size: 0.7rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.value {
  font-size: 0.875rem;
  color: var(--text-primary);
  display: flex;
  gap: 0.5rem;
}

.text-green { color: var(--color-success); }
.text-yellow { color: var(--color-warning); }
.text-red { color: var(--color-error); }

.no-data {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-style: italic;
}
</style>
