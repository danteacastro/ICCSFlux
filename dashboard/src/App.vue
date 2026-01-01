<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useDashboardStore } from './stores/dashboard'
import { useMqtt } from './composables/useMqtt'
import { useScripts } from './composables/useScripts'
import { useProjectFiles } from './composables/useProjectFiles'
import DashboardGrid from './components/DashboardGrid.vue'
import ControlBar from './components/ControlBar.vue'
import ConfigurationTab from './components/ConfigurationTab.vue'
import ScriptsTab from './components/ScriptsTab.vue'
import DataTab from './components/DataTab.vue'
import SafetyTab from './components/SafetyTab.vue'
import PlaygroundTab from './components/PlaygroundTab.vue'
import NotificationToast from './components/NotificationToast.vue'
import StatusMessages from './widgets/StatusMessages.vue'
import ConnectionOverlay from './components/ConnectionOverlay.vue'
import { availableWidgets, type WidgetTypeInfo } from './widgets'
import type { WidgetConfig } from './types'

const store = useDashboardStore()
const scripts = useScripts()
const projectFiles = useProjectFiles()

// Tabs
const activeTab = ref('overview')

// Add Widget modal state
const showAddPanel = ref(false)
const selectedWidgetType = ref<WidgetTypeInfo | null>(null)
const selectedChannel = ref<string>('')

function openAddPanel() {
  showAddPanel.value = true
  selectedWidgetType.value = null
  selectedChannel.value = ''
}

function closeAddPanel() {
  showAddPanel.value = false
  selectedWidgetType.value = null
  selectedChannel.value = ''
}

function selectWidgetType(wt: WidgetTypeInfo) {
  selectedWidgetType.value = wt
  selectedChannel.value = ''
}

function addWidget() {
  if (!selectedWidgetType.value) return

  const wt = selectedWidgetType.value
  const maxY = store.widgets.reduce((max, w) => Math.max(max, w.y + w.h), 0)

  const newWidget: Omit<WidgetConfig, 'id'> = {
    type: wt.type as any,
    x: 0,
    y: maxY,
    w: wt.defaultSize.w,
    h: wt.defaultSize.h,
  }

  if (wt.needsChannel && selectedChannel.value) {
    newWidget.channel = selectedChannel.value
    const chConfig = store.channels[selectedChannel.value]
    newWidget.label = chConfig?.display_name || selectedChannel.value
  }

  if (wt.type === 'title') {
    newWidget.label = 'New Title'
  }

  if (wt.type === 'chart') {
    newWidget.channels = []
    newWidget.timeRange = 300
  }

  store.addWidget(newWidget)
  closeAddPanel()
}

const filteredChannels = computed(() => {
  if (!selectedWidgetType.value) return []
  const wt = selectedWidgetType.value.type

  // Only show visible channels
  return Object.entries(store.channels).filter(([_, ch]) => {
    // Skip hidden channels
    if (ch.visible === false) return false
    // Toggle only works with digital outputs
    if (wt === 'toggle') return ch.channel_type === 'digital_output'
    // LED works with digital inputs, but also allow any channel (for threshold-based indicators)
    if (wt === 'led') return true
    // Numeric and gauge work with any channel
    if (wt === 'numeric' || wt === 'gauge') return true
    return true
  })
})
const mqtt = useMqtt('nisystem')

onMounted(() => {
  // Connect to MQTT broker via WebSocket
  mqtt.connect('ws://localhost:9001')

  // Wire up scripts MQTT handlers for hardware control
  scripts.setMqttHandlers({
    setOutput: mqtt.setOutput,
    startRecording: mqtt.startRecording,
    stopRecording: mqtt.stopRecording,
    sendScriptValues: mqtt.sendScriptValues
  })

  // Initialize scripts system
  scripts.loadAll()
  scripts.startEvaluation()

  // Set up data handlers
  mqtt.onData((data) => {
    store.updateValues(data)
  })

  mqtt.onStatus((status) => {
    store.setStatus(status)
  })

  // Watch for channel config and load project
  const checkChannels = setInterval(() => {
    if (Object.keys(mqtt.channelConfigs.value).length > 0) {
      store.setChannels(mqtt.channelConfigs.value)

      // Request current project from backend
      // If backend has a loaded project, it will send project/current with the data
      // The useProjectFiles composable will apply it automatically
      projectFiles.getCurrentProject()

      // Give time for project data to arrive, then fall back to layout from storage
      setTimeout(() => {
        if (!projectFiles.currentProjectData.value) {
          // No project loaded from backend, use local storage
          if (!store.loadLayoutFromStorage()) {
            store.generateDefaultLayout()
          }
        }
      }, 500)

      clearInterval(checkChannels)
    }
  }, 100)

  // When a project is loaded, reload scripts
  projectFiles.onProjectLoaded((data) => {
    console.log('Project loaded:', data.name)
    scripts.loadAll()  // Reload scripts from localStorage (where project data was applied)
    scripts.startEvaluation()
  })

  // Handle channel deletion - clean up widgets
  mqtt.onChannelDeleted((channelName: string) => {
    const removed = store.handleChannelDeleted(channelName)
    if (removed > 0) {
      console.log(`Cleaned up ${removed} widgets for deleted channel: ${channelName}`)
    }
  })

  // Handle channel creation - refresh store
  mqtt.onChannelCreated((channels: string[]) => {
    console.log(`Created channels: ${channels.join(', ')}`)
    // Channel config will be refreshed via the config/channels topic
  })

  // Cleanup interval on unmount
  onUnmounted(() => {
    clearInterval(checkChannels)
  })
})

// Control handlers
function handleStart() {
  mqtt.startAcquisition()
}

function handleStop() {
  mqtt.stopAcquisition()
  // Clear all values to reset widgets to boot state (showing "--")
  store.clearValues()
}

function handleRecordStart() {
  mqtt.startRecording()
}

function handleRecordStop() {
  mqtt.stopRecording()
}

function handleScheduleEnable() {
  mqtt.enableScheduler()
}

function handleScheduleDisable() {
  mqtt.disableScheduler()
}

function handleRetryConnection() {
  mqtt.disconnect()
  setTimeout(() => {
    mqtt.connect('ws://localhost:9001')
  }, 100)
}

</script>

<template>
  <div class="app">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
          <span class="title">DCFlux</span>
        </div>

        <!-- Navigation Tabs -->
        <nav class="header-tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'overview' }"
            @click="activeTab = 'overview'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
              <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
            </svg>
            Overview
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'configuration' }"
            @click="activeTab = 'configuration'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
            </svg>
            Configuration
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'scripts' }"
            @click="activeTab = 'scripts'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
              <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            Scripts
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'data' }"
            @click="activeTab = 'data'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
              <line x1="6" y1="20" x2="6" y2="14"/>
            </svg>
            Data
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'safety' }"
            @click="activeTab = 'safety'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              <path d="M12 8v4M12 16h.01"/>
            </svg>
            Safety
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'playground' }"
            @click="activeTab = 'playground'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 3v18h18"/>
              <path d="M7 12l4-4 4 4 4-4"/>
              <circle cx="7" cy="12" r="1.5"/>
              <circle cx="11" cy="8" r="1.5"/>
              <circle cx="15" cy="12" r="1.5"/>
              <circle cx="19" cy="8" r="1.5"/>
            </svg>
            Playground
          </button>
        </nav>
      </div>

      <div class="header-right">
        <!-- Control Bar integrated into header -->
        <ControlBar
          :show-edit-controls="activeTab === 'overview'"
          @start="handleStart"
          @stop="handleStop"
          @record-start="handleRecordStart"
          @record-stop="handleRecordStop"
          @schedule-enable="handleScheduleEnable"
          @schedule-disable="handleScheduleDisable"
          @add-widget="openAddPanel"
        />
        <span class="system-name">{{ store.systemName }}</span>
        <span class="connection-status" :class="{ connected: mqtt.connected.value }">
          {{ mqtt.connected.value ? 'Connected' : 'Disconnected' }}
        </span>
      </div>
    </header>

    <!-- Main content -->
    <main class="app-main">
      <DashboardGrid v-if="activeTab === 'overview'" />
      <ConfigurationTab v-else-if="activeTab === 'configuration'" />
      <ScriptsTab v-else-if="activeTab === 'scripts'" />
      <DataTab v-else-if="activeTab === 'data'" />
      <SafetyTab v-else-if="activeTab === 'safety'" />
      <PlaygroundTab v-else-if="activeTab === 'playground'" />
    </main>

    <!-- Notifications Toast -->
    <NotificationToast />

    <!-- Status Messages (only on overview) -->
    <StatusMessages v-if="activeTab === 'overview'" :maxMessages="50" />

    <!-- Connection Overlay -->
    <ConnectionOverlay
      :connected="mqtt.connected.value"
      :reconnect-attempts="mqtt.reconnectAttempts.value"
      :data-is-stale="mqtt.dataIsStale.value"
      :last-heartbeat-time="mqtt.lastHeartbeatTime.value"
      @retry-now="handleRetryConnection"
    />

    <!-- Add Widget Modal -->
    <Teleport to="body">
      <div v-if="showAddPanel" class="modal-overlay" @click.self="closeAddPanel">
        <div class="modal add-widget-modal">
          <h3>Add Widget</h3>
          <div class="widget-types">
            <button
              v-for="wt in availableWidgets"
              :key="wt.type"
              class="widget-type-btn"
              :class="{ selected: selectedWidgetType?.type === wt.type }"
              @click="selectWidgetType(wt)"
            >
              <span class="widget-icon">{{ wt.icon }}</span>
              <span class="widget-name">{{ wt.name }}</span>
            </button>
          </div>

          <div v-if="selectedWidgetType?.needsChannel" class="channel-select">
            <label>Select Channel:</label>
            <select v-model="selectedChannel">
              <option value="">-- Select --</option>
              <option v-for="[name, ch] in filteredChannels" :key="name" :value="name">
                {{ ch.display_name || name }} ({{ ch.unit }})
              </option>
            </select>
          </div>

          <p v-if="selectedWidgetType" class="widget-desc">{{ selectedWidgetType.description }}</p>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="closeAddPanel">Cancel</button>
            <button
              class="btn btn-primary"
              @click="addWidget"
              :disabled="!selectedWidgetType || (selectedWidgetType.needsChannel && !selectedChannel)"
            >Add</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0a0a14;
  color: #fff;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 16px;
  height: 56px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #60a5fa;
}

.title {
  font-size: 1.1rem;
  font-weight: 700;
}

.header-tabs {
  display: flex;
  gap: 4px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: transparent;
  color: #888;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: #1a1a2e;
  color: #ccc;
}

.tab-btn.active {
  background: #1e3a5f;
  color: #60a5fa;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  justify-content: flex-end;
}

.system-name {
  font-size: 0.85rem;
  color: #666;
  font-weight: 500;
}

.connection-status {
  font-size: 0.75rem;
  padding: 4px 8px;
  border-radius: 4px;
  background: #7f1d1d;
  color: #fca5a5;
}

.connection-status.connected {
  background: #14532d;
  color: #86efac;
}

.app-main {
  flex: 1;
  overflow: auto;
}

.tab-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #666;
}

.tab-placeholder h2 {
  margin: 0 0 8px;
  color: #888;
}

.tab-placeholder p {
  margin: 0;
  font-size: 0.9rem;
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

.add-widget-modal {
  min-width: 400px;
}

.widget-types {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.widget-type-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  cursor: pointer;
  transition: all 0.2s;
}

.widget-type-btn:hover {
  background: #1a1a2e;
  color: #fff;
  border-color: #3a3a5a;
}

.widget-type-btn.selected {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #fff;
}

.widget-icon {
  font-size: 1.5rem;
}

.widget-name {
  font-size: 0.7rem;
  text-align: center;
}

.channel-select {
  margin-bottom: 12px;
}

.channel-select label {
  display: block;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 4px;
}

.channel-select select {
  width: 100%;
  padding: 8px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
}

.channel-select select:focus {
  outline: none;
  border-color: #3b82f6;
}

.widget-desc {
  font-size: 0.8rem;
  color: #666;
  margin: 0 0 16px;
}

.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover:not(:disabled) {
  background: #4b5563;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}
</style>
