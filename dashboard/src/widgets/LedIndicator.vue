<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetStyle } from '../types'
import { WIDGET_COLORS } from '../types'

const props = defineProps<{
  widgetId: string
  channel: string
  label?: string
  style?: WidgetStyle
  invert?: boolean
  compact?: boolean        // Compact mode: smaller, inline
  industrial?: boolean     // Industrial theme: flat, square
  showLabel?: boolean      // Show/hide label (default true)
  showStatus?: boolean     // Show/hide status text (default true in normal, false in compact)
  ledSize?: 'small' | 'medium' | 'large'
}>()

const store = useDashboardStore()
const showSettings = ref(false)

const channelConfig = computed(() => store.channels[props.channel])
const channelValue = computed(() => store.values[props.channel])

// Check if data is stale (no update in last 5 seconds) or system not acquiring
const isStale = computed(() => {
  if (!channelValue.value?.timestamp) return true
  if (!store.isAcquiring) return true
  return (Date.now() - channelValue.value.timestamp) > 5000
})

const isOn = computed(() => {
  if (!channelValue.value || isStale.value) return false
  const val = channelValue.value.value
  const shouldInvert = props.invert ?? channelConfig.value?.invert ?? false
  return shouldInvert ? val === 0 : val !== 0
})

const displayLabel = computed(() =>
  props.label || channelConfig.value?.display_name || props.channel
)

const onColor = computed(() => props.style?.onColor || '#22c55e')
const offColor = computed(() => props.style?.offColor || '#374151')

const ledColor = computed(() => isOn.value ? onColor.value : offColor.value)
const statusText = computed(() => {
  if (isStale.value) return '--'
  return isOn.value ? 'OK' : 'OFF'
})

function openSettings() {
  if (store.editMode) {
    showSettings.value = true
  }
}

function closeSettings() {
  showSettings.value = false
}

function updateStyle(updates: Partial<WidgetStyle>) {
  store.updateWidgetStyle(props.widgetId, updates)
}

// Mode classes
const modeClasses = computed(() => ({
  compact: props.compact,
  industrial: props.industrial,
  [`led-${props.ledSize || 'medium'}`]: true
}))

// Show/hide logic
const shouldShowLabel = computed(() => props.showLabel !== false)
const shouldShowStatus = computed(() => {
  if (props.showStatus !== undefined) return props.showStatus
  return !props.compact // Default: show status in normal mode, hide in compact
})
</script>

<template>
  <div class="led-indicator" :class="modeClasses">
    <div
      class="led"
      :style="{
        backgroundColor: ledColor,
        boxShadow: isOn && !industrial ? `0 0 8px ${ledColor}` : 'none'
      }"
    ></div>
    <div v-if="shouldShowLabel || shouldShowStatus" class="info">
      <div v-if="shouldShowLabel" class="label">{{ displayLabel }}</div>
      <div v-if="shouldShowStatus" class="status" :style="{ color: isOn ? onColor : '#6b7280' }">{{ statusText }}</div>
    </div>

    <!-- Settings button (edit mode only) -->
    <button
      v-if="store.editMode"
      class="settings-btn"
      @click.stop="openSettings"
      title="Style settings"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
      </svg>
    </button>
  </div>

  <!-- Settings Modal -->
  <Teleport to="body">
    <div v-if="showSettings" class="modal-overlay" @click.self="closeSettings">
      <div class="modal">
        <h3>LED Style</h3>

        <!-- On Color -->
        <div class="setting-group">
          <label>ON Color</label>
          <div class="color-swatches">
            <button
              v-for="color in WIDGET_COLORS.led.on"
              :key="color"
              class="color-swatch"
              :class="{ active: onColor === color }"
              :style="{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }"
              @click="updateStyle({ onColor: color })"
            ></button>
          </div>
        </div>

        <!-- Off Color -->
        <div class="setting-group">
          <label>OFF Color</label>
          <div class="color-swatches">
            <button
              v-for="color in WIDGET_COLORS.led.off"
              :key="color"
              class="color-swatch"
              :class="{ active: offColor === color }"
              :style="{ backgroundColor: color }"
              @click="updateStyle({ offColor: color })"
            ></button>
          </div>
        </div>

        <button class="close-btn" @click="closeSettings">Done</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.led-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 100%;
  padding: 4px 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
}

.led {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: all 0.2s;
}

.info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.label {
  font-size: 0.65rem;
  color: var(--label-color, #888);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status {
  font-size: 0.75rem;
  font-weight: 600;
}

.settings-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  background: #2d3748;
  border: none;
  border-radius: 2px;
  color: #888;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  opacity: 0;
  transition: opacity 0.2s;
}

.led-indicator:hover .settings-btn {
  opacity: 1;
}

.settings-btn:hover {
  background: #4a5568;
  color: #fff;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px;
  min-width: 280px;
}

.modal h3 {
  margin: 0 0 16px;
  color: #fff;
  font-size: 1rem;
}

.setting-group {
  margin-bottom: 16px;
}

.setting-group label {
  display: block;
  font-size: 0.75rem;
  color: #888;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.color-swatches {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.color-swatch {
  width: 32px;
  height: 32px;
  border: 2px solid #2a2a4a;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.color-swatch:hover {
  border-color: #4a5568;
  transform: scale(1.1);
}

.color-swatch.active {
  border-color: #fff;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.3);
}

.close-btn {
  width: 100%;
  padding: 8px;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  margin-top: 8px;
}

.close-btn:hover {
  background: #2563eb;
}

/* ========================================
   LED SIZES
   ======================================== */
.led-small .led {
  width: 10px;
  height: 10px;
}

.led-medium .led {
  width: 16px;
  height: 16px;
}

.led-large .led {
  width: 24px;
  height: 24px;
}

/* ========================================
   COMPACT MODE
   Smaller, tighter, inline
   ======================================== */
.compact {
  padding: 2px 6px;
  gap: 4px;
}

.compact .led {
  width: 10px;
  height: 10px;
}

.compact .label {
  font-size: 0.6rem;
}

.compact .status {
  font-size: 0.65rem;
}

.compact .info {
  flex-direction: row;
  align-items: center;
  gap: 4px;
}

/* ========================================
   INDUSTRIAL MODE
   Flat, square, LabVIEW-style
   ======================================== */
.industrial {
  border-radius: 0;
  border: 1px solid #444;
  background: #2a2a2a;
}

.industrial .led {
  border-radius: 2px;
  border: 1px solid #555;
}

.industrial .label {
  font-size: 0.6rem;
  color: #aaa;
  letter-spacing: 0.5px;
}

/* Compact + Industrial combo */
.compact.industrial {
  padding: 1px 4px;
}
</style>
