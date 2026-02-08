/**
 * HMI Control Component Registry
 *
 * Maps hmi_* type strings to async Vue components for the P&ID canvas.
 */
import { defineAsyncComponent, type Component } from 'vue'

const registry: Record<string, Component> = {
  hmi_numeric: defineAsyncComponent(() => import('./HmiNumericIndicator.vue')),
  hmi_led: defineAsyncComponent(() => import('./HmiStatusLed.vue')),
  hmi_toggle: defineAsyncComponent(() => import('./HmiToggleControl.vue')),
  hmi_setpoint: defineAsyncComponent(() => import('./HmiSetpointControl.vue')),
  hmi_bar: defineAsyncComponent(() => import('./HmiBarIndicator.vue')),
  hmi_gauge: defineAsyncComponent(() => import('./HmiArcGauge.vue')),
  hmi_multistate: defineAsyncComponent(() => import('./HmiMultiStateIndicator.vue')),
  hmi_button: defineAsyncComponent(() => import('./HmiCommandButton.vue')),
  hmi_selector: defineAsyncComponent(() => import('./HmiSelectorSwitch.vue')),
  hmi_annunciator: defineAsyncComponent(() => import('./HmiAlarmAnnunciator.vue')),
  hmi_sparkline: defineAsyncComponent(() => import('./HmiTrendSparkline.vue')),
  hmi_valve_pos: defineAsyncComponent(() => import('./HmiValvePosition.vue')),
}

export function getHmiComponent(type: string): Component | null {
  return registry[type] || null
}
