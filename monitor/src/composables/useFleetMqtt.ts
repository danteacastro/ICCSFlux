import { watch } from 'vue'
import mqtt, { type MqttClient } from 'mqtt'
import { useFleetStore } from '../stores/fleet'
import type { MonitorNode } from '../types'

/** Active MQTT clients keyed by node id */
const clients = new Map<string, MqttClient>()

/** Stale-heartbeat check interval */
let staleCheckTimer: ReturnType<typeof setInterval> | null = null

let initialized = false

export function useFleetMqtt() {
  const store = useFleetStore()

  // ── Initialization ──────────────────────────────────────────────────

  function init() {
    if (initialized) return
    initialized = true

    // Connect all enabled nodes
    for (const node of store.nodes) {
      if (node.enabled) connectNode(node)
    }

    // Watch for node list changes (add / remove / enable toggle)
    watch(() => store.nodes, (current) => {
      // Connect newly enabled nodes
      for (const node of current) {
        if (node.enabled && !clients.has(node.id)) {
          connectNode(node)
        } else if (!node.enabled && clients.has(node.id)) {
          disconnectNode(node.id)
        }
      }
      // Disconnect removed nodes
      const currentIds = new Set(current.map(n => n.id))
      for (const id of clients.keys()) {
        if (!currentIds.has(id)) disconnectNode(id)
      }
    }, { deep: true })

    // Periodic stale-heartbeat check (every 5s)
    if (!staleCheckTimer) {
      staleCheckTimer = setInterval(() => {
        for (const [nodeId] of clients) {
          store.recalcHealth(nodeId)
        }
      }, 5_000)
    }
  }

  // ── Per-node connection ─────────────────────────────────────────────

  function connectNode(node: MonitorNode) {
    if (clients.has(node.id)) return

    store.updateConnection(node.id, { connecting: true, error: null })

    const url = `ws://${node.host}:${node.port}`
    const client = mqtt.connect(url, {
      clientId: `monitor_${node.id}_${Date.now()}`,
      username: node.username,
      password: node.password,
      clean: true,
      reconnectPeriod: 5_000,
      connectTimeout: 10_000,
    })

    clients.set(node.id, client)

    client.on('connect', () => {
      store.updateConnection(node.id, {
        connected: true,
        connecting: false,
        reconnectAttempts: 0,
        lastConnectTime: Date.now(),
        error: null,
      })

      // Subscribe to all status topics
      client.subscribe([
        'nisystem/status/system',
        'nisystem/status/service',
        'nisystem/heartbeat',
        'nisystem/alarms/active/#',
        'nisystem/alarms/cleared',
        'nisystem/safety/status',
        'nisystem/watchdog/status',
      ])
    })

    client.on('message', (topic: string, payload: Buffer) => {
      try {
        const data = JSON.parse(payload.toString())
        routeMessage(node.id, topic, data)
      } catch {
        // Ignore non-JSON messages
      }
    })

    client.on('error', (err: Error) => {
      store.updateConnection(node.id, { error: err.message })
    })

    client.on('close', () => {
      store.updateConnection(node.id, {
        connected: false,
        connecting: false,
        lastDisconnectTime: Date.now(),
      })
    })

    client.on('reconnect', () => {
      const state = store.nodeStates.get(node.id)
      const attempts = (state?.connection.reconnectAttempts ?? 0) + 1
      store.updateConnection(node.id, { reconnectAttempts: attempts, connecting: true })
    })
  }

  function disconnectNode(nodeId: string) {
    const client = clients.get(nodeId)
    if (!client) return
    client.end(true)
    clients.delete(nodeId)
    store.updateConnection(nodeId, {
      connected: false,
      connecting: false,
      lastDisconnectTime: Date.now(),
    })
  }

  function reconnectNode(nodeId: string) {
    disconnectNode(nodeId)
    const node = store.nodes.find(n => n.id === nodeId)
    if (node) setTimeout(() => connectNode(node), 200)
  }

  function disconnectAll() {
    for (const id of [...clients.keys()]) disconnectNode(id)
    if (staleCheckTimer) {
      clearInterval(staleCheckTimer)
      staleCheckTimer = null
    }
    initialized = false
  }

  // ── Message routing ─────────────────────────────────────────────────

  function routeMessage(nodeId: string, topic: string, data: unknown) {
    if (topic === 'nisystem/status/system') {
      store.updateStatus(nodeId, data as any)
    } else if (topic === 'nisystem/heartbeat') {
      store.updateHeartbeat(nodeId, data as any)
    } else if (topic.startsWith('nisystem/alarms/active/')) {
      store.updateAlarm(nodeId, data as any)
    } else if (topic === 'nisystem/alarms/cleared') {
      store.clearAlarms(nodeId)
    } else if (topic === 'nisystem/safety/status') {
      store.updateSafety(nodeId, data as any)
    } else if (topic === 'nisystem/watchdog/status') {
      store.updateWatchdog(nodeId, data as any)
    }
  }

  return { init, connectNode, disconnectNode, reconnectNode, disconnectAll }
}
