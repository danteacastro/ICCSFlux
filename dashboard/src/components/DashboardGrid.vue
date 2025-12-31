<script setup lang="ts">
import { computed, ref } from 'vue'
import { GridLayout, GridItem } from 'grid-layout-plus'
import { useDashboardStore } from '../stores/dashboard'
import { getWidgetComponent } from '../widgets'
import WidgetConfigModal from './WidgetConfigModal.vue'
import type { WidgetConfig } from '../types'

const store = useDashboardStore()

// Widget config modal
const configWidgetId = ref<string | null>(null)

function openWidgetConfig(widgetId: string) {
  configWidgetId.value = widgetId
}

function closeWidgetConfig() {
  configWidgetId.value = null
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

  return props
}

function removeWidget(id: string) {
  store.removeWidget(id)
}

// Chart config modal
const selectedChart = ref<string | null>(null)

function openChartConfig(widgetId: string) {
  selectedChart.value = widgetId
}

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
</script>

<template>
  <div class="dashboard-grid">
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
        drag-allow-from=".drag-handle"
        drag-ignore-from=".no-drag"
      >
        <div class="widget-wrapper" :class="{ 'edit-mode': store.editMode }">
          <div v-if="store.editMode" class="widget-controls">
            <div class="drag-handle" title="Drag to move">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="5" r="2"/>
                <circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/>
                <circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/>
              </svg>
            </div>
            <button class="config-btn no-drag" @click="openWidgetConfig(item.i)" title="Configure widget">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
              </svg>
            </button>
            <button class="remove-btn no-drag" @click="removeWidget(item.i)" title="Remove widget">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <component
            :is="getWidgetComponent(getWidget(item.i)?.type || 'numeric')"
            v-bind="(getWidgetProps(item.i) as any)"
            @configure="openChartConfig(item.i)"
            class="widget-content no-drag"
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
}

.widget-controls {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 4px;
  z-index: 9999;
  pointer-events: auto;
}

.drag-handle {
  cursor: move;
  padding: 4px 6px;
  background: rgba(45, 55, 72, 0.95);
  border-radius: 4px;
  color: #a0aec0;
  display: flex;
  align-items: center;
  backdrop-filter: blur(4px);
  border: 1px solid rgba(74, 85, 104, 0.5);
}

.drag-handle:hover {
  background: rgba(74, 85, 104, 0.95);
  color: #fff;
}

.config-btn {
  background: rgba(30, 58, 95, 0.95);
  border: 1px solid rgba(59, 130, 246, 0.5);
  border-radius: 4px;
  color: #93c5fd;
  cursor: pointer;
  padding: 4px 6px;
  display: flex;
  align-items: center;
  backdrop-filter: blur(4px);
}

.config-btn:hover {
  background: rgba(59, 130, 246, 0.95);
  color: #fff;
}

.remove-btn {
  background: rgba(116, 42, 42, 0.95);
  border: 1px solid rgba(155, 44, 44, 0.5);
  border-radius: 4px;
  color: #feb2b2;
  cursor: pointer;
  padding: 4px 6px;
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
