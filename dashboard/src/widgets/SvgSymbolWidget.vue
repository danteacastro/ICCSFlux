<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, type ScadaSymbolType } from '../assets/symbols'

const props = defineProps<{
  channel?: string
  label?: string
  symbol?: ScadaSymbolType
  showValue?: boolean
  showLabel?: boolean
  decimals?: number
  valuePosition?: 'top' | 'bottom' | 'left' | 'right' | 'inside'
  accentColor?: string
  size?: 'small' | 'medium' | 'large'
  rotation?: 0 | 90 | 180 | 270
}>()

const store = useDashboardStore()

const channelConfig = computed(() => props.channel ? store.channels[props.channel] : null)
const channelValue = computed(() => props.channel ? store.values[props.channel] : null)

// Check if data is stale
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

// For digital outputs (valves), check if ON
const isActive = computed(() => {
  if (!channelValue.value) return false
  const val = channelValue.value.value
  // Boolean or truthy number
  if (typeof val === 'boolean') return val
  if (typeof val === 'number') return val === 1 || val > 0.5
  return false
})

const displayValue = computed(() => {
  if (!channelValue.value) return '--'
  if (isStale.value) return '--'
  const val = channelValue.value.value
  // For boolean/digital
  if (typeof val === 'boolean') return val ? 'ON' : 'OFF'
  if (channelConfig.value?.channel_type === 'digital_output' ||
      channelConfig.value?.channel_type === 'digital_input') {
    return val ? 'ON' : 'OFF'
  }
  const dec = props.decimals ?? 1
  return val.toFixed(dec)
})

const unit = computed(() => channelConfig.value?.unit || '')

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel || ''
)

const symbolSvg = computed(() => {
  const sym = props.symbol || 'solenoidValve'
  return SCADA_SYMBOLS[sym] || SCADA_SYMBOLS.solenoidValve
})

const statusClass = computed(() => {
  if (!channelValue.value || isStale.value) return 'stale'
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  if (isActive.value) return 'active'
  return 'normal'
})

const symbolColor = computed(() => {
  if (props.accentColor) return props.accentColor
  if (isStale.value) return '#666'
  if (channelValue.value?.alarm) return '#ef4444'
  if (channelValue.value?.warning) return '#fbbf24'
  if (isActive.value) return '#22c55e' // Green when active
  return '#60a5fa' // Blue default
})

const rotation = computed(() => props.rotation || 0)
</script>

<template>
  <div
    class="svg-symbol-widget"
    :class="[statusClass, size || 'medium', `value-${valuePosition || 'bottom'}`]"
  >
    <!-- Label (if top) -->
    <div v-if="showLabel !== false && (valuePosition === 'bottom' || valuePosition === 'inside')" class="symbol-label top">
      {{ displayLabel }}
    </div>

    <div class="symbol-container">
      <!-- Value on left -->
      <div v-if="showValue !== false && valuePosition === 'left'" class="value-display side">
        <span class="value">{{ displayValue }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>

      <!-- Symbol -->
      <div
        class="symbol"
        :style="{ color: symbolColor, transform: rotation ? `rotate(${rotation}deg)` : undefined }"
        v-html="symbolSvg"
      />

      <!-- Value inside symbol (overlay) -->
      <div v-if="showValue !== false && valuePosition === 'inside'" class="value-display inside">
        <span class="value">{{ displayValue }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>

      <!-- Value on right -->
      <div v-if="showValue !== false && valuePosition === 'right'" class="value-display side">
        <span class="value">{{ displayValue }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>
    </div>

    <!-- Value below (default) -->
    <div v-if="showValue !== false && (!valuePosition || valuePosition === 'bottom')" class="value-display bottom">
      <span class="value">{{ displayValue }}</span>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>

    <!-- Value above -->
    <div v-if="showValue !== false && valuePosition === 'top'" class="value-display top">
      <span class="value">{{ displayValue }}</span>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>

    <!-- Label (if bottom) -->
    <div v-if="showLabel !== false && valuePosition === 'top'" class="symbol-label bottom">
      {{ displayLabel }}
    </div>
  </div>
</template>

<style scoped>
.svg-symbol-widget {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
  background: var(--widget-bg, transparent);
  border-radius: 4px;
  gap: 2px;
}

.symbol-container {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  flex: 1;
  min-height: 0;
}

.symbol {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.3s;
}

.symbol :deep(svg) {
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
}

/* Size variants */
.small .symbol {
  width: 40px;
  height: 40px;
}

.medium .symbol {
  width: 60px;
  height: 60px;
}

.large .symbol {
  width: 100px;
  height: 100px;
}

.symbol-label {
  font-size: 0.65rem;
  color: var(--text-secondary, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.value-display {
  display: flex;
  align-items: baseline;
  gap: 2px;
  white-space: nowrap;
}

.value-display.bottom,
.value-display.top {
  justify-content: center;
}

.value-display.side {
  flex-direction: column;
  align-items: center;
  padding: 0 4px;
}

.value-display.inside {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.7);
  padding: 2px 6px;
  border-radius: 3px;
}

.value {
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: var(--value-color, #fff);
}

.unit {
  font-size: 0.6rem;
  color: var(--text-secondary, #888);
}

/* Status states */
.normal .symbol {
  opacity: 0.9;
}

.active .symbol {
  filter: drop-shadow(0 0 4px currentColor);
}

.stale .symbol {
  opacity: 0.4;
}

.warning .symbol {
  animation: pulse-warning 2s infinite;
}

.alarm .symbol {
  animation: pulse-alarm 1s infinite;
}

@keyframes pulse-warning {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

@keyframes pulse-alarm {
  0%, 100% { opacity: 1; filter: drop-shadow(0 0 6px #ef4444); }
  50% { opacity: 0.7; filter: none; }
}

/* Value position specific layouts */
.value-left .symbol-container,
.value-right .symbol-container {
  flex-direction: row;
}
</style>
