<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')

const isConnected = computed(() => store.isConnected)
const mqttConnected = computed(() => mqtt.connected.value)

const isAcquiring = computed(() => store.status?.acquiring ?? false)
const isSimulation = computed(() => store.status?.simulation_mode ?? false)

const channelCount = computed(() => store.status?.channel_count ?? 0)
const scanRate = computed(() => store.status?.scan_rate_hz ?? 0)

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
        <span class="value">{{ scanRate }}</span>
        <span class="label">Hz</span>
      </div>
      <div v-if="isSimulation" class="sim-badge">SIM</div>
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
</style>
