<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  channel: string
  label?: string
  decimals?: number
  showUnit?: boolean
}>()

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale (no update in last 5 seconds) or system not acquiring
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  if (isStale.value) return '--'
  const val = channelValue.value.value
  const dec = props.decimals ?? 2
  return val.toFixed(dec)
})

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return channelConfig.value?.unit || ''
})

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const statusClass = computed(() => {
  if (!channelValue.value || isStale.value) return 'stale'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  return 'normal'
})
</script>

<template>
  <div class="numeric-display" :class="statusClass">
    <div class="label">{{ displayLabel }}</div>
    <div class="value-container">
      <span class="value">{{ displayValue }}</span>
      <span class="unit" v-if="unit">{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.numeric-display {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.label {
  font-size: 0.7rem;
  color: var(--label-color, #888);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.value-container {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.value {
  font-size: 1.4rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--value-color, #fff);
}

.unit {
  font-size: 0.7rem;
  color: var(--unit-color, #888);
}

.normal .value {
  color: #4ade80;
}

.stale .value {
  color: #666;
}

.warning {
  border-color: #fbbf24;
}
.warning .value {
  color: #fbbf24;
}

.alarm {
  border-color: #ef4444;
  animation: pulse-alarm 1s infinite;
}
.alarm .value {
  color: #ef4444;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: #1a1a2e; }
  50% { background-color: #3f1515; }
}
</style>
