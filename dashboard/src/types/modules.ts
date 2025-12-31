// NI C Series Module Configuration Types
// Based on NI-DAQmx parameters for CompactDAQ modules

// =============================================================================
// THERMOCOUPLE MODULES (NI-9210, 9211, 9212, 9213, 9214)
// =============================================================================
export type ThermocoupleType = 'J' | 'K' | 'T' | 'E' | 'N' | 'B' | 'R' | 'S'

export type TemperatureUnits = 'C' | 'F' | 'K' | 'R' // Celsius, Fahrenheit, Kelvin, Rankine

export type CJCSource = 'internal' | 'constant' | 'channel'

export interface ThermocoupleConfig {
  tc_type: ThermocoupleType
  units: TemperatureUnits
  cjc_source: CJCSource
  cjc_value?: number // For constant CJC
  open_detect: boolean
  auto_zero: boolean
}

export const THERMOCOUPLE_TYPES: { value: ThermocoupleType; label: string; range: string }[] = [
  { value: 'J', label: 'Type J', range: '-210°C to 1200°C' },
  { value: 'K', label: 'Type K', range: '-270°C to 1372°C' },
  { value: 'T', label: 'Type T', range: '-270°C to 400°C' },
  { value: 'E', label: 'Type E', range: '-270°C to 1000°C' },
  { value: 'N', label: 'Type N', range: '-270°C to 1300°C' },
  { value: 'B', label: 'Type B', range: '250°C to 1820°C' },
  { value: 'R', label: 'Type R', range: '-50°C to 1768°C' },
  { value: 'S', label: 'Type S', range: '-50°C to 1768°C' },
]

// =============================================================================
// VOLTAGE INPUT MODULES (NI-9201, 9205, 9215, 9220, 9221, 9222, 9223, etc.)
// =============================================================================
export type VoltageRange = '200mV' | '1V' | '5V' | '10V' | '60V'

export type TerminalConfig = 'differential' | 'RSE' | 'NRSE' | 'pseudodifferential'

export interface VoltageInputConfig {
  range: VoltageRange
  terminal_config: TerminalConfig
  // Custom scaling (slope-intercept)
  scale_type: 'none' | 'linear' | 'map' | 'polynomial' | 'table'
  scale_slope?: number
  scale_offset?: number
  scaled_units?: string
  // For map scaling (e.g., 0-10V -> 0-100 PSI)
  pre_scaled_min?: number
  pre_scaled_max?: number
  scaled_min?: number
  scaled_max?: number
}

export const VOLTAGE_RANGES: { value: VoltageRange; label: string; modules: string[] }[] = [
  { value: '200mV', label: '±200 mV', modules: ['NI-9205', 'NI-9206'] },
  { value: '1V', label: '±1 V', modules: ['NI-9205', 'NI-9206'] },
  { value: '5V', label: '±5 V', modules: ['NI-9205', 'NI-9206'] },
  { value: '10V', label: '±10 V', modules: ['NI-9201', 'NI-9205', 'NI-9215', 'NI-9220', 'NI-9222', 'NI-9223'] },
  { value: '60V', label: '±60 V', modules: ['NI-9221', 'NI-9228', 'NI-9229'] },
]

export const TERMINAL_CONFIGS: { value: TerminalConfig; label: string; description: string }[] = [
  { value: 'differential', label: 'Differential', description: 'Best noise rejection, uses 2 inputs per channel' },
  { value: 'RSE', label: 'RSE', description: 'Referenced Single-Ended, ground-referenced' },
  { value: 'NRSE', label: 'NRSE', description: 'Non-Referenced Single-Ended, AI SENSE referenced' },
  { value: 'pseudodifferential', label: 'Pseudodifferential', description: 'For floating signals with common-mode' },
]

// =============================================================================
// CURRENT INPUT MODULES (NI-9203, 9207, 9208, 9227, 9246, 9247, 9253)
// =============================================================================
export type CurrentRange = '20mA' | '5A' | '20A' | '50A'

export interface CurrentInputConfig {
  range: CurrentRange
  shunt_location: 'internal' | 'external'
  shunt_resistance?: number // For external shunt
  // 4-20mA scaling
  four_twenty_scaling: boolean
  eng_units_min?: number // e.g., 0 PSI at 4mA
  eng_units_max?: number // e.g., 100 PSI at 20mA
  scaled_units?: string
}

export const CURRENT_RANGES: { value: CurrentRange; label: string; modules: string[] }[] = [
  { value: '20mA', label: '±20 mA', modules: ['NI-9203', 'NI-9207', 'NI-9208', 'NI-9253'] },
  { value: '5A', label: '5 Arms', modules: ['NI-9227'] },
  { value: '20A', label: '20 Arms', modules: ['NI-9246'] },
  { value: '50A', label: '50 Arms', modules: ['NI-9247'] },
]

// =============================================================================
// RTD MODULES (NI-9216, 9217, 9226)
// =============================================================================
export type RTDType = 'Pt100_3850' | 'Pt100_3911' | 'Pt100_3916' | 'Pt100_3920' | 'Pt100_3928' | 'Pt1000' | 'custom'

export type RTDWiring = '2-wire' | '3-wire' | '4-wire'

export interface RTDConfig {
  rtd_type: RTDType
  wiring: RTDWiring
  units: TemperatureUnits
  r0: number // Resistance at 0°C (100Ω for Pt100, 1000Ω for Pt1000)
  excitation_current: number // µA (typically 500-1000µA)
  // Custom RTD coefficients (Callendar-Van Dusen)
  custom_a?: number
  custom_b?: number
  custom_c?: number
}

export const RTD_TYPES: { value: RTDType; label: string; r0: number }[] = [
  { value: 'Pt100_3850', label: 'Pt100 (α=0.00385)', r0: 100 },
  { value: 'Pt100_3911', label: 'Pt100 (α=0.003911)', r0: 100 },
  { value: 'Pt100_3916', label: 'Pt100 (α=0.003916)', r0: 100 },
  { value: 'Pt100_3920', label: 'Pt100 (α=0.00392)', r0: 100 },
  { value: 'Pt100_3928', label: 'Pt100 (α=0.003928)', r0: 100 },
  { value: 'Pt1000', label: 'Pt1000', r0: 1000 },
  { value: 'custom', label: 'Custom', r0: 100 },
]

// =============================================================================
// STRAIN/BRIDGE MODULES (NI-9235, 9236, 9237, 9219)
// =============================================================================
export type BridgeConfig = 'full' | 'half' | 'quarter_I' | 'quarter_II' | 'quarter_III'

export interface StrainConfig {
  bridge_config: BridgeConfig
  nominal_resistance: number // Ω (120, 350, 1000 typical)
  gage_factor: number // Typically ~2.0
  poisson_ratio?: number // For quarter bridge correction
  excitation_voltage: number // V (typically 2.5V or 10V)
  lead_wire_resistance?: number // Ω, for lead wire compensation
  initial_bridge_voltage?: number // For offset/tare
  units: 'strain' | 'mV_per_V' | 'custom'
}

export const BRIDGE_CONFIGS: { value: BridgeConfig; label: string; description: string }[] = [
  { value: 'full', label: 'Full Bridge', description: '4 active elements, highest sensitivity' },
  { value: 'half', label: 'Half Bridge', description: '2 active elements' },
  { value: 'quarter_I', label: 'Quarter Bridge I', description: '1 active element, 3 completion resistors' },
  { value: 'quarter_II', label: 'Quarter Bridge II', description: '1 active + 1 dummy element' },
  { value: 'quarter_III', label: 'Quarter Bridge III', description: 'Temperature compensated quarter' },
]

// =============================================================================
// DIGITAL INPUT MODULES (NI-9401, 9402, 9403, 9411, 9421, 9422, 9423, etc.)
// =============================================================================
export type DigitalLogicLevel = 'TTL' | 'LVTTL' | '24V' | '60V' | '250V'

export interface DigitalInputConfig {
  logic_level: DigitalLogicLevel
  invert: boolean
  debounce_time?: number // µs
  line_states_on_start?: boolean // State when task starts
  tristate?: boolean // For bidirectional modules
}

// =============================================================================
// DIGITAL OUTPUT MODULES (NI-9401, 9470, 9472, 9474, 9475, 9476, 9477, 9478)
// =============================================================================
export type OutputDriveType = 'sourcing' | 'sinking' | 'relay' | 'SSR'

export interface DigitalOutputConfig {
  drive_type: OutputDriveType
  invert: boolean
  initial_state: boolean
  watchdog_timeout?: number // ms, auto-reset on timeout
  tristate?: boolean
}

// =============================================================================
// ANALOG OUTPUT MODULES (NI-9260, 9262, 9263, 9264, 9265, 9266, 9269)
// =============================================================================
export type AnalogOutputType = 'voltage' | 'current'

export interface AnalogOutputConfig {
  output_type: AnalogOutputType
  range_min: number
  range_max: number
  // For voltage: typically ±10V
  // For current: typically 0-20mA or 4-20mA
  idle_output_behavior: 'zero' | 'hold_last' | 'custom'
  custom_idle_value?: number
  slew_rate_limit?: number // V/s or mA/s
}

// =============================================================================
// COUNTER/TIMER MODULES (NI-9361)
// =============================================================================
export type CounterMode = 'count_edges' | 'pulse_width' | 'frequency' | 'period' | 'position'

export type CounterEdge = 'rising' | 'falling' | 'both'

export interface CounterConfig {
  mode: CounterMode
  edge: CounterEdge
  initial_count: number
  count_direction: 'up' | 'down' | 'external'
  // For encoder/position mode
  decoding_type?: 'X1' | 'X2' | 'X4' | 'two_pulse'
  z_index_enable?: boolean
  z_index_phase?: 'A_high_B_high' | 'A_high_B_low' | 'A_low_B_high' | 'A_low_B_low'
  pulses_per_revolution?: number
}

// =============================================================================
// UNIVERSAL MODULE (NI-9219)
// =============================================================================
export type UniversalMeasType = 'voltage' | 'current' | 'thermocouple' | 'RTD' | 'resistance' | 'bridge'

export interface UniversalConfig {
  measurement_type: UniversalMeasType
  // Type-specific configs loaded based on measurement_type
  voltage_config?: VoltageInputConfig
  current_config?: CurrentInputConfig
  thermocouple_config?: ThermocoupleConfig
  rtd_config?: RTDConfig
  strain_config?: StrainConfig
}

// =============================================================================
// IEPE/ACCELEROMETER MODULES (NI-9230, 9231, 9232, 9233, 9234, 9250, 9251)
// =============================================================================
export interface IEPEConfig {
  coupling: 'AC' | 'DC'
  excitation_current: number // mA (typically 2-4mA)
  sensitivity: number // mV/g or mV/m/s²
  units: 'g' | 'm_s2' | 'mV'
  // For sound measurement
  reference_sensitivity?: number // mV/Pa
}

// =============================================================================
// COMBINED CHANNEL CONFIGURATION
// =============================================================================
export interface ChannelModuleConfig {
  // Common fields
  enabled: boolean
  label: string
  description?: string
  log_data: boolean

  // Display
  display_precision: number
  display_min?: number
  display_max?: number

  // Alarms
  alarm_low?: number
  alarm_high?: number
  warning_low?: number
  warning_high?: number
  alarm_enabled: boolean

  // Module-specific config (only one will be populated based on channel type)
  thermocouple?: ThermocoupleConfig
  voltage_input?: VoltageInputConfig
  current_input?: CurrentInputConfig
  rtd?: RTDConfig
  strain?: StrainConfig
  digital_input?: DigitalInputConfig
  digital_output?: DigitalOutputConfig
  analog_output?: AnalogOutputConfig
  counter?: CounterConfig
  iepe?: IEPEConfig
  universal?: UniversalConfig
}

// =============================================================================
// MODULE INFO DATABASE
// =============================================================================
export interface ModuleInfo {
  model: string
  category: string
  channels: number
  description: string
  sample_rate: string
  resolution: string
  configurable_params: string[]
}

export const NI_MODULES: Record<string, ModuleInfo> = {
  // Thermocouple
  'NI-9213': { model: 'NI-9213', category: 'thermocouple', channels: 16, description: '16-Ch Thermocouple Input', sample_rate: '75 S/s aggregate', resolution: '24-bit', configurable_params: ['tc_type', 'cjc_source', 'units', 'open_detect', 'auto_zero'] },
  'NI-9214': { model: 'NI-9214', category: 'thermocouple', channels: 16, description: '16-Ch Isothermal TC Input', sample_rate: '68 S/s aggregate', resolution: '24-bit', configurable_params: ['tc_type', 'cjc_source', 'units', 'open_detect', 'auto_zero'] },

  // Voltage Input
  'NI-9205': { model: 'NI-9205', category: 'voltage', channels: 32, description: '32-Ch ±10V Voltage Input', sample_rate: '250 kS/s', resolution: '16-bit', configurable_params: ['range', 'terminal_config', 'scaling'] },
  'NI-9215': { model: 'NI-9215', category: 'voltage', channels: 4, description: '4-Ch Simultaneous ±10V', sample_rate: '100 kS/s/ch', resolution: '16-bit', configurable_params: ['range', 'terminal_config', 'scaling'] },

  // Current Input
  'NI-9203': { model: 'NI-9203', category: 'current', channels: 8, description: '8-Ch ±20mA Current Input', sample_rate: '200 kS/s', resolution: '16-bit', configurable_params: ['range', 'shunt_location', '4-20_scaling'] },
  'NI-9208': { model: 'NI-9208', category: 'current', channels: 16, description: '16-Ch ±20mA Current Input', sample_rate: '500 S/s', resolution: '24-bit', configurable_params: ['range', 'shunt_location', '4-20_scaling'] },

  // RTD
  'NI-9217': { model: 'NI-9217', category: 'rtd', channels: 4, description: '4-Ch RTD Input (PT100)', sample_rate: '400 S/s aggregate', resolution: '24-bit', configurable_params: ['rtd_type', 'wiring', 'units', 'r0', 'excitation'] },

  // Strain/Bridge
  'NI-9237': { model: 'NI-9237', category: 'strain', channels: 4, description: '4-Ch Bridge Input', sample_rate: '50 kS/s/ch', resolution: '24-bit', configurable_params: ['bridge_config', 'excitation', 'gage_factor', 'nominal_resistance'] },

  // Universal
  'NI-9219': { model: 'NI-9219', category: 'universal', channels: 4, description: '4-Ch Universal Input', sample_rate: '100 S/s/ch', resolution: '24-bit', configurable_params: ['measurement_type', 'all_type_specific'] },

  // Digital I/O
  'NI-9375': { model: 'NI-9375', category: 'digital', channels: 32, description: '16 DI + 16 DO (30V)', sample_rate: '7µs/500µs', resolution: 'N/A', configurable_params: ['invert', 'debounce', 'initial_state'] },
  'NI-9401': { model: 'NI-9401', category: 'digital', channels: 8, description: '8-Ch Bidirectional TTL', sample_rate: '100ns', resolution: 'N/A', configurable_params: ['direction', 'invert', 'tristate'] },

  // Analog Output
  'NI-9263': { model: 'NI-9263', category: 'analog_output', channels: 4, description: '4-Ch ±10V Voltage Output', sample_rate: '100 kS/s/ch', resolution: '16-bit', configurable_params: ['range', 'idle_behavior'] },
  'NI-9265': { model: 'NI-9265', category: 'analog_output', channels: 4, description: '4-Ch 0-20mA Current Output', sample_rate: '100 kS/s', resolution: '16-bit', configurable_params: ['range', 'idle_behavior'] },
}

// Default configurations
export const DEFAULT_THERMOCOUPLE_CONFIG: ThermocoupleConfig = {
  tc_type: 'K',
  units: 'C',
  cjc_source: 'internal',
  open_detect: true,
  auto_zero: true,
}

export const DEFAULT_VOLTAGE_INPUT_CONFIG: VoltageInputConfig = {
  range: '10V',
  terminal_config: 'differential',
  scale_type: 'none',
}

export const DEFAULT_CURRENT_INPUT_CONFIG: CurrentInputConfig = {
  range: '20mA',
  shunt_location: 'internal',
  four_twenty_scaling: false,
}

export const DEFAULT_RTD_CONFIG: RTDConfig = {
  rtd_type: 'Pt100_3850',
  wiring: '4-wire',
  units: 'C',
  r0: 100,
  excitation_current: 1000,
}

export const DEFAULT_DIGITAL_INPUT_CONFIG: DigitalInputConfig = {
  logic_level: '24V',
  invert: false,
  debounce_time: 0,
}

export const DEFAULT_DIGITAL_OUTPUT_CONFIG: DigitalOutputConfig = {
  drive_type: 'sourcing',
  invert: false,
  initial_state: false,
}

export const DEFAULT_ANALOG_OUTPUT_CONFIG: AnalogOutputConfig = {
  output_type: 'voltage',
  range_min: -10,
  range_max: 10,
  idle_output_behavior: 'zero',
}
