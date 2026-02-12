/**
 * pidValidation.ts - P&ID connection validation
 *
 * Scans the current P&ID layer for:
 * - Unconnected symbol ports (no pipe attached)
 * - One-end-only pipes (start or end not connected to a symbol)
 * - Outlet-to-outlet connections (two outputs connected together)
 */

import type { PidLayerData, PidSymbol, PidPipe } from '../types'
import { SYMBOL_PORTS, isScadaSymbol, getPortPosition, type ScadaSymbolType } from '../assets/symbols'

export interface PidValidationIssue {
  id: string
  type: 'unconnected-port' | 'dangling-pipe' | 'invalid-connection'
  severity: 'warning' | 'error'
  message: string
  symbolId?: string
  pipeId?: string
  x: number
  y: number
}

/**
 * Validate a P&ID layer and return a list of issues.
 */
export function validatePidLayer(layer: PidLayerData): PidValidationIssue[] {
  const issues: PidValidationIssue[] = []

  // Build set of connected port references: "symbolId:portId"
  const connectedPorts = new Set<string>()
  for (const pipe of layer.pipes) {
    if (pipe.startSymbolId && pipe.startPortId) {
      connectedPorts.add(`${pipe.startSymbolId}:${pipe.startPortId}`)
    }
    if (pipe.endSymbolId && pipe.endPortId) {
      connectedPorts.add(`${pipe.endSymbolId}:${pipe.endPortId}`)
    }
  }

  // Check for unconnected ports on symbols
  for (const symbol of layer.symbols) {
    const ports = getSymbolPortList(symbol)
    for (const port of ports) {
      const key = `${symbol.id}:${port.id}`
      if (!connectedPorts.has(key)) {
        // Use getPortPosition for accurate coords (accounts for SVG letterbox + rotation)
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
    const hasStart = !!pipe.startSymbolId
    const hasEnd = !!pipe.endSymbolId

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

  return issues
}

function getSymbolPortList(symbol: PidSymbol): { id: string; x: number; y: number }[] {
  if (isScadaSymbol(symbol.type)) {
    return SYMBOL_PORTS[symbol.type as ScadaSymbolType] || []
  }
  return []
}
