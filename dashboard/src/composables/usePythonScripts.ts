/**
 * Python Scripts Composable
 *
 * Manages Pyodide-based Python script execution with full access to
 * cDAQ channel data, output control, and computed value publishing.
 *
 * Scripts run as `while session.active:` loops synchronized with scan cycle.
 */

import { ref, computed, shallowRef } from 'vue'
import type {
  PythonScript,
  PublishedValue,
  ScriptOutput,
  ScriptStatus,
  ScriptState,
  PyodideStatus,
  ScriptOutputType,
  ScriptRunMode,
  ImportedDataFile
} from '../types/python-scripts'
import {
  PYTHON_SCRIPTS_STORAGE_KEY,
  DEFAULT_SCRIPT_CODE
} from '../types/python-scripts'
import { loadPyodide, isPyodideReady, getPyodide } from '../utils/pyodideLoader'

// =============================================================================
// SINGLETON STATE - exists outside the composable function
// =============================================================================

// Scripts storage
const scripts = ref<Record<string, PythonScript>>({})

// Runtime state
const pyodideStatus = ref<PyodideStatus>('not_loaded')
const pyodideLoadProgress = ref<number>(0)
const pyodideLoadMessage = ref<string>('')

// Script execution state
const runningScripts = ref<Set<string>>(new Set())
const scriptStatuses = ref<Record<string, ScriptStatus>>({})
const scriptOutputs = ref<Record<string, ScriptOutput[]>>({})

// Published values from scripts
const publishedValues = ref<Record<string, PublishedValue>>({})

// Abort controllers for running scripts
const scriptAbortControllers = new Map<string, AbortController>()

// Scan synchronization
const scanCallbacks: Array<() => void> = []
let lastScanTime = Date.now()

// MQTT handlers - set by setMqttHandlers
let mqttPublish: ((topic: string, payload: any) => void) | null = null
let mqttSetOutput: ((channel: string, value: number | boolean) => void) | null = null
let getChannelValues: (() => Record<string, number>) | null = null
let getChannelTimestamps: (() => Record<string, number>) | null = null
let getChannelUnits: (() => Record<string, string>) | null = null
let getSessionActive: (() => boolean) | null = null
let getSessionElapsed: (() => number) | null = null
let mqttSendScriptValues: ((values: Record<string, number>) => void) | null = null
// Session/Acquisition control handlers
let startAcquisitionHandler: (() => void) | null = null
let stopAcquisitionHandler: (() => void) | null = null
let startRecordingHandler: ((filename?: string) => void) | null = null
let stopRecordingHandler: (() => void) | null = null
let isRecordingHandler: (() => boolean) | null = null

// =============================================================================
// RESET FUNCTION (for testing)
// =============================================================================

/**
 * Reset all singleton state - only use in tests!
 */
export function resetPythonScriptsState(): void {
  // Clear all refs
  for (const key of Object.keys(scripts.value)) {
    delete scripts.value[key]
  }
  for (const key of Object.keys(scriptStatuses.value)) {
    delete scriptStatuses.value[key]
  }
  for (const key of Object.keys(scriptOutputs.value)) {
    delete scriptOutputs.value[key]
  }
  for (const key of Object.keys(publishedValues.value)) {
    delete publishedValues.value[key]
  }
  runningScripts.value.clear()
  pyodideStatus.value = 'not_loaded'
  pyodideLoadProgress.value = 0
  pyodideLoadMessage.value = ''

  // Clear abort controllers
  scriptAbortControllers.clear()

  // Clear scan callbacks
  scanCallbacks.length = 0

  // Clear MQTT handlers
  mqttPublish = null
  mqttSetOutput = null
  getChannelValues = null
  getChannelTimestamps = null
  getChannelUnits = null
  getSessionActive = null
  getSessionElapsed = null
  mqttSendScriptValues = null
  startAcquisitionHandler = null
  stopAcquisitionHandler = null
  startRecordingHandler = null
  stopRecordingHandler = null
  isRecordingHandler = null
}

// =============================================================================
// COMPOSABLE FUNCTION
// =============================================================================

export function usePythonScripts() {

  // ===========================================================================
  // MQTT INTEGRATION
  // ===========================================================================

  function setMqttHandlers(handlers: {
    publish: (topic: string, payload: any) => void
    setOutput: (channel: string, value: number | boolean) => void
    getChannelValues: () => Record<string, number>
    getChannelTimestamps: () => Record<string, number>
    getChannelUnits: () => Record<string, string>
    getSessionActive: () => boolean
    getSessionElapsed: () => number
    sendScriptValues: (values: Record<string, number>) => void
    // Session/Acquisition control
    startAcquisition: () => void
    stopAcquisition: () => void
    startRecording: (filename?: string) => void
    stopRecording: () => void
    isRecording: () => boolean
  }) {
    mqttPublish = handlers.publish
    mqttSetOutput = handlers.setOutput
    getChannelValues = handlers.getChannelValues
    getChannelTimestamps = handlers.getChannelTimestamps
    getChannelUnits = handlers.getChannelUnits
    getSessionActive = handlers.getSessionActive
    getSessionElapsed = handlers.getSessionElapsed
    mqttSendScriptValues = handlers.sendScriptValues
    startAcquisitionHandler = handlers.startAcquisition
    stopAcquisitionHandler = handlers.stopAcquisition
    startRecordingHandler = handlers.startRecording
    stopRecordingHandler = handlers.stopRecording
    isRecordingHandler = handlers.isRecording
  }

  /**
   * Called when new channel data arrives (triggers next_scan resolution)
   */
  function onScanData() {
    lastScanTime = Date.now()
    // Resolve all waiting next_scan promises
    const callbacks = scanCallbacks.splice(0)
    callbacks.forEach(cb => cb())
  }

  // ===========================================================================
  // PYODIDE MANAGEMENT
  // ===========================================================================

  async function initializePyodide(): Promise<void> {
    if (pyodideStatus.value === 'ready' || pyodideStatus.value === 'loading') {
      return
    }

    try {
      await loadPyodide((status, message, progress) => {
        pyodideStatus.value = status
        pyodideLoadMessage.value = message
        pyodideLoadProgress.value = progress ?? 0
      })
    } catch (error: any) {
      pyodideStatus.value = 'error'
      pyodideLoadMessage.value = error.message || 'Failed to load Pyodide'
      throw error
    }
  }

  // ===========================================================================
  // SCRIPT CRUD
  // ===========================================================================

  function createScript(name: string, description: string = ''): PythonScript {
    const id = `script_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    const now = new Date().toISOString()

    const script: PythonScript = {
      id,
      name,
      description,
      code: DEFAULT_SCRIPT_CODE,
      enabled: true,
      runMode: 'manual',  // 'manual' | 'acquisition' | 'session'
      createdAt: now,
      modifiedAt: now
    }

    scripts.value[id] = script
    scriptOutputs.value[id] = []
    saveToLocalStorage()

    return script
  }

  function updateScript(id: string, updates: Partial<PythonScript>): void {
    const script = scripts.value[id]
    if (!script) return

    scripts.value[id] = {
      ...script,
      ...updates,
      modifiedAt: new Date().toISOString()
    }
    saveToLocalStorage()
  }

  function deleteScript(id: string): void {
    // Stop if running
    stopScript(id)

    delete scripts.value[id]
    delete scriptOutputs.value[id]
    delete scriptStatuses.value[id]

    // Remove published values from this script
    for (const key of Object.keys(publishedValues.value)) {
      if (publishedValues.value[key].scriptId === id) {
        delete publishedValues.value[key]
      }
    }

    saveToLocalStorage()
  }

  function getScript(id: string): PythonScript | undefined {
    return scripts.value[id]
  }

  // ===========================================================================
  // DATA IMPORT (CSV/Excel)
  // ===========================================================================

  /**
   * Parse CSV content into array of row objects
   */
  function parseCSV(content: string): { data: Record<string, any>[]; columns: string[] } {
    const lines = content.trim().split('\n')
    const headerLine = lines[0]
    if (!headerLine) return { data: [], columns: [] }

    // Parse header row
    const columns = parseCSVLine(headerLine)

    // Parse data rows
    const data: Record<string, any>[] = []
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i]
      if (!line) continue
      const values = parseCSVLine(line)
      if (values.length === 0) continue

      const row: Record<string, any> = {}
      for (let j = 0; j < columns.length; j++) {
        const colName = columns[j]
        if (!colName) continue
        const value = values[j] ?? ''
        // Try to convert to number
        const num = parseFloat(value)
        row[colName] = isNaN(num) ? value : num
      }
      data.push(row)
    }

    return { data, columns }
  }

  /**
   * Parse a single CSV line handling quoted values
   */
  function parseCSVLine(line: string): string[] {
    const result: string[] = []
    let current = ''
    let inQuotes = false

    for (let i = 0; i < line.length; i++) {
      const char = line[i]

      if (char === '"') {
        if (inQuotes && line[i + 1] === '"') {
          current += '"'
          i++
        } else {
          inQuotes = !inQuotes
        }
      } else if (char === ',' && !inQuotes) {
        result.push(current.trim())
        current = ''
      } else {
        current += char
      }
    }

    result.push(current.trim())
    return result
  }

  /**
   * Import CSV file for a script
   */
  async function importCSVFile(
    scriptId: string,
    file: File,
    variableName: string = 'imported_data'
  ): Promise<void> {
    const script = scripts.value[scriptId]
    if (!script) {
      throw new Error(`Script not found: ${scriptId}`)
    }

    const content = await file.text()
    const { data, columns } = parseCSV(content)

    const importedFile: ImportedDataFile = {
      filename: file.name,
      variableName,
      data,
      columns,
      importedAt: new Date().toISOString()
    }

    // Add to script's imported data
    const existing = script.importedData || []
    // Replace if same variable name exists
    const filtered = existing.filter(f => f.variableName !== variableName)

    scripts.value[scriptId] = {
      ...script,
      importedData: [...filtered, importedFile],
      modifiedAt: new Date().toISOString()
    }

    saveToLocalStorage()
    addScriptOutput(scriptId, 'info', `Imported ${data.length} rows from ${file.name} as '${variableName}'`)
  }

  /**
   * Import Excel file for a script
   * Uses SheetJS (xlsx) library if available, otherwise prompts to use CSV
   */
  async function importExcelFile(
    scriptId: string,
    file: File,
    variableName: string = 'imported_data'
  ): Promise<void> {
    const script = scripts.value[scriptId]
    if (!script) {
      throw new Error(`Script not found: ${scriptId}`)
    }

    try {
      // Dynamic import of xlsx (SheetJS) - may not be installed
      let XLSX: any
      try {
        // Use variable indirection to prevent Vite from statically analyzing this import
        // xlsx is an optional dependency - if not installed, we catch and show helpful message
        const xlsxModuleName = 'xlsx'
        XLSX = await import(/* @vite-ignore */ xlsxModuleName)
      } catch (e) {
        // xlsx not installed - provide helpful message
        addScriptOutput(scriptId, 'error',
          'Excel import requires the xlsx library. Install with: npm install xlsx\n' +
          'Or export your Excel file as CSV and use the CSV import instead.')
        throw new Error('xlsx library not installed. Please use CSV format instead.')
      }

      const buffer = await file.arrayBuffer()
      const workbook = XLSX.read(buffer, { type: 'array' })

      // Get first sheet
      const sheetName = workbook.SheetNames[0]
      if (!sheetName) {
        throw new Error('No sheets found in workbook')
      }
      const sheet = workbook.Sheets[sheetName]

      // Convert to JSON with header row
      const jsonData = XLSX.utils.sheet_to_json(sheet, { header: 1 }) as any[][]

      if (jsonData.length === 0) {
        throw new Error('Empty spreadsheet')
      }

      // First row is headers
      const headerRow = jsonData[0] as any[]
      if (!headerRow || headerRow.length === 0) {
        throw new Error('No header row found')
      }
      const columns = headerRow.map(h => String(h ?? ''))
      const data: Record<string, any>[] = []

      for (let i = 1; i < jsonData.length; i++) {
        const row: Record<string, any> = {}
        const values = jsonData[i] as any[]
        if (!values || values.length === 0) continue
        for (let j = 0; j < columns.length; j++) {
          const colName = columns[j]
          if (colName) {
            row[colName] = values[j] ?? null
          }
        }
        data.push(row)
      }

      const importedFile: ImportedDataFile = {
        filename: file.name,
        variableName,
        data,
        columns: columns.filter(c => c), // Remove empty column names
        importedAt: new Date().toISOString()
      }

      const existing = script.importedData || []
      const filtered = existing.filter(f => f.variableName !== variableName)

      scripts.value[scriptId] = {
        ...script,
        importedData: [...filtered, importedFile],
        modifiedAt: new Date().toISOString()
      }

      saveToLocalStorage()
      addScriptOutput(scriptId, 'info', `Imported ${data.length} rows from ${file.name} as '${variableName}'`)
    } catch (error: any) {
      if (!error.message.includes('xlsx library')) {
        addScriptOutput(scriptId, 'error', `Failed to import Excel: ${error.message}`)
      }
      throw error
    }
  }

  /**
   * Remove imported data from a script
   */
  function removeImportedData(scriptId: string, variableName: string): void {
    const script = scripts.value[scriptId]
    if (!script || !script.importedData) return

    scripts.value[scriptId] = {
      ...script,
      importedData: script.importedData.filter(f => f.variableName !== variableName),
      modifiedAt: new Date().toISOString()
    }

    saveToLocalStorage()
    addScriptOutput(scriptId, 'info', `Removed imported data '${variableName}'`)
  }

  /**
   * Get imported data for a script as Python-ready objects
   */
  function getImportedDataForScript(scriptId: string): Record<string, any[]> {
    const script = scripts.value[scriptId]
    if (!script || !script.importedData) return {}

    const result: Record<string, any[]> = {}
    for (const file of script.importedData) {
      result[file.variableName] = file.data
    }
    return result
  }

  // ===========================================================================
  // SCRIPT EXECUTION
  // ===========================================================================

  async function startScript(id: string): Promise<void> {
    const script = scripts.value[id]
    if (!script) {
      throw new Error(`Script not found: ${id}`)
    }

    if (runningScripts.value.has(id)) {
      console.warn(`Script already running: ${id}`)
      return
    }

    // Ensure Pyodide is loaded
    if (!isPyodideReady()) {
      await initializePyodide()
    }

    // Create abort controller
    const controller = new AbortController()
    scriptAbortControllers.set(id, controller)

    // Update status
    runningScripts.value.add(id)
    scriptStatuses.value[id] = {
      scriptId: id,
      state: 'running',
      startedAt: Date.now(),
      iterations: 0
    }

    // Clear previous outputs
    scriptOutputs.value[id] = []
    addScriptOutput(id, 'info', `Script started: ${script.name}`)

    // Execute script
    executeScript(id, controller.signal).catch(error => {
      addScriptOutput(id, 'error', error.message)
      scriptStatuses.value[id] = {
        ...scriptStatuses.value[id],
        state: 'error',
        error: error.message
      }
    }).finally(() => {
      runningScripts.value.delete(id)
      scriptAbortControllers.delete(id)
      if (scriptStatuses.value[id]?.state === 'running') {
        scriptStatuses.value[id].state = 'idle'
      }
      addScriptOutput(id, 'info', 'Script stopped')
    })
  }

  function stopScript(id: string): void {
    const controller = scriptAbortControllers.get(id)
    if (controller) {
      controller.abort()
      scriptStatuses.value[id] = {
        ...scriptStatuses.value[id],
        state: 'stopping'
      }
    }
  }

  function stopAllScripts(): void {
    for (const id of runningScripts.value) {
      stopScript(id)
    }
  }

  // ===========================================================================
  // SCRIPT VALIDATION
  // ===========================================================================

  interface ValidationResult {
    valid: boolean
    errors: Array<{
      line: number
      column: number
      message: string
      type: 'error' | 'warning'
    }>
  }

  /**
   * Validate Python script syntax without running it
   * Returns validation result with any syntax errors
   */
  async function validateScript(code: string): Promise<ValidationResult> {
    // Ensure Pyodide is loaded
    if (!isPyodideReady()) {
      await initializePyodide()
    }

    const pyodide = getPyodide()
    const errors: ValidationResult['errors'] = []

    try {
      // Properly escape the code for embedding in Python string
      // Use base64 encoding to avoid any escaping issues with quotes
      const encoder = new TextEncoder()
      const bytes = encoder.encode(code)
      const encodedCode = btoa(String.fromCharCode(...bytes))

      // Use Python's compile() to check syntax without executing
      await pyodide.runPythonAsync(`
import ast
import base64

_validation_code = base64.b64decode('${encodedCode}').decode('utf-8')

try:
    # Parse the code to check for syntax errors
    ast.parse(_validation_code)
    _validation_result = {'valid': True, 'errors': []}
except SyntaxError as e:
    _validation_result = {
        'valid': False,
        'errors': [{
            'line': e.lineno or 1,
            'column': e.offset or 0,
            'message': str(e.msg) if hasattr(e, 'msg') else str(e),
            'type': 'error'
        }]
    }
except Exception as e:
    _validation_result = {
        'valid': False,
        'errors': [{
            'line': 1,
            'column': 0,
            'message': str(e),
            'type': 'error'
        }]
    }
`)

      const result = pyodide.globals.get('_validation_result').toJs()

      // Check for common issues (warnings)
      const warnings: ValidationResult['errors'] = []

      // Check for missing await next_scan() in while loops
      if (code.includes('while session.active') && !code.includes('await next_scan()')) {
        warnings.push({
          line: 1,
          column: 0,
          message: 'while session.active loop should contain "await next_scan()" to prevent blocking',
          type: 'warning'
        })
      }

      // Check for infinite loops without await
      if (code.includes('while True') && !code.includes('await ')) {
        warnings.push({
          line: 1,
          column: 0,
          message: 'Infinite loop detected without await - this will block the browser',
          type: 'warning'
        })
      }

      return {
        valid: result.valid && warnings.filter(w => w.type === 'error').length === 0,
        errors: [...(result.errors || []), ...warnings]
      }
    } catch (error: any) {
      return {
        valid: false,
        errors: [{
          line: 1,
          column: 0,
          message: error.message || 'Validation failed',
          type: 'error'
        }]
      }
    }
  }

  // ===========================================================================
  // SESSION LIFECYCLE
  // ===========================================================================

  /**
   * Called when cDAQ acquisition starts.
   * Starts all scripts with runMode='acquisition'.
   */
  async function onAcquisitionStart(): Promise<void> {
    const acquisitionScripts = Object.values(scripts.value).filter(
      s => s.enabled && s.runMode === 'acquisition'
    )

    for (const script of acquisitionScripts) {
      if (!runningScripts.value.has(script.id)) {
        try {
          await startScript(script.id)
          addScriptOutput(script.id, 'info', 'Auto-started with acquisition')
        } catch (error) {
          console.error(`Failed to auto-start script ${script.name} on acquisition:`, error)
        }
      }
    }
  }

  /**
   * Called when cDAQ acquisition stops.
   * Stops all scripts with runMode='acquisition'.
   */
  function onAcquisitionStop(): void {
    const acquisitionScripts = Object.values(scripts.value).filter(
      s => s.runMode === 'acquisition'
    )

    for (const script of acquisitionScripts) {
      if (runningScripts.value.has(script.id)) {
        stopScript(script.id)
        addScriptOutput(script.id, 'info', 'Auto-stopped with acquisition')
      }
    }
  }

  /**
   * Called when test session starts.
   * Starts all scripts with runMode='session'.
   */
  async function onSessionStart(): Promise<void> {
    const sessionScripts = Object.values(scripts.value).filter(
      s => s.enabled && s.runMode === 'session'
    )

    for (const script of sessionScripts) {
      if (!runningScripts.value.has(script.id)) {
        try {
          await startScript(script.id)
          addScriptOutput(script.id, 'info', 'Auto-started with session')
        } catch (error) {
          console.error(`Failed to auto-start script ${script.name} on session start:`, error)
        }
      }
    }
  }

  /**
   * Called when test session ends.
   * Stops all scripts with runMode='session'.
   */
  function onSessionEnd(): void {
    const sessionScripts = Object.values(scripts.value).filter(
      s => s.runMode === 'session'
    )

    for (const script of sessionScripts) {
      if (runningScripts.value.has(script.id)) {
        stopScript(script.id)
        addScriptOutput(script.id, 'info', 'Auto-stopped with session')
      }
    }
  }

  /**
   * Get scripts by their run mode
   */
  function getScriptsByRunMode(mode: ScriptRunMode): PythonScript[] {
    return Object.values(scripts.value).filter(s => s.enabled && s.runMode === mode)
  }

  /**
   * Set run mode for a script
   */
  function setRunMode(id: string, runMode: ScriptRunMode): void {
    const script = scripts.value[id]
    if (script) {
      updateScript(id, { runMode })
    }
  }

  // Legacy aliases for backward compatibility
  function getAutoStartScripts(): PythonScript[] {
    return [
      ...getScriptsByRunMode('acquisition'),
      ...getScriptsByRunMode('session')
    ]
  }

  function setAutoStart(id: string, autoStart: boolean): void {
    // Legacy: true maps to 'acquisition', false maps to 'manual'
    setRunMode(id, autoStart ? 'acquisition' : 'manual')
  }

  async function executeScript(id: string, signal: AbortSignal): Promise<void> {
    const script = scripts.value[id]
    if (!script) return

    const pyodide = getPyodide()

    // Track warnings to avoid spam (reset each script run)
    const scriptWarnings = new Set<string>()

    // Create JavaScript functions that Python can call
    const jsBridge = {
      // Get channel value with validation
      getChannel: (name: string): number => {
        const values = getChannelValues?.() ?? {}
        const allNames = Object.keys(values)

        // Check if channel exists
        if (!(name in values)) {
          // Check for py.* published values
          if (name.startsWith('py.')) {
            const pubName = name.slice(3)
            if (pubName in publishedValues.value) {
              return publishedValues.value[pubName].value
            }
          }

          // Log warning for unknown channel (only once per name)
          const warningKey = `unknown_tag_${name}`
          if (!scriptWarnings.has(warningKey)) {
            scriptWarnings.add(warningKey)
            addScriptOutput(id, 'warning', `Unknown tag: "${name}" - available: ${allNames.slice(0, 5).join(', ')}${allNames.length > 5 ? '...' : ''}`)
          }
          return 0
        }
        return values[name]
      },

      // Check if channel exists
      hasChannel: (name: string): boolean => {
        const values = getChannelValues?.() ?? {}
        if (name in values) return true
        if (name.startsWith('py.')) {
          return (name.slice(3) in publishedValues.value)
        }
        return false
      },

      // Get all channel names (including published)
      getChannelNames: (): string[] => {
        const values = getChannelValues?.() ?? {}
        const hwChannels = Object.keys(values)
        const pyChannels = Object.keys(publishedValues.value).map(n => `py.${n}`)
        return [...hwChannels, ...pyChannels]
      },

      // Get channel timestamp (backend acquisition time in milliseconds)
      getTimestamp: (name: string): number => {
        const timestamps = getChannelTimestamps?.() ?? {}

        // Check hardware channels
        if (name in timestamps) {
          return timestamps[name]
        }

        // Check published values
        if (name.startsWith('py.')) {
          const pubName = name.slice(3)
          if (pubName in publishedValues.value) {
            return publishedValues.value[pubName].timestamp
          }
        }

        // Return 0 if not found
        return 0
      },

      // Get value and timestamp together (for efficient access)
      getValueWithTimestamp: (name: string): { value: number; timestamp: number } => {
        const values = getChannelValues?.() ?? {}
        const timestamps = getChannelTimestamps?.() ?? {}

        // Check hardware channels
        if (name in values) {
          return {
            value: values[name],
            timestamp: timestamps[name] ?? 0
          }
        }

        // Check published values
        if (name.startsWith('py.')) {
          const pubName = name.slice(3)
          if (pubName in publishedValues.value) {
            const pv = publishedValues.value[pubName]
            return { value: pv.value, timestamp: pv.timestamp }
          }
        }

        return { value: 0, timestamp: 0 }
      },

      // Get session active state
      isSessionActive: (): boolean => {
        return getSessionActive?.() ?? false
      },

      // Get session elapsed time
      getSessionElapsed: (): number => {
        return getSessionElapsed?.() ?? 0
      },

      // Session/Acquisition control
      startAcquisition: (): void => {
        startAcquisitionHandler?.()
        addScriptOutput(id, 'info', 'Acquisition started from script')
      },

      stopAcquisition: (): void => {
        stopAcquisitionHandler?.()
        addScriptOutput(id, 'info', 'Acquisition stopped from script')
      },

      startRecording: (filename?: string): void => {
        startRecordingHandler?.(filename)
        addScriptOutput(id, 'info', filename ? `Recording started: ${filename}` : 'Recording started')
      },

      stopRecording: (): void => {
        stopRecordingHandler?.()
        addScriptOutput(id, 'info', 'Recording stopped from script')
      },

      isRecording: (): boolean => {
        return isRecordingHandler?.() ?? false
      },

      // Time helpers
      getCurrentTimestamp: (): number => {
        return Date.now()
      },

      getCurrentTimeISO: (): string => {
        return new Date().toISOString()
      },

      // Set output value
      setOutput: (channel: string, value: number | boolean): void => {
        mqttSetOutput?.(channel, value)
        addScriptOutput(id, 'info', `Output: ${channel} = ${value}`)
      },

      // Publish computed value with validation
      publish: (name: string, value: number, units: string = '', description: string = ''): void => {
        // Validate name
        if (!name || typeof name !== 'string') {
          addScriptOutput(id, 'error', 'publish() requires a non-empty string name')
          return
        }

        // Check for invalid characters in name
        const validNamePattern = /^[a-zA-Z_][a-zA-Z0-9_]*$/
        if (!validNamePattern.test(name)) {
          addScriptOutput(id, 'error', `publish() name "${name}" invalid - use letters, numbers, underscore (start with letter/underscore)`)
          return
        }

        // Check for reserved prefixes
        if (name.startsWith('py.')) {
          addScriptOutput(id, 'error', `publish() name cannot start with "py." - just use "${name.slice(3)}"`)
          return
        }

        // Check for conflict with hardware channels
        const hwChannels = getChannelValues?.() ?? {}
        if (name in hwChannels) {
          addScriptOutput(id, 'error', `publish() name "${name}" conflicts with hardware channel - choose different name`)
          return
        }

        // Validate value is a number
        if (typeof value !== 'number' || isNaN(value)) {
          addScriptOutput(id, 'error', `publish() value must be a number, got: ${typeof value}`)
          return
        }

        // Validate units is string
        if (typeof units !== 'string') {
          units = String(units)
        }

        // Check if another script already publishes this name
        const existing = publishedValues.value[name]
        if (existing && existing.scriptId !== id) {
          const warningKey = `publish_conflict_${name}`
          if (!scriptWarnings.has(warningKey)) {
            scriptWarnings.add(warningKey)
            addScriptOutput(id, 'warning', `publish() "${name}" also published by another script`)
          }
        }

        // Store published value
        publishedValues.value[name] = {
          name,
          value,
          units,
          description: String(description || ''),
          scriptId: id,
          timestamp: Date.now()
        }

        // Send to backend for CSV recording (py.{name} channels)
        if (typeof value === 'number') {
          mqttSendScriptValues?.({ [name]: value })
        }
      },

      // Log output
      log: (type: ScriptOutputType, message: string): void => {
        addScriptOutput(id, type, message)
      },

      // Wait for next scan
      nextScan: (): Promise<void> => {
        return new Promise((resolve, reject) => {
          if (signal.aborted) {
            reject(new Error('Script aborted'))
            return
          }

          // Add abort listener
          const abortHandler = () => {
            reject(new Error('Script aborted'))
          }
          signal.addEventListener('abort', abortHandler, { once: true })

          // Wait for next scan data
          scanCallbacks.push(() => {
            signal.removeEventListener('abort', abortHandler)
            if (signal.aborted) {
              reject(new Error('Script aborted'))
            } else {
              resolve()
            }
          })

          // Fallback timeout in case no scan arrives
          setTimeout(() => {
            const idx = scanCallbacks.indexOf(arguments.callee as any)
            if (idx >= 0) {
              scanCallbacks.splice(idx, 1)
              signal.removeEventListener('abort', abortHandler)
              resolve()
            }
          }, 1000)
        })
      },

      // Wait for duration
      waitFor: (seconds: number): Promise<void> => {
        return new Promise((resolve, reject) => {
          if (signal.aborted) {
            reject(new Error('Script aborted'))
            return
          }

          const timeout = setTimeout(() => {
            signal.removeEventListener('abort', abortHandler)
            resolve()
          }, seconds * 1000)

          const abortHandler = () => {
            clearTimeout(timeout)
            reject(new Error('Script aborted'))
          }
          signal.addEventListener('abort', abortHandler, { once: true })
        })
      }
    }

    // Register bridge in Pyodide global scope
    pyodide.registerJsModule('_jsbridge', jsBridge)

    // Create runtime wrapper that connects bridge to Python API
    const runtimeCode = `
import _jsbridge
import nisystem
import asyncio

# Override placeholders with real bridge functions
class _RealTags:
    def __getattr__(self, name):
        return _jsbridge.getChannel(name)
    def __getitem__(self, name):
        return _jsbridge.getChannel(name)
    def __contains__(self, name):
        """Check if tag exists: 'TC001' in tags"""
        return _jsbridge.hasChannel(name)
    def keys(self):
        """List all available tags (hardware + published)"""
        return list(_jsbridge.getChannelNames())
    def get(self, name, default=0.0):
        """Get tag value with default if not found"""
        if _jsbridge.hasChannel(name):
            return _jsbridge.getChannel(name)
        return default
    def exists(self, name):
        """Check if tag exists"""
        return _jsbridge.hasChannel(name)
    def timestamp(self, name):
        """Get backend acquisition timestamp for a tag (Unix ms)"""
        return _jsbridge.getTimestamp(name)
    def get_with_timestamp(self, name):
        """Get value and timestamp together: (value, timestamp_ms)"""
        result = _jsbridge.getValueWithTimestamp(name)
        return (result.value, result.timestamp)
    def age(self, name):
        """Get age of tag data in seconds (time since acquisition)"""
        import time
        ts = _jsbridge.getTimestamp(name)
        if ts == 0:
            return float('inf')  # Unknown/never received
        return (time.time() * 1000 - ts) / 1000.0

class _RealSession:
    @property
    def active(self):
        return _jsbridge.isSessionActive()
    @property
    def elapsed(self):
        return _jsbridge.getSessionElapsed()
    @property
    def recording(self):
        """Check if currently recording data"""
        return _jsbridge.isRecording()

    def start(self):
        """Start data acquisition"""
        _jsbridge.startAcquisition()

    def stop(self):
        """Stop data acquisition"""
        _jsbridge.stopAcquisition()

    def start_recording(self, filename=None):
        """Start recording data to file. Optional filename parameter."""
        if filename:
            _jsbridge.startRecording(filename)
        else:
            _jsbridge.startRecording()

    def stop_recording(self):
        """Stop recording data"""
        _jsbridge.stopRecording()

    @staticmethod
    def now():
        """Get current timestamp in milliseconds (Unix epoch)"""
        return _jsbridge.getCurrentTimestamp()

    @staticmethod
    def now_iso():
        """Get current time as ISO 8601 string"""
        return _jsbridge.getCurrentTimeISO()

    @staticmethod
    def time_of_day():
        """Get current time of day as HH:MM:SS string"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

class _RealOutputs:
    def set(self, channel, value):
        _jsbridge.setOutput(channel, value)
    def __setitem__(self, name, value):
        self.set(name, value)

# Replace placeholders
tags = _RealTags()
session = _RealSession()
outputs = _RealOutputs()

def publish(name, value, units='', description=''):
    _jsbridge.publish(name, float(value), str(units), str(description))

async def next_scan():
    await _jsbridge.nextScan()

async def wait_for(seconds):
    await _jsbridge.waitFor(float(seconds))

# Make available globally
nisystem.tags = tags
nisystem.session = session
nisystem.outputs = outputs
nisystem.publish = publish
nisystem.next_scan = next_scan
nisystem.wait_for = wait_for

# Also expose in global namespace for convenience
import builtins
builtins.tags = tags
builtins.session = session
builtins.outputs = outputs
builtins.publish = publish
builtins.next_scan = next_scan
builtins.wait_for = wait_for
builtins.wait_until = nisystem.wait_until

# Time functions in builtins
builtins.now = nisystem.now
builtins.now_ms = nisystem.now_ms
builtins.now_iso = nisystem.now_iso
builtins.time_of_day = nisystem.time_of_day
builtins.format_timestamp = nisystem.format_timestamp
builtins.elapsed_since = nisystem.elapsed_since

# Conversions
builtins.F_to_C = nisystem.F_to_C
builtins.C_to_F = nisystem.C_to_F
builtins.GPM_to_LPM = nisystem.GPM_to_LPM
builtins.LPM_to_GPM = nisystem.LPM_to_GPM
builtins.PSI_to_bar = nisystem.PSI_to_bar
builtins.bar_to_PSI = nisystem.bar_to_PSI
builtins.gal_to_L = nisystem.gal_to_L
builtins.L_to_gal = nisystem.L_to_gal
builtins.BTU_to_kJ = nisystem.BTU_to_kJ
builtins.kJ_to_BTU = nisystem.kJ_to_BTU
builtins.lb_to_kg = nisystem.lb_to_kg
builtins.kg_to_lb = nisystem.kg_to_lb

# Helpers
builtins.RateCalculator = nisystem.RateCalculator
builtins.Accumulator = nisystem.Accumulator
builtins.EdgeDetector = nisystem.EdgeDetector
builtins.RollingStats = nisystem.RollingStats

print("Runtime bridge connected")
`

    await pyodide.runPythonAsync(runtimeCode)

    // Inject imported data into Python namespace
    const importedData = getImportedDataForScript(id)
    if (Object.keys(importedData).length > 0) {
      // Convert imported data to Python objects
      for (const [varName, data] of Object.entries(importedData)) {
        // Set the data as a Python variable using Pyodide's globals
        pyodide.globals.set(varName, pyodide.toPy(data))
        addScriptOutput(id, 'info', `Loaded ${data.length} rows as '${varName}'`)
      }
    }

    // Wrap user code in async function
    const wrappedCode = `
async def __user_script__():
    try:
${script.code.split('\n').map(line => '        ' + line).join('\n')}
    except Exception as e:
        _jsbridge.log('error', str(e))
        raise

import asyncio
asyncio.ensure_future(__user_script__())
`

    try {
      await pyodide.runPythonAsync(wrappedCode)

      // Keep running event loop while script is active
      while (!signal.aborted && runningScripts.value.has(id)) {
        await pyodide.runPythonAsync('import asyncio; await asyncio.sleep(0.01)')

        // Update iteration count
        if (scriptStatuses.value[id]) {
          scriptStatuses.value[id].iterations = (scriptStatuses.value[id].iterations ?? 0) + 1
        }
      }
    } catch (error: any) {
      // Parse Python traceback for line number
      const match = error.message?.match(/line (\d+)/)
      const lineNumber = match ? parseInt(match[1]) : undefined

      addScriptOutput(id, 'error', error.message || 'Unknown error', lineNumber)
      throw error
    }
  }

  // ===========================================================================
  // SCRIPT OUTPUT
  // ===========================================================================

  function addScriptOutput(
    scriptId: string,
    type: ScriptOutputType,
    message: string,
    lineNumber?: number
  ): void {
    if (!scriptOutputs.value[scriptId]) {
      scriptOutputs.value[scriptId] = []
    }

    scriptOutputs.value[scriptId].push({
      type,
      message,
      timestamp: Date.now(),
      lineNumber
    })

    // Limit output history
    if (scriptOutputs.value[scriptId].length > 1000) {
      scriptOutputs.value[scriptId] = scriptOutputs.value[scriptId].slice(-500)
    }
  }

  function clearScriptOutput(scriptId: string): void {
    scriptOutputs.value[scriptId] = []
  }

  // ===========================================================================
  // PERSISTENCE
  // ===========================================================================

  function saveToLocalStorage(): void {
    try {
      const data = Object.values(scripts.value)
      localStorage.setItem(PYTHON_SCRIPTS_STORAGE_KEY, JSON.stringify(data))
    } catch (error) {
      console.error('Failed to save Python scripts to localStorage:', error)
    }
  }

  function loadFromLocalStorage(): void {
    try {
      const data = localStorage.getItem(PYTHON_SCRIPTS_STORAGE_KEY)
      if (data) {
        const scriptsList: PythonScript[] = JSON.parse(data)
        scripts.value = {}
        for (const script of scriptsList) {
          scripts.value[script.id] = script
          scriptOutputs.value[script.id] = []
        }
      }
    } catch (error) {
      console.error('Failed to load Python scripts from localStorage:', error)
    }
  }

  function importScripts(scriptsList: PythonScript[], clearExisting: boolean = true): void {
    // Clear existing scripts to prevent duplicates when loading a project
    if (clearExisting) {
      scripts.value = {}
      scriptOutputs.value = {}
    }
    for (const script of scriptsList) {
      scripts.value[script.id] = script
      scriptOutputs.value[script.id] = []
    }
    saveToLocalStorage()
  }

  function exportScripts(): PythonScript[] {
    return Object.values(scripts.value)
  }

  // ===========================================================================
  // PUBLISHED VALUES AS TAGS
  // ===========================================================================

  /**
   * Get all published values as a channel-like object
   * Keys are prefixed with "py." to distinguish from hardware channels
   */
  function getPublishedChannels(): Record<string, number> {
    const channels: Record<string, number> = {}
    for (const [name, pv] of Object.entries(publishedValues.value)) {
      channels[`py.${name}`] = pv.value
    }
    return channels
  }

  /**
   * Get units for all published channels
   */
  function getPublishedUnits(): Record<string, string> {
    const units: Record<string, string> = {}
    for (const [name, pv] of Object.entries(publishedValues.value)) {
      units[`py.${name}`] = pv.units
    }
    return units
  }

  /**
   * Get a single published value by name (with or without py. prefix)
   */
  function getPublishedValue(name: string): number | undefined {
    const cleanName = name.startsWith('py.') ? name.slice(3) : name
    return publishedValues.value[cleanName]?.value
  }

  /**
   * Get all published channel names (for dropdowns)
   */
  function getPublishedChannelNames(): string[] {
    return Object.keys(publishedValues.value).map(name => `py.${name}`)
  }

  // ===========================================================================
  // COMPUTED PROPERTIES
  // ===========================================================================

  const scriptsList = computed(() => Object.values(scripts.value))

  const runningScriptsList = computed(() =>
    Array.from(runningScripts.value).map(id => scripts.value[id]).filter(Boolean)
  )

  const publishedValuesList = computed(() => Object.values(publishedValues.value))

  const isPyodideLoading = computed(() => pyodideStatus.value === 'loading')
  const isPyodideError = computed(() => pyodideStatus.value === 'error')

  // Aggregated console output from all scripts (for SessionTab)
  const consoleOutput = computed(() => {
    const allOutputs: ScriptOutput[] = []
    for (const outputs of Object.values(scriptOutputs.value)) {
      allOutputs.push(...outputs)
    }
    // Sort by timestamp, newest last
    allOutputs.sort((a, b) => a.timestamp - b.timestamp)
    return allOutputs
  })

  /**
   * Computed: all published channel names for widget dropdowns
   */
  const publishedChannelNames = computed(() => getPublishedChannelNames())

  // ===========================================================================
  // INITIALIZATION
  // ===========================================================================

  // Load scripts on first use
  loadFromLocalStorage()

  // ===========================================================================
  // RETURN
  // ===========================================================================

  return {
    // State
    scripts,
    scriptsList,
    runningScripts,
    runningScriptsList,
    scriptStatuses,
    scriptOutputs,
    consoleOutput,
    publishedValues,
    publishedValuesList,

    // Pyodide state
    pyodideStatus,
    pyodideLoadProgress,
    pyodideLoadMessage,
    isPyodideLoading,
    isPyodideError,

    // MQTT integration
    setMqttHandlers,
    onScanData,

    // Pyodide management
    initializePyodide,

    // Script CRUD
    createScript,
    updateScript,
    deleteScript,
    getScript,

    // Script execution
    startScript,
    stopScript,
    stopAllScripts,

    // Script validation
    validateScript,

    // Session lifecycle
    onAcquisitionStart,
    onAcquisitionStop,
    onSessionStart,
    onSessionEnd,
    getScriptsByRunMode,
    setRunMode,
    // Legacy aliases
    getAutoStartScripts,
    setAutoStart,

    // Script output
    addScriptOutput,
    clearScriptOutput,

    // Published values as tags
    getPublishedChannels,
    getPublishedUnits,
    getPublishedValue,
    getPublishedChannelNames,
    publishedChannelNames,

    // Data Import (CSV/Excel)
    importCSVFile,
    importExcelFile,
    removeImportedData,
    getImportedDataForScript,

    // Persistence
    saveToLocalStorage,
    loadFromLocalStorage,
    importScripts,
    exportScripts
  }
}
