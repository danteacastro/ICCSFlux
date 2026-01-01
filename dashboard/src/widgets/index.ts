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
  multi_channel_table: defineAsyncComponent(() => import('./MultiChannelTableWidget.vue')),
  action_button: defineAsyncComponent(() => import('./ActionButtonWidget.vue')),
  clock: defineAsyncComponent(() => import('./ClockWidget.vue')),
  gauge: defineAsyncComponent(() => import('./GaugeWidget.vue')),
  divider: defineAsyncComponent(() => import('./DividerWidget.vue')),
  setpoint: defineAsyncComponent(() => import('./SetpointWidget.vue')),
  bar_graph: defineAsyncComponent(() => import('./BarGraphWidget.vue')),
  scheduler_status: defineAsyncComponent(() => import('./SchedulerStatusWidget.vue')),
  sequence_status: defineAsyncComponent(() => import('./SequenceStatusWidget.vue')),
  svg_symbol: defineAsyncComponent(() => import('./SvgSymbolWidget.vue')),
  text_label: defineAsyncComponent(() => import('./TextLabelWidget.vue')),
  value_table: defineAsyncComponent(() => import('./ValueTableWidget.vue')),
  crio_status: defineAsyncComponent(() => import('./CrioStatusWidget.vue')),
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
  {
    type: 'title',
    name: 'Title/Label',
    icon: 'T',
    description: 'Text label or section header',
    needsChannel: false,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'numeric',
    name: 'Numeric Display',
    icon: '#',
    description: 'Shows channel value with unit',
    needsChannel: true,
    defaultSize: { w: 1, h: 1 }
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
    type: 'toggle',
    name: 'Toggle Switch',
    icon: '◐',
    description: 'Control digital output',
    needsChannel: true,
    defaultSize: { w: 1, h: 1 }
  },
  {
    type: 'chart',
    name: 'Trend Chart',
    icon: '📈',
    description: 'Real-time line chart',
    needsChannel: false, // Channels selected after adding
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
    type: 'sparkline',
    name: 'Sparkline',
    icon: '~',
    description: 'Mini trend with current value',
    needsChannel: true,
    defaultSize: { w: 2, h: 1 }
  },
  {
    type: 'alarm_summary',
    name: 'Alarm Summary',
    icon: '⚠',
    description: 'Active alarms and warnings',
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
    type: 'system_status',
    name: 'System Status',
    icon: '◉',
    description: 'Connection and DAQ status',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'interlock_status',
    name: 'Interlock Status',
    icon: '🛡',
    description: 'Safety interlock overview',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'multi_channel_table',
    name: 'Channel Table',
    icon: '▤',
    description: 'Compact multi-channel display',
    needsChannel: false,
    defaultSize: { w: 2, h: 3 }
  },
  {
    type: 'action_button',
    name: 'Action Button',
    icon: '▶',
    description: 'Trigger actions with interlock support',
    needsChannel: false,
    defaultSize: { w: 1, h: 1 }
  },
  {
    type: 'clock',
    name: 'Clock',
    icon: '⏱',
    description: 'Time, date, and run elapsed',
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
  {
    type: 'setpoint',
    name: 'Setpoint',
    icon: '⊕',
    description: 'Set analog output value',
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
    type: 'scheduler_status',
    name: 'Scheduler Status',
    icon: '📅',
    description: 'Schedule overview and control',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'sequence_status',
    name: 'Sequence Status',
    icon: '⚙',
    description: 'Running sequence progress',
    needsChannel: false,
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'svg_symbol',
    name: 'P&ID Symbol',
    icon: '⚙',
    description: 'SCADA equipment symbol (valve, pump, sensor)',
    needsChannel: false,  // Channel is optional - pick symbol first
    defaultSize: { w: 2, h: 2 }
  },
  {
    type: 'text_label',
    name: 'Text Label',
    icon: 'A',
    description: 'Static text annotation for P&ID labeling',
    needsChannel: false,
    defaultSize: { w: 3, h: 1 }
  },
  {
    type: 'value_table',
    name: 'Value Table',
    icon: '▦',
    description: 'Compact table of multiple values (industrial style)',
    needsChannel: false, // Uses channels array, not single channel
    defaultSize: { w: 3, h: 4 }
  },
  {
    type: 'crio_status',
    name: 'cRIO Status',
    icon: '⚡',
    description: 'cRIO controller safety status and I/O',
    needsChannel: false,
    defaultSize: { w: 2, h: 3 }
  }
]
