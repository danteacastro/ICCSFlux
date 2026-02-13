/**
 * pidValidation.ts - P&ID connection validation
 *
 * Scans the current P&ID layer for:
 * - Unconnected symbol ports (no pipe attached)
 * - One-end-only pipes (start or end not connected to a symbol)
 * - Outlet-to-outlet connections (two outputs connected together)
 * - Port type mismatches (connecting incompatible port types)
 * - ISA 5.1 tag format violations (instrument labels should follow XX-NNN pattern)
 */

import type { PidLayerData, PidSymbol, PidPipe } from '../types'
import { SYMBOL_PORTS, SYMBOL_INFO, isScadaSymbol, getPortPosition, type ScadaSymbolType } from '../assets/symbols'

export interface PidValidationIssue {
  id: string
  type: 'unconnected-port' | 'dangling-pipe' | 'invalid-connection' | 'tag-format' | 'outlet-to-outlet'
  severity: 'warning' | 'error'
  message: string
  symbolId?: string
  pipeId?: string
  x: number
  y: number
}

/** Port IDs that are considered "outlets" (flow exits the symbol). */
const OUTLET_PORT_IDS = new Set([
  'outlet', 'discharge', 'output', 'out', 'supply', 'vent', 'drain',
])

/** Port IDs that are considered "inlets" (flow enters the symbol). */
const INLET_PORT_IDS = new Set([
  'inlet', 'suction', 'input', 'in', 'return', 'fill',
])

/**
 * ISA 5.1 tag number pattern: 1-4 uppercase letters + optional dash + digits + optional letter suffix.
 * Examples: FT-101, PIC-200, TI-100A, LCV-201, PSH-300
 * Letters represent ISA function codes (F=Flow, T=Temperature, P=Pressure, L=Level, etc.)
 */
const ISA_TAG_PATTERN = /^[A-Z]{1,4}-?\d{1,5}[A-Z]?$/

/** Instrument symbol categories that should follow ISA 5.1 tagging. */
const INSTRUMENT_CATEGORIES = new Set(['instrument', 'sensor', 'controller', 'transmitter', 'indicator'])

function isInstrumentSymbol(symbolType: string): boolean {
  const info = (SYMBOL_INFO as Record<string, { category: string }>)[symbolType]
  if (!info) return false
  return INSTRUMENT_CATEGORIES.has(info.category)
}

function isOutletPort(portId: string): boolean {
  return OUTLET_PORT_IDS.has(portId)
}

function isInletPort(portId: string): boolean {
  return INLET_PORT_IDS.has(portId)
}

/**
 * Validate a P&ID layer and return a list of issues.
 */
export function validatePidLayer(layer: PidLayerData): PidValidationIssue[] {
  const issues: PidValidationIssue[] = []

  // Build maps of connected ports and port-to-pipe relationships
  const connectedPorts = new Set<string>()
  // Track which port types are on each end of each pipe
  const pipeEndPorts: Array<{
    pipe: PidPipe
    startPortId?: string
    startSymbolId?: string
    endPortId?: string
    endSymbolId?: string
  }> = []

  for (const pipe of layer.pipes) {
    const entry: typeof pipeEndPorts[0] = { pipe }

    if (pipe.startSymbolId && pipe.startPortId) {
      connectedPorts.add(`${pipe.startSymbolId}:${pipe.startPortId}`)
      entry.startPortId = pipe.startPortId
      entry.startSymbolId = pipe.startSymbolId
    } else if (pipe.startConnection) {
      connectedPorts.add(`${pipe.startConnection.symbolId}:${pipe.startConnection.portId}`)
      entry.startPortId = pipe.startConnection.portId
      entry.startSymbolId = pipe.startConnection.symbolId
    }

    if (pipe.endSymbolId && pipe.endPortId) {
      connectedPorts.add(`${pipe.endSymbolId}:${pipe.endPortId}`)
      entry.endPortId = pipe.endPortId
      entry.endSymbolId = pipe.endSymbolId
    } else if (pipe.endConnection) {
      connectedPorts.add(`${pipe.endConnection.symbolId}:${pipe.endConnection.portId}`)
      entry.endPortId = pipe.endConnection.portId
      entry.endSymbolId = pipe.endConnection.symbolId
    }

    pipeEndPorts.push(entry)
  }

  // Check for unconnected ports on symbols
  for (const symbol of layer.symbols) {
    const ports = getSymbolPortList(symbol)
    for (const port of ports) {
      const key = `${symbol.id}:${port.id}`
      if (!connectedPorts.has(key)) {
        const pos = getPortPosition(
          symbol.type as ScadaSymbolType,
          port.id,
          symbol.x, symbol.y,
          symbol.width, symbol.height,
          (symbol.rotation || 0) as 0 | 90 | 180 | 270
        )
        issues.push({
          id: `unconnected-${key}`,
          type: 'unconnected-port',
          severity: 'warning',
          message: `Port "${port.id}" on "${symbol.label || symbol.type}" is not connected`,
          symbolId: symbol.id,
          x: pos?.x ?? (symbol.x + symbol.width * port.x),
          y: pos?.y ?? (symbol.y + symbol.height * port.y),
        })
      }
    }
  }

  // Check for dangling pipes (one or both ends not connected)
  for (const pipe of layer.pipes) {
    const hasStart = !!(pipe.startSymbolId || pipe.startConnection)
    const hasEnd = !!(pipe.endSymbolId || pipe.endConnection)

    if (!hasStart && !hasEnd) {
      const mid = pipe.points[Math.floor(pipe.points.length / 2)]
      issues.push({
        id: `dangling-both-${pipe.id}`,
        type: 'dangling-pipe',
        severity: 'error',
        message: `Pipe "${pipe.label || pipe.id.slice(0, 8)}" has no connections on either end`,
        pipeId: pipe.id,
        x: mid?.x || 0,
        y: mid?.y || 0,
      })
    } else if (!hasStart) {
      const pt = pipe.points[0]
      issues.push({
        id: `dangling-start-${pipe.id}`,
        type: 'dangling-pipe',
        severity: 'warning',
        message: `Pipe "${pipe.label || pipe.id.slice(0, 8)}" start is not connected`,
        pipeId: pipe.id,
        x: pt?.x || 0,
        y: pt?.y || 0,
      })
    } else if (!hasEnd) {
      const pt = pipe.points[pipe.points.length - 1]
      issues.push({
        id: `dangling-end-${pipe.id}`,
        type: 'dangling-pipe',
        severity: 'warning',
        message: `Pipe "${pipe.label || pipe.id.slice(0, 8)}" end is not connected`,
        pipeId: pipe.id,
        x: pt?.x || 0,
        y: pt?.y || 0,
      })
    }
  }

  // Check for outlet-to-outlet connections (two outputs connected by the same pipe)
  for (const entry of pipeEndPorts) {
    if (!entry.startPortId || !entry.endPortId) continue

    const startIsOutlet = isOutletPort(entry.startPortId)
    const endIsOutlet = isOutletPort(entry.endPortId)

    if (startIsOutlet && endIsOutlet) {
      const mid = entry.pipe.points[Math.floor(entry.pipe.points.length / 2)]
      const startSym = layer.symbols.find(s => s.id === entry.startSymbolId)
      const endSym = layer.symbols.find(s => s.id === entry.endSymbolId)
      issues.push({
        id: `outlet-outlet-${entry.pipe.id}`,
        type: 'outlet-to-outlet',
        severity: 'error',
        message: `Outlet-to-outlet: "${startSym?.label || entry.startPortId}" → "${endSym?.label || entry.endPortId}" (pipe ${entry.pipe.label || entry.pipe.id.slice(0, 8)})`,
        pipeId: entry.pipe.id,
        x: mid?.x || 0,
        y: mid?.y || 0,
      })
    }

    // Also check inlet-to-inlet (both inlets, no outlet)
    const startIsInlet = isInletPort(entry.startPortId)
    const endIsInlet = isInletPort(entry.endPortId)

    if (startIsInlet && endIsInlet) {
      const mid = entry.pipe.points[Math.floor(entry.pipe.points.length / 2)]
      const startSym = layer.symbols.find(s => s.id === entry.startSymbolId)
      const endSym = layer.symbols.find(s => s.id === entry.endSymbolId)
      issues.push({
        id: `inlet-inlet-${entry.pipe.id}`,
        type: 'invalid-connection',
        severity: 'warning',
        message: `Inlet-to-inlet: "${startSym?.label || entry.startPortId}" → "${endSym?.label || entry.endPortId}" (may indicate reversed flow)`,
        pipeId: entry.pipe.id,
        x: mid?.x || 0,
        y: mid?.y || 0,
      })
    }
  }

  // ISA 5.1 tag format validation for instrument symbols
  for (const symbol of layer.symbols) {
    if (!symbol.label) continue
    if (!isInstrumentSymbol(symbol.type)) continue

    // Only validate if the label looks like it's intended to be a tag (has at least one letter and one digit)
    const label = symbol.label.trim()
    if (!label || label.length < 3) continue
    if (!/[A-Za-z]/.test(label) || !/\d/.test(label)) continue

    if (!ISA_TAG_PATTERN.test(label.toUpperCase())) {
      issues.push({
        id: `tag-format-${symbol.id}`,
        type: 'tag-format',
        severity: 'warning',
        message: `"${label}" doesn't match ISA 5.1 format (e.g., FT-101, PIC-200)`,
        symbolId: symbol.id,
        x: symbol.x + symbol.width / 2,
        y: symbol.y + symbol.height / 2,
      })
    }
  }

  return issues
}

function getSymbolPortList(symbol: PidSymbol): { id: string; x: number; y: number }[] {
  if (isScadaSymbol(symbol.type)) {
    return SYMBOL_PORTS[symbol.type as ScadaSymbolType] || []
  }
  return []
}
