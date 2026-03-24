<script setup lang="ts">
/**
 * HmiArcGauge — ISA-101 270-Degree Arc Gauge
 *
 * Simple SVG arc with pointer, alarm zone arcs, and center value.
 * No skeuomorphic dial face — flat ISA-101 style.
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

// Arc geometry: 270 degrees, starting from 135° (bottom-left) to 45° (bottom-right) going clockwise
const CX = 50
const CY = 50
const R = 38
const START_ANGLE = 135 // degrees
const SWEEP = 270 // degrees

function angleToPoint(angleDeg: number): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180
  return { x: CX + R * Math.cos(rad), y: CY + R * Math.sin(rad) }
}

function valueToAngle(value: number): number {
  if (range.value === 0) return START_ANGLE
  const pct = Math.max(0, Math.min(1, (value - minVal.value) / range.value))
  return START_ANGLE + pct * SWEEP
}

function arcPath(startAngle: number, endAngle: number): string {
  const s = angleToPoint(startAngle)
  const e = angleToPoint(endAngle)
  const largeArc = (endAngle - startAngle) > 180 ? 1 : 0
  return `M ${s.x} ${s.y} A ${R} ${R} 0 ${largeArc} 1 ${e.x} ${e.y}`
}

// Full background arc
const bgArc = computed(() => arcPath(START_ANGLE, START_ANGLE + SWEEP))

// Value fill arc
const valueArc = computed(() => {
  if (numericValue.value === null) return ''
  const endAngle = valueToAngle(numericValue.value)
  if (endAngle <= START_ANGLE) return ''
  return arcPath(START_ANGLE, endAngle)
})

// Pointer line
const pointerEnd = computed(() => {
  if (numericValue.value === null) return angleToPoint(START_ANGLE)
  return angleToPoint(valueToAngle(numericValue.value))
})

// Alarm zone arcs
const alarmLowArc = computed(() => {
  if (props.symbol.hmiAlarmLow === undefined) return ''
  const end = valueToAngle(props.symbol.hmiAlarmLow)
  return arcPath(START_ANGLE, Math.min(end, START_ANGLE + SWEEP))
})

const alarmHighArc = computed(() => {
  if (props.symbol.hmiAlarmHigh === undefined) return ''
  const start = valueToAngle(props.symbol.hmiAlarmHigh)
  return arcPath(Math.max(start, START_ANGLE), START_ANGLE + SWEEP)
})

const warningLowArc = computed(() => {
  if (props.symbol.hmiWarningLow === undefined) return ''
  const start = props.symbol.hmiAlarmLow !== undefined ? valueToAngle(props.symbol.hmiAlarmLow) : START_ANGLE
  const end = valueToAngle(props.symbol.hmiWarningLow)
  return arcPath(start, end)
})

const warningHighArc = computed(() => {
  if (props.symbol.hmiWarningHigh === undefined) return ''
  const start = valueToAngle(props.symbol.hmiWarningHigh)
  const end = props.symbol.hmiAlarmHigh !== undefined ? valueToAngle(props.symbol.hmiAlarmHigh) : START_ANGLE + SWEEP
  return arcPath(start, end)
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
</script>

<template>
  <div class="hmi-gauge" :class="[alarmState]">
    <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
      <!-- Background circle -->
      <circle :cx="CX" :cy="CY" :r="R + 6" fill="#D4D4D4" stroke="#A0A0A4" stroke-width="1" />

      <!-- Background arc -->
      <path :d="bgArc" fill="none" stroke="#E0E0E0" stroke-width="6" stroke-linecap="round" />

      <!-- Alarm zone arcs -->
      <path v-if="alarmLowArc" :d="alarmLowArc" fill="none" stroke="rgba(255,0,0,0.3)" stroke-width="6" stroke-linecap="round" />
      <path v-if="warningLowArc" :d="warningLowArc" fill="none" stroke="rgba(255,215,0,0.25)" stroke-width="6" stroke-linecap="round" />
      <path v-if="warningHighArc" :d="warningHighArc" fill="none" stroke="rgba(255,215,0,0.25)" stroke-width="6" stroke-linecap="round" />
      <path v-if="alarmHighArc" :d="alarmHighArc" fill="none" stroke="rgba(255,0,0,0.3)" stroke-width="6" stroke-linecap="round" />

      <!-- Value arc -->
      <path v-if="valueArc" :d="valueArc" fill="none" stroke="#1E3A8A" stroke-width="6" stroke-linecap="round" />

      <!-- Pointer line -->
      <line :x1="CX" :y1="CY" :x2="pointerEnd.x" :y2="pointerEnd.y" stroke="#333" stroke-width="2" stroke-linecap="round" />
      <circle :cx="CX" :cy="CY" r="3" fill="#333" />

      <!-- Value text -->
      <text :x="CX" :y="CY + 16" text-anchor="middle" font-size="11" font-weight="bold" font-family="Consolas, monospace"
        :fill="alarmState === 'alarm' ? '#FF0000' : alarmState === 'warning' ? '#FF8C00' : '#1E3A8A'">
        {{ displayValue }}
      </text>

      <!-- Unit text -->
      <text v-if="unit" :x="CX" :y="CY + 24" text-anchor="middle" font-size="6" fill="#888" font-family="Segoe UI, Arial, sans-serif">
        {{ unit }}
      </text>

      <!-- Label text -->
      <text v-if="symbol.label" :x="CX" :y="14" text-anchor="middle" font-size="7" fill="#555" font-weight="600"
        font-family="Segoe UI, Arial, sans-serif" text-transform="uppercase">
        {{ symbol.label }}
      </text>

      <!-- Min/Max labels -->
      <text x="14" y="78" text-anchor="middle" font-size="5" fill="#888" font-family="Segoe UI, sans-serif">{{ minVal }}</text>
      <text x="86" y="78" text-anchor="middle" font-size="5" fill="#888" font-family="Segoe UI, sans-serif">{{ maxVal }}</text>
    </svg>
  </div>
</template>

<style scoped>
.hmi-gauge {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}

.hmi-gauge.alarm svg circle:first-child {
  stroke: var(--hmi-alarm, #FF0000);
  stroke-width: 2;
}

.hmi-gauge.warning svg circle:first-child {
  stroke: var(--hmi-warning, #FFD700);
  stroke-width: 2;
}

.hmi-gauge svg {
  width: 100%;
  height: 100%;
}
</style>
