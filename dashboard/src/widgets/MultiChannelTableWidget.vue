<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  channels?: string[]
  group?: string
  showAlarmStatus?: boolean
  showUnit?: boolean
  compact?: boolean
}>()

const store = useDashboardStore()

// Get channels to display - either explicit list, by group, or all
const displayChannels = computed(() => {
  if (props.channels && props.channels.length > 0) {
    return props.channels
  }

  if (props.group) {
    return Object.entries(store.channels)
      .filter(([_, cfg]) => cfg.group === props.group)
      .map(([name]) => name)
  }

  // Default: show first 10 analog channels
  return Object.entries(store.channels)
    .filter(([_, cfg]) => !['digital_input', 'digital_output'].includes(cfg.channel_type))
    .slice(0, 10)
    .map(([name]) => name)
})

// Build table data
const tableData = computed(() => {
  return displayChannels.value.map(channelName => {
    const config = store.channels[channelName]
    const value = store.values[channelName]

    // Check if stale - no timestamp, not acquiring, or old data
    const isStale = !value?.timestamp || !store.isAcquiring || (Date.now() - value.timestamp) > 5000

    return {
      name: channelName,
      displayName: channelName,  // TAG is the only identifier
      value: isStale ? null : (value?.value ?? null),
      unit: config?.unit || '',
      alarm: isStale ? false : (value?.alarm ?? false),
      warning: isStale ? false : (value?.warning ?? false),
      stale: isStale
    }
  })
})

function formatValue(value: number | null): string {
  if (value === null) return '--'
  if (Math.abs(value) >= 1000) return value.toFixed(0)
  if (Math.abs(value) >= 100) return value.toFixed(1)
  if (Math.abs(value) >= 10) return value.toFixed(2)
  return value.toFixed(3)
}

function getStatusClass(row: { alarm: boolean; warning: boolean; stale: boolean }): string {
  if (row.alarm) return 'alarm'
  if (row.warning) return 'warning'
  if (row.stale) return 'stale'
  return 'normal'
}
</script>

<template>
  <div class="multi-channel-table" :class="{ compact }">
    <div v-if="tableData.length === 0" class="no-channels">
      No channels configured
    </div>

    <div v-else class="table-container">
      <table>
        <thead v-if="!compact">
          <tr>
            <th class="name-col">Channel</th>
            <th class="value-col">Value</th>
            <th v-if="showUnit !== false" class="unit-col">Unit</th>
            <th v-if="showAlarmStatus" class="status-col">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in tableData"
            :key="row.name"
            :class="getStatusClass(row)"
          >
            <td class="name-col">
              <span class="channel-name">{{ row.displayName }}</span>
            </td>
            <td class="value-col">
              <span class="value">{{ formatValue(row.value) }}</span>
            </td>
            <td v-if="showUnit !== false" class="unit-col">
              <span class="unit">{{ row.unit }}</span>
            </td>
            <td v-if="showAlarmStatus" class="status-col">
              <span v-if="row.alarm" class="status-badge alarm">ALM</span>
              <span v-else-if="row.warning" class="status-badge warning">WRN</span>
              <span v-else-if="row.stale" class="status-badge stale">--</span>
              <span v-else class="status-badge ok">OK</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.multi-channel-table {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 6px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  overflow: hidden;
}

.no-channels {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #666;
  font-size: 0.75rem;
}

.table-container {
  flex: 1;
  overflow-y: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}

thead {
  position: sticky;
  top: 0;
  background: #1a1a2e;
  z-index: 1;
}

th {
  padding: 4px 6px;
  text-align: left;
  font-weight: 600;
  color: #888;
  font-size: 0.6rem;
  text-transform: uppercase;
  border-bottom: 1px solid #2a2a4a;
}

td {
  padding: 4px 6px;
  border-bottom: 1px solid #1f1f35;
}

tr:last-child td {
  border-bottom: none;
}

.name-col {
  min-width: 60px;
}

.value-col {
  text-align: right;
  min-width: 50px;
}

.unit-col {
  text-align: left;
  min-width: 30px;
  color: #666;
}

.status-col {
  text-align: center;
  width: 36px;
}

.channel-name {
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
  max-width: 100px;
}

.value {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #fff;
}

.unit {
  font-size: 0.6rem;
}

/* Status-based row styling */
tr.normal .value {
  color: #4ade80;
}

tr.warning {
  background: linear-gradient(90deg, transparent 0%, #3f3515 100%);
}
tr.warning .value {
  color: #fbbf24;
}

tr.alarm {
  background: linear-gradient(90deg, transparent 0%, #3f1515 100%);
  animation: pulse-row 1s infinite;
}
tr.alarm .value {
  color: #ef4444;
}

tr.stale .value {
  color: #666;
}

.status-badge {
  font-size: 0.5rem;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: 700;
}

.status-badge.ok {
  background: #14532d;
  color: #86efac;
}

.status-badge.warning {
  background: #78350f;
  color: #fbbf24;
}

.status-badge.alarm {
  background: #7f1d1d;
  color: #fca5a5;
}

.status-badge.stale {
  background: #374151;
  color: #9ca3af;
}

/* Compact mode */
.compact table {
  font-size: 0.65rem;
}

.compact th,
.compact td {
  padding: 2px 4px;
}

.compact .channel-name {
  max-width: 70px;
}

@keyframes pulse-row {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.8; }
}
</style>
