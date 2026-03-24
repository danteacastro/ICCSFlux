<script setup lang="ts">
import { computed } from 'vue'
import type { AlarmInfo } from '../types'
import { formatTimestamp } from '../utils/formatters'

const props = defineProps<{ alarms: Map<string, AlarmInfo> }>()

const activeAlarms = computed(() =>
  Array.from(props.alarms.values())
    .filter(a => a.active)
    .sort((a, b) => {
      const order: Record<string, number> = { CRITICAL: 0, HIGH: 1, WARNING: 2, MEDIUM: 3, LOW: 4 }
      return (order[a.severity] ?? 5) - (order[b.severity] ?? 5)
    })
)
</script>

<template>
  <section class="section">
    <h3 class="section-title">
      Alarms
      <span v-if="activeAlarms.length > 0" class="count">{{ activeAlarms.length }}</span>
    </h3>
    <div v-if="activeAlarms.length > 0" class="alarm-list">
      <div v-for="alarm in activeAlarms" :key="alarm.alarm_id" class="alarm-row" :class="alarm.severity.toLowerCase()">
        <span class="severity">{{ alarm.severity }}</span>
        <span class="channel mono">{{ alarm.channel }}</span>
        <span class="message">{{ alarm.message }}</span>
        <span v-if="alarm.value != null" class="val mono">{{ alarm.value.toFixed(2) }}</span>
        <span class="time">{{ formatTimestamp(alarm.triggered_at) }}</span>
        <span v-if="alarm.acknowledged" class="acked">ACK</span>
      </div>
    </div>
    <div v-else class="no-data">No active alarms</div>
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
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.count {
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
}

.alarm-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.alarm-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.5rem 0.625rem;
  border-radius: 4px;
  background: var(--bg-panel-row);
  font-size: 0.8rem;
}

.alarm-row.critical, .alarm-row.high {
  background: var(--color-error-bg);
  border-left: 3px solid var(--color-error);
}

.alarm-row.warning, .alarm-row.medium {
  background: var(--color-warning-bg);
  border-left: 3px solid var(--color-warning);
}

.severity {
  font-weight: 700;
  font-size: 0.7rem;
  min-width: 60px;
  text-transform: uppercase;
}

.critical .severity, .high .severity { color: var(--color-error); }
.warning .severity, .medium .severity { color: var(--color-warning); }

.channel {
  min-width: 80px;
  color: var(--text-primary);
  font-size: 0.75rem;
}

.message {
  flex: 1;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.val {
  color: var(--text-primary);
  font-size: 0.75rem;
}

.time {
  color: var(--text-dim);
  font-size: 0.7rem;
  white-space: nowrap;
}

.acked {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  background: var(--indicator-success-bg);
  color: var(--indicator-success-text);
}

.no-data {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-style: italic;
}
</style>
