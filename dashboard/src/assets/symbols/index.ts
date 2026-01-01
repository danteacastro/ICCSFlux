// =============================================================================
// SCADA Symbol Library - Industrial Process Equipment SVG Symbols
// =============================================================================
// All symbols are SVG strings that can be rendered inline with dynamic coloring
// via CSS currentColor. Symbols scale to any size.

// =============================================================================
// VALVES
// =============================================================================

// Solenoid Valve (2-way, inline)
export const SolenoidValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M15 12 L30 20 L15 28 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 12 L30 20 L45 28 Z" class="valve-body" fill="currentColor"/>
  <rect x="22" y="2" width="16" height="10" rx="1" class="actuator" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="12" x2="30" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Control Valve (globe style with diaphragm actuator)
export const ControlValve = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M15 22 L30 30 L15 38 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" class="valve-body" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="8" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Manual Valve (handwheel)
export const ManualValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="21" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M15 17 L30 25 L15 33 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 17 L30 25 L45 33 Z" class="valve-body" fill="currentColor"/>
  <line x1="30" y1="17" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="5" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Check Valve (non-return)
export const CheckValve = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 15 L28 15 M24 10 L28 15 L24 20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
`

// Ball Valve
export const BallValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="20" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="30" cy="20" r="6" fill="currentColor" opacity="0.5"/>
  <line x1="30" y1="8" x2="30" y2="3" stroke="currentColor" stroke-width="2"/>
  <rect x="25" y="0" width="10" height="4" fill="currentColor"/>
</svg>
`

// Butterfly Valve
export const ButterflyValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="18" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="42" y="16" width="18" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="20" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="14" x2="38" y2="26" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="10" x2="30" y2="3" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Relief/Safety Valve
export const ReliefValve = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="21" y="35" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <path d="M15 35 L25 25 L35 35 Z" fill="currentColor"/>
  <rect x="18" y="10" width="14" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="10" x2="25" y2="3" stroke="currentColor" stroke-width="2"/>
  <path d="M20 3 L25 8 L30 3" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// 3-Way Valve
export const ThreeWayValve = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="26" y="45" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <path d="M22 45 L30 30 L38 45 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="8" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Gate Valve
export const GateValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="21" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="15" y="15" width="30" height="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="15" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="5" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Needle Valve
export const NeedleValve = `
<svg viewBox="0 0 50 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="38" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M12 17 L25 25 L12 33 Z" fill="currentColor"/>
  <path d="M38 17 L25 25 L38 33 Z" fill="currentColor"/>
  <line x1="25" y1="17" x2="25" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <polygon points="25,25 23,17 27,17" fill="currentColor"/>
  <circle cx="25" cy="5" r="4" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// =============================================================================
// INSTRUMENTS - Transmitters & Sensors
// =============================================================================

// Pressure Transmitter
export const PressureTransducer = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="35" width="10" height="15" fill="currentColor" opacity="0.3"/>
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">PT</text>
</svg>
`

// Temperature Element
export const TemperatureElement = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="25" width="6" height="25" rx="3" fill="currentColor" opacity="0.3"/>
  <circle cx="15" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="15" y="19" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">TE</text>
</svg>
`

// Flow Meter/Transmitter
export const FlowMeter = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="60" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="30" y="24" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">FT</text>
</svg>
`

// Level Transmitter
export const LevelTransmitter = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="35" width="10" height="15" fill="currentColor" opacity="0.3"/>
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">LT</text>
</svg>
`

// Flow Switch
export const FlowSwitch = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="50" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="17" y="5" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="16" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">FS</text>
  <path d="M20 25 L25 30 L30 25" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Pressure Switch
export const PressureSwitch = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="35" width="10" height="15" fill="currentColor" opacity="0.3"/>
  <rect x="5" y="5" width="30" height="25" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="21" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">PS</text>
</svg>
`

// Thermowell
export const Thermowell = `
<svg viewBox="0 0 20 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="6" y="0" width="8" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="8" y="15" width="4" height="40" rx="2" fill="currentColor" opacity="0.5"/>
  <line x1="10" y1="55" x2="10" y2="60" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Analyzer (generic)
export const Analyzer = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="40" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="29" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">AT</text>
  <rect x="10" y="40" width="6" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="34" y="40" width="6" height="10" fill="currentColor" opacity="0.3"/>
</svg>
`

// pH Sensor
export const PHSensor = `
<svg viewBox="0 0 40 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="0" width="16" height="20" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="14" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">pH</text>
  <rect x="16" y="20" width="8" height="30" rx="4" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.3"/>
  <circle cx="20" cy="45" r="3" fill="currentColor"/>
</svg>
`

// Conductivity Sensor
export const ConductivitySensor = `
<svg viewBox="0 0 40 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="0" width="20" height="18" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="12" text-anchor="middle" font-size="7" font-weight="bold" fill="currentColor">AE</text>
  <rect x="14" y="18" width="12" height="32" rx="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="17" y1="25" x2="17" y2="45" stroke="currentColor" stroke-width="1.5"/>
  <line x1="23" y1="25" x2="23" y2="45" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Pressure Gauge (local indicator)
export const PressureGauge = `
<svg viewBox="0 0 50 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="22" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="26" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">PI</text>
  <rect x="21" y="40" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <line x1="25" y1="10" x2="25" y2="22" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
</svg>
`

// Temperature Indicator
export const TemperatureIndicator = `
<svg viewBox="0 0 35 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="17" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="17" y="24" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">TI</text>
  <rect x="14" y="34" width="6" height="20" rx="3" fill="currentColor" opacity="0.3"/>
</svg>
`

// =============================================================================
// EQUIPMENT - Rotating & Process
// =============================================================================

// Pump (centrifugal)
export const Pump = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="21" y="0" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="20" r="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 25 L25 15 L32 25" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
`

// Positive Displacement Pump
export const PDPump = `
<svg viewBox="0 0 55 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="16" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="27" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="13" y="14" width="28" height="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 20 L27 13 L34 20" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Compressor
export const Compressor = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="50" y="21" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <polygon points="30,12 22,30 38,30" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="30" y="44" text-anchor="middle" font-size="7" fill="currentColor">C</text>
</svg>
`

// Blower/Fan
export const Blower = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="8" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="28" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M28 10 Q35 18 28 25 Q21 32 28 40" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 18 Q23 25 15 32" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="28" cy="25" r="4" fill="currentColor"/>
</svg>
`

// Electric Motor
export const Motor = `
<svg viewBox="0 0 60 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="15" cy="17" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="15" y="21" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">M</text>
  <line x1="27" y1="17" x2="45" y2="17" stroke="currentColor" stroke-width="3"/>
  <rect x="45" y="10" width="12" height="14" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Agitator/Mixer
export const Mixer = `
<svg viewBox="0 0 40 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="0" width="16" height="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="9" text-anchor="middle" font-size="7" font-weight="bold" fill="currentColor">M</text>
  <line x1="20" y1="12" x2="20" y2="45" stroke="currentColor" stroke-width="2"/>
  <line x1="10" y1="35" x2="30" y2="35" stroke="currentColor" stroke-width="3"/>
  <line x1="12" y1="45" x2="28" y2="45" stroke="currentColor" stroke-width="2.5"/>
</svg>
`

// Filter
export const Filter = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="21" y="0" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="21" y="40" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <polygon points="25,12 8,38 42,38" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="12" y1="25" x2="38" y2="25" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="15" y1="31" x2="35" y2="31" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
</svg>
`

// Electric Heater
export const Heater = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="30" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 20 L15 15 L20 25 L25 15 L30 20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="12" y1="40" x2="12" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="28" y1="40" x2="28" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Cooler/Chiller
export const Cooler = `
<svg viewBox="0 0 45 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="35" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M22 15 L22 35 M15 25 L30 25 M17 18 L28 32 M28 18 L17 32" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <rect x="18" y="40" width="9" height="10" fill="currentColor" opacity="0.3"/>
</svg>
`

// =============================================================================
// HEAT EXCHANGERS
// =============================================================================

// Shell & Tube Heat Exchanger
export const HeatExchanger = `
<svg viewBox="0 0 80 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="10" cy="25" rx="8" ry="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="70" cy="25" rx="8" ry="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="5" x2="70" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="10" y1="45" x2="70" y2="45" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="15" x2="60" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="35" x2="60" y2="35" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Plate Heat Exchanger
export const PlateHeatExchanger = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="5" width="30" height="50" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="25" x2="40" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="35" x2="40" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="45" x2="40" y2="45" stroke="currentColor" stroke-width="1"/>
  <rect x="0" y="8" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="46" width="10" height="6" fill="currentColor" opacity="0.3"/>
</svg>
`

// Condenser
export const Condenser = `
<svg viewBox="0 0 70 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="10" cy="25" rx="8" ry="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="60" cy="25" rx="8" ry="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="7" x2="60" y2="7" stroke="currentColor" stroke-width="2"/>
  <line x1="10" y1="43" x2="60" y2="43" stroke="currentColor" stroke-width="2"/>
  <path d="M20 20 L50 20 M20 25 L50 25 M20 30 L50 30" stroke="currentColor" stroke-width="1"/>
  <rect x="30" y="0" width="10" height="7" fill="currentColor" opacity="0.3"/>
  <rect x="30" y="43" width="10" height="7" fill="currentColor" opacity="0.3"/>
</svg>
`

// Air Cooled Heat Exchanger (Fin Fan)
export const AirCooler = `
<svg viewBox="0 0 70 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="25" width="60" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="25" x2="15" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="25" y1="25" x2="25" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="35" y1="25" x2="35" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="45" y1="25" x2="45" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="55" y1="25" x2="55" y2="40" stroke="currentColor" stroke-width="1"/>
  <circle cx="35" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M35 5 L35 19 M28 12 L42 12" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// =============================================================================
// VESSELS & TANKS
// =============================================================================

// Vertical Tank
export const Tank = `
<svg viewBox="0 0 60 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 Q10 5 30 5 Q50 5 50 15 L50 65 Q50 75 30 75 Q10 75 10 65 Z"
        stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="15" y="20" width="30" height="50" class="level-area" fill="currentColor" opacity="0.1"/>
  <rect x="15" y="40" width="30" height="30" class="level-fill" fill="currentColor" opacity="0.4"/>
</svg>
`

// Horizontal Tank/Drum
export const HorizontalTank = `
<svg viewBox="0 0 80 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="15" cy="25" rx="12" ry="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="65" cy="25" rx="12" ry="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="7" x2="65" y2="7" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="43" x2="65" y2="43" stroke="currentColor" stroke-width="2"/>
  <rect x="20" y="25" width="40" height="18" fill="currentColor" opacity="0.3"/>
</svg>
`

// Reactor with Agitator
export const Reactor = `
<svg viewBox="0 0 60 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 Q10 5 30 5 Q50 5 50 15 L50 55 Q50 75 30 75 Q10 75 10 55 Z"
        stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="0" x2="30" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="45" x2="40" y2="45" stroke="currentColor" stroke-width="3"/>
  <rect x="22" y="-8" width="16" height="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Column/Tower
export const Column = `
<svg viewBox="0 0 40 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 10 Q8 2 20 2 Q32 2 32 10 L32 90 Q32 98 20 98 Q8 98 8 90 Z"
        stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="25" x2="32" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="8" y1="40" x2="32" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="8" y1="55" x2="32" y2="55" stroke="currentColor" stroke-width="1"/>
  <line x1="8" y1="70" x2="32" y2="70" stroke="currentColor" stroke-width="1"/>
  <line x1="8" y1="85" x2="32" y2="85" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Cyclone Separator
export const Cyclone = `
<svg viewBox="0 0 50 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="25" cy="15" rx="18" ry="8" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M7 15 L20 60 Q25 70 30 60 L43 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="0" y="11" width="7" height="8" fill="currentColor" opacity="0.3"/>
  <line x1="25" y1="7" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Separator/Knockout Drum
export const Separator = `
<svg viewBox="0 0 60 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="30" cy="12" rx="22" ry="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="30" cy="58" rx="22" ry="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="12" x2="8" y2="58" stroke="currentColor" stroke-width="2"/>
  <line x1="52" y1="12" x2="52" y2="58" stroke="currentColor" stroke-width="2"/>
  <line x1="12" y1="35" x2="48" y2="35" stroke="currentColor" stroke-width="1" stroke-dasharray="4,2"/>
  <rect x="0" y="30" width="8" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="52" y="8" width="8" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="26" y="60" width="8" height="10" fill="currentColor" opacity="0.3"/>
</svg>
`

// Storage Sphere
export const Sphere = `
<svg viewBox="0 0 60 65" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="28" r="25" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="30" cy="28" rx="25" ry="8" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="15" y1="53" x2="15" y2="62" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="53" x2="45" y2="62" stroke="currentColor" stroke-width="2"/>
  <line x1="10" y1="62" x2="50" y2="62" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// PIPING & CONNECTIONS
// =============================================================================

// Horizontal Pipe
export const PipeHorizontal = `
<svg viewBox="0 0 60 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="6" width="60" height="8" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="6" x2="60" y2="6" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="14" x2="60" y2="14" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Vertical Pipe
export const PipeVertical = `
<svg viewBox="0 0 20 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="6" y="0" width="8" height="60" fill="currentColor" opacity="0.4"/>
  <line x1="6" y1="0" x2="6" y2="60" stroke="currentColor" stroke-width="1"/>
  <line x1="14" y1="0" x2="14" y2="60" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Elbow (90 degree)
export const Elbow90 = `
<svg viewBox="0 0 35 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M6 0 L6 20 Q6 29 15 29 L35 29" fill="currentColor" opacity="0.4"/>
  <path d="M14 0 L14 20 Q14 21 15 21 L35 21" fill="currentColor" opacity="0.4"/>
  <path d="M6 0 L6 20 Q6 29 15 29 L35 29" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M14 0 L14 20 Q14 21 15 21 L35 21" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Tee
export const PipeTee = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="50" height="8" fill="currentColor" opacity="0.4"/>
  <rect x="21" y="0" width="8" height="24" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="16" x2="50" y2="16" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="24" x2="50" y2="24" stroke="currentColor" stroke-width="1"/>
  <line x1="21" y1="0" x2="21" y2="16" stroke="currentColor" stroke-width="1"/>
  <line x1="29" y1="0" x2="29" y2="16" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Reducer
export const Reducer = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M0 8 L15 8 L35 12 L50 12 L50 18 L35 18 L15 22 L0 22 Z" fill="currentColor" opacity="0.4"/>
  <path d="M0 8 L15 8 L35 12 L50 12" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M0 22 L15 22 L35 18 L50 18" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Flange
export const Flange = `
<svg viewBox="0 0 30 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="11" y="0" width="8" height="40" fill="currentColor" opacity="0.3"/>
  <rect x="3" y="15" width="24" height="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="7" cy="20" r="2" fill="currentColor"/>
  <circle cx="23" cy="20" r="2" fill="currentColor"/>
</svg>
`

// Blind Flange / Cap
export const BlindFlange = `
<svg viewBox="0 0 30 25" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="11" y="10" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <rect x="0" y="0" width="30" height="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="6" cy="6" r="2" fill="currentColor"/>
  <circle cx="24" cy="6" r="2" fill="currentColor"/>
</svg>
`

// Expansion Joint
export const ExpansionJoint = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M10 8 L15 8 L15 22 L10 22 M40 8 L35 8 L35 22 L40 22" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 10 Q20 15 25 10 Q30 5 35 10 M15 20 Q20 15 25 20 Q30 25 35 20" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// =============================================================================
// MISCELLANEOUS
// =============================================================================

// Rupture Disc
export const RuptureDisc = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="16" y="30" width="8" height="20" fill="currentColor" opacity="0.3"/>
  <circle cx="20" cy="18" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M12 12 L28 24 M12 24 L28 12" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Flame Arrestor
export const FlameArrestor = `
<svg viewBox="0 0 40 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="13" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="28" y="13" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="12" y="5" width="16" height="24" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="10" x2="25" y2="10" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="15" x2="25" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="20" x2="25" y2="20" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="25" x2="25" y2="25" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Strainer
export const Strainer = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="35" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <polygon points="15,12 35,12 35,28 15,28 20,20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="15" x2="22" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="26" y1="14" x2="26" y2="26" stroke="currentColor" stroke-width="1"/>
  <line x1="30" y1="13" x2="30" y2="27" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Sight Glass
export const SightGlass = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="16" y="0" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="16" y="40" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="8" y="10" width="24" height="30" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="12" y="14" width="16" height="22" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.15"/>
</svg>
`

// Static Mixer
export const StaticMixer = `
<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="50" y="11" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="10" y="5" width="40" height="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 8 L25 22 M25 8 L35 22 M35 8 L45 22" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Spray Nozzle
export const SprayNozzle = `
<svg viewBox="0 0 40 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="16" y="0" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <polygon points="20,15 8,40 32,40" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="14" y1="30" x2="10" y2="42" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="20" y1="32" x2="20" y2="45" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="26" y1="30" x2="30" y2="42" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
</svg>
`

// Ejector/Eductor
export const Ejector = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="50" y="16" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="22" y="0" width="8" height="12" fill="currentColor" opacity="0.3"/>
  <path d="M10 12 L20 12 L20 28 L10 28" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 16 L30 16 L40 12 L50 12 L50 28 L40 28 L30 24 L20 24" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="26" y1="12" x2="26" y2="16" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// HYDROGEN & FUEL CELL EQUIPMENT
// =============================================================================

// PEM/SOFC Fuel Cell Stack
export const FuelCell = `
<svg viewBox="0 0 70 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="8" width="50" height="44" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="18" x2="60" y2="18" stroke="currentColor" stroke-width="1.5"/>
  <line x1="10" y1="28" x2="60" y2="28" stroke="currentColor" stroke-width="1.5"/>
  <line x1="10" y1="38" x2="60" y2="38" stroke="currentColor" stroke-width="1.5"/>
  <line x1="10" y1="48" x2="60" y2="48" stroke="currentColor" stroke-width="1.5"/>
  <rect x="0" y="20" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="60" y="20" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="0" y="36" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="60" y="36" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <text x="35" y="6" text-anchor="middle" font-size="6" fill="currentColor">H₂</text>
  <circle cx="25" cy="23" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="45" cy="23" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="25" cy="43" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="45" cy="43" r="3" fill="currentColor" opacity="0.4"/>
  <path d="M28 33 L35 28 L42 33 L35 38 Z" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.3"/>
</svg>
`

// Water Electrolyzer (PEM/Alkaline)
export const Electrolyzer = `
<svg viewBox="0 0 60 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="15" width="40" height="45" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="18" y="0" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <rect x="34" y="0" width="8" height="15" fill="currentColor" opacity="0.3"/>
  <line x1="22" y1="0" x2="22" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="38" y1="0" x2="38" y2="8" stroke="currentColor" stroke-width="2"/>
  <text x="22" y="12" text-anchor="middle" font-size="5" fill="currentColor">+</text>
  <text x="38" y="12" text-anchor="middle" font-size="5" fill="currentColor">-</text>
  <line x1="30" y1="20" x2="30" y2="55" stroke="currentColor" stroke-width="2" stroke-dasharray="3,2"/>
  <circle cx="20" cy="30" r="2" fill="currentColor" opacity="0.5"/>
  <circle cx="18" cy="38" r="2" fill="currentColor" opacity="0.5"/>
  <circle cx="22" cy="45" r="2" fill="currentColor" opacity="0.5"/>
  <circle cx="40" cy="32" r="2" fill="currentColor" opacity="0.5"/>
  <circle cx="38" cy="42" r="2" fill="currentColor" opacity="0.5"/>
  <circle cx="42" cy="48" r="2" fill="currentColor" opacity="0.5"/>
  <text x="20" y="65" text-anchor="middle" font-size="5" fill="currentColor">H₂</text>
  <text x="40" y="65" text-anchor="middle" font-size="5" fill="currentColor">O₂</text>
  <rect x="26" y="60" width="8" height="10" fill="currentColor" opacity="0.3"/>
</svg>
`

// Steam Methane Reformer (SMR)
export const SteamReformer = `
<svg viewBox="0 0 70 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="10" width="40" height="55" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="20" y="15" width="30" height="20" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.1"/>
  <text x="35" y="28" text-anchor="middle" font-size="6" fill="currentColor">CAT</text>
  <path d="M20 45 L25 40 L30 50 L35 40 L40 50 L45 40 L50 45" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <rect x="22" y="52" width="26" height="8" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <rect x="0" y="18" width="15" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="55" y="18" width="15" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="0" y="28" width="15" height="6" fill="currentColor" opacity="0.3"/>
  <text x="7" y="16" text-anchor="middle" font-size="5" fill="currentColor">CH₄</text>
  <text x="7" y="38" text-anchor="middle" font-size="5" fill="currentColor">H₂O</text>
  <text x="63" y="16" text-anchor="middle" font-size="5" fill="currentColor">H₂</text>
  <rect x="31" y="65" width="8" height="15" fill="currentColor" opacity="0.3"/>
</svg>
`

// High-Pressure Hydrogen Storage Tank
export const HydrogenTank = `
<svg viewBox="0 0 50 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="25" cy="15" rx="18" ry="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="25" cy="65" rx="18" ry="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="7" y1="15" x2="7" y2="65" stroke="currentColor" stroke-width="2"/>
  <line x1="43" y1="15" x2="43" y2="65" stroke="currentColor" stroke-width="2"/>
  <text x="25" y="43" text-anchor="middle" font-size="12" font-weight="bold" fill="currentColor">H₂</text>
  <rect x="21" y="0" width="8" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="8" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="15" y1="25" x2="35" y2="25" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="15" y1="55" x2="35" y2="55" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
</svg>
`

// Hydrogen Fuel Dispenser
export const FuelDispenser = `
<svg viewBox="0 0 50 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="5" width="34" height="50" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="14" y="12" width="22" height="14" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.1"/>
  <text x="25" y="22" text-anchor="middle" font-size="7" font-weight="bold" fill="currentColor">H₂</text>
  <circle cx="25" cy="40" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="25" y="43" text-anchor="middle" font-size="6" fill="currentColor">PSI</text>
  <path d="M42 25 Q50 25 50 35 L50 55 Q50 60 45 60 L40 60" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="40" cy="60" r="4" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.3"/>
  <rect x="18" y="55" width="14" height="15" fill="currentColor" opacity="0.3"/>
</svg>
`

// =============================================================================
// GASIFICATION & BIOMASS EQUIPMENT
// =============================================================================

// Fluidized Bed Gasifier (U-GAS style)
export const Gasifier = `
<svg viewBox="0 0 60 90" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 20 Q15 10 30 10 Q45 10 45 20 L45 60 L50 70 L50 80 L10 80 L10 70 L15 60 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="30" cy="50" rx="12" ry="5" stroke="currentColor" stroke-width="1" fill="none" stroke-dasharray="2,2"/>
  <circle cx="22" cy="55" r="2" fill="currentColor" opacity="0.4"/>
  <circle cx="30" cy="52" r="2" fill="currentColor" opacity="0.4"/>
  <circle cx="38" cy="56" r="2" fill="currentColor" opacity="0.4"/>
  <circle cx="25" cy="62" r="2" fill="currentColor" opacity="0.4"/>
  <circle cx="35" cy="60" r="2" fill="currentColor" opacity="0.4"/>
  <rect x="0" y="30" width="15" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="25" width="15" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="26" y="0" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <path d="M20 35 L25 30 L30 38 L35 28 L40 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="30" y="78" text-anchor="middle" font-size="5" fill="currentColor">ASH</text>
</svg>
`

// Syngas Cleanup / Gas Scrubber
export const SyngasCleanup = `
<svg viewBox="0 0 50 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 Q10 5 25 5 Q40 5 40 15 L40 65 Q40 75 25 75 Q10 75 10 65 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="25" cy="25" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <ellipse cx="25" cy="40" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <ellipse cx="25" cy="55" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <rect x="0" y="60" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="18" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="21" y="75" width="8" height="5" fill="currentColor" opacity="0.3"/>
  <path d="M18 15 L20 12 L22 15 M25 13 L27 10 L29 13 M32 15 L34 12 L36 15" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Biomass Hopper/Feeder
export const Hopper = `
<svg viewBox="0 0 50 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,5 45,5 45,30 35,55 15,55 5,30" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="18" y="55" width="14" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="15" x2="45" y2="15" stroke="currentColor" stroke-width="1"/>
  <circle cx="15" cy="22" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="20" r="4" fill="currentColor" opacity="0.3"/>
  <circle cx="35" cy="23" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="20" cy="30" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="28" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="38" r="3" fill="currentColor" opacity="0.3"/>
  <path d="M22 60 L22 65 M25 58 L25 65 M28 60 L28 65" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// =============================================================================
// HEATING & COMBUSTION EQUIPMENT
// =============================================================================

// Fire-Tube/Water-Tube Boiler
export const Boiler = `
<svg viewBox="0 0 80 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="15" cy="30" rx="12" ry="25" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="65" cy="30" rx="12" ry="25" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="5" x2="65" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="55" x2="65" y2="55" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="40" x2="60" y2="40" stroke="currentColor" stroke-width="1"/>
  <path d="M25 48 L30 44 L35 50 L40 44 L45 50 L50 44 L55 48" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <rect x="36" y="0" width="8" height="5" fill="currentColor" opacity="0.3"/>
  <path d="M38 0 L40 -5 L42 0" stroke="currentColor" stroke-width="1" fill="none"/>
  <rect x="0" y="27" width="8" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="72" y="27" width="8" height="6" fill="currentColor" opacity="0.3"/>
</svg>
`

// Industrial Furnace
export const Furnace = `
<svg viewBox="0 0 70 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="50" height="40" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="15" y="15" width="40" height="25" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.15"/>
  <path d="M20 35 L25 28 L30 38 L35 25 L40 38 L45 28 L50 35" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
  <rect x="30" y="0" width="10" height="10" fill="currentColor" opacity="0.3"/>
  <path d="M33 5 L35 0 L37 5" stroke="currentColor" stroke-width="1" fill="none"/>
  <rect x="0" y="22" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="60" y="22" width="10" height="8" fill="currentColor" opacity="0.3"/>
  <line x1="10" y1="50" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="50" x2="60" y2="50" stroke="currentColor" stroke-width="2"/>
  <rect x="25" y="48" width="20" height="12" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.2"/>
</svg>
`

// Regenerative Burner
export const Burner = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="30" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="30" r="10" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.2"/>
  <path d="M22 30 Q22 22 25 18 Q28 22 28 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M20 32 Q20 26 25 20 Q30 26 30 32" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.3"/>
  <rect x="21" y="0" width="8" height="12" fill="currentColor" opacity="0.3"/>
  <rect x="0" y="27" width="7" height="6" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="30" r="3" fill="currentColor"/>
</svg>
`

// Heating/Cooling Coil
export const Coil = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="50" height="40" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 15 Q15 10 20 15 Q25 20 30 15 Q35 10 40 15 Q45 20 50 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 25 Q15 20 20 25 Q25 30 30 25 Q35 20 40 25 Q45 30 50 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 35 Q15 30 20 35 Q25 40 30 35 Q35 30 40 35 Q45 40 50 35" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="0" y="12" width="5" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="55" y="32" width="5" height="6" fill="currentColor" opacity="0.3"/>
</svg>
`

// Tankless/Tank Water Heater
export const WaterHeater = `
<svg viewBox="0 0 45 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="10" width="30" height="50" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 45 L18 40 L21 48 L24 38 L27 48 L30 40 L33 45" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <circle cx="23" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="23" y="28" text-anchor="middle" font-size="7" fill="currentColor">T</text>
  <rect x="12" y="0" width="6" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="28" y="0" width="6" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="19" y="60" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <line x1="8" y1="55" x2="38" y2="55" stroke="currentColor" stroke-width="1"/>
</svg>
`

// =============================================================================
// POWER GENERATION EQUIPMENT
// =============================================================================

// Combined Heat & Power (CHP) Unit
export const CHPUnit = `
<svg viewBox="0 0 80 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="70" height="40" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="40" y1="10" x2="40" y2="50" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="22" cy="30" r="12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="22" y="34" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">G</text>
  <rect x="48" y="18" width="20" height="24" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M52 35 L55 30 L58 38 L61 28 L64 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <rect x="0" y="25" width="5" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="75" y="18" width="5" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="75" y="36" width="5" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="18" y="0" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <path d="M20 5 L22 0 L24 5" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="10" y1="30" x2="34" y2="30" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Gas/Steam Turbine
export const Turbine = `
<svg viewBox="0 0 70 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="25" cy="25" rx="8" ry="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="50" cy="25" rx="8" ry="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M33 10 L42 13" stroke="currentColor" stroke-width="2"/>
  <path d="M33 40 L42 37" stroke="currentColor" stroke-width="2"/>
  <path d="M33 25 L42 25" stroke="currentColor" stroke-width="2"/>
  <line x1="58" y1="25" x2="70" y2="25" stroke="currentColor" stroke-width="3"/>
  <rect x="0" y="21" width="17" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M20 15 L25 25 L20 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M25 12 L30 25 L25 38" stroke="currentColor" stroke-width="1" fill="none"/>
  <circle cx="25" cy="25" r="4" fill="currentColor" opacity="0.4"/>
</svg>
`

// Electric Generator
export const Generator = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="35" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="35" cy="25" r="10" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="35" y="29" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">G</text>
  <line x1="0" y1="25" x2="17" y2="25" stroke="currentColor" stroke-width="3"/>
  <rect x="53" y="15" width="7" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="53" y="29" width="7" height="6" fill="currentColor" opacity="0.3"/>
  <path d="M55 12 L58 8 L61 12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M55 38 L58 42 L61 38" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="53" y1="18" x2="60" y2="18" stroke="currentColor" stroke-width="1"/>
  <line x1="53" y1="32" x2="60" y2="32" stroke="currentColor" stroke-width="1"/>
</svg>
`

// =============================================================================
// OFF-PAGE CONNECTORS (P&ID Reference Tags)
// =============================================================================

// Off-Page Connector - Arrow pointing right (flow continues to another page)
export const OffPageConnectorRight = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <polygon points="15,8 45,8 55,20 45,32 15,32" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <text x="30" y="24" text-anchor="middle" font-size="12" font-weight="bold" fill="currentColor" font-family="sans-serif">→</text>
</svg>
`

// Off-Page Connector - Arrow pointing left (flow coming from another page)
export const OffPageConnectorLeft = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="45" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <polygon points="45,8 15,8 5,20 15,32 45,32" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <text x="30" y="24" text-anchor="middle" font-size="12" font-weight="bold" fill="currentColor" font-family="sans-serif">←</text>
</svg>
`

// Off-Page Connector - Pentagon (standard P&ID style, to page)
export const OffPageConnectorTo = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,5 45,5 45,35 25,45 5,35" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <path d="M25 18 L25 30 M19 24 L25 30 L31 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
`

// Off-Page Connector - Pentagon inverted (from page)
export const OffPageConnectorFrom = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,15 25,5 45,15 45,45 5,45" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <path d="M25 32 L25 20 M19 26 L25 20 L31 26" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
`

// Flow Arrow - Horizontal right
export const FlowArrowRight = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="5" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="3"/>
  <polygon points="35,8 48,15 35,22" fill="currentColor"/>
</svg>
`

// Flow Arrow - Horizontal left
export const FlowArrowLeft = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="10" y1="15" x2="45" y2="15" stroke="currentColor" stroke-width="3"/>
  <polygon points="15,8 2,15 15,22" fill="currentColor"/>
</svg>
`

// Flow Arrow - Vertical down
export const FlowArrowDown = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="15" y1="5" x2="15" y2="40" stroke="currentColor" stroke-width="3"/>
  <polygon points="8,35 15,48 22,35" fill="currentColor"/>
</svg>
`

// Flow Arrow - Vertical up
export const FlowArrowUp = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="15" y1="10" x2="15" y2="45" stroke="currentColor" stroke-width="3"/>
  <polygon points="8,15 15,2 22,15" fill="currentColor"/>
</svg>
`

// =============================================================================
// ADDITIONAL SYMBOLS
// =============================================================================

// Horizontal Drum (accumulator/receiver)
export const Drum = `
<svg viewBox="0 0 80 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="10" cy="25" rx="10" ry="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="70" cy="25" rx="10" ry="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="5" x2="70" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="10" y1="45" x2="70" y2="45" stroke="currentColor" stroke-width="2"/>
  <rect x="35" y="45" width="10" height="5" fill="currentColor" opacity="0.3"/>
</svg>
`

// Agitator/Impeller (for reactor vessels)
export const Agitator = `
<svg viewBox="0 0 40 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="17" y="0" width="6" height="8" fill="currentColor"/>
  <line x1="20" y1="8" x2="20" y2="35" stroke="currentColor" stroke-width="2"/>
  <path d="M8 35 L20 42 L32 35" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 45 L20 52 L32 45" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// VFD/Variable Frequency Drive
export const VFD = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="40" height="50" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="25" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">VFD</text>
  <rect x="12" y="32" width="26" height="8" rx="1" stroke="currentColor" stroke-width="1" fill="none"/>
  <circle cx="15" cy="48" r="3" fill="currentColor" opacity="0.5"/>
  <circle cx="25" cy="48" r="3" fill="currentColor" opacity="0.5"/>
  <circle cx="35" cy="48" r="3" fill="currentColor" opacity="0.5"/>
</svg>
`

// Orifice Plate (flow restriction)
export const OrificePlate = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="35" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <line x1="20" y1="5" x2="20" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="5" x2="30" y2="35" stroke="currentColor" stroke-width="2"/>
  <path d="M20 15 Q25 20 30 15" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M20 25 Q25 20 30 25" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Diaphragm Valve
export const DiaphragmValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="25" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="25" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="15" y="20" width="30" height="18" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 29 Q30 22 40 29" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="20" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Plug Valve
export const PlugValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="16" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="20" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="26" y="14" width="8" height="12" fill="currentColor" opacity="0.4"/>
  <line x1="30" y1="8" x2="30" y2="2" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pressure Regulator
export const PressureRegulator = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="45" y="26" width="15" height="8" fill="currentColor" opacity="0.3"/>
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="12" stroke="currentColor" stroke-width="2"/>
  <rect x="22" y="2" width="16" height="10" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="30" y="10" text-anchor="middle" font-size="6" fill="currentColor">REG</text>
</svg>
`

// Centrifuge
export const Centrifuge = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="35" r="22" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="30" cy="35" r="12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="13" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <rect x="26" y="0" width="8" height="6" fill="currentColor"/>
  <path d="M22 35 L30 28 L38 35 L30 42 Z" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.3"/>
</svg>
`

// Evaporator
export const Evaporator = `
<svg viewBox="0 0 60 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="15" width="40" height="45" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 35 Q25 30 30 35 Q35 40 40 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M20 45 Q25 40 30 45 Q35 50 40 45" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="0" x2="30" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="60" x2="30" y2="70" stroke="currentColor" stroke-width="2"/>
  <rect x="5" y="22" width="5" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="50" y="22" width="5" height="8" fill="currentColor" opacity="0.3"/>
</svg>
`

// Scrubber (gas cleaning)
export const Scrubber = `
<svg viewBox="0 0 50 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 L10 65 Q10 75 25 75 Q40 75 40 65 L40 15 Q40 5 25 5 Q10 5 10 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="25" x2="35" y2="25" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="15" y1="40" x2="35" y2="40" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="15" y1="55" x2="35" y2="55" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <rect x="0" y="60" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="30" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <line x1="25" y1="75" x2="25" y2="80" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Absorber Tower
export const Absorber = `
<svg viewBox="0 0 50 90" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 10 L10 75 Q10 85 25 85 Q40 85 40 75 L40 10 Q40 0 25 0 Q10 0 10 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="25" cy="20" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <ellipse cx="25" cy="40" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <ellipse cx="25" cy="60" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <rect x="0" y="45" width="10" height="6" fill="currentColor" opacity="0.3"/>
  <rect x="40" y="25" width="10" height="6" fill="currentColor" opacity="0.3"/>
</svg>
`

// Diaphragm Pump
export const DiaphragmPump = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="48" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="15" y="10" width="30" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M25 15 L25 35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M35 15 L35 35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M25 25 Q30 18 35 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="26" y="0" width="8" height="10" fill="currentColor"/>
</svg>
`

// Gear Pump
export const GearPump = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="48" y="21" width="12" height="8" fill="currentColor" opacity="0.3"/>
  <rect x="15" y="10" width="30" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="35" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="25" cy="25" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="35" cy="25" r="3" fill="currentColor" opacity="0.4"/>
</svg>
`

// Axial Fan
export const AxialFan = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="25" r="22" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="25" r="5" fill="currentColor"/>
  <path d="M25 8 Q30 15 25 20" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M25 30 Q20 35 25 42" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 25 Q15 20 20 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M30 25 Q35 30 42 25" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Load Cell / Weight Scale
export const LoadCell = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="25" width="40" height="10" rx="1" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="5" x2="25" y2="25" stroke="currentColor" stroke-width="2"/>
  <polygon points="20,5 25,0 30,5" fill="currentColor"/>
  <polygon points="20,5 25,10 30,5" fill="currentColor"/>
  <circle cx="15" cy="30" r="2" fill="currentColor"/>
  <circle cx="35" cy="30" r="2" fill="currentColor"/>
</svg>
`

// Vibration Sensor
export const VibrationSensor = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="19" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">VT</text>
  <line x1="20" y1="27" x2="20" y2="40" stroke="currentColor" stroke-width="2"/>
  <rect x="15" y="40" width="10" height="6" fill="currentColor" opacity="0.5"/>
  <path d="M8 15 Q12 10 8 5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M32 15 Q28 10 32 5" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Spectacle Blind
export const SpectacleBlind = `
<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="15" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="45" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="currentColor" opacity="0.3"/>
  <line x1="27" y1="15" x2="33" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pipe Cross
export const PipeCross = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="0" width="10" height="40" fill="currentColor" opacity="0.3"/>
  <rect x="0" y="15" width="40" height="10" fill="currentColor" opacity="0.3"/>
  <rect x="15" y="15" width="10" height="10" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Pipe Cap
export const PipeCap = `
<svg viewBox="0 0 30 25" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="10" height="15" fill="currentColor" opacity="0.3"/>
  <path d="M5 10 Q15 0 25 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="10" x2="25" y2="10" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Power Supply
export const PowerSupply = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="40" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">PWR</text>
  <line x1="10" y1="35" x2="10" y2="40" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="35" x2="25" y2="40" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="35" x2="40" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Circuit Breaker
export const CircuitBreaker = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="30" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="20" y1="0" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="40" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
  <path d="M12 20 L20 25 L28 20" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="20" cy="32" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Transformer
export const Transformer = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="18" cy="30" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="32" cy="30" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="6" y1="30" x2="0" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="44" y1="30" x2="50" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="18" y1="18" x2="18" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="32" y1="42" x2="32" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Conveyor
export const Conveyor = `
<svg viewBox="0 0 80 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="12" cy="18" r="8" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="68" cy="18" r="8" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="12" y1="10" x2="68" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="12" y1="26" x2="68" y2="26" stroke="currentColor" stroke-width="2"/>
  <circle cx="12" cy="18" r="3" fill="currentColor"/>
  <circle cx="68" cy="18" r="3" fill="currentColor"/>
  <path d="M25 6 L35 6 L30 2 Z" fill="currentColor"/>
</svg>
`

// Dryer
export const Dryer = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="40" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 20 Q23 25 18 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M28 20 Q33 25 28 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M38 20 Q43 25 38 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="0" x2="30" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="40" x2="30" y2="50" stroke="currentColor" stroke-width="2"/>
  <rect x="0" y="22" width="10" height="6" fill="currentColor" opacity="0.3"/>
</svg>
`

// =============================================================================
// SYMBOL REGISTRY
// =============================================================================

export const SCADA_SYMBOLS = {
  // Valves
  solenoidValve: SolenoidValve,
  controlValve: ControlValve,
  manualValve: ManualValve,
  checkValve: CheckValve,
  ballValve: BallValve,
  butterflyValve: ButterflyValve,
  reliefValve: ReliefValve,
  threeWayValve: ThreeWayValve,
  gateValve: GateValve,
  needleValve: NeedleValve,
  // Instruments
  pressureTransducer: PressureTransducer,
  temperatureElement: TemperatureElement,
  flowMeter: FlowMeter,
  levelTransmitter: LevelTransmitter,
  flowSwitch: FlowSwitch,
  pressureSwitch: PressureSwitch,
  thermowell: Thermowell,
  analyzer: Analyzer,
  phSensor: PHSensor,
  conductivitySensor: ConductivitySensor,
  pressureGauge: PressureGauge,
  temperatureIndicator: TemperatureIndicator,
  // Equipment
  pump: Pump,
  pdPump: PDPump,
  compressor: Compressor,
  blower: Blower,
  motor: Motor,
  mixer: Mixer,
  filter: Filter,
  heater: Heater,
  cooler: Cooler,
  // Heat Exchangers
  heatExchanger: HeatExchanger,
  plateHeatExchanger: PlateHeatExchanger,
  condenser: Condenser,
  airCooler: AirCooler,
  // Vessels
  tank: Tank,
  horizontalTank: HorizontalTank,
  reactor: Reactor,
  column: Column,
  cyclone: Cyclone,
  separator: Separator,
  sphere: Sphere,
  // Piping
  pipeHorizontal: PipeHorizontal,
  pipeVertical: PipeVertical,
  elbow90: Elbow90,
  pipeTee: PipeTee,
  reducer: Reducer,
  flange: Flange,
  blindFlange: BlindFlange,
  expansionJoint: ExpansionJoint,
  // Miscellaneous
  ruptureDisc: RuptureDisc,
  flameArrestor: FlameArrestor,
  strainer: Strainer,
  sightGlass: SightGlass,
  staticMixer: StaticMixer,
  sprayNozzle: SprayNozzle,
  ejector: Ejector,
  // Hydrogen & Fuel Cell
  fuelCell: FuelCell,
  electrolyzer: Electrolyzer,
  steamReformer: SteamReformer,
  hydrogenTank: HydrogenTank,
  fuelDispenser: FuelDispenser,
  // Gasification & Biomass
  gasifier: Gasifier,
  syngasCleanup: SyngasCleanup,
  hopper: Hopper,
  // Heating & Combustion
  boiler: Boiler,
  furnace: Furnace,
  burner: Burner,
  coil: Coil,
  waterHeater: WaterHeater,
  // Power Generation
  chpUnit: CHPUnit,
  turbine: Turbine,
  generator: Generator,
  // Off-Page Connectors
  offPageRight: OffPageConnectorRight,
  offPageLeft: OffPageConnectorLeft,
  offPageTo: OffPageConnectorTo,
  offPageFrom: OffPageConnectorFrom,
  flowArrowRight: FlowArrowRight,
  flowArrowLeft: FlowArrowLeft,
  flowArrowDown: FlowArrowDown,
  flowArrowUp: FlowArrowUp,
  // Additional Equipment
  drum: Drum,
  agitator: Agitator,
  vfd: VFD,
  orificePlate: OrificePlate,
  diaphragmValve: DiaphragmValve,
  plugValve: PlugValve,
  pressureRegulator: PressureRegulator,
  centrifuge: Centrifuge,
  evaporator: Evaporator,
  scrubber: Scrubber,
  absorber: Absorber,
  diaphragmPump: DiaphragmPump,
  gearPump: GearPump,
  axialFan: AxialFan,
  loadCell: LoadCell,
  vibrationSensor: VibrationSensor,
  spectacleBlind: SpectacleBlind,
  pipeCross: PipeCross,
  pipeCap: PipeCap,
  powerSupply: PowerSupply,
  circuitBreaker: CircuitBreaker,
  transformer: Transformer,
  conveyor: Conveyor,
  dryer: Dryer,
} as const

export type ScadaSymbolType = keyof typeof SCADA_SYMBOLS

// Symbol metadata for UI
export const SYMBOL_INFO: Record<ScadaSymbolType, { label: string; category: string }> = {
  // Valves
  solenoidValve: { label: 'Solenoid Valve', category: 'Valves' },
  controlValve: { label: 'Control Valve', category: 'Valves' },
  manualValve: { label: 'Manual Valve', category: 'Valves' },
  checkValve: { label: 'Check Valve', category: 'Valves' },
  ballValve: { label: 'Ball Valve', category: 'Valves' },
  butterflyValve: { label: 'Butterfly Valve', category: 'Valves' },
  reliefValve: { label: 'Relief/Safety Valve', category: 'Valves' },
  threeWayValve: { label: '3-Way Valve', category: 'Valves' },
  gateValve: { label: 'Gate Valve', category: 'Valves' },
  needleValve: { label: 'Needle Valve', category: 'Valves' },
  // Instruments
  pressureTransducer: { label: 'Pressure Transmitter (PT)', category: 'Instruments' },
  temperatureElement: { label: 'Temperature Element (TE)', category: 'Instruments' },
  flowMeter: { label: 'Flow Transmitter (FT)', category: 'Instruments' },
  levelTransmitter: { label: 'Level Transmitter (LT)', category: 'Instruments' },
  flowSwitch: { label: 'Flow Switch (FS)', category: 'Instruments' },
  pressureSwitch: { label: 'Pressure Switch (PS)', category: 'Instruments' },
  thermowell: { label: 'Thermowell', category: 'Instruments' },
  analyzer: { label: 'Analyzer (AT)', category: 'Instruments' },
  phSensor: { label: 'pH Sensor', category: 'Instruments' },
  conductivitySensor: { label: 'Conductivity Sensor', category: 'Instruments' },
  pressureGauge: { label: 'Pressure Gauge (PI)', category: 'Instruments' },
  temperatureIndicator: { label: 'Temperature Indicator (TI)', category: 'Instruments' },
  // Equipment
  pump: { label: 'Centrifugal Pump', category: 'Equipment' },
  pdPump: { label: 'PD Pump', category: 'Equipment' },
  compressor: { label: 'Compressor', category: 'Equipment' },
  blower: { label: 'Blower/Fan', category: 'Equipment' },
  motor: { label: 'Electric Motor', category: 'Equipment' },
  mixer: { label: 'Agitator/Mixer', category: 'Equipment' },
  filter: { label: 'Filter', category: 'Equipment' },
  heater: { label: 'Electric Heater', category: 'Equipment' },
  cooler: { label: 'Cooler/Chiller', category: 'Equipment' },
  // Heat Exchangers
  heatExchanger: { label: 'Shell & Tube HX', category: 'Heat Exchangers' },
  plateHeatExchanger: { label: 'Plate Heat Exchanger', category: 'Heat Exchangers' },
  condenser: { label: 'Condenser', category: 'Heat Exchangers' },
  airCooler: { label: 'Air Cooler (Fin Fan)', category: 'Heat Exchangers' },
  // Vessels
  tank: { label: 'Vertical Tank', category: 'Vessels' },
  horizontalTank: { label: 'Horizontal Tank/Drum', category: 'Vessels' },
  reactor: { label: 'Reactor', category: 'Vessels' },
  column: { label: 'Column/Tower', category: 'Vessels' },
  cyclone: { label: 'Cyclone Separator', category: 'Vessels' },
  separator: { label: 'Separator/KO Drum', category: 'Vessels' },
  sphere: { label: 'Storage Sphere', category: 'Vessels' },
  // Piping
  pipeHorizontal: { label: 'Horizontal Pipe', category: 'Piping' },
  pipeVertical: { label: 'Vertical Pipe', category: 'Piping' },
  elbow90: { label: '90° Elbow', category: 'Piping' },
  pipeTee: { label: 'Pipe Tee', category: 'Piping' },
  reducer: { label: 'Reducer', category: 'Piping' },
  flange: { label: 'Flange', category: 'Piping' },
  blindFlange: { label: 'Blind Flange/Cap', category: 'Piping' },
  expansionJoint: { label: 'Expansion Joint', category: 'Piping' },
  // Miscellaneous
  ruptureDisc: { label: 'Rupture Disc', category: 'Miscellaneous' },
  flameArrestor: { label: 'Flame Arrestor', category: 'Miscellaneous' },
  strainer: { label: 'Strainer', category: 'Miscellaneous' },
  sightGlass: { label: 'Sight Glass', category: 'Miscellaneous' },
  staticMixer: { label: 'Static Mixer', category: 'Miscellaneous' },
  sprayNozzle: { label: 'Spray Nozzle', category: 'Miscellaneous' },
  ejector: { label: 'Ejector/Eductor', category: 'Miscellaneous' },
  // Hydrogen & Fuel Cell
  fuelCell: { label: 'Fuel Cell Stack', category: 'Hydrogen & Fuel Cell' },
  electrolyzer: { label: 'Electrolyzer', category: 'Hydrogen & Fuel Cell' },
  steamReformer: { label: 'Steam Methane Reformer', category: 'Hydrogen & Fuel Cell' },
  hydrogenTank: { label: 'Hydrogen Storage Tank', category: 'Hydrogen & Fuel Cell' },
  fuelDispenser: { label: 'H₂ Fuel Dispenser', category: 'Hydrogen & Fuel Cell' },
  // Gasification & Biomass
  gasifier: { label: 'Gasifier', category: 'Gasification & Biomass' },
  syngasCleanup: { label: 'Syngas Cleanup', category: 'Gasification & Biomass' },
  hopper: { label: 'Hopper/Feeder', category: 'Gasification & Biomass' },
  // Heating & Combustion
  boiler: { label: 'Boiler', category: 'Heating & Combustion' },
  furnace: { label: 'Industrial Furnace', category: 'Heating & Combustion' },
  burner: { label: 'Burner', category: 'Heating & Combustion' },
  coil: { label: 'Heating/Cooling Coil', category: 'Heating & Combustion' },
  waterHeater: { label: 'Water Heater', category: 'Heating & Combustion' },
  // Power Generation
  chpUnit: { label: 'CHP Unit', category: 'Power Generation' },
  turbine: { label: 'Gas/Steam Turbine', category: 'Power Generation' },
  generator: { label: 'Electric Generator', category: 'Power Generation' },
  // Off-Page Connectors
  offPageRight: { label: 'Off-Page → (to right)', category: 'Off-Page Connectors' },
  offPageLeft: { label: 'Off-Page ← (from left)', category: 'Off-Page Connectors' },
  offPageTo: { label: 'Off-Page ↓ (to page)', category: 'Off-Page Connectors' },
  offPageFrom: { label: 'Off-Page ↑ (from page)', category: 'Off-Page Connectors' },
  flowArrowRight: { label: 'Flow Arrow →', category: 'Off-Page Connectors' },
  flowArrowLeft: { label: 'Flow Arrow ←', category: 'Off-Page Connectors' },
  flowArrowDown: { label: 'Flow Arrow ↓', category: 'Off-Page Connectors' },
  flowArrowUp: { label: 'Flow Arrow ↑', category: 'Off-Page Connectors' },
  // Additional Equipment
  drum: { label: 'Drum/Accumulator', category: 'Vessels' },
  agitator: { label: 'Agitator/Impeller', category: 'Equipment' },
  vfd: { label: 'VFD (Variable Frequency Drive)', category: 'Electrical' },
  orificePlate: { label: 'Orifice Plate', category: 'Instruments' },
  diaphragmValve: { label: 'Diaphragm Valve', category: 'Valves' },
  plugValve: { label: 'Plug Valve', category: 'Valves' },
  pressureRegulator: { label: 'Pressure Regulator', category: 'Valves' },
  centrifuge: { label: 'Centrifuge', category: 'Equipment' },
  evaporator: { label: 'Evaporator', category: 'Heat Exchangers' },
  scrubber: { label: 'Scrubber', category: 'Vessels' },
  absorber: { label: 'Absorber Tower', category: 'Vessels' },
  diaphragmPump: { label: 'Diaphragm Pump', category: 'Equipment' },
  gearPump: { label: 'Gear Pump', category: 'Equipment' },
  axialFan: { label: 'Axial Fan', category: 'Equipment' },
  loadCell: { label: 'Load Cell/Scale', category: 'Instruments' },
  vibrationSensor: { label: 'Vibration Sensor (VT)', category: 'Instruments' },
  spectacleBlind: { label: 'Spectacle Blind', category: 'Piping' },
  pipeCross: { label: 'Pipe Cross', category: 'Piping' },
  pipeCap: { label: 'Pipe Cap/Plug', category: 'Piping' },
  powerSupply: { label: 'Power Supply', category: 'Electrical' },
  circuitBreaker: { label: 'Circuit Breaker', category: 'Electrical' },
  transformer: { label: 'Transformer', category: 'Electrical' },
  conveyor: { label: 'Conveyor', category: 'Equipment' },
  dryer: { label: 'Dryer', category: 'Equipment' },
}

// Get symbols by category
export function getSymbolsByCategory(): Record<string, ScadaSymbolType[]> {
  const result: Record<string, ScadaSymbolType[]> = {}
  for (const [key, info] of Object.entries(SYMBOL_INFO)) {
    if (!result[info.category]) {
      result[info.category] = []
    }
    result[info.category]!.push(key as ScadaSymbolType)
  }
  return result
}

// =============================================================================
// CONNECTION PORTS - Defines pipe connection points for each symbol
// =============================================================================
// Ports are defined as relative positions (0-1) within the symbol's bounding box
// x: 0 = left, 1 = right
// y: 0 = top, 1 = bottom

export interface SymbolPort {
  id: string           // Unique port identifier
  x: number           // Relative X position (0-1)
  y: number           // Relative Y position (0-1)
  direction: 'left' | 'right' | 'top' | 'bottom'  // Preferred pipe direction
  label?: string      // Optional label for the port
}

export const SYMBOL_PORTS: Record<ScadaSymbolType, SymbolPort[]> = {
  // Valves - typically have left/right flow ports
  solenoidValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  controlValve: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  manualValve: [
    { id: 'inlet', x: 0, y: 0.55, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.55, direction: 'right', label: 'Out' },
  ],
  checkValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  ballValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  butterflyValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  reliefValve: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom', label: 'In' },
    { id: 'vent', x: 0.5, y: 0, direction: 'top', label: 'Vent' },
  ],
  threeWayValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet1', x: 1, y: 0.5, direction: 'right', label: 'Out1' },
    { id: 'outlet2', x: 0.5, y: 1, direction: 'bottom', label: 'Out2' },
  ],
  gateValve: [
    { id: 'inlet', x: 0, y: 0.55, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.55, direction: 'right', label: 'Out' },
  ],
  needleValve: [
    { id: 'inlet', x: 0, y: 0.55, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.55, direction: 'right', label: 'Out' },
  ],

  // Instruments - typically have one process connection
  pressureTransducer: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  temperatureElement: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  flowMeter: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  levelTransmitter: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  flowSwitch: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  pressureSwitch: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  thermowell: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  analyzer: [
    { id: 'inlet', x: 0.28, y: 1, direction: 'bottom', label: 'In' },
    { id: 'outlet', x: 0.72, y: 1, direction: 'bottom', label: 'Out' },
  ],
  phSensor: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  conductivitySensor: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  pressureGauge: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  temperatureIndicator: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],

  // Equipment - pumps, compressors, etc.
  pump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 0.58, y: 0, direction: 'top', label: 'Discharge' },
  ],
  pdPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  compressor: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  blower: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  motor: [
    { id: 'shaft', x: 1, y: 0.5, direction: 'right', label: 'Shaft' },
  ],
  mixer: [
    { id: 'shaft', x: 0.5, y: 0, direction: 'top', label: 'Motor' },
  ],
  filter: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'In' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Out' },
  ],
  heater: [
    { id: 'inlet', x: 0.3, y: 1, direction: 'bottom', label: 'In' },
    { id: 'outlet', x: 0.7, y: 1, direction: 'bottom', label: 'Out' },
  ],
  cooler: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],

  // Heat Exchangers
  heatExchanger: [
    { id: 'shell_in', x: 0, y: 0.5, direction: 'left', label: 'Shell In' },
    { id: 'shell_out', x: 1, y: 0.5, direction: 'right', label: 'Shell Out' },
    { id: 'tube_in', x: 0.25, y: 0, direction: 'top', label: 'Tube In' },
    { id: 'tube_out', x: 0.75, y: 1, direction: 'bottom', label: 'Tube Out' },
  ],
  plateHeatExchanger: [
    { id: 'hot_in', x: 0, y: 0.2, direction: 'left', label: 'Hot In' },
    { id: 'cold_out', x: 1, y: 0.85, direction: 'right', label: 'Cold Out' },
  ],
  condenser: [
    { id: 'vapor_in', x: 0.5, y: 0, direction: 'top', label: 'Vapor In' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
    { id: 'coolant_in', x: 0, y: 0.5, direction: 'left', label: 'Coolant In' },
    { id: 'coolant_out', x: 1, y: 0.5, direction: 'right', label: 'Coolant Out' },
  ],
  airCooler: [
    { id: 'inlet', x: 0, y: 0.75, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.75, direction: 'right', label: 'Out' },
  ],

  // Vessels
  tank: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
    { id: 'side', x: 0, y: 0.5, direction: 'left', label: 'Side' },
  ],
  horizontalTank: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Outlet' },
    { id: 'top', x: 0.5, y: 0, direction: 'top', label: 'Top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom', label: 'Bottom' },
  ],
  reactor: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'product', x: 0.5, y: 1, direction: 'bottom', label: 'Product' },
    { id: 'jacket_in', x: 0, y: 0.3, direction: 'left', label: 'Jacket In' },
    { id: 'jacket_out', x: 0, y: 0.7, direction: 'left', label: 'Jacket Out' },
  ],
  column: [
    { id: 'feed', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'overhead', x: 0.5, y: 0, direction: 'top', label: 'Overhead' },
    { id: 'bottoms', x: 0.5, y: 1, direction: 'bottom', label: 'Bottoms' },
    { id: 'reflux', x: 1, y: 0.15, direction: 'right', label: 'Reflux' },
    { id: 'reboiler', x: 1, y: 0.85, direction: 'right', label: 'Reboiler' },
  ],
  cyclone: [
    { id: 'inlet', x: 0, y: 0.2, direction: 'left', label: 'Inlet' },
    { id: 'gas_out', x: 0.5, y: 0, direction: 'top', label: 'Gas Out' },
    { id: 'solids_out', x: 0.5, y: 1, direction: 'bottom', label: 'Solids' },
  ],
  separator: [
    { id: 'inlet', x: 0, y: 0.48, direction: 'left', label: 'Inlet' },
    { id: 'vapor_out', x: 1, y: 0.15, direction: 'right', label: 'Vapor' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid' },
  ],
  sphere: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
  ],

  // Piping components
  pipeHorizontal: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  pipeVertical: [
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  elbow90: [
    { id: 'vertical', x: 0.3, y: 0, direction: 'top' },
    { id: 'horizontal', x: 1, y: 0.7, direction: 'right' },
  ],
  pipeTee: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
    { id: 'branch', x: 0.5, y: 0, direction: 'top' },
  ],
  reducer: [
    { id: 'large', x: 0, y: 0.5, direction: 'left' },
    { id: 'small', x: 1, y: 0.5, direction: 'right' },
  ],
  flange: [
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  blindFlange: [
    { id: 'connection', x: 0.5, y: 1, direction: 'bottom' },
  ],
  expansionJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],

  // Miscellaneous
  ruptureDisc: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
    { id: 'vent', x: 0.5, y: 0, direction: 'top', label: 'Vent' },
  ],
  flameArrestor: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right' },
  ],
  strainer: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right' },
  ],
  sightGlass: [
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  staticMixer: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right' },
  ],
  sprayNozzle: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
  ],
  ejector: [
    { id: 'motive', x: 0, y: 0.5, direction: 'left', label: 'Motive' },
    { id: 'suction', x: 0.48, y: 0, direction: 'top', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],

  // Hydrogen & Fuel Cell
  fuelCell: [
    { id: 'h2_in', x: 0, y: 0.35, direction: 'left', label: 'H2 In' },
    { id: 'air_in', x: 0, y: 0.65, direction: 'left', label: 'Air In' },
    { id: 'exhaust1', x: 1, y: 0.35, direction: 'right', label: 'Exhaust' },
    { id: 'exhaust2', x: 1, y: 0.65, direction: 'right', label: 'H2O Out' },
  ],
  electrolyzer: [
    { id: 'water_in', x: 0.5, y: 1, direction: 'bottom', label: 'H2O In' },
    { id: 'h2_out', x: 0.35, y: 0, direction: 'top', label: 'H2 Out' },
    { id: 'o2_out', x: 0.65, y: 0, direction: 'top', label: 'O2 Out' },
  ],
  steamReformer: [
    { id: 'ch4_in', x: 0, y: 0.25, direction: 'left', label: 'CH4 In' },
    { id: 'steam_in', x: 0, y: 0.38, direction: 'left', label: 'Steam In' },
    { id: 'h2_out', x: 1, y: 0.25, direction: 'right', label: 'H2 Out' },
    { id: 'flue', x: 0.5, y: 1, direction: 'bottom', label: 'Flue' },
  ],
  hydrogenTank: [
    { id: 'connection', x: 0.5, y: 0, direction: 'top', label: 'H2' },
  ],
  fuelDispenser: [
    { id: 'supply', x: 0.5, y: 1, direction: 'bottom', label: 'Supply' },
    { id: 'hose', x: 1, y: 0.85, direction: 'right', label: 'Hose' },
  ],

  // Gasification & Biomass
  gasifier: [
    { id: 'feed', x: 0, y: 0.35, direction: 'left', label: 'Feed' },
    { id: 'air', x: 1, y: 0.32, direction: 'right', label: 'Air/O2' },
    { id: 'syngas', x: 0.5, y: 0, direction: 'top', label: 'Syngas' },
    { id: 'ash', x: 0.5, y: 1, direction: 'bottom', label: 'Ash' },
  ],
  syngasCleanup: [
    { id: 'gas_in', x: 1, y: 0.25, direction: 'right', label: 'Dirty Gas' },
    { id: 'gas_out', x: 0, y: 0.8, direction: 'left', label: 'Clean Gas' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  hopper: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],

  // Heating & Combustion
  boiler: [
    { id: 'feedwater', x: 0, y: 0.5, direction: 'left', label: 'Feedwater' },
    { id: 'steam', x: 0.5, y: 0, direction: 'top', label: 'Steam' },
    { id: 'blowdown', x: 1, y: 0.5, direction: 'right', label: 'Blowdown' },
  ],
  furnace: [
    { id: 'fuel', x: 0, y: 0.45, direction: 'left', label: 'Fuel' },
    { id: 'air', x: 0.5, y: 0, direction: 'top', label: 'Air' },
    { id: 'exhaust', x: 1, y: 0.45, direction: 'right', label: 'Exhaust' },
  ],
  burner: [
    { id: 'fuel', x: 0, y: 0.56, direction: 'left', label: 'Fuel' },
    { id: 'air', x: 0.5, y: 0, direction: 'top', label: 'Air' },
  ],
  coil: [
    { id: 'inlet', x: 0, y: 0.35, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.75, direction: 'right', label: 'Outlet' },
  ],
  waterHeater: [
    { id: 'cold_in', x: 0.3, y: 0, direction: 'top', label: 'Cold In' },
    { id: 'hot_out', x: 0.68, y: 0, direction: 'top', label: 'Hot Out' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],

  // Power Generation
  chpUnit: [
    { id: 'fuel', x: 0, y: 0.5, direction: 'left', label: 'Fuel' },
    { id: 'exhaust', x: 0.28, y: 0, direction: 'top', label: 'Exhaust' },
    { id: 'heat_supply', x: 1, y: 0.35, direction: 'right', label: 'Heat Supply' },
    { id: 'heat_return', x: 1, y: 0.68, direction: 'right', label: 'Heat Return' },
  ],
  turbine: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Steam/Gas In' },
    { id: 'exhaust', x: 0.75, y: 0.5, direction: 'right', label: 'Exhaust' },
    { id: 'shaft', x: 1, y: 0.5, direction: 'right', label: 'Shaft' },
  ],
  generator: [
    { id: 'shaft', x: 0, y: 0.5, direction: 'left', label: 'Shaft' },
    { id: 'power_pos', x: 1, y: 0.35, direction: 'right', label: '+' },
    { id: 'power_neg', x: 1, y: 0.7, direction: 'right', label: '-' },
  ],

  // Off-Page Connectors
  offPageRight: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left' },
  ],
  offPageLeft: [
    { id: 'outlet', x: 1, y: 0.5, direction: 'right' },
  ],
  offPageTo: [
    { id: 'connection', x: 0.5, y: 0, direction: 'top' },
  ],
  offPageFrom: [
    { id: 'connection', x: 0.5, y: 1, direction: 'bottom' },
  ],
  flowArrowRight: [
    { id: 'tail', x: 0, y: 0.5, direction: 'left' },
    { id: 'head', x: 1, y: 0.5, direction: 'right' },
  ],
  flowArrowLeft: [
    { id: 'head', x: 0, y: 0.5, direction: 'left' },
    { id: 'tail', x: 1, y: 0.5, direction: 'right' },
  ],
  flowArrowDown: [
    { id: 'tail', x: 0.5, y: 0, direction: 'top' },
    { id: 'head', x: 0.5, y: 1, direction: 'bottom' },
  ],
  flowArrowUp: [
    { id: 'head', x: 0.5, y: 0, direction: 'top' },
    { id: 'tail', x: 0.5, y: 1, direction: 'bottom' },
  ],

  // Additional Equipment Ports
  drum: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Outlet' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  agitator: [
    { id: 'shaft', x: 0.5, y: 0, direction: 'top', label: 'Motor' },
  ],
  vfd: [
    { id: 'power_in', x: 0.5, y: 0, direction: 'top', label: 'Power In' },
    { id: 'motor_out', x: 0.5, y: 1, direction: 'bottom', label: 'Motor Out' },
  ],
  orificePlate: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  diaphragmValve: [
    { id: 'inlet', x: 0, y: 0.65, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.65, direction: 'right', label: 'Out' },
  ],
  plugValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  pressureRegulator: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  centrifuge: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'light', x: 0, y: 0.58, direction: 'left', label: 'Light' },
    { id: 'heavy', x: 1, y: 0.58, direction: 'right', label: 'Heavy' },
  ],
  evaporator: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'concentrate', x: 0.5, y: 1, direction: 'bottom', label: 'Concentrate' },
    { id: 'steam_in', x: 0, y: 0.4, direction: 'left', label: 'Steam In' },
    { id: 'condensate', x: 1, y: 0.4, direction: 'right', label: 'Condensate' },
  ],
  scrubber: [
    { id: 'gas_in', x: 0, y: 0.78, direction: 'left', label: 'Gas In' },
    { id: 'gas_out', x: 1, y: 0.4, direction: 'right', label: 'Gas Out' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
  ],
  absorber: [
    { id: 'gas_in', x: 0, y: 0.55, direction: 'left', label: 'Gas In' },
    { id: 'liquid_in', x: 1, y: 0.3, direction: 'right', label: 'Liquid In' },
    { id: 'gas_out', x: 0.5, y: 0, direction: 'top', label: 'Gas Out' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
  ],
  diaphragmPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  gearPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  axialFan: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Outlet' },
  ],
  loadCell: [
    { id: 'process', x: 0.5, y: 0, direction: 'top', label: 'Load' },
  ],
  vibrationSensor: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Mount' },
  ],
  spectacleBlind: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  pipeCross: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  pipeCap: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom' },
  ],
  powerSupply: [
    { id: 'output1', x: 0.2, y: 1, direction: 'bottom' },
    { id: 'output2', x: 0.5, y: 1, direction: 'bottom' },
    { id: 'output3', x: 0.8, y: 1, direction: 'bottom' },
  ],
  circuitBreaker: [
    { id: 'line', x: 0.5, y: 0, direction: 'top', label: 'Line' },
    { id: 'load', x: 0.5, y: 1, direction: 'bottom', label: 'Load' },
  ],
  transformer: [
    { id: 'primary', x: 0, y: 0.5, direction: 'left', label: 'Primary' },
    { id: 'secondary', x: 1, y: 0.5, direction: 'right', label: 'Secondary' },
  ],
  conveyor: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Discharge' },
  ],
  dryer: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Wet Feed' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Dry Product' },
    { id: 'air', x: 0, y: 0.5, direction: 'left', label: 'Hot Air' },
  ],
}

// Get port position in widget coordinates (accounting for widget size and rotation)
export function getPortPosition(
  symbolType: ScadaSymbolType,
  portId: string,
  widgetX: number,
  widgetY: number,
  widgetW: number,
  widgetH: number,
  rotation: 0 | 90 | 180 | 270 = 0
): { x: number; y: number; direction: 'left' | 'right' | 'top' | 'bottom' } | null {
  const ports = SYMBOL_PORTS[symbolType]
  const port = ports?.find(p => p.id === portId)
  if (!port) return null

  let relX = port.x
  let relY = port.y
  let direction = port.direction

  // Apply rotation transformation
  if (rotation === 90) {
    const temp = relX
    relX = 1 - relY
    relY = temp
    direction = rotateDirection(direction, 90)
  } else if (rotation === 180) {
    relX = 1 - relX
    relY = 1 - relY
    direction = rotateDirection(direction, 180)
  } else if (rotation === 270) {
    const temp = relX
    relX = relY
    relY = 1 - temp
    direction = rotateDirection(direction, 270)
  }

  return {
    x: widgetX + relX * widgetW,
    y: widgetY + relY * widgetH,
    direction
  }
}

function rotateDirection(
  dir: 'left' | 'right' | 'top' | 'bottom',
  degrees: 90 | 180 | 270
): 'left' | 'right' | 'top' | 'bottom' {
  const order: ('top' | 'right' | 'bottom' | 'left')[] = ['top', 'right', 'bottom', 'left']
  const idx = order.indexOf(dir)
  const steps = degrees / 90
  return order[(idx + steps) % 4] as 'left' | 'right' | 'top' | 'bottom'
}
