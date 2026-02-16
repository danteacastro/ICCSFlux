// Channel and system types matching the Python backend

export type ChannelType =
  // Analog Inputs
  | 'thermocouple'
  | 'voltage_input'
  | 'current_input'
  | 'rtd'
  | 'strain'           // Legacy - use strain_input
  | 'strain_input'
  | 'bridge_input'
  | 'iepe'             // Legacy - use iepe_input
  | 'iepe_input'
  | 'resistance'       // Legacy - use resistance_input
  | 'resistance_input'

  // Analog Outputs
  | 'voltage_output'
  | 'current_output'

  // Digital
  | 'digital_input'
  | 'digital_output'

  // Counter/Timer
  | 'counter'          // Legacy - use counter_input
  | 'counter_input'
  | 'counter_output'
  | 'frequency_input'
  | 'pulse_output'

  // Modbus
  | 'modbus_register'
  | 'modbus_coil'

  // Virtual/computed channels
  | 'script'           // Script-computed virtual channel
  | 'system'           // System status virtual channel

  // Legacy aliases for backwards compatibility
  | 'voltage'          // Maps to voltage_input
  | 'current'          // Maps to current_input
  | 'analog_input'     // Generic analog input (from discovery)
  | 'analog_output'    // Maps to voltage_output

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
  | 'heater_zone'
  | 'python_console'
  | 'script_output'
  | 'variable_explorer'
  | 'variable_input'
  | 'pid_loop'
  | 'status_messages'
  | 'image'
  | 'gc_chromatogram'
  | 'gc_overview'
  | 'small_multiples'

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
  cjc_value?: number             // Constant CJC temperature in °C (when cjc_source='constant')

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
  nominal_resistance?: number  // Bridge nominal resistance (default 350)

  // IEPE-specific
  iepe_coupling?: 'AC' | 'DC'
  coupling?: 'AC' | 'DC'       // Alias for iepe_coupling (UI)
  iepe_sensitivity?: number    // mV/g or mV/Pa (default 100.0)
  sensitivity?: number         // Alias for iepe_sensitivity (UI)
  iepe_current?: number        // Excitation current in Amps (default 0.004)
  excitation_current?: number  // Alias for iepe_current (UI)

  // Counter-specific
  counter_mode?: 'count_edges' | 'count' | 'frequency' | 'period' | 'pulse_width'
  edge?: 'rising' | 'falling'
  counter_edge?: 'rising' | 'falling'  // Backend uses this name
  initial_count?: number       // Initial counter value (default 0)
  direction?: 'up' | 'down'   // Count direction
  pulses_per_unit?: number     // e.g., 100 pulses = 1 gallon
  counter_reset_on_read?: boolean  // For totalizer mode
  counter_min_freq?: number    // Minimum expected frequency in Hz (for nidaqmx)
  counter_max_freq?: number    // Maximum expected frequency in Hz (for nidaqmx)

  // Resistance-specific
  resistance_range?: number    // Maximum expected resistance in Ohms
  resistance_wiring?: '2-wire' | '4-wire'
  excitation_current_ma?: number  // Excitation current in mA (resistance measurement)

  // Pulse/Counter output specific
  pulse_frequency?: number     // Output frequency in Hz
  pulse_duty_cycle?: number    // Duty cycle 0-100%
  pulse_idle_state?: 'LOW' | 'HIGH'  // Idle level
  idle_state?: string          // Alias for pulse_idle_state (UI)

  // Frequency input specific
  min_frequency?: number       // Minimum expected frequency in Hz
  max_frequency?: number       // Maximum expected frequency in Hz
  filter_enable?: boolean      // Enable hardware filter

  // Relay specific (digital_output subtype metadata)
  relay_type?: 'none' | 'spst' | 'spdt' | 'ssr'  // Relay subtype (informational)
  momentary_pulse_ms?: number  // 0 = latching, >0 = momentary auto-OFF after N ms

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
  voltage_range_min?: number   // Voltage output min range (default -10)
  voltage_range_max?: number   // Voltage output max range (default 10)
  raw_min?: number             // Raw input minimum (for scaling display)
  raw_max?: number             // Raw input maximum (for scaling display)
  current_range_ma?: number
  current_range_ma_min?: number  // Current output min range (default 4)
  current_range_ma_max?: number  // Current output max range (default 20)
  ao_range?: string  // Analog output range (e.g., '5V', '10V', 'pm10V')

  // Scaling type (alternative naming)
  scaling_type?: string        // Alias for scale_type (used by output channels)

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
  source_type?: 'local' | 'crio' | 'cdaq' | 'opto22' | 'gc'  // Source of channel data
  node_id?: string                 // Remote node ID for cRIO channels, chassis name for cDAQ
  chassis_name?: string            // Chassis name (e.g., "cDAQ-9189", "cRIO-9056")

  // UI settings
  step?: number  // Step increment for setpoint widgets
  decimals?: number  // Number of decimal places for display
  enabled?: boolean  // Channel enable/disable

  // Device connection settings (stored per-channel by backend)
  connection?: string             // 'tcp' | 'rtu' - connection type
  ip_address?: string             // Device IP address
  modbus_port?: number            // Modbus TCP port
  serial?: string                 // Serial port path (for RTU)
  modbus_baudrate?: number        // Serial baud rate
  modbus_parity?: string          // Serial parity
  modbus_stopbits?: number        // Serial stop bits
  modbus_bytesize?: number        // Serial byte size
  modbus_timeout?: number         // Communication timeout (seconds)
  modbus_retries?: number         // Number of retries on failure

  // CompactFieldPoint-specific
  cfp_device?: string             // CFP device identifier
  cfp_backplane_model?: string    // Backplane model (e.g., 'cFP-1808')
  cfp_slot?: number               // Module slot number
  cfp_module?: string             // Module type (e.g., 'cFP-AI-110')

  // EtherNet/IP-specific
  plc_type?: string               // PLC type (e.g., 'controllogix', 'micrologix')
  slot?: number                   // PLC slot number

  // OPC UA-specific
  endpoint_url?: string           // OPC UA server endpoint URL

  // Validation/alarm aliases (backend may use these names)
  min_value?: number              // Alias for low_limit
  max_value?: number              // Alias for high_limit
  eu_min?: number                 // Engineering unit minimum
  eu_max?: number                 // Engineering unit maximum
  hi_alarm?: number               // Alias for hi_limit
  hihi_alarm?: number             // Alias for hihi_limit
  lo_alarm?: number               // Alias for lo_limit
  lolo_alarm?: number             // Alias for lolo_limit
  chassis?: string                // Chassis identifier for Modbus devices
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
  // Enriched fields from status payload
  nodeType?: 'daq' | 'crio' | 'opto22' | 'gc'
  projectMode?: 'cdaq' | 'crio' | 'opto22'
  acquiring?: boolean
  recording?: boolean
  channelCount?: number
  safetyState?: 'normal' | 'warning' | 'tripped' | 'emergency'
}

export interface GCNodeConfig {
  node_id: string
  node_name: string
  gc_type: string
  vm_ip: string
  connection_mode: 'direct' | 'vm'
  source_type: 'file' | 'modbus' | 'serial' | 'analysis'
  // File watcher
  file_watch_dir?: string
  file_pattern?: string
  parse_template?: string
  column_mapping?: Record<string, string>
  // Modbus
  modbus_ip?: string
  modbus_port?: number
  modbus_slave_id?: number
  modbus_registers?: Array<{name: string, address: number, register_type: string, data_type: string, unit: string}>
  // Serial
  serial_port?: string
  serial_baudrate?: number
  serial_protocol?: string
  // Analysis engine
  analysis_method?: string
  analysis_components?: Record<string, {rt_expected: number, rt_tolerance: number, response_factor: number, unit: string}>
  // Status (from MQTT)
  status?: 'online' | 'offline' | 'unknown'
  last_seen?: number
  last_analysis?: string
  analysis_count?: number
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
  // Watchdog output configuration
  watchdog_output?: {
    enabled: boolean
    channel: string
    frequency_hz?: number
    duty_cycle?: number
  }
  // Resource monitoring
  resource_monitoring?: boolean
  cpu_percent?: number
  memory_mb?: number
  disk_percent?: number
  disk_used_gb?: number
  disk_total_gb?: number
  // Database status
  db_enabled?: boolean
  db_connected?: boolean
  db_rows_written?: number
}

// Result type for device command responses (test connection, tag browse, etc.)
export interface DeviceCommandResult {
  success: boolean
  message?: string
  error?: string
  tags?: Array<{ name: string; type?: string; value?: unknown }>  // EtherNet/IP tag list
  nodes?: Array<{ nodeId: string; displayName: string; nodeClass?: string }>  // OPC UA node list
  plc_info?: Record<string, unknown>  // EtherNet/IP PLC info
}

// Backend recording configuration (snake_case, matches Python backend)
export interface BackendRecordingConfig {
  // File settings
  base_path: string
  file_prefix: string
  file_format: 'csv' | 'tdms'
  // Logging rate
  sample_interval: number
  sample_interval_unit: 'seconds' | 'milliseconds'
  decimation: number
  // File rotation
  rotation_mode: 'single' | 'time' | 'size' | 'samples' | 'session'
  max_file_size_mb: number
  max_file_duration_s: number
  max_file_samples: number
  // Naming
  naming_pattern: 'timestamp' | 'sequential' | 'custom'
  include_date: boolean
  include_time: boolean
  include_channels_in_name: boolean
  sequential_start: number
  sequential_padding: number
  custom_suffix: string
  // Directory
  directory_structure: 'flat' | 'daily' | 'monthly' | 'experiment'
  experiment_name: string
  // Write strategy
  write_mode: 'immediate' | 'buffered'
  buffer_size: number
  flush_interval_s: number
  // Limits
  on_limit_reached: 'new_file' | 'stop' | 'circular'
  circular_max_files: number
  // Recording mode
  mode: 'manual' | 'triggered' | 'scheduled'
  selected_channels: string[]
  include_scripts: boolean
  // Triggered mode
  trigger_channel: string
  trigger_condition: 'above' | 'below' | 'change'
  trigger_value: number
  pre_trigger_samples: number
  post_trigger_samples: number
  // Scheduled mode
  schedule_start: string
  schedule_end: string
  schedule_days: string[]
  // File reuse
  reuse_file: boolean
  // ALCOA+ (FDA 21 CFR Part 11)
  append_only: boolean
  verify_on_close: boolean
  include_audit_metadata: boolean
  // PostgreSQL
  db_enabled: boolean
  db_host: string
  db_port: number
  db_name: string
  db_user: string
  db_password: string
  db_table: string
  db_batch_size: number
  db_timescale: boolean
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
  verticalAlign?: 'top' | 'center' | 'bottom'
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

export interface ChartThreshold {
  value: number          // Y-axis value where line is drawn
  label?: string         // Optional label shown at right edge
  color?: string         // Line color (default: #ef4444 red)
  style?: 'solid' | 'dashed' | 'dotted'  // Line style (default: dashed)
}

// ============================================================================
// Historian Types (Data Viewer)
// ============================================================================

export interface HistorianTag {
  name: string
  unit: string
  first_ts: number | null   // epoch seconds
  last_ts: number | null     // epoch seconds
  point_count: number
}

export interface HistorianPanel {
  id: string
  channels: string[]
  yAxisAuto: boolean
  yAxisMin?: number
  yAxisMax?: number
  collapsed: boolean
  showTable: boolean
  height?: number            // panel chart height in px (default 280)
}

export interface HistorianTimeRange {
  preset?: string            // '1h', '6h', '12h', '24h', '7d', '30d'
  start?: number             // custom range start (unix ms)
  end?: number               // custom range end (unix ms)
}

export interface HistorianQueryResult {
  success: boolean
  error?: string
  timestamps: number[]       // epoch seconds (for uPlot)
  series: Record<string, (number | null)[]>
  channels: string[]
  total_points: number
  decimated: boolean
}

export interface HistorianStats {
  db_size_bytes: number
  total_points: number
  channel_count: number
  oldest_ts: number | null
  newest_ts: number | null
  retention_days: number
  points_written: number
  write_errors: number
}

// Log Viewer types
export interface LogEntry {
  timestamp: string       // ISO 8601 with milliseconds
  level: string           // DEBUG, INFO, WARNING, ERROR, CRITICAL
  logger: string          // Logger name (e.g., 'DAQService', 'AlarmManager')
  message: string         // Formatted log message
}

export type ButtonActionType =
  | 'mqtt_publish'      // Publish to MQTT topic
  | 'digital_output'    // Set digital output (pulse or toggle)
  | 'script_run'        // Run a script/sequence
  | 'script_oneshot'    // Run a script once (one-shot execution)
  | 'variable_set'      // Set a user variable to a value
  | 'variable_reset'    // Reset a user variable (counter, timer, etc.)
  | 'system_command'    // System command (start/stop acquisition, recording)

// Button mechanical action (similar to LabVIEW Boolean controls)
export type ButtonBehavior =
  | 'momentary'         // Switch When Pressed - active while held, returns to off when released
  | 'toggle'            // Switch When Released - alternates state on each press
  | 'latching'          // Latch When Pressed - sets ON and stays until external reset
  | 'one_shot'          // Latch Until Released - pulses once per press (default)

// Button visual style
export type ButtonStyle =
  | 'standard'          // Default rectangular button
  | 'round'             // Circular button (like indicator lamps)
  | 'square'            // Square button
  | 'emergency'         // Emergency stop style (red, prominent, round)
  | 'flat'              // Flat/minimal style

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
  // For script_oneshot
  scriptName?: string   // Script name to run once
  // For variable_set / variable_reset
  variableId?: string   // User variable ID
  variableValue?: number // Value to set (for variable_set)
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
  updateMode?: ChartUpdateMode  // strip, scope, sweep
  chartMode?: 'time' | 'xy'     // 'time' (default) or 'xy' for XY graph (default strip)
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
  // TrendChart enhancements (Grafana-inspired)
  interpolation?: 'linear' | 'smooth' | 'stepBefore' | 'stepAfter'
  fillOpacity?: number          // 0-100, default 0
  tooltipMode?: 'single' | 'all' | 'hidden'
  connectNulls?: 'never' | 'always' | 'threshold'
  connectNullsThreshold?: number
  cursorSyncGroup?: string
  // Display options
  decimals?: number
  showUnit?: boolean
  showAlarmStatus?: boolean
  label?: string
  // Button-specific
  buttonAction?: ButtonAction
  requireConfirmation?: boolean
  buttonColor?: string
  buttonBehavior?: ButtonBehavior  // Mechanical action (momentary, toggle, etc.)
  buttonVisualStyle?: ButtonStyle  // Visual style (round, square, etc.)
  buttonActiveColor?: string    // Color when active/pressed
  buttonSize?: 'small' | 'medium' | 'large'  // Button size
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
  barGraphStyle?: 'bar' | 'tank' | 'thermometer'
  // Setpoint-specific visual style
  setpointStyle?: 'standard' | 'knob'
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
  // Text Label/Title-specific
  text?: string             // Static text content
  title?: string            // Title text (for title_label, alarm_summary)
  subtitle?: string         // Subtitle text (for alarm_summary)
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
  // Alarm Summary-specific
  maxItems?: number         // Max alarms to display
  filterPriority?: string   // Filter by priority level
  showAckButton?: boolean   // Show acknowledge button
  showBypassButtons?: boolean // Show bypass controls
  // Toggle Switch-specific
  onLabel?: string          // Label for ON state
  offLabel?: string         // Label for OFF state
  confirmOn?: boolean       // Require confirmation for ON
  confirmOff?: boolean      // Require confirmation for OFF
  // LED Indicator-specific
  invert?: boolean          // Invert on/off logic
  ledSize?: 'small' | 'medium' | 'large'
  onColor?: string          // Color when ON
  offColor?: string         // Color when OFF
  // Numeric Display-specific
  historyLength?: number    // Length of value history for sparkline
  showMinMax?: boolean      // Show min/max values
  // Setpoint-specific
  setpointMin?: number      // Min setpoint value
  setpointMax?: number      // Max setpoint value
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
  columns?: number
  showTimestamp?: boolean
  refreshRate?: number
  // Styling
  style?: WidgetStyle
  // HeaterZone-specific (multi-channel composite widget)
  pvChannel?: string
  spChannel?: string
  enableChannel?: string
  outputChannel?: string
  spMin?: number
  spMax?: number
  temperatureUnit?: 'F' | 'C'
  advancedParams?: Array<{
    channel: string
    label: string
    readonly?: boolean
  }>

  // Image widget
  imageUrl?: string
  imageFit?: 'contain' | 'cover' | 'fill' | 'none'

  // GC Chromatogram widget
  gcNodeId?: string            // GC node ID to subscribe to
  showPeakLabels?: boolean     // Show peak name labels on chart
  showComponentTable?: boolean // Show component results table
  showSstBar?: boolean         // Show SST pass/fail status bar
  gcHistoryDepth?: number      // Number of past runs to keep (default 10)
}

// GC Analysis types (from gc_node MQTT topics)
export interface GCPeakResult {
  name: string
  rt: number             // Retention time (seconds)
  area: number
  area_pct: number
  height: number
  width_s: number
  concentration?: number
  unit?: string
  identified: boolean
  plates?: number        // Theoretical plates (SST)
  tailing?: number       // Tailing factor (SST)
  resolution?: number    // Resolution to adjacent peak (SST)
}

export interface GCComponentResult {
  name: string
  concentration: number
  area_pct: number
  unit: string
  rt: number
}

export interface GCChromatogramData {
  run_number: number
  node_id: string
  times: number[]
  values: number[]
  points: number
  duration_s: number
  timestamp: number
}

export interface GCAnalysisResult {
  run_number: number
  run_duration_s?: number
  finish_reason?: string
  timestamp: string
  method?: string
  port?: number
  port_label?: string
  components: Record<string, {
    concentration?: number
    area_pct?: number
    area?: number
    rt?: number
    unit?: string
  }>
  unidentified_peaks?: GCPeakResult[]
  total_area?: number
  chromatogram_points?: number
}

export interface GCRunProgress {
  run_number: number
  elapsed_s: number
  points: number
  max_voltage: number
  last_voltage: number
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
  // Horizontal/vertical mirror
  flipX?: boolean
  flipY?: boolean
  // ISA loop number (e.g. "100", "200A") — validated unique across all pages
  loopNumber?: string
  // Optional channel binding for live data
  channel?: string
  // Styling
  label?: string
  color?: string
  showValue?: boolean
  decimals?: number
  // Z-index for layering
  zIndex?: number
  // === Enhanced Features (Phase 1+) ===
  // Grouping
  groupId?: string
  // Faceplate/popup configuration
  faceplateId?: string
  // Tank fill animation (Phase 2)
  fillLevel?: number         // 0-100% static fill level (for design mode)
  fillChannel?: string       // Channel to bind fill level to (runtime)
  fillColor?: string         // Fill color (default: blue gradient)
  // Flow direction indicator (for pumps, compressors)
  flowDirection?: 'forward' | 'reverse' | 'stopped'
  flowChannel?: string       // Channel to determine flow state
  // Locked symbol cannot be moved/resized
  locked?: boolean
  // Runtime state (set by channel binding)
  runtimeState?: 'on' | 'off' | 'fault' | 'manual' | 'auto'
  stateChannel?: string      // Channel to determine state
  // State-based coloring (for valves, pumps, etc.)
  onColor?: string           // Color when state channel value >= threshold (default: '#22c55e' green)
  offColor?: string          // Color when state channel value < threshold (default: '#6b7280' gray)
  faultColor?: string        // Color when state channel has alarm/disconnected (default: '#ef4444' red)
  stateThreshold?: number    // Value threshold for on/off (default: 0.5 — works for digital 0/1)
  // ISA-101 grayscale mode override
  useGrayscale?: boolean
  // Custom pipe connection ports (in addition to built-in ports)
  customPorts?: Array<{
    id: string
    x: number  // Relative position 0-1
    y: number  // Relative position 0-1
    direction: 'left' | 'right' | 'top' | 'bottom'
    label?: string
  }>
  // Hidden built-in ports (by port ID)
  hiddenPorts?: string[]

  // HMI Control config (only used when type starts with 'hmi_')
  hmiMinValue?: number
  hmiMaxValue?: number
  hmiAlarmHigh?: number
  hmiAlarmLow?: number
  hmiWarningHigh?: number
  hmiWarningLow?: number
  hmiOrientation?: 'horizontal' | 'vertical'
  hmiUnit?: string
  // Multi-State Indicator: value-to-state mapping
  hmiStates?: Array<{ value: number; label: string; color: string }>
  // Selector Switch: position definitions
  hmiSelectorPositions?: Array<{ value: number; label: string }>
  // Command Button: action to execute on press
  hmiButtonAction?: ButtonAction
  // Legacy: simple value to write on press (deprecated, use hmiButtonAction)
  hmiButtonValue?: number
  // Trend Sparkline: number of history samples to keep
  hmiSparklineSamples?: number
  // Valve position channel (0-100% open) — for control/modulating valves
  positionChannel?: string
  // Off-page connector: target page for navigation
  linkedPageId?: string
  // Named layer membership
  layerId?: string
  // Interlock binding (for hmi_interlock control)
  interlockId?: string
  // Auxiliary channel bindings — for equipment with multiple Modbus/OPC registers
  // (e.g., heater controllers: PV, SP, output%, enable, heater current)
  auxiliaryChannels?: Array<{
    role: string            // e.g., 'pv', 'sp', 'output', 'enable', 'heaterCurrent'
    channel: string         // channel name from store.channels
    label: string           // display label (e.g., 'Setpoint', 'Output %')
    unit?: string           // optional unit override
    decimals?: number       // optional decimal places
    writable?: boolean      // true if user can write a value (setpoint, enable)
    min?: number            // range min for writable channels
    max?: number            // range max for writable channels
  }>

  // Block editor indicator stubs (nozzle-point style annotations)
  indicators?: PidIndicator[]
}

// Indicator stub on a P&ID symbol's perimeter edge.
// Represents channel values, interlocks, alarm annotations, or control outputs.
export interface PidIndicator {
  id: string
  edge: 'top' | 'right' | 'bottom' | 'left'
  edgeOffset: number  // 0-1 position along that edge
  type: PidIndicatorType
  channel?: string
  interlockId?: string
  label?: string
  isaLetters?: string    // ISA function letters (TE, LSH, TAH, etc.)
  tagNumber?: string
  shape: PidIndicatorShape
  showValue?: boolean
  decimals?: number
  unit?: string
  signalLineLength?: number   // pixels, default 30
  signalLineDashed?: boolean  // default true (deprecated — use signalType for ISA-standard dashing)
  // ISA 5.1 signal line type — controls dash pattern per standard
  signalType?: PidSignalLineType
}

// ISA 5.1 signal line types — each has a specific dash pattern per the standard
export type PidSignalLineType =
  | 'undefined'      // Solid line (connection/process)
  | 'pneumatic'      // Dashed: --- --- ---
  | 'electrical'     // Dotted: . . . . .
  | 'capillary'      // Dash-dot: -.-.-.-
  | 'hydraulic'      // Dash-dot-dot: -..-..-..-
  | 'electromagnetic' // Triple-dot-dash: ...---...---
  | 'software'       // Software/data link: equal dashes ═══

export type PidIndicatorType = 'channel_value' | 'interlock' | 'alarm_annotation' | 'control_output'
export type PidIndicatorShape = 'circle' | 'diamond' | 'flag' | 'square' | 'hexagon' | 'circleBar' | 'dashedCircle' | 'circleInSquare'

// Preset auxiliary channel templates for common equipment types
export const AUXILIARY_CHANNEL_PRESETS: Record<string, Array<{
  role: string; label: string; unit?: string; decimals?: number; writable?: boolean
}>> = {
  heaterController: [
    { role: 'pv', label: 'Process Value', unit: '°C', decimals: 1 },
    { role: 'sp', label: 'Setpoint', unit: '°C', decimals: 1, writable: true },
    { role: 'output', label: 'Output', unit: '%', decimals: 0 },
    { role: 'enable', label: 'Enable', writable: true },
  ],
  heaterControllerFull: [
    { role: 'pv', label: 'Process Value', unit: '°C', decimals: 1 },
    { role: 'sp', label: 'Setpoint', unit: '°C', decimals: 1, writable: true },
    { role: 'output', label: 'Output', unit: '%', decimals: 0 },
    { role: 'enable', label: 'Enable', writable: true },
    { role: 'heaterCurrent', label: 'Heater Current', unit: 'A', decimals: 2 },
    { role: 'controlMode', label: 'Control Mode' },
  ],
  pidLoop: [
    { role: 'pv', label: 'Process Variable', decimals: 2 },
    { role: 'sp', label: 'Setpoint', decimals: 2, writable: true },
    { role: 'cv', label: 'Control Output', unit: '%', decimals: 1 },
    { role: 'mode', label: 'Mode' },
  ],
  vfd: [
    { role: 'speed', label: 'Speed', unit: 'Hz', decimals: 1 },
    { role: 'speedCmd', label: 'Speed Command', unit: 'Hz', decimals: 1, writable: true },
    { role: 'current', label: 'Current', unit: 'A', decimals: 1 },
    { role: 'enable', label: 'Run/Stop', writable: true },
    { role: 'fault', label: 'Fault Code' },
  ],
}

// Arrow marker types for pipe endpoints
export type PidArrowType = 'none' | 'arrow' | 'open' | 'dot' | 'diamond' | 'bar'

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
  opacity?: number           // 0-1, default 1
  dashed?: boolean
  dashPattern?: string       // Custom SVG dash-array, e.g. "8,4", overrides dashed
  animated?: boolean
  label?: string
  labelPosition?: 'start' | 'middle' | 'end'  // default 'middle'
  // Arrow markers (PidArrowType or boolean for backwards compat)
  startArrow?: PidArrowType | boolean
  endArrow?: PidArrowType | boolean
  // Rounded corners
  rounded?: boolean
  cornerRadius?: number      // default 8
  // Line jumps at crossings
  jumpStyle?: 'none' | 'arc' | 'gap'
  jumpSize?: number          // default 8
  // Z-index for layering
  zIndex?: number
  // === Enhanced Features (Phase 1+) ===
  // Grouping
  groupId?: string
  // Snap-to-port connections (Phase 1)
  startConnection?: PidPipeConnection
  endConnection?: PidPipeConnection
  // Legacy port binding (kept for backwards compatibility)
  startSymbolId?: string
  startPortId?: string
  endSymbolId?: string
  endPortId?: string
  // Enhanced flow animation (Phase 2)
  flowChannel?: string       // Channel to determine flow rate/direction
  flowSpeed?: number         // Animation speed multiplier (default 1)
  flowDirection?: 'forward' | 'reverse' | 'stopped'
  // Pipe medium/type indicator
  medium?: 'water' | 'steam' | 'gas' | 'air' | 'oil' | 'chemical' | 'electrical' | 'signal' | 'custom'
  // ISA-5.1 line coding (for signal/instrument lines)
  lineCode?: PidSignalLineType
  // Structured pipe attributes (ISA standard pipe identification)
  nominalSize?: string       // Nominal pipe size, e.g. "4\"", "DN100", "2\""
  pressureRating?: string    // Pressure class, e.g. "150#", "300#", "PN16"
  material?: string          // Material spec, e.g. "CS", "SS316", "CPVC"
  fluidCode?: string         // Fluid service code, e.g. "S" (steam), "W" (water), "G" (gas)
  lineNumber?: string        // Full line number, e.g. "4\"-S-150#-CS-101"
  // Flow particle animation (animated dots along the pipe path)
  flowParticles?: boolean
  particleCount?: number     // Number of particles (default 4)
  particleColor?: string     // Particle color (default: pipe color)
  // Heat tracing (ISA zigzag marking alongside pipe)
  heatTrace?: 'none' | 'electric' | 'steam' | 'hot-water'
  heatTraceChannel?: string  // Channel binding: trace on when value >= threshold
  heatTraceThreshold?: number // On/off threshold (default 0.5)
  // Named layer membership
  layerId?: string
  // System grouping (e.g., cooling, heating, process)
  system?: string
}

// P&ID layer data for a page
export interface PidLayerData {
  symbols: PidSymbol[]
  pipes: PidPipe[]
  // Layer visibility toggle
  visible?: boolean
  // Layer opacity (for showing behind grid widgets)
  opacity?: number
  // Text annotations (Phase 1)
  textAnnotations?: PidTextAnnotation[]
  // Symbol groups (Phase 2)
  groups?: PidGroup[]
  // Background image (Phase 3)
  backgroundImage?: PidBackgroundImage
  // Grid snapping options (Phase 4)
  gridSnap?: boolean
  gridSize?: number
  // User-created guide lines (dragged from rulers)
  guides?: Array<{ id: string; axis: 'h' | 'v'; position: number }>
  // Named layer metadata
  layerInfos?: PidLayerInfo[]
  // Pipe system definitions (for color-coding and filtering)
  systems?: Array<{ id: string; name: string; color: string }>
}

// Named layer for P&ID elements
export interface PidLayerInfo {
  id: string
  name: string
  visible: boolean
  locked: boolean
  opacity: number
  order: number
}

// ============================================================================
// P&ID Enhanced Types (FactoryTalk/ISA-101 Compliant Features)
// ============================================================================

/**
 * Text annotation for P&ID canvas labels, notes, and callouts
 */
export interface PidTextAnnotation {
  id: string
  text: string
  x: number
  y: number
  fontSize: number
  fontWeight?: 'normal' | 'bold'
  fontStyle?: 'normal' | 'italic'
  color?: string
  backgroundColor?: string
  rotation?: number
  textAlign?: 'left' | 'center' | 'right'
  // Optional border/callout
  border?: boolean
  borderColor?: string
  // Z-index for layering
  zIndex?: number
  // Grouping
  groupId?: string
  // Named layer membership
  layerId?: string
}

/**
 * Command for Undo/Redo system (Command Pattern)
 * Stores state before and after each operation
 */
export interface PidCommand {
  id: string
  type: 'add' | 'delete' | 'modify' | 'move' | 'resize' | 'group' | 'ungroup' | 'paste' | 'batch'
  timestamp: number
  description: string
  // State snapshots for undo/redo
  beforeState: {
    symbols?: PidSymbol[]
    pipes?: PidPipe[]
    textAnnotations?: PidTextAnnotation[]
    groups?: PidGroup[]
    layerInfos?: PidLayerInfo[]
  }
  afterState: {
    symbols?: PidSymbol[]
    pipes?: PidPipe[]
    textAnnotations?: PidTextAnnotation[]
    groups?: PidGroup[]
    layerInfos?: PidLayerInfo[]
  }
  // For batch operations, store sub-commands
  subCommands?: PidCommand[]
}

/**
 * Group of P&ID elements that move/resize together
 */
export interface PidGroup {
  id: string
  name?: string
  // IDs of grouped elements
  symbolIds: string[]
  pipeIds: string[]
  textAnnotationIds: string[]
  // Group bounding box (computed from members)
  x?: number
  y?: number
  width?: number
  height?: number
  // Locked group cannot be ungrouped or modified
  locked?: boolean
  // Z-index for layering
  zIndex?: number
}

/**
 * Background image configuration for P&ID layer
 */
export interface PidBackgroundImage {
  url: string
  x: number
  y: number
  width: number
  height: number
  opacity: number
  locked: boolean
}

/**
 * P&ID Template - reusable symbol group
 * Similar to FactoryTalk global objects
 */
export interface PidTemplate {
  id: string
  name: string
  description?: string
  category?: string
  // Template content (relative positions)
  symbols: Array<Omit<PidSymbol, 'id'> & { offsetX: number; offsetY: number }>
  pipes: Array<Omit<PidPipe, 'id'> & { offsetPoints: { x: number; y: number }[] }>
  textAnnotations: Array<Omit<PidTextAnnotation, 'id'> & { offsetX: number; offsetY: number }>
  // Preview thumbnail (data URL)
  thumbnail?: string
  // Metadata
  createdAt: string
  updatedAt?: string
}

/**
 * Faceplate configuration for runtime symbol popups
 * Similar to FactoryTalk View faceplates
 */
export interface FaceplateConfig {
  id: string
  name: string
  // Symbol types this faceplate applies to
  symbolTypes: string[]
  // Layout
  width: number
  height: number
  // Sections to display
  sections: FaceplateSection[]
}

export type FaceplateSectionType =
  | 'header'        // Symbol name, status, channel binding
  | 'value'         // Current value with unit
  | 'controls'      // Toggle, setpoint controls
  | 'trend'         // Mini trend chart
  | 'alarms'        // Active alarms for this channel
  | 'diagnostics'   // Device status, quality, timestamps
  | 'custom'        // Custom HTML/template

export interface FaceplateSection {
  type: FaceplateSectionType
  label?: string
  height?: number
  // For value section
  decimals?: number
  showUnit?: boolean
  // For controls section
  controlType?: 'toggle' | 'setpoint' | 'button'
  // For trend section
  timeRange?: number  // seconds
  // For custom section
  template?: string
}

/**
 * Port definition for symbol connection points
 * Used for pipe snap-to-port feature
 */
export interface SymbolPort {
  id: string
  name: string
  // Position relative to symbol (0-1 normalized)
  x: number
  y: number
  // Direction the pipe should exit
  direction: 'up' | 'down' | 'left' | 'right'
  // Port type for compatibility checking
  type?: 'inlet' | 'outlet' | 'bidirectional'
}

/**
 * Pipe connection to symbol port
 * Extends PidPipe with port binding info
 */
export interface PidPipeConnection {
  symbolId: string
  portId: string
  // Computed world position (updated when symbol moves)
  x?: number
  y?: number
}

/**
 * ISA-101 Display Hierarchy Levels
 * L1: Overview - Plant-wide status, key KPIs
 * L2: Area - Unit operation P&IDs
 * L3: Equipment - Faceplates, detailed equipment views
 * L4: Diagnostics - Troubleshooting, raw data, trends
 */
export type DisplayHierarchyLevel = 'L1' | 'L2' | 'L3' | 'L4'

// Dashboard Page - each page has its own widget layout
export interface DashboardPage {
  id: string
  name: string
  widgets: WidgetConfig[]
  pipes?: PipeConnection[]  // Legacy: grid-locked pipe connections
  pidLayer?: PidLayerData   // New: free-form P&ID layer
  order: number             // Sort order
  createdAt?: string
  // ISA-101 Display Hierarchy
  hierarchyLevel?: DisplayHierarchyLevel
  // Navigation links to other pages
  linkedPages?: {
    parentId?: string       // Link to parent L1/L2 page
    childIds?: string[]     // Links to child L3/L4 pages
  }
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
  script_monitor: { w: 3, h: 4, minW: 2, minH: 2 },
  heater_zone: { w: 2, h: 2, minW: 2, minH: 2 },
  python_console: { w: 4, h: 3, minW: 2, minH: 2 },
  script_output: { w: 4, h: 3, minW: 2, minH: 2 },
  variable_explorer: { w: 3, h: 4, minW: 2, minH: 2 },
  variable_input: { w: 2, h: 3, minW: 1, minH: 2 },
  pid_loop: { w: 2, h: 3, minW: 2, minH: 2 },
  status_messages: { w: 3, h: 2, minW: 2, minH: 2 },
  image: { w: 2, h: 2, minW: 1, minH: 1 },
  gc_chromatogram: { w: 4, h: 4, minW: 3, minH: 3 },
  gc_overview: { w: 6, h: 4, minW: 3, minH: 3 },
  small_multiples: { w: 4, h: 3, minW: 2, minH: 2 }
}

// Preset colors for widgets (expanded palette)
export const WIDGET_COLORS = {
  led: {
    on: [
      '#22c55e', // green
      '#3b82f6', // blue
      '#fbbf24', // amber
      '#ef4444', // red
      '#8b5cf6', // violet
      '#ec4899', // pink
      '#06b6d4', // cyan
      '#f97316', // orange
      '#84cc16', // lime
      '#14b8a6', // teal
      '#6366f1', // indigo
      '#f43f5e', // rose
    ],
    off: [
      '#166534', // green-dark
      '#1e3a8a', // blue-dark
      '#78350f', // amber-dark
      '#7f1d1d', // red-dark
      '#4c1d95', // violet-dark
      '#831843', // pink-dark
      '#164e63', // cyan-dark
      '#7c2d12', // orange-dark
      '#365314', // lime-dark
      '#134e4a', // teal-dark
      '#312e81', // indigo-dark
      '#881337', // rose-dark
    ]
  },
  text: [
    '#ffffff', // white
    '#60a5fa', // blue
    '#4ade80', // green
    '#fbbf24', // amber
    '#ef4444', // red
    '#a855f7', // purple
    '#22d3ee', // cyan
    '#fb923c', // orange
    '#a3e635', // lime
    '#2dd4bf', // teal
    '#f472b6', // pink
    '#888888', // gray
  ],
  background: [
    'transparent',
    '#1a1a2e', // dark navy
    '#0f0f1a', // darker
    '#1e3a5f', // blue tint
    '#14532d', // green tint
    '#7f1d1d', // red tint
    '#78350f', // amber tint
    '#164e63', // cyan tint
    '#4c1d95', // purple tint
    '#134e4a', // teal tint
    '#1e1b4b', // indigo tint
    '#3f3f46', // zinc
  ],
  button: [
    '#3b82f6', // blue
    '#22c55e', // green
    '#ef4444', // red
    '#fbbf24', // amber
    '#8b5cf6', // violet
    '#ec4899', // pink
    '#06b6d4', // cyan
    '#f97316', // orange
    '#14b8a6', // teal
    '#6366f1', // indigo
    '#84cc16', // lime
    '#6b7280', // gray
  ]
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
  // Operational priority for dashboard display (ISA-18.2 aligned)
  priority?: 'critical' | 'high' | 'medium' | 'low'
  // Require operator acknowledgment after trip (IEC 61511)
  requiresAcknowledgment?: boolean
  // Proof test interval in days (IEC 61511)
  proofTestInterval?: number
  lastProofTest?: string
  // Demand tracking
  demandCount?: number
  lastDemandTime?: string
  // Backend-evaluated status (runtime, not persisted)
  _backendSatisfied?: boolean
  _backendFailedConditions?: Array<{ condition: InterlockCondition; currentValue?: unknown; reason: string; delayRemaining?: number }>
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
  // IEC 61511 compliance fields
  priority?: 'critical' | 'high' | 'medium' | 'low'
  silRating?: 'SIL1' | 'SIL2' | 'SIL3' | 'SIL4'
  requiresAcknowledgment?: boolean
  tripAcknowledged?: boolean
  tripAcknowledgedBy?: string
  tripAcknowledgedAt?: string
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
  | 'trip_acknowledged' // Operator acknowledged a trip (IEC 61511)
  | 'removed'         // Interlock removed from configuration

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
  | 'string'        // Text value (notes, batch ID, operator input)

export type UserVariableDataType =
  | 'number'        // Numeric value (float)
  | 'string'        // Text value

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
  description?: string
  variableType: UserVariableType
  dataType?: UserVariableDataType  // 'number' (default) or 'string'
  value: number                    // Numeric value
  stringValue?: string             // String value (for dataType='string')
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
  // Session metadata (operator-provided at start)
  testId?: string             // e.g. "TEST-20260130-001"
  description?: string        // Free text description
  operatorNotes?: string      // Free text notes
  timeoutMinutes?: number     // 0 = no timeout
}

// Variable value from backend (for MQTT subscription)
export interface UserVariableValue {
  name: string
  display_name: string
  value: number | string           // Number for numeric, string for string variables
  units: string
  variable_type: UserVariableType
  data_type?: UserVariableDataType // 'number' or 'string'
  string_value?: string            // String value (for data_type='string')
  numeric_value?: number           // Numeric value (for data_type='number')
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

// ============================================================================
// MQTT CALLBACK PAYLOAD TYPES (FE-H11)
// Typed interfaces for useMqtt callback payloads
// ============================================================================

/** Payload passed to discovery callbacks from handleDiscoveryResult */
export interface DiscoveryCallbackPayload {
  success: boolean
  total_channels: number
  message?: string
  error?: string
  simulation_mode?: boolean
  chassis?: Array<{
    name: string
    product_type?: string
    modules?: Array<Record<string, unknown>>
  }>
  crio_nodes?: Array<Record<string, unknown>>
  opto22_nodes?: Array<Record<string, unknown>>
}

/** Payload passed to config update callbacks */
export interface ConfigUpdateCallbackPayload {
  success?: boolean
  message?: string
  error?: string
  node_id?: string
  config_version?: string
  configs?: Array<Record<string, unknown>>
  failed?: Array<{ name?: string; error?: string }>
}

/** Payload passed to recording callbacks */
export interface RecordingCallbackPayload {
  success: boolean
  message: string
  error?: string
}

/** Alarm event payload constructed in handleAlarm and passed to alarm callbacks */
export interface AlarmCallbackPayload {
  id: string
  alarm_id: string
  channel: string
  name: string
  severity: string
  state: string
  threshold_type?: string
  threshold?: number
  value: number
  current_value?: number
  triggered_at: string
  acknowledged_at?: string
  acknowledged_by?: string
  cleared_at?: string
  sequence_number: number
  is_first_out: boolean
  shelved_at?: string
  shelved_by?: string
  shelve_expires_at?: string
  shelve_reason?: string
  message: string
  duration_seconds?: number
}

/** Payload passed to system update callbacks */
export interface SystemUpdateCallbackPayload {
  success: boolean
  message?: string
  error?: string
  scan_rate_hz?: number
  publish_rate_hz?: number
}

/** Payload passed to cRIO operation callbacks */
export interface CrioCallbackPayload {
  success: boolean
  message?: string
  error?: string
  node_id?: string
  operation?: string
}

// =========================================================================
// Notification System (Twilio SMS + Email)
// =========================================================================

export type NotificationEventType = 'triggered' | 'cleared' | 'acknowledged' | 'alarm_flood'

export interface NotificationTriggerRules {
  severities: AlarmSeverityLevel[]
  event_types: NotificationEventType[]
  groups: string[]
  alarm_select_mode: 'all' | 'include_only' | 'exclude'
  alarm_ids: string[]
}

export interface TwilioNotificationConfig {
  enabled: boolean
  account_sid: string
  auth_token: string
  from_number: string
  to_numbers: string[]
  rules: NotificationTriggerRules
}

export interface EmailNotificationConfig {
  enabled: boolean
  smtp_host: string
  smtp_port: number
  use_tls: boolean
  username: string
  password: string
  from_address: string
  to_addresses: string[]
  rules: NotificationTriggerRules
}

export interface NotificationSettings {
  twilio: TwilioNotificationConfig
  email: EmailNotificationConfig
  cooldown_seconds: number
  daily_limit: number
  quiet_hours_enabled: boolean
  quiet_hours_start: string
  quiet_hours_end: string
}
