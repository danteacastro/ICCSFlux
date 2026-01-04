import { ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'

/**
 * Project File Structure (v2)
 *
 * The project file (JSON) contains ONLY frontend/dashboard state.
 * Hardware configuration (cDAQ, Modbus) stays in the INI file.
 *
 * Structure:
 * - configFile: Reference to the INI file to use (e.g., "system.ini")
 * - All dashboard state: layouts, scripts, recording, safety, variables
 */
export interface ProjectFile {
  version: string
  type: 'nisystem-project'
  name: string
  description?: string
  createdAt: string
  modifiedAt: string

  // Reference to hardware config (INI file in config/ directory)
  configFile: string  // e.g., "system.ini"

  // Dashboard layout (multi-page support)
  layout: {
    pages: any[]
    currentPageId: string
    gridColumns: number
    rowHeight: number
  }

  // Scripts and automation
  scripts: {
    calculatedParams: any[]
    sequences: any[]
    schedules: any[]
    triggers: any[]
    transformations: any[]
    functionBlocks: any[]
    drawPatterns: any
    stateMachines: any[]
    watchdogs: any[]
    reportTemplates: any[]
    scheduledReports: any[]
    pythonScripts: any[]  // Pyodide-based Python scripts
  }

  // Recording configuration
  recording: {
    config: {
      basePath?: string
      filenamePattern?: string
      writeMode?: string
      sampleInterval?: number
      sampleIntervalUnit?: string
      rotationMode?: string
      maxFileSizeMb?: number
      maxFileSamples?: number
      onLimitReached?: string
      directoryStructure?: string
      experimentName?: string
    }
    selectedChannels: string[]
  }

  // Safety configuration (alarms defined in dashboard, not INI)
  safety: {
    alarmConfigs: any
    interlocks: any[]
    alarms: any[]  // Legacy alarms from useScripts
  }
}

// Legacy format for backwards compatibility
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
      pages?: any[]
      currentPageId?: string
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
const currentConfigFile = ref('system.ini')

export function useProjectManager() {
  const store = useDashboardStore()
  const mqtt = useMqtt()

  // ============================================================================
  // HELPER: Storage keys for all localStorage data
  // ============================================================================

  const STORAGE_KEYS = {
    // Layout
    LAYOUT: (systemId: string) => `nisystem-layout-${systemId}`,

    // Scripts
    CALCULATED_PARAMS: 'nisystem-scripts',
    SEQUENCES: 'nisystem-sequences',
    SCHEDULES: 'nisystem-schedules',
    TRIGGERS: 'nisystem-triggers',
    TRANSFORMATIONS: 'nisystem-transformations',
    FUNCTION_BLOCKS: 'nisystem-function-blocks',
    DRAW_PATTERNS: 'nisystem-draw-patterns',

    // Extended scripts (dcflux prefix for backwards compat)
    STATE_MACHINES: 'dcflux-state-machines',
    WATCHDOGS: 'dcflux-watchdogs',
    REPORT_TEMPLATES: 'dcflux-report-templates',
    SCHEDULED_REPORTS: 'dcflux-scheduled-reports',

    // Python scripts
    PYTHON_SCRIPTS: 'nisystem-python-scripts',

    // Recording
    RECORDING_CONFIG: 'nisystem-recording-config',
    RECORDING_CHANNELS: 'nisystem-recording-channels',

    // Safety
    ALARM_CONFIGS: 'nisystem-alarm-configs',
    ALARM_CONFIGS_V2: 'nisystem-alarm-configs-v2',
    INTERLOCKS: 'nisystem-interlocks',
    ALARMS: 'nisystem-alarms',  // Legacy alarms from useScripts
  }

  function safeParseJSON(value: string | null, fallback: any): any {
    if (!value) return fallback
    try {
      return JSON.parse(value)
    } catch {
      return fallback
    }
  }

  // ============================================================================
  // COLLECT ALL FRONTEND STATE (new ProjectFile format)
  // ============================================================================

  function collectAllState(): Omit<ProjectFile, 'version' | 'type' | 'name' | 'description' | 'createdAt' | 'modifiedAt' | 'configFile'> {
    const layout = store.getLayout()

    return {
      layout: {
        pages: layout.pages || [],
        currentPageId: layout.currentPageId || 'default',
        gridColumns: layout.gridColumns || 24,
        rowHeight: layout.rowHeight || 30
      },

      scripts: {
        calculatedParams: safeParseJSON(localStorage.getItem(STORAGE_KEYS.CALCULATED_PARAMS), []),
        sequences: safeParseJSON(localStorage.getItem(STORAGE_KEYS.SEQUENCES), []),
        schedules: safeParseJSON(localStorage.getItem(STORAGE_KEYS.SCHEDULES), []),
        triggers: safeParseJSON(localStorage.getItem(STORAGE_KEYS.TRIGGERS), []),
        transformations: safeParseJSON(localStorage.getItem(STORAGE_KEYS.TRANSFORMATIONS), []),
        functionBlocks: safeParseJSON(localStorage.getItem(STORAGE_KEYS.FUNCTION_BLOCKS), []),
        drawPatterns: safeParseJSON(localStorage.getItem(STORAGE_KEYS.DRAW_PATTERNS), { patterns: [], history: [] }),
        stateMachines: safeParseJSON(localStorage.getItem(STORAGE_KEYS.STATE_MACHINES), []),
        watchdogs: safeParseJSON(localStorage.getItem(STORAGE_KEYS.WATCHDOGS), []),
        reportTemplates: safeParseJSON(localStorage.getItem(STORAGE_KEYS.REPORT_TEMPLATES), []),
        scheduledReports: safeParseJSON(localStorage.getItem(STORAGE_KEYS.SCHEDULED_REPORTS), []),
        pythonScripts: safeParseJSON(localStorage.getItem(STORAGE_KEYS.PYTHON_SCRIPTS), [])
      },

      recording: {
        config: safeParseJSON(localStorage.getItem(STORAGE_KEYS.RECORDING_CONFIG), {}),
        selectedChannels: safeParseJSON(localStorage.getItem(STORAGE_KEYS.RECORDING_CHANNELS), [])
      },

      safety: {
        // Try v2 first, fall back to v1
        alarmConfigs: safeParseJSON(
          localStorage.getItem(STORAGE_KEYS.ALARM_CONFIGS_V2) ||
          localStorage.getItem(STORAGE_KEYS.ALARM_CONFIGS),
          {}
        ),
        interlocks: safeParseJSON(localStorage.getItem(STORAGE_KEYS.INTERLOCKS), []),
        alarms: safeParseJSON(localStorage.getItem(STORAGE_KEYS.ALARMS), [])
      }
    }
  }

  // ============================================================================
  // APPLY ALL FRONTEND STATE
  // ============================================================================

  function applyAllState(data: Omit<ProjectFile, 'version' | 'type' | 'name' | 'description' | 'createdAt' | 'modifiedAt' | 'configFile'>) {
    // Layout
    if (data.layout) {
      store.setLayout({
        system_id: store.systemId || 'default',
        widgets: [],  // Legacy field
        pages: data.layout.pages || [],
        currentPageId: data.layout.currentPageId || 'default',
        gridColumns: data.layout.gridColumns || 24,
        rowHeight: data.layout.rowHeight || 30
      })
      store.saveLayoutToStorage()
    }

    // Scripts
    if (data.scripts) {
      if (data.scripts.calculatedParams) {
        localStorage.setItem(STORAGE_KEYS.CALCULATED_PARAMS, JSON.stringify(data.scripts.calculatedParams))
      }
      if (data.scripts.sequences) {
        localStorage.setItem(STORAGE_KEYS.SEQUENCES, JSON.stringify(data.scripts.sequences))
      }
      if (data.scripts.schedules) {
        localStorage.setItem(STORAGE_KEYS.SCHEDULES, JSON.stringify(data.scripts.schedules))
      }
      if (data.scripts.triggers) {
        localStorage.setItem(STORAGE_KEYS.TRIGGERS, JSON.stringify(data.scripts.triggers))
      }
      if (data.scripts.transformations) {
        localStorage.setItem(STORAGE_KEYS.TRANSFORMATIONS, JSON.stringify(data.scripts.transformations))
      }
      if (data.scripts.functionBlocks) {
        localStorage.setItem(STORAGE_KEYS.FUNCTION_BLOCKS, JSON.stringify(data.scripts.functionBlocks))
      }
      if (data.scripts.drawPatterns) {
        localStorage.setItem(STORAGE_KEYS.DRAW_PATTERNS, JSON.stringify(data.scripts.drawPatterns))
      }
      if (data.scripts.stateMachines) {
        localStorage.setItem(STORAGE_KEYS.STATE_MACHINES, JSON.stringify(data.scripts.stateMachines))
      }
      if (data.scripts.watchdogs) {
        localStorage.setItem(STORAGE_KEYS.WATCHDOGS, JSON.stringify(data.scripts.watchdogs))
      }
      if (data.scripts.reportTemplates) {
        localStorage.setItem(STORAGE_KEYS.REPORT_TEMPLATES, JSON.stringify(data.scripts.reportTemplates))
      }
      if (data.scripts.scheduledReports) {
        localStorage.setItem(STORAGE_KEYS.SCHEDULED_REPORTS, JSON.stringify(data.scripts.scheduledReports))
      }
      if (data.scripts.pythonScripts) {
        localStorage.setItem(STORAGE_KEYS.PYTHON_SCRIPTS, JSON.stringify(data.scripts.pythonScripts))
      }
    }

    // Recording
    if (data.recording) {
      if (data.recording.config) {
        localStorage.setItem(STORAGE_KEYS.RECORDING_CONFIG, JSON.stringify(data.recording.config))
      }
      if (data.recording.selectedChannels) {
        localStorage.setItem(STORAGE_KEYS.RECORDING_CHANNELS, JSON.stringify(data.recording.selectedChannels))
      }
    }

    // Safety
    if (data.safety) {
      if (data.safety.alarmConfigs) {
        // Save to v2 format
        localStorage.setItem(STORAGE_KEYS.ALARM_CONFIGS_V2, JSON.stringify(data.safety.alarmConfigs))
      }
      if (data.safety.interlocks) {
        localStorage.setItem(STORAGE_KEYS.INTERLOCKS, JSON.stringify(data.safety.interlocks))
      }
      if (data.safety.alarms) {
        localStorage.setItem(STORAGE_KEYS.ALARMS, JSON.stringify(data.safety.alarms))
      }
    }
  }

  // ============================================================================
  // CREATE NEW PROJECT FILE (v2 format)
  // ============================================================================

  function createProjectFile(name?: string, description?: string): ProjectFile {
    const state = collectAllState()
    const now = new Date().toISOString()

    return {
      version: '2.0',
      type: 'nisystem-project',
      name: name || store.systemName || 'NISystem Project',
      description: description || '',
      createdAt: now,
      modifiedAt: now,
      configFile: currentConfigFile.value,
      ...state
    }
  }

  // ============================================================================
  // EXPORT / DOWNLOAD
  // ============================================================================

  async function downloadProject(name?: string, description?: string) {
    try {
      const project = createProjectFile(name, description)

      const blob = new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)

      const a = document.createElement('a')
      a.href = url
      const timestamp = new Date().toISOString().slice(0, 10)
      const safeName = (project.name || 'project').replace(/[^a-zA-Z0-9_-]/g, '_')
      a.download = `${safeName}_${timestamp}.nisystem.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      return { success: true, message: 'Project exported successfully' }
    } catch (error: any) {
      return { success: false, message: error.message || 'Export failed' }
    }
  }

  // ============================================================================
  // IMPORT / LOAD
  // ============================================================================

  function isProjectFileV2(data: any): data is ProjectFile {
    // V2 projects either have configFile (legacy) or embedded channels (new format)
    return data &&
           data.type === 'nisystem-project' &&
           data.version?.startsWith('2') &&
           (data.configFile !== undefined || data.channels !== undefined)
  }

  function isLegacyBundle(data: any): data is ProjectBundle {
    return data &&
           data.type === 'nisystem-project' &&
           data.backend !== undefined &&
           data.frontend !== undefined
  }

  function migrateLegacyBundle(bundle: ProjectBundle): ProjectFile {
    const now = new Date().toISOString()

    // Convert legacy layout to new format
    const pages = bundle.frontend.layout.pages || [{
      id: 'default',
      name: 'Page 1',
      widgets: bundle.frontend.layout.widgets || [],
      order: 0
    }]

    return {
      version: '2.0',
      type: 'nisystem-project',
      name: bundle.name,
      description: 'Migrated from legacy format',
      createdAt: bundle.exportedAt || now,
      modifiedAt: now,
      configFile: 'system.ini',  // Default

      layout: {
        pages,
        currentPageId: bundle.frontend.layout.currentPageId || 'default',
        gridColumns: bundle.frontend.layout.gridColumns || 24,
        rowHeight: bundle.frontend.layout.rowHeight || 30
      },

      scripts: {
        calculatedParams: bundle.frontend.scripts.calculatedParams || [],
        sequences: bundle.frontend.scripts.sequences || [],
        schedules: bundle.frontend.scripts.schedules || [],
        triggers: bundle.frontend.scripts.triggers || [],
        transformations: bundle.frontend.scripts.transformations || [],
        functionBlocks: [],
        drawPatterns: { patterns: [], history: [] },
        stateMachines: [],
        watchdogs: [],
        reportTemplates: [],
        scheduledReports: [],
        pythonScripts: []
      },

      recording: {
        config: bundle.frontend.recording.config || {},
        selectedChannels: bundle.frontend.recording.selectedChannels || []
      },

      safety: {
        alarmConfigs: bundle.frontend.safety.alarmConfigs || {},
        interlocks: bundle.frontend.safety.interlocks || [],
        alarms: bundle.frontend.scripts.alarms || []
      }
    }
  }

  async function importProject(data: any): Promise<{ success: boolean; message: string }> {
    try {
      let project: ProjectFile

      if (isProjectFileV2(data)) {
        project = data

        // For V2 projects with embedded channels, send to backend
        if (mqtt.connected.value && data.channels) {
          // Send the full project for backend to apply channels/system config
          mqtt.sendCommand('project/import/json', data)
        }
      } else if (isLegacyBundle(data)) {
        project = migrateLegacyBundle(data)

        // For legacy bundles, also send backend config via MQTT
        if (mqtt.connected.value && data.backend) {
          mqtt.sendCommand('config/load/full', data.backend)
        }
      } else {
        return { success: false, message: 'Invalid project file format' }
      }

      // Update current config file reference
      currentConfigFile.value = project.configFile || 'system.ini'

      // Apply all frontend state
      applyAllState(project)

      // Reload page to apply all changes cleanly
      setTimeout(() => {
        window.location.reload()
      }, 500)

      return { success: true, message: `Project "${project.name}" imported successfully. Reloading...` }
    } catch (error: any) {
      return { success: false, message: error.message || 'Import failed' }
    }
  }

  async function loadProjectFromFile(file: File): Promise<{ success: boolean; message: string }> {
    return new Promise((resolve) => {
      const reader = new FileReader()

      reader.onload = async (e) => {
        try {
          const content = e.target?.result as string
          const data = JSON.parse(content)
          const result = await importProject(data)
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

  // ============================================================================
  // LEGACY SUPPORT: Export with backend config (for full system backup)
  // ============================================================================

  function requestBackendConfig(): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!mqtt.connected.value) {
        reject(new Error('Not connected to MQTT'))
        return
      }

      pendingConfigRequest.value = true

      const timeout = setTimeout(() => {
        pendingConfigRequest.value = false
        reject(new Error('Config request timed out'))
      }, 5000)

      const unsubscribe = mqtt.onConfigCurrent((config: any) => {
        clearTimeout(timeout)
        pendingConfigRequest.value = false
        unsubscribe()
        resolve(config)
      })

      mqtt.sendCommand('config/get')
    })
  }

  async function exportFullBackup(name?: string): Promise<ProjectBundle> {
    const backendConfig = await requestBackendConfig()
    const frontendState = collectAllState()

    // Convert new format to legacy format for full backup
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
      frontend: {
        layout: {
          widgets: frontendState.layout.pages?.[0]?.widgets || [],
          pages: frontendState.layout.pages,
          currentPageId: frontendState.layout.currentPageId,
          gridColumns: frontendState.layout.gridColumns,
          rowHeight: frontendState.layout.rowHeight
        },
        scripts: {
          calculatedParams: frontendState.scripts.calculatedParams,
          sequences: frontendState.scripts.sequences,
          schedules: frontendState.scripts.schedules,
          alarms: frontendState.safety.alarms,
          transformations: frontendState.scripts.transformations,
          triggers: frontendState.scripts.triggers
        },
        recording: frontendState.recording,
        safety: {
          alarmConfigs: Array.isArray(frontendState.safety.alarmConfigs)
            ? frontendState.safety.alarmConfigs
            : Object.values(frontendState.safety.alarmConfigs || {}),
          interlocks: frontendState.safety.interlocks
        }
      }
    }

    return bundle
  }

  async function downloadFullBackup(name?: string) {
    try {
      const bundle = await exportFullBackup(name)

      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)

      const a = document.createElement('a')
      a.href = url
      const timestamp = new Date().toISOString().slice(0, 10)
      const safeName = (bundle.name || 'backup').replace(/[^a-zA-Z0-9_-]/g, '_')
      a.download = `${safeName}_full_backup_${timestamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      return { success: true, message: 'Full backup exported successfully' }
    } catch (error: any) {
      return { success: false, message: error.message || 'Export failed' }
    }
  }

  // ============================================================================
  // CONFIG FILE MANAGEMENT
  // ============================================================================

  function setConfigFile(filename: string) {
    currentConfigFile.value = filename
  }

  function getConfigFile() {
    return currentConfigFile.value
  }

  return {
    // New v2 API
    createProjectFile,
    downloadProject,
    importProject,
    loadProjectFromFile,

    // Config file reference
    currentConfigFile,
    setConfigFile,
    getConfigFile,

    // Legacy / Full backup
    exportFullBackup,
    downloadFullBackup,
    requestBackendConfig,
    pendingConfigRequest,

    // Collect/apply state (for external use)
    collectAllState,
    applyAllState
  }
}
