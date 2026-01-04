/**
 * Format unit strings for display
 * Converts common abbreviations to proper symbols
 */
export function formatUnit(unit: string | undefined): string {
  if (!unit) return ''

  // Common unit conversions
  const conversions: Record<string, string> = {
    'degF': '°F',
    'degC': '°C',
    'degK': 'K',
    'deg': '°',
    'degf': '°F',
    'degc': '°C',
    'DegF': '°F',
    'DegC': '°C',
    'Deg': '°',
    'ohm': 'Ω',
    'ohms': 'Ω',
    'Ohm': 'Ω',
    'Ohms': 'Ω',
    'micro': 'µ',
    'uA': 'µA',
    'uV': 'µV',
    'uF': 'µF',
  }

  return conversions[unit] || unit
}
