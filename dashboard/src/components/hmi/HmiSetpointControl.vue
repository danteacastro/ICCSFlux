<script setup lang="ts">
/**
 * HmiSetpointControl — ISA-101 Editable Setpoint
 *
 * Click-to-edit numeric value with range display.
 * Writes to analog/modbus output channel via MQTT.
 */
import { ref, computed, nextTick } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useMqtt } from '../../composables/useMqtt'
import { useSafety } from '../../composables/useSafety'
import type { PidSymbol } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()

const isEditing = ref(false)
const editValue = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.getChannelRef(props.symbol.channel).value ?? null
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

const minValue = computed(() => props.symbol.hmiMinValue ?? 0)
const maxValue = computed(() => props.symbol.hmiMaxValue ?? 100)

const isBlocked = computed(() => {
  if (!props.symbol.channel) return false
  return safety.isOutputBlocked(props.symbol.channel).blocked
})

const canOperate = computed(() => {
  return !props.editMode && props.symbol.channel && store.isConnected && store.isAcquiring && !isBlocked.value
})

const alarmState = computed(() => {
  if (!channelValue.value) return 'disconnected'
  const val = channelValue.value
  if (val.alarm) return 'alarm'
  if (val.warning) return 'warning'
  if (typeof val.value === 'number') {
    const v = val.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return 'normal'
})

function startEdit() {
  if (!canOperate.value) return
  isEditing.value = true
  editValue.value = displayValue.value === '--' ? '' : displayValue.value
  nextTick(() => {
    inputRef.value?.select()
  })
}

function applyEdit() {
  if (!props.symbol.channel) return
  const val = parseFloat(editValue.value)
  if (isNaN(val)) {
    isEditing.value = false
    return
  }
  const clamped = Math.min(Math.max(val, minValue.value), maxValue.value)
  mqtt.setOutput(props.symbol.channel, clamped)
  isEditing.value = false
}

function cancelEdit() {
  isEditing.value = false
}
</script>

<template>
  <div class="hmi-setpoint" :class="[alarmState, { blocked: isBlocked, disabled: !canOperate }]">
    <div class="hmi-sp-label">{{ symbol.label || 'SP' }}</div>
    <div class="hmi-sp-body" @click.stop="startEdit">
      <template v-if="isEditing">
        <input
          ref="inputRef"
          v-model="editValue"
          type="number"
          class="hmi-sp-input"
          :min="minValue"
          :max="maxValue"
          @keydown.enter="applyEdit"
          @keydown.escape="cancelEdit"
          @blur="applyEdit"
          @click.stop
        />
      </template>
      <template v-else>
        <span class="hmi-sp-value">{{ displayValue }}</span>
        <span v-if="unit" class="hmi-sp-unit">{{ unit }}</span>
      </template>
    </div>
    <div class="hmi-sp-range">{{ minValue }} – {{ maxValue }}</div>
  </div>
</template>

<style scoped>
.hmi-setpoint {
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

.hmi-setpoint.alarm {
  border-color: var(--hmi-alarm, #FF0000);
  border-width: 2px;
}

.hmi-setpoint.warning {
  border-color: var(--hmi-warning, #FFD700);
  border-width: 2px;
}

.hmi-setpoint.disabled {
  opacity: 0.5;
}

.hmi-sp-label {
  background: var(--hmi-label-bg, #C0C0C0);
  color: var(--hmi-label-text, #333);
  font-size: clamp(7px, 18%, 10px);
  font-weight: 600;
  text-transform: uppercase;
  padding: 1px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-sp-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 2px 4px;
  background: var(--hmi-input-bg, white);
  margin: 3px;
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 1px;
  cursor: pointer;
  min-height: 0;
}

.hmi-sp-body:hover {
  border-color: var(--hmi-accent, #4169E1);
}

.disabled .hmi-sp-body {
  cursor: default;
  background: var(--hmi-inactive-bg, #E8E8E8);
}

.hmi-sp-value {
  color: var(--hmi-value-text, #1E3A8A);
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(10px, 40%, 20px);
  font-weight: 700;
  line-height: 1;
}

.alarm .hmi-sp-value {
  color: var(--hmi-alarm, #FF0000);
}

.warning .hmi-sp-value {
  color: var(--hmi-warning-text, #FF8C00);
}

.hmi-sp-unit {
  color: var(--hmi-muted-text, #888);
  font-size: clamp(7px, 24%, 11px);
}

.hmi-sp-input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--hmi-value-text, #1E3A8A);
  font-family: 'Consolas', 'JetBrains Mono', monospace;
  font-size: clamp(10px, 40%, 20px);
  font-weight: 700;
  text-align: center;
}

.hmi-sp-range {
  color: var(--hmi-muted-text, #888);
  font-size: clamp(6px, 14%, 9px);
  text-align: center;
  padding: 1px 4px 2px;
  flex-shrink: 0;
}
</style>
