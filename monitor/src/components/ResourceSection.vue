<script setup lang="ts">
import type { SystemStatus } from '../types'

const props = defineProps<{ status: SystemStatus | null }>()
</script>

<template>
  <section v-if="status?.resource_monitoring" class="section">
    <h3 class="section-title">Resources</h3>
    <div class="bars">
      <!-- CPU -->
      <div class="bar-row">
        <span class="bar-label">CPU</span>
        <div class="bar-track">
          <div
            class="bar-fill"
            :class="{ warn: (status.cpu_percent ?? 0) > 80, crit: (status.cpu_percent ?? 0) > 90 }"
            :style="{ width: `${Math.min(status.cpu_percent ?? 0, 100)}%` }"
          ></div>
        </div>
        <span class="bar-value mono">{{ status.cpu_percent?.toFixed(0) ?? '--' }}%</span>
      </div>

      <!-- Memory -->
      <div class="bar-row">
        <span class="bar-label">Memory</span>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: '50%' }"></div>
        </div>
        <span class="bar-value mono">{{ status.memory_mb?.toFixed(0) ?? '--' }} MB</span>
      </div>

      <!-- Disk -->
      <div class="bar-row">
        <span class="bar-label">Disk</span>
        <div class="bar-track">
          <div
            class="bar-fill"
            :class="{ warn: (status.disk_percent ?? 0) > 80, crit: (status.disk_percent ?? 0) > 90 }"
            :style="{ width: `${Math.min(status.disk_percent ?? 0, 100)}%` }"
          ></div>
        </div>
        <span class="bar-value mono">{{ status.disk_percent?.toFixed(0) ?? '--' }}%</span>
      </div>

      <div v-if="status.disk_used_gb != null" class="disk-detail">
        {{ status.disk_used_gb.toFixed(1) }} / {{ status.disk_total_gb?.toFixed(0) ?? '?' }} GB
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

.bars {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.bar-label {
  width: 55px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 8px;
  background: var(--bg-surface);
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  background: var(--color-accent);
  transition: width 0.4s ease;
}

.bar-fill.warn { background: var(--color-warning); }
.bar-fill.crit { background: var(--color-error); }

.bar-value {
  width: 55px;
  text-align: right;
  font-size: 0.75rem;
  color: var(--text-primary);
  flex-shrink: 0;
}

.disk-detail {
  font-size: 0.7rem;
  color: var(--text-dim);
  text-align: right;
}
</style>
