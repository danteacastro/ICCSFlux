/**
 * ISA-101 High Performance HMI Control Catalog
 *
 * Defines the HMI control types available in the P&ID symbol panel.
 * These render as interactive HTML components on the canvas (not SVG).
 */

export function isHmiControl(type: string): boolean {
  return type.startsWith('hmi_')
}

export interface HmiControlEntry {
  type: string
  name: string
  category: string
  thumbnail: string
  defaultWidth: number
  defaultHeight: number
}

// Thumbnail SVGs for the symbol panel tiles (ISA-101 style preview)
const THUMBNAILS = {
  hmi_numeric: `<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="58" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="1" y="1" width="58" height="10" rx="2" fill="#C0C0C0" stroke="none"/>
    <text x="30" y="9" text-anchor="middle" font-size="6" fill="#555">LABEL</text>
    <text x="30" y="23" text-anchor="middle" font-size="10" font-weight="bold" font-family="monospace" fill="#1E3A8A">123.4</text>
  </svg>`,

  hmi_led: `<svg viewBox="0 0 30 36" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="15" cy="14" r="8" fill="#808080" stroke="#666" stroke-width="1"/>
    <text x="15" y="32" text-anchor="middle" font-size="5" fill="#555">TAG</text>
  </svg>`,

  hmi_toggle: `<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="48" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="4" y="4" width="20" height="22" rx="1" fill="#2D862D" stroke="#555"/>
    <text x="14" y="18" text-anchor="middle" font-size="6" font-weight="bold" fill="white">ON</text>
    <rect x="26" y="4" width="20" height="22" rx="1" fill="#E8E8E8" stroke="#A0A0A4"/>
    <text x="36" y="18" text-anchor="middle" font-size="6" fill="#888">OFF</text>
  </svg>`,

  hmi_setpoint: `<svg viewBox="0 0 60 34" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="58" height="32" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <text x="30" y="10" text-anchor="middle" font-size="5" fill="#555">SP</text>
    <rect x="8" y="13" width="44" height="14" rx="1" fill="white" stroke="#A0A0A4"/>
    <text x="30" y="24" text-anchor="middle" font-size="9" font-weight="bold" font-family="monospace" fill="#1E3A8A">850.0</text>
  </svg>`,

  hmi_bar: `<svg viewBox="0 0 70 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="68" height="22" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="4" y="5" width="62" height="8" rx="1" fill="#E8E8E8" stroke="#A0A0A4"/>
    <rect x="4" y="5" width="8" height="8" rx="1" fill="rgba(255,0,0,0.15)"/>
    <rect x="12" y="5" width="10" height="8" fill="rgba(255,215,0,0.1)"/>
    <rect x="44" y="5" width="10" height="8" fill="rgba(255,215,0,0.1)"/>
    <rect x="54" y="5" width="12" height="8" rx="1" fill="rgba(255,0,0,0.15)"/>
    <polygon points="38,4 40,1 42,4" fill="#333"/>
    <text x="40" y="20" text-anchor="middle" font-size="5" font-family="monospace" fill="#1E3A8A">62.5</text>
  </svg>`,

  hmi_gauge: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="20" cy="20" r="17" fill="#D4D4D4" stroke="#A0A0A4"/>
    <path d="M7 27 A15 15 0 1 1 33 27" stroke="#E0E0E0" stroke-width="3" fill="none" stroke-linecap="round"/>
    <path d="M7 27 A15 15 0 0 1 20 5" stroke="#1E3A8A" stroke-width="3" fill="none" stroke-linecap="round"/>
    <line x1="20" y1="20" x2="12" y2="10" stroke="#333" stroke-width="1.5" stroke-linecap="round"/>
    <circle cx="20" cy="20" r="2" fill="#333"/>
    <text x="20" y="32" text-anchor="middle" font-size="5" font-family="monospace" fill="#1E3A8A">75</text>
  </svg>`,

  hmi_multistate: `<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="58" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <circle cx="12" cy="15" r="5" fill="#2D862D"/>
    <text x="22" y="18" font-size="7" font-weight="600" fill="#333">RUNNING</text>
  </svg>`,

  hmi_button: `<svg viewBox="0 0 50 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="48" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="6" y="5" width="38" height="20" rx="2" fill="#E8E8E8" stroke="#888"/>
    <text x="25" y="19" text-anchor="middle" font-size="7" font-weight="700" fill="#555">START</text>
  </svg>`,

  hmi_selector: `<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="58" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="4" y="4" width="16" height="22" rx="1" fill="#E8E8E8" stroke="#A0A0A4"/>
    <text x="12" y="18" text-anchor="middle" font-size="5" fill="#888">OFF</text>
    <rect x="22" y="4" width="16" height="22" rx="1" fill="#4169E1" stroke="#2850B0"/>
    <text x="30" y="18" text-anchor="middle" font-size="5" font-weight="700" fill="white">MAN</text>
    <rect x="40" y="4" width="16" height="22" rx="1" fill="#E8E8E8" stroke="#A0A0A4"/>
    <text x="48" y="18" text-anchor="middle" font-size="5" fill="#888">AUTO</text>
  </svg>`,

  hmi_annunciator: `<svg viewBox="0 0 60 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="58" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <rect x="3" y="3" width="54" height="24" rx="1" fill="#808080"/>
    <text x="30" y="12" text-anchor="middle" font-size="5" fill="#ddd">HI TEMP</text>
    <text x="30" y="22" text-anchor="middle" font-size="7" font-weight="700" fill="#ddd">NORMAL</text>
  </svg>`,

  hmi_sparkline: `<svg viewBox="0 0 70 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="68" height="28" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <polyline points="5,20 15,18 25,12 35,14 45,8 55,10 65,6" stroke="#1E3A8A" stroke-width="1.5" fill="none"/>
    <text x="65" y="24" text-anchor="end" font-size="6" font-family="monospace" fill="#1E3A8A">72.3</text>
  </svg>`,

  hmi_valve_pos: `<svg viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="48" height="48" rx="2" fill="#D4D4D4" stroke="#A0A0A4"/>
    <polygon points="10,35 25,15 40,35" fill="none" stroke="#808080" stroke-width="2"/>
    <rect x="10" y="35" width="30" height="4" fill="#808080" stroke="none" rx="1"/>
    <text x="25" y="46" text-anchor="middle" font-size="7" font-family="monospace" font-weight="700" fill="#1E3A8A">75%</text>
  </svg>`,
}

export const HMI_CONTROL_CATALOG: HmiControlEntry[] = [
  {
    type: 'hmi_numeric',
    name: 'Numeric Indicator',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_numeric,
    defaultWidth: 120,
    defaultHeight: 50,
  },
  {
    type: 'hmi_led',
    name: 'Status LED',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_led,
    defaultWidth: 40,
    defaultHeight: 50,
  },
  {
    type: 'hmi_toggle',
    name: 'Toggle Switch',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_toggle,
    defaultWidth: 100,
    defaultHeight: 50,
  },
  {
    type: 'hmi_setpoint',
    name: 'Setpoint Control',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_setpoint,
    defaultWidth: 120,
    defaultHeight: 60,
  },
  {
    type: 'hmi_bar',
    name: 'Bar Indicator',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_bar,
    defaultWidth: 140,
    defaultHeight: 40,
  },
  {
    type: 'hmi_gauge',
    name: 'Arc Gauge',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_gauge,
    defaultWidth: 100,
    defaultHeight: 100,
  },
  {
    type: 'hmi_multistate',
    name: 'Multi-State',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_multistate,
    defaultWidth: 120,
    defaultHeight: 40,
  },
  {
    type: 'hmi_button',
    name: 'Command Button',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_button,
    defaultWidth: 100,
    defaultHeight: 40,
  },
  {
    type: 'hmi_selector',
    name: 'Selector Switch',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_selector,
    defaultWidth: 140,
    defaultHeight: 50,
  },
  {
    type: 'hmi_annunciator',
    name: 'Annunciator',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_annunciator,
    defaultWidth: 120,
    defaultHeight: 50,
  },
  {
    type: 'hmi_sparkline',
    name: 'Trend Sparkline',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_sparkline,
    defaultWidth: 160,
    defaultHeight: 50,
  },
  {
    type: 'hmi_valve_pos',
    name: 'Valve Position',
    category: 'HMI Controls',
    thumbnail: THUMBNAILS.hmi_valve_pos,
    defaultWidth: 80,
    defaultHeight: 80,
  },
]

/** Get HMI thumbnail SVG for symbol panel */
export function getHmiThumbnail(type: string): string {
  return THUMBNAILS[type as keyof typeof THUMBNAILS] || ''
}

/** Get default size for an HMI control type */
export function getHmiDefaultSize(type: string): { width: number; height: number } | null {
  const entry = HMI_CONTROL_CATALOG.find(h => h.type === type)
  return entry ? { width: entry.defaultWidth, height: entry.defaultHeight } : null
}
