<script setup lang="ts">
import { computed, ref } from 'vue'
import { GridLayout, GridItem } from 'grid-layout-plus'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { getWidgetComponent } from '../widgets'
import WidgetConfigModal from './WidgetConfigModal.vue'
import type { WidgetConfig } from '../types'

const store = useDashboardStore()
const mqtt = useMqtt()

// Widget config modal
const configWidgetId = ref<string | null>(null)

// Track dragging state to hide controls
const isDragging = ref(false)
const draggingWidgetId = ref<string | null>(null)

// Multi-select state
const selectedWidgets = ref<Set<string>>(new Set())

function openWidgetConfig(widgetId: string) {
  configWidgetId.value = widgetId
}

function closeWidgetConfig() {
  configWidgetId.value = null
}

// Handle widget selection (for multi-select)
function handleWidgetClick(widgetId: string, event: MouseEvent) {
  if (!store.editMode) return

  if (event.shiftKey || event.ctrlKey || event.metaKey) {
    // Toggle selection
    if (selectedWidgets.value.has(widgetId)) {
      selectedWidgets.value.delete(widgetId)
    } else {
      selectedWidgets.value.add(widgetId)
    }
    // Force reactivity
    selectedWidgets.value = new Set(selectedWidgets.value)
  } else {
    // Single click without modifier - clear selection
    selectedWidgets.value.clear()
  }
}

// Clear selection when exiting edit mode
function clearSelection() {
  selectedWidgets.value.clear()
}

// Expose for external use
defineExpose({ clearSelection })

// Handle drag start - dispatch custom event for PageSelector
function onDragStart(widgetId: string) {
  isDragging.value = true
  draggingWidgetId.value = widgetId

  // Dispatch custom event for PageSelector to listen
  window.dispatchEvent(new CustomEvent('widget-drag-start', {
    detail: { widgetId }
  }))
}

// Handle drag end - dispatch custom event for PageSelector
function onDragEnd() {
  const widgetId = draggingWidgetId.value
  isDragging.value = false
  draggingWidgetId.value = null

  // Dispatch custom event for PageSelector to listen
  window.dispatchEvent(new CustomEvent('widget-drag-end', {
    detail: { widgetId }
  }))
}

// Convert widgets to grid-layout format
const layoutItems = computed(() =>
  store.widgets.map(w => ({
    i: w.id,
    x: w.x,
    y: w.y,
    w: w.w,
    h: w.h,
    minW: w.minW || 1,
    minH: w.minH || 1,
  }))
)

function onLayoutUpdated(newLayout: { i: string; x: number; y: number; w: number; h: number }[]) {
  newLayout.forEach(item => {
    store.updateWidgetPosition(item.i, item.x, item.y, item.w, item.h)
  })
}

function getWidget(id: string): WidgetConfig | undefined {
  return store.widgets.find(w => w.id === id)
}

function getWidgetProps(widgetId: string): Record<string, unknown> {
  const widget = getWidget(widgetId)
  if (!widget) return {}

  const props: Record<string, unknown> = {}

  if (widget.channel) props.channel = widget.channel
  if (widget.channels) props.channels = widget.channels
  if (widget.label) props.label = widget.label
  if (widget.decimals !== undefined) props.decimals = widget.decimals
  if (widget.showUnit !== undefined) props.showUnit = widget.showUnit
  if (widget.showAlarmStatus !== undefined) props.showAlarmStatus = widget.showAlarmStatus
  if (widget.timeRange !== undefined) props.timeRange = widget.timeRange
  if (widget.style) props.style = widget.style
  props.widgetId = widgetId
  props.text = widget.label

  // Chart-specific props
  if (widget.yAxisAuto !== undefined) props.yAxisAuto = widget.yAxisAuto
  if (widget.yAxisMin !== undefined) props.yAxisMin = widget.yAxisMin
  if (widget.yAxisMax !== undefined) props.yAxisMax = widget.yAxisMax
  if (widget.showGrid !== undefined) props.showGrid = widget.showGrid
  if (widget.showLegend !== undefined) props.showLegend = widget.showLegend
  // LabVIEW-style chart props
  if (widget.historySize !== undefined) props.historySize = widget.historySize
  if (widget.updateMode !== undefined) props.updateMode = widget.updateMode
  if (widget.yAxes !== undefined) props.yAxes = widget.yAxes
  if (widget.showScrollbar !== undefined) props.showScrollbar = widget.showScrollbar
  if (widget.showDigitalDisplay !== undefined) props.showDigitalDisplay = widget.showDigitalDisplay
  if (widget.stackPlots !== undefined) props.stackPlots = widget.stackPlots
  if (widget.plotStyles !== undefined) props.plotStyles = widget.plotStyles
  if (widget.cursors !== undefined) props.cursors = widget.cursors

  // SVG Symbol props
  if (widget.symbol !== undefined) props.symbol = widget.symbol
  if (widget.symbolSize !== undefined) props.size = widget.symbolSize
  if (widget.valuePosition !== undefined) props.valuePosition = widget.valuePosition
  if (widget.showLabel !== undefined) props.showLabel = widget.showLabel
  if (widget.showValue !== undefined) props.showValue = widget.showValue
  if (widget.accentColor !== undefined) props.accentColor = widget.accentColor
  if (widget.rotation !== undefined) props.rotation = widget.rotation

  // Text Label props
  if (widget.text !== undefined) props.text = widget.text
  if (widget.fontSize !== undefined) props.fontSize = widget.fontSize
  if (widget.textAlign !== undefined) props.textAlign = widget.textAlign
  if (widget.textColor !== undefined) props.textColor = widget.textColor

  // Compact/Industrial mode (for numeric, led, value_table)
  if (widget.compact !== undefined) props.compact = widget.compact
  if (widget.industrial !== undefined) props.industrial = widget.industrial
  if (widget.showUnits !== undefined) props.showUnits = widget.showUnits
  if (widget.showStatus !== undefined) props.showStatus = widget.showStatus
  if (widget.maxRows !== undefined) props.maxRows = widget.maxRows

  return props
}

function removeWidget(id: string) {
  store.removeWidget(id)
}

// Chart config modal
const selectedChart = ref<string | null>(null)

function closeChartConfig() {
  selectedChart.value = null
}

function toggleChartChannel(chartId: string, channel: string, add: boolean) {
  if (add) {
    store.addChannelToChart(chartId, channel)
  } else {
    store.removeChannelFromChart(chartId, channel)
  }
}

// Handle toggle switch change events for digital outputs
function handleToggleChange(widgetId: string, value: boolean) {
  const widget = store.widgets.find(w => w.id === widgetId)
  if (!widget?.channel) return
  mqtt.setOutput(widget.channel, value)
}
</script>

<template>
  <div class="dashboard-grid" :class="{ 'is-dragging': isDragging }">
    <GridLayout
      v-model:layout="layoutItems"
      :col-num="store.gridColumns"
      :row-height="store.rowHeight"
      :is-draggable="store.editMode"
      :is-resizable="store.editMode"
      :vertical-compact="false"
      :use-css-transforms="true"
      :margin="[8, 8]"
      @layout-updated="onLayoutUpdated"
    >
      <GridItem
        v-for="item in layoutItems"
        :key="item.i"
        :x="item.x"
        :y="item.y"
        :w="item.w"
        :h="item.h"
        :i="item.i"
        :min-w="item.minW"
        :min-h="item.minH"
        drag-ignore-from=".no-drag"
        @movestart="onDragStart(item.i)"
        @moveend="onDragEnd"
        @resizestart="onDragStart(item.i)"
        @resizeend="onDragEnd"
      >
        <div
          class="widget-wrapper"
          :class="{
            'edit-mode': store.editMode,
            'selected': selectedWidgets.has(item.i)
          }"
          @click="handleWidgetClick(item.i, $event)"
        >
          <!-- Minimal controls - only show when in edit mode and not dragging -->
          <div v-if="store.editMode && !isDragging" class="widget-controls">
            <button class="config-btn no-drag" @click.stop="openWidgetConfig(item.i)" title="Configure">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
              </svg>
            </button>
            <button class="remove-btn no-drag" @click.stop="removeWidget(item.i)" title="Remove">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <component
            :is="getWidgetComponent(getWidget(item.i)?.type || 'numeric')"
            v-bind="(getWidgetProps(item.i) as any)"
            @configure="openWidgetConfig(item.i)"
            @change="handleToggleChange(item.i, $event)"
            class="widget-content"
          />
        </div>
      </GridItem>
    </GridLayout>

    <!-- Widget config modal -->
    <WidgetConfigModal
      :widget-id="configWidgetId"
      @close="closeWidgetConfig"
    />

    <!-- Chart config modal (legacy, kept for chart @configure event) -->
    <Teleport to="body">
      <div v-if="selectedChart" class="modal-overlay" @click.self="closeChartConfig">
        <div class="modal">
          <h3>Configure Chart</h3>
          <div class="channel-list">
            <label v-for="(config, name) in store.channels" :key="name" class="channel-option">
              <input
                type="checkbox"
                :checked="getWidget(selectedChart!)?.channels?.includes(name as string)"
                @change="toggleChartChannel(selectedChart!, name as string, ($event.target as HTMLInputElement).checked)"
              />
              <span>{{ config.display_name || name }}</span>
              <span class="unit">{{ config.unit }}</span>
            </label>
          </div>
          <button @click="closeChartConfig" class="close-btn">Close</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dashboard-grid {
  height: 100%;
  padding: 8px;
  position: relative;
}

.widget-wrapper {
  height: 100%;
  position: relative;
}

.widget-wrapper.edit-mode {
  outline: 1px dashed #4a5568;
  outline-offset: -1px;
  cursor: move;
  user-select: none;
  -webkit-user-select: none;
}

.widget-wrapper.edit-mode:hover {
  outline-color: #60a5fa;
}

.widget-wrapper.selected {
  outline: 2px solid #3b82f6 !important;
  outline-offset: -1px;
}

/* Hide controls while dragging for cleaner UX */
.is-dragging .widget-controls {
  display: none !important;
}

.widget-controls {
  position: absolute;
  top: 2px;
  right: 2px;
  display: flex;
  gap: 2px;
  z-index: 9999;
  pointer-events: auto;
  opacity: 0;
  transition: opacity 0.15s;
}

.widget-wrapper:hover .widget-controls {
  opacity: 1;
}

.config-btn {
  background: rgba(30, 58, 95, 0.9);
  border: 1px solid rgba(59, 130, 246, 0.5);
  border-radius: 3px;
  color: #93c5fd;
  cursor: pointer;
  padding: 3px 5px;
  display: flex;
  align-items: center;
  backdrop-filter: blur(4px);
}

.config-btn:hover {
  background: rgba(59, 130, 246, 0.95);
  color: #fff;
}

.remove-btn {
  background: rgba(116, 42, 42, 0.9);
  border: 1px solid rgba(155, 44, 44, 0.5);
  border-radius: 3px;
  color: #feb2b2;
  cursor: pointer;
  padding: 3px 5px;
  display: flex;
  align-items: center;
  backdrop-filter: blur(4px);
}

.remove-btn:hover {
  background: rgba(155, 44, 44, 0.95);
  color: #fff;
}

.widget-content {
  height: 100%;
}

/* Make interactive elements inside widgets still clickable in edit mode */
.widget-content :deep(button),
.widget-content :deep(input),
.widget-content :deep(select),
.widget-content :deep(.interactive) {
  pointer-events: auto;
}

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
  min-width: 300px;
  max-width: 400px;
  max-height: 80vh;
  overflow-y: auto;
}

.modal h3 {
  margin: 0 0 12px;
  color: #fff;
  font-size: 1rem;
}

.channel-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.channel-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  color: #ccc;
  font-size: 0.85rem;
}

.channel-option:hover {
  background: #2a2a4a;
}

.channel-option .unit {
  margin-left: auto;
  color: #666;
  font-size: 0.75rem;
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
}

.close-btn:hover {
  background: #2563eb;
}
</style>
