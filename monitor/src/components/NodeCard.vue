<script setup lang="ts">
import { computed } from 'vue'
import type { NodeState } from '../types'
import { formatUptime } from '../utils/formatters'

const props = defineProps<{
  nodeState: NodeState
  selected: boolean
}>()

const activeAlarms = computed(() =>
  Array.from(props.nodeState.alarms.values()).filter(a => a.active).length
)

const dotColor = computed(() => {
  if (!props.nodeState.connection.connected) return 'gray'
  return { healthy: 'green', warning: 'yellow', error: 'red', unknown: 'gray' }[props.nodeState.health]
})

const uptime = computed(() => {
  const s = props.nodeState.heartbeat?.uptime_seconds
  return s != null ? formatUptime(s) : '--'
})
</script>

<template>
  <div class="card" :class="[nodeState.health, { selected }]">
    <div class="card-top">
      <span class="dot" :class="dotColor"></span>
      <span class="name">{{ nodeState.node.name }}</span>
    </div>

    <div class="card-meta">
      <span class="host mono">{{ nodeState.node.host }}</span>
      <span v-if="nodeState.heartbeat" class="uptime">{{ uptime }}</span>
    </div>

    <div class="badges">
      <span v-if="nodeState.status?.acquiring" class="badge acq">ACQ</span>
      <span v-if="nodeState.status?.recording" class="badge rec">REC</span>
      <span v-if="nodeState.status?.simulation_mode" class="badge sim">SIM</span>
      <span v-if="activeAlarms > 0" class="badge alarm">{{ activeAlarms }} ALARM{{ activeAlarms > 1 ? 'S' : '' }}</span>
      <span v-if="nodeState.safety?.isTripped" class="badge tripped">TRIPPED</span>
    </div>

    <div v-if="!nodeState.connection.connected" class="offline-overlay">
      <span v-if="nodeState.connection.connecting">Connecting...</span>
      <span v-else>Offline</span>
    </div>
  </div>
</template>

<style scoped>
.card {
  position: relative;
  padding: 0.75rem;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 0.375rem;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
}

.card:hover { background: var(--bg-elevated); border-color: var(--border-light); }
.card.selected { border-color: var(--color-accent); background: var(--color-accent-bg); }
.card.error { border-left: 3px solid var(--color-error); }
.card.warning { border-left: 3px solid var(--color-warning); }
.card.healthy { border-left: 3px solid var(--color-success); }

.card-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.green { background: var(--color-success); box-shadow: 0 0 6px var(--color-success); }
.dot.yellow { background: var(--color-warning); box-shadow: 0 0 6px var(--color-warning); }
.dot.red { background: var(--color-error); box-shadow: 0 0 6px var(--color-error); }
.dot.gray { background: var(--text-muted); }

.name {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--text-bright);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.375rem;
}

.host {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.uptime {
  font-size: 0.7rem;
  color: var(--text-dim);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.badge {
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.03em;
}

.badge.acq { background: var(--indicator-success-bg); color: var(--indicator-success-text); }
.badge.rec { background: var(--color-accent-bg); color: var(--color-accent-light); }
.badge.sim { background: var(--indicator-warning-bg); color: var(--indicator-warning-text); }
.badge.alarm { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); }
.badge.tripped { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); animation: pulse 1s infinite; }

.offline-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.8rem;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
