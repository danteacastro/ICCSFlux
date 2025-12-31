import { ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'

// Project file structure
export interface ProjectBundle {
  version: string
  type: 'nisystem-project'
  name: string
  exportedAt: string
  backend: {
    system: Record<string, any>
    channels: Record<string, any>
    modules: Record<string, any>
    chassis: Record<string, any>
    safety_actions?: any[]
  }
  frontend: {
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
}

// State for pending config request
const pendingConfigRequest = ref(false)

export function useProjectManager() {
  const store = useDashboardStore()
  const mqtt = useMqtt()

  // Request backend config and wait for response
  function requestBackendConfig(): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!mqtt.connected.value) {
        reject(new Error('Not connected to MQTT'))
        return
      }

      pendingConfigRequest.value = true

      // Set timeout
      const timeout = setTimeout(() => {
        pendingConfigRequest.value = false
        reject(new Error('Config request timed out'))
      }, 5000)

      // Listen for config response
      const unsubscribe = mqtt.onConfigCurrent((config: any) => {
        clearTimeout(timeout)
        pendingConfigRequest.value = false
        unsubscribe()
        resolve(config)
      })

      // Request config
      mqtt.sendCommand('config/get')
    })
  }

  // Collect all frontend state
  function collectFrontendState(): ProjectBundle['frontend'] {
    // Get layout from store
    const layout = store.getLayout()

    // Get scripts from localStorage (same as useScripts does)
    const calculatedParams = JSON.parse(localStorage.getItem('nisystem-scripts') || '[]')
    const sequences = JSON.parse(localStorage.getItem('nisystem-sequences') || '[]')
    const schedules = JSON.parse(localStorage.getItem('nisystem-schedules') || '[]')
    const alarms = JSON.parse(localStorage.getItem('nisystem-alarms') || '[]')
    const transformations = JSON.parse(localStorage.getItem('nisystem-transformations') || '[]')
    const triggers = JSON.parse(localStorage.getItem('nisystem-triggers') || '[]')

    // Get recording config
    const recordingConfig = JSON.parse(localStorage.getItem('nisystem-recording-config') || '{}')
    const selectedChannels = JSON.parse(localStorage.getItem('nisystem-recording-channels') || '[]')

    // Get safety config
    const alarmConfigs = JSON.parse(localStorage.getItem('nisystem-alarm-configs') || '[]')
    const interlocks = JSON.parse(localStorage.getItem('nisystem-interlocks') || '[]')

    return {
      layout: {
        widgets: layout.widgets || [],
        gridColumns: layout.gridColumns || 12,
        rowHeight: layout.rowHeight || 80
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

  // Export complete project bundle
  async function exportProject(name?: string): Promise<ProjectBundle> {
    // Get backend config
    const backendConfig = await requestBackendConfig()

    // Get frontend state
    const frontendState = collectFrontendState()

    const bundle: ProjectBundle = {
      version: '1.0',
      type: 'nisystem-project',
      name: name || store.systemName || 'NISystem Project',
      exportedAt: new Date().toISOString(),
      backend: {
        system: backendConfig.system || {},
        channels: backendConfig.channels || {},
        modules: backendConfig.modules || {},
        chassis: backendConfig.chassis || {},
        safety_actions: backendConfig.safety_actions || []
      },
      frontend: frontendState
    }

    return bundle
  }

  // Download project as JSON file
  async function downloadProject(name?: string) {
    try {
      const bundle = await exportProject(name)

      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)

      const a = document.createElement('a')
      a.href = url
      const timestamp = new Date().toISOString().slice(0, 10)
      const safeName = (bundle.name || 'project').replace(/[^a-zA-Z0-9_-]/g, '_')
      a.download = `${safeName}_${timestamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      return { success: true, message: 'Project exported successfully' }
    } catch (error: any) {
      return { success: false, message: error.message || 'Export failed' }
    }
  }

  // Validate project bundle structure
  function validateBundle(data: any): data is ProjectBundle {
    if (!data || typeof data !== 'object') return false
    if (data.type !== 'nisystem-project') return false
    if (!data.version) return false
    if (!data.backend || !data.frontend) return false
    return true
  }

  // Import project from bundle
  async function importProject(bundle: ProjectBundle): Promise<{ success: boolean; message: string }> {
    try {
      if (!validateBundle(bundle)) {
        return { success: false, message: 'Invalid project file format' }
      }

      // 1. Send backend config via MQTT
      if (mqtt.connected.value && bundle.backend) {
        // Send full config to backend for loading
        mqtt.sendCommand('config/load/full', bundle.backend)
      }

      // 2. Apply frontend layout
      if (bundle.frontend.layout) {
        store.setLayout({
          system_id: store.systemId || 'default',
          widgets: bundle.frontend.layout.widgets || [],
          gridColumns: bundle.frontend.layout.gridColumns || 12,
          rowHeight: bundle.frontend.layout.rowHeight || 80
        })
        store.saveLayoutToStorage()
      }

      // 3. Apply scripts
      if (bundle.frontend.scripts) {
        const { calculatedParams, sequences, schedules, alarms, transformations, triggers } = bundle.frontend.scripts

        if (calculatedParams) {
          localStorage.setItem('nisystem-scripts', JSON.stringify(calculatedParams))
        }
        if (sequences) {
          localStorage.setItem('nisystem-sequences', JSON.stringify(sequences))
        }
        if (schedules) {
          localStorage.setItem('nisystem-schedules', JSON.stringify(schedules))
        }
        if (alarms) {
          localStorage.setItem('nisystem-alarms', JSON.stringify(alarms))
        }
        if (transformations) {
          localStorage.setItem('nisystem-transformations', JSON.stringify(transformations))
        }
        if (triggers) {
          localStorage.setItem('nisystem-triggers', JSON.stringify(triggers))
        }
      }

      // 4. Apply recording config
      if (bundle.frontend.recording) {
        if (bundle.frontend.recording.config) {
          localStorage.setItem('nisystem-recording-config', JSON.stringify(bundle.frontend.recording.config))
        }
        if (bundle.frontend.recording.selectedChannels) {
          localStorage.setItem('nisystem-recording-channels', JSON.stringify(bundle.frontend.recording.selectedChannels))
        }
      }

      // 5. Apply safety config
      if (bundle.frontend.safety) {
        if (bundle.frontend.safety.alarmConfigs) {
          localStorage.setItem('nisystem-alarm-configs', JSON.stringify(bundle.frontend.safety.alarmConfigs))
        }
        if (bundle.frontend.safety.interlocks) {
          localStorage.setItem('nisystem-interlocks', JSON.stringify(bundle.frontend.safety.interlocks))
        }
      }

      // Reload page to apply all changes cleanly
      setTimeout(() => {
        window.location.reload()
      }, 500)

      return { success: true, message: `Project "${bundle.name}" imported successfully. Reloading...` }
    } catch (error: any) {
      return { success: false, message: error.message || 'Import failed' }
    }
  }

  // Load project from file
  async function loadProjectFromFile(file: File): Promise<{ success: boolean; message: string }> {
    return new Promise((resolve) => {
      const reader = new FileReader()

      reader.onload = async (e) => {
        try {
          const content = e.target?.result as string
          const bundle = JSON.parse(content)
          const result = await importProject(bundle)
          resolve(result)
        } catch (error: any) {
          resolve({ success: false, message: 'Failed to parse project file' })
        }
      }

      reader.onerror = () => {
        resolve({ success: false, message: 'Failed to read file' })
      }

      reader.readAsText(file)
    })
  }

  return {
    exportProject,
    downloadProject,
    importProject,
    loadProjectFromFile,
    pendingConfigRequest
  }
}
