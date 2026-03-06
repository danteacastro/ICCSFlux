/**
 * Node health composable — detects offline-but-reachable edge nodes
 * and shows informational alerts in the dashboard.
 *
 * Subscribes to: nisystem/nodes/+/credential_status
 */

import { ref, onUnmounted, computed } from 'vue'
import type { CredentialStatus } from '../types'

export function useCredentialPush(mqtt: {
  connected: { value: boolean }
  subscribe: <T>(topic: string, callback: (payload: T, topic?: string) => void) => () => void
}) {
  const desyncedNodes = ref<Map<string, CredentialStatus>>(new Map())

  const hasDesyncedNodes = computed(() => desyncedNodes.value.size > 0)

  // Subscribe to credential status updates from DAQ service
  const unsubStatus = mqtt.subscribe<CredentialStatus>(
    'credential_status',
    (payload: CredentialStatus, topic?: string) => {
      if (!payload.node_id) return

      if (payload.diagnosis === 'offline_reachable') {
        desyncedNodes.value.set(payload.node_id, payload)
      } else {
        desyncedNodes.value.delete(payload.node_id)
      }
    }
  )

  function dismissNode(nodeId: string) {
    desyncedNodes.value.delete(nodeId)
  }

  onUnmounted(() => {
    unsubStatus()
  })

  return {
    desyncedNodes,
    hasDesyncedNodes,
    dismissNode,
  }
}
