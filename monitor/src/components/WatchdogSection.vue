<script setup lang="ts">
import type { WatchdogStatus } from '../types'
import { formatTimestamp } from '../utils/formatters'

const props = defineProps<{ watchdog: WatchdogStatus | null }>()
</script>

<template>
  <section v-if="watchdog" class="section">
    <h3 class="section-title">Watchdog</h3>
    <div class="grid">
      <div class="field">
        <span class="label">Status</span>
        <span class="value" :class="watchdog.status === 'online' ? 'ok' : 'err'">
          {{ watchdog.status }}
        </span>
      </div>
      <div class="field">
        <span class="label">DAQ Online</span>
        <span class="value" :class="watchdog.daq_online ? 'ok' : 'err'">
          {{ watchdog.daq_online ? 'Yes' : 'No' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Failsafe</span>
        <span class="value" :class="watchdog.failsafe_triggered ? 'err' : 'ok'">
          {{ watchdog.failsafe_triggered ? 'TRIGGERED' : 'Normal' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Last Heartbeat</span>
        <span class="value">{{ formatTimestamp(watchdog.last_heartbeat) }}</span>
      </div>
      <div class="field">
        <span class="label">Timeout</span>
        <span class="value mono">{{ watchdog.timeout_sec }}s</span>
      </div>
    </div>
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
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.625rem;
}

.field { display: flex; flex-direction: column; gap: 0.125rem; }
.label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.value { font-size: 0.875rem; color: var(--text-primary); }
.value.ok { color: var(--color-success); }
.value.err { color: var(--color-error); font-weight: 600; }
</style>
