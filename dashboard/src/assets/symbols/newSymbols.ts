// =============================================================================
// Additional P&ID Symbols - ISA 5.1 / ISO 10628 Standard
// =============================================================================
// Extends the base symbol library with comprehensive industrial P&ID symbols.
// All symbols use currentColor for dynamic theming and scale to any size.

// =============================================================================
// VALVES - Additional Types
// =============================================================================

// Globe Valve (ISA: bowtie body with horizontal bar)
export const GlobeValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 12 L30 20 L15 28 Z" fill="currentColor"/>
  <path d="M45 12 L30 20 L45 28 Z" fill="currentColor"/>
  <line x1="24" y1="20" x2="36" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Angle Valve (90° body)
export const AngleValve = `
<svg viewBox="0 0 45 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 12 L22 22 L10 32 Z" fill="currentColor"/>
  <path d="M22 10 L22 22 L32 10 Z" fill="currentColor"/>
  <line x1="0" y1="22" x2="10" y2="22" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="10" x2="22" y2="0" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Stop-Check Valve (globe + check arrow)
export const StopCheckValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 15 L30 23 L15 31 Z" fill="currentColor"/>
  <path d="M45 15 L30 23 L45 31 Z" fill="currentColor"/>
  <line x1="24" y1="23" x2="36" y2="23" stroke="currentColor" stroke-width="2"/>
  <path d="M27 17 L33 12 L33 17" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <line x1="0" y1="23" x2="15" y2="23" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="23" x2="60" y2="23" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pressure Reducing Valve (bowtie with pilot diaphragm)
export const ReducingValve = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="12" stroke="currentColor" stroke-width="2"/>
  <path d="M22 12 L30 4 L38 12 Z" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Motor-Operated Valve (bowtie with filled motor actuator)
export const PoweredValve = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="12" stroke="currentColor" stroke-width="2"/>
  <rect x="22" y="2" width="16" height="10" rx="1" fill="currentColor"/>
  <text x="30" y="10" text-anchor="middle" font-size="7" font-weight="bold" fill="white" stroke="none">M</text>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Float-Operated Valve
export const FloatValve = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="12" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="12" x2="42" y2="6" stroke="currentColor" stroke-width="1.5"/>
  <circle cx="42" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// 3-Way Plug Valve
export const ThreeWayPlugValve = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <path d="M22 45 L30 30 L38 45 Z" fill="currentColor"/>
  <rect x="26" y="16" width="8" height="10" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="45" x2="30" y2="60" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Wedge Gate Valve (gate with wedge indicator)
export const WedgeGateValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="15" width="30" height="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M26 18 L30 32 L34 18" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="15" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="5" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Flanged Valve (bowtie with flange symbols)
export const FlangedValve = `
<svg viewBox="0 0 70 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="12" y1="10" x2="12" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="14" y1="10" x2="14" y2="30" stroke="currentColor" stroke-width="2"/>
  <path d="M20 12 L35 20 L20 28 Z" fill="currentColor"/>
  <path d="M50 12 L35 20 L50 28 Z" fill="currentColor"/>
  <line x1="56" y1="10" x2="56" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="58" y1="10" x2="58" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="12" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="58" y1="20" x2="70" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Relief Valve - Angle Body
export const ReliefAngleValve = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 35 L25 25 L35 35 Z" fill="currentColor"/>
  <path d="M15 15 L25 25 L25 15 Z" fill="currentColor"/>
  <line x1="25" y1="15" x2="25" y2="5" stroke="currentColor" stroke-width="2"/>
  <path d="M20 5 L25 10 L30 5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="35" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Screw-Down Valve
export const ScrewDownValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 17 L30 25 L15 33 Z" fill="currentColor"/>
  <path d="M45 17 L30 25 L45 33 Z" fill="currentColor"/>
  <line x1="30" y1="17" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <line x1="27" y1="2" x2="33" y2="2" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Mixing Valve (3-way with mixing arrows)
export const MixingValve = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <path d="M22 45 L30 30 L38 45 Z" fill="currentColor"/>
  <circle cx="30" cy="30" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="45" x2="30" y2="60" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Character Port Valve
export const CharacterPortValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 12 L30 20 L15 28 Z" fill="currentColor"/>
  <path d="M45 12 L30 20 L45 28 Z" fill="currentColor"/>
  <text x="30" y="10" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">V</text>
  <line x1="0" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// PUMPS - Additional Types
// =============================================================================

// In-Line Pump
export const InlinePump = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M22 14 L38 20 L22 26" stroke="currentColor" stroke-width="2" fill="none" stroke-linejoin="round"/>
  <line x1="0" y1="20" x2="16" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="44" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Reciprocating Pump (rectangle with piston)
export const ReciprocatingPump = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="8" width="28" height="24" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="26" y1="8" x2="26" y2="32" stroke="currentColor" stroke-width="2"/>
  <path d="M18 16 L24 20 L18 24" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="12" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Rotary Pump (circle with two lobe arcs)
export const RotaryPump = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 13 A8 8 0 0 1 32 13" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M32 27 A8 8 0 0 1 18 27" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Positive Displacement Pump (circle with + symbol)
export const PositiveDisplacementPump = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="13" x2="25" y2="27" stroke="currentColor" stroke-width="2"/>
  <line x1="18" y1="20" x2="32" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Proportioning/Metering Pump
export const ProportioningPump = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="8" width="28" height="24" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="26" y1="8" x2="26" y2="32" stroke="currentColor" stroke-width="2" stroke-dasharray="3 2"/>
  <path d="M18 16 L24 20 L18 24" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="33" y="24" text-anchor="middle" font-size="7" fill="currentColor" stroke="none">P</text>
  <line x1="0" y1="20" x2="12" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Centrifugal Fan (scroll/volute housing)
export const CentrifugalFan = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M25 5 A20 20 0 1 1 5 25 L5 5 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="25" r="6" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="5" x2="5" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="45" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Rotary Compressor (circle with rotor)
export const RotaryCompressor = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M11 12 L25 20 L11 28 Z" fill="currentColor"/>
  <path d="M39 12 L25 20 L39 28 Z" fill="none" stroke="currentColor" stroke-width="2"/>
  <circle cx="25" cy="20" r="4" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Ejector/Injector (converging nozzle)
export const EjectorInjector = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 8 L30 18 L10 28" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M30 14 L50 8 L50 32 L30 26 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="0" x2="22" y2="14" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="18" x2="10" y2="18" stroke="currentColor" stroke-width="2"/>
  <line x1="50" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Motor-Driven Turbine
export const MotorDrivenTurbine = `
<svg viewBox="0 0 70 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 10 L10 40 L45 30 L45 20 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="48" y="18" width="18" height="14" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="57" y="28" text-anchor="middle" font-size="7" fill="currentColor" stroke="none">M</text>
  <line x1="0" y1="25" x2="10" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="48" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Compressor/Turbine combo
export const CompressorTurbine = `
<svg viewBox="0 0 70 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 8 L5 32 L30 24 L30 16 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M35 16 L35 24 L60 32 L60 8 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="20" x2="35" y2="20" stroke="currentColor" stroke-width="3"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="60" y1="20" x2="70" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Spray Nozzle (variant)
export const SprayHead = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="20" y1="40" x2="20" y2="22" stroke="currentColor" stroke-width="2"/>
  <path d="M8 10 L20 22 L32 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="5" x2="8" y2="10" stroke="currentColor" stroke-width="1.5"/>
  <line x1="14" y1="3" x2="14" y2="10" stroke="currentColor" stroke-width="1.5"/>
  <line x1="20" y1="2" x2="20" y2="10" stroke="currentColor" stroke-width="1.5"/>
  <line x1="26" y1="3" x2="26" y2="10" stroke="currentColor" stroke-width="1.5"/>
  <line x1="32" y1="5" x2="32" y2="10" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// =============================================================================
// HEAT EXCHANGERS - Additional Types
// =============================================================================

// Shell and Tube HX (explicit ISA standard)
export const ShellAndTubeHX = `
<svg viewBox="0 0 80 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="55" height="34" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="12" cy="25" rx="4" ry="15" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <ellipse cx="59" cy="25" rx="4" ry="15" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="16" y1="15" x2="55" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="16" y1="25" x2="55" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="16" y1="35" x2="55" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="63" y1="25" x2="80" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="0" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="42" x2="45" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Kettle Reboiler
export const KettleReboiler = `
<svg viewBox="0 0 80 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 10 L55 10 Q70 10 70 25 Q70 40 55 40 L10 40 Q5 40 5 35 L5 15 Q5 10 10 10 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="18" x2="50" y2="18" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="25" x2="50" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="32" x2="50" y2="32" stroke="currentColor" stroke-width="1"/>
  <line x1="60" y1="10" x2="60" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="25" x2="5" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="70" y1="25" x2="80" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Fired Heater (box with flame symbol)
export const FiredHeater = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="44" height="44" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M25 45 Q25 35 30 30 Q35 35 35 45" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M28 42 Q28 38 30 35 Q32 38 32 42" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.3"/>
  <line x1="15" y1="15" x2="45" y2="15" stroke="currentColor" stroke-width="1.5"/>
  <line x1="15" y1="20" x2="45" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="17" x2="8" y2="17" stroke="currentColor" stroke-width="2"/>
  <line x1="52" y1="17" x2="60" y2="17" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Cooling Tower
export const CoolingTower = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 55 Q5 30 15 20 Q20 15 25 12 Q30 15 35 20 Q45 30 45 55 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 35 Q20 32 25 35 Q30 38 35 35" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M15 42 Q20 39 25 42 Q30 45 35 42" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="0" y1="48" x2="5" y2="48" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="48" x2="50" y2="48" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="12" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Double Pipe Heat Exchanger
export const DoublePipeHX = `
<svg viewBox="0 0 80 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="60" height="20" rx="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="20" x2="65" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="15" x2="10" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="70" y1="15" x2="80" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="25" x2="10" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="70" y1="25" x2="80" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Finned Tube Element
export const FinnedTubeHX = `
<svg viewBox="0 0 70 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="5" y1="15" x2="65" y2="15" stroke="currentColor" stroke-width="3"/>
  <line x1="12" y1="5" x2="12" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="5" x2="20" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="28" y1="5" x2="28" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="36" y1="5" x2="36" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="44" y1="5" x2="44" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="52" y1="5" x2="52" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="60" y1="5" x2="60" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="15" x2="5" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="65" y1="15" x2="70" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Autoclave (pressure vessel)
export const AutoclaveHX = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="44" height="34" rx="4" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="14" x2="52" y2="14" stroke="currentColor" stroke-width="1.5"/>
  <circle cx="14" cy="11" r="2" fill="currentColor"/>
  <circle cx="46" cy="11" r="2" fill="currentColor"/>
  <line x1="0" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="52" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Evaporative Condenser
export const EvaporativeCondenser = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="40" height="40" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="12" y1="25" x2="38" y2="25" stroke="currentColor" stroke-width="1.5"/>
  <line x1="12" y1="32" x2="38" y2="32" stroke="currentColor" stroke-width="1.5"/>
  <path d="M18 18 Q20 15 22 18 Q24 21 26 18 Q28 15 30 18 Q32 21 34 18" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="25" y1="0" x2="25" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="50" x2="25" y2="60" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="28" x2="5" y2="28" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="28" x2="50" y2="28" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Oil Burner
export const OilBurner = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="30" r="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M22 35 Q22 25 25 20 Q28 25 28 35" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="30" x2="10" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="30" x2="50" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="15" x2="25" y2="5" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Oil Separator
export const OilSeparator = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="34" height="44" rx="4" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="28" x2="42" y2="28" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 2"/>
  <text x="25" y="22" text-anchor="middle" font-size="7" fill="currentColor" stroke="none">OIL</text>
  <text x="25" y="42" text-anchor="middle" font-size="7" fill="currentColor" stroke="none">H₂O</text>
  <line x1="0" y1="20" x2="8" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="40" x2="50" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Extractor Hood
export const ExtractorHood = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 35 L5 15 L20 5 L30 5 L45 15 L45 35" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="35" x2="45" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="5" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Refrigerator
export const Refrigerator = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="34" height="34" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 18 L32 18 L32 25 L18 25 Z" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="25" y="37" text-anchor="middle" font-size="8" fill="currentColor" stroke="none">*</text>
  <line x1="0" y1="20" x2="8" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="30" x2="8" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="30" x2="50" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// VESSELS - Additional Types
// =============================================================================

// Open Tank (no lid)
export const OpenTank = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 5 L8 52 Q8 55 11 55 L39 55 Q42 55 42 52 L42 5" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="55" x2="25" y2="60" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="30" x2="8" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Closed Tank (with dished head)
export const ClosedTank = `
<svg viewBox="0 0 50 65" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 12 Q8 5 25 5 Q42 5 42 12 L42 52 Q42 58 25 58 Q8 58 8 52 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="5" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="58" x2="25" y2="65" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="30" x2="8" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Covered Tank (floating roof)
export const CoveredTank = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="34" height="44" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 8 L25 3 L42 8" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="3" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="52" x2="25" y2="60" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="30" x2="8" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Gas Holder (dome top)
export const GasHolder = `
<svg viewBox="0 0 50 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 25 Q8 5 25 5 Q42 5 42 25 L42 52 L8 52 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="52" x2="5" y2="58" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="52" x2="45" y2="58" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="52" x2="25" y2="60" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Gas Cylinder (tall narrow with dome)
export const GasCylinder = `
<svg viewBox="0 0 30 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 12 Q8 5 15 5 Q22 5 22 12 L22 50 Q22 55 15 55 Q8 55 8 50 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="12" y="2" width="6" height="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="15" y1="0" x2="15" y2="2" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Barrel/Drum
export const Barrel = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 5 Q5 5 5 10 L5 40 Q5 45 10 45 L30 45 Q35 45 35 40 L35 10 Q35 5 30 5 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M5 15 Q20 18 35 15" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M5 35 Q20 32 35 35" stroke="currentColor" stroke-width="1" fill="none"/>
  <circle cx="20" cy="8" r="3" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Tray Column (column with internal trays)
export const TrayColumn = `
<svg viewBox="0 0 40 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 8 Q8 2 20 2 Q32 2 32 8 L32 92 Q32 98 20 98 Q8 98 8 92 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="25" x2="30" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="40" x2="30" y2="40" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="55" x2="30" y2="55" stroke="currentColor" stroke-width="1"/>
  <line x1="10" y1="70" x2="30" y2="70" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="2" x2="20" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="98" x2="20" y2="100" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="50" x2="8" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="32" y1="18" x2="40" y2="18" stroke="currentColor" stroke-width="2"/>
  <line x1="32" y1="82" x2="40" y2="82" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Clarifier (settling tank)
export const Clarifier = `
<svg viewBox="0 0 70 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 10 L5 35 L25 45 L45 45 L65 35 L65 10 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="10" x2="65" y2="10" stroke="currentColor" stroke-width="2"/>
  <path d="M30 10 L30 30" stroke="currentColor" stroke-width="1.5"/>
  <path d="M25 30 L30 35 L35 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="65" y1="20" x2="70" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="45" x2="35" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Reaction Vessel (jacketed with agitator)
export const ReactionVessel = `
<svg viewBox="0 0 60 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 10 L15 65 Q15 72 30 72 Q45 72 45 65 L45 10 Q45 5 30 5 Q15 5 15 10 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 18 L10 58 Q10 65 15 65" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M50 18 L50 58 Q50 65 45 65" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="0" x2="30" y2="35" stroke="currentColor" stroke-width="2"/>
  <path d="M24 35 L30 42 L36 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="25" x2="10" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="50" x2="10" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="72" x2="30" y2="80" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Vessel (generic)
export const Vessel = `
<svg viewBox="0 0 50 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 12 Q10 5 25 5 Q40 5 40 12 L40 58 Q40 65 25 65 Q10 65 10 58 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="5" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="65" x2="25" y2="70" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="35" x2="10" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="35" x2="50" y2="35" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Fluid Contacting column
export const FluidContacting = `
<svg viewBox="0 0 40 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 8 Q8 2 20 2 Q32 2 32 8 L32 72 Q32 78 20 78 Q8 78 8 72 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="15" cy="25" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="25" cy="30" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="18" cy="40" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="22" cy="50" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="14" cy="55" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="26" cy="60" r="3" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="40" x2="8" y2="40" stroke="currentColor" stroke-width="2"/>
  <line x1="32" y1="40" x2="40" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// INSTRUMENTS - Additional Types
// =============================================================================

// PLC Controller
export const PLCController = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="40" height="30" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor" stroke="none">PLC</text>
  <line x1="15" y1="35" x2="15" y2="40" stroke="currentColor" stroke-width="1.5"/>
  <line x1="25" y1="35" x2="25" y2="40" stroke="currentColor" stroke-width="1.5"/>
  <line x1="35" y1="35" x2="35" y2="40" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// DCS Computer
export const DCSComputer = `
<svg viewBox="0 0 50 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="40" height="25" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="18" y="30" width="14" height="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <rect x="12" y="34" width="26" height="3" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="25" y="21" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">DCS</text>
  <line x1="25" y1="37" x2="25" y2="45" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Rotameter (variable area flowmeter)
export const Rotameter = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 45 L5 5 L25 5 L22 45 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="15" cy="30" rx="5" ry="3" fill="currentColor" opacity="0.4"/>
  <line x1="15" y1="0" x2="15" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="45" x2="15" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Venturi Element
export const VenturiElement = `
<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 5 L25 12 L35 12 L55 5" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M5 25 L25 18 L35 18 L55 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="0" y1="15" x2="5" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="55" y1="15" x2="60" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="12" x2="30" y2="0" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// AND Logic Gate
export const ANDGate = `
<svg viewBox="0 0 40 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 3 L20 3 Q35 3 35 15 Q35 27 20 27 L5 27 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="0" y1="10" x2="5" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// OR Logic Gate
export const ORGate = `
<svg viewBox="0 0 40 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 3 Q15 15 5 27" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M5 3 L18 3 Q32 3 38 15 Q32 27 18 27 L5 27" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="0" y1="10" x2="8" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="8" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="38" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// NOT Logic Gate (inverter/buffer with bubble)
export const NOTGate = `
<svg viewBox="0 0 40 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 3 L30 15 L5 27 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="33" cy="15" r="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="15" x2="5" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="36" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Indicator/Recorder (circle with horizontal line)
export const IndicatorRecorder = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="4" y1="20" x2="36" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <text x="20" y="17" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">I</text>
  <text x="20" y="30" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">R</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Signal Converter (diamond/square rotated)
export const SignalConverter = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="6" y="6" width="22" height="22" rx="0" transform="rotate(45 17 17)" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="17" y="21" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">√</text>
  <line x1="0" y1="17" x2="5" y2="17" stroke="currentColor" stroke-width="2"/>
  <line x1="29" y1="17" x2="40" y2="17" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Operator Station
export const OperatorStation = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="8" width="40" height="24" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="8" x2="45" y2="32" stroke="currentColor" stroke-width="1.5"/>
  <text x="25" y="24" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor" stroke="none">HC</text>
  <line x1="25" y1="32" x2="25" y2="40" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Thermometer (glass)
export const Thermometer = `
<svg viewBox="0 0 25 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M9 8 L9 32 Q5 35 5 40 Q5 47 12.5 47 Q20 47 20 40 Q20 35 16 32 L16 8 Q16 4 12.5 4 Q9 4 9 8 Z" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="12.5" cy="40" r="4" fill="currentColor" opacity="0.4"/>
  <line x1="12.5" y1="36" x2="12.5" y2="12" stroke="currentColor" stroke-width="2" opacity="0.4"/>
  <line x1="16" y1="15" x2="19" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="16" y1="20" x2="19" y2="20" stroke="currentColor" stroke-width="1"/>
  <line x1="16" y1="25" x2="19" y2="25" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Level Meter
export const LevelMeter = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="5" width="14" height="40" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="10" y="25" width="10" height="18" fill="currentColor" opacity="0.2"/>
  <line x1="5" y1="15" x2="8" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="5" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="5" y1="35" x2="8" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="0" x2="15" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="45" x2="15" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Indicator Light
export const IndicatorLight = `
<svg viewBox="0 0 30 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="15" cy="15" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="8" y1="8" x2="22" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="22" y1="8" x2="8" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="15" y1="25" x2="15" y2="35" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Propeller/Turbine Meter
export const PropellerMeter = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M25 7 L28 15 L25 23 L22 15 Z" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="15" x2="13" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="37" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Vortex Sensor
export const VortexSensor = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="23" y="7" width="4" height="16" fill="currentColor" opacity="0.3"/>
  <path d="M28 10 Q32 13 28 15 Q32 17 28 20" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="0" y1="15" x2="13" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="37" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Generic Indicator (circle with letter)
export const GenericIndicator = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="25" text-anchor="middle" font-size="12" font-weight="bold" fill="currentColor" stroke="none">I</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// CRT Display
export const CRTDisplay = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="40" height="25" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="8" y="8" width="34" height="19" rx="1" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="20" y1="30" x2="20" y2="35" stroke="currentColor" stroke-width="1.5"/>
  <line x1="30" y1="30" x2="30" y2="35" stroke="currentColor" stroke-width="1.5"/>
  <line x1="12" y1="35" x2="38" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="35" x2="25" y2="40" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Correcting/Final Control Element
export const CorrectingElement = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="25" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor" stroke="none">FE</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Diamond (instrument modifier)
export const DiamondSymbol = `
<svg viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 2 L28 15 L15 28 L2 15 Z" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Flowmeter (generic, inline)
export const FlowmeterGeneric = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="19" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor" stroke="none">FI</text>
  <line x1="0" y1="15" x2="13" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="37" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pressure Gauges (dial gauge)
export const PressureGauges = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="25" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor" stroke="none">PI</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
  <path d="M12 12 L20 20" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// =============================================================================
// EQUIPMENT - General Additional Types
// =============================================================================

// Ball Mill
export const BallMill = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="30" cy="20" rx="24" ry="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="22" cy="24" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="30" cy="26" r="2.5" fill="currentColor" opacity="0.3"/>
  <circle cx="38" cy="23" r="3" fill="currentColor" opacity="0.3"/>
  <circle cx="26" cy="18" r="2" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="20" x2="6" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="54" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Jaw Crusher
export const JawCrusher = `
<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M12 8 L12 40 L28 40" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M36 8 L36 28 L28 40" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M14 12 L14 35" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2"/>
  <line x1="24" y1="0" x2="24" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="40" x2="20" y2="48" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Vibrating Screen
export const VibratingScreen = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 10 L55 10 L50 35 L10 35 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="18" x2="50" y2="18" stroke="currentColor" stroke-width="1" stroke-dasharray="2 2"/>
  <line x1="10" y1="26" x2="50" y2="26" stroke="currentColor" stroke-width="1" stroke-dasharray="2 2"/>
  <path d="M2 8 L5 10 L2 12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M58 8 L55 10 L58 12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="22" x2="7" y2="22" stroke="currentColor" stroke-width="2"/>
  <line x1="53" y1="22" x2="60" y2="22" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Screw Conveyor (auger)
export const ScrewConveyor = `
<svg viewBox="0 0 80 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="70" height="20" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 5 L15 25 M25 5 L25 25 M35 5 L35 25 M45 5 L45 25 M55 5 L55 25 M65 5 L65 25" stroke="currentColor" stroke-width="1" opacity="0.5"/>
  <line x1="10" y1="15" x2="70" y2="15" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="15" x2="5" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="75" y1="15" x2="80" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Bucket Elevator
export const BucketElevator = `
<svg viewBox="0 0 30 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="20" height="60" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M9 15 L15 15 L15 20 L9 20 Z" fill="currentColor" opacity="0.3"/>
  <path d="M9 28 L15 28 L15 33 L9 33 Z" fill="currentColor" opacity="0.3"/>
  <path d="M9 41 L15 41 L15 46 L9 46 Z" fill="currentColor" opacity="0.3"/>
  <path d="M9 54 L15 54 L15 59 L9 59 Z" fill="currentColor" opacity="0.3"/>
  <line x1="15" y1="0" x2="15" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="65" x2="15" y2="70" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Kneader/Mixer
export const KneaderMixer = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 10 L8 42 Q8 45 11 45 L39 45 Q42 45 42 42 L42 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 10 L42 10" stroke="currentColor" stroke-width="2"/>
  <path d="M20 10 L20 30 Q20 35 25 35 Q30 35 30 30 L30 10" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="25" x2="50" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Blender Vessel
export const BlenderVessel = `
<svg viewBox="0 0 40 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 8 L5 45 L15 55 L25 55 L35 45 L35 8 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="8" x2="35" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="0" x2="20" y2="35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M14 35 L20 30 L26 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="20" y1="55" x2="20" y2="60" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Rotary Filter (drum)
export const RotaryFilter = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="30" cy="25" rx="22" ry="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="7" x2="30" y2="43" stroke="currentColor" stroke-width="1.5"/>
  <line x1="12" y1="13" x2="48" y2="37" stroke="currentColor" stroke-width="1" opacity="0.4"/>
  <line x1="12" y1="37" x2="48" y2="13" stroke="currentColor" stroke-width="1" opacity="0.4"/>
  <line x1="0" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="52" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Prill Tower
export const PrillTower = `
<svg viewBox="0 0 40 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="5" width="24" height="70" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="16" cy="25" r="2" fill="currentColor" opacity="0.3"/>
  <circle cx="24" cy="30" r="2" fill="currentColor" opacity="0.3"/>
  <circle cx="18" cy="40" r="2" fill="currentColor" opacity="0.3"/>
  <circle cx="22" cy="50" r="2" fill="currentColor" opacity="0.3"/>
  <circle cx="16" cy="55" r="2" fill="currentColor" opacity="0.3"/>
  <line x1="20" y1="0" x2="20" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="75" x2="20" y2="80" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Briquetting Machine
export const BriquettingMachine = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="8" width="34" height="24" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="8" x2="22" y2="32" stroke="currentColor" stroke-width="2"/>
  <path d="M12 16 L20 20 L12 24" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <rect x="24" y="14" width="8" height="4" fill="currentColor" opacity="0.3"/>
  <rect x="24" y="22" width="8" height="4" fill="currentColor" opacity="0.3"/>
  <line x1="0" y1="20" x2="8" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Scraper Conveyor
export const ScraperConveyor = `
<svg viewBox="0 0 80 25" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="3" width="70" height="19" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="3" x2="15" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="30" y1="3" x2="30" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="45" y1="3" x2="45" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="60" y1="3" x2="60" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="12" x2="5" y2="12" stroke="currentColor" stroke-width="2"/>
  <line x1="75" y1="12" x2="80" y2="12" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Skip Hoist
export const SkipHoist = `
<svg viewBox="0 0 30 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="8" y1="5" x2="8" y2="60" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="5" x2="22" y2="60" stroke="currentColor" stroke-width="2"/>
  <rect x="5" y="35" width="20" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 5 L15 0 L22 5" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="0" x2="15" y2="35" stroke="currentColor" stroke-width="1" stroke-dasharray="3 2"/>
  <line x1="15" y1="50" x2="15" y2="70" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Overhead Conveyor
export const OverheadConveyor = `
<svg viewBox="0 0 80 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="5" y1="8" x2="75" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="15" cy="8" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="65" cy="8" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="15" y1="12" x2="15" y2="22" stroke="currentColor" stroke-width="1"/>
  <line x1="30" y1="8" x2="30" y2="22" stroke="currentColor" stroke-width="1"/>
  <line x1="45" y1="8" x2="45" y2="22" stroke="currentColor" stroke-width="1"/>
  <line x1="65" y1="12" x2="65" y2="22" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="8" x2="5" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="75" y1="8" x2="80" y2="8" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Hoist
export const Hoist = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 5 L30 5 L30 15 L10 15 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="20" cy="10" r="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="20" y1="15" x2="20" y2="30" stroke="currentColor" stroke-width="1.5"/>
  <path d="M14 30 L20 35 L26 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="20" y1="35" x2="20" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Electric Motor (standalone)
export const ElectricMotor = `
<svg viewBox="0 0 50 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="17" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="21" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor" stroke="none">M</text>
  <line x1="34" y1="17" x2="50" y2="17" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="17" x2="6" y2="17" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Tank Truck
export const TankTruck = `
<svg viewBox="0 0 70 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 10 Q5 5 10 5 L55 5 Q60 5 60 10 L60 25 L5 25 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="60" y="15" width="8" height="13" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="18" cy="30" r="5" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="48" cy="30" r="5" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="32" y1="0" x2="32" y2="5" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Tank Car (rail)
export const TankCar = `
<svg viewBox="0 0 70 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 10 Q10 5 15 5 L55 5 Q60 5 60 10 L60 25 Q60 30 55 30 L15 30 Q10 30 10 25 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="35" x2="65" y2="35" stroke="currentColor" stroke-width="2"/>
  <circle cx="18" cy="35" r="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="52" cy="35" r="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="35" y1="0" x2="35" y2="5" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Roll Crusher
export const RollCrusher = `
<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="16" cy="24" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="32" cy="24" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="16" cy="24" r="2" fill="currentColor"/>
  <circle cx="32" cy="24" r="2" fill="currentColor"/>
  <line x1="24" y1="0" x2="24" y2="14" stroke="currentColor" stroke-width="2"/>
  <line x1="24" y1="34" x2="24" y2="48" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Hammer Crusher
export const HammerCrusher = `
<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="24" cy="24" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="24" y1="10" x2="24" y2="16" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="16" x2="26" y2="16" stroke="currentColor" stroke-width="2"/>
  <line x1="24" y1="32" x2="24" y2="38" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="32" x2="26" y2="32" stroke="currentColor" stroke-width="2"/>
  <line x1="12" y1="22" x2="16" y2="22" stroke="currentColor" stroke-width="2"/>
  <line x1="12" y1="26" x2="16" y2="26" stroke="currentColor" stroke-width="2"/>
  <line x1="24" y1="0" x2="24" y2="8" stroke="currentColor" stroke-width="2"/>
  <line x1="24" y1="40" x2="24" y2="48" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// FITTINGS & SAFETY - Additional Types
// =============================================================================

// Y-Strainer
export const YStrainer = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="15" x2="20" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
  <circle cx="25" cy="15" r="8" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="23" x2="25" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="35" x2="30" y2="35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M20 12 L25 18 L30 12" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Bursting Disc
export const BurstingDisc = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M12 16 L28 24" stroke="currentColor" stroke-width="2"/>
  <path d="M12 24 L28 16" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="32" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="8" x2="20" y2="0" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Exhaust Head / Vent
export const ExhaustHead = `
<svg viewBox="0 0 30 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="15" y1="40" x2="15" y2="15" stroke="currentColor" stroke-width="2"/>
  <path d="M5 15 L15 5 L25 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="15" x2="25" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Open Vent
export const OpenVent = `
<svg viewBox="0 0 20 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="10" y1="40" x2="10" y2="5" stroke="currentColor" stroke-width="2"/>
  <path d="M5 10 L10 5 L15 10" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
</svg>
`

// Bell Mouth Inlet
export const BellMouth = `
<svg viewBox="0 0 40 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 5 Q5 15 15 15 L40 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M5 25 Q5 15 15 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="15" x2="40" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Valve Manifold
export const ValveManifold = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="12" width="50" height="16" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="12" x2="15" y2="0" stroke="currentColor" stroke-width="1.5"/>
  <line x1="30" y1="12" x2="30" y2="0" stroke="currentColor" stroke-width="1.5"/>
  <line x1="45" y1="12" x2="45" y2="0" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="55" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="28" x2="30" y2="40" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Exhaust Silencer
export const ExhaustSilencer = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="5" width="30" height="20" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="18" y1="5" x2="18" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="25" y1="5" x2="25" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="32" y1="5" x2="32" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="15" x2="10" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Hydrant
export const Hydrant = `
<svg viewBox="0 0 30 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="15" width="14" height="22" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 15 Q8 8 15 5 Q22 8 22 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="4" y1="25" x2="8" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="25" x2="26" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="37" x2="15" y2="45" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Tundish (waste funnel)
export const Tundish = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 5 L5 20 L15 30 L25 30 L35 20 L35 5" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="30" x2="20" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Liquid Seal Pot
export const LiquidSealPot = `
<svg viewBox="0 0 40 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="30" height="25" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M8 25 Q15 22 22 25 Q29 28 32 25" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="20" y1="0" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="20" x2="40" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="35" x2="20" y2="45" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Syphon Drain
export const SyphonDrain = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 0 L10 10 Q10 25 20 25 Q30 25 30 10 L30 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="20" y1="25" x2="20" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Drain Silencer
export const DrainSilencer = `
<svg viewBox="0 0 30 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="10" width="20" height="25" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="10" y1="10" x2="10" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="10" x2="15" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="20" y1="10" x2="20" y2="35" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="0" x2="15" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="35" x2="15" y2="45" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Electrically Bonded
export const ElectricallyBonded = `
<svg viewBox="0 0 50 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="50" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="5" x2="22" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="28" y1="5" x2="28" y2="15" stroke="currentColor" stroke-width="2"/>
  <path d="M22 3 Q25 0 28 3" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Electrically Insulated
export const ElectricallyInsulated = `
<svg viewBox="0 0 50 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="10" x2="50" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="5" x2="22" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="28" y1="5" x2="28" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// End Cap (flat)
export const EndCap = `
<svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="14" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="14" y1="3" x2="14" y2="17" stroke="currentColor" stroke-width="3"/>
</svg>
`

// =============================================================================
// JOINTS
// =============================================================================

// Butt Weld Joint
export const ButtWeldJoint = `
<svg viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="40" y2="10" stroke="currentColor" stroke-width="2"/>
  <path d="M18 4 L20 10 L22 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M18 16 L20 10 L22 16" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Flanged/Bolted Joint
export const FlangedJoint = `
<svg viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="40" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="18" y1="3" x2="18" y2="17" stroke="currentColor" stroke-width="2"/>
  <line x1="22" y1="3" x2="22" y2="17" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Screwed/Threaded Joint
export const ScrewedJoint = `
<svg viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="40" y2="10" stroke="currentColor" stroke-width="2"/>
  <circle cx="20" cy="10" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="20" cy="10" r="1.5" fill="currentColor"/>
</svg>
`

// Socket Weld Joint
export const SocketWeldJoint = `
<svg viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="40" y2="10" stroke="currentColor" stroke-width="2"/>
  <rect x="16" y="4" width="8" height="12" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Swivel Joint
export const SwivelJoint = `
<svg viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="15" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="10" x2="40" y2="10" stroke="currentColor" stroke-width="2"/>
  <circle cx="20" cy="10" r="5" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M16 6 A6 6 0 0 1 24 6" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M16 14 A6 6 0 0 0 24 14" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// =============================================================================
// PIPING - Additional Types
// =============================================================================

// Jacketed Pipeline
export const JacketedPipe = `
<svg viewBox="0 0 60 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="60" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="5" y1="4" x2="55" y2="4" stroke="currentColor" stroke-width="1"/>
  <line x1="5" y1="16" x2="55" y2="16" stroke="currentColor" stroke-width="1"/>
  <line x1="5" y1="4" x2="5" y2="16" stroke="currentColor" stroke-width="1"/>
  <line x1="55" y1="4" x2="55" y2="16" stroke="currentColor" stroke-width="1"/>
</svg>
`

// Traced Pipeline (heat traced)
export const TracedPipe = `
<svg viewBox="0 0 60 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="60" y2="10" stroke="currentColor" stroke-width="2"/>
  <path d="M5 5 Q12 15 20 5 Q28 15 36 5 Q44 15 52 5" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Future Pipeline (dashed)
export const FuturePipe = `
<svg viewBox="0 0 60 10" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="5" x2="60" y2="5" stroke="currentColor" stroke-width="2" stroke-dasharray="8 4"/>
</svg>
`

// Connection Point (filled dot)
export const ConnectionPoint = `
<svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="10" cy="10" r="5" fill="currentColor"/>
</svg>
`

// Crossover (pipe crossing without connection)
export const Crossover = `
<svg viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="15" x2="30" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="0" x2="15" y2="11" stroke="currentColor" stroke-width="2"/>
  <path d="M15 11 Q18 15 15 19" stroke="none" fill="none"/>
  <line x1="15" y1="19" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <path d="M12 12 Q15 15 18 12" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Pneumatic Conveying
export const PneumaticConveying = `
<svg viewBox="0 0 60 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="10" x2="60" y2="10" stroke="currentColor" stroke-width="2"/>
  <path d="M15 6 L20 10 L15 14" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M30 6 L35 10 L30 14" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M45 6 L50 10 L45 14" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Major Pipeline (thick)
export const MajorPipeline = `
<svg viewBox="0 0 60 10" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="5" x2="60" y2="5" stroke="currentColor" stroke-width="4"/>
</svg>
`

// =============================================================================
// ANNOTATIONS
// =============================================================================

// Callout Box
export const CalloutBox = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="2" y="2" width="56" height="28" rx="2" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M15 30 L20 38 L25 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
</svg>
`

// Off-Sheet Label (pentagon arrow)
export const OffSheetLabel = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 5 L35 5 L45 15 L35 25 L5 25 Z" stroke="currentColor" stroke-width="2" fill="none"/>
</svg>
`

// Interface Point (circle with line)
export const InterfacePoint = `
<svg viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="15" cy="15" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="5" x2="15" y2="25" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// =============================================================================
// ISA 5.1 INSTRUMENT BALLOONS
// =============================================================================
// Generic instrument balloon symbols per ISA 5.1 / ISA S5.1 mounting-location
// conventions. Each balloon has ISA letter labels rendered via the symbol label.
// These are placeable standalone symbols with left/right process connection ports.

// Field Instrument — plain circle (ISA 5.1: field-mounted discrete instrument)
export const IsaFieldInstrument = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="14" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Panel-Mounted Instrument — circle with horizontal line (ISA 5.1: main panel)
export const IsaPanelInstrument = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="14" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="11" y1="20" x2="39" y2="20" stroke="currentColor" stroke-width="1.2"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Behind-Panel Instrument — dashed circle (ISA 5.1: inaccessible / behind panel)
export const IsaBehindPanelInstrument = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="14" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="4,3"/>
  <line x1="0" y1="20" x2="11" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="39" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Local Panel Instrument — circle inside square (ISA 5.1: local panel)
export const IsaLocalPanelInstrument = `
<svg viewBox="0 0 56 44" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="4" width="36" height="36" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="28" cy="22" r="13" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="22" x2="10" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="46" y1="22" x2="56" y2="22" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// DCS / Computer Function — square (ISA 5.1: DCS or computer function)
export const IsaDCSFunction = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="5" width="30" height="30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="10" y2="20" stroke="currentColor" stroke-width="1.5"/>
  <line x1="40" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// PLC / Programmable Function — diamond (ISA 5.1: PLC or programmable logic)
export const IsaPLCFunction = `
<svg viewBox="0 0 56 44" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="28,4 50,22 28,40 6,22" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="22" x2="6" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="50" y1="22" x2="56" y2="22" stroke="currentColor" stroke-width="1.5"/>
</svg>
`

// Shared Display / Shared Control — hexagon (ISA 5.1: shared display/control)
export const IsaSharedDisplay = `
<svg viewBox="0 0 56 44" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="16,4 40,4 52,22 40,40 16,40 4,22" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="22" x2="4" y2="22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="52" y1="22" x2="56" y2="22" stroke="currentColor" stroke-width="1.5"/>
</svg>
`
