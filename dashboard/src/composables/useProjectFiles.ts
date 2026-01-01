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

export interface ProjectData {
  type: 'nisystem-project'
  version: string
  name: string
  config: string
  created: string
  modified: string
  layout: {
    widgets: any[]
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
      if (payload.success && payload.project) {
        currentProject.value = payload.filename
        currentProjectData.value = payload.project

        // Apply project data to frontend
        applyProjectData(payload.project)

        // Notify callbacks
        projectLoadedCallbacks.forEach(cb => cb(payload.project))
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
      currentProject.value = payload.filename
      currentProjectData.value = payload.project
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

  // Apply loaded project data to frontend
  function applyProjectData(data: ProjectData) {
    // Apply layout
    if (data.layout) {
      store.setLayout({
        system_id: store.systemId,
        widgets: data.layout.widgets || [],
        gridColumns: data.layout.gridColumns || 12,
        rowHeight: data.layout.rowHeight || 80
      })
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
