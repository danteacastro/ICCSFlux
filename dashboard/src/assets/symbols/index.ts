// =============================================================================
// SCADA Symbol Library - Industrial Process Equipment SVG Symbols
// =============================================================================
// All symbols are SVG strings that can be rendered inline with dynamic coloring
// via CSS currentColor. Symbols scale to any size.

// Additional P&ID symbols (ISA 5.1 / ISO 10628)
import {
  GlobeValve, AngleValve, StopCheckValve, ReducingValve, PoweredValve,
  FloatValve, ThreeWayPlugValve, WedgeGateValve, FlangedValve, ReliefAngleValve,
  ScrewDownValve, MixingValve, CharacterPortValve,
  InlinePump, ReciprocatingPump, RotaryPump, PositiveDisplacementPump,
  ProportioningPump, CentrifugalFan, RotaryCompressor, EjectorInjector,
  MotorDrivenTurbine, CompressorTurbine, SprayHead,
  ShellAndTubeHX, KettleReboiler, FiredHeater, CoolingTower, DoublePipeHX,
  FinnedTubeHX, AutoclaveHX, EvaporativeCondenser, OilBurner, OilSeparator,
  ExtractorHood, Refrigerator,
  OpenTank, ClosedTank, CoveredTank, GasHolder, GasCylinder, Barrel,
  TrayColumn, Clarifier, ReactionVessel, Vessel, FluidContacting,
  PLCController, DCSComputer, Rotameter, VenturiElement, ANDGate, ORGate,
  NOTGate, IndicatorRecorder, SignalConverter, OperatorStation, Thermometer,
  LevelMeter, IndicatorLight, PropellerMeter, VortexSensor, GenericIndicator,
  CRTDisplay, CorrectingElement, DiamondSymbol, FlowmeterGeneric, PressureGauges,
  BallMill, JawCrusher, VibratingScreen, ScrewConveyor, BucketElevator,
  KneaderMixer, BlenderVessel, RotaryFilter, PrillTower, BriquettingMachine,
  ScraperConveyor, SkipHoist, OverheadConveyor, Hoist, ElectricMotor,
  TankTruck, TankCar, RollCrusher, HammerCrusher,
  YStrainer, BurstingDisc, ExhaustHead, OpenVent, BellMouth, ValveManifold,
  ExhaustSilencer, Hydrant, Tundish, LiquidSealPot, SyphonDrain, DrainSilencer,
  ElectricallyBonded, ElectricallyInsulated, EndCap,
  ButtWeldJoint, FlangedJoint, ScrewedJoint, SocketWeldJoint, SwivelJoint,
  JacketedPipe, TracedPipe, FuturePipe, ConnectionPoint, Crossover,
  PneumaticConveying, MajorPipeline,
  CalloutBox, OffSheetLabel, InterfacePoint,
  IsaFieldInstrument, IsaPanelInstrument, IsaBehindPanelInstrument,
  IsaLocalPanelInstrument, IsaDCSFunction, IsaPLCFunction, IsaSharedDisplay,
} from './newSymbols'

// =============================================================================
// VALVES
// =============================================================================

// Solenoid Valve (2-way, inline)
export const SolenoidValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 12 L30 20 L15 28 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 12 L30 20 L45 28 Z" class="valve-body" fill="currentColor"/>
  <rect x="22" y="2" width="16" height="10" rx="1" class="actuator" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="12" x2="30" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Control Valve (globe style with diaphragm actuator)
export const ControlValve = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" class="valve-body" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="8" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Manual Valve (handwheel)
export const ManualValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 17 L30 25 L15 33 Z" class="valve-body" fill="currentColor"/>
  <path d="M45 17 L30 25 L45 33 Z" class="valve-body" fill="currentColor"/>
  <line x1="30" y1="17" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="5" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Check Valve (non-return)
export const CheckValve = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 15 L28 15 M24 10 L28 15 L24 20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="0" y1="15" x2="13" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="37" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Ball Valve
export const BallValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="20" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="30" cy="20" r="6" fill="currentColor" opacity="0.5"/>
  <line x1="30" y1="8" x2="30" y2="3" stroke="currentColor" stroke-width="2"/>
  <rect x="25" y="0" width="10" height="4" fill="currentColor"/>
  <line x1="0" y1="20" x2="18" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Butterfly Valve
export const ButterflyValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="20" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="14" x2="38" y2="26" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="10" x2="30" y2="3" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="20" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Relief/Safety Valve
export const ReliefValve = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 35 L25 25 L35 35 Z" fill="currentColor"/>
  <rect x="18" y="10" width="14" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="25" y1="10" x2="25" y2="3" stroke="currentColor" stroke-width="2"/>
  <path d="M20 3 L25 8 L30 3" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="35" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// 3-Way Valve
export const ThreeWayValve = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <path d="M22 45 L30 30 L38 45 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="8" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="45" x2="30" y2="60" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Gate Valve
export const GateValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="15" width="30" height="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="15" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="5" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="5" x2="35" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Needle Valve
export const NeedleValve = `
<svg viewBox="0 0 50 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M12 17 L25 25 L12 33 Z" fill="currentColor"/>
  <path d="M38 17 L25 25 L38 33 Z" fill="currentColor"/>
  <line x1="25" y1="17" x2="25" y2="5" stroke="currentColor" stroke-width="1.5"/>
  <polygon points="25,25 23,17 27,17" fill="currentColor"/>
  <circle cx="25" cy="5" r="4" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="0" y1="25" x2="12" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="38" y1="25" x2="50" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// INSTRUMENTS - Transmitters & Sensors
// =============================================================================

// Pressure Transmitter
export const PressureTransducer = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">PT</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Temperature Element
export const TemperatureElement = `
<svg viewBox="0 0 30 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="15" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="15" y="19" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">TE</text>
  <line x1="15" y1="27" x2="15" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Flow Meter/Transmitter
export const FlowMeter = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="30" y="24" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">FT</text>
  <line x1="0" y1="20" x2="16" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="44" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Level Transmitter
export const LevelTransmitter = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">LT</text>
  <line x1="20" y1="36" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Flow Switch
export const FlowSwitch = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="17" y="5" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="25" y="16" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">FS</text>
  <path d="M20 25 L25 30 L30 25" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="17" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="33" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pressure Switch
export const PressureSwitch = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="30" height="25" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="21" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">PS</text>
  <line x1="20" y1="30" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="13" y1="40" x2="13" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="37" y1="40" x2="37" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// pH Sensor
export const PHSensor = `
<svg viewBox="0 0 40 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="0" width="16" height="20" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="20" y="14" text-anchor="middle" font-size="8" font-weight="bold" fill="currentColor">pH</text>
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
  <line x1="25" y1="10" x2="25" y2="22" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="25" y1="40" x2="25" y2="55" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Temperature Indicator
export const TemperatureIndicator = `
<svg viewBox="0 0 35 55" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="17" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="17" y="24" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor">TI</text>
  <line x1="17" y1="34" x2="17" y2="54" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// EQUIPMENT - Rotating & Process
// =============================================================================

// Pump (centrifugal)
export const Pump = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="20" r="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M18 25 L25 15 L32 25" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="0" y1="20" x2="10" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="0" x2="25" y2="5" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Positive Displacement Pump
export const PDPump = `
<svg viewBox="0 0 55 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="27" cy="20" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="13" y="14" width="28" height="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 20 L27 13 L34 20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="0" y1="20" x2="13" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="41" y1="20" x2="55" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Compressor
export const Compressor = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <polygon points="30,12 22,30 38,30" stroke="currentColor" stroke-width="2" fill="none"/>
  <text x="30" y="44" text-anchor="middle" font-size="7" fill="currentColor">C</text>
  <line x1="0" y1="25" x2="12" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="48" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Blower/Fan
export const Blower = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="28" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M28 10 Q35 18 28 25 Q21 32 28 40" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 18 Q23 25 15 32" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="28" cy="25" r="4" fill="currentColor"/>
  <line x1="0" y1="25" x2="10" y2="25" stroke="currentColor" stroke-width="2"/>
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
  <polygon points="25,12 8,38 42,38" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="12" y1="25" x2="38" y2="25" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="15" y1="31" x2="35" y2="31" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="25" y1="0" x2="25" y2="12" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="38" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="22" y1="40" x2="22" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="20" y1="0" x2="20" y2="5" stroke="currentColor" stroke-width="2"/>
  <line x1="60" y1="45" x2="60" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="0" y1="11" x2="10" y2="11" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="49" x2="50" y2="49" stroke="currentColor" stroke-width="2"/>
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
  <line x1="35" y1="0" x2="35" y2="7" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="43" x2="35" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="40" y1="0" x2="40" y2="7" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="43" x2="40" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="0" y1="24" x2="10" y2="24" stroke="currentColor" stroke-width="2"/>
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
  <line x1="25" y1="7" x2="25" y2="0" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="15" x2="7" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="60" x2="25" y2="70" stroke="currentColor" stroke-width="2"/>
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
  <line x1="0" y1="34" x2="8" y2="34" stroke="currentColor" stroke-width="2"/>
  <line x1="52" y1="12" x2="60" y2="12" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="68" x2="30" y2="70" stroke="currentColor" stroke-width="2"/>
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
  <line x1="30" y1="62" x2="30" y2="65" stroke="currentColor" stroke-width="2"/>
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
  <path d="M0 8 L15 8 L35 12 L50 12 L50 15 L50 18 L35 18 L15 22 L0 22 L0 15 Z" fill="currentColor" opacity="0.4"/>
  <path d="M0 8 L15 8 L35 12 L50 12" stroke="currentColor" stroke-width="1" fill="none"/>
  <path d="M0 22 L15 22 L35 18 L50 18" stroke="currentColor" stroke-width="1" fill="none"/>
</svg>
`

// Flange
export const Flange = `
<svg viewBox="0 0 30 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="3" y="15" width="24" height="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="7" cy="20" r="2" fill="currentColor"/>
  <circle cx="23" cy="20" r="2" fill="currentColor"/>
  <line x1="15" y1="0" x2="15" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="25" x2="15" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Blind Flange / Cap
export const BlindFlange = `
<svg viewBox="0 0 30 25" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="30" height="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="6" cy="6" r="2" fill="currentColor"/>
  <circle cx="24" cy="6" r="2" fill="currentColor"/>
  <line x1="15" y1="12" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Expansion Joint
export const ExpansionJoint = `
<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 8 L15 8 L15 22 L10 22 M40 8 L35 8 L35 22 L40 22" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 10 Q20 15 25 10 Q30 5 35 10 M15 20 Q20 15 25 20 Q30 25 35 20" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="15" x2="10" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="15" x2="50" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// =============================================================================
// MISCELLANEOUS
// =============================================================================

// Rupture Disc
export const RuptureDisc = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="18" r="14" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M12 12 L28 24 M12 24 L28 12" stroke="currentColor" stroke-width="1.5"/>
  <line x1="20" y1="32" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Flame Arrestor
export const FlameArrestor = `
<svg viewBox="0 0 40 35" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="5" width="16" height="24" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="10" x2="25" y2="10" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="15" x2="25" y2="15" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="20" x2="25" y2="20" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="25" x2="25" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="17" x2="12" y2="17" stroke="currentColor" stroke-width="2"/>
  <line x1="28" y1="17" x2="40" y2="17" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Strainer
export const Strainer = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="15,12 35,12 35,28 15,28 20,20" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="22" y1="15" x2="22" y2="25" stroke="currentColor" stroke-width="1"/>
  <line x1="26" y1="14" x2="26" y2="26" stroke="currentColor" stroke-width="1"/>
  <line x1="30" y1="13" x2="30" y2="27" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Sight Glass
export const SightGlass = `
<svg viewBox="0 0 40 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="10" width="24" height="30" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="12" y="14" width="16" height="22" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.15"/>
  <line x1="20" y1="0" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="40" x2="20" y2="50" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Static Mixer
export const StaticMixer = `
<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="5" width="40" height="20" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 8 L25 22 M25 8 L35 22 M35 8 L45 22" stroke="currentColor" stroke-width="1.5"/>
  <line x1="0" y1="15" x2="10" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="50" y1="15" x2="60" y2="15" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Spray Nozzle
export const SprayNozzle = `
<svg viewBox="0 0 40 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="20" y1="0" x2="20" y2="15" stroke="currentColor" stroke-width="2"/>
  <polygon points="20,15 8,40 32,40" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="14" y1="30" x2="10" y2="42" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="20" y1="32" x2="20" y2="45" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="26" y1="30" x2="30" y2="42" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
</svg>
`

// Ejector/Eductor
export const Ejector = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 12 L20 12 L20 28 L10 28" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 16 L30 16 L40 12 L50 12 L50 28 L40 28 L30 24 L20 24" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="26" y1="0" x2="26" y2="16" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="10" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="50" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
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
  <text x="35" y="6" text-anchor="middle" font-size="6" fill="currentColor">H₂</text>
  <circle cx="25" cy="23" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="45" cy="23" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="25" cy="43" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="45" cy="43" r="3" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="24" x2="10" y2="24" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="40" x2="10" y2="40" stroke="currentColor" stroke-width="2"/>
  <line x1="60" y1="24" x2="70" y2="24" stroke="currentColor" stroke-width="2"/>
  <line x1="60" y1="40" x2="70" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Water Electrolyzer (PEM/Alkaline)
export const Electrolyzer = `
<svg viewBox="0 0 60 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="15" width="40" height="45" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
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
  <line x1="30" y1="60" x2="30" y2="70" stroke="currentColor" stroke-width="2"/>
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
  <text x="7" y="16" text-anchor="middle" font-size="5" fill="currentColor">CH₄</text>
  <text x="7" y="38" text-anchor="middle" font-size="5" fill="currentColor">H₂O</text>
  <text x="63" y="16" text-anchor="middle" font-size="5" fill="currentColor">H₂</text>
  <line x1="0" y1="21" x2="15" y2="21" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="31" x2="15" y2="31" stroke="currentColor" stroke-width="2"/>
  <line x1="55" y1="21" x2="70" y2="21" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="65" x2="35" y2="80" stroke="currentColor" stroke-width="2"/>
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
  <circle cx="25" cy="8" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="25" y1="0" x2="25" y2="4" stroke="currentColor" stroke-width="2"/>
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
  <line x1="25" y1="55" x2="25" y2="70" stroke="currentColor" stroke-width="2"/>
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
  <path d="M20 35 L25 30 L30 38 L35 28 L40 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="30" y="78" text-anchor="middle" font-size="5" fill="currentColor">ASH</text>
  <line x1="0" y1="33" x2="15" y2="33" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="28" x2="60" y2="28" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="0" x2="30" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="80" x2="30" y2="90" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Syngas Cleanup / Gas Scrubber
export const SyngasCleanup = `
<svg viewBox="0 0 50 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 Q10 5 25 5 Q40 5 40 15 L40 65 Q40 75 25 75 Q10 75 10 65 Z" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="25" cy="25" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <ellipse cx="25" cy="40" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <ellipse cx="25" cy="55" rx="10" ry="4" stroke="currentColor" stroke-width="1" fill="currentColor" opacity="0.2"/>
  <path d="M18 15 L20 12 L22 15 M25 13 L27 10 L29 13 M32 15 L34 12 L36 15" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="40" y1="21" x2="50" y2="21" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="63" x2="10" y2="63" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="75" x2="25" y2="80" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Biomass Hopper/Feeder
export const Hopper = `
<svg viewBox="0 0 50 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,5 45,5 45,30 35,55 15,55 5,30" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="18" y="55" width="14" height="15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="15" x2="45" y2="15" stroke="currentColor" stroke-width="1"/>
  <path d="M22 60 L22 65 M25 58 L25 65 M28 60 L28 65" stroke="currentColor" stroke-width="1.5"/>
  <line x1="25" y1="0" x2="25" y2="5" stroke="currentColor" stroke-width="2"/>
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
  <path d="M38 0 L40 -5 L42 0" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="0" y1="30" x2="3" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="77" y1="30" x2="80" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Industrial Furnace
export const Furnace = `
<svg viewBox="0 0 70 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="50" height="40" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="15" y="15" width="40" height="25" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.15"/>
  <path d="M20 35 L25 28 L30 38 L35 25 L40 38 L45 28 L50 35" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
  <path d="M33 5 L35 0 L37 5" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="10" y1="50" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="50" x2="60" y2="50" stroke="currentColor" stroke-width="2"/>
  <rect x="25" y="48" width="20" height="12" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.2"/>
  <line x1="0" y1="26" x2="10" y2="26" stroke="currentColor" stroke-width="2"/>
  <line x1="60" y1="26" x2="70" y2="26" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Regenerative Burner
export const Burner = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="25" cy="30" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="30" r="10" stroke="currentColor" stroke-width="1.5" fill="currentColor" opacity="0.2"/>
  <path d="M22 30 Q22 22 25 18 Q28 22 28 30" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="25" cy="30" r="3" fill="currentColor"/>
  <line x1="0" y1="30" x2="7" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="0" x2="25" y2="12" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Heating/Cooling Coil
export const Coil = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="50" height="40" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 15 Q15 10 20 15 Q25 20 30 15 Q35 10 40 15 Q45 20 50 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 25 Q15 20 20 25 Q25 30 30 25 Q35 20 40 25 Q45 30 50 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M10 35 Q15 30 20 35 Q25 40 30 35 Q35 30 40 35 Q45 40 50 35" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="0" y1="15" x2="5" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="55" y1="35" x2="60" y2="35" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Tankless/Tank Water Heater
export const WaterHeater = `
<svg viewBox="0 0 45 70" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="10" width="30" height="50" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M15 45 L18 40 L21 48 L24 38 L27 48 L30 40 L33 45" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <circle cx="23" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="23" y="28" text-anchor="middle" font-size="7" fill="currentColor">T</text>
  <line x1="8" y1="55" x2="38" y2="55" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="0" x2="15" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="31" y1="0" x2="31" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="23" y1="60" x2="23" y2="70" stroke="currentColor" stroke-width="2"/>
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
  <path d="M20 5 L22 0 L24 5" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="10" y1="30" x2="34" y2="30" stroke="currentColor" stroke-width="1"/>
  <line x1="0" y1="29" x2="5" y2="29" stroke="currentColor" stroke-width="2"/>
  <line x1="75" y1="21" x2="80" y2="21" stroke="currentColor" stroke-width="2"/>
  <line x1="75" y1="39" x2="80" y2="39" stroke="currentColor" stroke-width="2"/>
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
  <path d="M20 15 L25 25 L20 35" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M25 12 L30 25 L25 38" stroke="currentColor" stroke-width="1" fill="none"/>
  <circle cx="25" cy="25" r="4" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="25" x2="17" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Electric Generator
export const Generator = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="35" cy="25" r="18" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="35" cy="25" r="10" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="35" y="29" text-anchor="middle" font-size="10" font-weight="bold" fill="currentColor">G</text>
  <line x1="0" y1="25" x2="17" y2="25" stroke="currentColor" stroke-width="3"/>
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
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,5 35,5 45,20 35,35 5,35" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <line x1="0" y1="20" x2="5" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Off-Page Connector - Arrow pointing left (flow coming from another page)
export const OffPageConnectorLeft = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="45,5 15,5 5,20 15,35 45,35" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <line x1="45" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Off-Page Connector - Pentagon (standard P&ID style, to page)
export const OffPageConnectorTo = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,5 45,5 45,35 25,45 5,35" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <line x1="25" y1="0" x2="25" y2="5" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Off-Page Connector - Pentagon inverted (from page)
export const OffPageConnectorFrom = `
<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="5,15 25,5 45,15 45,45 5,45" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/>
  <line x1="25" y1="45" x2="25" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="40" y1="45" x2="40" y2="50" stroke="currentColor" stroke-width="2"/>
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
  <line x1="20" y1="5" x2="20" y2="35" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="5" x2="30" y2="35" stroke="currentColor" stroke-width="2"/>
  <path d="M20 15 Q25 20 30 15" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <path d="M20 25 Q25 20 30 25" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="20" x2="20" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="30" y1="20" x2="50" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Diaphragm Valve
export const DiaphragmValve = `
<svg viewBox="0 0 60 45" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="20" width="30" height="18" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M20 29 Q30 22 40 29" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="20" x2="30" y2="8" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="29" x2="15" y2="29" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="29" x2="60" y2="29" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Plug Valve
export const PlugValve = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="20" r="12" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="26" y="14" width="8" height="12" fill="currentColor" opacity="0.4"/>
  <line x1="30" y1="8" x2="30" y2="2" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="20" x2="18" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="42" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pressure Regulator
export const PressureRegulator = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L30 30 L15 38 Z" fill="currentColor"/>
  <path d="M45 22 L30 30 L45 38 Z" fill="currentColor"/>
  <line x1="30" y1="22" x2="30" y2="12" stroke="currentColor" stroke-width="2"/>
  <rect x="22" y="2" width="16" height="10" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="30" y="10" text-anchor="middle" font-size="6" fill="currentColor">REG</text>
  <line x1="0" y1="30" x2="15" y2="30" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Centrifuge
export const Centrifuge = `
<svg viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="30" cy="35" r="22" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="30" cy="35" r="12" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="30" y1="13" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <rect x="26" y="0" width="8" height="6" fill="currentColor"/>
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
  <line x1="0" y1="26" x2="10" y2="26" stroke="currentColor" stroke-width="2"/>
  <line x1="50" y1="26" x2="60" y2="26" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Scrubber (gas cleaning)
export const Scrubber = `
<svg viewBox="0 0 50 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 15 L10 65 Q10 75 25 75 Q40 75 40 65 L40 15 Q40 5 25 5 Q10 5 10 15" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="15" y1="25" x2="35" y2="25" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="15" y1="40" x2="35" y2="40" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="15" y1="55" x2="35" y2="55" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="25" y1="75" x2="25" y2="80" stroke="currentColor" stroke-width="2"/>
  <line x1="0" y1="63" x2="10" y2="63" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="33" x2="50" y2="33" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Absorber Tower
export const Absorber = `
<svg viewBox="0 0 50 90" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 10 L10 75 Q10 85 25 85 Q40 85 40 75 L40 10 Q40 0 25 0 Q10 0 10 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <ellipse cx="25" cy="20" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <ellipse cx="25" cy="40" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <ellipse cx="25" cy="60" rx="12" ry="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <line x1="0" y1="48" x2="10" y2="48" stroke="currentColor" stroke-width="2"/>
  <line x1="40" y1="28" x2="50" y2="28" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Diaphragm Pump
export const DiaphragmPump = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="10" width="30" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <path d="M25 15 L25 35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M35 15 L35 35" stroke="currentColor" stroke-width="1.5"/>
  <path d="M25 25 Q30 18 35 25" stroke="currentColor" stroke-width="2" fill="none"/>
  <rect x="26" y="0" width="8" height="10" fill="currentColor"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Gear Pump
export const GearPump = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="10" width="30" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <circle cx="25" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="35" cy="25" r="8" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <circle cx="25" cy="25" r="3" fill="currentColor" opacity="0.4"/>
  <circle cx="35" cy="25" r="3" fill="currentColor" opacity="0.4"/>
  <line x1="0" y1="25" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
  <line x1="45" y1="25" x2="60" y2="25" stroke="currentColor" stroke-width="2"/>
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
  <line x1="27" y1="15" x2="33" y2="15" stroke="currentColor" stroke-width="2"/>
  <circle cx="45" cy="15" r="12" stroke="currentColor" stroke-width="2" fill="currentColor" opacity="0.2"/>
</svg>
`

// Pipe Cross
export const PipeCross = `
<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="15" y="15" width="10" height="10" stroke="currentColor" stroke-width="1" fill="none"/>
  <line x1="0" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="25" y1="20" x2="40" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="0" x2="20" y2="15" stroke="currentColor" stroke-width="2"/>
  <line x1="20" y1="25" x2="20" y2="40" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Pipe Cap
export const PipeCap = `
<svg viewBox="0 0 30 25" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 10 Q15 0 25 10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="5" y1="10" x2="25" y2="10" stroke="currentColor" stroke-width="2"/>
  <line x1="15" y1="10" x2="15" y2="25" stroke="currentColor" stroke-width="2"/>
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
  <line x1="0" y1="25" x2="10" y2="25" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Steam Trap (inverted bucket style, ISA standard)
export const SteamTrap = `
<svg viewBox="0 0 50 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 12 L25 20 L15 28 Z" class="valve-body" fill="currentColor"/>
  <path d="M35 12 L25 20 L35 28 Z" class="valve-body" fill="currentColor"/>
  <line x1="5" y1="20" x2="15" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="35" y1="20" x2="45" y2="20" stroke="currentColor" stroke-width="2"/>
  <circle cx="25" cy="32" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/>
  <text x="25" y="35" text-anchor="middle" font-size="7" fill="currentColor">S</text>
</svg>
`

// Damper (HVAC/duct control, ISA standard)
export const Damper = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="8" width="40" height="24" rx="2" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="18" y1="12" x2="42" y2="28" stroke="currentColor" stroke-width="2"/>
  <line x1="18" y1="20" x2="42" y2="20" stroke="currentColor" stroke-width="1" stroke-dasharray="2,2" opacity="0.4"/>
  <line x1="0" y1="20" x2="10" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="50" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
</svg>
`

// Desuperheater (spray-type, ISA standard)
export const Desuperheater = `
<svg viewBox="0 0 60 50" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="30" x2="60" y2="30" stroke="currentColor" stroke-width="2"/>
  <circle cx="30" cy="30" r="10" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="30" y1="20" x2="30" y2="5" stroke="currentColor" stroke-width="2"/>
  <path d="M26 12 L30 5 L34 12" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <circle cx="25" cy="30" r="1.5" fill="currentColor" opacity="0.6"/>
  <circle cx="30" cy="27" r="1.5" fill="currentColor" opacity="0.6"/>
  <circle cx="35" cy="30" r="1.5" fill="currentColor" opacity="0.6"/>
  <circle cx="30" cy="33" r="1.5" fill="currentColor" opacity="0.6"/>
</svg>
`

// Silencer / Muffler (exhaust/vent, ISA standard)
export const Silencer = `
<svg viewBox="0 0 60 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="12" y="5" width="36" height="30" rx="3" stroke="currentColor" stroke-width="2" fill="none"/>
  <line x1="20" y1="5" x2="20" y2="35" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="30" y1="5" x2="30" y2="35" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="40" y1="5" x2="40" y2="35" stroke="currentColor" stroke-width="1" stroke-dasharray="3,2"/>
  <line x1="0" y1="20" x2="12" y2="20" stroke="currentColor" stroke-width="2"/>
  <line x1="48" y1="20" x2="60" y2="20" stroke="currentColor" stroke-width="2"/>
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
  steamTrap: SteamTrap,
  damper: Damper,
  desuperheater: Desuperheater,
  silencer: Silencer,
  // --- Additional Valves ---
  globeValve: GlobeValve,
  angleValve: AngleValve,
  stopCheckValve: StopCheckValve,
  reducingValve: ReducingValve,
  poweredValve: PoweredValve,
  floatValve: FloatValve,
  threeWayPlugValve: ThreeWayPlugValve,
  wedgeGateValve: WedgeGateValve,
  flangedValve: FlangedValve,
  reliefAngleValve: ReliefAngleValve,
  screwDownValve: ScrewDownValve,
  mixingValve: MixingValve,
  characterPortValve: CharacterPortValve,
  // --- Additional Pumps ---
  inlinePump: InlinePump,
  reciprocatingPump: ReciprocatingPump,
  rotaryPump: RotaryPump,
  positiveDisplacementPump: PositiveDisplacementPump,
  proportioningPump: ProportioningPump,
  centrifugalFan: CentrifugalFan,
  rotaryCompressor: RotaryCompressor,
  ejectorInjector: EjectorInjector,
  motorDrivenTurbine: MotorDrivenTurbine,
  compressorTurbine: CompressorTurbine,
  sprayHead: SprayHead,
  // --- Additional Heat Exchangers ---
  shellAndTubeHX: ShellAndTubeHX,
  kettleReboiler: KettleReboiler,
  firedHeater: FiredHeater,
  coolingTower: CoolingTower,
  doublePipeHX: DoublePipeHX,
  finnedTubeHX: FinnedTubeHX,
  autoclaveHX: AutoclaveHX,
  evaporativeCondenser: EvaporativeCondenser,
  oilBurner: OilBurner,
  oilSeparator: OilSeparator,
  extractorHood: ExtractorHood,
  refrigerator: Refrigerator,
  // --- Additional Vessels ---
  openTank: OpenTank,
  closedTank: ClosedTank,
  coveredTank: CoveredTank,
  gasHolder: GasHolder,
  gasCylinder: GasCylinder,
  barrel: Barrel,
  trayColumn: TrayColumn,
  clarifier: Clarifier,
  reactionVessel: ReactionVessel,
  vessel: Vessel,
  fluidContacting: FluidContacting,
  // --- Additional Instruments ---
  plcController: PLCController,
  dcsComputer: DCSComputer,
  rotameter: Rotameter,
  venturiElement: VenturiElement,
  andGate: ANDGate,
  orGate: ORGate,
  notGate: NOTGate,
  indicatorRecorder: IndicatorRecorder,
  signalConverter: SignalConverter,
  operatorStation: OperatorStation,
  thermometer: Thermometer,
  levelMeter: LevelMeter,
  indicatorLight: IndicatorLight,
  propellerMeter: PropellerMeter,
  vortexSensor: VortexSensor,
  genericIndicator: GenericIndicator,
  crtDisplay: CRTDisplay,
  correctingElement: CorrectingElement,
  diamondSymbol: DiamondSymbol,
  flowmeterGeneric: FlowmeterGeneric,
  pressureGauges: PressureGauges,
  // --- Additional Equipment ---
  ballMill: BallMill,
  jawCrusher: JawCrusher,
  vibratingScreen: VibratingScreen,
  screwConveyor: ScrewConveyor,
  bucketElevator: BucketElevator,
  kneaderMixer: KneaderMixer,
  blenderVessel: BlenderVessel,
  rotaryFilter: RotaryFilter,
  prillTower: PrillTower,
  briquettingMachine: BriquettingMachine,
  scraperConveyor: ScraperConveyor,
  skipHoist: SkipHoist,
  overheadConveyor: OverheadConveyor,
  hoist: Hoist,
  electricMotor: ElectricMotor,
  tankTruck: TankTruck,
  tankCar: TankCar,
  rollCrusher: RollCrusher,
  hammerCrusher: HammerCrusher,
  // --- Additional Fittings & Safety ---
  yStrainer: YStrainer,
  burstingDisc: BurstingDisc,
  exhaustHead: ExhaustHead,
  openVent: OpenVent,
  bellMouth: BellMouth,
  valveManifold: ValveManifold,
  exhaustSilencer: ExhaustSilencer,
  hydrant: Hydrant,
  tundish: Tundish,
  liquidSealPot: LiquidSealPot,
  syphonDrain: SyphonDrain,
  drainSilencer: DrainSilencer,
  electricallyBonded: ElectricallyBonded,
  electricallyInsulated: ElectricallyInsulated,
  endCap: EndCap,
  // --- Joints ---
  buttWeldJoint: ButtWeldJoint,
  flangedJoint: FlangedJoint,
  screwedJoint: ScrewedJoint,
  socketWeldJoint: SocketWeldJoint,
  swivelJoint: SwivelJoint,
  // --- Additional Piping ---
  jacketedPipe: JacketedPipe,
  tracedPipe: TracedPipe,
  futurePipe: FuturePipe,
  connectionPoint: ConnectionPoint,
  crossover: Crossover,
  pneumaticConveying: PneumaticConveying,
  majorPipeline: MajorPipeline,
  // --- Annotations ---
  calloutBox: CalloutBox,
  offSheetLabel: OffSheetLabel,
  interfacePoint: InterfacePoint,
  // --- ISA 5.1 Instrument Balloons ---
  isaFieldInstrument: IsaFieldInstrument,
  isaPanelInstrument: IsaPanelInstrument,
  isaBehindPanelInstrument: IsaBehindPanelInstrument,
  isaLocalPanelInstrument: IsaLocalPanelInstrument,
  isaDCSFunction: IsaDCSFunction,
  isaPLCFunction: IsaPLCFunction,
  isaSharedDisplay: IsaSharedDisplay,
  // Parametric ISA function block (letters + location set per-instance via PidSymbol.isaLetters/isaLocation)
  isaFunctionBlock: IsaFieldInstrument, // Default preview SVG; runtime uses generateIsaFunctionBlockSvg()
} as const

export type ScadaSymbolType = keyof typeof SCADA_SYMBOLS

// Parse viewBox dimensions from each SVG string for letterbox-aware port positioning.
// SVG default preserveAspectRatio="xMidYMid meet" scales content uniformly and centers it,
// so the rendered area may be offset from the widget bounding box edges.
const SYMBOL_VIEWBOX: Partial<Record<ScadaSymbolType, { width: number; height: number }>> = {}
for (const [type, svg] of Object.entries(SCADA_SYMBOLS)) {
  const match = svg.match(/viewBox=["'](\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["']/)
  if (match) {
    SYMBOL_VIEWBOX[type as ScadaSymbolType] = { width: parseFloat(match[3]!), height: parseFloat(match[4]!) }
  }
}

// Symbol capability flags for runtime behavior
export interface SymbolInfoEntry {
  label: string
  category: string
  isRotating?: boolean   // Pumps, fans, motors — spin animation when running
  isTank?: boolean       // Tanks, reactors, vessels — support fill level rendering
  isValve?: boolean      // Valves — support position animation (0-100%)
  variantGroup?: string  // Groups related symbols for variant switching in properties panel
}

// Symbol metadata for UI
export const SYMBOL_INFO: Record<ScadaSymbolType, SymbolInfoEntry> = {
  // Valves
  solenoidValve: { label: 'Solenoid Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  controlValve: { label: 'Control Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  manualValve: { label: 'Manual Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  checkValve: { label: 'Check Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  ballValve: { label: 'Ball Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  butterflyValve: { label: 'Butterfly Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  reliefValve: { label: 'Relief/Safety Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  threeWayValve: { label: '3-Way Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  gateValve: { label: 'Gate Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  needleValve: { label: 'Needle Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
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
  pump: { label: 'Centrifugal Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  pdPump: { label: 'PD Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  compressor: { label: 'Compressor', category: 'Equipment', isRotating: true },
  blower: { label: 'Blower/Fan', category: 'Equipment', isRotating: true, variantGroup: 'fan' },
  motor: { label: 'Electric Motor', category: 'Equipment', isRotating: true },
  mixer: { label: 'Agitator/Mixer', category: 'Equipment', isRotating: true },
  filter: { label: 'Filter', category: 'Equipment' },
  heater: { label: 'Electric Heater', category: 'Equipment' },
  cooler: { label: 'Cooler/Chiller', category: 'Equipment' },
  // Heat Exchangers
  heatExchanger: { label: 'Shell & Tube HX', category: 'Heat Exchangers', variantGroup: 'hx' },
  plateHeatExchanger: { label: 'Plate Heat Exchanger', category: 'Heat Exchangers', variantGroup: 'hx' },
  condenser: { label: 'Condenser', category: 'Heat Exchangers', variantGroup: 'hx' },
  airCooler: { label: 'Air Cooler (Fin Fan)', category: 'Heat Exchangers', variantGroup: 'hx' },
  // Vessels
  tank: { label: 'Vertical Tank', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  horizontalTank: { label: 'Horizontal Tank/Drum', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  reactor: { label: 'Reactor', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  column: { label: 'Column/Tower', category: 'Vessels' },
  cyclone: { label: 'Cyclone Separator', category: 'Vessels' },
  separator: { label: 'Separator/KO Drum', category: 'Vessels' },
  sphere: { label: 'Storage Sphere', category: 'Vessels', isTank: true, variantGroup: 'tank' },
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
  hydrogenTank: { label: 'Hydrogen Storage Tank', category: 'Hydrogen & Fuel Cell', isTank: true, variantGroup: 'tank' },
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
  drum: { label: 'Drum/Accumulator', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  agitator: { label: 'Agitator/Impeller', category: 'Equipment', isRotating: true },
  vfd: { label: 'VFD (Variable Frequency Drive)', category: 'Electrical' },
  orificePlate: { label: 'Orifice Plate', category: 'Instruments' },
  diaphragmValve: { label: 'Diaphragm Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  plugValve: { label: 'Plug Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  pressureRegulator: { label: 'Pressure Regulator', category: 'Valves', isValve: true, variantGroup: 'valve' },
  centrifuge: { label: 'Centrifuge', category: 'Equipment', isRotating: true },
  evaporator: { label: 'Evaporator', category: 'Heat Exchangers', variantGroup: 'hx' },
  scrubber: { label: 'Scrubber', category: 'Vessels' },
  absorber: { label: 'Absorber Tower', category: 'Vessels' },
  diaphragmPump: { label: 'Diaphragm Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  gearPump: { label: 'Gear Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  axialFan: { label: 'Axial Fan', category: 'Equipment', isRotating: true, variantGroup: 'fan' },
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
  steamTrap: { label: 'Steam Trap', category: 'Piping' },
  damper: { label: 'Damper', category: 'Valves', isValve: true, variantGroup: 'valve' },
  desuperheater: { label: 'Desuperheater', category: 'Equipment' },
  silencer: { label: 'Silencer/Muffler', category: 'Equipment' },
  // --- Additional Valves ---
  globeValve: { label: 'Globe Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  angleValve: { label: 'Angle Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  stopCheckValve: { label: 'Stop-Check Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  reducingValve: { label: 'Pressure Reducing Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  poweredValve: { label: 'Motor-Operated Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  floatValve: { label: 'Float-Operated Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  threeWayPlugValve: { label: '3-Way Plug Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  wedgeGateValve: { label: 'Wedge Gate Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  flangedValve: { label: 'Flanged Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  reliefAngleValve: { label: 'Angle Relief Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  screwDownValve: { label: 'Screw-Down Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  mixingValve: { label: 'Mixing Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  characterPortValve: { label: 'Characterized Port Valve', category: 'Valves', isValve: true, variantGroup: 'valve' },
  // --- Additional Pumps ---
  inlinePump: { label: 'In-Line Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  reciprocatingPump: { label: 'Reciprocating Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  rotaryPump: { label: 'Rotary Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  positiveDisplacementPump: { label: 'PD Pump (Generic)', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  proportioningPump: { label: 'Proportioning/Metering Pump', category: 'Equipment', isRotating: true, variantGroup: 'pump' },
  centrifugalFan: { label: 'Centrifugal Fan', category: 'Equipment', isRotating: true, variantGroup: 'fan' },
  rotaryCompressor: { label: 'Rotary Compressor', category: 'Equipment', isRotating: true },
  ejectorInjector: { label: 'Ejector/Injector', category: 'Equipment' },
  motorDrivenTurbine: { label: 'Motor-Driven Turbine', category: 'Power Generation', isRotating: true },
  compressorTurbine: { label: 'Compressor/Turbine', category: 'Power Generation', isRotating: true },
  sprayHead: { label: 'Spray Head', category: 'Equipment' },
  // --- Additional Heat Exchangers ---
  shellAndTubeHX: { label: 'Shell & Tube HX', category: 'Heat Exchangers', variantGroup: 'hx' },
  kettleReboiler: { label: 'Kettle Reboiler', category: 'Heat Exchangers', variantGroup: 'hx' },
  firedHeater: { label: 'Fired Heater', category: 'Heating & Combustion' },
  coolingTower: { label: 'Cooling Tower', category: 'Heat Exchangers' },
  doublePipeHX: { label: 'Double Pipe HX', category: 'Heat Exchangers', variantGroup: 'hx' },
  finnedTubeHX: { label: 'Finned Tube HX', category: 'Heat Exchangers', variantGroup: 'hx' },
  autoclaveHX: { label: 'Autoclave', category: 'Heat Exchangers' },
  evaporativeCondenser: { label: 'Evaporative Condenser', category: 'Heat Exchangers', variantGroup: 'hx' },
  oilBurner: { label: 'Oil Burner', category: 'Heating & Combustion' },
  oilSeparator: { label: 'Oil Separator', category: 'Vessels' },
  extractorHood: { label: 'Extractor Hood', category: 'Equipment' },
  refrigerator: { label: 'Refrigerator', category: 'Heat Exchangers' },
  // --- Additional Vessels ---
  openTank: { label: 'Open Tank', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  closedTank: { label: 'Closed Tank', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  coveredTank: { label: 'Covered/Floating Roof Tank', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  gasHolder: { label: 'Gas Holder', category: 'Vessels', isTank: true },
  gasCylinder: { label: 'Gas Cylinder', category: 'Vessels' },
  barrel: { label: 'Barrel/Drum', category: 'Vessels' },
  trayColumn: { label: 'Tray Column', category: 'Vessels' },
  clarifier: { label: 'Clarifier', category: 'Vessels' },
  reactionVessel: { label: 'Reaction Vessel', category: 'Vessels', isTank: true },
  vessel: { label: 'Vessel (Generic)', category: 'Vessels', isTank: true, variantGroup: 'tank' },
  fluidContacting: { label: 'Fluid Contacting Column', category: 'Vessels' },
  // --- Additional Instruments ---
  plcController: { label: 'PLC Controller', category: 'Instruments' },
  dcsComputer: { label: 'DCS Computer', category: 'Instruments' },
  rotameter: { label: 'Rotameter', category: 'Instruments' },
  venturiElement: { label: 'Venturi Element', category: 'Instruments' },
  andGate: { label: 'AND Gate', category: 'Logic' },
  orGate: { label: 'OR Gate', category: 'Logic' },
  notGate: { label: 'NOT Gate', category: 'Logic' },
  indicatorRecorder: { label: 'Indicator/Recorder (IR)', category: 'Instruments' },
  signalConverter: { label: 'Signal Converter', category: 'Instruments' },
  operatorStation: { label: 'Operator Station (HC)', category: 'Instruments' },
  thermometer: { label: 'Thermometer', category: 'Instruments' },
  levelMeter: { label: 'Level Meter', category: 'Instruments' },
  indicatorLight: { label: 'Indicator Light', category: 'Instruments' },
  propellerMeter: { label: 'Propeller/Turbine Meter', category: 'Instruments' },
  vortexSensor: { label: 'Vortex Sensor', category: 'Instruments' },
  genericIndicator: { label: 'Generic Indicator', category: 'Instruments' },
  crtDisplay: { label: 'CRT Display', category: 'Instruments' },
  correctingElement: { label: 'Final Control Element', category: 'Instruments' },
  diamondSymbol: { label: 'Diamond (Modifier)', category: 'Instruments' },
  flowmeterGeneric: { label: 'Flowmeter (Generic)', category: 'Instruments' },
  pressureGauges: { label: 'Pressure Gauge (Dial)', category: 'Instruments' },
  // --- Additional Equipment ---
  ballMill: { label: 'Ball Mill', category: 'Equipment', isRotating: true },
  jawCrusher: { label: 'Jaw Crusher', category: 'Equipment' },
  vibratingScreen: { label: 'Vibrating Screen', category: 'Equipment' },
  screwConveyor: { label: 'Screw Conveyor', category: 'Equipment' },
  bucketElevator: { label: 'Bucket Elevator', category: 'Equipment' },
  kneaderMixer: { label: 'Kneader', category: 'Equipment' },
  blenderVessel: { label: 'Blender', category: 'Equipment' },
  rotaryFilter: { label: 'Rotary Filter', category: 'Equipment', isRotating: true },
  prillTower: { label: 'Prill Tower', category: 'Equipment' },
  briquettingMachine: { label: 'Briquetting Machine', category: 'Equipment' },
  scraperConveyor: { label: 'Scraper Conveyor', category: 'Equipment' },
  skipHoist: { label: 'Skip Hoist', category: 'Equipment' },
  overheadConveyor: { label: 'Overhead Conveyor', category: 'Equipment' },
  hoist: { label: 'Hoist', category: 'Equipment' },
  electricMotor: { label: 'Electric Motor', category: 'Equipment', isRotating: true },
  tankTruck: { label: 'Tank Truck', category: 'Equipment' },
  tankCar: { label: 'Tank Car', category: 'Equipment' },
  rollCrusher: { label: 'Roll Crusher', category: 'Equipment', isRotating: true },
  hammerCrusher: { label: 'Hammer Crusher', category: 'Equipment', isRotating: true },
  // --- Additional Fittings & Safety ---
  yStrainer: { label: 'Y-Strainer', category: 'Miscellaneous' },
  burstingDisc: { label: 'Bursting Disc', category: 'Miscellaneous' },
  exhaustHead: { label: 'Exhaust Head/Vent', category: 'Piping' },
  openVent: { label: 'Open Vent', category: 'Piping' },
  bellMouth: { label: 'Bell Mouth Inlet', category: 'Piping' },
  valveManifold: { label: 'Valve Manifold', category: 'Piping' },
  exhaustSilencer: { label: 'Exhaust Silencer', category: 'Equipment' },
  hydrant: { label: 'Fire Hydrant', category: 'Miscellaneous' },
  tundish: { label: 'Tundish', category: 'Miscellaneous' },
  liquidSealPot: { label: 'Liquid Seal Pot', category: 'Miscellaneous' },
  syphonDrain: { label: 'Syphon Drain', category: 'Piping' },
  drainSilencer: { label: 'Drain Silencer', category: 'Equipment' },
  electricallyBonded: { label: 'Electrically Bonded', category: 'Piping' },
  electricallyInsulated: { label: 'Electrically Insulated', category: 'Piping' },
  endCap: { label: 'End Cap', category: 'Piping' },
  // --- Joints ---
  buttWeldJoint: { label: 'Butt Weld', category: 'Joints' },
  flangedJoint: { label: 'Flanged/Bolted Joint', category: 'Joints' },
  screwedJoint: { label: 'Screwed Joint', category: 'Joints' },
  socketWeldJoint: { label: 'Socket Weld', category: 'Joints' },
  swivelJoint: { label: 'Swivel Joint', category: 'Joints' },
  // --- Additional Piping ---
  jacketedPipe: { label: 'Jacketed Pipeline', category: 'Piping' },
  tracedPipe: { label: 'Heat Traced Pipeline', category: 'Piping' },
  futurePipe: { label: 'Future Pipeline', category: 'Piping' },
  connectionPoint: { label: 'Connection Point', category: 'Piping' },
  crossover: { label: 'Pipe Crossover', category: 'Piping' },
  pneumaticConveying: { label: 'Pneumatic Conveying Line', category: 'Piping' },
  majorPipeline: { label: 'Major Pipeline', category: 'Piping' },
  // --- Annotations ---
  calloutBox: { label: 'Callout Box', category: 'Annotations' },
  offSheetLabel: { label: 'Off-Sheet Label', category: 'Annotations' },
  interfacePoint: { label: 'Interface Point', category: 'Annotations' },
  // --- ISA 5.1 Instrument Balloons ---
  isaFieldInstrument: { label: 'Field Instrument', category: 'Instruments' },
  isaPanelInstrument: { label: 'Panel Instrument', category: 'Instruments' },
  isaBehindPanelInstrument: { label: 'Behind-Panel Instrument', category: 'Instruments' },
  isaLocalPanelInstrument: { label: 'Local Panel Instrument', category: 'Instruments' },
  isaDCSFunction: { label: 'DCS Function', category: 'Instruments' },
  isaPLCFunction: { label: 'PLC Function', category: 'Instruments' },
  isaSharedDisplay: { label: 'Shared Display', category: 'Instruments' },
  isaFunctionBlock: { label: 'ISA Function Block', category: 'Instruments' },
}

/**
 * Categories whose symbols render nozzle stubs on ports.
 * Equipment-type symbols get stubs; inline components (valves, instruments,
 * piping, connectors) do not.
 */
export const NOZZLE_STUB_CATEGORIES: ReadonlySet<string> = new Set([
  'Equipment',
  'Heat Exchangers',
  'Vessels',
  'Heating & Combustion',
  'Power Generation',
  'Hydrogen & Fuel Cell',
  'Gasification & Biomass',
])

// Off-page connector symbol types (for special label rendering + page navigation)
export const OFF_PAGE_CONNECTOR_TYPES: ReadonlySet<string> = new Set([
  'offPageRight', 'offPageLeft', 'offPageTo', 'offPageFrom',
])

// Symbol catalog entry for the symbol panel UI
export interface PidSymbolEntry {
  type: ScadaSymbolType
  name: string
  category: string
}

// Derive symbol catalog from SYMBOL_INFO (single source of truth)
export function getSymbolCatalog(): PidSymbolEntry[] {
  return (Object.entries(SYMBOL_INFO) as [ScadaSymbolType, SymbolInfoEntry][])
    .map(([type, info]) => ({ type, name: info.label, category: info.category }))
}

// Type guard for built-in SCADA symbols
export function isScadaSymbol(type: string): type is ScadaSymbolType {
  return type in SCADA_SYMBOLS
}

// Get variant group members for a given symbol type
export function getVariantGroup(type: string): { type: ScadaSymbolType; label: string }[] {
  if (!isScadaSymbol(type)) return []
  const group = SYMBOL_INFO[type].variantGroup
  if (!group) return []
  return (Object.entries(SYMBOL_INFO) as [ScadaSymbolType, SymbolInfoEntry][])
    .filter(([, info]) => info.variantGroup === group)
    .map(([t, info]) => ({ type: t, label: info.label }))
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
  // Valves — stubs extend to viewBox edges, ports correct at x=0/1
  solenoidValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  controlValve: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  manualValve: [
    { id: 'inlet', x: 0, y: 0.556, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.556, direction: 'right', label: 'Out' },
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
    { id: 'vent', x: 0.5, y: 0.06, direction: 'top', label: 'Vent' },
  ],
  threeWayValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet1', x: 1, y: 0.5, direction: 'right', label: 'Out1' },
    { id: 'outlet2', x: 0.5, y: 1, direction: 'bottom', label: 'Out2' },
  ],
  gateValve: [
    { id: 'inlet', x: 0, y: 0.556, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.556, direction: 'right', label: 'Out' },
  ],
  needleValve: [
    { id: 'inlet', x: 0, y: 0.556, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.556, direction: 'right', label: 'Out' },
  ],

  // Instruments — stubs extend to viewBox edges
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
    // viewBox 50x50, stubs at x=10-16 and x=34-40 at y=40-50
    { id: 'inlet', x: 0.26, y: 1, direction: 'bottom', label: 'In' },
    { id: 'outlet', x: 0.74, y: 1, direction: 'bottom', label: 'Out' },
  ],
  phSensor: [
    // viewBox 40x55, probe rect ends at y=50, circle at y=45
    { id: 'process', x: 0.5, y: 0.909, direction: 'bottom', label: 'Process' },
  ],
  conductivitySensor: [
    // viewBox 40x55, probe rect ends at y=50
    { id: 'process', x: 0.5, y: 0.909, direction: 'bottom', label: 'Process' },
  ],
  pressureGauge: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  temperatureIndicator: [
    // viewBox 35x55, stub x=14-20 center x=17, rect ends at y=54
    { id: 'process', x: 0.486, y: 0.982, direction: 'bottom', label: 'Process' },
  ],

  // Equipment — ports aligned to stub centers/edges
  pump: [
    // viewBox 50x40, discharge stub x=21-29 center x=25/50=0.5
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 0.5, y: 0, direction: 'top', label: 'Discharge' },
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
    // viewBox 50x50, circle cx=28 r=18, right edge x=46
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 0.92, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  motor: [
    // viewBox 60x35, shaft coupling rect ends at x=57
    { id: 'shaft', x: 0.95, y: 0.486, direction: 'right', label: 'Shaft' },
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

  // Heat Exchangers — ports at equipment surface
  heatExchanger: [
    // viewBox 80x50, left ellipse edge x=2, right edge x=78, lines at y=5 and y=45
    { id: 'shell_in', x: 0.025, y: 0.5, direction: 'left', label: 'Shell In' },
    { id: 'shell_out', x: 0.975, y: 0.5, direction: 'right', label: 'Shell Out' },
    { id: 'tube_in', x: 0.25, y: 0.1, direction: 'top', label: 'Tube In' },
    { id: 'tube_out', x: 0.75, y: 0.9, direction: 'bottom', label: 'Tube Out' },
  ],
  plateHeatExchanger: [
    // viewBox 50x60, left stub y=8-14 center=11, right stub y=46-52 center=49
    { id: 'hot_in', x: 0, y: 0.183, direction: 'left', label: 'Hot In' },
    { id: 'cold_out', x: 1, y: 0.817, direction: 'right', label: 'Cold Out' },
  ],
  condenser: [
    // viewBox 70x50, left ellipse edge x=2, right edge x=68
    { id: 'vapor_in', x: 0.5, y: 0, direction: 'top', label: 'Vapor In' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
    { id: 'coolant_in', x: 0.029, y: 0.5, direction: 'left', label: 'Coolant In' },
    { id: 'coolant_out', x: 0.971, y: 0.5, direction: 'right', label: 'Coolant Out' },
  ],
  airCooler: [
    // viewBox 70x45, tube bundle rect x=5-65 at y=25-40
    { id: 'inlet', x: 0.071, y: 0.722, direction: 'left', label: 'In' },
    { id: 'outlet', x: 0.929, y: 0.722, direction: 'right', label: 'Out' },
  ],

  // Vessels — ports at vessel wall
  tank: [
    // viewBox 60x80, path x=10-50 y=5-75
    { id: 'inlet', x: 0.5, y: 0.063, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 0.938, direction: 'bottom', label: 'Outlet' },
    { id: 'side', x: 0.167, y: 0.5, direction: 'left', label: 'Side' },
  ],
  horizontalTank: [
    // viewBox 80x50, left ellipse edge x=3, right edge x=77, top y=7, bottom y=43
    { id: 'inlet', x: 0.038, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 0.963, y: 0.5, direction: 'right', label: 'Outlet' },
    { id: 'top', x: 0.5, y: 0.14, direction: 'top', label: 'Top' },
    { id: 'bottom', x: 0.5, y: 0.86, direction: 'bottom', label: 'Bottom' },
  ],
  reactor: [
    // viewBox 60x80, path x=10-50 y=5-75, shaft starts at y=0
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'product', x: 0.5, y: 0.938, direction: 'bottom', label: 'Product' },
    { id: 'jacket_in', x: 0.167, y: 0.3, direction: 'left', label: 'Jacket In' },
    { id: 'jacket_out', x: 0.167, y: 0.7, direction: 'left', label: 'Jacket Out' },
  ],
  column: [
    // viewBox 40x100, path x=8-32 y=2-98
    { id: 'feed', x: 0.2, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'overhead', x: 0.5, y: 0.02, direction: 'top', label: 'Overhead' },
    { id: 'bottoms', x: 0.5, y: 0.98, direction: 'bottom', label: 'Bottoms' },
    { id: 'reflux', x: 0.8, y: 0.15, direction: 'right', label: 'Reflux' },
    { id: 'reboiler', x: 0.8, y: 0.85, direction: 'right', label: 'Reboiler' },
  ],
  cyclone: [
    // viewBox 50x70, left stub x=0-7 at y=11-19 center y=15
    { id: 'inlet', x: 0, y: 0.214, direction: 'left', label: 'Inlet' },
    { id: 'gas_out', x: 0.5, y: 0, direction: 'top', label: 'Gas Out' },
    { id: 'solids_out', x: 0.5, y: 0.929, direction: 'bottom', label: 'Solids' },
  ],
  separator: [
    // viewBox 60x70, vapor stub y=8-16 center=12
    { id: 'inlet', x: 0, y: 0.486, direction: 'left', label: 'Inlet' },
    { id: 'vapor_out', x: 1, y: 0.171, direction: 'right', label: 'Vapor' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid' },
  ],
  sphere: [
    // viewBox 60x65, circle top at y=3, base line at y=62
    { id: 'inlet', x: 0.5, y: 0.046, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 0.954, direction: 'bottom', label: 'Outlet' },
  ],

  // Piping components — fill viewBox edges
  pipeHorizontal: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  pipeVertical: [
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  elbow90: [
    // viewBox 35x35, pipe center at x=10, y=25
    { id: 'vertical', x: 0.286, y: 0, direction: 'top' },
    { id: 'horizontal', x: 1, y: 0.714, direction: 'right' },
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
    { id: 'vent', x: 0.5, y: 0.08, direction: 'top', label: 'Vent' },
  ],
  flameArrestor: [
    { id: 'inlet', x: 0, y: 0.486, direction: 'left' },
    { id: 'outlet', x: 1, y: 0.486, direction: 'right' },
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
    // viewBox 60x40, top stub x=22-30 center x=26
    { id: 'motive', x: 0, y: 0.5, direction: 'left', label: 'Motive' },
    { id: 'suction', x: 0.433, y: 0, direction: 'top', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],

  // Hydrogen & Fuel Cell
  fuelCell: [
    // viewBox 70x60, left stubs at y=20-28 (center 24) and y=36-44 (center 40)
    { id: 'h2_in', x: 0, y: 0.4, direction: 'left', label: 'H2 In' },
    { id: 'air_in', x: 0, y: 0.667, direction: 'left', label: 'Air In' },
    { id: 'exhaust1', x: 1, y: 0.4, direction: 'right', label: 'Exhaust' },
    { id: 'exhaust2', x: 1, y: 0.667, direction: 'right', label: 'H2O Out' },
  ],
  electrolyzer: [
    // viewBox 60x70, top stubs center x=22 and x=38
    { id: 'water_in', x: 0.5, y: 1, direction: 'bottom', label: 'H2O In' },
    { id: 'h2_out', x: 0.367, y: 0, direction: 'top', label: 'H2 Out' },
    { id: 'o2_out', x: 0.633, y: 0, direction: 'top', label: 'O2 Out' },
  ],
  steamReformer: [
    // viewBox 70x80, left stubs center y=21 and y=31
    { id: 'ch4_in', x: 0, y: 0.263, direction: 'left', label: 'CH4 In' },
    { id: 'steam_in', x: 0, y: 0.388, direction: 'left', label: 'Steam In' },
    { id: 'h2_out', x: 1, y: 0.263, direction: 'right', label: 'H2 Out' },
    { id: 'flue', x: 0.5, y: 1, direction: 'bottom', label: 'Flue' },
  ],
  hydrogenTank: [
    { id: 'connection', x: 0.5, y: 0, direction: 'top', label: 'H2' },
  ],
  fuelDispenser: [
    { id: 'supply', x: 0.5, y: 1, direction: 'bottom', label: 'Supply' },
    // hose runs along x=50 from y=35 to y=55, center at y=45
    { id: 'hose', x: 1, y: 0.786, direction: 'right', label: 'Hose' },
  ],

  // Gasification & Biomass
  gasifier: [
    // viewBox 60x90, left stub center y=33, right stub center y=28, bottom path at y=80
    { id: 'feed', x: 0, y: 0.367, direction: 'left', label: 'Feed' },
    { id: 'air', x: 1, y: 0.311, direction: 'right', label: 'Air/O2' },
    { id: 'syngas', x: 0.5, y: 0, direction: 'top', label: 'Syngas' },
    { id: 'ash', x: 0.5, y: 0.889, direction: 'bottom', label: 'Ash' },
  ],
  syngasCleanup: [
    // viewBox 50x80, right stub center y=21, left stub center y=63
    { id: 'gas_in', x: 1, y: 0.263, direction: 'right', label: 'Dirty Gas' },
    { id: 'gas_out', x: 0, y: 0.788, direction: 'left', label: 'Clean Gas' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  hopper: [
    // viewBox 50x70, polygon top at y=5
    { id: 'feed', x: 0.5, y: 0.071, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],

  // Heating & Combustion
  boiler: [
    { id: 'feedwater', x: 0, y: 0.5, direction: 'left', label: 'Feedwater' },
    { id: 'steam', x: 0.5, y: 0, direction: 'top', label: 'Steam' },
    { id: 'blowdown', x: 1, y: 0.5, direction: 'right', label: 'Blowdown' },
  ],
  furnace: [
    // viewBox 70x60, left/right stubs center y=26
    { id: 'fuel', x: 0, y: 0.433, direction: 'left', label: 'Fuel' },
    { id: 'air', x: 0.5, y: 0, direction: 'top', label: 'Air' },
    { id: 'exhaust', x: 1, y: 0.433, direction: 'right', label: 'Exhaust' },
  ],
  burner: [
    // viewBox 50x50, left stub center y=30
    { id: 'fuel', x: 0, y: 0.6, direction: 'left', label: 'Fuel' },
    { id: 'air', x: 0.5, y: 0, direction: 'top', label: 'Air' },
  ],
  coil: [
    // viewBox 60x50, left stub center y=15, right stub center y=35
    { id: 'inlet', x: 0, y: 0.3, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.7, direction: 'right', label: 'Outlet' },
  ],
  waterHeater: [
    // viewBox 45x70, top stubs center x=15 and x=31
    { id: 'cold_in', x: 0.333, y: 0, direction: 'top', label: 'Cold In' },
    { id: 'hot_out', x: 0.689, y: 0, direction: 'top', label: 'Hot Out' },
    { id: 'drain', x: 0.511, y: 1, direction: 'bottom', label: 'Drain' },
  ],

  // Power Generation
  chpUnit: [
    // viewBox 80x60, right stubs center y=21 and y=39
    { id: 'fuel', x: 0, y: 0.483, direction: 'left', label: 'Fuel' },
    { id: 'exhaust', x: 0.275, y: 0, direction: 'top', label: 'Exhaust' },
    { id: 'heat_supply', x: 1, y: 0.35, direction: 'right', label: 'Heat Supply' },
    { id: 'heat_return', x: 1, y: 0.65, direction: 'right', label: 'Heat Return' },
  ],
  turbine: [
    // viewBox 70x50, LP section right edge at x=58
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Steam/Gas In' },
    { id: 'exhaust', x: 0.829, y: 0.5, direction: 'right', label: 'Exhaust' },
    { id: 'shaft', x: 1, y: 0.5, direction: 'right', label: 'Shaft' },
  ],
  generator: [
    // viewBox 60x50, right stubs center y=18 and y=32
    { id: 'shaft', x: 0, y: 0.5, direction: 'left', label: 'Shaft' },
    { id: 'power_pos', x: 1, y: 0.36, direction: 'right', label: '+' },
    { id: 'power_neg', x: 1, y: 0.64, direction: 'right', label: '-' },
  ],

  // Off-Page Connectors
  offPageRight: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left' },
  ],
  offPageLeft: [
    { id: 'outlet', x: 1, y: 0.5, direction: 'right' },
  ],
  offPageTo: [
    // viewBox 50x50, pentagon top vertex at y=5
    { id: 'connection', x: 0.5, y: 0.1, direction: 'top' },
  ],
  offPageFrom: [
    // viewBox 50x50, pentagon bottom vertex at y=45
    { id: 'connection', x: 0.5, y: 0.9, direction: 'bottom' },
  ],
  flowArrowRight: [
    // viewBox 50x30, line starts at x=5, arrow tip at x=48
    { id: 'tail', x: 0.1, y: 0.5, direction: 'left' },
    { id: 'head', x: 0.96, y: 0.5, direction: 'right' },
  ],
  flowArrowLeft: [
    // viewBox 50x30, arrow tip at x=2, line ends at x=45
    { id: 'head', x: 0.04, y: 0.5, direction: 'left' },
    { id: 'tail', x: 0.9, y: 0.5, direction: 'right' },
  ],
  flowArrowDown: [
    // viewBox 30x50, line starts at y=5, arrow tip at y=48
    { id: 'tail', x: 0.5, y: 0.1, direction: 'top' },
    { id: 'head', x: 0.5, y: 0.96, direction: 'bottom' },
  ],
  flowArrowUp: [
    // viewBox 30x50, arrow tip at y=2, line ends at y=45
    { id: 'head', x: 0.5, y: 0.04, direction: 'top' },
    { id: 'tail', x: 0.5, y: 0.9, direction: 'bottom' },
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
    // viewBox 60x45, stubs at y=25-33 center=29
    { id: 'inlet', x: 0, y: 0.644, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.644, direction: 'right', label: 'Out' },
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
    // viewBox 60x60, circle cx=30 r=22, left edge x=8, right edge x=52
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'light', x: 0.133, y: 0.583, direction: 'left', label: 'Light' },
    { id: 'heavy', x: 0.867, y: 0.583, direction: 'right', label: 'Heavy' },
  ],
  evaporator: [
    // viewBox 60x70, left stub x=5-10 center=(7.5,26), right stub x=50-55
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'concentrate', x: 0.5, y: 1, direction: 'bottom', label: 'Concentrate' },
    { id: 'steam_in', x: 0.083, y: 0.371, direction: 'left', label: 'Steam In' },
    { id: 'condensate', x: 0.917, y: 0.371, direction: 'right', label: 'Condensate' },
  ],
  scrubber: [
    // viewBox 50x80, left stub center y=63, right stub center y=33
    { id: 'gas_in', x: 0, y: 0.788, direction: 'left', label: 'Gas In' },
    { id: 'gas_out', x: 1, y: 0.413, direction: 'right', label: 'Gas Out' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
  ],
  absorber: [
    // viewBox 50x90, left stub center y=48, right stub center y=28, body bottom ~y=85
    { id: 'gas_in', x: 0, y: 0.533, direction: 'left', label: 'Gas In' },
    { id: 'liquid_in', x: 1, y: 0.311, direction: 'right', label: 'Liquid In' },
    { id: 'gas_out', x: 0.5, y: 0, direction: 'top', label: 'Gas Out' },
    { id: 'liquid_out', x: 0.5, y: 0.944, direction: 'bottom', label: 'Liquid Out' },
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
    // viewBox 50x50, circle cx=25 r=22, left edge x=3, right edge x=47
    { id: 'inlet', x: 0.06, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 0.94, y: 0.5, direction: 'right', label: 'Outlet' },
  ],
  loadCell: [
    { id: 'process', x: 0.5, y: 0, direction: 'top', label: 'Load' },
  ],
  vibrationSensor: [
    // viewBox 40x50, mounting base rect bottom at y=46
    { id: 'process', x: 0.5, y: 0.92, direction: 'bottom', label: 'Mount' },
  ],
  spectacleBlind: [
    // viewBox 60x30, left circle edge x=3, right circle edge x=57
    { id: 'left', x: 0.05, y: 0.5, direction: 'left' },
    { id: 'right', x: 0.95, y: 0.5, direction: 'right' },
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
    // viewBox 80x30, left circle edge x=4, right circle edge x=76
    { id: 'inlet', x: 0.05, y: 0.6, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 0.95, y: 0.6, direction: 'right', label: 'Discharge' },
  ],
  dryer: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Wet Feed' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Dry Product' },
    { id: 'air', x: 0, y: 0.5, direction: 'left', label: 'Hot Air' },
  ],
  steamTrap: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  damper: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  desuperheater: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'Steam In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Steam Out' },
    { id: 'spray', x: 0.5, y: 0, direction: 'top', label: 'Spray Water' },
  ],
  silencer: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],

  // --- Additional Valves ---
  globeValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  angleValve: [
    { id: 'inlet', x: 0, y: 0.489, direction: 'left', label: 'In' },
    { id: 'outlet', x: 0.489, y: 0, direction: 'top', label: 'Out' },
  ],
  stopCheckValve: [
    { id: 'inlet', x: 0, y: 0.511, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.511, direction: 'right', label: 'Out' },
  ],
  reducingValve: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  poweredValve: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  floatValve: [
    { id: 'inlet', x: 0, y: 0.6, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.6, direction: 'right', label: 'Out' },
  ],
  threeWayPlugValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet1', x: 1, y: 0.5, direction: 'right', label: 'Out1' },
    { id: 'outlet2', x: 0.5, y: 1, direction: 'bottom', label: 'Out2' },
  ],
  wedgeGateValve: [
    { id: 'inlet', x: 0, y: 0.556, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.556, direction: 'right', label: 'Out' },
  ],
  flangedValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  reliefAngleValve: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom', label: 'In' },
    { id: 'vent', x: 0, y: 0.5, direction: 'left', label: 'Vent' },
  ],
  screwDownValve: [
    { id: 'inlet', x: 0, y: 0.556, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.556, direction: 'right', label: 'Out' },
  ],
  mixingValve: [
    { id: 'inlet1', x: 0, y: 0.5, direction: 'left', label: 'In1' },
    { id: 'inlet2', x: 0.5, y: 1, direction: 'bottom', label: 'In2' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  characterPortValve: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],

  // --- Additional Pumps ---
  inlinePump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  reciprocatingPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  rotaryPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  positiveDisplacementPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  proportioningPump: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  centrifugalFan: [
    { id: 'inlet', x: 0, y: 0.1, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
  ],
  rotaryCompressor: [
    { id: 'suction', x: 0, y: 0.5, direction: 'left', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  ejectorInjector: [
    { id: 'motive', x: 0, y: 0.45, direction: 'left', label: 'Motive' },
    { id: 'suction', x: 0.367, y: 0, direction: 'top', label: 'Suction' },
    { id: 'discharge', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  motorDrivenTurbine: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Steam/Gas In' },
    { id: 'shaft', x: 1, y: 0.5, direction: 'right', label: 'Shaft' },
  ],
  compressorTurbine: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  sprayHead: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom', label: 'Inlet' },
  ],

  // --- Additional Heat Exchangers ---
  shellAndTubeHX: [
    { id: 'shell_in', x: 0, y: 0.5, direction: 'left', label: 'Shell In' },
    { id: 'shell_out', x: 1, y: 0.5, direction: 'right', label: 'Shell Out' },
    { id: 'tube_in', x: 0.375, y: 0, direction: 'top', label: 'Tube In' },
    { id: 'tube_out', x: 0.563, y: 1, direction: 'bottom', label: 'Tube Out' },
  ],
  kettleReboiler: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Outlet' },
    { id: 'vapor', x: 0.75, y: 0, direction: 'top', label: 'Vapor' },
  ],
  firedHeater: [
    { id: 'inlet', x: 0, y: 0.283, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.283, direction: 'right', label: 'Out' },
  ],
  coolingTower: [
    { id: 'water_in', x: 0, y: 0.8, direction: 'left', label: 'Warm Water In' },
    { id: 'water_out', x: 1, y: 0.8, direction: 'right', label: 'Cool Water Out' },
    { id: 'air_out', x: 0.5, y: 0, direction: 'top', label: 'Air Out' },
  ],
  doublePipeHX: [
    { id: 'outer_in', x: 0, y: 0.375, direction: 'left', label: 'Outer In' },
    { id: 'outer_out', x: 1, y: 0.375, direction: 'right', label: 'Outer Out' },
    { id: 'inner_in', x: 0, y: 0.625, direction: 'left', label: 'Inner In' },
    { id: 'inner_out', x: 1, y: 0.625, direction: 'right', label: 'Inner Out' },
  ],
  finnedTubeHX: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  autoclaveHX: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  evaporativeCondenser: [
    { id: 'vapor_in', x: 0.5, y: 0, direction: 'top', label: 'Vapor In' },
    { id: 'liquid_out', x: 0.5, y: 1, direction: 'bottom', label: 'Liquid Out' },
    { id: 'water_in', x: 0, y: 0.467, direction: 'left', label: 'Water In' },
    { id: 'water_out', x: 1, y: 0.467, direction: 'right', label: 'Water Out' },
  ],
  oilBurner: [
    { id: 'fuel', x: 0, y: 0.6, direction: 'left', label: 'Fuel' },
    { id: 'air', x: 0.5, y: 0.1, direction: 'top', label: 'Air' },
    { id: 'exhaust', x: 1, y: 0.6, direction: 'right', label: 'Exhaust' },
  ],
  oilSeparator: [
    { id: 'inlet', x: 0, y: 0.333, direction: 'left', label: 'Inlet' },
    { id: 'oil_out', x: 1, y: 0.25, direction: 'right', label: 'Oil Out' },
    { id: 'water_out', x: 1, y: 0.667, direction: 'right', label: 'Water Out' },
  ],
  extractorHood: [
    { id: 'exhaust', x: 0.5, y: 0, direction: 'top', label: 'Exhaust' },
  ],
  refrigerator: [
    { id: 'inlet1', x: 0, y: 0.4, direction: 'left', label: 'In 1' },
    { id: 'outlet1', x: 1, y: 0.4, direction: 'right', label: 'Out 1' },
    { id: 'inlet2', x: 0, y: 0.6, direction: 'left', label: 'In 2' },
    { id: 'outlet2', x: 1, y: 0.6, direction: 'right', label: 'Out 2' },
  ],

  // --- Additional Vessels ---
  openTank: [
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
    { id: 'side', x: 0, y: 0.5, direction: 'left', label: 'Side' },
  ],
  closedTank: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
    { id: 'side', x: 0, y: 0.462, direction: 'left', label: 'Side' },
  ],
  coveredTank: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
    { id: 'side', x: 0, y: 0.5, direction: 'left', label: 'Side' },
  ],
  gasHolder: [
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
  ],
  gasCylinder: [
    { id: 'valve', x: 0.5, y: 0, direction: 'top', label: 'Valve' },
  ],
  barrel: [],
  trayColumn: [
    { id: 'feed', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'overhead', x: 0.5, y: 0, direction: 'top', label: 'Overhead' },
    { id: 'bottoms', x: 0.5, y: 1, direction: 'bottom', label: 'Bottoms' },
    { id: 'reflux', x: 1, y: 0.18, direction: 'right', label: 'Reflux' },
    { id: 'reboiler', x: 1, y: 0.82, direction: 'right', label: 'Reboiler' },
  ],
  clarifier: [
    { id: 'inlet', x: 0, y: 0.4, direction: 'left', label: 'Inlet' },
    { id: 'overflow', x: 1, y: 0.4, direction: 'right', label: 'Overflow' },
    { id: 'underflow', x: 0.5, y: 1, direction: 'bottom', label: 'Underflow' },
  ],
  reactionVessel: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'product', x: 0.5, y: 1, direction: 'bottom', label: 'Product' },
    { id: 'jacket_in', x: 0, y: 0.313, direction: 'left', label: 'Jacket In' },
    { id: 'jacket_out', x: 0, y: 0.625, direction: 'left', label: 'Jacket Out' },
  ],
  vessel: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Outlet' },
    { id: 'side_left', x: 0, y: 0.5, direction: 'left', label: 'Left' },
    { id: 'side_right', x: 1, y: 0.5, direction: 'right', label: 'Right' },
  ],
  fluidContacting: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Inlet' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Outlet' },
  ],

  // --- Additional Instruments ---
  plcController: [
    { id: 'io1', x: 0.3, y: 1, direction: 'bottom', label: 'I/O 1' },
    { id: 'io2', x: 0.5, y: 1, direction: 'bottom', label: 'I/O 2' },
    { id: 'io3', x: 0.7, y: 1, direction: 'bottom', label: 'I/O 3' },
  ],
  dcsComputer: [
    { id: 'signal', x: 0.5, y: 1, direction: 'bottom', label: 'Signal' },
  ],
  rotameter: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'In' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Out' },
  ],
  venturiElement: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
    { id: 'tap', x: 0.5, y: 0, direction: 'top', label: 'Tap' },
  ],
  andGate: [
    { id: 'in1', x: 0, y: 0.333, direction: 'left', label: 'A' },
    { id: 'in2', x: 0, y: 0.667, direction: 'left', label: 'B' },
    { id: 'out', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  orGate: [
    { id: 'in1', x: 0, y: 0.333, direction: 'left', label: 'A' },
    { id: 'in2', x: 0, y: 0.667, direction: 'left', label: 'B' },
    { id: 'out', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  notGate: [
    { id: 'in', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'out', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  indicatorRecorder: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  signalConverter: [
    { id: 'input', x: 0, y: 0.425, direction: 'left', label: 'Input' },
    { id: 'output', x: 1, y: 0.425, direction: 'right', label: 'Output' },
  ],
  operatorStation: [
    { id: 'signal', x: 0.5, y: 1, direction: 'bottom', label: 'Signal' },
  ],
  thermometer: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  levelMeter: [
    { id: 'top', x: 0.5, y: 0, direction: 'top', label: 'Top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom', label: 'Bottom' },
  ],
  indicatorLight: [
    { id: 'signal', x: 0.5, y: 1, direction: 'bottom', label: 'Signal' },
  ],
  propellerMeter: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  vortexSensor: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  genericIndicator: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  crtDisplay: [
    { id: 'signal', x: 0.5, y: 1, direction: 'bottom', label: 'Signal' },
  ],
  correctingElement: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],
  diamondSymbol: [],
  flowmeterGeneric: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  pressureGauges: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
  ],

  // --- Additional Equipment ---
  ballMill: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  jawCrusher: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.417, y: 1, direction: 'bottom', label: 'Discharge' },
  ],
  vibratingScreen: [
    { id: 'inlet', x: 0, y: 0.367, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.367, direction: 'right', label: 'Overs' },
  ],
  screwConveyor: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Discharge' },
  ],
  bucketElevator: [
    { id: 'feed', x: 0.5, y: 1, direction: 'bottom', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 0, direction: 'top', label: 'Discharge' },
  ],
  kneaderMixer: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  blenderVessel: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],
  rotaryFilter: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Filtrate' },
  ],
  prillTower: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'product', x: 0.5, y: 1, direction: 'bottom', label: 'Product' },
  ],
  briquettingMachine: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Product' },
  ],
  scraperConveyor: [
    { id: 'inlet', x: 0, y: 0.48, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.48, direction: 'right', label: 'Discharge' },
  ],
  skipHoist: [
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],
  overheadConveyor: [
    { id: 'inlet', x: 0, y: 0.267, direction: 'left', label: 'Feed' },
    { id: 'outlet', x: 1, y: 0.267, direction: 'right', label: 'Discharge' },
  ],
  hoist: [
    { id: 'hook', x: 0.5, y: 1, direction: 'bottom', label: 'Hook' },
  ],
  electricMotor: [
    { id: 'shaft_in', x: 0, y: 0.486, direction: 'left', label: 'Power' },
    { id: 'shaft_out', x: 1, y: 0.486, direction: 'right', label: 'Shaft' },
  ],
  tankTruck: [
    { id: 'connection', x: 0.457, y: 0, direction: 'top', label: 'Connection' },
  ],
  tankCar: [
    { id: 'connection', x: 0.5, y: 0, direction: 'top', label: 'Connection' },
  ],
  rollCrusher: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],
  hammerCrusher: [
    { id: 'feed', x: 0.5, y: 0, direction: 'top', label: 'Feed' },
    { id: 'discharge', x: 0.5, y: 1, direction: 'bottom', label: 'Discharge' },
  ],

  // --- Additional Fittings & Safety ---
  yStrainer: [
    { id: 'inlet', x: 0, y: 0.375, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.375, direction: 'right', label: 'Out' },
  ],
  burstingDisc: [
    { id: 'process', x: 0.5, y: 1, direction: 'bottom', label: 'Process' },
    { id: 'vent', x: 0.5, y: 0, direction: 'top', label: 'Vent' },
  ],
  exhaustHead: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom', label: 'In' },
  ],
  openVent: [
    { id: 'inlet', x: 0.5, y: 1, direction: 'bottom', label: 'In' },
  ],
  bellMouth: [
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  valveManifold: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
    { id: 'branch1', x: 0.25, y: 0, direction: 'top', label: 'V1' },
    { id: 'branch2', x: 0.5, y: 0, direction: 'top', label: 'V2' },
    { id: 'branch3', x: 0.75, y: 0, direction: 'top', label: 'V3' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  exhaustSilencer: [
    { id: 'inlet', x: 0, y: 0.5, direction: 'left', label: 'In' },
    { id: 'outlet', x: 1, y: 0.5, direction: 'right', label: 'Out' },
  ],
  hydrant: [
    { id: 'supply', x: 0.5, y: 1, direction: 'bottom', label: 'Supply' },
  ],
  tundish: [
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  liquidSealPot: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'Inlet' },
    { id: 'left', x: 0, y: 0.444, direction: 'left', label: 'Left' },
    { id: 'right', x: 1, y: 0.444, direction: 'right', label: 'Right' },
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  syphonDrain: [
    { id: 'drain', x: 0.5, y: 1, direction: 'bottom', label: 'Drain' },
  ],
  drainSilencer: [
    { id: 'inlet', x: 0.5, y: 0, direction: 'top', label: 'In' },
    { id: 'outlet', x: 0.5, y: 1, direction: 'bottom', label: 'Out' },
  ],
  electricallyBonded: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  electricallyInsulated: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  endCap: [
    { id: 'connection', x: 0, y: 0.5, direction: 'left' },
  ],

  // --- Joints ---
  buttWeldJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  flangedJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  screwedJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  socketWeldJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  swivelJoint: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],

  // --- Additional Piping ---
  jacketedPipe: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  tracedPipe: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  futurePipe: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  connectionPoint: [],
  crossover: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
    { id: 'top', x: 0.5, y: 0, direction: 'top' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom' },
  ],
  pneumaticConveying: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],
  majorPipeline: [
    { id: 'left', x: 0, y: 0.5, direction: 'left' },
    { id: 'right', x: 1, y: 0.5, direction: 'right' },
  ],

  // --- Annotations ---
  calloutBox: [],
  offSheetLabel: [],
  interfacePoint: [],
  // --- ISA 5.1 Instrument Balloons ---
  isaFieldInstrument: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaPanelInstrument: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaBehindPanelInstrument: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaLocalPanelInstrument: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaDCSFunction: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaPLCFunction: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaSharedDisplay: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
  ],
  isaFunctionBlock: [
    { id: 'left', x: 0, y: 0.5, direction: 'left', label: 'Process' },
    { id: 'right', x: 1, y: 0.5, direction: 'right', label: 'Signal' },
    { id: 'bottom', x: 0.5, y: 1, direction: 'bottom', label: 'Bottom' },
  ],
}

// Rotate a direction label by the given CW degrees (matches CSS transform: rotate())
export function rotateDirection(
  dir: 'left' | 'right' | 'top' | 'bottom',
  degrees: 90 | 180 | 270
): 'left' | 'right' | 'top' | 'bottom' {
  const order: ('top' | 'right' | 'bottom' | 'left')[] = ['top', 'right', 'bottom', 'left']
  const idx = order.indexOf(dir)
  const steps = degrees / 90
  return order[(idx + steps) % 4] as 'left' | 'right' | 'top' | 'bottom'
}

// Rotate a pixel point CW around a center, matching CSS transform: rotate(deg)
export function rotateCW(
  x: number, y: number,
  cx: number, cy: number,
  rotation: 0 | 90 | 180 | 270
): { x: number; y: number } {
  if (rotation === 0) return { x, y }
  const dx = x - cx
  const dy = y - cy
  switch (rotation) {
    case 90:  return { x: cx - dy, y: cy + dx }
    case 180: return { x: cx - dx, y: cy - dy }
    case 270: return { x: cx + dy, y: cy - dx }
  }
}

// Mirror a pixel point around a center (matches CSS transform: scaleX(-1) / scaleY(-1))
export function flipPoint(
  x: number, y: number,
  cx: number, cy: number,
  doFlipX: boolean, doFlipY: boolean
): { x: number; y: number } {
  return {
    x: doFlipX ? cx + (cx - x) : x,
    y: doFlipY ? cy + (cy - y) : y,
  }
}

// Mirror a direction label (left↔right for flipX, top↔bottom for flipY)
export function flipDirection(
  dir: 'left' | 'right' | 'top' | 'bottom',
  doFlipX: boolean, doFlipY: boolean
): 'left' | 'right' | 'top' | 'bottom' {
  let d = dir
  if (doFlipX) {
    if (d === 'left') d = 'right'
    else if (d === 'right') d = 'left'
  }
  if (doFlipY) {
    if (d === 'top') d = 'bottom'
    else if (d === 'bottom') d = 'top'
  }
  return d
}

// Get port position in canvas coordinates.
// Strategy: compute the port's local-div position (with SVG letterbox offset), then flip+rotate
// that pixel position around the div center to match CSS transform order. This ensures
// ports align with the visually rendered SVG edges regardless of aspect ratio, flip, or rotation.
export function getPortPosition(
  symbolType: ScadaSymbolType,
  portId: string,
  widgetX: number,
  widgetY: number,
  widgetW: number,
  widgetH: number,
  rotation: 0 | 90 | 180 | 270 = 0,
  doFlipX: boolean = false,
  doFlipY: boolean = false
): { x: number; y: number; direction: 'left' | 'right' | 'top' | 'bottom' } | null {
  const ports = SYMBOL_PORTS[symbolType]
  const port = ports?.find(p => p.id === portId)
  if (!port) return null

  // Step 1: Map normalized port coords (0-1 in viewBox space) to unrotated local-div pixels,
  // accounting for SVG preserveAspectRatio="xMidYMid meet" letterboxing
  let localX: number, localY: number
  const vb = SYMBOL_VIEWBOX[symbolType]
  if (vb) {
    const svgAR = vb.width / vb.height
    const widgetAR = widgetW / widgetH
    let renderW: number, renderH: number, offsetX: number, offsetY: number
    if (svgAR > widgetAR) {
      renderW = widgetW
      renderH = widgetW / svgAR
      offsetX = 0
      offsetY = (widgetH - renderH) / 2
    } else {
      renderH = widgetH
      renderW = widgetH * svgAR
      offsetX = (widgetW - renderW) / 2
      offsetY = 0
    }
    localX = offsetX + port.x * renderW
    localY = offsetY + port.y * renderH
  } else {
    localX = port.x * widgetW
    localY = port.y * widgetH
  }

  // Step 2: Apply flip then rotate (matching CSS transform order: scaleX scaleY rotate)
  const cx = widgetW / 2, cy = widgetH / 2
  const flipped = flipPoint(localX, localY, cx, cy, doFlipX, doFlipY)
  const rotated = rotateCW(flipped.x, flipped.y, cx, cy, rotation)

  let direction = port.direction
  if (doFlipX || doFlipY) direction = flipDirection(direction, doFlipX, doFlipY)
  if (rotation !== 0) direction = rotateDirection(direction, rotation)

  return {
    x: widgetX + rotated.x,
    y: widgetY + rotated.y,
    direction
  }
}
