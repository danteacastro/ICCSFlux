<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { useScripts } from '../composables/useScripts'

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const scripts = useScripts()

const isConnected = computed(() => store.isConnected)
const mqttConnected = computed(() => mqtt.connected.value)

const isAcquiring = computed(() => store.status?.acquiring ?? false)
const isSimulation = computed(() => store.status?.simulation_mode ?? false)

const channelCount = computed(() => store.status?.channel_count ?? 0)
const publishRate = computed(() => store.status?.publish_rate_hz ?? 0)

// Running sequence info
const runningSequence = computed(() => scripts.runningSequence.value)
const isSequenceRunning = computed(() => !!runningSequence.value)

// Active alarms info
const activeAlarmCount = computed(() => scripts.activeAlarmIds.value.length)
const hasActiveAlarms = computed(() => activeAlarmCount.value > 0)

// Calculate data freshness
const lastUpdate = computed(() => {
  const firstValue = Object.values(store.values)[0]
  if (!firstValue?.timestamp) return null
  return firstValue.timestamp
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
  <div class="system-status-widget">
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
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 8px;
}

.status-row {
  display: flex;
  gap: 8px;
  justify-content: space-around;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #0f0f1a;
  border-radius: 4px;
}

.status-item .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4b5563;
}

.status-item.ok .dot {
  background: #22c55e;
  box-shadow: 0 0 4px #22c55e;
}

.status-item.error .dot {
  background: #ef4444;
}

.status-item.inactive .dot {
  background: #4b5563;
}

.status-item .label {
  font-size: 0.6rem;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
}

.status-item.ok .label {
  color: #86efac;
}

.status-item.error .label {
  color: #fca5a5;
}

.data-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px 8px;
  background: #14532d;
  color: #86efac;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
}

.data-status.stale {
  background: #78350f;
  color: #fbbf24;
}

.stats-row {
  display: flex;
  gap: 8px;
  justify-content: center;
  align-items: center;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.stat .value {
  font-size: 0.85rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.stat .label {
  font-size: 0.55rem;
  color: #6b7280;
  text-transform: uppercase;
}

.sim-badge {
  font-size: 0.55rem;
  padding: 2px 6px;
  background: #7c3aed;
  color: #fff;
  border-radius: 3px;
  font-weight: 700;
}

.activity-row {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

.activity-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 0.6rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-icon {
  font-size: 0.55rem;
  flex-shrink: 0;
}

.activity-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-item.sequence-running {
  background: #1e3a5f;
  color: #60a5fa;
  animation: pulse-seq 2s infinite;
}

.activity-item.idle {
  background: #1a1a2e;
  color: #6b7280;
}

.activity-item.alarms-active {
  background: #7f1d1d;
  color: #fca5a5;
  animation: pulse-alarm 1s infinite;
}

.activity-item.ok {
  background: #14532d;
  color: #86efac;
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
