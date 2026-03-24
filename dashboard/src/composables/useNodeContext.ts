/**
 * useNodeContext - Per-node project context switching
 *
 * Manages saving/caching/restoring the entire dashboard state per-node.
 * When the user clicks a different node pill, this composable:
 *   1. Saves the current node's state to cache
 *   2. Switches the active node (command routing)
 *   3. Restores the target node's state (channels, widgets, scripts, safety, recording)
 *
 * Each node is a completely independent DAQ instance with its own project.
 */

import { ref, computed, watch } from 'vue'
import { useMqtt } from './useMqtt'
import { useProjectFiles, type ProjectData } from './useProjectFiles'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from './useScripts'
import { usePythonScripts } from './usePythonScripts'
import { useBackendScripts } from './useBackendScripts'
import { usePlayground } from './usePlayground'
import type { ChannelConfig, ChannelType } from '../types'

// Singleton state
const nodeProjectCache = new Map<string, Partial<ProjectData>>()
const displayedNodeId = ref<string | null>(null)
const isSwitching = ref(false)
const switchError = ref<string | null>(null)

// Track if cache warming subscriptions are set up
let cacheWarmingInitialized = false

export function useNodeContext() {
  const mqtt = useMqtt()
  const projectFiles = useProjectFiles()
  const store = useDashboardStore()
  const scripts = useScripts()

  // Set up cache warming: only activate when 2+ nodes exist (multi-node mode)
  // In single-node mode, no extra subscriptions = zero overhead
  function initCacheWarming() {
    if (cacheWarmingInitialized) return
    cacheWarmingInitialized = true

    // Watch for multi-node activation — only subscribe when needed
    let subscriptionsActive = false
    watch(() => mqtt.knownNodes.value.size, (nodeCount) => {
      if (nodeCount >= 2 && !subscriptionsActive) {
        subscriptionsActive = true
        console.debug('[NODE-CTX] Multi-node detected — activating cache warming')

        // Listen for project/loaded from any node to keep cache updated
        mqtt.subscribe('nisystem/nodes/+/project/loaded', (payload: any, topic?: string) => {
          if (!payload.success || !payload.project) return
          const nodeId = extractNodeIdFromTopic(topic)
          if (nodeId) {
            nodeProjectCache.set(nodeId, payload.project)
            console.debug(`[NODE-CTX] Cache updated for ${nodeId} via project/loaded`)
          }
        })

        // Listen for project/current responses to cache them
        mqtt.subscribe('nisystem/nodes/+/project/current', (payload: any, topic?: string) => {
          if (!payload.project) return
          const nodeId = extractNodeIdFromTopic(topic)
          if (nodeId) {
            nodeProjectCache.set(nodeId, payload.project)
            console.debug(`[NODE-CTX] Cache updated for ${nodeId} via project/current`)
          }
        })
      }
    }, { immediate: true })
  }

  function extractNodeIdFromTopic(topic?: string): string | null {
    if (!topic) return null
    // topic format: nisystem/nodes/{nodeId}/...
    const parts = topic.split('/')
    if (parts.length >= 3 && parts[0] === 'nisystem' && parts[1] === 'nodes') {
      return parts[2] ?? null
    }
    return null
  }

  /**
   * Warm the cache for a specific node by requesting its project
   */
  function warmCache(nodeId: string) {
    if (nodeProjectCache.has(nodeId)) return
    console.debug(`[NODE-CTX] Warming cache for ${nodeId}...`)
    mqtt.sendNodeCommand('project/get-current', {}, nodeId)
  }

  /**
   * Switch the entire dashboard context to a different node.
   * Saves current state, swaps channels/widgets/scripts/safety/recording.
   */
  async function switchToNode(targetNodeId: string | null): Promise<boolean> {
    // No-op if already displaying this node
    if (targetNodeId === displayedNodeId.value) return true

    isSwitching.value = true
    switchError.value = null

    try {
      // 1. Save current node's state to cache
      if (displayedNodeId.value) {
        const currentState = projectFiles.collectCurrentState()
        nodeProjectCache.set(displayedNodeId.value, currentState)
        console.debug(`[NODE-CTX] Saved state for ${displayedNodeId.value}`)
      }

      // 2. Switch active node for command routing
      mqtt.setActiveNode(targetNodeId)

      // 3. Clear channel values to prevent stale cross-node data
      // channelValues and channelOwners are cleared in the MQTT filtering (Phase 3)

      // 4. Determine effective target
      const effectiveTarget = targetNodeId || getDefaultNodeId()

      if (!effectiveTarget) {
        // No nodes available — just deselect
        displayedNodeId.value = null
        isSwitching.value = false
        return true
      }

      // 5. Restore from cache (fast path) or fetch from node (slow path)
      const cached = nodeProjectCache.get(effectiveTarget)
      if (cached) {
        console.debug(`[NODE-CTX] Restoring ${effectiveTarget} from cache (fast path)`)
        await restoreFromCache(cached)
      } else {
        console.debug(`[NODE-CTX] Fetching project from ${effectiveTarget} (slow path)...`)
        const fetched = await fetchNodeProject(effectiveTarget)
        if (fetched) {
          nodeProjectCache.set(effectiveTarget, fetched)
          await restoreFromCache(fetched)
        } else {
          switchError.value = `Failed to fetch project from ${effectiveTarget}`
          console.error(`[NODE-CTX] ${switchError.value}`)
          isSwitching.value = false
          return false
        }
      }

      displayedNodeId.value = targetNodeId
      console.debug(`[NODE-CTX] Switched to ${targetNodeId ?? '(all nodes)'}`)
      return true
    } catch (err) {
      switchError.value = `Switch failed: ${err instanceof Error ? err.message : String(err)}`
      console.error(`[NODE-CTX] ${switchError.value}`)
      return false
    } finally {
      isSwitching.value = false
    }
  }

  /**
   * Lightweight project swap — only updates the dashboard UI.
   * Does NOT touch the backend (no safe-state, no acquisition stop/start, no bulk-create).
   */
  async function restoreFromCache(data: Partial<ProjectData>) {
    // Apply channels
    if (data.channels && Object.keys(data.channels).length > 0) {
      const channelConfigs: Record<string, ChannelConfig> = {}
      for (const [name, pch] of Object.entries(data.channels)) {
        channelConfigs[name] = {
          ...pch,
          name,
          channel_type: pch.channel_type as ChannelType,
          unit: pch.unit || pch.units || '',
          group: pch.group || 'Ungrouped',
          chartable: pch.chartable !== false && pch.channel_type !== 'digital_output',
          visible: pch.visible !== false,
        } as ChannelConfig
      }
      store.setChannels(channelConfigs)
    } else {
      store.setChannels({})
    }

    // Apply layout
    if (data.layout) {
      store.setLayout({
        system_id: store.systemId,
        widgets: data.layout.widgets || [],
        pages: data.layout.pages,
        currentPageId: data.layout.currentPageId,
        gridColumns: data.layout.gridColumns || 12,
        rowHeight: data.layout.rowHeight || 80
      })
      store.saveLayoutToStorage()
    }

    // Apply scripts to localStorage
    if (data.scripts) {
      localStorage.setItem('nisystem-scripts', JSON.stringify(data.scripts.calculatedParams || []))
      localStorage.setItem('nisystem-sequences', JSON.stringify(data.scripts.sequences || []))
      localStorage.setItem('nisystem-schedules', JSON.stringify(data.scripts.schedules || []))
      localStorage.setItem('nisystem-alarms', JSON.stringify(data.scripts.alarms || []))
      localStorage.setItem('nisystem-transformations', JSON.stringify(data.scripts.transformations || []))
      localStorage.setItem('nisystem-triggers', JSON.stringify(data.scripts.triggers || []))

      const pythonScripts = data.scripts.pythonScripts || []
      localStorage.setItem('nisystem-python-scripts', JSON.stringify(pythonScripts))

      if (pythonScripts.length > 0) {
        const pythonScriptsComposable = usePythonScripts()
        pythonScriptsComposable.importScripts(pythonScripts)

        const backendScripts = useBackendScripts()
        backendScripts.clearAllScripts()
        for (const script of pythonScripts) {
          backendScripts.addScript({
            id: script.id,
            name: script.name,
            code: script.code,
            description: script.description || '',
            runMode: script.runMode || script.run_mode || 'manual',
            enabled: script.enabled !== false
          })
        }
      }

      localStorage.setItem('dcflux-function-blocks', JSON.stringify(data.scripts.functionBlocks || []))
      localStorage.setItem('dcflux-draw-patterns', JSON.stringify(data.scripts.drawPatterns || { patterns: [], history: [] }))
      localStorage.setItem('dcflux-watchdogs', JSON.stringify(data.scripts.watchdogs || []))
      localStorage.setItem('dcflux-state-machines', JSON.stringify(data.scripts.stateMachines || []))
      localStorage.setItem('dcflux-report-templates', JSON.stringify(data.scripts.reportTemplates || []))
      localStorage.setItem('dcflux-scheduled-reports', JSON.stringify(data.scripts.scheduledReports || []))
    } else {
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

    // Apply recording settings
    if (data.recording) {
      localStorage.setItem('nisystem-recording-config', JSON.stringify(data.recording.config || {}))
      localStorage.setItem('nisystem-recording-channels', JSON.stringify(data.recording.selectedChannels || []))
    } else {
      localStorage.setItem('nisystem-recording-config', JSON.stringify({}))
      localStorage.setItem('nisystem-recording-channels', JSON.stringify([]))
    }

    // Apply safety settings
    if (data.safety) {
      localStorage.setItem('nisystem-alarm-configs', JSON.stringify(data.safety.alarmConfigs || {}))
      localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify(data.safety.alarmConfigs || {}))
      localStorage.setItem('nisystem-interlocks', JSON.stringify(data.safety.interlocks || []))
      localStorage.setItem('nisystem-safety-actions', JSON.stringify(data.safety.safetyActions || {}))
      localStorage.setItem('nisystem-safe-state-config', JSON.stringify(data.safety.safeStateConfig || {}))
      localStorage.setItem('nisystem-auto-execute-safety-actions', String(data.safety.autoExecuteSafetyActions || false))
      localStorage.setItem('nisystem-alarm-history', JSON.stringify([]))
    } else {
      localStorage.setItem('nisystem-alarm-configs', JSON.stringify({}))
      localStorage.setItem('nisystem-alarm-configs-v2', JSON.stringify({}))
      localStorage.setItem('nisystem-interlocks', JSON.stringify([]))
      localStorage.setItem('nisystem-safety-actions', JSON.stringify({}))
      localStorage.setItem('nisystem-safe-state-config', JSON.stringify({}))
      localStorage.setItem('nisystem-auto-execute-safety-actions', 'false')
      localStorage.setItem('nisystem-alarm-history', JSON.stringify([]))
    }

    // Apply notebook data
    if (data.notebook) {
      localStorage.setItem('nisystem_notebook', JSON.stringify(data.notebook.entries || []))
      localStorage.setItem('nisystem_experiments', JSON.stringify(data.notebook.experiments || []))
    } else {
      localStorage.setItem('nisystem_notebook', JSON.stringify([]))
      localStorage.setItem('nisystem_experiments', JSON.stringify([]))
    }

    // Reload scripts composable so formulas/sequences pick up new data
    scripts.reloadFromStorage()

    // Clear channel values to show fresh data from the new node
    store.clearValues()
  }

  /**
   * Fetch a node's current project via MQTT request/response
   */
  function fetchNodeProject(nodeId: string): Promise<Partial<ProjectData> | null> {
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        unsubscribe()
        console.warn(`[NODE-CTX] Timeout fetching project from ${nodeId}`)
        resolve(null)
      }, 5000)

      const unsubscribe = mqtt.subscribe(`nisystem/nodes/${nodeId}/project/current`, (payload: any) => {
        clearTimeout(timeout)
        unsubscribe()
        resolve(payload.project || null)
      })

      mqtt.sendNodeCommand('project/get-current', {}, nodeId)
    })
  }

  /**
   * Get the default node ID (first known node)
   */
  function getDefaultNodeId(): string | null {
    const nodes = Array.from(mqtt.knownNodes.value.keys())
    return nodes.length > 0 ? (nodes[0] ?? null) : null
  }

  /**
   * Invalidate cache for a specific node (e.g., after project save)
   */
  function invalidateCache(nodeId: string) {
    nodeProjectCache.delete(nodeId)
  }

  /**
   * Clear all cached data
   */
  function clearCache() {
    nodeProjectCache.clear()
  }

  // Initialize cache warming subscriptions
  initCacheWarming()

  return {
    // State
    displayedNodeId: computed(() => displayedNodeId.value),
    isSwitching: computed(() => isSwitching.value),
    switchError: computed(() => switchError.value),

    // Actions
    switchToNode,
    warmCache,
    invalidateCache,
    clearCache,

    // For testing
    nodeProjectCache,
  }
}
