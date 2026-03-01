import { defineAsyncComponent, defineComponent, h } from 'vue'
import type { WidgetType } from '../types'

// H7: Error boundary component for async widgets.
// When a widget fails to load (chunk error, syntax error, etc.), this component
// renders an error message instead of crashing the entire dashboard.
const WidgetLoadError = defineComponent({
  name: 'WidgetLoadError',
  props: {
    error: { type: Error, default: null }
  },
  setup(props) {
    return () => h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '8px',
        color: '#ef4444',
        fontSize: '12px',
        textAlign: 'center',
        background: '#1e1e1e',
        border: '1px solid #333',
        borderRadius: '4px',
      }
    }, [
      h('span', {}, `Widget failed to load${props.error ? ': ' + props.error.message : ''}`)
    ])
  }
})

// H7: Loading placeholder shown while widget chunk is being fetched
const WidgetLoading = defineComponent({
  name: 'WidgetLoading',
  setup() {
    return () => h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '8px',
        color: '#666',
        fontSize: '12px',
        background: '#1e1e1e',
      }
    }, 'Loading...')
  }
})

// H7: Helper that wraps defineAsyncComponent with error/loading boundaries
// so a single widget failure doesn't crash the whole dashboard
function defineWidgetComponent(loader: () => Promise<unknown>) {
  return defineAsyncComponent({
    loader: loader as () => Promise<{ default: ReturnType<typeof defineComponent> }>,
    errorComponent: WidgetLoadError,
    loadingComponent: WidgetLoading,
    delay: 200,    // Show loading after 200ms delay
    timeout: 30000 // Fail after 30 seconds
  })
}

// Widget component registry
export const widgetComponents: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  numeric: defineWidgetComponent(() => import('./NumericDisplay.vue')),
  led: defineWidgetComponent(() => import('./LedIndicator.vue')),
  chart: defineWidgetComponent(() => import('./TrendChart.vue')),
  toggle: defineWidgetComponent(() => import('./ToggleSwitch.vue')),
  title: defineWidgetComponent(() => import('./TitleLabel.vue')),
  sparkline: defineWidgetComponent(() => import('./SparklineWidget.vue')),
  alarm_summary: defineWidgetComponent(() => import('./AlarmSummaryWidget.vue')),
  recording_status: defineWidgetComponent(() => import('./RecordingStatusWidget.vue')),
  system_status: defineWidgetComponent(() => import('./SystemStatusWidget.vue')),
  interlock_status: defineWidgetComponent(() => import('./InterlockStatusWidget.vue')),
  // multi_channel_table removed - use value_table instead
  action_button: defineWidgetComponent(() => import('./ActionButtonWidget.vue')),
  clock: defineWidgetComponent(() => import('./ClockWidget.vue')),
  gauge: defineWidgetComponent(() => import('./GaugeWidget.vue')),
  divider: defineWidgetComponent(() => import('./DividerWidget.vue')),
  setpoint: defineWidgetComponent(() => import('./SetpointWidget.vue')),
  bar_graph: defineWidgetComponent(() => import('./BarGraphWidget.vue')),
  scheduler_status: defineWidgetComponent(() => import('./SchedulerStatusWidget.vue')),
  // sequence_status removed - use script_monitor with py.SM_* tags
  svg_symbol: defineWidgetComponent(() => import('./SvgSymbolWidget.vue')),
  // text_label removed - use title instead
  value_table: defineWidgetComponent(() => import('./ValueTableWidget.vue')),
  crio_status: defineWidgetComponent(() => import('./CrioStatusWidget.vue')),
  latch_switch: defineWidgetComponent(() => import('./LatchSwitchWidget.vue')),
  script_monitor: defineWidgetComponent(() => import('./ScriptMonitorWidget.vue')),
  python_console: defineWidgetComponent(() => import('./PythonConsoleWidget.vue')),
  script_output: defineWidgetComponent(() => import('./ScriptOutputWidget.vue')),
  variable_explorer: defineWidgetComponent(() => import('./VariableExplorerWidget.vue')),
  variable_input: defineWidgetComponent(() => import('./VariableInputWidget.vue')),
  pid_loop: defineWidgetComponent(() => import('./PidLoopWidget.vue')),
  heater_zone: defineWidgetComponent(() => import('./HeaterZoneWidget.vue')),
  status_messages: defineWidgetComponent(() => import('./StatusMessages.vue')),
  image: defineWidgetComponent(() => import('./ImageWidget.vue')),
  gc_chromatogram: defineWidgetComponent(() => import('./GcChromatogramWidget.vue')),
  gc_overview: defineWidgetComponent(() => import('./GcOverviewWidget.vue')),
  small_multiples: defineWidgetComponent(() => import('./SmallMultiplesWidget.vue')),
}

export function getWidgetComponent(type: WidgetType | string) {
  return widgetComponents[type] || widgetComponents.numeric
}

// Widget type definitions for the Add Widget panel
export interface WidgetTypeInfo {
  type: string
  name: string
  icon: string
  description: string
  needsChannel: boolean
  defaultSize: { w: number; h: number }
}

export const availableWidgets: WidgetTypeInfo[] = [
  // === LAYOUT (commonly used for organization) ===
  {
    type: 'title',
    name: 'Title/Label',
    icon: 'T',
    description: 'Text label or section header',
    needsChannel: false,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'divider',
    name: 'Divider',
    icon: '―',
    description: 'Visual separator line',
    needsChannel: false,
    defaultSize: { w: 3, h: 1 }
  },

  // === DATA DISPLAY ===
  {
    type: 'numeric',
    name: 'Numeric Display',
    icon: '#',
    description: 'Shows channel value with unit',
    needsChannel: true,
    defaultSize: { w: 1, h: 1 }
  },
  {
    type: 'chart',
    name: 'Trend Chart',
    icon: '📈',
    description: 'Real-time line chart',
    needsChannel: false,
    defaultSize: { w: 4, h: 3 }
  },
  {
    type: 'gauge',
    name: 'Gauge',
    icon: '◔',
    description: 'Circular gauge display',
    needsChannel: true,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'led',
    name: 'LED Indicator',
    icon: '●',
    description: 'Boolean status indicator',
    needsChannel: true,
    defaultSize: { w: 1, h: 1 }
  },
  {
    type: 'sparkline',
    name: 'Sparkline',
    icon: '~',
    description: 'Mini trend with current value',
    needsChannel: true,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'bar_graph',
    name: 'Bar Graph',
    icon: '▮',
    description: 'Horizontal/vertical bar display',
    needsChannel: true,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'value_table',
    name: 'Value Table',
    icon: '▦',
    description: 'Compact table of multiple values',
    needsChannel: false,
    defaultSize: { w: 3, h: 4 }
  },

  // === CONTROLS ===
  {
    type: 'pid_loop',
    name: 'PID Loop',
    icon: '⟳',
    description: 'PID control loop faceplate',
    needsChannel: false,
    defaultSize: { w: 2, h: 3 }
  },
  {
    type: 'heater_zone',
    name: 'Heater Zone',
    icon: '🔥',
    description: 'Temperature controller faceplate (SLM1-C)',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'toggle',
    name: 'Toggle Switch',
    icon: '◐',
    description: 'Control digital output',
    needsChannel: true,
    defaultSize: { w: 1, h: 1 }
  },
  {
    type: 'setpoint',
    name: 'Setpoint',
    icon: '⊕',
    description: 'Set analog output value',
    needsChannel: true,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'action_button',
    name: 'Action Button',
    icon: '▶',
    description: 'Trigger actions with interlock support',
    needsChannel: false,
    defaultSize: { w: 1, h: 1 }
  },

  // === STATUS & ALARMS ===
  {
    type: 'alarm_summary',
    name: 'Alarm Summary',
    icon: '⚠',
    description: 'Active alarms and warnings',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'system_status',
    name: 'System Status',
    icon: '◉',
    description: 'Connection and DAQ status',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'recording_status',
    name: 'Recording Status',
    icon: '●',
    description: 'Recording file and duration',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'clock',
    name: 'Clock',
    icon: '⏱',
    description: 'Time, date, and run elapsed',
    needsChannel: false,
    defaultSize: { w: 2, h: 1 }
  },

  // === SAFETY ===
  {
    type: 'interlock_status',
    name: 'Interlock Status',
    icon: '🛡',
    description: 'Safety interlock overview',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'latch_switch',
    name: 'Safety Latch',
    icon: '🔒',
    description: 'Safety latch for outputs/session',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'crio_status',
    name: 'cRIO Status',
    icon: '⚡',
    description: 'cRIO controller safety status and I/O',
    needsChannel: false,
    defaultSize: { w: 2, h: 3 }
  },

  // === SCRIPTING ===
  {
    type: 'script_monitor',
    name: 'Script Monitor',
    icon: '📊',
    description: 'Monitor py.* script values in real-time',
    needsChannel: false,
    defaultSize: { w: 3, h: 4 }
  },
  {
    type: 'script_output',
    name: 'Script Output',
    icon: '📜',
    description: 'View console output from scripts',
    needsChannel: false,
    defaultSize: { w: 4, h: 3 }
  },
  {
    type: 'python_console',
    name: 'Python Console',
    icon: '>_',
    description: 'Interactive Python REPL',
    needsChannel: false,
    defaultSize: { w: 4, h: 3 }
  },
  {
    type: 'variable_explorer',
    name: 'Variable Explorer',
    icon: '{}',
    description: 'IPython-like variable inspector',
    needsChannel: false,
    defaultSize: { w: 3, h: 4 }
  },
  {
    type: 'variable_input',
    name: 'Variable Input',
    icon: '⎆',
    description: 'Input values for script parameters/constants',
    needsChannel: false,
    defaultSize: { w: 2, h: 3 }
  },

  // === SPECIALIZED ===
  {
    type: 'scheduler_status',
    name: 'Scheduler Status',
    icon: '📅',
    description: 'Schedule overview and control',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'svg_symbol',
    name: 'P&ID Symbol',
    icon: '⚙',
    description: 'SCADA equipment symbol (use dedicated P&ID system instead)',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'status_messages',
    name: 'Status Messages',
    icon: '💬',
    description: 'Scrolling system status and event messages',
    needsChannel: false,
    defaultSize: { w: 3, h: 2 }
  },
  {
    type: 'image',
    name: 'Image / Logo',
    icon: '🖼',
    description: 'Static image from URL (logos, photos, diagrams)',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },

  // === GC ANALYSIS ===
  {
    type: 'gc_chromatogram',
    name: 'GC Chromatogram',
    icon: '⚗',
    description: 'Gas chromatograph chromatogram with peak analysis',
    needsChannel: false,
    defaultSize: { w: 4, h: 4 }
  },
  {
    type: 'gc_overview',
    name: 'GC Overview',
    icon: '🔬',
    description: 'Multi-GC instrument overview with run queue',
    needsChannel: false,
    defaultSize: { w: 6, h: 4 }
  },

  // === MONITORING ===
  {
    type: 'small_multiples',
    name: 'Small Multiples',
    icon: '▣',
    description: 'Grid of sparklines for monitoring many channels at once',
    needsChannel: false,
    defaultSize: { w: 4, h: 3 }
  }
]
