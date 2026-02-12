<script setup lang="ts">
/**
 * HmiMultiStateIndicator — ISA-101 Multi-State Display
 *
 * Shows one of N named states with ISA-101 colors.
 * Configurable value-to-state mapping via hmiStates.
 */
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import type { PidSymbol } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const store = useDashboardStore()

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.values[props.symbol.channel] ?? null
})

const numericValue = computed(() => {
  if (!channelValue.value) return null
  const val = channelValue.value.value
  return typeof val === 'number' ? val : null
})

// Default states if none configured
const defaultStates = [
  { value: 0, label: 'OFF', color: '#808080' },
  { value: 1, label: 'ON', color: '#2D862D' },
  { value: 2, label: 'FAULT', color: '#FF0000' },
]

const states = computed(() => {
  return props.symbol.hmiStates?.length ? props.symbol.hmiStates : defaultStates
})

const currentState = computed(() => {
  if (numericValue.value === null) {
    return { label: 'N/A', color: '#555' }
  }
  const val = numericValue.value
  // Find matching state (exact match first, then closest)
  const exact = states.value.find(s => s.value === val)
  if (exact) return exact
  // For integer values, try rounding
  const rounded = states.value.find(s => s.value === Math.round(val))
  if (rounded) return rounded
  return { label: String(val), color: '#808080' }
})

const isAlarm = computed(() => {
  // Check backend alarm flags first (consistent with all other HMI controls)
  if (channelValue.value?.alarm) return true
  if (channelValue.value?.warning) return true
  // Check HMI threshold overrides
  if (numericValue.value !== null) {
    const v = numericValue.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return true
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return true
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return true
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return true
  }
  // No color-based fallback — alarm state should come from backend flags or HMI thresholds
  return false
})
</script>

<template>
  <div class="hmi-multistate" :class="{ alarm: isAlarm }">
    <div v-if="symbol.label" class="hmi-ms-label">{{ symbol.label }}</div>
    <div class="hmi-ms-body">
      <div class="hmi-ms-dot" :style="{ background: currentState.color }" />
      <span class="hmi-ms-state">{{ currentState.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.hmi-multistate {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--hmi-panel-bg, #D4D4D4);
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 2px;
  overflow: hidden;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
}

.hmi-multistate.alarm {
  border-color: var(--hmi-alarm, #FF0000);
  border-width: 2px;
}

.hmi-ms-label {
  background: var(--hmi-label-bg, #C0C0C0);
  color: var(--hmi-label-text, #333);
  font-size: clamp(7px, 20%, 10px);
  font-weight: 600;
  text-transform: uppercase;
  padding: 1px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-ms-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 2px 6px;
  min-height: 0;
}

.hmi-ms-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(0,0,0,0.2);
}

.hmi-ms-state {
  color: var(--hmi-label-text, #333);
  font-size: clamp(8px, 30%, 14px);
  font-weight: 700;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
