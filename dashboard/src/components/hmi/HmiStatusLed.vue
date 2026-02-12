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
  background: var(--hmi-led-off, #808080);
  border: 1px solid var(--hmi-led-off-border, #666);
  transition: background-color 0.2s;
}

.hmi-led-circle.on {
  background: var(--hmi-led-on, #2D862D);
  border-color: var(--hmi-led-on-border, #1A6B1A);
}

.hmi-led-circle.off {
  background: var(--hmi-led-off, #808080);
  border-color: var(--hmi-led-off-border, #666);
}

.hmi-led-circle.alarm {
  background: var(--hmi-alarm, #FF0000);
  border-color: var(--hmi-alarm-dark, #CC0000);
  animation: hmi-flash 1s step-end infinite;
}

.hmi-led-circle.warning {
  background: var(--hmi-warning, #FFD700);
  border-color: var(--hmi-warning-border, #CCA600);
}

.hmi-led-circle.disconnected {
  background: var(--hmi-disconnected-bg, #555);
  border-color: var(--hmi-disconnected-border, #444);
}

@keyframes hmi-flash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.hmi-led-label {
  color: var(--hmi-subtle-text, #555);
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
