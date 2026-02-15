<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'

const props = defineProps<{
  channels?: string[]
  label?: string
  columns?: number
  historyLength?: number
  decimals?: number
  showUnits?: boolean
}>()

const store = useDashboardStore()

const maxPoints = computed(() => props.historyLength ?? 60)
const colCount = computed(() => Math.max(1, Math.min(6, props.columns ?? 3)))

// Per-channel history buffers
const histories = ref<Record<string, { value: number; time: number }[]>>({})

// Watch all channel values and push into histories
watch(
  () => {
    if (!props.channels?.length) return null
    return props.channels.map(ch => store.values[ch]?.value)
  },
  () => {
    if (!props.channels?.length) return
    const now = Date.now()
    for (const ch of props.channels) {
      const val = store.values[ch]
      if (!val) continue
      if (!histories.value[ch]) histories.value[ch] = []
      const hist = histories.value[ch]!
      // Avoid duplicate pushes for same timestamp
      const last = hist.length > 0 ? hist[hist.length - 1] : undefined
      if (last && last.time === val.timestamp) continue
      hist.push({ value: val.value, time: now })
      if (hist.length > maxPoints.value) {
        hist.splice(0, hist.length - maxPoints.value)
      }
    }
  },
  { immediate: true, deep: true }
)

// Periodic cleanup of stale history
let cleanupInterval: number | null = null
onMounted(() => {
  cleanupInterval = window.setInterval(() => {
    const cutoff = Date.now() - maxPoints.value * 1000
    for (const ch in histories.value) {
      const arr = histories.value[ch]
      if (arr) histories.value[ch] = arr.filter(h => h.time > cutoff)
    }
  }, 5000)
})
onUnmounted(() => {
  if (cleanupInterval) clearInterval(cleanupInterval)
})

// Build cell data for each channel
const cells = computed(() => {
  if (!props.channels?.length) return []
  return props.channels.map(ch => {
    const config = store.channels[ch]
    const value = store.values[ch]
    const hist = histories.value[ch] ?? []

    const isStale = !value?.timestamp || !store.isAcquiring ||
                    (Date.now() - value.timestamp) > 5000

    const formattedValue = isStale || !value
      ? '--'
      : value.value.toFixed(props.decimals ?? 1)

    const unit = formatUnit(config?.unit)

    // SVG sparkline path
    let path = ''
    let lineColor = 'var(--color-success-light)'
    if (hist.length >= 2) {
      const w = 100, h = 24, pad = 1
      const vals = hist.map(p => p.value)
      const min = Math.min(...vals)
      const max = Math.max(...vals)
      const range = max - min || 1
      const pts = hist.map((p, i) => {
        const x = pad + (i / (hist.length - 1)) * (w - pad * 2)
        const y = h - pad - ((p.value - min) / range) * (h - pad * 2)
        return `${x},${y}`
      })
      path = `M ${pts.join(' L ')}`
    }

    if (value?.alarm) lineColor = 'var(--color-error)'
    else if (value?.warning) lineColor = 'var(--color-warning)'

    const statusClass = value?.alarm ? 'alarm' : value?.warning ? 'warning' : isStale ? 'stale' : 'normal'

    return { ch, label: ch.replace(/^py\./, ''), formattedValue, unit, path, lineColor, statusClass, isStale }
  })
})
</script>

<template>
  <div class="small-multiples-widget">
    <div v-if="label" class="widget-header">{{ label }}</div>
    <div
      class="grid"
      :style="{ gridTemplateColumns: `repeat(${colCount}, 1fr)` }"
    >
      <div
        v-for="cell in cells"
        :key="cell.ch"
        class="cell"
        :class="cell.statusClass"
      >
        <div class="cell-header">
          <span class="cell-label">{{ cell.label }}</span>
          <span class="cell-value">{{ cell.formattedValue }}<span v-if="showUnits !== false && cell.unit" class="cell-unit"> {{ cell.unit }}</span></span>
        </div>
        <svg v-if="cell.path" viewBox="0 0 100 24" preserveAspectRatio="none" class="cell-spark">
          <path :d="cell.path" fill="none" :stroke="cell.lineColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <div v-else class="cell-spark cell-spark-empty" />
      </div>
    </div>
    <div v-if="!cells.length" class="empty-state">No channels configured</div>
  </div>
</template>

<style scoped>
.small-multiples-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.widget-header {
  padding: 4px 8px;
  background: var(--bg-gradient-elevated);
  border-bottom: 1px solid var(--border-color);
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.grid {
  flex: 1;
  display: grid;
  gap: 1px;
  background: var(--border-color);
  overflow-y: auto;
  min-height: 0;
}

.cell {
  display: flex;
  flex-direction: column;
  padding: 4px 6px;
  background: var(--bg-widget);
  min-height: 0;
  overflow: hidden;
}

.cell-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 4px;
  min-height: 14px;
}

.cell-label {
  font-size: 0.6rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}

.cell-value {
  font-size: 0.75rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--color-success-light);
  white-space: nowrap;
  flex-shrink: 0;
}

.cell-unit {
  font-size: 0.55rem;
  color: var(--text-muted);
  font-weight: 400;
}

.cell-spark {
  flex: 1;
  width: 100%;
  min-height: 16px;
}

.cell-spark-empty {
  min-height: 16px;
}

/* Status colors */
.cell.stale .cell-value {
  color: var(--text-muted);
}

.cell.warning {
  border-left: 2px solid var(--color-warning);
}
.cell.warning .cell-value {
  color: var(--color-warning);
}

.cell.alarm {
  border-left: 2px solid var(--color-error);
  animation: pulse-alarm 1s infinite;
}
.cell.alarm .cell-value {
  color: var(--color-error);
}

.empty-state {
  padding: 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8rem;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: var(--bg-widget); }
  50% { background-color: var(--bg-alarm-pulse); }
}
</style>
