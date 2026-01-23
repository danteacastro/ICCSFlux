import { defineAsyncComponent } from 'vue'
import type { WidgetType } from '../types'

// Widget component registry
export const widgetComponents: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  numeric: defineAsyncComponent(() => import('./NumericDisplay.vue')),
  led: defineAsyncComponent(() => import('./LedIndicator.vue')),
  chart: defineAsyncComponent(() => import('./TrendChart.vue')),
  toggle: defineAsyncComponent(() => import('./ToggleSwitch.vue')),
  title: defineAsyncComponent(() => import('./TitleLabel.vue')),
  sparkline: defineAsyncComponent(() => import('./SparklineWidget.vue')),
  alarm_summary: defineAsyncComponent(() => import('./AlarmSummaryWidget.vue')),
  recording_status: defineAsyncComponent(() => import('./RecordingStatusWidget.vue')),
  system_status: defineAsyncComponent(() => import('./SystemStatusWidget.vue')),
  interlock_status: defineAsyncComponent(() => import('./InterlockStatusWidget.vue')),
  // multi_channel_table removed - use value_table instead
  action_button: defineAsyncComponent(() => import('./ActionButtonWidget.vue')),
  clock: defineAsyncComponent(() => import('./ClockWidget.vue')),
  gauge: defineAsyncComponent(() => import('./GaugeWidget.vue')),
  divider: defineAsyncComponent(() => import('./DividerWidget.vue')),
  setpoint: defineAsyncComponent(() => import('./SetpointWidget.vue')),
  bar_graph: defineAsyncComponent(() => import('./BarGraphWidget.vue')),
  scheduler_status: defineAsyncComponent(() => import('./SchedulerStatusWidget.vue')),
  // sequence_status removed - use script_monitor with py.SM_* tags
  svg_symbol: defineAsyncComponent(() => import('./SvgSymbolWidget.vue')),
  // text_label removed - use title instead
  value_table: defineAsyncComponent(() => import('./ValueTableWidget.vue')),
  crio_status: defineAsyncComponent(() => import('./CrioStatusWidget.vue')),
  latch_switch: defineAsyncComponent(() => import('./LatchSwitchWidget.vue')),
  script_monitor: defineAsyncComponent(() => import('./ScriptMonitorWidget.vue')),
  python_console: defineAsyncComponent(() => import('./PythonConsoleWidget.vue')),
  script_output: defineAsyncComponent(() => import('./ScriptOutputWidget.vue')),
  variable_explorer: defineAsyncComponent(() => import('./VariableExplorerWidget.vue')),
  variable_input: defineAsyncComponent(() => import('./VariableInputWidget.vue')),
  pid_loop: defineAsyncComponent(() => import('./PidLoopWidget.vue')),
  // Placeholders for future widgets
  table: defineAsyncComponent(() => import('./NumericDisplay.vue')), // fallback
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
  }
]
