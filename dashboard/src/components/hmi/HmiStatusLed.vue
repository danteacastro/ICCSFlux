<script setup lang="ts">
/**
 * HmiStatusLed — ISA-101 Status Indicator
 *
 * Simple circle indicator. Gray when normal, colored only on alarm/fault.
 * No glow effects (ISA-101 principle).
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

const isOn = computed(() => {
  if (!channelValue.value) return false
  return channelValue.value.value === 1
})

const alarmState = computed(() => {
  if (!channelValue.value) return 'disconnected'
  const val = channelValue.value
  if (val.alarm) return 'alarm'
  if (val.warning) return 'warning'
  // Check HMI thresholds for numeric values
  if (typeof val.value === 'number') {
    const v = val.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return isOn.value ? 'on' : 'off'
})
</script>

<template>
  <div class="hmi-led">
    <div class="hmi-led-circle" :class="[alarmState]" />
    <div v-if="symbol.label" class="hmi-led-label">{{ symbol.label }}</div>
  </div>
</template>

<style scoped>
.hmi-led {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  user-select: none;
}

.hmi-led-circle {
  width: 60%;
  aspect-ratio: 1;
  max-width: 36px;
  border-radius: 50%;
  background: #808080;
  border: 1px solid #666;
  transition: background-color 0.2s;
}

.hmi-led-circle.on {
  background: #2D862D;
  border-color: #1A6B1A;
}

.hmi-led-circle.off {
  background: #808080;
  border-color: #666;
}

.hmi-led-circle.alarm {
  background: #FF0000;
  border-color: #CC0000;
  animation: hmi-flash 1s step-end infinite;
}

.hmi-led-circle.warning {
  background: #FFD700;
  border-color: #CCA600;
}

.hmi-led-circle.disconnected {
  background: #555;
  border-color: #444;
}

@keyframes hmi-flash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.hmi-led-label {
  color: #555;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: clamp(7px, 24%, 10px);
  font-weight: 600;
  text-transform: uppercase;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
</style>
