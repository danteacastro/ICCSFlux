<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetStyle } from '../types'
import { WIDGET_COLORS } from '../types'

// Prevent Vue from auto-inheriting attrs (we have multiple root nodes: div + Teleport)
defineOptions({
  inheritAttrs: false
})

const props = defineProps<{
  widgetId: string
  channel: string
  label?: string
  style?: WidgetStyle
  invert?: boolean
  industrial?: boolean     // Industrial theme: flat, square
  showLabel?: boolean      // Show/hide label (default true)
  showStatus?: boolean     // Show/hide status text
  ledSize?: 'small' | 'medium' | 'large'
  onColor?: string         // LED on color (can also be in style.onColor)
  offColor?: string        // LED off color (can also be in style.offColor)
  // Props passed by grid but not used - declare to prevent warnings
  showUnit?: boolean
  text?: string
  showValue?: boolean
  compact?: boolean        // Legacy prop - ignored, layout is now CSS-based
}>()

// Declare emits to prevent warnings
defineEmits<{
  (e: 'configure'): void
  (e: 'change', value: any): void
}>()

const store = useDashboardStore()
const showSettings = ref(false)

// Get widget config directly from store for reliable label access
// This fixes the bug where props weren't being passed reactively on initial load
const widgetConfig = computed(() =>
  props.widgetId ? store.widgets.find(w => w.id === props.widgetId) : null
)

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

// Display label - check props first, then widget config from store, then channel name
const displayLabel = computed(() =>
  (props.label || widgetConfig.value?.label || props.channel || widgetConfig.value?.channel || '').replace(/^py\./, '')
)

// Support both direct props and style object for colors
const onColor = computed(() => props.onColor || props.style?.onColor || '#22c55e')
const offColor = computed(() => props.offColor || props.style?.offColor || '#374151')

const ledColor = computed(() => isOn.value ? onColor.value : offColor.value)
const statusText = computed(() => {
  if (isStale.value) return '--'
  return isOn.value ? 'ON' : 'OFF'
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
  industrial: props.industrial,
  [`led-${props.ledSize || 'medium'}`]: true
}))

// Container style for background color
const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

// Show/hide logic - label always shows by default
const shouldShowLabel = computed(() => props.showLabel !== false)
const shouldShowStatus = computed(() => props.showStatus === true)
</script>

<template>
  <div class="led-indicator" :class="modeClasses" :style="containerStyle">
    <!-- Compact horizontal layout (shown when short) -->
    <div class="layout-horizontal">
      <div
        class="led"
        :style="{
          backgroundColor: ledColor,
          boxShadow: isOn && !industrial ? `0 0 8px ${ledColor}` : 'none'
        }"
      ></div>
      <div v-if="shouldShowLabel" class="label">{{ displayLabel }}</div>
    </div>

    <!-- Vertical layout (shown when tall enough) -->
    <div class="layout-vertical">
      <div v-if="shouldShowLabel" class="label">{{ displayLabel }}</div>
      <div
        class="led"
        :style="{
          backgroundColor: ledColor,
          boxShadow: isOn && !industrial ? `0 0 12px ${ledColor}` : 'none'
        }"
      ></div>
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
  justify-content: center;
  height: 100%;
  padding: 4px 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  position: relative;
  container-type: size;
}

/* ========================================
   LAYOUT SWITCHING VIA CONTAINER QUERIES
   ======================================== */

/* Default: show horizontal, hide vertical */
.layout-horizontal {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.layout-vertical {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 100%;
}

/* When widget is tall enough (2+ rows ~60px), switch to vertical layout */
@container (min-height: 60px) {
  .layout-horizontal {
    display: none;
  }
  .layout-vertical {
    display: flex;
  }
}

/* ========================================
   LED ELEMENT
   ======================================== */
.led {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: all 0.2s;
}

/* Larger LED in vertical mode */
@container (min-height: 60px) {
  .led {
    width: 24px;
    height: 24px;
  }
}

@container (min-height: 100px) {
  .led {
    width: 32px;
    height: 32px;
  }
}

/* ========================================
   LABEL
   ======================================== */
.label {
  font-size: 0.7rem;
  font-weight: 500;
  color: #ccc;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.5px;
}

/* Label styling in vertical mode */
@container (min-height: 60px) {
  .label {
    font-size: 0.65rem;
    color: #888;
    text-align: center;
    max-width: 100%;
  }
}

/* ========================================
   STATUS TEXT
   ======================================== */
.status {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

/* ========================================
   LED SIZES (can override defaults)
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
}

/* ========================================
   SETTINGS BUTTON
   ======================================== */
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
  z-index: 10;
}

.led-indicator:hover .settings-btn {
  opacity: 1;
}

.settings-btn:hover {
  background: #4a5568;
  color: #fff;
}

/* ========================================
   MODAL STYLES
   ======================================== */
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
</style>
