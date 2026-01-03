/**
 * useProjectFiles - Manages project and config file operations via MQTT
 *
 * Projects are stored as .json files in the projects/ directory
 * Configs are stored as .ini files in the config/ directory
 *
 * A project contains:
 * - Layout (widgets, grid settings)
 * - Scripts (calculated params, sequences, schedules, alarms, transformations, triggers)
 * - Recording settings
 * - Safety settings (alarm configs, interlocks)
 * - Reference to which .ini config file it uses
 *
 * When loading a project, the backend will also load the associated .ini config
 */

import { ref, computed } from 'vue'
import { useMqtt } from './useMqtt'
import { useDashboardStore } from '../stores/dashboard'
import type { ChannelConfig, ChannelType } from '../types'

// Channel config as stored in the project JSON file
export interface ProjectChannelConfig {
  physical_channel: string
  channel_type: string  // 'rtd', 'thermocouple', 'voltage', 'digital_output', etc.
  // display_name removed - use name (TAG) everywhere
  unit?: string
  group?: string
  description?: string  // For tooltips/documentation only

  // Legacy limit names (for backward compatibility)
  low_limit?: number
  high_limit?: number
  low_warning?: number
  high_warning?: number

  // ISA-18.2 Alarm Configuration
  alarm_enabled?: boolean           // Master enable for limit checking
  hihi_limit?: number               // High-High (critical)
  hi_limit?: number                 // High (warning)
  lo_limit?: number                 // Low (warning)
  lolo_limit?: number               // Low-Low (critical)
  alarm_priority?: 'diagnostic' | 'low' | 'medium' | 'high' | 'critical'
  alarm_deadband?: number           // Hysteresis to prevent chatter
  alarm_delay_sec?: number          // On-delay before triggering
  alarm_clear_delay_sec?: number    // Off-delay before clearing
  safety_action?: string            // Reference to safety action (null = visual only)

  chartable?: boolean
  color?: string
  visible?: boolean
  scale_slope?: number
  scale_offset?: number
  // Type-specific fields
  rtd_type?: string
  thermocouple_type?: string
  resistance_config?: string
  // Digital output settings
  invert?: boolean
}

// System config as stored in the project JSON file
export interface ProjectSystemConfig {
  mqtt_broker: string
  mqtt_port: number
  scan_rate_hz: number
  simulation_mode: boolean
  device_name: string
  default_tc_type?: string
  default_rtd_type?: string
  default_resistance_config?: string
}

export interface ProjectFile {
  filename: string
  name: string
  config: string  // Associated .ini file
  modified: string
  created: string
  active: boolean
  error?: string
}

export interface ConfigFile {
  filename: string
  path: string
  modified: string
  size: number
  active: boolean
}

import type { DashboardPage } from '../types'

export interface ProjectData {
  type: 'nisystem-project'
  version: string
  name: string
  config?: string  // Legacy: external .ini file reference (optional for merged configs)
  created: string
  modified: string
  // Embedded system config (v2.0+)
  system?: ProjectSystemConfig
  // Embedded channel definitions (v2.0+)
  channels?: Record<string, ProjectChannelConfig>
  layout: {
    widgets?: any[]                // Optional for legacy single-page
    pages?: DashboardPage[]        // Multi-page support
    currentPageId?: string         // Current page ID
    gridColumns: number
    rowHeight: number
  }
  scripts: {
    calculatedParams: any[]
    sequences: any[]
    schedules: any[]
    alarms: any[]
    transformations: any[]
    triggers: any[]
  }
  recording: {
    config: any
    selectedChannels: string[]
  }
  safety: {
    alarmConfigs: any[]
    interlocks: any[]
  }
}

// Singleton state
const projects = ref<ProjectFile[]>([])
const configs = ref<ConfigFile[]>([])
const currentProject = ref<string | null>(null)
const currentProjectData = ref<ProjectData | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const initialized = ref(false)

// Callbacks for project events
const projectLoadedCallbacks: ((data: ProjectData) => void)[] = []

export function useProjectFiles() {
  const mqtt = useMqtt()
  const store = useDashboardStore()

  // Subscribe to MQTT responses
  function setupSubscriptions() {
    if (initialized.value) return
    initialized.value = true

    const prefix = 'nisystem'

    mqtt.subscribe(`${prefix}/project/list/response`, (payload: any) => {
      projects.value = payload.projects || []
    })

    mqtt.subscribe(`${prefix}/project/loaded`, (payload: any) => {
      console.log('[PROJECT LOADING] Received project/loaded message:', {
        success: payload.success,
        hasProject: !!payload.project,
        filename: payload.filename
      })

      if (payload.success && payload.project) {
        currentProject.value = payload.filename
        currentProjectData.value = payload.project

        try {
          // Apply project data to frontend
          console.log('[PROJECT LOADING] Calling applyProjectData...')
          applyProjectData(payload.project)
          console.log('[PROJECT LOADING] ✅ Project applied successfully')

          // Notify callbacks
          projectLoadedCallbacks.forEach(cb => cb(payload.project))
        } catch (err) {
          console.error('[PROJECT LOADING] ❌ Error applying project data:', err)
          error.value = `Failed to apply project: ${err instanceof Error ? err.message : String(err)}`
        }
      } else {
        console.error('[PROJECT LOADING] ❌ Project load failed or missing data')
        if (!payload.success) {
          error.value = payload.message || 'Project load failed'
        }
      }
      isLoading.value = false
    })

    mqtt.subscribe(`${prefix}/project/response`, (payload: any) => {
      isLoading.value = false
      if (!payload.success) {
        error.value = payload.message
      } else {
        error.value = null
      }
    })

    mqtt.subscribe(`${prefix}/project/current`, (payload: any) => {
      console.log('[PROJECT LOADING] Received project/current message:', {
        hasProject: !!payload.project,
        filename: payload.filename
      })

      currentProject.value = payload.filename
      currentProjectData.value = payload.project

      // Apply project data if present (same as project/loaded)
      if (payload.project) {
        try {
          console.log('[PROJECT LOADING] Applying current project data...')
          applyProjectData(payload.project)
          console.log('[PROJECT LOADING] ✅ Current project applied successfully')
          projectLoadedCallbacks.forEach(cb => cb(payload.project))
        } catch (err) {
          console.error('[PROJECT LOADING] ❌ Error applying current project:', err)
          error.value = `Failed to apply project: ${err instanceof Error ? err.message : String(err)}`
        }
      } else {
        console.log('[PROJECT LOADING] No current project to apply')
      }
    })

    mqtt.subscribe(`${prefix}/config/list/response`, (payload: any) => {
      configs.value = payload.configs || []
    })
  }

  // List available projects
  function listProjects() {
    mqtt.sendCommand('project/list')
  }

  // List available configs
  function listConfigs() {
    mqtt.sendCommand('config/list')
  }

  // Load a project (backend will also load associated config)
  function loadProject(filename: string): Promise<boolean> {
    return new Promise((resolve) => {
      isLoading.value = true
      error.value = null

      const timeout = setTimeout(() => {
        isLoading.value = false
        error.value = 'Load timeout'
        resolve(false)
      }, 10000)

      // Listen for response
      const unsubscribe = mqtt.subscribe('nisystem/project/loaded', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        resolve(payload.success)
      })

      mqtt.sendCommand('project/load', { filename })
    })
  }

  // Save current state as project
  function saveProject(filename: string, name?: string): Promise<boolean> {
    return new Promise((resolve) => {
      isLoading.value = true
      error.value = null

      const projectData = collectCurrentState()
      projectData.name = name || filename.replace('.json', '')

      const timeout = setTimeout(() => {
        isLoading.value = false
        error.value = 'Save timeout'
        resolve(false)
      }, 10000)

      const unsubscribe = mqtt.subscribe('nisystem/project/response', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        if (payload.success) {
          currentProject.value = filename.endsWith('.json') ? filename : filename + '.json'
          // Refresh project list
          listProjects()
        }
        resolve(payload.success)
      })

      mqtt.sendCommand('project/save', { filename, data: projectData })
    })
  }

  // Delete a project
  function deleteProject(filename: string): Promise<boolean> {
    return new Promise((resolve) => {
      isLoading.value = true

      const timeout = setTimeout(() => {
        isLoading.value = false
        resolve(false)
      }, 5000)

      const unsubscribe = mqtt.subscribe('nisystem/project/response', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        if (payload.success) {
          listProjects()  // Refresh list
        }
        resolve(payload.success)
      })

      mqtt.sendCommand('project/delete', { filename })
    })
  }

  // Get current project from backend
  function getCurrentProject() {
    mqtt.sendCommand('project/get-current')
  }

  // Collect current frontend state into project data
  function collectCurrentState(): Partial<ProjectData> {
    // Get layout from store
    const layout = store.getLayout()

    // Get scripts - these should eventually come from a scripts store
    // For now, using localStorage as intermediate (to be migrated)
    const calculatedParams = JSON.parse(localStorage.getItem('nisystem-scripts') || '[]')
    const sequences = JSON.parse(localStorage.getItem('nisystem-sequences') || '[]')
    const schedules = JSON.parse(localStorage.getItem('nisystem-schedules') || '[]')
    const alarms = JSON.parse(localStorage.getItem('nisystem-alarms') || '[]')
    const transformations = JSON.parse(localStorage.getItem('nisystem-transformations') || '[]')
    const triggers = JSON.parse(localStorage.getItem('nisystem-triggers') || '[]')

    // Get recording settings
    const recordingConfig = JSON.parse(localStorage.getItem('nisystem-recording-config') || '{}')
    const selectedChannels = JSON.parse(localStorage.getItem('nisystem-recording-channels') || '[]')

    // Get safety settings
    const alarmConfigs = JSON.parse(localStorage.getItem('nisystem-alarm-configs') || '[]')
    const interlocks = JSON.parse(localStorage.getItem('nisystem-interlocks') || '[]')

    return {
      layout: {
        widgets: layout.widgets,
        pages: layout.pages,                    // Multi-page support
        currentPageId: layout.currentPageId,    // Current page ID
        gridColumns: layout.gridColumns,
        rowHeight: layout.rowHeight
      },
      scripts: {
        calculatedParams,
        sequences,
        schedules,
        alarms,
        transformations,
        triggers
      },
      recording: {
        config: recordingConfig,
        selectedChannels
      },
      safety: {
        alarmConfigs,
        interlocks
      }
    }
  }

  // Convert project channel config to store channel config
  function convertProjectChannel(name: string, pch: ProjectChannelConfig): ChannelConfig {
    return {
      name,  // TAG is the only identifier
      // display_name removed - use name (TAG) everywhere
      channel_type: pch.channel_type as ChannelType,
      physical_channel: pch.physical_channel,
      unit: pch.unit || '',
      group: pch.group || 'Ungrouped',
      description: pch.description,  // For tooltips/documentation only

      // Legacy limit names (backward compatibility)
      low_limit: pch.low_limit,
      high_limit: pch.high_limit,
      low_warning: pch.low_warning,
      high_warning: pch.high_warning,

      // ISA-18.2 Alarm Configuration
      alarm_enabled: pch.alarm_enabled,
      hihi_limit: pch.hihi_limit,
      hi_limit: pch.hi_limit,
      lo_limit: pch.lo_limit,
      lolo_limit: pch.lolo_limit,
      alarm_priority: pch.alarm_priority,
      alarm_deadband: pch.alarm_deadband,
      alarm_delay_sec: pch.alarm_delay_sec,
      alarm_clear_delay_sec: pch.alarm_clear_delay_sec,
      safety_action: pch.safety_action,

      chartable: pch.chartable !== false && pch.channel_type !== 'digital_output',
      color: pch.color,
      visible: pch.visible !== false,
      scale_slope: pch.scale_slope,
      scale_offset: pch.scale_offset,
      invert: pch.invert
    }
  }

  // Apply loaded project data to frontend
  function applyProjectData(data: ProjectData) {
    console.log('[PROJECT LOADING] Starting to apply project data...')
    console.log('[PROJECT LOADING] Project name:', data.name)
    console.log('[PROJECT LOADING] Project version:', data.version)
    console.log('[PROJECT LOADING] Project config:', data.config)
    console.log('[PROJECT LOADING] Has embedded channels:', !!data.channels)

    // Apply embedded channels if present (v2.0+ merged config format)
    if (data.channels && Object.keys(data.channels).length > 0) {
      console.log('[PROJECT LOADING] Applying embedded channels...')
      const channelConfigs: Record<string, ChannelConfig> = {}

      for (const [name, pch] of Object.entries(data.channels)) {
        channelConfigs[name] = convertProjectChannel(name, pch)
      }

      console.log('[PROJECT LOADING] Converted channels:', Object.keys(channelConfigs).length)
      store.setChannels(channelConfigs)
      console.log('[PROJECT LOADING] ✅ Channels applied to store')
    }

    // Apply layout (supports both legacy single-page and multi-page)
    if (data.layout) {
      console.log('[PROJECT LOADING] Applying layout...')
      console.log('[PROJECT LOADING] Layout structure:', {
        hasLegacyWidgets: !!data.layout.widgets && data.layout.widgets.length > 0,
        legacyWidgetCount: data.layout.widgets?.length || 0,
        hasPages: !!data.layout.pages && data.layout.pages.length > 0,
        pageCount: data.layout.pages?.length || 0,
        currentPageId: data.layout.currentPageId,
        gridColumns: data.layout.gridColumns,
        rowHeight: data.layout.rowHeight
      })

      // Log detailed page info
      if (data.layout.pages && data.layout.pages.length > 0) {
        data.layout.pages.forEach((page: any, idx: number) => {
          console.log(`[PROJECT LOADING] Page ${idx}: ${page.name} (id: ${page.id}, widgets: ${page.widgets?.length || 0})`)
        })
      }

      try {
        store.setLayout({
          system_id: store.systemId,
          widgets: data.layout.widgets || [],      // Legacy single-page
          pages: data.layout.pages,                 // Multi-page support
          currentPageId: data.layout.currentPageId, // Current page ID
          gridColumns: data.layout.gridColumns || 12,
          rowHeight: data.layout.rowHeight || 80
        })
        console.log('[PROJECT LOADING] ✅ Layout applied successfully')
      } catch (error) {
        console.error('[PROJECT LOADING] ❌ Error applying layout:', error)
        throw error
      }
    } else {
      console.warn('[PROJECT LOADING] ⚠️ No layout data found in project')
    }

    // Apply scripts to localStorage (useScripts will pick them up)
    if (data.scripts) {
      if (data.scripts.calculatedParams) {
        localStorage.setItem('nisystem-scripts', JSON.stringify(data.scripts.calculatedParams))
      }
      if (data.scripts.sequences) {
        localStorage.setItem('nisystem-sequences', JSON.stringify(data.scripts.sequences))
      }
      if (data.scripts.schedules) {
        localStorage.setItem('nisystem-schedules', JSON.stringify(data.scripts.schedules))
      }
      if (data.scripts.alarms) {
        localStorage.setItem('nisystem-alarms', JSON.stringify(data.scripts.alarms))
      }
      if (data.scripts.transformations) {
        localStorage.setItem('nisystem-transformations', JSON.stringify(data.scripts.transformations))
      }
      if (data.scripts.triggers) {
        localStorage.setItem('nisystem-triggers', JSON.stringify(data.scripts.triggers))
      }
    }

    // Apply recording settings
    if (data.recording) {
      if (data.recording.config) {
        localStorage.setItem('nisystem-recording-config', JSON.stringify(data.recording.config))
      }
      if (data.recording.selectedChannels) {
        localStorage.setItem('nisystem-recording-channels', JSON.stringify(data.recording.selectedChannels))
      }
    }

    // Apply safety settings
    if (data.safety) {
      if (data.safety.alarmConfigs) {
        localStorage.setItem('nisystem-alarm-configs', JSON.stringify(data.safety.alarmConfigs))
      }
      if (data.safety.interlocks) {
        localStorage.setItem('nisystem-interlocks', JSON.stringify(data.safety.interlocks))
      }
    }

    currentProjectData.value = data
  }

  // Register callback for when a project is loaded
  function onProjectLoaded(callback: (data: ProjectData) => void): () => void {
    projectLoadedCallbacks.push(callback)
    return () => {
      const idx = projectLoadedCallbacks.indexOf(callback)
      if (idx > -1) projectLoadedCallbacks.splice(idx, 1)
    }
  }

  // Check if there are unsaved changes
  function hasUnsavedChanges(): boolean {
    if (!currentProjectData.value) return false

    const current = collectCurrentState()
    const saved = currentProjectData.value

    // Simple comparison - could be made more sophisticated
    return JSON.stringify(current.layout) !== JSON.stringify(saved.layout) ||
           JSON.stringify(current.scripts) !== JSON.stringify(saved.scripts)
  }

  // Create new project (clear current state)
  function newProject() {
    currentProject.value = null
    currentProjectData.value = null

    // Clear layout
    store.widgets.splice(0)

    // Clear localStorage items
    localStorage.removeItem('nisystem-scripts')
    localStorage.removeItem('nisystem-sequences')
    localStorage.removeItem('nisystem-schedules')
    localStorage.removeItem('nisystem-alarms')
    localStorage.removeItem('nisystem-transformations')
    localStorage.removeItem('nisystem-triggers')
    localStorage.removeItem('nisystem-recording-config')
    localStorage.removeItem('nisystem-recording-channels')
    localStorage.removeItem('nisystem-alarm-configs')
    localStorage.removeItem('nisystem-interlocks')
  }

  // Initialize on first use
  setupSubscriptions()

  return {
    // State
    projects: computed(() => projects.value),
    configs: computed(() => configs.value),
    currentProject: computed(() => currentProject.value),
    currentProjectData: computed(() => currentProjectData.value),
    isLoading: computed(() => isLoading.value),
    error: computed(() => error.value),

    // Actions
    listProjects,
    listConfigs,
    loadProject,
    saveProject,
    deleteProject,
    getCurrentProject,
    newProject,
    collectCurrentState,
    applyProjectData,
    hasUnsavedChanges,

    // Events
    onProjectLoaded
  }
}
