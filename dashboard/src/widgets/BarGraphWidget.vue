<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { formatUnit } from '../utils/formatUnit'
import type { WidgetStyle } from '../types'

export type BarGraphStyle = 'bar' | 'tank' | 'thermometer'

const props = defineProps<{
  channel: string
  label?: string
  minValue?: number
  maxValue?: number
  orientation?: 'horizontal' | 'vertical'
  showValue?: boolean
  showUnit?: boolean
  decimals?: number
  style?: WidgetStyle
  visualStyle?: BarGraphStyle
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

const store = useDashboardStore()

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const displayLabel = computed(() =>
  props.label || props.channel
)

const unit = computed(() => {
  if (props.showUnit === false) return ''
  return formatUnit(channelConfig.value?.unit)
})

const minVal = computed(() => {
  if (props.minValue !== undefined) return props.minValue
  return channelConfig.value?.low_limit ?? 0
})

const maxVal = computed(() => {
  if (props.maxValue !== undefined) return props.maxValue
  return channelConfig.value?.high_limit ?? 100
})

const currentValue = computed(() => {
  if (!channelValue.value || isStale.value) return null
  return channelValue.value.value
})

const displayValue = computed(() => {
  if (currentValue.value === null) return '--'
  const dec = props.decimals ?? 1
  return currentValue.value.toFixed(dec)
})

// Calculate percentage for bar fill
const percentage = computed(() => {
  if (currentValue.value === null) return 0
  const range = maxVal.value - minVal.value
  if (range <= 0) return 0
  const pct = ((currentValue.value - minVal.value) / range) * 100
  return Math.max(0, Math.min(100, pct))
})

const isVertical = computed(() => props.orientation === 'vertical')

// Visual style - tank/thermometer force vertical orientation
const visualStyle = computed(() => props.visualStyle || 'bar')
const effectiveVertical = computed(() => {
  if (visualStyle.value === 'tank' || visualStyle.value === 'thermometer') return true
  return isVertical.value
})

// Color based on status
const barColor = computed(() => {
  if (isStale.value) return '#666'
  if (channelValue.value?.alarm) return '#ef4444'
  if (channelValue.value?.warning) return '#fbbf24'
  return '#4ade80'
})

const statusClass = computed(() => {
  if (isStale.value) return 'stale'
  if (channelValue.value?.alarm) return 'alarm'
  if (channelValue.value?.warning) return 'warning'
  return 'normal'
})
</script>

<template>
  <div class="bar-graph-widget" :class="[statusClass, visualStyle, { vertical: effectiveVertical }]" :style="containerStyle">
    <div class="label">{{ displayLabel }}</div>

    <!-- Standard bar style -->
    <template v-if="visualStyle === 'bar'">
      <div class="bar-container" :class="{ vertical: isVertical }">
        <div class="bar-track">
          <div class="bar-fill-container">
            <div
              class="bar-fill"
              :style="{
                [isVertical ? 'height' : 'width']: `${percentage}%`,
                backgroundColor: barColor
              }"
            />
          </div>
          <!-- Inline label shown inside bar track for compact mode -->
          <div class="inline-label">{{ displayLabel }}</div>
        </div>

        <div v-if="showValue !== false" class="value-display">
          <span class="value">{{ displayValue }}</span>
          <span v-if="unit" class="unit">{{ unit }}</span>
        </div>
      </div>

      <div class="range-labels">
        <span>{{ minVal }}</span>
        <span>{{ maxVal }}</span>
      </div>
    </template>

    <!-- Tank style -->
    <template v-else-if="visualStyle === 'tank'">
      <div class="tank-container">
        <div class="tank-body">
          <div class="tank-graduations">
            <div v-for="n in 5" :key="n" class="graduation" :style="{ bottom: `${(n - 1) * 25}%` }">
              <span class="grad-label">{{ (minVal + (maxVal - minVal) * (n - 1) / 4).toFixed(0) }}</span>
            </div>
          </div>
          <div class="tank-liquid" :style="{ height: `${percentage}%`, backgroundColor: barColor }" />
          <div class="tank-shine" />
        </div>
        <div v-if="showValue !== false" class="tank-value">
          <span class="value">{{ displayValue }}</span>
          <span v-if="unit" class="unit">{{ unit }}</span>
        </div>
      </div>
    </template>

    <!-- Thermometer style -->
    <template v-else-if="visualStyle === 'thermometer'">
      <div class="thermo-container">
        <div class="thermo-tube">
          <div class="thermo-graduations">
            <div v-for="n in 5" :key="n" class="graduation" :style="{ bottom: `${(n - 1) * 25}%` }">
              <span class="grad-label">{{ (minVal + (maxVal - minVal) * (n - 1) / 4).toFixed(0) }}</span>
            </div>
          </div>
          <div class="thermo-mercury" :style="{ height: `${percentage}%`, backgroundColor: barColor }" />
          <div class="thermo-shine" />
        </div>
        <div class="thermo-bulb" :style="{ backgroundColor: barColor }">
          <div class="bulb-shine" />
        </div>
        <div v-if="showValue !== false" class="thermo-value">
          <span class="value">{{ displayValue }}</span>
          <span v-if="unit" class="unit">{{ unit }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.bar-graph-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 6px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  container-type: size;
}

.label {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  text-align: center;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Inline label inside bar - hidden by default, shown in compact mode */
.inline-label {
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.65rem;
  font-weight: 600;
  color: #fff;
  text-transform: uppercase;
  white-space: nowrap;
  z-index: 2;
  display: none;
  text-shadow: 0 1px 2px rgba(0,0,0,0.9);
  pointer-events: none;
}

/* Compact mode: when widget is short, use inline layout */
@container (max-height: 50px) {
  .bar-graph-widget {
    flex-direction: row;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
  }

  .label {
    display: none;
  }

  .inline-label {
    display: block;
  }

  .bar-container {
    flex: 1;
    flex-direction: row;
    gap: 6px;
    align-items: center;
  }

  .bar-track {
    flex: 1;
    min-height: 16px;
    max-height: 20px;
  }

  .range-labels {
    display: none;
  }

  .value-display {
    flex-shrink: 0;
  }

  .value {
    font-size: 0.8rem;
  }

  .unit {
    font-size: 0.55rem;
  }
}

.bar-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
}

.bar-container.vertical {
  flex-direction: row;
  align-items: stretch;
}

.bar-track {
  flex: 1;
  background: #0f0f1a;
  border-radius: 4px;
  overflow: visible;
  position: relative;
  min-height: 12px;
}

.bar-fill-container {
  position: absolute;
  inset: 0;
  overflow: hidden;
  border-radius: 4px;
}

.bar-container.vertical .bar-track {
  min-width: 16px;
  min-height: unset;
}

.bar-fill {
  position: absolute;
  transition: all 0.3s ease-out;
  border-radius: 4px;
  z-index: 1;
}

/* Horizontal fill - from left */
.bar-container:not(.vertical) .bar-fill {
  left: 0;
  top: 0;
  height: 100%;
}

/* Vertical fill - from bottom */
.bar-container.vertical .bar-fill {
  left: 0;
  bottom: 0;
  width: 100%;
}

.value-display {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 2px;
}

.bar-container.vertical .value-display {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
}

.value {
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.unit {
  font-size: 0.6rem;
  color: #888;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.5rem;
  color: #666;
  margin-top: 2px;
}

.bar-container.vertical + .range-labels {
  flex-direction: column-reverse;
  align-items: center;
  margin-top: 0;
  margin-left: 4px;
}

/* Status styling */
.warning {
  border-color: #fbbf24;
}

.alarm {
  border-color: #ef4444;
  animation: pulse-alarm 1s infinite;
}

.normal .value {
  color: #4ade80;
}

.warning .value {
  color: #fbbf24;
}

.alarm .value {
  color: #ef4444;
}

.stale .value {
  color: #666;
}

@keyframes pulse-alarm {
  0%, 100% { background-color: #1a1a2e; }
  50% { background-color: #3f1515; }
}

/* ========== TANK STYLE ========== */
.tank-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-height: 0;
  padding: 4px;
}

.tank-body {
  flex: 1;
  width: 40px;
  min-width: 30px;
  max-width: 60px;
  background: linear-gradient(90deg, #1a1a2e 0%, #252540 50%, #1a1a2e 100%);
  border-radius: 6px 6px 12px 12px;
  border: 2px solid #3a3a5a;
  position: relative;
  overflow: hidden;
}

.tank-liquid {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  transition: height 0.3s ease-out;
  background: linear-gradient(90deg,
    rgba(0,0,0,0.2) 0%,
    rgba(255,255,255,0.1) 30%,
    rgba(255,255,255,0.2) 50%,
    rgba(255,255,255,0.1) 70%,
    rgba(0,0,0,0.2) 100%
  );
}

.tank-shine {
  position: absolute;
  top: 0;
  left: 15%;
  width: 20%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
  pointer-events: none;
}

.tank-graduations {
  position: absolute;
  top: 0;
  right: -24px;
  bottom: 0;
  width: 20px;
  z-index: 2;
}

.tank-graduations .graduation {
  position: absolute;
  right: 0;
  display: flex;
  align-items: center;
  transform: translateY(50%);
}

.tank-graduations .graduation::before {
  content: '';
  width: 6px;
  height: 1px;
  background: #666;
  margin-right: 2px;
}

.tank-graduations .grad-label {
  font-size: 0.5rem;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}

.tank-value {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.tank-value .value {
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.tank-value .unit {
  font-size: 0.6rem;
  color: #888;
}

/* ========== THERMOMETER STYLE ========== */
.thermo-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  min-height: 0;
  padding: 4px;
  position: relative;
}

.thermo-tube {
  flex: 1;
  width: 16px;
  min-width: 12px;
  max-width: 20px;
  background: linear-gradient(90deg, #1a1a2e 0%, #252540 50%, #1a1a2e 100%);
  border-radius: 8px 8px 0 0;
  border: 2px solid #3a3a5a;
  border-bottom: none;
  position: relative;
  overflow: hidden;
  margin-bottom: -8px;
  z-index: 1;
}

.thermo-mercury {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  transition: height 0.3s ease-out;
  border-radius: 4px 4px 0 0;
}

.thermo-shine {
  position: absolute;
  top: 0;
  left: 20%;
  width: 30%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
  pointer-events: none;
}

.thermo-bulb {
  width: 28px;
  height: 28px;
  min-width: 24px;
  min-height: 24px;
  max-width: 32px;
  max-height: 32px;
  border-radius: 50%;
  border: 2px solid #3a3a5a;
  position: relative;
  z-index: 2;
  box-shadow: inset 0 -4px 8px rgba(0,0,0,0.3);
}

.bulb-shine {
  position: absolute;
  top: 15%;
  left: 20%;
  width: 30%;
  height: 30%;
  background: rgba(255,255,255,0.25);
  border-radius: 50%;
}

.thermo-graduations {
  position: absolute;
  top: 0;
  right: -24px;
  bottom: 0;
  width: 20px;
  z-index: 2;
}

.thermo-graduations .graduation {
  position: absolute;
  right: 0;
  display: flex;
  align-items: center;
  transform: translateY(50%);
}

.thermo-graduations .graduation::before {
  content: '';
  width: 4px;
  height: 1px;
  background: #666;
  margin-right: 2px;
}

.thermo-graduations .grad-label {
  font-size: 0.45rem;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}

.thermo-value {
  display: flex;
  align-items: baseline;
  gap: 2px;
  margin-top: 4px;
}

.thermo-value .value {
  font-size: 0.85rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.thermo-value .unit {
  font-size: 0.55rem;
  color: #888;
}

/* Status colors for tank/thermometer */
.tank .normal .value,
.thermometer .normal .value,
.bar-graph-widget.tank.normal .tank-value .value,
.bar-graph-widget.thermometer.normal .thermo-value .value {
  color: #4ade80;
}

.bar-graph-widget.tank.warning .tank-value .value,
.bar-graph-widget.thermometer.warning .thermo-value .value {
  color: #fbbf24;
}

.bar-graph-widget.tank.alarm .tank-value .value,
.bar-graph-widget.thermometer.alarm .thermo-value .value {
  color: #ef4444;
}

.bar-graph-widget.tank.stale .tank-value .value,
.bar-graph-widget.thermometer.stale .thermo-value .value {
  color: #666;
}
</style>
