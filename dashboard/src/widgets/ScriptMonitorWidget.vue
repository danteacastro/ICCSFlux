<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

interface MonitorItem {
  tag: string
  label?: string
  unit?: string
  format?: string  // 'number', 'integer', 'percent', 'status', 'text'
  decimals?: number
  thresholds?: {
    low?: number
    high?: number
    lowColor?: string
    highColor?: string
  }
}

interface Props {
  title?: string
  items?: MonitorItem[]
  columns?: 1 | 2 | 3
  compact?: boolean
  showTimestamp?: boolean
  refreshRate?: number  // ms
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Script Monitor',
  items: () => [],
  columns: 1,
  compact: false,
  showTimestamp: false,
  refreshRate: 100
})

const emit = defineEmits<{
  (e: 'configure'): void
  (e: 'update:items', items: MonitorItem[]): void
}>()

const store = useDashboardStore()

// Local state for values
const values = ref<Record<string, any>>({})
const lastUpdate = ref<Date | null>(null)

// Get current value for a tag
function getValue(tag: string): any {
  // Check store.values for all tags (including py.* script-published values)
  if (store.values && tag in store.values) {
    const val = store.values[tag]
    return val?.value ?? val
  }

  // Check local cache
  if (tag in values.value) {
    return values.value[tag]
  }

  return null
}

// Format value based on config
function formatValue(item: MonitorItem, value: any): string {
  if (value === null || value === undefined) {
    return '--'
  }

  const format = item.format || 'number'
  const decimals = item.decimals ?? 2

  switch (format) {
    case 'integer':
      return Math.round(Number(value)).toString()
    case 'percent':
      return `${Number(value).toFixed(decimals)}%`
    case 'status':
      // Treat as boolean/status
      if (typeof value === 'boolean') {
        return value ? 'ON' : 'OFF'
      }
      if (typeof value === 'number') {
        return value > 0 ? 'ON' : 'OFF'
      }
      return String(value)
    case 'text':
      return String(value)
    case 'number':
    default:
      if (typeof value === 'number') {
        return value.toFixed(decimals)
      }
      return String(value)
  }
}

// Get color based on thresholds
function getValueColor(item: MonitorItem, value: any): string {
  if (value === null || value === undefined) {
    return 'var(--text-muted)'
  }

  if (!item.thresholds) {
    // Default colors for status format
    if (item.format === 'status') {
      const isOn = (typeof value === 'boolean' && value) ||
                   (typeof value === 'number' && value > 0) ||
                   (typeof value === 'string' && ['on', 'true', 'running', 'active'].includes(value.toLowerCase()))
      return isOn ? '#22c55e' : '#6b7280'
    }
    return 'var(--text-primary)'
  }

  const numValue = Number(value)
  if (isNaN(numValue)) return 'var(--text-primary)'

  if (item.thresholds.high !== undefined && numValue >= item.thresholds.high) {
    return item.thresholds.highColor || '#ef4444'
  }
  if (item.thresholds.low !== undefined && numValue <= item.thresholds.low) {
    return item.thresholds.lowColor || '#3b82f6'
  }

  return 'var(--text-primary)'
}

// Get status indicator class
function getStatusClass(item: MonitorItem, value: any): string {
  if (item.format !== 'status') return ''

  const isOn = (typeof value === 'boolean' && value) ||
               (typeof value === 'number' && value > 0) ||
               (typeof value === 'string' && ['on', 'true', 'running', 'active', '1'].includes(String(value).toLowerCase()))

  return isOn ? 'status-on' : 'status-off'
}

// Update values
let updateInterval: number | null = null

function updateValues() {
  let updated = false
  for (const item of props.items) {
    const newValue = getValue(item.tag)
    if (values.value[item.tag] !== newValue) {
      values.value[item.tag] = newValue
      updated = true
    }
  }
  if (updated) {
    lastUpdate.value = new Date()
  }
}

onMounted(() => {
  updateValues()
  updateInterval = window.setInterval(updateValues, props.refreshRate)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

// Watch for item changes
watch(() => props.items, () => {
  updateValues()
}, { deep: true })

// Computed for grid style
const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${props.columns}, 1fr)`
}))

// Format timestamp
const formattedTimestamp = computed(() => {
  if (!lastUpdate.value) return '--'
  return lastUpdate.value.toLocaleTimeString()
})
</script>

<template>
  <div class="script-monitor" :class="{ compact }">
    <div class="monitor-header">
      <h3>{{ title }}</h3>
      <div class="header-actions">
        <span v-if="showTimestamp" class="timestamp">{{ formattedTimestamp }}</span>
        <button class="config-btn" @click="emit('configure')" title="Configure">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="monitor-grid" :style="gridStyle">
      <div
        v-for="item in items"
        :key="item.tag"
        class="monitor-item"
        :class="getStatusClass(item, values[item.tag])"
      >
        <div class="item-label">{{ item.label || item.tag }}</div>
        <div class="item-value" :style="{ color: getValueColor(item, values[item.tag]) }">
          <span v-if="item.format === 'status'" class="status-indicator"></span>
          {{ formatValue(item, values[item.tag]) }}
          <span v-if="item.unit" class="item-unit">{{ item.unit }}</span>
        </div>
      </div>
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <p>No items configured</p>
      <button class="add-btn" @click="emit('configure')">Add Items</button>
    </div>
  </div>
</template>

<style scoped>
.script-monitor {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-color);
}

.monitor-header h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.timestamp {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.config-btn {
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  color: var(--text-muted);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.config-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.monitor-grid {
  display: grid;
  gap: 1px;
  background: var(--border-color);
}

.monitor-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: var(--bg-secondary);
}

.compact .monitor-item {
  padding: 6px 12px;
}

.item-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.compact .item-label {
  font-size: 0.75rem;
}

.item-value {
  font-size: 1rem;
  font-weight: 600;
  font-family: 'SF Mono', 'Consolas', monospace;
  display: flex;
  align-items: center;
  gap: 6px;
}

.compact .item-value {
  font-size: 0.85rem;
}

.item-unit {
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--text-muted);
}

/* Status indicator */
.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6b7280;
}

.status-on .status-indicator {
  background: #22c55e;
  box-shadow: 0 0 6px #22c55e;
}

.status-off .status-indicator {
  background: #6b7280;
}

/* Empty state */
.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
}

.empty-state p {
  margin: 0 0 12px 0;
}

.add-btn {
  background: var(--color-accent);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}

.add-btn:hover {
  opacity: 0.9;
}

/* Hover effect */
.monitor-item:hover {
  background: var(--bg-hover);
}

/* Multi-column layout adjustments */
@media (min-width: 400px) {
  .monitor-grid[style*="repeat(2"] .monitor-item,
  .monitor-grid[style*="repeat(3"] .monitor-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}
</style>
