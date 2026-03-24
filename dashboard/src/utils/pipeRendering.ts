/**
 * pipeRendering.ts - Shared pipe rendering utilities (#7.5)
 *
 * Used by both PipeOverlay (grid-based) and PidCanvas (pixel-based) pipe systems.
 */

/** Distance from point (px,py) to line segment (x1,y1)→(x2,y2) */
export function distanceToSegment(
  px: number, py: number,
  x1: number, y1: number,
  x2: number, y2: number
): number {
  const A = px - x1
  const B = py - y1
  const C = x2 - x1
  const D = y2 - y1
  const dot = A * C + B * D
  const lenSq = C * C + D * D
  const param = lenSq !== 0 ? dot / lenSq : -1

  let xx: number, yy: number
  if (param < 0) { xx = x1; yy = y1 }
  else if (param > 1) { xx = x2; yy = y2 }
  else { xx = x1 + param * C; yy = y1 + param * D }

  return Math.sqrt((px - xx) ** 2 + (py - yy) ** 2)
}

/** Common dash pattern presets for pipe styles */
export const PIPE_DASH_PATTERNS: Record<string, string> = {
  solid: '',
  dashed: '8,4',
  dotted: '2,4',
  dashDot: '8,4,2,4',
  longDash: '16,6',
}

/** Generate CSS animation style string for flow animation */
export function getFlowAnimationCss(durationSec: number, reverse = false): string {
  return `animation: pipe-flow ${durationSec}s linear infinite${reverse ? ' reverse' : ''}`
}
