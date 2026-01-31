<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import InterlockBlockOverlay from '../components/InterlockBlockOverlay.vue'

const props = defineProps<{
  widgetId?: string
  channel: string
  label?: string
  disabled?: boolean
  onLabel?: string      // Label when ON
  offLabel?: string     // Label when OFF
  confirmOn?: boolean   // Require confirmation to turn ON
  confirmOff?: boolean  // Require confirmation to turn OFF
  style?: { onColor?: string; offColor?: string }
}>()

const emit = defineEmits<{
  (e: 'change', value: boolean): void
}>()

const store = useDashboardStore()
const safety = useSafety()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if output is blocked by interlocks (e.g., latched alarms)
const blockStatus = computed(() => safety.isOutputBlocked(props.channel))
const isBlocked = computed(() => blockStatus.value.blocked)
const blockedBy = computed(() => blockStatus.value.blockedBy.map(s => s.name).join(', '))

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

// Display label - use onLabel/offLabel if provided, otherwise fallback to label or channel
const displayLabel = computed(() => {
  if (isOn.value && props.onLabel) return props.onLabel
  if (!isOn.value && props.offLabel) return props.offLabel
  return props.label || channelConfig.value?.name || props.channel
})

// Custom colors from style prop
const onColor = computed(() => props.style?.onColor || '#22c55e')
const offColor = computed(() => props.style?.offColor || '#4b5563')

// Block toggle if: disabled, not acquiring, OR blocked by interlocks
const canToggle = computed(() => !props.disabled && store.isAcquiring && !isBlocked.value)

const statusText = computed(() => {
  if (isBlocked.value) return `Blocked: ${blockedBy.value}`
  if (!store.isAcquiring) return 'Not acquiring'
  return ''
})

function toggle() {
  if (!canToggle.value) return
  emit('change', !isOn.value)
}
</script>

<template>
  <div class="toggle-switch" :class="{ disabled: !canToggle, blocked: isBlocked }" :title="statusText">
    <div class="label">{{ displayLabel }}</div>
    <button
      class="switch"
      :class="{ on: isOn }"
      :style="{ backgroundColor: isOn ? onColor : offColor }"
      @click="toggle"
      :disabled="!canToggle"
    >
      <span class="slider"></span>
    </button>
    <InterlockBlockOverlay v-if="isBlocked" :blocked-by="blockStatus.blockedBy" />
  </div>
</template>

<style scoped>
.toggle-switch {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  container-type: size;
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

/* Compact horizontal layout when short (1 row ~30-40px) */
@container (max-height: 50px) {
  .toggle-switch {
    flex-direction: row;
    gap: 8px;
    padding: 4px 8px;
  }

  .label {
    margin-bottom: 0;
    flex: 1;
    text-align: left;
  }

  .switch {
    flex-shrink: 0;
  }
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

.toggle-switch.blocked {
  border: 2px solid #dc2626;
  animation: pulse-blocked 2s ease-in-out infinite;
}

.toggle-switch.blocked .switch {
  background: #7f1d1d;
}

@keyframes pulse-blocked {
  0%, 100% { box-shadow: 0 0 4px rgba(220, 38, 38, 0.3); }
  50% { box-shadow: 0 0 12px rgba(220, 38, 38, 0.6); }
}
</style>
