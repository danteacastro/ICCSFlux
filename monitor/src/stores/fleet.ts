import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  MonitorNode, NodeState, NodeConnectionState,
  SystemStatus, HeartbeatData, AlarmInfo,
  SafetyStatus, WatchdogStatus, FleetSummary,
} from '../types'
import { calculateNodeHealth } from '../utils/formatters'

const STORAGE_KEY = 'iccsflux-monitor-nodes'

export const useFleetStore = defineStore('fleet', () => {
  // ── Persisted node configs ──────────────────────────────────────────
  const nodes = ref<MonitorNode[]>([])

  // ── Runtime state per node ──────────────────────────────────────────
  const nodeStates = ref<Map<string, NodeState>>(new Map())

  // ── Selection ───────────────────────────────────────────────────────
  const selectedNodeId = ref<string | null>(null)

  const selectedNode = computed(() =>
    selectedNodeId.value ? nodeStates.value.get(selectedNodeId.value) ?? null : null
  )

  // ── Derived lists ───────────────────────────────────────────────────
  const nodeStatesList = computed(() => Array.from(nodeStates.value.values()))

  const summary = computed<FleetSummary>(() => {
    const all = Array.from(nodeStates.value.values())
    return {
      total: all.length,
      connected: all.filter(s => s.connection.connected).length,
      healthy: all.filter(s => s.health === 'healthy').length,
      warning: all.filter(s => s.health === 'warning').length,
      error: all.filter(s => s.health === 'error').length,
      unknown: all.filter(s => s.health === 'unknown').length,
      acquiring: all.filter(s => s.status?.acquiring).length,
      recording: all.filter(s => s.status?.recording).length,
      totalAlarms: all.reduce((sum, s) =>
        sum + Array.from(s.alarms.values()).filter(a => a.active).length, 0
      ),
    }
  })

  // ── State helpers ───────────────────────────────────────────────────

  function makeNodeState(node: MonitorNode): NodeState {
    return {
      node,
      connection: {
        connected: false,
        connecting: false,
        reconnectAttempts: 0,
        lastConnectTime: null,
        lastDisconnectTime: null,
        error: null,
      },
      status: null,
      heartbeat: null,
      alarms: new Map(),
      safety: null,
      watchdog: null,
      lastMessageTime: 0,
      health: 'unknown',
      healthReasons: [],
    }
  }

  function recalcHealth(nodeId: string) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    const details = calculateNodeHealth(state)
    state.health = details.overall
    state.healthReasons = details.reasons
  }

  // ── Update methods (called by useFleetMqtt) ─────────────────────────

  function updateConnection(nodeId: string, patch: Partial<NodeConnectionState>) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    Object.assign(state.connection, patch)
    recalcHealth(nodeId)
  }

  function updateStatus(nodeId: string, data: SystemStatus) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    state.status = data
    state.lastMessageTime = Date.now()
    recalcHealth(nodeId)
  }

  function updateHeartbeat(nodeId: string, data: HeartbeatData) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    state.heartbeat = data
    state.lastMessageTime = Date.now()
  }

  function updateAlarm(nodeId: string, data: AlarmInfo) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    if (data.active) {
      state.alarms.set(data.alarm_id, data)
    } else {
      state.alarms.delete(data.alarm_id)
    }
    recalcHealth(nodeId)
  }

  function clearAlarms(nodeId: string) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    state.alarms.clear()
    recalcHealth(nodeId)
  }

  function updateSafety(nodeId: string, data: SafetyStatus) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    state.safety = data
    recalcHealth(nodeId)
  }

  function updateWatchdog(nodeId: string, data: WatchdogStatus) {
    const state = nodeStates.value.get(nodeId)
    if (!state) return
    state.watchdog = data
    recalcHealth(nodeId)
  }

  // ── CRUD ────────────────────────────────────────────────────────────

  function addNode(node: MonitorNode) {
    nodes.value.push(node)
    nodeStates.value.set(node.id, makeNodeState(node))
    saveNodes()
  }

  function updateNode(nodeId: string, patch: Partial<MonitorNode>) {
    const idx = nodes.value.findIndex(n => n.id === nodeId)
    if (idx === -1) return
    const existing = nodes.value[idx]!
    Object.assign(existing, patch)
    const state = nodeStates.value.get(nodeId)
    if (state) state.node = existing
    saveNodes()
  }

  function removeNode(nodeId: string) {
    const idx = nodes.value.findIndex(n => n.id === nodeId)
    if (idx !== -1) nodes.value.splice(idx, 1)
    nodeStates.value.delete(nodeId)
    if (selectedNodeId.value === nodeId) selectedNodeId.value = null
    saveNodes()
  }

  function selectNode(nodeId: string | null) {
    selectedNodeId.value = nodeId
  }

  // ── Persistence ─────────────────────────────────────────────────────

  function loadNodes() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const parsed: MonitorNode[] = JSON.parse(raw)
      nodes.value = parsed
      for (const node of parsed) {
        nodeStates.value.set(node.id, makeNodeState(node))
      }
    } catch (e) {
      console.error('Failed to load monitor nodes:', e)
    }
  }

  function saveNodes() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nodes.value))
  }

  // Initialize on store creation
  loadNodes()

  return {
    // State
    nodes,
    nodeStates,
    selectedNodeId,
    selectedNode,
    nodeStatesList,
    summary,
    // Updates
    updateConnection,
    updateStatus,
    updateHeartbeat,
    updateAlarm,
    clearAlarms,
    updateSafety,
    updateWatchdog,
    recalcHealth,
    // CRUD
    addNode,
    updateNode,
    removeNode,
    selectNode,
  }
})
