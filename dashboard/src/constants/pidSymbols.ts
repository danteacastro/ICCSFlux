import type { ScadaSymbolType } from '../assets/symbols'

export interface PidSymbolEntry {
  type: ScadaSymbolType
  name: string
  category: string
}

export const PID_SYMBOL_CATALOG: PidSymbolEntry[] = [
  // Valves
  { type: 'solenoidValve', name: 'Solenoid Valve', category: 'Valves' },
  { type: 'controlValve', name: 'Control Valve', category: 'Valves' },
  { type: 'ballValve', name: 'Ball Valve', category: 'Valves' },
  { type: 'gateValve', name: 'Gate Valve', category: 'Valves' },
  { type: 'checkValve', name: 'Check Valve', category: 'Valves' },
  { type: 'reliefValve', name: 'Relief Valve', category: 'Valves' },
  { type: 'butterflyValve', name: 'Butterfly Valve', category: 'Valves' },
  { type: 'threeWayValve', name: '3-Way Valve', category: 'Valves' },
  { type: 'needleValve', name: 'Needle Valve', category: 'Valves' },
  { type: 'diaphragmValve', name: 'Diaphragm Valve', category: 'Valves' },
  { type: 'plugValve', name: 'Plug Valve', category: 'Valves' },
  { type: 'pressureRegulator', name: 'Pressure Regulator', category: 'Valves' },
  // Equipment
  { type: 'pump', name: 'Pump (Centrifugal)', category: 'Equipment' },
  { type: 'pdPump', name: 'PD Pump', category: 'Equipment' },
  { type: 'diaphragmPump', name: 'Diaphragm Pump', category: 'Equipment' },
  { type: 'gearPump', name: 'Gear Pump', category: 'Equipment' },
  { type: 'compressor', name: 'Compressor', category: 'Equipment' },
  { type: 'blower', name: 'Blower/Fan', category: 'Equipment' },
  { type: 'axialFan', name: 'Axial Fan', category: 'Equipment' },
  { type: 'motor', name: 'Motor', category: 'Equipment' },
  { type: 'filter', name: 'Filter', category: 'Equipment' },
  { type: 'mixer', name: 'Mixer', category: 'Equipment' },
  { type: 'agitator', name: 'Agitator', category: 'Equipment' },
  { type: 'conveyor', name: 'Conveyor', category: 'Equipment' },
  { type: 'centrifuge', name: 'Centrifuge', category: 'Equipment' },
  { type: 'dryer', name: 'Dryer', category: 'Equipment' },
  // Vessels
  { type: 'tank', name: 'Tank (Vertical)', category: 'Vessels' },
  { type: 'horizontalTank', name: 'Horizontal Tank', category: 'Vessels' },
  { type: 'reactor', name: 'Reactor', category: 'Vessels' },
  { type: 'column', name: 'Column/Tower', category: 'Vessels' },
  { type: 'drum', name: 'Drum/Accumulator', category: 'Vessels' },
  { type: 'cyclone', name: 'Cyclone Separator', category: 'Vessels' },
  { type: 'separator', name: 'Separator/KO Drum', category: 'Vessels' },
  { type: 'scrubber', name: 'Scrubber', category: 'Vessels' },
  { type: 'absorber', name: 'Absorber Tower', category: 'Vessels' },
  // Heat Exchangers
  { type: 'heatExchanger', name: 'Shell & Tube HX', category: 'Heat Exchangers' },
  { type: 'plateHeatExchanger', name: 'Plate Heat Exchanger', category: 'Heat Exchangers' },
  { type: 'heater', name: 'Heater', category: 'Heat Exchangers' },
  { type: 'cooler', name: 'Cooler', category: 'Heat Exchangers' },
  { type: 'condenser', name: 'Condenser', category: 'Heat Exchangers' },
  { type: 'evaporator', name: 'Evaporator', category: 'Heat Exchangers' },
  { type: 'boiler', name: 'Boiler', category: 'Heat Exchangers' },
  { type: 'airCooler', name: 'Air Cooler (Fin Fan)', category: 'Heat Exchangers' },
  // Instruments
  { type: 'pressureTransducer', name: 'Pressure Transmitter', category: 'Instruments' },
  { type: 'temperatureElement', name: 'Temperature Element', category: 'Instruments' },
  { type: 'flowMeter', name: 'Flow Meter', category: 'Instruments' },
  { type: 'levelTransmitter', name: 'Level Transmitter', category: 'Instruments' },
  { type: 'pressureGauge', name: 'Pressure Gauge', category: 'Instruments' },
  { type: 'analyzer', name: 'Analyzer', category: 'Instruments' },
  { type: 'phSensor', name: 'pH Sensor', category: 'Instruments' },
  { type: 'conductivitySensor', name: 'Conductivity Sensor', category: 'Instruments' },
  { type: 'loadCell', name: 'Load Cell/Scale', category: 'Instruments' },
  { type: 'vibrationSensor', name: 'Vibration Sensor', category: 'Instruments' },
  { type: 'orificePlate', name: 'Orifice Plate', category: 'Instruments' },
  // Electrical
  { type: 'vfd', name: 'VFD (Variable Freq Drive)', category: 'Electrical' },
  { type: 'circuitBreaker', name: 'Circuit Breaker', category: 'Electrical' },
  { type: 'transformer', name: 'Transformer', category: 'Electrical' },
  { type: 'powerSupply', name: 'Power Supply', category: 'Electrical' },
  { type: 'generator', name: 'Generator', category: 'Electrical' },
  // Power Generation
  { type: 'turbine', name: 'Turbine', category: 'Power Generation' },
  { type: 'chpUnit', name: 'CHP Unit', category: 'Power Generation' },
  // Piping
  { type: 'flange', name: 'Flange', category: 'Piping' },
  { type: 'reducer', name: 'Reducer', category: 'Piping' },
  { type: 'pipeTee', name: 'Pipe Tee', category: 'Piping' },
  { type: 'elbow90', name: '90\u00B0 Elbow', category: 'Piping' },
  { type: 'strainer', name: 'Strainer', category: 'Piping' },
  { type: 'sightGlass', name: 'Sight Glass', category: 'Piping' },
  // Connectors
  { type: 'flowArrowRight', name: 'Flow Arrow \u2192', category: 'Connectors' },
  { type: 'flowArrowLeft', name: 'Flow Arrow \u2190', category: 'Connectors' },
  { type: 'flowArrowDown', name: 'Flow Arrow \u2193', category: 'Connectors' },
  { type: 'flowArrowUp', name: 'Flow Arrow \u2191', category: 'Connectors' },
  { type: 'offPageRight', name: 'Off-Page \u2192', category: 'Connectors' },
  { type: 'offPageLeft', name: 'Off-Page \u2190', category: 'Connectors' },
]
