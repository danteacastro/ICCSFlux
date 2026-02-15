// ============================================================================
// ICCSFlux Fleet Monitor — Type Definitions
// ============================================================================

/** User-configured node to monitor */
export interface MonitorNode {
  id: string
  name: string
  host: string
  port: number
  username: string
  password: string
  enabled: boolean
}

/** MQTT connection state per node */
export interface NodeConnectionState {
  connected: boolean
  connecting: boolean
  reconnectAttempts: number
  lastConnectTime: number | null
  lastDisconnectTime: number | null
  error: string | null
}

/** Hardware health (from status/system → hardware_health) */
export interface HardwareHealth {
  running: boolean
  thread_alive: boolean
  reader_died: boolean
  error_count: number
  recovery_attempts: number
  healthy: boolean
  watchdog_triggered?: boolean
  watchdog_active?: boolean
}

/** System status payload (from nisystem/status/system, retained) */
export interface SystemStatus {
  status: string
  timestamp: string
  node_id?: string
  node_name?: string
  node_type?: string
  project_mode?: string
  simulation_mode?: boolean
  acquiring: boolean
  acquisition_state?: string
  recording: boolean
  recording_filename?: string | null
  recording_duration?: string
  recording_duration_seconds?: number
  recording_bytes?: number
  recording_samples?: number
  recording_mode?: string
  channel_count: number
  scan_rate_hz: number
  publish_rate_hz: number
  dt_scan_ms?: number
  dt_publish_ms?: number
  scan_timing?: {
    mean_ms: number
    std_dev_ms: number
    min_ms: number
    max_ms: number
    p95_ms: number
    p99_ms: number
  }
  cpu_percent?: number
  memory_mb?: number
  disk_percent?: number
  disk_used_gb?: number
  disk_total_gb?: number
  resource_monitoring?: boolean
  session_active?: boolean
  sequences_active?: number
  sequences_total?: number
  hardware_health?: HardwareHealth
  hardware_sources?: Record<string, number>
  config_path?: string
  authenticated?: boolean
  auth_user?: string | null
  scheduler_enabled?: boolean
}

/** Heartbeat payload (from nisystem/heartbeat, every 2s) */
export interface HeartbeatData {
  sequence: number
  timestamp: string
  acquiring: boolean
  recording: boolean
  mode?: string
  thread_health?: {
    scan: boolean
    publish: boolean
    heartbeat: boolean
  }
  uptime_seconds?: number
  scan_rate_actual_hz?: number
  publish_rate_actual_hz?: number
}

/** Alarm info (from nisystem/alarms/active/{id}, retained) */
export interface AlarmInfo {
  alarm_id: string
  active: boolean
  name?: string
  severity: string
  channel: string
  value?: number
  limit?: number
  message: string
  triggered_at: string
  acknowledged: boolean
  shelved?: boolean
}

/** Safety/interlock status (from nisystem/safety/status) */
export interface SafetyStatus {
  latchState: string
  isTripped: boolean
  lastTripTime?: string | null
  lastTripReason?: string | null
  hasFailedInterlocks: boolean
  interlockStatuses: InterlockStatusInfo[]
}

export interface InterlockStatusInfo {
  id: string
  name: string
  enabled: boolean
  satisfied: boolean
  bypassed: boolean
  message?: string
  failedConditions?: string[]
  hasOfflineChannels?: boolean
}

/** Watchdog status (from nisystem/watchdog/status, retained) */
export interface WatchdogStatus {
  status: string
  monitoring: boolean
  daq_online: boolean
  failsafe_triggered: boolean
  failsafe_trigger_time?: string | null
  last_heartbeat?: string | null
  timeout_sec: number
  timestamp?: string | null
}

/** Overall health level */
export type NodeHealth = 'healthy' | 'warning' | 'error' | 'unknown'

/** Detailed health breakdown */
export interface NodeHealthDetails {
  overall: NodeHealth
  reasons: string[]
}

/** Combined runtime state for a single node */
export interface NodeState {
  node: MonitorNode
  connection: NodeConnectionState
  status: SystemStatus | null
  heartbeat: HeartbeatData | null
  alarms: Map<string, AlarmInfo>
  safety: SafetyStatus | null
  watchdog: WatchdogStatus | null
  lastMessageTime: number
  health: NodeHealth
  healthReasons: string[]
}

/** Fleet summary (computed from all nodes) */
export interface FleetSummary {
  total: number
  connected: number
  healthy: number
  warning: number
  error: number
  unknown: number
  acquiring: number
  recording: number
  totalAlarms: number
}
