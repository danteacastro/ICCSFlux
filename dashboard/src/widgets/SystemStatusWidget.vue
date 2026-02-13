<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useScripts } from '../composables/useScripts'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  style?: WidgetStyle
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const scripts = useScripts()

const isConnected = computed(() => store.isConnected)
const mqttConnected = computed(() => mqtt.connected.value)

const isAcquiring = computed(() => store.status?.acquiring ?? false)
const isSimulation = computed(() => store.status?.simulation_mode ?? false)

const channelCount = computed(() => store.status?.channel_count ?? 0)
const publishRate = computed(() => store.status?.publish_rate_hz ?? 0)

// Resource monitoring
const resourceMonitoringEnabled = computed(() => store.status?.resource_monitoring ?? false)
const cpuPercent = computed(() => store.status?.cpu_percent ?? 0)
const memoryMb = computed(() => store.status?.memory_mb ?? 0)
const diskPercent = computed(() => store.status?.disk_percent ?? 0)
const diskUsedGb = computed(() => store.status?.disk_used_gb ?? 0)
const diskTotalGb = computed(() => store.status?.disk_total_gb ?? 0)

// Health status helpers
const getCpuStatus = computed(() => {
  if (cpuPercent.value > 80) return 'critical'
  if (cpuPercent.value > 50) return 'warning'
  return 'ok'
})

const getMemoryStatus = computed(() => {
  if (memoryMb.value > 500) return 'critical'
  if (memoryMb.value > 300) return 'warning'
  return 'ok'
})

const getDiskStatus = computed(() => {
  if (diskPercent.value > 90) return 'critical'
  if (diskPercent.value > 75) return 'warning'
  return 'ok'
})

// Running sequence info
const runningSequence = computed(() => scripts.runningSequence.value)
const isSequenceRunning = computed(() => !!runningSequence.value)

// Active alarms info
const activeAlarmCount = computed(() => scripts.activeAlarmIds.value.length)
const hasActiveAlarms = computed(() => activeAlarmCount.value > 0)

// Calculate data freshness
const lastUpdate = computed(() => {
  const values = Object.values(store.values)
  if (values.length === 0) return null
  let maxTs = 0
  for (const v of values) {
    if (!v) continue
    if (v.timestamp && v.timestamp > maxTs) maxTs = v.timestamp
  }
  return maxTs > 0 ? maxTs : null
})

const dataAge = computed(() => {
  if (!lastUpdate.value) return '--'
  const age = (Date.now() - lastUpdate.value) / 1000
  if (age < 2) return 'Live'
  if (age < 60) return `${age.toFixed(0)}s ago`
  return 'Stale'
})

const isDataStale = computed(() => {
  if (!lastUpdate.value) return true
  return (Date.now() - lastUpdate.value) > 5000
})
</script>

<template>
  <div class="system-status-widget" :style="containerStyle">
    <!-- Connection Status -->
    <div class="status-row">
      <div class="status-item" :class="{ ok: mqttConnected, error: !mqttConnected }">
        <span class="dot"></span>
        <span class="label">MQTT</span>
      </div>
      <div class="status-item" :class="{ ok: isConnected, error: !isConnected }">
        <span class="dot"></span>
        <span class="label">DAQ</span>
      </div>
      <div class="status-item" :class="{ ok: isAcquiring, inactive: !isAcquiring }">
        <span class="dot"></span>
        <span class="label">ACQ</span>
      </div>
    </div>

    <!-- Data freshness -->
    <div class="data-status" :class="{ stale: isDataStale }">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12,6 12,12 16,14"/>
      </svg>
      <span>{{ dataAge }}</span>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <div class="stat">
        <span class="value">{{ channelCount }}</span>
        <span class="label">CH</span>
      </div>
      <div class="stat">
        <span class="value">{{ publishRate }}</span>
        <span class="label">Hz</span>
      </div>
      <div v-if="isSimulation" class="sim-badge">SIM</div>
    </div>

    <!-- System Health -->
    <div v-if="resourceMonitoringEnabled" class="health-row">
      <div class="health-item" :class="getCpuStatus">
        <span class="health-label">CPU</span>
        <div class="health-bar">
          <div class="health-fill" :style="{ width: cpuPercent + '%' }"></div>
        </div>
        <span class="health-value">{{ cpuPercent }}%</span>
      </div>
      <div class="health-item" :class="getMemoryStatus">
        <span class="health-label">MEM</span>
        <div class="health-bar">
          <div class="health-fill" :style="{ width: Math.min(memoryMb / 5, 100) + '%' }"></div>
        </div>
        <span class="health-value">{{ memoryMb }}M</span>
      </div>
      <div class="health-item" :class="getDiskStatus">
        <span class="health-label">DISK</span>
        <div class="health-bar">
          <div class="health-fill" :style="{ width: diskPercent + '%' }"></div>
        </div>
        <span class="health-value">{{ diskPercent }}%</span>
      </div>
    </div>

    <!-- Sequence & Alarm Status -->
    <div class="activity-row">
      <!-- Running Sequence -->
      <div v-if="isSequenceRunning" class="activity-item sequence-running">
        <span class="activity-icon">▶</span>
        <span class="activity-label">{{ runningSequence?.name }}</span>
      </div>
      <div v-else class="activity-item idle">
        <span class="activity-icon">◼</span>
        <span class="activity-label">No sequence</span>
      </div>

      <!-- Active Alarms -->
      <div v-if="hasActiveAlarms" class="activity-item alarms-active">
        <span class="activity-icon">⚠</span>
        <span class="activity-label">{{ activeAlarmCount }} alarm{{ activeAlarmCount > 1 ? 's' : '' }}</span>
      </div>
      <div v-else class="activity-item ok">
        <span class="activity-icon">✓</span>
        <span class="activity-label">No alarms</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.system-status-widget {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
  padding: 4px 6px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  gap: 4px;
  container-type: size;
  overflow: hidden;
}

.status-row {
  display: flex;
  gap: 6px;
  justify-content: center;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 3px;
}

.status-item .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--btn-secondary-hover);
  flex-shrink: 0;
}

.status-item.ok .dot {
  background: var(--color-success);
  box-shadow: 0 0 4px var(--color-success);
}

.status-item.error .dot {
  background: var(--color-error);
}

.status-item.inactive .dot {
  background: var(--btn-secondary-hover);
}

.status-item .label {
  font-size: 0.55rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
}

.status-item.ok .label {
  color: var(--indicator-success-text);
}

.status-item.error .label {
  color: var(--indicator-danger-text);
}

.data-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--indicator-success-bg);
  color: var(--indicator-success-text);
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
}

.data-status svg {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
}

.data-status.stale {
  background: var(--indicator-warning-bg);
  color: #fbbf24;
}

.stats-row {
  display: flex;
  gap: 6px;
  justify-content: center;
  align-items: center;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.stat .value {
  font-size: 0.75rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-primary);
}

.stat .label {
  font-size: 0.5rem;
  color: var(--text-dim);
  text-transform: uppercase;
}

.sim-badge {
  font-size: 0.5rem;
  padding: 1px 4px;
  background: #7c3aed;
  color: var(--text-primary);
  border-radius: 2px;
  font-weight: 700;
}

.activity-row {
  display: flex;
  gap: 4px;
}

.activity-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 0.55rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-icon {
  font-size: 0.5rem;
  flex-shrink: 0;
}

.activity-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-item.sequence-running {
  background: var(--color-accent-bg);
  color: var(--color-accent-light);
  animation: pulse-seq 2s infinite;
}

.activity-item.idle {
  background: var(--bg-widget);
  color: var(--text-dim);
}

.activity-item.alarms-active {
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
  animation: pulse-alarm 1s infinite;
}

.activity-item.ok {
  background: var(--indicator-success-bg);
  color: var(--indicator-success-text);
}

/* System Health Row */
.health-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.health-label {
  font-size: 0.5rem;
  font-weight: 600;
  color: var(--text-dim);
  width: 28px;
  flex-shrink: 0;
}

.health-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-widget);
  border-radius: 2px;
  overflow: hidden;
}

.health-fill {
  height: 100%;
  background: var(--color-success);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.health-item.warning .health-fill {
  background: #eab308;
}

.health-item.critical .health-fill {
  background: var(--color-error);
}

.health-value {
  font-size: 0.5rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted);
  width: 32px;
  text-align: right;
  flex-shrink: 0;
}

.health-item.ok .health-value {
  color: var(--indicator-success-text);
}

.health-item.warning .health-value {
  color: #fbbf24;
}

.health-item.critical .health-value {
  color: var(--indicator-danger-text);
}

/* Compact mode: hide activity and health rows when short */
@container (max-height: 90px) {
  .activity-row {
    display: none;
  }
}

@container (max-height: 120px) {
  .health-row {
    display: none;
  }
}

/* Very compact: combine stats with data-status */
@container (max-height: 60px) {
  .data-status {
    display: none;
  }
  .system-status-widget {
    gap: 2px;
  }
}

/* Scale up when taller */
@container (min-height: 120px) {
  .system-status-widget {
    gap: 6px;
    padding: 6px 8px;
  }
  .status-item {
    padding: 3px 8px;
    gap: 4px;
  }
  .status-item .dot {
    width: 6px;
    height: 6px;
  }
  .status-item .label {
    font-size: 0.6rem;
  }
  .data-status {
    padding: 4px 10px;
    font-size: 0.7rem;
  }
  .stat .value {
    font-size: 0.85rem;
  }
  .stat .label {
    font-size: 0.55rem;
  }
  .activity-item {
    padding: 3px 6px;
    font-size: 0.6rem;
  }
  .health-row {
    gap: 4px;
  }
  .health-label {
    font-size: 0.55rem;
  }
  .health-bar {
    height: 5px;
  }
  .health-value {
    font-size: 0.55rem;
  }
}

/* Large mode */
@container (min-height: 160px) {
  .system-status-widget {
    gap: 8px;
    padding: 8px 10px;
  }
  .status-item {
    padding: 4px 10px;
  }
  .status-item .dot {
    width: 8px;
    height: 8px;
  }
  .status-item .label {
    font-size: 0.65rem;
  }
  .data-status {
    padding: 6px 12px;
    font-size: 0.75rem;
  }
  .data-status svg {
    width: 12px;
    height: 12px;
  }
  .stat .value {
    font-size: 1rem;
  }
  .stat .label {
    font-size: 0.6rem;
  }
  .sim-badge {
    font-size: 0.55rem;
    padding: 2px 6px;
  }
  .activity-item {
    padding: 4px 8px;
    font-size: 0.65rem;
  }
  .health-row {
    gap: 5px;
  }
  .health-label {
    font-size: 0.6rem;
    width: 32px;
  }
  .health-bar {
    height: 6px;
  }
  .health-value {
    font-size: 0.6rem;
    width: 36px;
  }
}

@keyframes pulse-seq {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

@keyframes pulse-alarm {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
