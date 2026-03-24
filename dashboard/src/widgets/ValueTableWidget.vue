<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'

const props = defineProps<{
  channels?: string[]      // List of channels to display
  label?: string           // Table header/title
  decimals?: number
  compact?: boolean
  industrial?: boolean
  showUnits?: boolean      // Show unit column (default true)
  showStatus?: boolean     // Show status indicator column
  maxRows?: number         // Limit visible rows
}>()

const store = useDashboardStore()

// Get channel data for each configured channel
const rows = computed(() => {
  if (!props.channels?.length) return []

  return props.channels.slice(0, props.maxRows || 20).map(channelName => {
    const config = store.channels[channelName]
    const value = store.values[channelName]

    const isStale = !value?.timestamp || !store.isAcquiring ||
                    (Date.now() - value.timestamp) > 5000

    const formattedValue = isStale || !value
      ? '--'
      : typeof value.value === 'number'
        ? value.value.toFixed(props.decimals ?? 2)
        : String(value.value)

    return {
      name: channelName,
      label: channelName.replace(/^py\./, ''),  // Strip py. prefix for display
      value: formattedValue,
      unit: formatUnit(config?.unit),
      isStale,
      isAlarm: value?.alarm || false,
      isWarning: value?.warning || false
    }
  })
})

const modeClasses = computed(() => ({
  compact: props.compact,
  industrial: props.industrial
}))

const shouldShowUnits = computed(() => props.showUnits !== false)
const shouldShowStatus = computed(() => props.showStatus === true)
</script>

<template>
  <div class="value-table-widget" :class="modeClasses">
    <!-- Header -->
    <div v-if="label" class="table-header">{{ label }}</div>

    <!-- Table rows -->
    <div class="table-body">
      <div
        v-for="row in rows"
        :key="row.name"
        class="table-row"
        :class="{ stale: row.isStale, alarm: row.isAlarm, warning: row.isWarning }"
      >
        <!-- Status indicator (optional) -->
        <div v-if="shouldShowStatus" class="status-cell">
          <div
            class="status-dot"
            :class="{
              active: !row.isStale && !row.isAlarm && !row.isWarning,
              alarm: row.isAlarm,
              warning: row.isWarning
            }"
          />
        </div>

        <!-- Label -->
        <div class="label-cell">{{ row.label }}</div>

        <!-- Value -->
        <div class="value-cell">{{ row.value }}</div>

        <!-- Unit (optional) -->
        <div v-if="shouldShowUnits" class="unit-cell">{{ row.unit }}</div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!rows.length" class="empty-state">
      No channels configured
    </div>
  </div>
</template>

<style scoped>
.value-table-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.table-header {
  padding: 6px 8px;
  background: var(--bg-gradient-elevated);
  border-bottom: 1px solid var(--border-color);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
}

.table-body {
  flex: 1;
  overflow-y: auto;
}

.table-row {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  border-bottom: 1px solid #1f1f35;
  gap: 8px;
}

.table-row:last-child {
  border-bottom: none;
}

.table-row:hover {
  background: rgba(255, 255, 255, 0.02);
}

.status-cell {
  width: 12px;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #444;
}

.status-dot.active {
  background: var(--color-success);
  box-shadow: 0 0 4px var(--color-success);
}

.status-dot.warning {
  background: var(--color-warning);
}

.status-dot.alarm {
  background: var(--color-error);
  animation: blink 1s infinite;
}

.label-cell {
  flex: 1;
  font-size: 0.75rem;
  color: #aaa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.value-cell {
  font-size: 0.85rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  color: var(--color-success-light);
  text-align: right;
  min-width: 60px;
}

.unit-cell {
  font-size: 0.65rem;
  color: var(--text-muted);
  min-width: 30px;
}

/* Status colors */
.table-row.stale .value-cell {
  color: var(--text-muted);
}

.table-row.warning .value-cell {
  color: var(--color-warning);
}

.table-row.alarm .value-cell {
  color: var(--color-error);
}

.empty-state {
  padding: 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8rem;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ========================================
   COMPACT MODE
   ======================================== */
.compact .table-header {
  padding: 3px 6px;
  font-size: 0.6rem;
}

.compact .table-row {
  padding: 2px 6px;
  gap: 4px;
}

.compact .label-cell {
  font-size: 0.65rem;
}

.compact .value-cell {
  font-size: 0.75rem;
  min-width: 50px;
}

.compact .unit-cell {
  font-size: 0.55rem;
  min-width: 24px;
}

/* ========================================
   INDUSTRIAL MODE
   ======================================== */
.industrial {
  border-radius: 0;
  border: 1px solid #444;
  background: #2a2a2a;
}

.industrial .table-header {
  background: #333;
  border-color: #444;
  color: #aaa;
}

.industrial .table-row {
  border-color: #3a3a3a;
}

.industrial .label-cell {
  color: #bbb;
}

.industrial .value-cell {
  color: #7fff7f;
  font-family: 'Consolas', 'Courier New', monospace;
}

.industrial .status-dot {
  border-radius: 2px;
}

.industrial .status-dot.active {
  box-shadow: none;
}

/* Compact + Industrial */
.compact.industrial .table-row {
  padding: 1px 4px;
}
</style>
