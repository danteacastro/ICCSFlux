<script setup lang="ts">
/**
 * HmiNumericIndicator — ISA-101 Numeric Value Display
 *
 * Gray label bar at top, large dark-blue value below, unit suffix.
 * Color changes only for alarm/warning states.
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

const channelConfig = computed(() => {
  if (!props.symbol.channel) return null
  return store.channels[props.symbol.channel] ?? null
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  const val = channelValue.value.value
  const dec = props.symbol.decimals ?? 1
  return typeof val === 'number' ? val.toFixed(dec) : String(val)
})

const unit = computed(() => {
  return props.symbol.hmiUnit || channelConfig.value?.unit || ''
})

const alarmState = computed(() => {
  if (!channelValue.value) return 'disconnected'
  const val = channelValue.value
  if (val.alarm) return 'alarm'
  if (val.warning) return 'warning'
  // Check HMI thresholds
  if (typeof val.value === 'number') {
    const v = val.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return 'normal'
})
</script>

<template>
  <div class="hmi-numeric" :class="[alarmState]">
    <div class="hmi-numeric-label">{{ symbol.label || symbol.channel || 'TAG' }}</div>
    <div class="hmi-numeric-body">
      <span class="hmi-numeric-value">{{ displayValue }}</span>
      <span v-if="unit" class="hmi-numeric-unit">{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.hmi-numeric {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #D4D4D4;
  border: 1px solid #A0A0A4;
  border-radius: 2px;
  overflow: hidden;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
}

.hmi-numeric.alarm {
  border-color: #FF0000;
  border-width: 2px;
}

.hmi-numeric.warning {
  border-color: #FFD700;
  border-width: 2px;
}

.hmi-numeric.disconnected {
  opacity: 0.5;
}

.hmi-numeric-label {
  background: #C0C0C0;
  color: #333;
  font-size: clamp(7px, 22%, 11px);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  padding: 2px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-numeric-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 2px 6px;
  min-height: 0;
}

.hmi-numeric-value {
  color: #1E3A8A;
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(10px, 50%, 24px);
  font-weight: 700;
  line-height: 1;
}

.alarm .hmi-numeric-value {
  color: #FF0000;
}

.warning .hmi-numeric-value {
  color: #FF8C00;
}

.hmi-numeric-unit {
  color: #888;
  font-size: clamp(7px, 30%, 12px);
  font-weight: 400;
}
</style>
