import type { NodeState, NodeHealthDetails, NodeHealth } from '../types'

/** Format seconds to human-readable uptime (e.g. "3d 5h", "2h 15m", "45s") */
export function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    return `${h}h ${m}m`
  }
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  return `${d}d ${h}h`
}

/** Format bytes to human-readable size */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

/** Format ISO timestamp to local time string */
export function formatTimestamp(timestamp: string | undefined | null): string {
  if (!timestamp) return 'Never'
  try {
    return new Date(timestamp).toLocaleString()
  } catch {
    return 'Invalid'
  }
}

/** Format milliseconds-ago to relative time (e.g. "2m ago") */
export function formatRelativeTime(epochMs: number): string {
  if (epochMs === 0) return 'Never'
  const diff = Date.now() - epochMs
  if (diff < 1000) return 'just now'
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

/** Calculate derived health status from all node data */
export function calculateNodeHealth(state: NodeState): NodeHealthDetails {
  const reasons: string[] = []
  let hasError = false
  let hasWarning = false

  // Not connected at all
  if (!state.connection.connected) {
    return { overall: 'error', reasons: ['Disconnected from MQTT broker'] }
  }

  // No status data received yet
  if (!state.status) {
    return { overall: 'unknown', reasons: ['Waiting for status data'] }
  }

  // Heartbeat stale (> 10s since last message)
  if (state.lastMessageTime > 0 && (Date.now() - state.lastMessageTime) > 10_000) {
    hasError = true
    reasons.push('Heartbeat stale (>10s)')
  }

  // Hardware health
  if (state.status.hardware_health) {
    const hw = state.status.hardware_health
    if (hw.reader_died) {
      hasError = true
      reasons.push('Hardware reader died')
    } else if (!hw.healthy) {
      hasError = true
      reasons.push('Hardware unhealthy')
    } else if (hw.error_count > 0) {
      hasWarning = true
      reasons.push(`Hardware errors: ${hw.error_count}`)
    }
    if (hw.watchdog_triggered) {
      hasError = true
      reasons.push('Hardware watchdog triggered')
    }
  }

  // Critical alarms
  const alarms = Array.from(state.alarms.values()).filter(a => a.active)
  const criticalCount = alarms.filter(a =>
    a.severity === 'CRITICAL' || a.severity === 'HIGH'
  ).length
  const warningCount = alarms.filter(a =>
    a.severity === 'WARNING' || a.severity === 'MEDIUM' || a.severity === 'LOW'
  ).length

  if (criticalCount > 0) {
    hasError = true
    reasons.push(`${criticalCount} critical alarm${criticalCount > 1 ? 's' : ''}`)
  }
  if (warningCount > 0) {
    hasWarning = true
    reasons.push(`${warningCount} warning alarm${warningCount > 1 ? 's' : ''}`)
  }

  // Safety tripped
  if (state.safety?.isTripped) {
    hasError = true
    reasons.push('Safety interlock TRIPPED')
  }

  // Watchdog failsafe
  if (state.watchdog?.failsafe_triggered) {
    hasError = true
    reasons.push('Watchdog failsafe triggered')
  }

  // Resource warnings
  if (state.status.cpu_percent != null && state.status.cpu_percent > 90) {
    hasWarning = true
    reasons.push(`CPU ${state.status.cpu_percent.toFixed(0)}%`)
  }
  if (state.status.disk_percent != null && state.status.disk_percent > 90) {
    hasWarning = true
    reasons.push(`Disk ${state.status.disk_percent.toFixed(0)}% used`)
  }

  // Derive overall health
  let overall: NodeHealth
  if (hasError) {
    overall = 'error'
  } else if (hasWarning) {
    overall = 'warning'
  } else {
    overall = 'healthy'
    reasons.push('All systems operational')
  }

  return { overall, reasons }
}
