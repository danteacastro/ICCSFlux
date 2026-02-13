/**
 * GC Chromatogram Analysis Composable
 *
 * Provides centralized management of Gas Chromatograph (GC) node data:
 * - GC node discovery from heartbeat messages
 * - Real-time chromatogram data from active runs
 * - Analysis results with peak identification
 * - Run progress tracking for active acquisitions
 * - Command interface for starting/stopping runs and pushing methods
 *
 * This composable uses a singleton pattern so state is shared across all components.
 */

import { ref, computed, readonly } from 'vue'
import { useMqtt } from './useMqtt'
import type { GCChromatogramData, GCAnalysisResult, GCRunProgress, GCPeakResult } from '../types'

// ============================================
// Types
// ============================================

export interface GCNodeInfo {
  nodeId: string
  nodeName: string
  gcType: string
  status: 'online' | 'offline' | 'unknown'
  analysisCount: number
  runActive: boolean
  lastSeen: number
}

export interface ActiveRunInfo {
  run_number: number
  elapsed_s: number
  points: number
  max_voltage: number
}

// ============================================
// Singleton State (shared across all instances)
// ============================================

const gcNodes = ref<Map<string, GCNodeInfo>>(new Map())
const chromatograms = ref<Map<string, GCChromatogramData[]>>(new Map())
const analysisResults = ref<Map<string, GCAnalysisResult[]>>(new Map())
const activeRuns = ref<Map<string, ActiveRunInfo>>(new Map())

// Default ring buffer depth for chromatogram and analysis history
const DEFAULT_HISTORY_DEPTH = 20

// Configurable max depth
let maxHistoryDepth = DEFAULT_HISTORY_DEPTH

// Node offline timeout (ms) - consider GC node offline if no heartbeat for this long
const NODE_OFFLINE_TIMEOUT_MS = 15000

// Initialization flag
let initialized = false

// Heartbeat check interval handle
let heartbeatCheckInterval: ReturnType<typeof setInterval> | null = null

// ============================================
// Composable Factory
// ============================================

export function useGcAnalysis() {
  const mqtt = useMqtt('nisystem')

  // ============================================
  // Computed Getters
  // ============================================

  /**
   * Get the latest chromatogram for a given node.
   * Returns null if no chromatograms have been received.
   */
  function latestChromatogram(nodeId: string): GCChromatogramData | null {
    const history = chromatograms.value.get(nodeId)
    if (!history || history.length === 0) return null
    return history[history.length - 1] ?? null
  }

  /**
   * Get the latest analysis result for a given node.
   * Returns null if no results have been received.
   */
  function latestResult(nodeId: string): GCAnalysisResult | null {
    const history = analysisResults.value.get(nodeId)
    if (!history || history.length === 0) return null
    return history[history.length - 1] ?? null
  }

  /**
   * Get all discovered GC nodes as an array.
   */
  function getGcNodes(): GCNodeInfo[] {
    return Array.from(gcNodes.value.values())
  }

  /**
   * Get the active run info for a node, or null if no run is active.
   */
  function getActiveRun(nodeId: string): ActiveRunInfo | null {
    return activeRuns.value.get(nodeId) ?? null
  }

  /**
   * Check if any GC node has an active run.
   */
  const hasActiveRun = computed(() => activeRuns.value.size > 0)

  /**
   * Total number of discovered GC nodes.
   */
  const nodeCount = computed(() => gcNodes.value.size)

  // ============================================
  // Message Handler
  // ============================================

  /**
   * Handle incoming GC-related MQTT messages.
   * Called from the MQTT message router for gc/* subtopics.
   *
   * @param nodeId - The node ID that sent the message
   * @param subtopic - The subtopic under gc/ (e.g., 'chromatogram', 'analysis')
   * @param payload - The parsed JSON payload
   */
  function handleGcMessage(nodeId: string, subtopic: string, payload: any): void {
    if (!payload || typeof payload !== 'object') {
      console.warn('[GC] Invalid payload for', subtopic, payload)
      return
    }

    switch (subtopic) {
      case 'chromatogram':
        handleChromatogram(nodeId, payload)
        break

      case 'analysis':
        handleAnalysis(nodeId, payload)
        break

      case 'run_started':
        handleRunStarted(nodeId, payload)
        break

      case 'run_progress':
        handleRunProgress(nodeId, payload)
        break

      case 'run_finished':
        handleRunFinished(nodeId)
        break

      default:
        console.debug('[GC] Unhandled subtopic:', subtopic, 'from node:', nodeId)
    }
  }

  // ============================================
  // Subtopic Handlers
  // ============================================

  function handleChromatogram(nodeId: string, payload: any): void {
    const data: GCChromatogramData = {
      run_number: payload.run_number ?? 0,
      node_id: payload.node_id ?? nodeId,
      times: payload.times ?? [],
      values: payload.values ?? [],
      points: payload.points ?? 0,
      duration_s: payload.duration_s ?? 0,
      timestamp: payload.timestamp ?? Date.now()
    }

    // Initialize history array if needed
    if (!chromatograms.value.has(nodeId)) {
      chromatograms.value.set(nodeId, [])
    }

    const history = chromatograms.value.get(nodeId)!
    history.push(data)

    // Trim to max depth (ring buffer behavior)
    while (history.length > maxHistoryDepth) {
      history.shift()
    }

    // Trigger reactivity
    chromatograms.value = new Map(chromatograms.value)

    // Update node info
    updateNodeLastSeen(nodeId)
  }

  function handleAnalysis(nodeId: string, payload: any): void {
    const result: GCAnalysisResult = {
      run_number: payload.run_number ?? 0,
      run_duration_s: payload.run_duration_s,
      finish_reason: payload.finish_reason,
      timestamp: payload.timestamp ?? new Date().toISOString(),
      method: payload.method,
      port: payload.port,
      port_label: payload.port_label,
      components: payload.components ?? {},
      unidentified_peaks: payload.unidentified_peaks,
      total_area: payload.total_area,
      chromatogram_points: payload.chromatogram_points
    }

    // Initialize history array if needed
    if (!analysisResults.value.has(nodeId)) {
      analysisResults.value.set(nodeId, [])
    }

    const history = analysisResults.value.get(nodeId)!
    history.push(result)

    // Trim to max depth
    while (history.length > maxHistoryDepth) {
      history.shift()
    }

    // Trigger reactivity
    analysisResults.value = new Map(analysisResults.value)

    // Analysis arrival implies run is finished — remove from activeRuns
    if (activeRuns.value.has(nodeId)) {
      activeRuns.value.delete(nodeId)
      activeRuns.value = new Map(activeRuns.value)
    }

    // Update node analysis count
    const node = gcNodes.value.get(nodeId)
    if (node) {
      node.analysisCount += 1
      node.runActive = false
      node.lastSeen = Date.now()
      gcNodes.value = new Map(gcNodes.value)
    }
  }

  function handleRunStarted(nodeId: string, payload: any): void {
    const runInfo: ActiveRunInfo = {
      run_number: payload.run_number ?? 0,
      elapsed_s: 0,
      points: 0,
      max_voltage: 0
    }

    activeRuns.value.set(nodeId, runInfo)
    activeRuns.value = new Map(activeRuns.value)

    // Update node state
    const node = gcNodes.value.get(nodeId)
    if (node) {
      node.runActive = true
      node.lastSeen = Date.now()
      gcNodes.value = new Map(gcNodes.value)
    }

    updateNodeLastSeen(nodeId)
  }

  function handleRunProgress(nodeId: string, payload: any): void {
    const existing = activeRuns.value.get(nodeId)
    if (!existing) {
      // Got progress without a start — create the entry
      activeRuns.value.set(nodeId, {
        run_number: payload.run_number ?? 0,
        elapsed_s: payload.elapsed_s ?? 0,
        points: payload.points ?? 0,
        max_voltage: payload.max_voltage ?? 0
      })
    } else {
      existing.elapsed_s = payload.elapsed_s ?? existing.elapsed_s
      existing.points = payload.points ?? existing.points
      existing.max_voltage = payload.max_voltage ?? existing.max_voltage
    }

    activeRuns.value = new Map(activeRuns.value)
    updateNodeLastSeen(nodeId)
  }

  function handleRunFinished(nodeId: string): void {
    activeRuns.value.delete(nodeId)
    activeRuns.value = new Map(activeRuns.value)

    const node = gcNodes.value.get(nodeId)
    if (node) {
      node.runActive = false
      node.lastSeen = Date.now()
      gcNodes.value = new Map(gcNodes.value)
    }
  }

  // ============================================
  // Heartbeat / Node Discovery
  // ============================================

  /**
   * Handle a heartbeat message to discover or update a GC node.
   * Should be called when a heartbeat with node_type === 'gc' is received.
   */
  function handleHeartbeat(nodeId: string, payload: any): void {
    if (payload.node_type !== 'gc') return

    const existing = gcNodes.value.get(nodeId)

    const nodeInfo: GCNodeInfo = {
      nodeId,
      nodeName: payload.node_name ?? existing?.nodeName ?? nodeId,
      gcType: payload.gc_type ?? existing?.gcType ?? 'unknown',
      status: 'online',
      analysisCount: payload.analysis_count ?? existing?.analysisCount ?? 0,
      runActive: payload.run_active ?? existing?.runActive ?? false,
      lastSeen: Date.now()
    }

    gcNodes.value.set(nodeId, nodeInfo)
    gcNodes.value = new Map(gcNodes.value)
  }

  /**
   * Update lastSeen timestamp for a node (called on any message from that node).
   */
  function updateNodeLastSeen(nodeId: string): void {
    const node = gcNodes.value.get(nodeId)
    if (node) {
      node.lastSeen = Date.now()
    }
  }

  /**
   * Check all GC nodes for heartbeat timeout and mark offline if stale.
   */
  function checkNodeHeartbeats(): void {
    const now = Date.now()
    let changed = false

    for (const [nodeId, node] of gcNodes.value) {
      if (node.status === 'online' && (now - node.lastSeen) > NODE_OFFLINE_TIMEOUT_MS) {
        node.status = 'offline'
        node.runActive = false
        changed = true

        // Clear active run if node goes offline
        if (activeRuns.value.has(nodeId)) {
          activeRuns.value.delete(nodeId)
          activeRuns.value = new Map(activeRuns.value)
        }
      }
    }

    if (changed) {
      gcNodes.value = new Map(gcNodes.value)
    }
  }

  // ============================================
  // Commands
  // ============================================

  /**
   * Start a GC run on the specified node.
   */
  function startRun(nodeId: string): void {
    mqtt.sendNodeCommand('commands/gc', { command: 'start_run' }, nodeId)
  }

  /**
   * Stop an active GC run on the specified node.
   */
  function stopRun(nodeId: string): void {
    mqtt.sendNodeCommand('commands/gc', { command: 'stop_run' }, nodeId)
  }

  /**
   * Push an analysis method configuration to a GC node.
   */
  function pushMethod(nodeId: string, method: any): void {
    mqtt.sendNodeCommand('commands/gc', { command: 'push_method', method }, nodeId)
  }

  // ============================================
  // Configuration
  // ============================================

  /**
   * Set the maximum history depth for chromatograms and analysis results.
   * Existing histories will be trimmed on the next incoming message.
   */
  function setHistoryDepth(depth: number): void {
    maxHistoryDepth = Math.max(1, Math.min(depth, 1000))
  }

  /**
   * Clear all stored data for a specific node or all nodes.
   */
  function clearHistory(nodeId?: string): void {
    if (nodeId) {
      chromatograms.value.delete(nodeId)
      analysisResults.value.delete(nodeId)
      chromatograms.value = new Map(chromatograms.value)
      analysisResults.value = new Map(analysisResults.value)
    } else {
      chromatograms.value = new Map()
      analysisResults.value = new Map()
    }
  }

  // ============================================
  // Initialization
  // ============================================

  function initialize(): void {
    if (initialized) return

    // Start periodic heartbeat check
    heartbeatCheckInterval = setInterval(checkNodeHeartbeats, 5000)

    initialized = true
  }

  function cleanup(): void {
    if (heartbeatCheckInterval !== null) {
      clearInterval(heartbeatCheckInterval)
      heartbeatCheckInterval = null
    }
    initialized = false
  }

  // Initialize on first use
  initialize()

  // ============================================
  // Return Public API
  // ============================================

  return {
    // State (readonly)
    gcNodes: readonly(gcNodes),
    chromatograms: readonly(chromatograms),
    analysisResults: readonly(analysisResults),
    activeRuns: readonly(activeRuns),

    // Computed
    hasActiveRun,
    nodeCount,

    // Getters
    latestChromatogram,
    latestResult,
    getGcNodes,
    getActiveRun,

    // Message handlers (called from MQTT router)
    handleGcMessage,
    handleHeartbeat,

    // Commands
    startRun,
    stopRun,
    pushMethod,

    // Configuration
    setHistoryDepth,
    clearHistory,

    // Lifecycle
    cleanup
  }
}
