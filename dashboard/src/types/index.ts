// Channel and system types matching the Python backend

export type ChannelType =
  | 'thermocouple'
  | 'voltage'
  | 'current'
  | 'rtd'
  | 'strain'
  | 'iepe'
  | 'counter'
  | 'resistance'
  | 'digital_input'
  | 'digital_output'
  | 'analog_output'

export type WidgetType =
  | 'numeric'
  | 'gauge'
  | 'led'
  | 'chart'
  | 'table'
  | 'setpoint'
  | 'toggle'
  | 'title'
  | 'sparkline'
  | 'alarm_summary'
  | 'recording_status'
  | 'system_status'
  | 'interlock_status'
  | 'multi_channel_table'
  | 'action_button'
  | 'clock'
  | 'divider'
  | 'bar_graph'
  | 'scheduler_status'
  | 'sequence_status'

export interface ChannelConfig {
  name: string
  display_name: string
  channel_type: ChannelType
  unit: string
  group: string
  description?: string
  low_limit?: number
  high_limit?: number
  low_warning?: number
  high_warning?: number
  chartable?: boolean
  color?: string
  widget?: WidgetType

  // Scaling parameters
  scale_slope?: number
  scale_offset?: number
  scale_type?: 'none' | 'linear' | 'map' | 'four_twenty'
  // 4-20mA scaling
  four_twenty_scaling?: boolean
  eng_units_min?: number
  eng_units_max?: number
  // Map scaling
  pre_scaled_min?: number
  pre_scaled_max?: number
  scaled_min?: number
  scaled_max?: number
  // Scaling info from backend (for display/validation)
  scaling_info?: {
    type: string
    formula?: string
    raw_range?: [number, number]
    scaled_range?: [number, number]
    example?: string
  }

  // Thermocouple-specific
  thermocouple_type?: 'J' | 'K' | 'T' | 'E' | 'N' | 'R' | 'S' | 'B'
  cjc_source?: 'internal' | 'constant' | 'channel'

  // Ranges
  voltage_range?: number
  current_range_ma?: number

  // Digital I/O
  invert?: boolean
  default_value?: number
  default_state?: boolean

  // Safety
  safety_action?: string
  safety_interlock?: string

  // Logging
  log?: boolean
  log_interval_ms?: number
}

export interface ChannelValue {
  name: string
  value: number
  timestamp: number
  alarm?: boolean
  warning?: boolean
}

export interface SystemStatus {
  status: 'online' | 'offline' | 'error'
  timestamp: string
  simulation_mode: boolean
  acquiring: boolean
  recording: boolean
  recording_filename?: string
  recording_duration?: string // HH:MM:SS format
  recording_duration_seconds?: number
  recording_start_time?: string
  recording_bytes?: number
  recording_samples?: number
  recording_mode?: 'manual' | 'triggered' | 'scheduled'
  authenticated: boolean
  auth_user?: string
  scheduler_enabled: boolean
  scan_rate_hz: number
  publish_rate_hz: number
  dt_scan_ms: number
  dt_publish_ms: number
  channel_count: number
  config_path: string
}

// Recording configuration matching Python backend
export interface RecordingConfig {
  // File settings
  base_path: string
  file_prefix: string
  file_format: 'csv' | 'tdms'
  include_timestamp: boolean
  include_date: boolean
  // Logging rate
  log_rate_hz: number
  decimation: number
  // File management
  max_file_size_mb: number
  max_file_duration_s: number
  split_files: boolean
  // Recording mode
  mode: 'manual' | 'triggered' | 'scheduled'
  // Triggered mode settings
  trigger_channel: string
  trigger_condition: 'above' | 'below' | 'change'
  trigger_value: number
  trigger_hysteresis: number
  pre_trigger_samples: number
  post_trigger_samples: number
  // Scheduled mode settings
  schedule_start: string
  schedule_end: string
  schedule_days: string[]
  // Channel selection
  selected_channels: string[]
  include_scripts: boolean
}

export interface RecordedFile {
  name: string
  path: string
  size: number
  duration: number
  created: string
  modified?: string
  sample_count: number
  channels: string[]
}

export interface WidgetStyle {
  // Title/Label styling
  fontSize?: 'small' | 'medium' | 'large' | 'xlarge'
  textAlign?: 'left' | 'center' | 'right'
  textColor?: string
  backgroundColor?: string
  // LED/Indicator styling
  onColor?: string
  offColor?: string
  // Numeric/Gauge styling
  valueColor?: string
  borderColor?: string
}

export type ButtonActionType =
  | 'mqtt_publish'      // Publish to MQTT topic
  | 'digital_output'    // Set digital output (pulse or toggle)
  | 'script_run'        // Run a script
  | 'system_command'    // System command (start/stop acquisition, recording)

export type SystemCommandType =
  | 'acquisition_start'
  | 'acquisition_stop'
  | 'recording_start'
  | 'recording_stop'
  | 'alarm_acknowledge_all'
  | 'latch_reset_all'

export interface ButtonAction {
  type: ButtonActionType
  // For mqtt_publish
  topic?: string
  payload?: string
  // For digital_output
  channel?: string
  pulseMs?: number      // If set, pulse for this duration; otherwise toggle
  setValue?: number     // Value to set (0 or 1)
  // For script_run (sequence)
  sequenceId?: string
  // For system_command
  command?: SystemCommandType
}

export interface WidgetConfig {
  id: string
  channel?: string        // For single-channel widgets
  channels?: string[]     // For charts (multi-channel)
  type: WidgetType
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
  // Chart-specific
  timeRange?: number      // seconds
  // Display options
  decimals?: number
  showUnit?: boolean
  showAlarmStatus?: boolean
  label?: string
  // Button-specific
  buttonAction?: ButtonAction
  requireConfirmation?: boolean
  buttonColor?: string
  // Clock-specific
  showDate?: boolean
  showElapsed?: boolean
  format24h?: boolean
  // Gauge/Setpoint/BarGraph-specific
  minValue?: number
  maxValue?: number
  step?: number
  // BarGraph-specific
  orientation?: 'horizontal' | 'vertical'
  showValue?: boolean
  // Divider-specific
  lineColor?: string
  lineStyle?: 'solid' | 'dashed' | 'dotted'
  // Styling
  style?: WidgetStyle
}

export interface LayoutConfig {
  system_id: string
  user?: string
  widgets: WidgetConfig[]
  gridColumns: number
  rowHeight: number
}

export interface SystemConfig {
  id: string
  name: string
  mqtt_prefix: string
  channels: Record<string, ChannelConfig>
}

export interface DashboardConfig {
  name: string
  theme: 'dark' | 'light'
  gridColumns: number
  rowHeight: number
  maxCharts: number
  systems: SystemConfig[]
}

// Widget defaults by type
export const WIDGET_DEFAULTS: Record<WidgetType, Partial<WidgetConfig>> = {
  numeric: { w: 1, h: 1, minW: 1, minH: 1 },
  gauge: { w: 2, h: 2, minW: 2, minH: 2 },
  led: { w: 1, h: 1, minW: 1, minH: 1 },
  chart: { w: 4, h: 3, minW: 2, minH: 2, timeRange: 300 },
  table: { w: 3, h: 2, minW: 2, minH: 2 },
  setpoint: { w: 2, h: 1, minW: 1, minH: 1 },
  toggle: { w: 1, h: 1, minW: 1, minH: 1 },
  title: { w: 2, h: 1, minW: 1, minH: 1 },
  sparkline: { w: 2, h: 1, minW: 1, minH: 1 },
  alarm_summary: { w: 2, h: 2, minW: 2, minH: 2 },
  recording_status: { w: 2, h: 2, minW: 2, minH: 1 },
  system_status: { w: 2, h: 2, minW: 2, minH: 1 },
  interlock_status: { w: 2, h: 2, minW: 2, minH: 2 },
  multi_channel_table: { w: 2, h: 3, minW: 2, minH: 2 },
  action_button: { w: 1, h: 1, minW: 1, minH: 1 },
  clock: { w: 2, h: 1, minW: 1, minH: 1 },
  divider: { w: 3, h: 1, minW: 1, minH: 1 },
  bar_graph: { w: 2, h: 1, minW: 1, minH: 1 },
  scheduler_status: { w: 2, h: 2, minW: 2, minH: 2 },
  sequence_status: { w: 2, h: 2, minW: 2, minH: 2 }
}

// Preset colors for widgets
export const WIDGET_COLORS = {
  led: {
    on: ['#22c55e', '#3b82f6', '#fbbf24', '#ef4444', '#8b5cf6', '#ec4899'],
    off: ['#166534', '#1e3a8a', '#78350f', '#7f1d1d', '#4c1d95', '#831843']
  },
  text: ['#ffffff', '#60a5fa', '#22c55e', '#fbbf24', '#ef4444', '#a855f7', '#888888'],
  background: ['transparent', '#1a1a2e', '#0f0f1a', '#1e3a5f', '#14532d', '#7f1d1d', '#78350f'],
  button: ['#3b82f6', '#22c55e', '#ef4444', '#fbbf24', '#8b5cf6', '#ec4899', '#6b7280']
}

// ============================================
// Safety & Alarm Types
// ============================================

export type AlarmSeverity = 'alarm' | 'warning'
export type AlarmBehavior = 'latch' | 'auto_clear'
export type AlarmState = 'active' | 'acknowledged' | 'cleared'

export interface AlarmConfig {
  channel: string
  enabled: boolean
  // Thresholds
  low_alarm?: number
  high_alarm?: number
  low_warning?: number
  high_warning?: number
  // Behavior
  behavior: AlarmBehavior  // 'latch' requires manual reset, 'auto_clear' resets when value is OK
  // Filtering
  deadband: number         // Hysteresis to prevent chatter (e.g., alarm at 100, clear at 95 = 5 deadband)
  delay_seconds: number    // Value must exceed threshold for this long before triggering
  // Actions
  log_to_file: boolean
  play_sound: boolean
  start_recording: boolean
  run_script?: string      // Script name to execute on alarm
}

export interface ActiveAlarm {
  id: string               // Unique alarm instance ID
  channel: string
  severity: AlarmSeverity
  state: AlarmState
  value: number            // Value that triggered the alarm
  threshold: number        // The threshold that was exceeded
  threshold_type: 'high_alarm' | 'low_alarm' | 'high_warning' | 'low_warning'
  triggered_at: string     // ISO timestamp when alarm first triggered
  acknowledged_at?: string // ISO timestamp when acknowledged
  acknowledged_by?: string // User who acknowledged
  cleared_at?: string      // ISO timestamp when cleared
  duration_seconds: number // How long the alarm has been active
  message: string          // Human-readable alarm message
}

export interface AlarmHistoryEntry {
  id: string
  channel: string
  severity: AlarmSeverity
  value: number
  threshold: number
  threshold_type: 'high_alarm' | 'low_alarm' | 'high_warning' | 'low_warning'
  triggered_at: string
  cleared_at: string
  duration_seconds: number
  acknowledged_by?: string
  message: string
}

export interface SystemHealth {
  mqtt_connected: boolean
  daq_connected: boolean
  last_data_received?: string  // ISO timestamp
  data_timeout: boolean        // True if no data for configured timeout
  cpu_usage?: number
  memory_usage?: number
}

// ============================================
// Interlock Types
// ============================================

export type InterlockConditionType =
  | 'channel_value'    // Compare channel value to threshold
  | 'digital_input'    // Check digital input state
  | 'no_active_alarms' // No alarms of specified severity
  | 'no_latched_alarms'// All latched alarms must be cleared
  | 'mqtt_connected'   // MQTT broker connected
  | 'daq_connected'    // DAQ hardware online
  | 'acquiring'        // System is acquiring data
  | 'not_recording'    // Not currently recording

export type InterlockOperator = '<' | '<=' | '>' | '>=' | '=' | '!='

export interface InterlockCondition {
  id: string
  type: InterlockConditionType
  // For channel_value / digital_input:
  channel?: string
  operator?: InterlockOperator
  value?: number | boolean
  // Human-readable description (auto-generated if not provided)
  description?: string
}

export type InterlockControlType =
  | 'digital_output'   // Block specific digital output
  | 'schedule_enable'  // Block scheduler from starting
  | 'recording_start'  // Block recording from starting
  | 'acquisition_start'// Block acquisition from starting
  | 'button_action'    // Block specific action button

export interface InterlockControl {
  type: InterlockControlType
  channel?: string     // For digital_output type
  buttonId?: string    // For button_action type
}

export interface Interlock {
  id: string
  name: string
  enabled: boolean
  description?: string
  // ALL conditions must be TRUE for interlock to be satisfied (AND logic)
  conditions: InterlockCondition[]
  // What this interlock gates/controls
  controls: InterlockControl[]
  // Can operator bypass this interlock?
  bypassAllowed: boolean
  // Is currently bypassed?
  bypassed: boolean
  bypassedAt?: string
  bypassedBy?: string
}

export interface InterlockStatus {
  id: string
  name: string
  satisfied: boolean      // Are all conditions met?
  bypassed: boolean       // Is it bypassed?
  enabled: boolean
  failedConditions: {     // Which conditions are failing
    condition: InterlockCondition
    currentValue?: any
    reason: string
  }[]
  controls: InterlockControl[]
}
