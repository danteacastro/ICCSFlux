<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  channel: string
  label?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'change', value: boolean): void
}>()

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const isOn = computed(() => {
  if (!channelValue.value || isStale.value) return false
  return channelValue.value.value !== 0
})

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const canToggle = computed(() => !props.disabled && store.isAcquiring)

function toggle() {
  if (!canToggle.value) return
  emit('change', !isOn.value)
}
</script>

<template>
  <div class="toggle-switch" :class="{ disabled: !canToggle }">
    <div class="label">{{ displayLabel }}</div>
    <button
      class="switch"
      :class="{ on: isOn }"
      @click="toggle"
      :disabled="!canToggle"
    >
      <span class="slider"></span>
    </button>
  </div>
</template>

<style scoped>
.toggle-switch {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.toggle-switch.disabled {
  opacity: 0.5;
}

.label {
  font-size: 0.65rem;
  color: var(--label-color, #888);
  text-transform: uppercase;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.switch {
  position: relative;
  width: 40px;
  height: 20px;
  background: #4b5563;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  padding: 2px;
  transition: background 0.2s;
}

.switch.on {
  background: #22c55e;
}

.switch:disabled {
  cursor: not-allowed;
}

.slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.switch.on .slider {
  transform: translateX(20px);
}
</style>
