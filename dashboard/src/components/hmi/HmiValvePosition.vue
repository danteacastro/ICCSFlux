<script setup lang="ts">
/**
 * HmiValvePosition — ISA-101 Valve Position Indicator
 *
 * Shows 0-100% valve travel with butterfly/gate symbol.
 * ISA-101: gray body, dark blue value, color only on alarm.
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

const minVal = computed(() => props.symbol.hmiMinValue ?? 0)
const maxVal = computed(() => props.symbol.hmiMaxValue ?? 100)
const range = computed(() => maxVal.value - minVal.value)

// Position as percentage 0-100
const positionPct = computed(() => {
  if (numericValue.value === null || range.value === 0) return 0
  const pct = ((numericValue.value - minVal.value) / range.value) * 100
  return Math.max(0, Math.min(100, pct))
})

const displayValue = computed(() => {
  if (numericValue.value === null) return '--'
  const dec = props.symbol.decimals ?? 0
  return numericValue.value.toFixed(dec) + '%'
})

const alarmState = computed(() => {
  if (!channelValue.value) return 'disconnected'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  if (numericValue.value !== null) {
    const v = numericValue.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return 'normal'
})

// Valve disc angle: 0% = 90° (closed), 100% = 0° (open)
const discAngle = computed(() => {
  return 90 - (positionPct.value / 100) * 90
})
</script>

<template>
  <div class="hmi-valve-pos" :class="[alarmState]">
    <div v-if="symbol.label" class="hmi-vp-label">{{ symbol.label }}</div>
    <div class="hmi-vp-body">
      <svg viewBox="0 0 60 50" class="hmi-vp-svg">
        <!-- Valve body (butterfly style) -->
        <polygon points="10,38 30,14 50,38" fill="none" stroke="#808080" stroke-width="2"/>
        <!-- Pipe stubs -->
        <line x1="5" y1="38" x2="55" y2="38" stroke="#808080" stroke-width="3"/>
        <!-- Disc (rotates with position) -->
        <line
          :x1="30 - 14 * Math.cos(discAngle * Math.PI / 180)"
          :y1="26 + 14 * Math.sin(discAngle * Math.PI / 180)"
          :x2="30 + 14 * Math.cos(discAngle * Math.PI / 180)"
          :y2="26 - 14 * Math.sin(discAngle * Math.PI / 180)"
          :stroke="alarmState === 'alarm' ? '#FF0000' : alarmState === 'warning' ? '#FF8C00' : '#1E3A8A'"
          stroke-width="2.5"
          stroke-linecap="round"
        />
        <!-- Center pivot -->
        <circle cx="30" cy="26" r="2.5" fill="#666"/>
      </svg>
    </div>
    <div class="hmi-vp-value">{{ displayValue }}</div>
  </div>
</template>

<style scoped>
.hmi-valve-pos {
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
  padding: 2px;
}

.hmi-valve-pos.alarm {
  border-color: #FF0000;
  border-width: 2px;
}

.hmi-valve-pos.warning {
  border-color: #FFD700;
  border-width: 2px;
}

.hmi-vp-label {
  color: #555;
  font-size: clamp(6px, 16%, 9px);
  font-weight: 600;
  text-transform: uppercase;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-vp-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
}

.hmi-vp-svg {
  width: 80%;
  height: 80%;
  max-width: 80px;
}

.hmi-vp-value {
  color: #1E3A8A;
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(8px, 24%, 14px);
  font-weight: 700;
  text-align: center;
  flex-shrink: 0;
}

.alarm .hmi-vp-value {
  color: #FF0000;
}

.warning .hmi-vp-value {
  color: #FF8C00;
}
</style>
