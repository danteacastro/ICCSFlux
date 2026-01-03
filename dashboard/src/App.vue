<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
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
import NotebookTab from './components/NotebookTab.vue'
import PageSelector from './components/PageSelector.vue'
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

// URL-based page selection (for multi-window support)
function getPageFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('page')
}

function updateUrlWithPage(pageId: string) {
  const url = new URL(window.location.href)
  if (pageId && pageId !== 'default') {
    url.searchParams.set('page', pageId)
  } else {
    url.searchParams.delete('page')
  }
  window.history.replaceState({}, '', url.toString())
}

// Watch for page changes and update URL
watch(() => store.currentPageId, (newPageId) => {
  updateUrlWithPage(newPageId)
})

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
    newWidget.label = selectedChannel.value  // TAG is the only identifier
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
  // Connect to MQTT broker via WebSocket (port 9002 per mosquitto_ws.conf)
  mqtt.connect('ws://localhost:9002')

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

  // One-time migration: Clear corrupted showLabel/showUnit from localStorage
  // TODO: Remove this after January 2026
  const MIGRATION_KEY = 'nisystem-migration-v1-showlabel-fix'
  if (!localStorage.getItem(MIGRATION_KEY)) {
    console.log('[APP] Running one-time localStorage migration...')
    // Clear all nisystem layout data to force fresh load from project
    Object.keys(localStorage).forEach(key => {
      if (key.startsWith('nisystem-layout-')) {
        localStorage.removeItem(key)
        console.log('[APP] Cleared corrupted layout:', key)
      }
    })
    localStorage.setItem(MIGRATION_KEY, Date.now().toString())
  }

  // Track if project has been loaded from backend
  let projectLoadHandled = false

  // When a project is loaded from backend, apply it
  projectFiles.onProjectLoaded((data) => {
    console.log('[APP] Project loaded from backend:', data.name)
    projectLoadHandled = true
    scripts.loadAll()
    scripts.startEvaluation()

    // Log final state after a tick
    setTimeout(() => {
      console.log('[APP] Final state - pages:', store.pages.length, 'widgets on current page:', store.widgets.length)
      const urlPageId = getPageFromUrl()
      if (urlPageId && store.pages.some(p => p.id === urlPageId)) {
        store.switchPage(urlPageId)
      }
    }, 100)
  })

  // Watch for channel config and load project
  const checkChannels = setInterval(() => {
    if (Object.keys(mqtt.channelConfigs.value).length > 0) {
      store.setChannels(mqtt.channelConfigs.value)
      console.log('[APP] Channels loaded, requesting current project...')

      clearInterval(checkChannels)

      // Request current project from backend
      projectFiles.getCurrentProject()

      // Wait 2 seconds for backend response, then fall back to localStorage
      setTimeout(() => {
        if (!projectLoadHandled && !projectFiles.currentProjectData.value) {
          console.log('[APP] No project from backend after 2s, trying localStorage...')
          if (!store.loadLayoutFromStorage()) {
            console.log('[APP] No saved layout, generating default')
            store.generateDefaultLayout()
          }

          const urlPageId = getPageFromUrl()
          if (urlPageId && store.pages.some(p => p.id === urlPageId)) {
            store.switchPage(urlPageId)
          }
          console.log('[APP] Fallback complete - pages:', store.pages.length, 'widgets:', store.widgets.length)
        }
      }, 2000)
    }
  }, 100)

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
    mqtt.connect('ws://localhost:9002')
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

          <!-- Page Selector (only visible on Overview tab) -->
          <PageSelector v-if="activeTab === 'overview'" />
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
            :class="{ active: activeTab === 'notebook' }"
            @click="activeTab = 'notebook'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 016.5 17H20"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>
              <line x1="8" y1="7" x2="16" y2="7"/>
              <line x1="8" y1="11" x2="14" y2="11"/>
            </svg>
            Notebook
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
      </div>
    </header>

    <!-- Main content -->
    <main class="app-main">
      <DashboardGrid v-if="activeTab === 'overview'" />
      <ConfigurationTab v-else-if="activeTab === 'configuration'" />
      <ScriptsTab v-else-if="activeTab === 'scripts'" />
      <DataTab v-else-if="activeTab === 'data'" />
      <SafetyTab v-else-if="activeTab === 'safety'" />
      <NotebookTab v-else-if="activeTab === 'notebook'" />
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
                {{ name }} ({{ ch.unit }})
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
  min-height: 0;  /* Allow flex shrinking for nested scroll containers */
  flex: 1;
  overflow: hidden;  /* Let child components handle their own scrolling */
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
