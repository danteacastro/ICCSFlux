/**
 * ISA-5.1 Parametric Function Block SVG Generator
 *
 * Generates ISA-compliant instrument bubble SVGs with arbitrary letter codes.
 * Shapes per ISA-5.1:
 *   field        → plain circle
 *   panel        → circle with horizontal midline
 *   behind-panel → dashed circle
 *   local-panel  → circle inside square
 *   dcs          → circle inside hexagon
 *   plc          → circle inside diamond
 *   shared       → circle with double horizontal lines
 */

export type IsaLocation = 'field' | 'panel' | 'dcs' | 'plc' | 'shared' | 'behind-panel' | 'local-panel'

// ISA-5.1 first (measured variable) letter designations
export const ISA_FIRST_LETTERS: Record<string, string> = {
  A: 'Analysis', B: 'Burner/Combustion', C: 'Conductivity', D: 'Density',
  E: 'Voltage', F: 'Flow', G: 'Gauging/Position', H: 'Hand',
  I: 'Current', J: 'Power', K: 'Time/Schedule', L: 'Level',
  M: 'Moisture', N: 'User Choice', O: 'User Choice', P: 'Pressure',
  Q: 'Quantity', R: 'Radiation', S: 'Speed/Frequency', T: 'Temperature',
  U: 'Multivariable', V: 'Vibration', W: 'Weight/Force', X: 'Unclassified',
  Y: 'Event/State', Z: 'Position/Dimension',
}

// ISA-5.1 successor (function) letter designations
export const ISA_SUCCESSOR_LETTERS: Record<string, string> = {
  A: 'Alarm', C: 'Controller', D: 'Differential', E: 'Element/Sensor',
  G: 'Glass/Gauge', H: 'High', I: 'Indicator', K: 'Control Station',
  L: 'Low', R: 'Recorder', S: 'Switch', T: 'Transmitter',
  V: 'Valve/Damper', Y: 'Relay/Compute', Z: 'Final Element',
}

// Memoization cache for generated SVGs
const svgCache = new Map<string, string>()

/**
 * Generate an ISA-5.1 compliant instrument function block SVG.
 *
 * @param letters - ISA letter codes (e.g., "TIC", "FT", "PIC", "LAH")
 * @param location - Instrument location per ISA-5.1
 * @param tagNumber - Optional tag/loop number (shown above letters)
 */
export function generateIsaFunctionBlockSvg(
  letters: string = 'TI',
  location: IsaLocation = 'field',
  tagNumber?: string
): string {
  const cacheKey = `${letters}|${location}|${tagNumber ?? ''}`
  const cached = svgCache.get(cacheKey)
  if (cached) return cached

  const vw = 60, vh = 48
  const cx = vw / 2, cy = vh / 2
  const r = 16

  let shapeMarkup = ''
  let midlineMarkup = ''

  switch (location) {
    case 'field':
      // Plain circle
      shapeMarkup = `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`
      break

    case 'panel':
      // Circle with horizontal midline
      shapeMarkup = `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`
      midlineMarkup = `<line x1="${cx - r}" y1="${cy}" x2="${cx + r}" y2="${cy}" stroke="currentColor" stroke-width="1"/>`
      break

    case 'behind-panel':
      // Dashed circle
      shapeMarkup = `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="4,3"/>`
      break

    case 'local-panel':
      // Circle inside square
      shapeMarkup = [
        `<rect x="${cx - r - 3}" y="${cy - r - 3}" width="${(r + 3) * 2}" height="${(r + 3) * 2}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
        `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
      ].join('\n  ')
      break

    case 'dcs':
      // Circle inside hexagon
      shapeMarkup = [
        `<polygon points="${cx},${cy - r - 4} ${cx + r + 4},${cy - (r + 4) / 2} ${cx + r + 4},${cy + (r + 4) / 2} ${cx},${cy + r + 4} ${cx - r - 4},${cy + (r + 4) / 2} ${cx - r - 4},${cy - (r + 4) / 2}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
        `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
      ].join('\n  ')
      break

    case 'plc':
      // Circle inside diamond
      shapeMarkup = [
        `<polygon points="${cx},${cy - r - 5} ${cx + r + 5},${cy} ${cx},${cy + r + 5} ${cx - r - 5},${cy}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
        `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
      ].join('\n  ')
      break

    case 'shared':
      // Circle with double horizontal lines
      shapeMarkup = `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="currentColor" stroke-width="1.5" fill="none"/>`
      midlineMarkup = [
        `<line x1="${cx - r}" y1="${cy - 2}" x2="${cx + r}" y2="${cy - 2}" stroke="currentColor" stroke-width="1"/>`,
        `<line x1="${cx - r}" y1="${cy + 2}" x2="${cx + r}" y2="${cy + 2}" stroke="currentColor" stroke-width="1"/>`,
      ].join('\n  ')
      break
  }

  // Text sizing: scale font based on letter count
  const letterCount = letters.length
  const fontSize = letterCount <= 2 ? 11 : letterCount <= 3 ? 9 : 7.5

  // Tag number in upper half, letters in lower half (ISA standard)
  const hasTag = tagNumber && tagNumber.length > 0
  const lettersY = hasTag ? cy + 5 : cy + 1
  const tagY = cy - 5

  // Process connection stubs (left/right)
  const stubs = [
    `<line x1="0" y1="${cy}" x2="${cx - r}" y2="${cy}" stroke="currentColor" stroke-width="1.5"/>`,
    `<line x1="${cx + r}" y1="${cy}" x2="${vw}" y2="${cy}" stroke="currentColor" stroke-width="1.5"/>`,
  ].join('\n  ')

  const svg = `<svg viewBox="0 0 ${vw} ${vh}" fill="none" xmlns="http://www.w3.org/2000/svg">
  ${stubs}
  ${shapeMarkup}
  ${midlineMarkup}
  <text x="${cx}" y="${lettersY}" text-anchor="middle" dominant-baseline="middle" font-family="Arial, sans-serif" font-size="${fontSize}" font-weight="bold" fill="currentColor">${escapeXml(letters)}</text>
  ${hasTag ? `<text x="${cx}" y="${tagY}" text-anchor="middle" dominant-baseline="middle" font-family="Arial, sans-serif" font-size="8" fill="currentColor">${escapeXml(tagNumber!)}</text>` : ''}
</svg>`

  svgCache.set(cacheKey, svg)
  return svg
}

function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Clear the SVG cache (useful if symbol styling changes) */
export function clearIsaCache(): void {
  svgCache.clear()
}
