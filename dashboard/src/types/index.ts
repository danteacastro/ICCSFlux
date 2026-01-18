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
  | 'modbus_register'
  | 'modbus_coil'

/**
 * Project mode determines system architecture:
 * - cdaq: PC is the "PLC" - reads hardware, evaluates alarms, executes safety
 * - crio: cRIO is the PLC, PC is HMI only (like Allen Bradley + FactoryTalk)
 * - opto22: Opto22 groov EPIC/RIO is the PLC, PC is HMI only
 */
export type ProjectMode = 'cdaq' | 'crio' | 'opto22'

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
  | 'action_button'
  | 'clock'
  | 'divider'
  | 'bar_graph'
  | 'scheduler_status'
  | 'svg_symbol'
  | 'value_table'
  | 'crio_status'
  | 'latch_switch'
  | 'script_monitor'

export interface ChannelConfig {
  name: string                    // TAG - the only identifier (ISA-5.1 compliant)
  // display_name removed - use name (TAG) everywhere
  channel_type: ChannelType
  physical_channel?: string  // NI-DAQmx hardware address (e.g., cDAQ1Mod1/ai0)
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

  // Visibility - hidden channels still collect data but don't appear in dropdowns
  visible?: boolean

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

  // RTD-specific
  rtd_type?: 'Pt100' | 'Pt500' | 'Pt1000' | 'custom'
  rtd_resistance?: number      // Nominal resistance at 0°C (default 100.0)
  rtd_wiring?: '2-wire' | '3-wire' | '4-wire'
  wiring?: '2-wire' | '3-wire' | '4-wire'  // Alias for rtd_wiring (UI compatibility)
  rtd_current?: number         // Excitation current in Amps (default 0.001)

  // Voltage-specific
  terminal_config?: 'differential' | 'rse' | 'nrse' | 'pseudo_diff' | 'RSE' | 'DIFF' | 'NRSE' | 'PSEUDO_DIFF'

  // Strain-specific
  strain_config?: 'full-bridge' | 'half-bridge' | 'quarter-bridge'
  bridge_config?: 'full' | 'half' | 'quarter' | 'full-bridge' | 'half-bridge' | 'quarter-bridge'  // UI alias
  strain_excitation_voltage?: number  // Bridge excitation voltage (default 2.5V)
  excitation_voltage?: number  // Alias for strain_excitation_voltage (UI)
  strain_gage_factor?: number  // Gage factor (default 2.0)
  gage_factor?: number         // Alias for strain_gage_factor (UI)
  strain_resistance?: number   // Nominal gage resistance in Ohms (default 350)

  // IEPE-specific
  iepe_coupling?: 'AC' | 'DC'
  coupling?: 'AC' | 'DC'       // Alias for iepe_coupling (UI)
  iepe_sensitivity?: number    // mV/g or mV/Pa (default 100.0)
  sensitivity?: number         // Alias for iepe_sensitivity (UI)
  iepe_current?: number        // Excitation current in Amps (default 0.004)

  // Counter-specific
  counter_mode?: 'count_edges' | 'count' | 'frequency' | 'period' | 'pulse_width'
  edge?: 'rising' | 'falling'
  counter_edge?: 'rising' | 'falling'  // Backend uses this name
  pulses_per_unit?: number     // e.g., 100 pulses = 1 gallon
  counter_reset_on_read?: boolean  // For totalizer mode
  counter_min_freq?: number    // Minimum expected frequency in Hz (for nidaqmx)
  counter_max_freq?: number    // Maximum expected frequency in Hz (for nidaqmx)

  // Resistance-specific
  resistance_range?: number    // Maximum expected resistance in Ohms
  resistance_wiring?: '2-wire' | '4-wire'

  // Modbus-specific
  modbus_register_type?: 'holding' | 'input' | 'coil' | 'discrete'
  modbus_address?: number              // Register/coil address
  modbus_data_type?: 'int16' | 'uint16' | 'int32' | 'uint32' | 'float32' | 'float64' | 'bool'
  modbus_byte_order?: 'big' | 'little' // Endianness
  modbus_word_order?: 'big' | 'little' // For 32/64-bit values (word swap)
  modbus_scale?: number                // Scale factor: value = raw * scale + offset
  modbus_offset?: number               // Offset: value = raw * scale + offset
  modbus_slave_id?: number             // Explicit slave/unit ID (overrides module config)
  // Batch reading: read multiple registers, extract value at specific index
  modbus_register_count?: number       // Total registers to read (for batch reading)
  modbus_register_index?: number       // Index within batch to extract value from

  // Digital I/O
  logic_level?: '5V' | '24V'

  // Ranges
  voltage_range?: number | string  // Can be number or string like "±10V"
  current_range_ma?: number
  ao_range?: string  // Analog output range (e.g., '5V', '10V', 'pm10V')

  // Digital I/O
  invert?: boolean
  default_value?: number
  default_state?: boolean

  // Safety
  safety_action?: string
  safety_interlock?: string

  // ============================================
  // Alarm Configuration (ISA-18.2 compliant)
  // ============================================

  // Master alarm enable - if false, no limit checking for this channel
  alarm_enabled?: boolean

  // Alarm setpoints (ISA-18.2 naming: HiHi, Hi, Lo, LoLo)
  // Note: low_limit/high_limit above are legacy aliases for hi_limit/lo_limit
  hihi_limit?: number    // High-High (critical) - most severe
  hi_limit?: number      // High (warning)
  lo_limit?: number      // Low (warning)
  lolo_limit?: number    // Low-Low (critical) - most severe

  // Alarm priority level
  alarm_priority?: 'diagnostic' | 'low' | 'medium' | 'high' | 'critical'

  // Deadband (hysteresis) - prevents alarm chatter at threshold
  alarm_deadband?: number

  // On-delay - value must exceed limit for this duration before alarm triggers
  alarm_delay_sec?: number

  // Off-delay - value must be within limits for this duration before alarm clears
  alarm_clear_delay_sec?: number

  // Logging
  log?: boolean
  log_interval_ms?: number

  // Multi-node support
  source_type?: 'local' | 'crio' | 'cdaq' | 'opto22'  // Source of channel data
  node_id?: string                 // Remote node ID for cRIO channels, chassis name for cDAQ
  chassis_name?: string            // Chassis name (e.g., "cDAQ-9189", "cRIO-9056")

  // UI settings
  step?: number  // Step increment for setpoint widgets
}

export interface ChannelValue {
  name: string
  value: number
  raw_value?: number  // Raw value before scaling (for voltage/current inputs)
  timestamp: number
  alarm?: boolean
  warning?: boolean
  quality?: 'good' | 'bad' | 'alarm' | 'warning' | 'uncertain'  // Data quality indicator
  disconnected?: boolean  // True when hardware device is not connected
  // Specific error states for better diagnostics
  openThermocouple?: boolean  // True when thermocouple is open/broken
  overflow?: boolean  // True when value exceeds measurement range
  valueString?: string | null  // Human-readable error: "NaN", "Open TC", "Inf"
  status?: 'normal' | 'disconnected' | 'open_thermocouple' | 'overflow' | 'low_limit' | 'high_limit' | 'low_warning' | 'high_warning'
  // Multi-node support
  nodeId?: string  // Source node ID (for multi-node deployments)
  // SOE (Sequence of Events) support - microsecond precision
  acquisitionTsUs?: number  // Microseconds since epoch (from hardware acquisition time)
}

// Multi-node support
export interface NodeInfo {
  nodeId: string
  nodeName: string
  status: 'online' | 'offline' | 'unknown'
  lastSeen: number  // Unix timestamp ms
  simulationMode: boolean
  configVersion?: string      // Reported by cRIO node in status
  expectedVersion?: string    // What PC expects from last push
  configSynced?: boolean      // configVersion === expectedVersion
}

export interface SystemStatus {
  status: 'online' | 'offline' | 'error'
  timestamp: string
  simulation_mode: boolean
  acquiring: boolean
  acquisition_state?: 'stopped' | 'initializing' | 'running'
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
  // Multi-node support
  node_id?: string   // Unique node identifier
  node_name?: string // Human-readable node name
  // Project mode (cdaq = PC is PLC, crio = cRIO is PLC)
  project_mode?: ProjectMode
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

// LabVIEW-style chart types
export type ChartUpdateMode = 'strip' | 'scope' | 'sweep'
export type ChartToolMode = 'cursor' | 'zoom' | 'pan' | 'none'

export interface ChartCursor {
  id: string
  x: number              // X position (timestamp)
  color: string
  label?: string
  locked?: boolean       // Whether cursor can be dragged
}

export interface ChartPlotStyle {
  channel: string
  color: string
  lineWidth: number
  lineStyle: 'solid' | 'dashed' | 'dotted'
  showMarkers: boolean
  markerStyle: 'circle' | 'square' | 'triangle' | 'diamond'
  yAxisId: number        // Which Y-axis this trace uses (0 = left, 1 = right)
  visible: boolean
}

export interface ChartYAxis {
  id: number
  label?: string
  auto: boolean
  min: number
  max: number
  position: 'left' | 'right'
  color?: string         // Axis color (matches trace if single trace)
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
  timeRange?: number      // seconds (X-axis range)
  historySize?: number    // Max data points to keep (default 1024)
  updateMode?: ChartUpdateMode  // strip, scope, sweep (default strip)
  // Y-axis settings
  yAxisAuto?: boolean     // Auto-scale Y axis (default true)
  yAxisMin?: number       // Manual Y min (when yAxisAuto=false)
  yAxisMax?: number       // Manual Y max (when yAxisAuto=false)
  yAxes?: ChartYAxis[]    // Multiple Y-axis config
  // Display options for chart
  showGrid?: boolean      // Show grid lines (default true)
  showLegend?: boolean    // Show legend (default true)
  showScrollbar?: boolean // Show X-axis scrollbar for history
  showDigitalDisplay?: boolean  // Show current value for each trace
  stackPlots?: boolean    // Stack traces vertically vs overlay
  // Plot styling per channel
  plotStyles?: ChartPlotStyle[]
  // Cursor configuration
  cursors?: ChartCursor[]
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
  // SVG Symbol-specific
  symbol?: string           // Symbol type from SCADA_SYMBOLS
  valuePosition?: 'top' | 'bottom' | 'left' | 'right' | 'inside'
  showLabel?: boolean
  accentColor?: string
  symbolSize?: 'small' | 'medium' | 'large'
  rotation?: 0 | 90 | 180 | 270  // Symbol rotation
  // Text Label-specific
  text?: string             // Static text content
  fontSize?: 'small' | 'medium' | 'large' | 'xlarge'
  textAlign?: 'left' | 'center' | 'right'
  textColor?: string
  // Compact mode (for numeric, led, etc.)
  compact?: boolean         // Hide label, show only value
  industrial?: boolean      // Industrial/LabVIEW-style theme
  // Value Table-specific
  showUnits?: boolean       // Show unit column in tables
  showStatus?: boolean      // Show status indicator
  maxRows?: number          // Limit visible rows
  // Script Monitor-specific
  items?: Array<{
    tag: string
    label?: string
    unit?: string
    format?: 'number' | 'integer' | 'percent' | 'status' | 'text'
    decimals?: number
    thresholds?: {
      low?: number
      high?: number
      lowColor?: string
      highColor?: string
    }
  }>
  columns?: 1 | 2 | 3
  showTimestamp?: boolean
  refreshRate?: number
  // Styling
  style?: WidgetStyle
}

// Pipe/Connection point on grid
export interface PipePoint {
  x: number  // Grid x coordinate
  y: number  // Grid y coordinate
}

// Pipe connection between widgets or free-form
export interface PipeConnection {
  id: string
  // Waypoints define the path (orthogonal segments)
  // First and last points can optionally be anchored to widgets
  points: PipePoint[]
  // Optional: anchor to widget connection ports
  startWidgetId?: string
  startPort?: 'top' | 'bottom' | 'left' | 'right'
  endWidgetId?: string
  endPort?: 'top' | 'bottom' | 'left' | 'right'
  // Styling
  color?: string
  strokeWidth?: number
  dashed?: boolean
  animated?: boolean  // Animated flow direction
  label?: string      // Optional pipe label (e.g., "Steam", "H2")
}

// ============================================================================
// P&ID Canvas Layer Types (Free-Form, Pixel-Based)
// ============================================================================

// Free-form point in pixel coordinates (not grid)
export interface PidPoint {
  x: number  // Pixel x coordinate
  y: number  // Pixel y coordinate
}

// Free-form P&ID symbol (valve, pump, tank, etc.)
export interface PidSymbol {
  id: string
  type: string  // Symbol type from SCADA_SYMBOLS (e.g., 'solenoidValve', 'pump')
  // Position in pixels (free-form, not grid-locked)
  x: number
  y: number
  // Size in pixels (true resizing)
  width: number
  height: number
  // Rotation in degrees (any angle, not just 0/90/180/270)
  rotation?: number
  // Optional channel binding for live data
  channel?: string
  // Styling
  label?: string
  color?: string
  showValue?: boolean
  decimals?: number
  // Z-index for layering
  zIndex?: number
}

// Free-form pipe (bezier/polyline, not orthogonal-only)
export interface PidPipe {
  id: string
  // Path points in pixels (click anywhere to add points)
  points: PidPoint[]
  // Path type
  pathType: 'polyline' | 'bezier' | 'orthogonal'
  // Styling
  color?: string
  strokeWidth?: number
  dashed?: boolean
  animated?: boolean
  label?: string
  // Arrow markers
  startArrow?: boolean
  endArrow?: boolean
  // Z-index for layering
  zIndex?: number
}

// P&ID layer data for a page
export interface PidLayerData {
  symbols: PidSymbol[]
  pipes: PidPipe[]
  // Layer visibility toggle
  visible?: boolean
  // Layer opacity (for showing behind grid widgets)
  opacity?: number
}

// Dashboard Page - each page has its own widget layout
export interface DashboardPage {
  id: string
  name: string
  widgets: WidgetConfig[]
  pipes?: PipeConnection[]  // Legacy: grid-locked pipe connections
  pidLayer?: PidLayerData   // New: free-form P&ID layer
  order: number             // Sort order
  createdAt?: string
}

export interface LayoutConfig {
  system_id: string
  user?: string
  widgets: WidgetConfig[]  // Legacy: widgets for default page
  gridColumns: number
  rowHeight: number
  // Multi-page support
  pages?: DashboardPage[]
  currentPageId?: string
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
  action_button: { w: 1, h: 1, minW: 1, minH: 1 },
  clock: { w: 2, h: 1, minW: 1, minH: 1 },
  divider: { w: 3, h: 1, minW: 1, minH: 1 },
  bar_graph: { w: 2, h: 1, minW: 1, minH: 1 },
  scheduler_status: { w: 2, h: 2, minW: 2, minH: 2 },
  svg_symbol: { w: 2, h: 2, minW: 1, minH: 1 },
  value_table: { w: 3, h: 4, minW: 2, minH: 2 },
  crio_status: { w: 2, h: 2, minW: 2, minH: 2 },
  latch_switch: { w: 1, h: 1, minW: 1, minH: 1 },
  script_monitor: { w: 3, h: 4, minW: 2, minH: 2 }
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
// Safety & Alarm Types (ISA-18.2 aligned)
// ============================================

// Alarm severity levels (ISA-18.2 style)
export type AlarmSeverityLevel = 'critical' | 'high' | 'medium' | 'low'

// Legacy severity type for backward compatibility
export type AlarmSeverity = 'alarm' | 'warning'

// Latch behavior
export type AlarmBehavior = 'latch' | 'auto_clear' | 'timed_latch'

// Alarm lifecycle states
export type AlarmState = 'normal' | 'active' | 'acknowledged' | 'returned' | 'shelved' | 'out_of_service'

// Threshold types (includes digital_state for DI alarms)
export type ThresholdType = 'high_high' | 'high' | 'low' | 'low_low' | 'rate' | 'digital_state'

// ============================================
// Safety Action Types (ISA-18.2 / IEC 62682)
// ============================================

/**
 * Safety action executed when alarm triggers
 * Maps alarm severity to automatic responses
 */
export type SafetyActionType =
  | 'trip_system'           // Full system trip - all outputs to safe state
  | 'stop_session'          // Stop test session only
  | 'stop_recording'        // Stop recording only
  | 'set_output_safe'       // Set specific output(s) to safe state
  | 'run_sequence'          // Run a safety sequence
  | 'custom'                // Custom action via MQTT

export interface SafetyAction {
  id: string
  name: string
  description?: string
  type: SafetyActionType
  enabled: boolean

  // For set_output_safe: which outputs and what state
  outputChannels?: string[]
  safeValue?: number        // 0 for OFF, 1 for ON (for DO)
  analogSafeValue?: number  // For AO channels

  // For run_sequence
  sequenceId?: string

  // For custom action
  mqttTopic?: string
  mqttPayload?: any

  // Audit
  lastTriggeredAt?: string
  lastTriggeredBy?: string  // Alarm ID that triggered it
}

/**
 * Digital input alarm configuration
 * Supports inverted logic (normally-closed vs normally-open)
 */
export interface DigitalAlarmConfig {
  // Expected "safe" state - alarm triggers when state != expected
  expectedState: boolean    // true = expect HIGH (1), false = expect LOW (0)
  invert: boolean           // Invert the input before comparison
  // Debounce to prevent chatter
  debounceMs?: number
}

export interface AlarmConfig {
  id: string               // Unique alarm ID
  channel: string
  name: string             // Human-readable name
  description?: string
  enabled: boolean

  // Severity level
  severity: AlarmSeverityLevel

  // Thresholds (ISA-18.2 style: HH, H, L, LL)
  high_high?: number       // Critical high (most severe)
  high?: number            // High warning
  low?: number             // Low warning
  low_low?: number         // Critical low (most severe)

  // Legacy threshold names for backward compatibility
  high_alarm?: number      // Maps to high_high
  low_alarm?: number       // Maps to low_low
  high_warning?: number    // Maps to high
  low_warning?: number     // Maps to low

  // Deadband prevents alarm chatter at threshold boundary
  deadband: number

  // Time-based filtering
  on_delay_s: number       // Must be in alarm for X seconds before triggering (was delay_seconds)
  off_delay_s: number      // Must be clear for X seconds before clearing
  delay_seconds?: number   // Legacy alias for on_delay_s

  // Rate-of-change alarm
  rate_limit?: number      // Max change per second
  rate_window_s?: number   // Time window for rate calculation

  // Behavior
  behavior: AlarmBehavior
  timed_latch_s?: number   // For 'timed_latch': seconds after clear to auto-reset

  // Actions
  actions?: string[]       // Action IDs to execute on alarm
  log_to_file: boolean
  play_sound: boolean
  start_recording: boolean
  run_script?: string

  // Grouping
  group?: string           // Alarm group (e.g., "Zone1", "Coolant")
  priority?: number        // Priority within severity (for first-out)

  // Shelving
  max_shelve_time_s?: number  // Max time alarm can be shelved (default 1 hour)
  shelve_allowed?: boolean

  // Safety action (ISA-18.2 high-severity response)
  safety_action?: string     // SafetyAction ID to execute when alarm triggers

  // Digital input alarm configuration (nested structure)
  digital_alarm?: DigitalAlarmConfig

  // Digital alarm flat properties (convenience aliases for forms)
  digital_alarm_enabled?: boolean
  digital_expected_state?: boolean
  digital_invert?: boolean
  digital_debounce_ms?: number
}

export interface ActiveAlarm {
  id: string               // Unique alarm instance ID (alarm_id from backend)
  alarm_id?: string        // Reference to AlarmConfig.id
  channel: string
  name?: string            // Human-readable name from config
  severity: AlarmSeverity | AlarmSeverityLevel
  state: AlarmState
  value: number            // Value that triggered the alarm (triggered_value)
  threshold: number        // The threshold that was exceeded
  threshold_type: ThresholdType | 'high_alarm' | 'low_alarm' | 'high_warning' | 'low_warning'
  current_value?: number   // Current channel value
  triggered_at: string     // ISO timestamp when alarm first triggered
  acknowledged_at?: string // ISO timestamp when acknowledged
  acknowledged_by?: string // User who acknowledged
  cleared_at?: string      // ISO timestamp when cleared
  duration_seconds: number // How long the alarm has been active
  message: string          // Human-readable alarm message

  // First-out tracking
  sequence_number?: number  // Global sequence for first-out
  is_first_out?: boolean    // First alarm in a cascade

  // Multi-node support
  nodeId?: string           // Source node ID for multi-node systems

  // Shelving
  shelved_at?: string
  shelved_by?: string
  shelve_expires_at?: string
  shelve_reason?: string

  // Safety action (from AlarmConfig)
  safety_action?: string     // SafetyAction ID to execute
}

export interface AlarmHistoryEntry {
  id: string
  alarm_id?: string        // Reference to AlarmConfig.id
  channel: string
  event_type: 'triggered' | 'acknowledged' | 'cleared' | 'reset' | 'shelved' | 'unshelved'
  severity: AlarmSeverity | AlarmSeverityLevel
  value?: number
  threshold?: number
  threshold_type?: ThresholdType | 'high_alarm' | 'low_alarm' | 'high_warning' | 'low_warning'
  triggered_at: string
  cleared_at?: string
  duration_seconds?: number
  user?: string
  acknowledged_by?: string  // Legacy alias for user
  message: string
}

export interface AlarmCounts {
  total: number
  active: number
  acknowledged: number
  returned: number
  shelved: number
  critical: number
  high: number
  medium: number
  low: number
  // Legacy counts
  warnings?: number
}

export interface AlarmStats {
  total_alarms: number
  total_acknowledged: number
  total_cleared: number
  total_shelved: number
  counts: AlarmCounts
  first_out?: string       // Alarm ID of first-out alarm
  config_count: number
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
// Interlock Types (IEC 61511 / ISA-84 Compliant)
// ============================================

export type InterlockConditionType =
  | 'channel_value'    // Compare channel value to threshold
  | 'digital_input'    // Check digital input state
  | 'alarm_active'     // Specific alarm is active
  | 'alarm_state'      // Alarm is in specific state (active, acknowledged, shelved)
  | 'no_active_alarms' // No alarms of specified severity
  | 'no_latched_alarms'// All latched alarms must be cleared
  | 'mqtt_connected'   // MQTT broker connected
  | 'daq_connected'    // DAQ hardware online
  | 'acquiring'        // System is acquiring data
  | 'not_recording'    // Not currently recording
  | 'expression'       // Custom expression (channel math)
  | 'variable_value'   // User variable comparison

export type InterlockOperator = '<' | '<=' | '>' | '>=' | '=' | '!='

// Logic for combining conditions within a group
export type ConditionLogic = 'AND' | 'OR'

// Voting logic types (IEC 61508)
export type VotingLogic =
  | '1oo1'  // 1 out of 1 (simple)
  | '1oo2'  // 1 out of 2 (any one)
  | '2oo2'  // 2 out of 2 (both required)
  | '2oo3'  // 2 out of 3 (majority)
  | '1oo3'  // 1 out of 3 (any one of three)

export interface InterlockCondition {
  id: string
  type: InterlockConditionType
  // For channel_value / digital_input:
  channel?: string
  operator?: InterlockOperator
  value?: number | boolean
  // For digital_input: invert the input before comparison (NC vs NO)
  invert?: boolean
  // For alarm_active / alarm_state:
  alarmId?: string
  alarmState?: 'active' | 'acknowledged' | 'shelved' | 'returned'
  // For expression:
  expression?: string
  // For variable_value:
  variableId?: string
  // Timer/Delay: condition must be TRUE for this duration before triggering (seconds)
  delay_s?: number
  // Timer state tracking (runtime, not persisted)
  _delayStartTime?: number
  _delayMet?: boolean
  // Human-readable description (auto-generated if not provided)
  description?: string
}

// Condition group for nested logic (A AND (B OR C))
export interface InterlockConditionGroup {
  id: string
  logic: ConditionLogic  // How to combine items in this group
  conditions: (InterlockCondition | InterlockConditionGroup)[]
  // Voting logic (optional, overrides simple AND/OR)
  voting?: VotingLogic
  votingChannels?: string[]  // For voting: list of channels to vote on
}

export type InterlockControlType =
  // BLOCKING actions (prevent user from doing something)
  | 'digital_output'      // Block specific digital output
  | 'analog_output'       // Block specific analog output / setpoint
  | 'schedule_enable'     // Block scheduler from starting
  | 'recording_start'     // Block recording from starting
  | 'acquisition_start'   // Block acquisition from starting
  | 'session_start'       // Block starting test sessions
  | 'script_start'        // Block starting backend scripts
  | 'button_action'       // Block specific action button
  // ACTIVE actions (do something when interlock conditions FAIL)
  | 'set_digital_output'  // Force DO to specific value when conditions fail
  | 'set_analog_output'   // Force AO to specific value when conditions fail
  | 'stop_session'        // Stop test session when conditions fail
  | 'stop_acquisition'    // Stop acquisition when conditions fail

export interface InterlockControl {
  type: InterlockControlType
  channel?: string     // For digital_output, set_digital_output, set_analog_output
  buttonId?: string    // For button_action type
  setValue?: number | boolean  // For set_digital_output (0/1) and set_analog_output (voltage)
}

export interface Interlock {
  id: string
  name: string
  enabled: boolean
  description?: string
  // Root condition group (supports nested AND/OR logic)
  conditionGroup?: InterlockConditionGroup
  // Legacy: flat conditions with AND logic (for backwards compatibility)
  conditions: InterlockCondition[]
  // Logic for flat conditions (default: AND)
  conditionLogic?: ConditionLogic
  // What this interlock gates/controls
  controls: InterlockControl[]
  // Can operator bypass this interlock?
  bypassAllowed: boolean
  // Max bypass duration in seconds (0 = unlimited)
  maxBypassDuration?: number
  // Is currently bypassed?
  bypassed: boolean
  bypassedAt?: string
  bypassedBy?: string
  bypassReason?: string
  // SIL Rating (IEC 61508) - informational
  silRating?: 'SIL1' | 'SIL2' | 'SIL3' | 'SIL4'
  // Proof test interval in days (IEC 61511)
  proofTestInterval?: number
  lastProofTest?: string
  // Demand tracking
  demandCount?: number
  lastDemandTime?: string
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
    delayRemaining?: number  // Seconds until delay met (if delay_s set)
  }[]
  controls: InterlockControl[]
  // Timer status
  conditionsWithDelay: {
    conditionId: string
    delayTotal: number
    delayElapsed: number
    delayMet: boolean
  }[]
}

// Interlock History Event Types
export type InterlockEventType =
  | 'created'
  | 'modified'
  | 'enabled'
  | 'disabled'
  | 'bypassed'
  | 'bypass_removed'
  | 'bypass_expired'
  | 'tripped'         // Interlock activated (conditions failed)
  | 'cleared'         // Interlock cleared (conditions restored)
  | 'demand'          // Interlock was demanded (conditions failed while controlling)
  | 'proof_test'      // Proof test performed

export interface InterlockHistoryEntry {
  id: string
  timestamp: string
  interlockId: string
  interlockName: string
  event: InterlockEventType
  user?: string
  reason?: string
  details?: {
    failedConditions?: string[]
    bypassDuration?: number
    previousState?: boolean
    newState?: boolean
  }
}

// ============================================
// User Variables / Playground Types
// ============================================

export type UserVariableType =
  | 'constant'      // Fixed value, usable in formulas (e.g., calibration factors, setpoints)
  | 'manual'        // User sets value directly
  | 'accumulator'   // Watches counter channel for increments
  | 'counter'       // Edge-triggered counter
  | 'timer'         // Elapsed time counter
  | 'sum'           // Running sum of channel values
  | 'average'       // Running average
  | 'min'           // Minimum value seen
  | 'max'           // Maximum value seen
  | 'stddev'        // Running standard deviation (Welford's algorithm)
  | 'rms'           // Root mean square (for AC, vibration)
  | 'median'        // Running median (reservoir sampling)
  | 'peak_to_peak'  // Difference between max and min
  | 'rolling'       // Sliding window accumulator (e.g., last 24 hours)
  | 'expression'    // Formula-based calculation
  | 'rate'          // Rate of change (derivative)
  | 'runtime'       // Time above/below threshold
  | 'dwell'         // Time in a state/condition
  | 'conditional_average'  // Average only when condition true
  | 'cross_channel' // Min/max/delta across multiple channels

export type ResetMode =
  | 'manual'        // Only reset manually
  | 'time_of_day'   // Reset at specific time each day
  | 'elapsed'       // Reset after elapsed time
  | 'test_session'  // Reset when test session starts
  | 'never'         // Never reset (persistent forever)

export type EdgeType =
  | 'increment'     // Counter increased by any amount
  | 'rising'        // 0 -> 1 transition
  | 'falling'       // 1 -> 0 transition
  | 'both'          // Any transition
  | 'rate'          // Rate signal (4-20mA, voltage) - integrate over time

export type SourceRateUnit =
  | 'per_second'    // Signal is X per second
  | 'per_minute'    // Signal is X per minute (e.g., GPM)
  | 'per_hour'      // Signal is X per hour
  | 'per_day'       // Signal is X per day

export interface UserVariable {
  id: string
  name: string
  displayName: string
  variableType: UserVariableType
  value: number
  units: string
  persistent: boolean

  // Accumulator/Counter/Stats config
  sourceChannel?: string      // Channel to watch
  sourceChannels?: string[]   // Multiple channels (for cross_channel type)
  edgeType?: EdgeType
  scaleFactor?: number
  sourceRateUnit?: SourceRateUnit  // For rate integration: what unit is the source signal?

  // Reset config
  resetMode: ResetMode
  resetTime?: string          // HH:MM for time_of_day
  resetElapsedS?: number      // Seconds for elapsed reset
  lastReset?: string          // ISO timestamp

  // Timer state
  timerRunning?: boolean

  // Statistics tracking
  sampleCount?: number

  // Expression/formula
  formula?: string

  // Rate of change config
  rateWindowMs?: number       // Time window for rate calculation

  // Runtime counter config
  thresholdValue?: number     // Threshold for runtime counting
  thresholdOperator?: '<' | '>' | '<=' | '>=' | '==' | '!='

  // Conditional stats config
  conditionChannel?: string   // Channel to check for condition
  conditionOperator?: '<' | '>' | '<=' | '>=' | '==' | '!='
  conditionValue?: number

  // Cross-channel config
  crossChannelOperation?: 'min' | 'max' | 'delta' | 'spread'

  // Dwell time config
  dwellCondition?: string     // Formula that returns boolean

  // Rolling window config
  rollingWindowS?: number     // Window size in seconds (default 86400 = 24 hours)

  // UI state
  lastUpdated?: number
  formatted?: string          // Pre-formatted value (for timers)
}

export interface TestSessionConfig {
  enableScheduler: boolean
  startRecording: boolean
  enableTriggers: boolean
  resetVariables: string[]    // Variable IDs to reset on start
  runSequenceId?: string      // Sequence to run at start
  stopSequenceId?: string     // Sequence to run at stop
  enableTriggerIds?: string[] // Specific triggers to enable
  enableScheduleIds?: string[] // Specific schedules to enable
}

export interface TestSession {
  active: boolean
  startedAt?: string          // ISO timestamp
  startedBy?: string
  elapsedSeconds?: number
  elapsedFormatted?: string   // HH:MM:SS
  config: TestSessionConfig
}

// Variable value from backend (for MQTT subscription)
export interface UserVariableValue {
  name: string
  display_name: string
  value: number
  units: string
  variable_type: UserVariableType
  last_reset?: string
  last_update?: number
  timer_running?: boolean
  formatted?: string
}

// ============================================
// Formula Block Types
// ============================================

export interface FormulaBlockOutput {
  units: string
  description: string
}

export interface FormulaBlock {
  id: string
  name: string
  description: string
  code: string                              // Multi-line Python-like code
  enabled: boolean
  outputs: Record<string, FormulaBlockOutput>  // output_name -> metadata
  lastError?: string                        // Last evaluation error
  lastValidated?: string                    // ISO timestamp of last validation
}

// Formula block computed values (updated each scan)
export interface FormulaBlockValues {
  [outputName: string]: number              // NaN if condition returned None
}

// Validation result from backend
export interface FormulaValidationResult {
  valid: boolean
  outputs: string[]                         // Variable names that will be created
  error?: string
  errorLine?: number
}

// ============================================
// Event Correlation Types
// ============================================

/**
 * Defines how alarms should be correlated/grouped.
 * When trigger_alarm fires, look for related_alarms within time_window_ms.
 */
export interface CorrelationRule {
  id: string
  name: string
  triggerAlarm: string           // Primary alarm ID that starts correlation
  relatedAlarms: string[]        // Alarm IDs to group when triggered together
  timeWindowMs: number           // Window for grouping (default 1000ms)
  rootCauseHint?: string         // Which alarm is likely root cause
  enabled: boolean
  description?: string
}

/**
 * Represents a group of correlated alarms that triggered together.
 * Used for root cause analysis and reducing alarm flooding.
 */
export interface EventCorrelation {
  correlationId: string
  triggerAlarmId: string
  relatedAlarmIds: string[]
  timestamp: string              // ISO timestamp
  rootCauseAlarmId: string
  ruleId: string
  nodeId?: string
}

// ============================================
// SOE (Sequence of Events) Types
// ============================================

export type SOEEventType =
  | 'alarm_triggered'
  | 'alarm_cleared'
  | 'alarm_acknowledged'
  | 'state_change'
  | 'digital_edge'
  | 'setpoint_change'

/**
 * Sequence of Events entry with microsecond precision.
 * Used for forensic analysis of alarm cascades.
 */
export interface SOEEvent {
  eventId: string
  timestampUs: number            // Microseconds since epoch (for precise ordering)
  timestampIso: string           // ISO string for display
  eventType: SOEEventType
  sourceChannel: string
  value: number | boolean
  previousValue?: number | boolean
  severity?: string
  message: string
  nodeId?: string
  alarmId?: string
  correlationId?: string         // Link to correlation group
}

/**
 * SOE query filters
 */
export interface SOEQueryFilters {
  startTimeUs?: number
  endTimeUs?: number
  eventTypes?: SOEEventType[]
  channels?: string[]
  limit?: number
}
