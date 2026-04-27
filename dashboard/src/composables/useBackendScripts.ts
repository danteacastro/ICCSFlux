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
import { useScripts } from './useScripts'

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
  autoRestart: boolean  // Auto-restart if script times out
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
// TRACEBACK PARSING
// =============================================================================

/**
 * Parse Python traceback to extract error details including line number
 *
 * Python tracebacks look like:
 *   File "<script:My Script>", line 15, in <module>
 *     x = tags.nonexistent
 *   AttributeError: ...
 */
export function parseTraceback(errorMessage: string): {
  lineNumber?: number
  errorType?: string
  shortMessage: string
} {
  // Match: File "<script:name>", line X
  const lineMatch = errorMessage.match(/File\s+"<script:[^"]+>",\s+line\s+(\d+)/i)
  const lineNumber = lineMatch && lineMatch[1] ? parseInt(lineMatch[1], 10) : undefined

  // Match common Python error types at the start of a line
  const errorTypeMatch = errorMessage.match(/^(\w+Error|\w+Exception):\s*(.*)$/m)
  const errorType = errorTypeMatch && errorTypeMatch[1] ? errorTypeMatch[1] : undefined
  const shortMessage = errorTypeMatch && errorTypeMatch[2]
    ? errorTypeMatch[2].trim() || errorMessage
    : errorMessage

  return { lineNumber, errorType, shortMessage }
}

// =============================================================================
// SINGLETON STATE
// =============================================================================

const scripts = ref<Record<string, BackendScript>>({})
const scriptOutputs = ref<Record<string, ScriptOutput[]>>({})
const isLoading = ref(false)
const lastError = ref<string | null>(null)
let handlersInitialized = false

// Track recent optimistic updates to prevent backend status from overwriting.
// Window must comfortably exceed the worst-case MQTT round-trip + backend
// processing latency. 2s was tight on slow links — Mike's user-toggle would
// flip back when the backend's stale status arrived ~2.1s later.
// Key format: `${scriptId}:${field}` -> timestamp
const recentOptimisticUpdates = new Map<string, number>()
const OPTIMISTIC_UPDATE_TTL = 8000 // 8 seconds protection window (was 2s; too tight on slow links)

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

  // Helper to check if a field is protected by a recent optimistic update
  function isFieldProtected(scriptId: string, field: string): boolean {
    const key = `${scriptId}:${field}`
    const timestamp = recentOptimisticUpdates.get(key)
    if (!timestamp) return false

    const age = Date.now() - timestamp
    if (age > OPTIMISTIC_UPDATE_TTL) {
      // Expired, clean up
      recentOptimisticUpdates.delete(key)
      return false
    }
    return true
  }

  function handleScriptStatus(data: ScriptStatus) {
    if (!data || !Array.isArray(data.scripts)) return

    // Build set of current script IDs from backend
    const backendIds = new Set<string>()
    const scriptsComposable = useScripts()

    // Update scripts from backend (array format)
    for (const scriptData of data.scripts) {
      if (scriptData.id) {
        backendIds.add(scriptData.id)

        const normalizedScript = normalizeScript(scriptData)
        const existingScript = scripts.value[scriptData.id]

        // Preserve fields that were recently updated optimistically (race condition protection)
        // This prevents backend status (generated before the update was processed) from
        // overwriting the user's recent changes
        if (existingScript) {
          if (isFieldProtected(scriptData.id, 'runMode')) {
            normalizedScript.runMode = existingScript.runMode
          }
          if (isFieldProtected(scriptData.id, 'enabled')) {
            normalizedScript.enabled = existingScript.enabled
          }
          if (isFieldProtected(scriptData.id, 'autoRestart')) {
            normalizedScript.autoRestart = existingScript.autoRestart
          }
          if (isFieldProtected(scriptData.id, 'name')) {
            normalizedScript.name = existingScript.name
          }
        }

        // Only update if data actually changed (prevents unnecessary re-renders/blinking)
        const hasChanged = !existingScript ||
          existingScript.state !== normalizedScript.state ||
          existingScript.iterations !== normalizedScript.iterations ||
          existingScript.errorMessage !== normalizedScript.errorMessage ||
          existingScript.startedAt !== normalizedScript.startedAt ||
          existingScript.enabled !== normalizedScript.enabled ||
          existingScript.name !== normalizedScript.name ||
          existingScript.runMode !== normalizedScript.runMode ||
          existingScript.autoRestart !== normalizedScript.autoRestart

        // Detect state transition to 'error'
        const previousState = existingScript?.state
        const newState = normalizedScript.state

        if (hasChanged) {
          // Update script data
          scripts.value[scriptData.id] = normalizedScript

          // Show notification if script just entered error state
          if (newState === 'error' && previousState !== 'error') {
            const scriptName = scriptData.name || scriptData.id
            let errorMsg = scriptData.error || 'Unknown error'

            // Parse error for better formatting
            const parsed = parseTraceback(errorMsg)
            if (parsed.lineNumber) {
              errorMsg = `Line ${parsed.lineNumber}: ${parsed.shortMessage}`
            } else {
              errorMsg = parsed.shortMessage
            }

            scriptsComposable.addNotification('error', `Script Failed: ${scriptName}`, errorMsg)
          }

          // Check for timeout and handle auto-restart
          if (newState === 'error' && normalizedScript.autoRestart && scriptData.error?.includes('timeout')) {
            // Auto-restart after a brief delay
            setTimeout(() => {
              if (scripts.value[scriptData.id]?.state === 'error') {
                console.debug(`[BackendScripts] Auto-restarting timed out script: ${scriptData.name}`)
                scriptsComposable.addNotification('info', `Auto-Restart: ${scriptData.name}`, 'Restarting script after timeout')
                startScript(scriptData.id)
              }
            }, 2000) // 2 second delay before restart
          }
        }
      }
    }

    // Remove scripts that are no longer in backend
    // But only if backend sent a non-empty list (empty list during transitions causes blinking)
    if (backendIds.size > 0) {
      for (const id of Object.keys(scripts.value)) {
        if (!backendIds.has(id)) {
          delete scripts.value[id]
        }
      }
    }
  }

  function handleScriptResponse(data: ScriptResponse) {
    if (!data) return

    if (!data.success && data.error) {
      lastError.value = data.error
      console.error(`Script ${data.action} failed:`, data.error)
      // Surface failure to the user via the existing toast bus, not just
      // console. A failed start/stop/save was previously indistinguishable
      // from a slow MQTT round-trip — operator just saw nothing happen.
      const action = data.action || 'operation'
      scriptsComposable.addNotification(
        'error',
        `Script ${action} failed`,
        data.error,
      )
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

    // Parse traceback for line numbers if this is an error
    let lineNumber: number | undefined
    if (data.type === 'error') {
      const parsed = parseTraceback(data.message)
      lineNumber = parsed.lineNumber
    }

    const output: ScriptOutput = {
      scriptId: data.script_id,
      type: data.type as ScriptOutput['type'],
      message: data.message,
      timestamp: Date.now(),
      lineNumber
    }

    if (!scriptOutputs.value[data.script_id]) {
      scriptOutputs.value[data.script_id] = []
    }

    scriptOutputs.value[data.script_id]!.push(output)

    // Limit output history
    if (scriptOutputs.value[data.script_id]!.length > 1000) {
      scriptOutputs.value[data.script_id] = scriptOutputs.value[data.script_id]!.slice(-500)
    }

    // Show toast notification for errors
    if (data.type === 'error') {
      const script = scripts.value[data.script_id]
      const scriptName = script?.name || data.script_id
      const parsed = parseTraceback(data.message)

      // Build notification message
      let notifMessage = parsed.shortMessage
      if (parsed.lineNumber) {
        notifMessage = `Line ${parsed.lineNumber}: ${notifMessage}`
      }
      if (parsed.errorType) {
        notifMessage = `${parsed.errorType} - ${notifMessage}`
      }

      // Use the notification system from useScripts
      const scriptsComposable = useScripts()
      scriptsComposable.addNotification('error', `Script Error: ${scriptName}`, notifMessage)
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
      autoRestart: data.autoRestart || data.auto_restart || false,
      state: data.state || 'idle',
      startedAt: data.startedAt || data.started_at || null,
      iterations: data.iterations || 0,
      // Backend sends 'error', accept all variations
      errorMessage: data.errorMessage || data.error_message || data.error || null
    }
  }

  // ===========================================================================
  // SCRIPT CRUD (send to backend)
  // ===========================================================================

  // Backend limits: script name max 256 chars, code max 256 KB
  const MAX_SCRIPT_NAME_LENGTH = 256
  const MAX_SCRIPT_CODE_LENGTH = 256 * 1024

  function addScript(script: {
    id?: string  // Allow passing existing ID to preserve identity
    name: string
    code: string
    description?: string
    runMode?: ScriptRunMode
    enabled?: boolean
    autoRestart?: boolean
  }): string {
    // Validate limits before sending to backend
    if (script.name.length > MAX_SCRIPT_NAME_LENGTH) {
      const scriptsComposable = useScripts()
      scriptsComposable.addNotification('error', 'Script Name Too Long', `Name must be ${MAX_SCRIPT_NAME_LENGTH} characters or fewer`)
      return ''
    }
    if (script.code.length > MAX_SCRIPT_CODE_LENGTH) {
      const scriptsComposable = useScripts()
      scriptsComposable.addNotification('error', 'Script Code Too Large', `Code must be ${MAX_SCRIPT_CODE_LENGTH / 1024} KB or smaller`)
      return ''
    }

    // Use provided ID or generate new one
    const id = script.id || `script_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    const now = new Date().toISOString()

    // OPTIMISTIC UPDATE: Add to local state immediately so projectFiles.saveNow()
    // has the script before the MQTT round-trip completes
    scripts.value[id] = {
      id,
      name: script.name,
      code: script.code,
      description: script.description || '',
      enabled: script.enabled !== false,
      runMode: script.runMode || 'manual',
      autoRestart: script.autoRestart || false,
      createdAt: now,
      modifiedAt: now,
      state: 'idle',
      startedAt: null,
      iterations: 0,
      errorMessage: null
    }
    scriptOutputs.value[id] = []

    // Send to backend
    mqtt.sendLocalCommand('script/add', {
      id,
      name: script.name,
      code: script.code,
      description: script.description || '',
      run_mode: script.runMode || 'manual',
      enabled: script.enabled !== false,
      auto_restart: script.autoRestart || false
    })

    return id
  }

  function updateScript(id: string, updates: Partial<{
    name: string
    code: string
    description: string
    runMode: ScriptRunMode
    enabled: boolean
    autoRestart: boolean
  }>) {
    // Validate limits before sending to backend
    if (updates.name !== undefined && updates.name.length > MAX_SCRIPT_NAME_LENGTH) {
      const scriptsComposable = useScripts()
      scriptsComposable.addNotification('error', 'Script Name Too Long', `Name must be ${MAX_SCRIPT_NAME_LENGTH} characters or fewer`)
      return
    }
    if (updates.code !== undefined && updates.code.length > MAX_SCRIPT_CODE_LENGTH) {
      const scriptsComposable = useScripts()
      scriptsComposable.addNotification('error', 'Script Code Too Large', `Code must be ${MAX_SCRIPT_CODE_LENGTH / 1024} KB or smaller`)
      return
    }

    // OPTIMISTIC UPDATE: Update local state immediately so projectFiles.saveNow()
    // has the latest data before the MQTT round-trip completes
    const existingScript = scripts.value[id]
    if (existingScript) {
      scripts.value[id] = {
        ...existingScript,
        ...(updates.name !== undefined && { name: updates.name }),
        ...(updates.code !== undefined && { code: updates.code }),
        ...(updates.description !== undefined && { description: updates.description }),
        ...(updates.runMode !== undefined && { runMode: updates.runMode }),
        ...(updates.enabled !== undefined && { enabled: updates.enabled }),
        ...(updates.autoRestart !== undefined && { autoRestart: updates.autoRestart }),
        modifiedAt: new Date().toISOString()
      }

      // Track which fields were optimistically updated to prevent race condition
      // where backend status (generated before update was processed) overwrites local state
      const now = Date.now()
      if (updates.runMode !== undefined) recentOptimisticUpdates.set(`${id}:runMode`, now)
      if (updates.enabled !== undefined) recentOptimisticUpdates.set(`${id}:enabled`, now)
      if (updates.autoRestart !== undefined) recentOptimisticUpdates.set(`${id}:autoRestart`, now)
      if (updates.name !== undefined) recentOptimisticUpdates.set(`${id}:name`, now)
    }

    // Send to backend
    const payload: any = { id }

    if (updates.name !== undefined) payload.name = updates.name
    if (updates.code !== undefined) payload.code = updates.code
    if (updates.description !== undefined) payload.description = updates.description
    if (updates.runMode !== undefined) payload.run_mode = updates.runMode
    if (updates.enabled !== undefined) payload.enabled = updates.enabled
    if (updates.autoRestart !== undefined) payload.auto_restart = updates.autoRestart

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

  /**
   * Hot-reload a script without stopping acquisition.
   *
   * This sends the reload command which:
   * 1. Stops the running script gracefully
   * 2. Updates the code
   * 3. Restarts the script
   * 4. Script recovers state via restore() calls
   *
   * Use this instead of updateScript when you want to apply code changes
   * to a running script without losing its persisted state.
   *
   * @param id - Script ID to reload
   * @param code - New code to use (optional - if omitted, reloads existing code)
   */
  function reloadScript(id: string, code?: string) {
    const payload: { id: string; code?: string } = { id }
    if (code !== undefined) {
      payload.code = code
    }
    mqtt.sendLocalCommand('script/reload', payload)
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

  function clearAllOutput() {
    for (const id of Object.keys(scriptOutputs.value)) {
      scriptOutputs.value[id] = []
    }
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
    reloadScript,
    clearAllScripts,

    // Output
    getScriptOutputs,
    clearScriptOutput,
    clearAllOutput,

    // Queries
    requestScriptList
  }
}
