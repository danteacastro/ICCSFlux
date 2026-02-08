<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, provide, markRaw, type Component } from 'vue'
import { useDashboardStore } from './stores/dashboard'
import { useMqtt } from './composables/useMqtt'
import { useScripts } from './composables/useScripts'
import { useProjectFiles } from './composables/useProjectFiles'
import { useAuth } from './composables/useAuth'
import { usePlayground } from './composables/usePlayground'
import { useWindowSync } from './composables/useWindowSync'
import DashboardGrid from './components/DashboardGrid.vue'
import ControlBar from './components/ControlBar.vue'
import PidToolbar from './components/PidToolbar.vue'
import ConfigurationTab from './components/ConfigurationTab.vue'
import ScriptsTab from './components/ScriptsTab.vue'
import DataTab from './components/DataTab.vue'
import SafetyTab from './components/SafetyTab.vue'
import NotebookTab from './components/NotebookTab.vue'
import AdminTab from './components/AdminTab.vue'
import PageSelector from './components/PageSelector.vue'
import NotificationToast from './components/NotificationToast.vue'
import StatusMessages from './widgets/StatusMessages.vue'
import ConnectionOverlay from './components/ConnectionOverlay.vue'
import LoginDialog from './components/LoginDialog.vue'
import { availableWidgets, type WidgetTypeInfo } from './widgets'
import type { WidgetConfig, WidgetType } from './types'

const store = useDashboardStore()
const scripts = useScripts()
const projectFiles = useProjectFiles()
const auth = useAuth()
const playground = usePlayground()
const windowSync = useWindowSync()

// Track if project has been loaded from backend (module-level for access in loadLastProject)
let projectLoadHandled = false

// Track window position for the current page (multi-monitor support)
let windowPositionCleanup: (() => void) | null = null

// Login dialog state
const showLoginDialog = ref(false)

// Tabs
const activeTab = ref('overview')

// Map activeTab to component for keep-alive (prevents destroy/recreate on tab switch)
const tabComponents: Record<string, Component> = {
  overview: markRaw(DashboardGrid),
  configuration: markRaw(ConfigurationTab),
  scripts: markRaw(ScriptsTab),
  data: markRaw(DataTab),
  safety: markRaw(SafetyTab),
  notebook: markRaw(NotebookTab),
  admin: markRaw(AdminTab),
}
const activeTabComponent = computed(() => tabComponents[activeTab.value] || DashboardGrid)

// Permission-based EDIT control (viewing is allowed for everyone)
// These are provided to child components via provide/inject
// Using role-based checks that align with backend permission model:
// - Operator+: Can modify channel configs
// - Supervisor+: Can modify scripts, safety, recording settings
// - Admin: Can manage users
// Note: Use isOperator/isSupervisor directly (computed refs) for proper reactivity
const canEditConfig = computed(() => auth.isOperator.value)
const canEditScripts = computed(() => auth.isSupervisor.value)
const canEditData = computed(() => auth.isOperator.value)
const canEditSafety = computed(() => auth.isSupervisor.value)
const canEditAdmin = computed(() => auth.isSupervisor.value)

// Provide edit permissions to child components
provide('canEditConfig', canEditConfig)
provide('canEditScripts', canEditScripts)
provide('canEditData', canEditData)
provide('canEditSafety', canEditSafety)
provide('canEditAdmin', canEditAdmin)
provide('showLoginDialog', () => { showLoginDialog.value = true })

// URL-based navigation state (for multi-window support)
// Encodes both view (overview/config/data/safety) and page within overview
function getViewFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('view')
}

function getPageFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('page')
}

function updateUrlNavigation(view: string, pageId: string) {
  const url = new URL(window.location.href)
  // Always persist view so each tab remembers its own panel
  if (view && view !== 'overview') {
    url.searchParams.set('view', view)
  } else {
    url.searchParams.delete('view')
  }
  if (pageId && pageId !== 'default') {
    url.searchParams.set('page', pageId)
  } else {
    url.searchParams.delete('page')
  }
  window.history.replaceState({}, '', url.toString())
}

// Restore activeTab from URL on startup (before any watches fire)
const urlView = getViewFromUrl()
if (urlView && ['overview', 'configuration', 'scripts', 'data', 'safety', 'notebook', 'admin'].includes(urlView)) {
  activeTab.value = urlView
}

// Watch for view (activeTab) changes and update URL
watch(activeTab, (newView) => {
  updateUrlNavigation(newView, store.currentPageId)
})

// Watch for page changes and update URL + track window position
watch(() => store.currentPageId, (newPageId) => {
  updateUrlNavigation(activeTab.value, newPageId)

  // Start tracking window position for this page (multi-monitor memory)
  if (windowPositionCleanup) {
    windowPositionCleanup()
  }
  windowPositionCleanup = windowSync.trackWindowPosition(newPageId)
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
    type: wt.type as WidgetType,
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

// Startup dialog state
const showStartupDialog = ref(false)
const hasLastProject = ref(false)
const projectLoading = ref(false)  // True while loading project from backend
provide('projectLoading', projectLoading)
// Last project info for display in dialog
const lastProjectName = computed(() => projectFiles.currentProjectData.value?.name || 'Unknown Project')
const lastProjectModified = computed(() => {
  const modified = projectFiles.currentProjectData.value?.modified
  if (!modified) return ''
  try {
    const date = new Date(modified)
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return modified
  }
})

// Autosave recovery info
const hasAutosaveRecovery = computed(() => projectFiles.backendAutosaveStatus.value?.exists === true)
const autosaveTimestamp = computed(() => {
  const ts = projectFiles.backendAutosaveStatus.value?.timestamp
  if (!ts) return ''
  try {
    const date = new Date(ts)
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
})
const autosaveProjectName = computed(() => projectFiles.backendAutosaveStatus.value?.projectName || 'Unsaved Work')

async function loadLastProject() {
  showStartupDialog.value = false
  projectLoading.value = true
  console.log('[APP] User chose to load last project')

  // Send command to backend to load the last used project from settings
  mqtt.sendNodeCommand('project/load-last')

  // Wait for backend response with timeout
  // projectFiles.onProjectLoaded will set projectLoadHandled = true and clear loading
  const startTime = Date.now()
  const maxWaitMs = 5000  // 5 second timeout

  const checkLoaded = setInterval(() => {
    const elapsed = Date.now() - startTime

    if (projectLoadHandled || projectFiles.currentProjectData.value) {
      // Project loaded successfully
      clearInterval(checkLoaded)
      projectLoading.value = false
      console.log('[APP] ✅ Project loaded from backend')
      return
    }

    if (elapsed >= maxWaitMs) {
      // Timeout - fall back to localStorage
      clearInterval(checkLoaded)
      projectLoading.value = false
      console.log('[APP] Backend timeout, trying localStorage...')
      if (store.loadLayoutFromStorage()) {
        console.log('[APP] ✅ Loaded layout from localStorage')
      } else {
        console.log('[APP] No saved layout found')
      }
    }
  }, 100)
}

async function startFresh() {
  showStartupDialog.value = false
  console.log('[APP] User chose to start fresh - clearing all state')
  // Clear everything: frontend state, backend channels, localStorage, layout
  await projectFiles.newProject()
  console.log('[APP] ✅ Clean slate ready - user can now configure from Config tab')
}

function continueWithFreshSystem() {
  showStartupDialog.value = false
  console.log('[APP] User acknowledged fresh system state')
}

async function recoverFromAutosave() {
  showStartupDialog.value = false
  projectLoading.value = true
  console.log('[APP] User chose to recover from autosave')

  try {
    const success = await projectFiles.loadFromAutosave()
    if (success) {
      console.log('[APP] ✅ Successfully recovered from autosave')
    } else {
      console.log('[APP] ❌ Failed to recover from autosave')
    }
  } catch (err) {
    console.error('[APP] Error recovering from autosave:', err)
  } finally {
    projectLoading.value = false
  }
}

function discardAutosaveAndLoadProject() {
  projectFiles.discardBackendAutosave()
  console.log('[APP] User discarded autosave, loading saved project')
  loadLastProject()
}

function discardAutosaveAndStartFresh() {
  projectFiles.discardBackendAutosave()
  console.log('[APP] User discarded autosave, starting fresh')
  startFresh()
}

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

  // When a project is loaded from backend, apply it
  projectFiles.onProjectLoaded((data) => {
    console.log('[APP] Project loaded from backend:', data.name)
    projectLoadHandled = true
    projectLoading.value = false  // Clear loading state
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

  // Wait for MQTT connection and backend initialization
  // Backend now starts with NO channels/project - user chooses what to load
  const checkMqttReady = setInterval(() => {
    // Check if MQTT is connected and backend has published initial state
    if (mqtt.connected.value) {
      console.log('[APP] MQTT connected, initializing frontend...')

      // Set any channels that exist (may be empty if backend just started)
      if (Object.keys(mqtt.channelConfigs.value).length > 0) {
        store.setChannels(mqtt.channelConfigs.value)
        console.log('[APP] Channels loaded from backend:', Object.keys(mqtt.channelConfigs.value).length)
      } else {
        console.log('[APP] No channels from backend (clean slate)')
      }

      clearInterval(checkMqttReady)

      // Ensure we have at least one empty page for the Overview tab
      store.ensureDefaultPage()

      // Request current project from backend to sync state
      console.log('[APP] ✅ Boot complete - syncing with backend state...')
      projectFiles.getCurrentProject()

      // Check for autosave recovery (in case browser opened after service restart)
      // The startup-cleared event only fires when browser is connected during service start
      // This handles the case where service restarted with autosave, but browser wasn't open
      projectFiles.checkBackendAutosave()

      // Wait for responses, then check if we need to show recovery dialog
      // Only show if: autosave exists AND backend has no project loaded (fresh state)
      // If backend has a project loaded, the autosave is from current session's dirty state
      setTimeout(() => {
        const hasAutosave = projectFiles.backendAutosaveStatus.value?.exists
        const backendHasProject = !!projectFiles.currentProjectData.value
        const backendHasChannels = Object.keys(mqtt.channelConfigs.value).length > 0

        // Only show recovery dialog if autosave exists but backend is in fresh state
        // (no project loaded and no channels configured)
        if (hasAutosave && !backendHasProject && !backendHasChannels) {
          console.log('[APP] Autosave recovery available (backend is fresh) - showing dialog')
          hasLastProject.value = false
          showStartupDialog.value = true
        }
      }, 1000)
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

  // Keep store in sync with MQTT channel configs
  // This ensures newly created/deleted channels are reflected in the UI
  watch(() => mqtt.channelConfigs.value, (newConfigs) => {
    store.setChannels(newConfigs)
    console.log('[APP] Channel configs updated:', Object.keys(newConfigs).length)
  }, { deep: true })

  // Listen for backend startup cleared event
  // This is the ONLY time we show the startup dialog - when the DAQ service starts fresh
  // Page refreshes just reconnect and use current state (no dialog)
  mqtt.subscribe('nisystem/nodes/+/system/startup-cleared', (payload: any) => {
    console.log('[APP] Backend service started fresh - showing startup dialog...')

    // Request current project info to show in dialog
    projectFiles.getCurrentProject()

    // Wait a bit for project info, then show dialog
    setTimeout(() => {
      if (projectFiles.currentProjectData.value) {
        console.log('[APP] Last project available - showing load/fresh options')
        hasLastProject.value = true
      } else {
        console.log('[APP] No previous project - showing fresh system message')
        hasLastProject.value = false
      }
      showStartupDialog.value = true
    }, 500)
  })

  // ========================================================================
  // AUTO-SAVE: Watch for layout changes and mark project dirty
  // ========================================================================
  watch(() => store.pages, () => {
    // Only mark dirty if a project is loaded
    if (projectFiles.currentProject.value) {
      console.log('[APP] Layout changed, marking project dirty')
      projectFiles.markDirty()
    }
  }, { deep: true })

  // ========================================================================
  // BEFORE UNLOAD: Warn about unsaved changes
  // ========================================================================
  const handleBeforeUnload = (e: BeforeUnloadEvent) => {
    if (projectFiles.checkUnsavedChanges()) {
      // Standard way to show browser's "unsaved changes" dialog
      e.preventDefault()
      // Chrome requires returnValue to be set
      e.returnValue = 'You have unsaved changes. Are you sure you want to leave?'
      return e.returnValue
    }
  }
  window.addEventListener('beforeunload', handleBeforeUnload)

  // Cleanup interval on unmount
  onUnmounted(() => {
    clearInterval(checkMqttReady)
    window.removeEventListener('beforeunload', handleBeforeUnload)
    if (windowPositionCleanup) {
      windowPositionCleanup()
    }
  })

  // Start tracking window position for initial page
  const initialPageId = getPageFromUrl() || store.currentPageId
  if (initialPageId) {
    windowPositionCleanup = windowSync.trackWindowPosition(initialPageId)
  }
})

// Control handlers
function handleStart() {
  console.log('[APP] handleStart called, isAcquiring:', store.isAcquiring)
  mqtt.startAcquisition()
}

function handleStop() {
  console.log('[APP] handleStop called, isAcquiring:', store.isAcquiring)
  mqtt.stopAcquisition()
  // Clear all values to reset widgets to boot state (showing "--")
  store.clearValues()
}

function handleRecordStart() {
  console.log('[APP] handleRecordStart called, isAcquiring:', store.isAcquiring, 'isRecording:', store.isRecording)
  mqtt.startRecording()
}

function handleRecordStop() {
  console.log('[APP] handleRecordStop called, isRecording:', store.isRecording)
  mqtt.stopRecording()
}

function handleSessionStart() {
  const username = auth.currentUser.value?.username || 'user'
  playground.startTestSession(username)
}

function handleSessionStop() {
  playground.stopTestSession()
}

function handleRetryConnection() {
  mqtt.disconnect()
  setTimeout(() => {
    mqtt.connect('ws://localhost:9002')
  }, 100)
}

const saveDenied = ref(false)

async function handleManualSave() {
  if (!auth.isSupervisor.value) {
    saveDenied.value = true
    setTimeout(() => { saveDenied.value = false }, 800)
    console.warn('[APP] Save denied - requires supervisor or admin role')
    return
  }
  const success = await projectFiles.saveNow()
  if (success) {
    console.log('[APP] Project saved manually')
  } else {
    console.error('[APP] Failed to save project')
  }
}

</script>

<template>
  <div class="app">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
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
            title="Configuration"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
            </svg>
            Config
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'scripts' }"
            @click="activeTab = 'scripts'"
            title="Scripts"
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
            title="Data Recording"
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
            title="Safety System"
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
            Notes
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'admin' }"
            @click="activeTab = 'admin'"
            title="Admin Panel"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
              <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
            </svg>
            Admin
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
          @session-start="handleSessionStart"
          @session-stop="handleSessionStop"
          @add-widget="openAddPanel"
        />

        <!-- Project Status / Save Indicator -->
        <div class="project-status" v-if="projectFiles.currentProject.value">
          <span class="project-name" :title="projectFiles.currentProject.value">
            {{ projectFiles.currentProjectData.value?.name || 'Untitled' }}
          </span>
          <span
            v-if="projectFiles.isDirty.value"
            class="dirty-indicator"
            title="Unsaved changes"
          >
            <span class="dot"></span>
            Modified
          </span>
          <button
            v-if="projectFiles.isDirty.value"
            class="btn-save"
            :class="{ 'save-denied': saveDenied }"
            @click="handleManualSave"
            :title="auth.isSupervisor.value ? 'Save now' : 'Save requires supervisor or admin role'"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/>
              <polyline points="17,21 17,13 7,13 7,21"/>
              <polyline points="7,3 7,8 15,8"/>
            </svg>
          </button>
        </div>

        <!-- User Auth Section -->
        <div class="user-section">
          <template v-if="auth.authenticated.value && auth.currentUser.value">
            <span class="user-info">
              <span class="user-avatar">{{ auth.currentUser.value.username.charAt(0).toUpperCase() }}</span>
              <span class="user-name">{{ auth.currentUser.value.displayName || auth.currentUser.value.username }}</span>
              <span class="user-role">{{ auth.currentUser.value.role }}</span>
            </span>
            <button class="btn-logout" @click="auth.logout()" title="Logout">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
                <polyline points="16,17 21,12 16,7"/>
                <line x1="21" y1="12" x2="9" y2="12"/>
              </svg>
            </button>
          </template>
          <template v-else>
            <button class="btn-login" @click="showLoginDialog = true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
                <polyline points="10,17 15,12 10,7"/>
                <line x1="15" y1="12" x2="3" y2="12"/>
              </svg>
              Login
            </button>
          </template>
        </div>
      </div>
    </header>

    <!-- Main content -->
    <main class="app-main">
      <!-- P&ID Toolbar (shown when in P&ID edit mode on overview) -->
      <PidToolbar v-if="activeTab === 'overview' && store.pidEditMode" />
      <keep-alive>
        <component :is="activeTabComponent" :key="activeTab" />
      </keep-alive>
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

    <!-- Login Dialog -->
    <LoginDialog
      :is-open="showLoginDialog"
      :allow-cancel="true"
      @close="showLoginDialog = false"
      @success="showLoginDialog = false"
    />

    <!-- Startup Dialog -->
    <Transition name="modal">
      <div v-if="showStartupDialog" class="startup-overlay">
        <div class="startup-dialog">
          <!-- CRASH RECOVERY: Show if autosave exists -->
          <template v-if="hasAutosaveRecovery">
            <div class="startup-header recovery-header">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              <h2>Unsaved Work Detected</h2>
              <p>The service was shut down unexpectedly. Would you like to recover your unsaved work?</p>
            </div>

            <!-- Show autosave info -->
            <div class="last-project-info recovery-info">
              <div class="project-name">{{ autosaveProjectName }}</div>
              <div class="project-modified">Autosaved: {{ autosaveTimestamp }}</div>
            </div>

            <div class="startup-actions">
              <button class="startup-btn recovery" @click="recoverFromAutosave">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="23 4 23 10 17 10"/>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                </svg>
                <div>
                  <strong>Recover Unsaved Work</strong>
                  <span>Restore your work from before shutdown</span>
                </div>
              </button>

              <button class="startup-btn secondary" @click="discardAutosaveAndLoadProject" v-if="hasLastProject">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <div>
                  <strong>Load Saved Project Instead</strong>
                  <span>Discard unsaved work, load "{{ lastProjectName }}"</span>
                </div>
              </button>

              <button class="startup-btn secondary" @click="discardAutosaveAndStartFresh">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
                <div>
                  <strong>Discard &amp; Start Fresh</strong>
                  <span>Ignore unsaved work, start with clean slate</span>
                </div>
              </button>
            </div>

            <div class="startup-hint warning">
              If you don't recover now, the unsaved work will be lost
            </div>
          </template>

          <!-- Has Last Project: Show choice between Load/Fresh -->
          <template v-else-if="hasLastProject">
            <div class="startup-header">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
              <h2>Welcome to NISystem</h2>
              <p>Would you like to load your previous project or start fresh?</p>
            </div>

            <!-- Show last project info -->
            <div class="last-project-info" v-if="lastProjectName">
              <div class="project-name">{{ lastProjectName }}</div>
              <div class="project-modified" v-if="lastProjectModified">Last modified: {{ lastProjectModified }}</div>
            </div>

            <div class="startup-actions">
              <button class="startup-btn primary" @click="loadLastProject">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                  <polyline points="9 22 9 12 15 12 15 22"/>
                </svg>
                <div>
                  <strong>Load "{{ lastProjectName }}"</strong>
                  <span>Continue where you left off</span>
                </div>
              </button>

              <button class="startup-btn secondary" @click="startFresh">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                </svg>
                <div>
                  <strong>Start Fresh</strong>
                  <span>Configure new channels from scratch</span>
                </div>
              </button>
            </div>

            <div class="startup-hint">
              You can manage projects anytime from the Config tab
            </div>
          </template>

          <!-- No Last Project: Show fresh system message -->
          <template v-else>
            <div class="startup-header">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
              </svg>
              <h2>Fresh System - Ready to Configure</h2>
              <p class="fresh-message">
                No previous project found. The system is starting with a clean slate.
                <br><br>
                Configure your channels, widgets, and settings from the Config tab.
              </p>
            </div>

            <div class="startup-actions">
              <button class="startup-btn primary full-width" @click="continueWithFreshSystem">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
                <div>
                  <strong>Continue</strong>
                  <span>Begin configuration</span>
                </div>
              </button>
            </div>

            <div class="startup-hint">
              Start by adding channels in Config → Channel Configuration
            </div>
          </template>
        </div>
      </div>
    </Transition>
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
  position: relative;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
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
  overflow-y: auto;  /* Enable scrolling for widgets below viewport */
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

/* Project Status / Save Indicator */
.project-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-left: 1px solid #2a2a4a;
  margin-left: 8px;
}

.project-status .project-name {
  font-size: 0.7rem;
  color: #9ca3af;
  max-width: 100px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.2;
  word-break: break-word;
}

.dirty-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

.dirty-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fbbf24;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.btn-save {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  background: transparent;
  border: 1px solid #fbbf24;
  border-radius: 4px;
  color: #fbbf24;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-save:hover {
  background: rgba(251, 191, 36, 0.2);
}

.btn-save.save-denied {
  border-color: #ef4444;
  color: #ef4444;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
  animation: shake 0.4s ease-in-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-3px); }
  40% { transform: translateX(3px); }
  60% { transform: translateX(-2px); }
  80% { transform: translateX(2px); }
}

/* User Auth Section */
.user-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-left: 16px;
  border-left: 1px solid #2a2a4a;
  margin-left: 8px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #3b82f6;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
}

.user-name {
  font-size: 0.85rem;
  color: #fff;
  font-weight: 500;
}

.user-role {
  font-size: 0.7rem;
  color: #888;
  text-transform: capitalize;
  background: #1a1a2e;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-login,
.btn-logout {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid #3b82f6;
  border-radius: 4px;
  color: #60a5fa;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-login:hover,
.btn-logout:hover {
  background: #1e3a5f;
}

.btn-logout {
  padding: 6px;
  border-color: #4b5563;
  color: #888;
}

.btn-logout:hover {
  border-color: #ef4444;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

/* Startup Dialog */
.startup-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  padding: 20px;
}

.startup-dialog {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border: 2px solid #3b82f6;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  max-width: 600px;
  width: 100%;
  overflow: hidden;
  animation: slideUp 0.3s ease-out;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.startup-header {
  text-align: center;
  padding: 40px 40px 32px;
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.1) 0%, transparent 100%);
  border-bottom: 1px solid rgba(59, 130, 246, 0.2);
}

.startup-header svg {
  color: #3b82f6;
  margin-bottom: 20px;
}

.startup-header h2 {
  font-size: 1.75rem;
  font-weight: 700;
  color: #fff;
  margin: 0 0 12px;
}

.startup-header p {
  font-size: 1rem;
  color: #9ca3af;
  margin: 0;
}

/* Last Project Info */
.last-project-info {
  text-align: center;
  padding: 16px 40px;
  background: rgba(59, 130, 246, 0.1);
  border-bottom: 1px solid rgba(59, 130, 246, 0.2);
}

.project-name {
  font-size: 1.25rem;
  font-weight: 600;
  color: #60a5fa;
  margin-bottom: 4px;
}

.project-modified {
  font-size: 0.85rem;
  color: #9ca3af;
}

.startup-actions {
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.startup-btn {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: #1a1a2e;
  border: 2px solid #2a2a4a;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  width: 100%;
}

.startup-btn:hover {
  background: #242442;
  border-color: #3b82f6;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.2);
}

.startup-btn svg {
  flex-shrink: 0;
  color: #3b82f6;
}

.startup-btn.primary:hover svg {
  color: #60a5fa;
}

.startup-btn.secondary svg {
  color: #22c55e;
}

.startup-btn.secondary:hover {
  border-color: #22c55e;
  box-shadow: 0 8px 20px rgba(34, 197, 94, 0.2);
}

.startup-btn.secondary:hover svg {
  color: #4ade80;
}

.startup-btn div {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.startup-btn strong {
  font-size: 1.1rem;
  font-weight: 600;
  color: #fff;
  display: block;
}

.startup-btn span {
  font-size: 0.875rem;
  color: #9ca3af;
  display: block;
}

.startup-btn.full-width {
  justify-content: center;
}

.fresh-message {
  font-size: 0.95rem;
  line-height: 1.6;
  color: #d1d5db;
  max-width: 480px;
}

.startup-hint {
  text-align: center;
  padding: 0 40px 32px;
  font-size: 0.85rem;
  color: #6b7280;
}

.startup-hint.warning {
  color: #f59e0b;
}

/* Recovery dialog styles */
.recovery-header svg {
  color: #f59e0b !important;
}

.recovery-info {
  background: rgba(245, 158, 11, 0.1) !important;
  border-color: rgba(245, 158, 11, 0.2) !important;
}

.recovery-info .project-name {
  color: #fbbf24 !important;
}

.startup-btn.recovery {
  border-color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
}

.startup-btn.recovery:hover {
  border-color: #fbbf24;
  background: rgba(245, 158, 11, 0.2);
  box-shadow: 0 8px 20px rgba(245, 158, 11, 0.2);
}

.startup-btn.recovery svg {
  color: #f59e0b;
}

.startup-btn.recovery:hover svg {
  color: #fbbf24;
}
</style>
