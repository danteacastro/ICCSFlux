<script setup lang="ts">
/**
 * HmiToggleControl — ISA-101 On/Off Switch
 *
 * Rectangular toggle with text labels. ISA-101 style: no iOS pill shape.
 * Writes to digital output channel via MQTT.
 */
import { computed } from 'vue'
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

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.values[props.symbol.channel] ?? null
})

const isOn = computed(() => {
  if (!channelValue.value) return false
  return channelValue.value.value === 1
})

const isBlocked = computed(() => {
  if (!props.symbol.channel) return false
  return safety.isOutputBlocked(props.symbol.channel).blocked
})

const canOperate = computed(() => {
  return !props.editMode && props.symbol.channel && store.isConnected && store.isAcquiring && !isBlocked.value
})

function toggle() {
  if (!canOperate.value || !props.symbol.channel) return
  mqtt.setOutput(props.symbol.channel, isOn.value ? 0 : 1)
}
</script>

<template>
  <div class="hmi-toggle" :class="{ blocked: isBlocked, disabled: !canOperate }">
    <div v-if="symbol.label" class="hmi-toggle-label">{{ symbol.label }}</div>
    <div class="hmi-toggle-buttons">
      <button
        class="hmi-toggle-btn on-btn"
        :class="{ active: isOn }"
        @click.stop="toggle"
        :disabled="!canOperate || isOn"
      >ON</button>
      <button
        class="hmi-toggle-btn off-btn"
        :class="{ active: !isOn }"
        @click.stop="toggle"
        :disabled="!canOperate || !isOn"
      >OFF</button>
    </div>
  </div>
</template>

<style scoped>
.hmi-toggle {
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

.hmi-toggle.blocked {
  border-color: var(--hmi-alarm, #FF0000);
}

.hmi-toggle.disabled {
  opacity: 0.5;
}

.hmi-toggle-label {
  background: var(--hmi-label-bg, #C0C0C0);
  color: var(--hmi-label-text, #333);
  font-size: clamp(7px, 22%, 10px);
  font-weight: 600;
  text-transform: uppercase;
  padding: 2px 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.hmi-toggle-buttons {
  flex: 1;
  display: flex;
  gap: 2px;
  padding: 3px;
  min-height: 0;
}

.hmi-toggle-btn {
  flex: 1;
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 1px;
  font-size: clamp(8px, 30%, 12px);
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  font-family: 'Segoe UI', Arial, sans-serif;
}

.hmi-toggle-btn:disabled {
  cursor: default;
}

.on-btn {
  background: var(--hmi-inactive-bg, #E8E8E8);
  color: var(--hmi-muted-text, #888);
}

.on-btn.active {
  background: var(--hmi-led-on, #2D862D);
  border-color: var(--hmi-led-on-border, #1A6B1A);
  color: var(--hmi-on-text, white);
}

.off-btn {
  background: var(--hmi-inactive-bg, #E8E8E8);
  color: var(--hmi-muted-text, #888);
}

.off-btn.active {
  background: var(--hmi-led-off, #808080);
  border-color: var(--hmi-led-off-border, #666);
  color: var(--hmi-on-text, white);
}

.hmi-toggle-btn:not(:disabled):hover {
  border-color: var(--hmi-accent, #4169E1);
}
</style>
