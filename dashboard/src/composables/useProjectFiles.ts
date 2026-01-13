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
import { usePythonScripts } from './usePythonScripts'
import { useBackendScripts } from './useBackendScripts'
import { useSafety } from './useSafety'
import type { ChannelConfig, ChannelType } from '../types'

// Channel config as stored in the project JSON file
export interface ProjectChannelConfig {
  physical_channel: string
  channel_type: string  // 'rtd', 'thermocouple', 'voltage', 'digital_output', etc.
  // display_name removed - use name (TAG) everywhere
  unit?: string         // Preferred field name
  units?: string        // Legacy field name (backward compatibility)
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
    // Extended script types (v2.1+)
    pythonScripts?: any[]          // Pyodide-based Python scripts
    functionBlocks?: any[]         // Function block diagrams
    drawPatterns?: any             // Draw patterns { patterns: [], history: [] }
    watchdogs?: any[]              // Watchdog timers
    stateMachines?: any[]          // State machine definitions
    reportTemplates?: any[]        // Report templates
    scheduledReports?: any[]       // Scheduled report configurations
  }
  recording: {
    config: any
    selectedChannels: string[]
  }
  safety: {
    alarmConfigs: any              // Can be array or Record<string, AlarmConfig>
    interlocks: any[]
    // Extended safety settings (v2.1+)
    safetyActions?: any            // ISA-18.2 safety actions
    safeStateConfig?: any          // Safe state configuration for trips
    autoExecuteSafetyActions?: boolean
  }
  // Notebook data (v2.1+)
  notebook?: {
    entries?: any[]
    experiments?: any[]
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

// Guard to prevent duplicate script loading when both project/loaded and project/current are received
let scriptLoadingTimeout: ReturnType<typeof setTimeout> | null = null

export function useProjectFiles() {
  const mqtt = useMqtt()
  const store = useDashboardStore()
  const safety = useSafety()

  // Subscribe to MQTT responses
  // NOTE: Backend uses node-prefixed topics: nisystem/nodes/{node_id}/project/...
  // We use wildcard (+) to receive from any node
  function setupSubscriptions() {
    if (initialized.value) return
    initialized.value = true

    const prefix = 'nisystem'
    const nodePrefix = `${prefix}/nodes/+`  // Wildcard for any node

    mqtt.subscribe(`${nodePrefix}/project/list/response`, (payload: any) => {
      projects.value = payload.projects || []
    })

    mqtt.subscribe(`${nodePrefix}/project/loaded`, async (payload: any) => {
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
          await applyProjectData(payload.project)
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

    mqtt.subscribe(`${nodePrefix}/project/response`, (payload: any) => {
      isLoading.value = false
      if (!payload.success) {
        error.value = payload.message
      } else {
        error.value = null
      }
    })

    mqtt.subscribe(`${nodePrefix}/project/current`, async (payload: any) => {
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
          await applyProjectData(payload.project)
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

    mqtt.subscribe(`${nodePrefix}/config/list/response`, (payload: any) => {
      configs.value = payload.configs || []
    })
  }

  // List available projects
  function listProjects() {
    mqtt.sendNodeCommand('project/list')
  }

  // List available configs
  function listConfigs() {
    mqtt.sendNodeCommand('config/list')
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

      // Listen for response (using wildcard for node ID)
      const unsubscribe = mqtt.subscribe('nisystem/nodes/+/project/loaded', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        resolve(payload.success)
      })

      mqtt.sendNodeCommand('project/load', { filename })
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

      const unsubscribe = mqtt.subscribe('nisystem/nodes/+/project/response', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        if (payload.success) {
          currentProject.value = filename.endsWith('.json') ? filename : filename + '.json'
          // Refresh project list
          listProjects()
        }
        resolve(payload.success)
      })

      mqtt.sendNodeCommand('project/save', { filename, data: projectData })
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

      const unsubscribe = mqtt.subscribe('nisystem/nodes/+/project/response', (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        if (payload.success) {
          listProjects()  // Refresh list
        }
        resolve(payload.success)
      })

      mqtt.sendNodeCommand('project/delete', { filename })
    })
  }

  // Get current project from backend
  function getCurrentProject() {
    mqtt.sendNodeCommand('project/get-current')
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

    // Extended script types (v2.1+)
    // Get Python scripts directly from composable (source of truth) instead of localStorage
    const pythonScriptsComposable = usePythonScripts()
    const pythonScripts = pythonScriptsComposable.exportScripts()
    const functionBlocks = JSON.parse(localStorage.getItem('dcflux-function-blocks') || '[]')
    const drawPatterns = JSON.parse(localStorage.getItem('dcflux-draw-patterns') || '{"patterns":[],"history":[]}')
    const watchdogs = JSON.parse(localStorage.getItem('dcflux-watchdogs') || '[]')
    const stateMachines = JSON.parse(localStorage.getItem('dcflux-state-machines') || '[]')
    const reportTemplates = JSON.parse(localStorage.getItem('dcflux-report-templates') || '[]')
    const scheduledReports = JSON.parse(localStorage.getItem('dcflux-scheduled-reports') || '[]')

    // Get recording settings
    const recordingConfig = JSON.parse(localStorage.getItem('nisystem-recording-config') || '{}')
    const selectedChannels = JSON.parse(localStorage.getItem('nisystem-recording-channels') || '[]')

    // Get safety settings - try v2 first, then fall back to v1
    let alarmConfigs = localStorage.getItem('nisystem-alarm-configs-v2')
    if (!alarmConfigs) {
      alarmConfigs = localStorage.getItem('nisystem-alarm-configs')
    }
    alarmConfigs = JSON.parse(alarmConfigs || '{}')
    const interlocks = JSON.parse(localStorage.getItem('nisystem-interlocks') || '[]')

    // Extended safety settings (v2.1+)
    const safetyActions = JSON.parse(localStorage.getItem('nisystem-safety-actions') || '{}')
    const safeStateConfig = JSON.parse(localStorage.getItem('nisystem-safe-state-config') || '{}')
    const autoExecuteSafetyActions = localStorage.getItem('nisystem-auto-execute-safety-actions') === 'true'

    // Get notebook data (v2.1+)
    const notebookEntries = JSON.parse(localStorage.getItem('nisystem_notebook') || '[]')
    const experiments = JSON.parse(localStorage.getItem('nisystem_experiments') || '[]')

    // IMPORTANT: Include channels from store so they're saved back to the project
    // Spread ALL channel fields to preserve hardware-specific settings
    // (rtd_type, thermocouple_type, voltage_range, terminal_config, log, precision, etc.)
    const channels: Record<string, ProjectChannelConfig> = {}
    for (const [name, ch] of Object.entries(store.channels)) {
      // Spread all fields from the channel to preserve everything
      channels[name] = { ...ch } as unknown as ProjectChannelConfig
    }

    // Preserve system, service, and schedules sections from loaded project
    // These contain hardware config (scan_rate, mqtt settings) that shouldn't be lost
    const system = currentProjectData.value?.system
    const service = (currentProjectData.value as any)?.service
    // Top-level schedules array (DHW draw schedules) - separate from scripts.schedules
    const topLevelSchedules = (currentProjectData.value as any)?.schedules

    return {
      // Preserve system config (mqtt, scan_rate, etc.) from loaded project
      ...(system ? { system } : {}),
      // Preserve service config (heartbeat, timeouts) from loaded project
      ...(service ? { service } : {}),
      // Preserve top-level schedules (DHW draw schedules) from loaded project
      ...(topLevelSchedules ? { schedules: topLevelSchedules } : {}),
      channels,  // Include channels so they're saved!
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
        triggers,
        // Extended script types
        pythonScripts,
        functionBlocks,
        drawPatterns,
        watchdogs,
        stateMachines,
        reportTemplates,
        scheduledReports
      },
      recording: {
        config: recordingConfig,
        selectedChannels
      },
      safety: {
        alarmConfigs,
        interlocks,
        // Extended safety settings
        safetyActions,
        safeStateConfig,
        autoExecuteSafetyActions
      },
      notebook: {
        entries: notebookEntries,
        experiments
      }
    }
  }

  // Convert project channel config to store channel config
  // IMPORTANT: Spread ALL fields to preserve hardware-specific settings
  // (rtd_type, thermocouple_type, voltage_range, terminal_config, log, precision, etc.)
  function convertProjectChannel(name: string, pch: ProjectChannelConfig): ChannelConfig {
    return {
      // Spread ALL fields from project channel to preserve everything
      ...pch,
      // Override specific fields with computed/normalized values
      name,  // TAG is the only identifier
      channel_type: pch.channel_type as ChannelType,
      unit: pch.unit || pch.units || '',  // Support both 'unit' and 'units' (legacy)
      group: pch.group || 'Ungrouped',
      chartable: pch.chartable !== false && pch.channel_type !== 'digital_output',
      visible: pch.visible !== false,
    } as ChannelConfig
  }

  // Apply loaded project data to frontend
  async function applyProjectData(data: ProjectData) {
    console.log('[PROJECT LOADING] Starting to apply project data...')
    console.log('[PROJECT LOADING] Project name:', data.name)
    console.log('[PROJECT LOADING] Project version:', data.version)
    console.log('[PROJECT LOADING] Project config:', data.config)
    console.log('[PROJECT LOADING] Has embedded channels:', !!data.channels)

    // CRITICAL: Clear all safety state FIRST to prevent ghost alarms from previous project
    console.log('[PROJECT LOADING] Clearing old safety state before loading new project...')
    safety.clearAllSafetyState('project_loading')

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

      // CRITICAL: Stop acquisition before sending channels (backend rejects bulk-create while acquiring)
      const wasAcquiring = store.isAcquiring
      if (wasAcquiring) {
        console.log('[PROJECT LOADING] Stopping acquisition to apply new channels...')
        mqtt.stopAcquisition()
        // Wait for acquisition to stop before sending channels
        await new Promise(resolve => setTimeout(resolve, 500))
      }

      // CRITICAL: Send channels to backend so it knows about the new channel config
      // Without this, the backend still has the old channel list and won't publish the new channel values
      console.log('[PROJECT LOADING] Sending channels to backend via bulk-create...')
      const channelArray = Object.values(channelConfigs)
      mqtt.bulkCreateChannels(channelArray)
      console.log('[PROJECT LOADING] ✅ Channels sent to backend:', channelArray.length, 'channels')

      // Wait for backend to process channels before restarting acquisition
      await new Promise(resolve => setTimeout(resolve, 1000))

      // Restart acquisition if it was running
      if (wasAcquiring) {
        console.log('[PROJECT LOADING] Restarting acquisition with new channels...')
        mqtt.startAcquisition()
      }
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

        // CRITICAL: Save layout to localStorage to prevent old cached layout from loading on next boot
        // Without this, localStorage has stale layout data that overwrites the project layout
        console.log('[PROJECT LOADING] Saving layout to localStorage to prevent cache issues...')
        store.saveLayoutToStorage()
        console.log('[PROJECT LOADING] ✅ Layout saved to localStorage')
      } catch (error) {
        console.error('[PROJECT LOADING] ❌ Error applying layout:', error)
        throw error
      }
    } else {
      console.warn('[PROJECT LOADING] ⚠️ No layout data found in project')
    }

    // Apply scripts to localStorage (useScripts will pick them up)
    // IMPORTANT: Always write to localStorage, even if empty, to clear stale data from previous project
    if (data.scripts) {
      // Core script types - always write, even if empty
      localStorage.setItem('nisystem-scripts', JSON.stringify(data.scripts.calculatedParams || []))
      localStorage.setItem('nisystem-sequences', JSON.stringify(data.scripts.sequences || []))
      localStorage.setItem('nisystem-schedules', JSON.stringify(data.scripts.schedules || []))
      localStorage.setItem('nisystem-alarms', JSON.stringify(data.scripts.alarms || []))
      localStorage.setItem('nisystem-transformations', JSON.stringify(data.scripts.transformations || []))
      localStorage.setItem('nisystem-triggers', JSON.stringify(data.scripts.triggers || []))

      // Extended script types (v2.1+) - always write, even if empty, to clear stale data
      const pythonScripts = data.scripts.pythonScripts || []
      localStorage.setItem('nisystem-python-scripts', JSON.stringify(pythonScripts))

      if (pythonScripts.length > 0) {
        // Notify usePythonScripts composable to reload scripts (frontend/Pyodide)
        const pythonScriptsComposable = usePythonScripts()
        pythonScriptsComposable.importScripts(pythonScripts)

        // ALSO send scripts to backend via MQTT for server-side execution
        // Use debouncing to prevent duplicate loading when both project/loaded and project/current fire
        if (scriptLoadingTimeout) {
          clearTimeout(scriptLoadingTimeout)
          console.log('[PROJECT LOADING] Debouncing script load - clearing previous timeout')
        }

        const backendScripts = useBackendScripts()

        // Clear existing scripts first to prevent duplicates
        console.log('[PROJECT LOADING] Clearing existing backend scripts...')
        backendScripts.clearAllScripts()

        // Debounced script loading - only the last call within 200ms will execute
        scriptLoadingTimeout = setTimeout(() => {
          console.log('[PROJECT LOADING] Sending', pythonScripts.length, 'scripts to backend...')
          for (const script of pythonScripts) {
            backendScripts.addScript({
              id: script.id,  // Preserve original ID to prevent duplicates
              name: script.name,
              code: script.code,
              description: script.description || '',
              runMode: script.runMode || script.run_mode || 'manual',
              enabled: script.enabled !== false
            })
            console.log('[PROJECT LOADING] Added script to backend:', script.name, 'with ID:', script.id)
          }
          scriptLoadingTimeout = null
        }, 200)
      }

      // Extended script types - always write, even if empty
      localStorage.setItem('dcflux-function-blocks', JSON.stringify(data.scripts.functionBlocks || []))
      localStorage.setItem('dcflux-draw-patterns', JSON.stringify(data.scripts.drawPatterns || { patterns: [], history: [] }))
      localStorage.setItem('dcflux-watchdogs', JSON.stringify(data.scripts.watchdogs || []))
      localStorage.setItem('dcflux-state-machines', JSON.stringify(data.scripts.stateMachines || []))
      localStorage.setItem('dcflux-report-templates', JSON.stringify(data.scripts.reportTemplates || []))
      localStorage.setItem('dcflux-scheduled-reports', JSON.stringify(data.scripts.scheduledReports || []))
    } else {
      // No scripts section in project - clear any stale data
      localStorage.setItem('nisystem-scripts', JSON.stringify([]))
      localStorage.setItem('nisystem-sequences', JSON.stringify([]))
      localStorage.setItem('nisystem-schedules', JSON.stringify([]))
      localStorage.setItem('nisystem-alarms', JSON.stringify([]))
      localStorage.setItem('nisystem-transformations', JSON.stringify([]))
      localStorage.setItem('nisystem-triggers', JSON.stringify([]))
      localStorage.setItem('nisystem-python-scripts', JSON.stringify([]))
      localStorage.setItem('dcflux-function-blocks', JSON.stringify([]))
      localStorage.setItem('dcflux-draw-patterns', JSON.stringify({ patterns: [], history: [] }))
      localStorage.setItem('dcflux-watchdogs', JSON.stringify([]))
      localStorage.setItem('dcflux-state-machines', JSON.stringify([]))
      localStorage.setItem('dcflux-report-templates', JSON.stringify([]))
      localStorage.setItem('dcflux-scheduled-reports', JSON.stringify([]))
    }

    // Apply recording settings - always write, even if empty, to clear stale data
    if (data.recording) {
      localStorage.setItem('nisystem-recording-config', JSON.stringify(data.recording.config || {}))
      localStorage.setItem('nisystem-recording-channels', JSON.stringify(data.recording.selectedChannels || []))
    } else {
      // No recording section in project - clear any stale data
      localStorage.setItem('nisystem-recording-config', JSON.stringify({}))
      localStorage.setItem('nisystem-recording-channels', JSON.stringify([]))
    }

    // Apply safety settings - always write, even if empty, to clear stale data
    if (data.safety) {
      // Save to both v1 and v2 keys for compatibility - always write, even if empty
      localStorage.setItem('nisystem-alarm-configs', JSON.stringify(data.safety.alarmConfigs || {}))
      localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify(data.safety.alarmConfigs || {}))
      localStorage.setItem('nisystem-interlocks', JSON.stringify(data.safety.interlocks || []))

      // Extended safety settings (v2.1+) - always write, even if empty
      localStorage.setItem('nisystem-safety-actions', JSON.stringify(data.safety.safetyActions || {}))
      localStorage.setItem('nisystem-safe-state-config', JSON.stringify(data.safety.safeStateConfig || {}))
      localStorage.setItem('nisystem-auto-execute-safety-actions', String(data.safety.autoExecuteSafetyActions || false))

      // IMPORTANT: Clear alarm history when loading new project to prevent ghost alarms
      // Alarm history is per-project and should not persist across projects
      localStorage.setItem('nisystem-alarm-history', JSON.stringify([]))
    } else {
      // No safety section in project - clear any stale data
      localStorage.setItem('nisystem-alarm-configs', JSON.stringify({}))
      localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify({}))
      localStorage.setItem('nisystem-interlocks', JSON.stringify([]))
      localStorage.setItem('nisystem-safety-actions', JSON.stringify({}))
      localStorage.setItem('nisystem-safe-state-config', JSON.stringify({}))
      localStorage.setItem('nisystem-auto-execute-safety-actions', 'false')
      localStorage.setItem('nisystem-alarm-history', JSON.stringify([]))
    }

    // Apply notebook data (v2.1+) - always write, even if empty, to clear stale data
    if (data.notebook) {
      localStorage.setItem('nisystem_notebook', JSON.stringify(data.notebook.entries || []))
      localStorage.setItem('nisystem_experiments', JSON.stringify(data.notebook.experiments || []))
    } else {
      // No notebook section in project - clear any stale data
      localStorage.setItem('nisystem_notebook', JSON.stringify([]))
      localStorage.setItem('nisystem_experiments', JSON.stringify([]))
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

    // Compare all sections that could have changes
    return JSON.stringify(current.layout) !== JSON.stringify(saved.layout) ||
           JSON.stringify(current.scripts) !== JSON.stringify(saved.scripts) ||
           JSON.stringify(current.recording) !== JSON.stringify(saved.recording) ||
           JSON.stringify(current.safety) !== JSON.stringify(saved.safety) ||
           JSON.stringify(current.notebook) !== JSON.stringify(saved.notebook)
  }

  // Create new project (clear current state)
  async function newProject() {
    console.log('[PROJECT] Starting fresh - clearing all state...')

    // Stop acquisition if running (backend needs to be stopped before clearing channels)
    if (store.isAcquiring) {
      console.log('[PROJECT] Stopping acquisition...')
      mqtt.stopAcquisition()
      await new Promise(resolve => setTimeout(resolve, 500))
    }

    currentProject.value = null
    currentProjectData.value = null

    // Clear ALL pages and widgets (not just current page)
    console.log('[PROJECT] Clearing pages and widgets...')
    store.pages.forEach(page => page.widgets = [])

    // Clear channels from frontend (this triggers alarm clearing via useSafety watcher)
    console.log('[PROJECT] Clearing channels...')
    store.setChannels({})

    // Clear ALL safety state (alarms, history, configs, interlocks, safety actions)
    // This ensures no ghost values persist in the safety system
    console.log('[PROJECT] Clearing all safety state...')
    safety.clearAllSafetyState('new_project')

    // Clear layout from localStorage to prevent stale data
    const layoutKey = `nisystem-layout-${store.systemId}`
    localStorage.removeItem(layoutKey)
    console.log('[PROJECT] Cleared layout from localStorage')

    // Clear localStorage items - core scripts
    localStorage.removeItem('nisystem-scripts')
    localStorage.removeItem('nisystem-sequences')
    localStorage.removeItem('nisystem-schedules')
    localStorage.removeItem('nisystem-alarms')
    localStorage.removeItem('nisystem-transformations')
    localStorage.removeItem('nisystem-triggers')

    // Clear extended script types (v2.1+)
    localStorage.removeItem('nisystem-python-scripts')
    localStorage.removeItem('dcflux-function-blocks')
    localStorage.removeItem('dcflux-draw-patterns')
    localStorage.removeItem('dcflux-watchdogs')
    localStorage.removeItem('dcflux-state-machines')
    localStorage.removeItem('dcflux-report-templates')
    localStorage.removeItem('dcflux-scheduled-reports')

    // Clear recording settings
    localStorage.removeItem('nisystem-recording-config')
    localStorage.removeItem('nisystem-recording-channels')

    // Clear safety settings
    localStorage.removeItem('nisystem-alarm-configs')
    localStorage.removeItem('nisystem-alarm-configs-v2')
    localStorage.removeItem('nisystem-alarm-history')
    localStorage.removeItem('nisystem-interlocks')
    localStorage.removeItem('nisystem-safety-actions')
    localStorage.removeItem('nisystem-safe-state-config')
    localStorage.removeItem('nisystem-auto-execute-safety-actions')

    // Clear notebook data
    localStorage.removeItem('nisystem_notebook')
    localStorage.removeItem('nisystem_experiments')

    // Ensure we have at least one empty page
    console.log('[PROJECT] Ensuring default page...')
    store.ensureDefaultPage()

    // Clear all channel values to show "--" in widgets
    console.log('[PROJECT] Clearing channel values...')
    store.clearValues()

    console.log('[PROJECT] ✅ Clean slate ready - all state cleared')
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
