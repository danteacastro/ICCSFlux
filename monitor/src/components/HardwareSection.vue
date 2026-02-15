<script setup lang="ts">
import type { HardwareHealth } from '../types'

const props = defineProps<{ health: HardwareHealth | null }>()
</script>

<template>
  <section v-if="health" class="section">
    <h3 class="section-title">Hardware</h3>
    <div class="grid">
      <div class="field">
        <span class="label">Status</span>
        <span class="value" :class="health.healthy ? 'ok' : 'err'">
          {{ health.healthy ? 'Healthy' : 'Unhealthy' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Running</span>
        <span class="value" :class="health.running ? 'ok' : 'err'">
          {{ health.running ? 'Yes' : 'No' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Thread Alive</span>
        <span class="value" :class="health.thread_alive ? 'ok' : 'err'">
          {{ health.thread_alive ? 'Yes' : 'No' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Reader Died</span>
        <span class="value" :class="health.reader_died ? 'err' : 'ok'">
          {{ health.reader_died ? 'YES' : 'No' }}
        </span>
      </div>
      <div class="field">
        <span class="label">Errors</span>
        <span class="value mono" :class="health.error_count > 0 ? 'warn' : ''">
          {{ health.error_count }}
        </span>
      </div>
      <div class="field">
        <span class="label">Recovery Attempts</span>
        <span class="value mono" :class="health.recovery_attempts > 0 ? 'warn' : ''">
          {{ health.recovery_attempts }}
        </span>
      </div>
      <div v-if="health.watchdog_active != null" class="field">
        <span class="label">HW Watchdog</span>
        <span class="value" :class="health.watchdog_triggered ? 'err' : 'ok'">
          {{ health.watchdog_triggered ? 'TRIGGERED' : (health.watchdog_active ? 'Active' : 'Inactive') }}
        </span>
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

.value { font-size: 0.875rem; color: var(--text-primary); }
.value.ok { color: var(--color-success); }
.value.warn { color: var(--color-warning); }
.value.err { color: var(--color-error); font-weight: 600; }
</style>
