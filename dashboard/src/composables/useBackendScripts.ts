/**
 * Backend Scripts Composable
 *
 * Manages Python script execution on the BACKEND (DAQ service).
 * Scripts run in isolated Python threads server-side, NOT in the browser.
 *
 * This ensures scripts continue running even when the browser is closed,
 * which is critical for industrial automation and safety.
 *
 * Architecture:
 * - Frontend sends scripts to backend via MQTT (script/add, script/update, etc.)
 * - Backend ScriptManager executes scripts in Python threads
 * - Scripts have access to tags, outputs, session control
 * - Auto-start with acquisition or session based on runMode
 *
 * MQTT Topics (relative to base):
 * - script/add - Add/update a script
 * - script/update - Update script code/settings
 * - script/remove - Delete a script
 * - script/start - Start a script
 * - script/stop - Stop a script
 * - script/list - Request script list
 * - script/status - Backend publishes script status (subscribe)
 * - script/response - Backend responses to commands (subscribe)
 * - script/output - Script console output (subscribe)
 */

import { ref, computed, readonly, watch } from 'vue'
import { useMqtt } from './useMqtt'

// =============================================================================
// TYPES
// =============================================================================

export type ScriptRunMode = 'manual' | 'acquisition' | 'session'
export type ScriptState = 'idle' | 'running' | 'stopping' | 'error'

export interface BackendScript {
  id: string
  name: string
  code: string
  description: string
  enabled: boolean
  runMode: ScriptRunMode
  createdAt: string
  modifiedAt: string
  // Runtime state (from backend)
  state: ScriptState
  startedAt: number | null
  iterations: number
  errorMessage: string | null
}

export interface ScriptOutput {
  scriptId: string
  type: 'info' | 'warning' | 'error' | 'stdout'
  message: string
  timestamp: number
  lineNumber?: number
}

export interface ScriptResponse {
  action: string
  success: boolean
  script_id?: string
  error?: string
}

export interface ScriptStatus {
  timestamp: number
  scripts: Array<{
    id: string
    name: string
    run_mode: string
    enabled: boolean
    state: string
    error: string | null
    started_at: number | null
    iterations: number
  }>
}

// =============================================================================
// SINGLETON STATE
// =============================================================================

const scripts = ref<Record<string, BackendScript>>({})
const scriptOutputs = ref<Record<string, ScriptOutput[]>>({})
const isLoading = ref(false)
const lastError = ref<string | null>(null)
let handlersInitialized = false

// =============================================================================
// COMPOSABLE
// =============================================================================

export function useBackendScripts() {
  const mqtt = useMqtt()

  // Initialize MQTT handlers once when connected
  if (!handlersInitialized && mqtt.connected.value) {
    initializeHandlers()
  }

  // Watch for connection to initialize handlers if not already done
  watch(mqtt.connected, (connected) => {
    if (connected && !handlersInitialized) {
      initializeHandlers()
    }
  })

  function initializeHandlers() {
    if (handlersInitialized) return
    handlersInitialized = true

    const prefix = 'nisystem/nodes/+' // Subscribe to all nodes

    // Subscribe to script topics
    mqtt.subscribe(`${prefix}/script/status`, handleScriptStatus)
    mqtt.subscribe(`${prefix}/script/response`, handleScriptResponse)
    mqtt.subscribe(`${prefix}/script/output`, handleScriptOutput)

    // Request initial script list
    requestScriptList()
  }

  // ===========================================================================
  // MQTT HANDLERS
  // ===========================================================================

  function handleScriptStatus(data: ScriptStatus) {
    if (!data || !Array.isArray(data.scripts)) return

    // Build set of current script IDs from backend
    const backendIds = new Set<string>()

    // Update scripts from backend (array format)
    for (const scriptData of data.scripts) {
      if (scriptData.id) {
        backendIds.add(scriptData.id)
        scripts.value[scriptData.id] = normalizeScript(scriptData)
      }
    }

    // Remove scripts that are no longer in backend
    for (const id of Object.keys(scripts.value)) {
      if (!backendIds.has(id)) {
        delete scripts.value[id]
      }
    }
  }

  function handleScriptResponse(data: ScriptResponse) {
    if (!data) return

    if (!data.success && data.error) {
      lastError.value = data.error
      console.error(`Script ${data.action} failed:`, data.error)
    } else {
      lastError.value = null
    }

    // Refresh script list after any change
    if (data.success) {
      requestScriptList()
    }
  }

  function handleScriptOutput(data: { script_id: string; type: string; message: string }) {
    if (!data || !data.script_id) return

    const output: ScriptOutput = {
      scriptId: data.script_id,
      type: data.type as ScriptOutput['type'],
      message: data.message,
      timestamp: Date.now()
    }

    if (!scriptOutputs.value[data.script_id]) {
      scriptOutputs.value[data.script_id] = []
    }

    scriptOutputs.value[data.script_id]!.push(output)

    // Limit output history
    if (scriptOutputs.value[data.script_id]!.length > 1000) {
      scriptOutputs.value[data.script_id] = scriptOutputs.value[data.script_id]!.slice(-500)
    }
  }

  function normalizeScript(data: any): BackendScript {
    return {
      id: data.id || '',
      name: data.name || 'Untitled',
      code: data.code || '',
      description: data.description || '',
      enabled: data.enabled !== false,
      runMode: data.runMode || data.run_mode || 'manual',
      createdAt: data.createdAt || data.created_at || '',
      modifiedAt: data.modifiedAt || data.modified_at || '',
      state: data.state || 'idle',
      startedAt: data.startedAt || data.started_at || null,
      iterations: data.iterations || 0,
      errorMessage: data.errorMessage || data.error_message || null
    }
  }

  // ===========================================================================
  // SCRIPT CRUD (send to backend)
  // ===========================================================================

  function addScript(script: {
    id?: string  // Allow passing existing ID to preserve identity
    name: string
    code: string
    description?: string
    runMode?: ScriptRunMode
    enabled?: boolean
  }): string {
    // Use provided ID or generate new one
    const id = script.id || `script_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`

    mqtt.sendLocalCommand('script/add', {
      id,
      name: script.name,
      code: script.code,
      description: script.description || '',
      run_mode: script.runMode || 'manual',
      enabled: script.enabled !== false
    })

    return id
  }

  function updateScript(id: string, updates: Partial<{
    name: string
    code: string
    description: string
    runMode: ScriptRunMode
    enabled: boolean
  }>) {
    const payload: any = { id }

    if (updates.name !== undefined) payload.name = updates.name
    if (updates.code !== undefined) payload.code = updates.code
    if (updates.description !== undefined) payload.description = updates.description
    if (updates.runMode !== undefined) payload.run_mode = updates.runMode
    if (updates.enabled !== undefined) payload.enabled = updates.enabled

    mqtt.sendLocalCommand('script/update', payload)
  }

  function removeScript(id: string) {
    mqtt.sendLocalCommand('script/remove', { id })

    // Clear local output
    delete scriptOutputs.value[id]
  }

  // ===========================================================================
  // SCRIPT EXECUTION (send to backend)
  // ===========================================================================

  function startScript(id: string) {
    mqtt.sendLocalCommand('script/start', { id })
  }

  function stopScript(id: string) {
    mqtt.sendLocalCommand('script/stop', { id })
  }

  function stopAllScripts() {
    for (const id of Object.keys(scripts.value)) {
      if (scripts.value[id]?.state === 'running') {
        stopScript(id)
      }
    }
  }

  function clearAllScripts() {
    // Send clear-all command to backend - this ensures ALL scripts are cleared
    // even if frontend state is stale or empty (e.g., after page refresh)
    mqtt.sendLocalCommand('script/clear-all', {})

    // Clear local state immediately
    scripts.value = {}
    scriptOutputs.value = {}
  }

  // ===========================================================================
  // QUERIES
  // ===========================================================================

  function requestScriptList() {
    if (!mqtt.connected.value) return
    mqtt.sendLocalCommand('script/list', {})
  }

  function getScript(id: string): BackendScript | undefined {
    return scripts.value[id]
  }

  function getScriptOutputs(id: string): ScriptOutput[] {
    return scriptOutputs.value[id] || []
  }

  function clearScriptOutput(id: string) {
    scriptOutputs.value[id] = []
  }

  // ===========================================================================
  // COMPUTED
  // ===========================================================================

  const scriptsList = computed(() => Object.values(scripts.value))

  const runningScripts = computed(() =>
    Object.values(scripts.value).filter(s => s.state === 'running')
  )

  const runningScriptIds = computed(() =>
    new Set(runningScripts.value.map(s => s.id))
  )

  const scriptCount = computed(() => Object.keys(scripts.value).length)
  const runningCount = computed(() => runningScripts.value.length)

  // Scripts by run mode
  const acquisitionScripts = computed(() =>
    scriptsList.value.filter(s => s.enabled && s.runMode === 'acquisition')
  )

  const sessionScripts = computed(() =>
    scriptsList.value.filter(s => s.enabled && s.runMode === 'session')
  )

  const manualScripts = computed(() =>
    scriptsList.value.filter(s => s.runMode === 'manual')
  )

  // ===========================================================================
  // INITIALIZATION
  // ===========================================================================

  // Re-initialize when MQTT connects
  if (mqtt.connected.value && !handlersInitialized) {
    initializeHandlers()
  }

  // ===========================================================================
  // RETURN
  // ===========================================================================

  return {
    // State
    scripts: readonly(scripts),
    scriptsList,
    scriptOutputs: readonly(scriptOutputs),
    isLoading: readonly(isLoading),
    lastError: readonly(lastError),

    // Running state
    runningScripts,
    runningScriptIds,
    scriptCount,
    runningCount,

    // Scripts by mode
    acquisitionScripts,
    sessionScripts,
    manualScripts,

    // CRUD
    addScript,
    updateScript,
    removeScript,
    getScript,

    // Execution
    startScript,
    stopScript,
    stopAllScripts,
    clearAllScripts,

    // Output
    getScriptOutputs,
    clearScriptOutput,

    // Queries
    requestScriptList
  }
}
