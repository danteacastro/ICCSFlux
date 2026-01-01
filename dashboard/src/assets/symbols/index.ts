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
  // Off-Page Connectors
  offPageRight: OffPageConnectorRight,
  offPageLeft: OffPageConnectorLeft,
  offPageTo: OffPageConnectorTo,
  offPageFrom: OffPageConnectorFrom,
  flowArrowRight: FlowArrowRight,
  flowArrowLeft: FlowArrowLeft,
  flowArrowDown: FlowArrowDown,
  flowArrowUp: FlowArrowUp,
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
  // Off-Page Connectors
  offPageRight: { label: 'Off-Page → (to right)', category: 'Off-Page Connectors' },
  offPageLeft: { label: 'Off-Page ← (from left)', category: 'Off-Page Connectors' },
  offPageTo: { label: 'Off-Page ↓ (to page)', category: 'Off-Page Connectors' },
  offPageFrom: { label: 'Off-Page ↑ (from page)', category: 'Off-Page Connectors' },
  flowArrowRight: { label: 'Flow Arrow →', category: 'Off-Page Connectors' },
  flowArrowLeft: { label: 'Flow Arrow ←', category: 'Off-Page Connectors' },
  flowArrowDown: { label: 'Flow Arrow ↓', category: 'Off-Page Connectors' },
  flowArrowUp: { label: 'Flow Arrow ↑', category: 'Off-Page Connectors' },
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
