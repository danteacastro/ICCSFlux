<script setup lang="ts">
/**
 * HmiBarIndicator — ISA-101 Bar with Alarm Zone Segments
 *
 * Horizontal bar with colored alarm/warning zones, triangle pointer,
 * and numeric value display.
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
  return store.getChannelRef(props.symbol.channel).value ?? null
})

const channelConfig = computed(() => {
  if (!props.symbol.channel) return null
  return store.channels[props.symbol.channel] ?? null
})

const numericValue = computed(() => {
  if (!channelValue.value) return null
  const val = channelValue.value.value
  return typeof val === 'number' ? val : null
})

const displayValue = computed(() => {
  if (numericValue.value === null) return '--'
  const dec = props.symbol.decimals ?? 1
  return numericValue.value.toFixed(dec)
})

const unit = computed(() => {
  return props.symbol.hmiUnit || channelConfig.value?.unit || ''
})

const minVal = computed(() => props.symbol.hmiMinValue ?? 0)
const maxVal = computed(() => props.symbol.hmiMaxValue ?? 100)
const range = computed(() => maxVal.value - minVal.value)

// Pointer position as percentage
const pointerPercent = computed(() => {
  if (numericValue.value === null || range.value === 0) return 50
  const pct = ((numericValue.value - minVal.value) / range.value) * 100
  return Math.max(0, Math.min(100, pct))
})

// Alarm/warning zone positions as percentages
const alarmLowPct = computed(() => {
  if (props.symbol.hmiAlarmLow === undefined) return 0
  return Math.max(0, ((props.symbol.hmiAlarmLow - minVal.value) / range.value) * 100)
})

const warningLowPct = computed(() => {
  if (props.symbol.hmiWarningLow === undefined) return alarmLowPct.value
  return Math.max(0, ((props.symbol.hmiWarningLow - minVal.value) / range.value) * 100)
})

const warningHighPct = computed(() => {
  if (props.symbol.hmiWarningHigh === undefined) return 100 - alarmHighPct.value
  return Math.min(100, ((props.symbol.hmiWarningHigh - minVal.value) / range.value) * 100)
})

const alarmHighPct = computed(() => {
  if (props.symbol.hmiAlarmHigh === undefined) return 100
  return Math.min(100, ((props.symbol.hmiAlarmHigh - minVal.value) / range.value) * 100)
})

const isVertical = computed(() => props.symbol.hmiOrientation === 'vertical')

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
</script>

<template>
  <div class="hmi-bar" :class="[alarmState, { vertical: isVertical }]">
    <div v-if="symbol.label" class="hmi-bar-label">{{ symbol.label }}</div>
    <div class="hmi-bar-track">
      <!-- Alarm zones -->
      <div class="hmi-bar-zone zone-alarm-low" :style="{ width: alarmLowPct + '%' }" />
      <div class="hmi-bar-zone zone-warning-low" :style="{ left: alarmLowPct + '%', width: (warningLowPct - alarmLowPct) + '%' }" />
      <div class="hmi-bar-zone zone-warning-high" :style="{ left: warningHighPct + '%', width: (alarmHighPct - warningHighPct) + '%' }" />
      <div class="hmi-bar-zone zone-alarm-high" :style="{ left: alarmHighPct + '%', width: (100 - alarmHighPct) + '%' }" />
      <!-- Pointer -->
      <div class="hmi-bar-pointer" :style="{ left: pointerPercent + '%' }">
        <svg width="12" height="8" viewBox="0 0 12 8">
          <polygon points="0,8 6,0 12,8" fill="#333" />
        </svg>
      </div>
    </div>
    <div class="hmi-bar-value">
      <span class="hmi-bar-num">{{ displayValue }}</span>
      <span v-if="unit" class="hmi-bar-unit">{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.hmi-bar {
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
  padding: 2px;
}

.hmi-bar.alarm {
  border-color: var(--hmi-alarm, #FF0000);
  border-width: 2px;
}

.hmi-bar.warning {
  border-color: var(--hmi-warning, #FFD700);
  border-width: 2px;
}

.hmi-bar-label {
  color: var(--hmi-subtle-text, #555);
  font-size: clamp(6px, 18%, 9px);
  font-weight: 600;
  text-transform: uppercase;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
  margin-bottom: 1px;
}

.hmi-bar-track {
  position: relative;
  flex: 1;
  min-height: 8px;
  background: var(--hmi-inactive-bg, #E8E8E8);
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 1px;
}

.hmi-bar-zone {
  position: absolute;
  top: 0;
  height: 100%;
}

.zone-alarm-low, .zone-alarm-high {
  background: var(--hmi-alarm-zone, rgba(255, 0, 0, 0.15));
}

.zone-warning-low, .zone-warning-high {
  background: var(--hmi-warning-zone, rgba(255, 215, 0, 0.10));
}

.hmi-bar-pointer {
  position: absolute;
  top: -2px;
  transform: translateX(-6px);
  z-index: 1;
  line-height: 0;
}

.hmi-bar-value {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  flex-shrink: 0;
  margin-top: 1px;
}

.hmi-bar-num {
  color: var(--hmi-value-text, #1E3A8A);
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(7px, 24%, 12px);
  font-weight: 700;
}

.alarm .hmi-bar-num {
  color: var(--hmi-alarm, #FF0000);
}

.warning .hmi-bar-num {
  color: var(--hmi-warning-text, #FF8C00);
}

.hmi-bar-unit {
  color: var(--hmi-muted-text, #888);
  font-size: clamp(6px, 18%, 9px);
}
</style>
