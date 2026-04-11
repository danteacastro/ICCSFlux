<script setup lang="ts">
/**
 * HmiSelectorSwitch — ISA-101 Multi-Position Selector
 *
 * Multi-position switch (e.g., Auto/Manual/Off).
 * Writes selected position index to channel.
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
  return store.getChannelRef(props.symbol.channel).value ?? null
})

const currentPosition = computed(() => {
  if (!channelValue.value) return null
  return channelValue.value.value
})

// Default positions if none configured
const defaultPositions = [
  { value: 0, label: 'OFF' },
  { value: 1, label: 'MAN' },
  { value: 2, label: 'AUTO' },
]

const positions = computed(() => {
  return props.symbol.hmiSelectorPositions?.length ? props.symbol.hmiSelectorPositions : defaultPositions
})

const isBlocked = computed(() => {
  if (!props.symbol.channel) return false
  return safety.isOutputBlocked(props.symbol.channel).blocked
})

const canOperate = computed(() => {
  return !props.editMode && props.symbol.channel && store.isConnected && store.isAcquiring && !isBlocked.value
})

function selectPosition(value: number) {
  if (!canOperate.value || !props.symbol.channel) return
  mqtt.setOutput(props.symbol.channel, value)
}
</script>

<template>
  <div class="hmi-selector" :class="{ blocked: isBlocked, disabled: !canOperate }">
    <div v-if="symbol.label" class="hmi-sel-label">{{ symbol.label }}</div>
    <div class="hmi-sel-positions">
      <button
        v-for="pos in positions"
        :key="pos.value"
        class="hmi-sel-btn"
        :class="{ active: currentPosition === pos.value }"
        @click.stop="selectPosition(pos.value)"
        :disabled="!canOperate || currentPosition === pos.value"
      >{{ pos.label }}</button>
    </div>
  </div>
</template>

<style scoped>
.hmi-selector {
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

.hmi-selector.blocked {
  border-color: var(--hmi-alarm, #FF0000);
}

.hmi-selector.disabled {
  opacity: 0.5;
}

.hmi-sel-label {
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

.hmi-sel-positions {
  flex: 1;
  display: flex;
  gap: 2px;
  padding: 3px;
  min-height: 0;
}

.hmi-sel-btn {
  flex: 1;
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 1px;
  background: var(--hmi-inactive-bg, #E8E8E8);
  color: var(--hmi-muted-text, #888);
  font-size: clamp(7px, 24%, 11px);
  font-weight: 700;
  font-family: 'Segoe UI', Arial, sans-serif;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 2px;
}

.hmi-sel-btn:disabled {
  cursor: default;
}

.hmi-sel-btn.active {
  background: var(--hmi-accent, #4169E1);
  border-color: var(--hmi-accent-dark, #2850B0);
  color: var(--hmi-on-text, white);
}

.hmi-sel-btn:not(:disabled):not(.active):hover {
  border-color: var(--hmi-accent, #4169E1);
}
</style>
