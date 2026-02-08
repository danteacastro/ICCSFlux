<script setup lang="ts">
/**
 * PidPropertiesPanel - Right-side collapsible properties panel for P&ID Editor
 *
 * Shows different content based on selection:
 * - No selection: Canvas settings (grid, background)
 * - Single symbol: Label, channel, color, rotation, show value
 * - Single pipe: Color, width, dashed, animated, path type
 * - Multiple selection: Bulk color, alignment
 */

import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import { useBackendScripts } from '../composables/useBackendScripts'
import type { PidSymbol, PidPipe, ButtonAction, ButtonActionType, SystemCommandType } from '../types'
import { isHmiControl, HMI_CONTROL_CATALOG } from '../constants/hmiControls'
import { SYMBOL_INFO, OFF_PAGE_CONNECTOR_TYPES } from '../assets/symbols'

const store = useDashboardStore()
const scriptsComposable = useScripts()
const backendScriptsComposable = useBackendScripts()

const selectedSymbolIds = computed(() => store.pidSelectedIds.symbolIds)
const selectedPipeIds = computed(() => store.pidSelectedIds.pipeIds)

const selectedSymbol = computed<PidSymbol | null>(() => {
  if (selectedSymbolIds.value.length !== 1) return null
  return store.pidLayer.symbols.find(s => s.id === selectedSymbolIds.value[0]) || null
})

const selectedPipe = computed<PidPipe | null>(() => {
  if (selectedPipeIds.value.length !== 1 || selectedSymbolIds.value.length > 0) return null
  return store.pidLayer.pipes.find(p => p.id === selectedPipeIds.value[0]) || null
})

const selectionCount = computed(() =>
  selectedSymbolIds.value.length + selectedPipeIds.value.length +
  store.pidSelectedIds.textAnnotationIds.length
)

const channelNames = computed(() => Object.keys(store.channels).sort())

const symbolDisplayName = computed(() => {
  if (!selectedSymbol.value) return ''
  const t = selectedSymbol.value.type
  // Check HMI controls first
  const hmi = HMI_CONTROL_CATALOG.find(h => h.type === t)
  if (hmi) return hmi.name
  // Check SCADA symbols
  const info = (SYMBOL_INFO as Record<string, { label: string }>)[t]
  if (info) return info.label
  // Fallback: convert camelCase to Title Case
  return t.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase()).trim()
})

// Symbol property updates
function updateSymbol(updates: Partial<PidSymbol>) {
  if (!selectedSymbol.value) return
  store.updatePidSymbolWithUndo(selectedSymbol.value.id, updates)
}

// Pipe property updates
function updatePipe(updates: Partial<PidPipe>) {
  if (!selectedPipe.value) return
  store.updatePidPipeWithUndo(selectedPipe.value.id, updates)
}

function reversePipe() {
  const p = selectedPipe.value
  if (!p) return
  store.updatePidPipeWithUndo(p.id, {
    points: [...p.points].reverse(),
    startConnection: p.endConnection,
    endConnection: p.startConnection,
    startSymbolId: p.endSymbolId,
    endSymbolId: p.startSymbolId,
    startPortId: p.endPortId,
    endPortId: p.startPortId,
    startArrow: p.endArrow,
    endArrow: p.startArrow,
  })
}

// Resolve arrow type from boolean | string for backwards compat
function resolvePipeArrow(val: any): string {
  if (val === true) return 'arrow'
  if (!val || val === false) return 'none'
  return val
}

// Dash pattern preset helpers
function getDashPreset(pipe: PidPipe): string {
  if (pipe.dashPattern === '2,2' || pipe.dashPattern === '2 2') return 'dotted'
  if (pipe.dashPattern === '8,3,2,3' || pipe.dashPattern === '8 3 2 3') return 'dashdot'
  if (pipe.dashPattern === '16,4' || pipe.dashPattern === '16 4') return 'longdash'
  if (pipe.dashPattern) return 'custom'
  if (pipe.dashed) return 'dashed'
  return 'solid'
}

function applyDashPreset(preset: string) {
  const presets: Record<string, Partial<PidPipe>> = {
    solid:    { dashed: undefined, dashPattern: undefined },
    dashed:   { dashed: true, dashPattern: undefined },
    dotted:   { dashed: undefined, dashPattern: '2,2' },
    dashdot:  { dashed: undefined, dashPattern: '8,3,2,3' },
    longdash: { dashed: undefined, dashPattern: '16,4' },
    custom:   { dashed: undefined, dashPattern: selectedPipe.value?.dashPattern || '8,4' },
  }
  updatePipe(presets[preset] || {})
}

// HMI Multi-State helpers
function updateHmiState(index: number, field: string, value: string | number) {
  if (!selectedSymbol.value) return
  const states = [...(selectedSymbol.value.hmiStates || [])]
  if (states[index]) {
    states[index] = { ...states[index], [field]: value }
    updateSymbol({ hmiStates: states })
  }
}

function addHmiState() {
  if (!selectedSymbol.value) return
  const states = [...(selectedSymbol.value.hmiStates || [])]
  const nextVal = states.length > 0 ? Math.max(...states.map(s => s.value)) + 1 : 0
  states.push({ value: nextVal, label: 'STATE', color: '#808080' })
  updateSymbol({ hmiStates: states })
}

function removeHmiState(index: number) {
  if (!selectedSymbol.value) return
  const states = [...(selectedSymbol.value.hmiStates || [])]
  states.splice(index, 1)
  updateSymbol({ hmiStates: states })
}

// HMI Selector position helpers
function updateSelectorPos(index: number, field: string, value: string | number) {
  if (!selectedSymbol.value) return
  const positions = [...(selectedSymbol.value.hmiSelectorPositions || [])]
  if (positions[index]) {
    positions[index] = { ...positions[index], [field]: value }
    updateSymbol({ hmiSelectorPositions: positions })
  }
}

function addSelectorPos() {
  if (!selectedSymbol.value) return
  const positions = [...(selectedSymbol.value.hmiSelectorPositions || [])]
  const nextVal = positions.length > 0 ? Math.max(...positions.map(p => p.value)) + 1 : 0
  positions.push({ value: nextVal, label: 'POS' })
  updateSymbol({ hmiSelectorPositions: positions })
}

function removeSelectorPos(index: number) {
  if (!selectedSymbol.value) return
  const positions = [...(selectedSymbol.value.hmiSelectorPositions || [])]
  positions.splice(index, 1)
  updateSymbol({ hmiSelectorPositions: positions })
}

// HMI Button Action helpers
const buttonAction = computed<ButtonAction>(() => {
  return selectedSymbol.value?.hmiButtonAction ?? { type: 'digital_output' }
})

const sequenceList = computed(() => scriptsComposable.sequences.value || [])
const scriptList = computed(() => backendScriptsComposable.scriptsList.value || [])

function updateButtonAction(updates: Partial<ButtonAction>) {
  const current = selectedSymbol.value?.hmiButtonAction ?? { type: 'digital_output' as ButtonActionType }
  updateSymbol({ hmiButtonAction: { ...current, ...updates } })
}

function setButtonActionType(type: ButtonActionType) {
  // Reset to clean action when type changes
  updateSymbol({ hmiButtonAction: { type } })
}

function closePanel() {
  store.pidPropertiesPanelOpen = false
}
</script>

<template>
  <div class="pid-properties-panel">
    <div class="panel-header">
      <span class="panel-title">Properties</span>
      <button class="btn-close-panel" @click="closePanel" title="Close Panel">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>

    <div class="panel-body">
      <!-- Single Symbol Selected -->
      <template v-if="selectedSymbol">
        <div class="prop-section">
          <div class="section-title">Symbol</div>
          <div class="prop-type">{{ symbolDisplayName }}</div>
        </div>

        <div class="prop-section">
          <div class="section-title">Label</div>
          <input
            type="text"
            class="prop-input"
            :value="selectedSymbol.label || ''"
            @change="updateSymbol({ label: ($event.target as HTMLInputElement).value || undefined })"
            :placeholder="OFF_PAGE_CONNECTOR_TYPES.has(selectedSymbol.type) ? 'e.g. TO BOILER' : 'e.g. SOV-101'"
          />
        </div>

        <!-- Off-Page Connector: Linked Page -->
        <div v-if="OFF_PAGE_CONNECTOR_TYPES.has(selectedSymbol.type)" class="prop-section">
          <div class="section-title">Linked Page</div>
          <select
            class="prop-select"
            :value="selectedSymbol.linkedPageId || ''"
            @change="updateSymbol({ linkedPageId: ($event.target as HTMLSelectElement).value || undefined })"
          >
            <option value="">None (not linked)</option>
            <option
              v-for="page in store.pages.filter(p => p.id !== store.currentPageId)"
              :key="page.id"
              :value="page.id"
            >{{ page.name }}</option>
          </select>
          <div class="prop-hint">Double-click in runtime to navigate</div>
        </div>

        <div class="prop-section">
          <div class="section-title">Channel</div>
          <select
            class="prop-select"
            :value="selectedSymbol.channel || ''"
            @change="updateSymbol({ channel: ($event.target as HTMLSelectElement).value || undefined })"
          >
            <option value="">None</option>
            <option v-for="ch in channelNames" :key="ch" :value="ch">{{ ch }}</option>
          </select>
        </div>

        <div class="prop-section">
          <div class="section-title">Color</div>
          <div class="prop-row">
            <input
              type="color"
              class="prop-color"
              :value="selectedSymbol.color || '#60a5fa'"
              @input="updateSymbol({ color: ($event.target as HTMLInputElement).value })"
            />
            <span class="color-hex">{{ selectedSymbol.color || '#60a5fa' }}</span>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Rotation</div>
          <select
            class="prop-select"
            :value="selectedSymbol.rotation || 0"
            @change="updateSymbol({ rotation: Number(($event.target as HTMLSelectElement).value) })"
          >
            <option :value="0">0°</option>
            <option :value="90">90°</option>
            <option :value="180">180°</option>
            <option :value="270">270°</option>
          </select>
        </div>

        <div class="prop-section">
          <div class="section-title">Position / Size</div>
          <div class="prop-grid-4">
            <label class="mini-label">X</label>
            <input type="number" class="prop-input-sm" :value="Math.round(selectedSymbol.x)"
              @change="updateSymbol({ x: Number(($event.target as HTMLInputElement).value) })" />
            <label class="mini-label">Y</label>
            <input type="number" class="prop-input-sm" :value="Math.round(selectedSymbol.y)"
              @change="updateSymbol({ y: Number(($event.target as HTMLInputElement).value) })" />
            <label class="mini-label">W</label>
            <input type="number" class="prop-input-sm" :value="Math.round(selectedSymbol.width)"
              @change="updateSymbol({ width: Number(($event.target as HTMLInputElement).value) })" />
            <label class="mini-label">H</label>
            <input type="number" class="prop-input-sm" :value="Math.round(selectedSymbol.height)"
              @change="updateSymbol({ height: Number(($event.target as HTMLInputElement).value) })" />
          </div>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="selectedSymbol.showValue || false"
              @change="updateSymbol({ showValue: ($event.target as HTMLInputElement).checked })" />
            Show Live Value
          </label>
          <div v-if="selectedSymbol.showValue" class="prop-sub">
            <div class="section-title">Decimals</div>
            <input type="number" class="prop-input-sm" min="0" max="6"
              :value="selectedSymbol.decimals ?? 2"
              @change="updateSymbol({ decimals: Number(($event.target as HTMLInputElement).value) })" />
          </div>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="selectedSymbol.locked || false"
              @change="updateSymbol({ locked: ($event.target as HTMLInputElement).checked })" />
            Locked
          </label>
        </div>

        <!-- HMI Control Properties (type-filtered) -->
        <template v-if="isHmiControl(selectedSymbol.type)">
          <!-- Decimals: display types only -->
          <div v-if="['hmi_numeric','hmi_bar','hmi_gauge','hmi_sparkline','hmi_valve_pos','hmi_setpoint','hmi_annunciator'].includes(selectedSymbol.type)" class="prop-section">
            <div class="section-title">Decimals</div>
            <input type="number" class="prop-input-sm" min="0" max="6"
              :value="selectedSymbol.decimals ?? 1"
              @change="updateSymbol({ decimals: Number(($event.target as HTMLInputElement).value) })" />
          </div>

          <!-- Unit: display types only (not button/toggle/selector) -->
          <div v-if="!['hmi_button','hmi_toggle','hmi_selector','hmi_multistate'].includes(selectedSymbol.type)" class="prop-section">
            <div class="section-title">Unit Override</div>
            <input type="text" class="prop-input"
              :value="selectedSymbol.hmiUnit || ''"
              @change="updateSymbol({ hmiUnit: ($event.target as HTMLInputElement).value || undefined })"
              placeholder="Auto from channel" />
          </div>

          <!-- Value Range: types with min/max scaling -->
          <div v-if="['hmi_bar','hmi_gauge','hmi_valve_pos','hmi_setpoint'].includes(selectedSymbol.type)" class="prop-section">
            <div class="section-title">Value Range</div>
            <div class="prop-grid-4">
              <label class="mini-label">Min</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiMinValue ?? 0"
                @change="updateSymbol({ hmiMinValue: Number(($event.target as HTMLInputElement).value) })" />
              <label class="mini-label">Max</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiMaxValue ?? 100"
                @change="updateSymbol({ hmiMaxValue: Number(($event.target as HTMLInputElement).value) })" />
            </div>
          </div>

          <!-- Alarm Thresholds: types that check alarm state -->
          <div v-if="['hmi_numeric','hmi_bar','hmi_gauge','hmi_sparkline','hmi_valve_pos','hmi_setpoint','hmi_annunciator','hmi_led'].includes(selectedSymbol.type)" class="prop-section">
            <div class="section-title">Alarm Thresholds</div>
            <div class="prop-grid-4">
              <label class="mini-label">Hi</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiAlarmHigh ?? ''"
                @change="updateSymbol({ hmiAlarmHigh: ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : undefined })"
                placeholder="—" />
              <label class="mini-label">Lo</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiAlarmLow ?? ''"
                @change="updateSymbol({ hmiAlarmLow: ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : undefined })"
                placeholder="—" />
            </div>
          </div>

          <!-- Warning Thresholds: same types as alarm -->
          <div v-if="['hmi_numeric','hmi_bar','hmi_gauge','hmi_sparkline','hmi_valve_pos','hmi_setpoint','hmi_annunciator','hmi_led'].includes(selectedSymbol.type)" class="prop-section">
            <div class="section-title">Warning Thresholds</div>
            <div class="prop-grid-4">
              <label class="mini-label">Hi</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiWarningHigh ?? ''"
                @change="updateSymbol({ hmiWarningHigh: ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : undefined })"
                placeholder="—" />
              <label class="mini-label">Lo</label>
              <input type="number" class="prop-input-sm"
                :value="selectedSymbol.hmiWarningLow ?? ''"
                @change="updateSymbol({ hmiWarningLow: ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : undefined })"
                placeholder="—" />
            </div>
          </div>

          <div v-if="selectedSymbol.type === 'hmi_bar'" class="prop-section">
            <div class="section-title">Orientation</div>
            <select class="prop-select"
              :value="selectedSymbol.hmiOrientation || 'horizontal'"
              @change="updateSymbol({ hmiOrientation: ($event.target as HTMLSelectElement).value as 'horizontal' | 'vertical' })">
              <option value="horizontal">Horizontal</option>
              <option value="vertical">Vertical</option>
            </select>
          </div>

          <!-- Command Button: action config -->
          <template v-if="selectedSymbol.type === 'hmi_button'">
            <div class="prop-section">
              <div class="section-title">Action Type</div>
              <select class="prop-select"
                :value="buttonAction.type"
                @change="setButtonActionType(($event.target as HTMLSelectElement).value as ButtonActionType)">
                <option value="digital_output">Digital Output</option>
                <option value="mqtt_publish">MQTT Publish</option>
                <option value="script_run">Run Sequence</option>
                <option value="script_oneshot">Run Script (One-Shot)</option>
                <option value="variable_set">Set Variable</option>
                <option value="variable_reset">Reset Variable</option>
                <option value="system_command">System Command</option>
              </select>
            </div>

            <!-- Digital Output fields -->
            <div v-if="buttonAction.type === 'digital_output'" class="prop-section">
              <div class="section-title">Channel</div>
              <select class="prop-select"
                :value="buttonAction.channel || ''"
                @change="updateButtonAction({ channel: ($event.target as HTMLSelectElement).value || undefined })">
                <option value="">-- Select --</option>
                <option v-for="ch in channelNames" :key="ch" :value="ch">{{ ch }}</option>
              </select>
              <div class="section-title">Set Value</div>
              <input type="number" class="prop-input-sm"
                :value="buttonAction.setValue ?? 1"
                @change="updateButtonAction({ setValue: Number(($event.target as HTMLInputElement).value) })" />
              <div class="section-title">Pulse (ms, 0=toggle)</div>
              <input type="number" class="prop-input-sm" min="0"
                :value="buttonAction.pulseMs ?? 0"
                @change="updateButtonAction({ pulseMs: Number(($event.target as HTMLInputElement).value) || undefined })" />
            </div>

            <!-- MQTT Publish fields -->
            <div v-if="buttonAction.type === 'mqtt_publish'" class="prop-section">
              <div class="section-title">Topic</div>
              <input type="text" class="prop-input"
                :value="buttonAction.topic || ''"
                @change="updateButtonAction({ topic: ($event.target as HTMLInputElement).value })"
                placeholder="e.g. command/custom" />
              <div class="section-title">Payload</div>
              <input type="text" class="prop-input"
                :value="buttonAction.payload || ''"
                @change="updateButtonAction({ payload: ($event.target as HTMLInputElement).value })"
                placeholder="e.g. {}" />
            </div>

            <!-- Script Run (Sequence) fields -->
            <div v-if="buttonAction.type === 'script_run'" class="prop-section">
              <div class="section-title">Sequence</div>
              <select class="prop-select"
                :value="buttonAction.sequenceId || ''"
                @change="updateButtonAction({ sequenceId: ($event.target as HTMLSelectElement).value || undefined })">
                <option value="">-- Select --</option>
                <option v-for="seq in sequenceList" :key="seq.id" :value="seq.id">{{ seq.name }}</option>
              </select>
            </div>

            <!-- Script One-Shot fields -->
            <div v-if="buttonAction.type === 'script_oneshot'" class="prop-section">
              <div class="section-title">Script</div>
              <select class="prop-select"
                :value="buttonAction.scriptName || ''"
                @change="updateButtonAction({ scriptName: ($event.target as HTMLSelectElement).value || undefined })">
                <option value="">-- Select --</option>
                <option v-for="s in scriptList" :key="s.id" :value="s.id">{{ s.name || s.id }}</option>
              </select>
            </div>

            <!-- Variable Set fields -->
            <div v-if="buttonAction.type === 'variable_set'" class="prop-section">
              <div class="section-title">Variable ID</div>
              <input type="text" class="prop-input"
                :value="buttonAction.variableId || ''"
                @change="updateButtonAction({ variableId: ($event.target as HTMLInputElement).value })"
                placeholder="e.g. my_counter" />
              <div class="section-title">Value</div>
              <input type="number" class="prop-input-sm"
                :value="buttonAction.variableValue ?? 0"
                @change="updateButtonAction({ variableValue: Number(($event.target as HTMLInputElement).value) })" />
            </div>

            <!-- Variable Reset fields -->
            <div v-if="buttonAction.type === 'variable_reset'" class="prop-section">
              <div class="section-title">Variable ID</div>
              <input type="text" class="prop-input"
                :value="buttonAction.variableId || ''"
                @change="updateButtonAction({ variableId: ($event.target as HTMLInputElement).value })"
                placeholder="e.g. my_counter" />
            </div>

            <!-- System Command fields -->
            <div v-if="buttonAction.type === 'system_command'" class="prop-section">
              <div class="section-title">Command</div>
              <select class="prop-select"
                :value="buttonAction.command || ''"
                @change="updateButtonAction({ command: ($event.target as HTMLSelectElement).value as SystemCommandType })">
                <option value="">-- Select --</option>
                <option value="acquisition_start">Start Acquisition</option>
                <option value="acquisition_stop">Stop Acquisition</option>
                <option value="recording_start">Start Recording</option>
                <option value="recording_stop">Stop Recording</option>
                <option value="alarm_acknowledge_all">Acknowledge All Alarms</option>
                <option value="latch_reset_all">Reset All Latches</option>
              </select>
            </div>
          </template>

          <!-- Sparkline: history samples -->
          <div v-if="selectedSymbol.type === 'hmi_sparkline'" class="prop-section">
            <div class="section-title">History Samples</div>
            <input type="number" class="prop-input-sm" min="10" max="300"
              :value="selectedSymbol.hmiSparklineSamples ?? 60"
              @change="updateSymbol({ hmiSparklineSamples: Number(($event.target as HTMLInputElement).value) })" />
          </div>

          <!-- Multi-State: state definitions -->
          <div v-if="selectedSymbol.type === 'hmi_multistate'" class="prop-section">
            <div class="section-title">States</div>
            <div class="hmi-states-list">
              <div v-for="(st, i) in (selectedSymbol.hmiStates || [])" :key="i" class="hmi-state-row">
                <input type="number" class="prop-input-xs" :value="st.value" placeholder="Val"
                  @change="updateHmiState(i, 'value', Number(($event.target as HTMLInputElement).value))" />
                <input type="text" class="prop-input-xs" :value="st.label" placeholder="Label"
                  @change="updateHmiState(i, 'label', ($event.target as HTMLInputElement).value)" />
                <input type="color" class="prop-color-sm" :value="st.color"
                  @change="updateHmiState(i, 'color', ($event.target as HTMLInputElement).value)" />
                <button class="btn-remove-xs" @click="removeHmiState(i)">x</button>
              </div>
              <button class="btn-add-xs" @click="addHmiState">+ State</button>
            </div>
          </div>

          <!-- Selector Switch: position definitions -->
          <div v-if="selectedSymbol.type === 'hmi_selector'" class="prop-section">
            <div class="section-title">Positions</div>
            <div class="hmi-states-list">
              <div v-for="(pos, i) in (selectedSymbol.hmiSelectorPositions || [])" :key="i" class="hmi-state-row">
                <input type="number" class="prop-input-xs" :value="pos.value" placeholder="Val"
                  @change="updateSelectorPos(i, 'value', Number(($event.target as HTMLInputElement).value))" />
                <input type="text" class="prop-input-xs" :value="pos.label" placeholder="Label"
                  @change="updateSelectorPos(i, 'label', ($event.target as HTMLInputElement).value)" />
                <button class="btn-remove-xs" @click="removeSelectorPos(i)">x</button>
              </div>
              <button class="btn-add-xs" @click="addSelectorPos">+ Position</button>
            </div>
          </div>
        </template>
      </template>

      <!-- Single Pipe Selected -->
      <template v-else-if="selectedPipe">
        <div class="prop-section">
          <div class="section-title">Pipe</div>
          <div class="prop-type">{{ selectedPipe.pathType }}</div>
        </div>

        <div class="prop-section">
          <div class="section-title">Label</div>
          <input
            type="text"
            class="prop-input"
            :value="selectedPipe.label || ''"
            @change="updatePipe({ label: ($event.target as HTMLInputElement).value || undefined })"
            placeholder="e.g. Steam Supply"
          />
          <div class="prop-sub">
            <div class="section-title">Label Position</div>
            <select
              class="prop-select"
              :value="selectedPipe.labelPosition || 'middle'"
              @change="updatePipe({ labelPosition: ($event.target as HTMLSelectElement).value as 'start' | 'middle' | 'end' })"
            >
              <option value="start">Start</option>
              <option value="middle">Middle</option>
              <option value="end">End</option>
            </select>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Color</div>
          <div class="prop-row">
            <input
              type="color"
              class="prop-color"
              :value="selectedPipe.color || '#94a3b8'"
              @input="updatePipe({ color: ($event.target as HTMLInputElement).value })"
            />
            <span class="color-hex">{{ selectedPipe.color || '#94a3b8' }}</span>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Stroke Width</div>
          <input type="number" class="prop-input-sm" min="1" max="20"
            :value="selectedPipe.strokeWidth || 2"
            @change="updatePipe({ strokeWidth: Number(($event.target as HTMLInputElement).value) })" />
        </div>

        <div class="prop-section">
          <div class="section-title">Opacity</div>
          <div class="prop-row">
            <input type="range" min="0" max="1" step="0.05"
              :value="selectedPipe.opacity ?? 1"
              @input="updatePipe({ opacity: Number(($event.target as HTMLInputElement).value) })"
              style="flex: 1;" />
            <span style="font-size: 11px; color: #888; width: 32px; text-align: right;">
              {{ Math.round((selectedPipe.opacity ?? 1) * 100) }}%
            </span>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Path Type</div>
          <select
            class="prop-select"
            :value="selectedPipe.pathType"
            @change="updatePipe({ pathType: ($event.target as HTMLSelectElement).value as 'polyline' | 'bezier' | 'orthogonal' })"
          >
            <option value="polyline">Polyline</option>
            <option value="bezier">Bezier</option>
            <option value="orthogonal">Orthogonal</option>
          </select>
        </div>

        <div class="prop-section" v-if="selectedPipe.pathType !== 'bezier'">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="selectedPipe.rounded || false"
              @change="updatePipe({ rounded: ($event.target as HTMLInputElement).checked })" />
            Rounded Corners
          </label>
          <div v-if="selectedPipe.rounded" class="prop-sub">
            <div class="section-title">Corner Radius</div>
            <input type="number" class="prop-input-sm" min="2" max="50"
              :value="selectedPipe.cornerRadius || 8"
              @change="updatePipe({ cornerRadius: Number(($event.target as HTMLInputElement).value) })" />
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Line Style</div>
          <select
            class="prop-select"
            :value="getDashPreset(selectedPipe)"
            @change="applyDashPreset(($event.target as HTMLSelectElement).value)"
          >
            <option value="solid">Solid</option>
            <option value="dashed">Dashed</option>
            <option value="dotted">Dotted</option>
            <option value="dashdot">Dash-Dot</option>
            <option value="longdash">Long Dash</option>
            <option value="custom">Custom...</option>
          </select>
          <div v-if="getDashPreset(selectedPipe) === 'custom'" class="prop-sub">
            <input type="text" class="prop-input-sm" placeholder="e.g. 8,4,2,4"
              :value="selectedPipe.dashPattern || ''"
              @change="updatePipe({ dashPattern: ($event.target as HTMLInputElement).value || undefined, dashed: undefined })" />
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Medium</div>
          <select
            class="prop-select"
            :value="selectedPipe.medium || ''"
            @change="updatePipe({ medium: (($event.target as HTMLSelectElement).value || undefined) as any })"
          >
            <option value="">None</option>
            <option value="water">Water</option>
            <option value="steam">Steam</option>
            <option value="gas">Gas</option>
            <option value="air">Air</option>
            <option value="oil">Oil</option>
            <option value="chemical">Chemical</option>
            <option value="electrical">Electrical</option>
            <option value="signal">Signal</option>
          </select>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="selectedPipe.animated || false"
              @change="updatePipe({ animated: ($event.target as HTMLInputElement).checked })" />
            Flow Animation
          </label>
          <div v-if="selectedPipe.animated" class="prop-sub">
            <div class="section-title">Flow Channel</div>
            <select
              class="prop-select"
              :value="selectedPipe.flowChannel || ''"
              @change="updatePipe({ flowChannel: ($event.target as HTMLSelectElement).value || undefined })"
            >
              <option value="">None</option>
              <option v-for="ch in channelNames" :key="ch" :value="ch">{{ ch }}</option>
            </select>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Start Arrow</div>
          <select
            class="prop-select"
            :value="resolvePipeArrow(selectedPipe.startArrow)"
            @change="updatePipe({ startArrow: ($event.target as HTMLSelectElement).value as any })"
          >
            <option value="none">None</option>
            <option value="arrow">Arrow (filled)</option>
            <option value="open">Arrow (open)</option>
            <option value="dot">Dot</option>
            <option value="diamond">Diamond</option>
            <option value="bar">Bar</option>
          </select>
        </div>

        <div class="prop-section">
          <div class="section-title">End Arrow</div>
          <select
            class="prop-select"
            :value="resolvePipeArrow(selectedPipe.endArrow)"
            @change="updatePipe({ endArrow: ($event.target as HTMLSelectElement).value as any })"
          >
            <option value="none">None</option>
            <option value="arrow">Arrow (filled)</option>
            <option value="open">Arrow (open)</option>
            <option value="dot">Dot</option>
            <option value="diamond">Diamond</option>
            <option value="bar">Bar</option>
          </select>
        </div>

        <div class="prop-section">
          <div class="section-title">Line Jumps</div>
          <select
            class="prop-select"
            :value="selectedPipe.jumpStyle || 'none'"
            @change="updatePipe({ jumpStyle: ($event.target as HTMLSelectElement).value as any })"
          >
            <option value="none">None</option>
            <option value="arc">Arc</option>
            <option value="gap">Gap</option>
          </select>
          <div v-if="selectedPipe.jumpStyle && selectedPipe.jumpStyle !== 'none'" class="prop-sub">
            <div class="section-title">Jump Size</div>
            <input type="number" class="prop-input-sm" min="4" max="24"
              :value="selectedPipe.jumpSize || 8"
              @change="updatePipe({ jumpSize: Number(($event.target as HTMLInputElement).value) })" />
          </div>
        </div>

        <div class="prop-section">
          <button class="prop-btn" @click="reversePipe">Reverse Direction</button>
        </div>
      </template>

      <!-- Multi Selection -->
      <template v-else-if="selectionCount > 1">
        <div class="prop-section">
          <div class="section-title">Selection</div>
          <div class="prop-type">{{ selectionCount }} items selected</div>
        </div>
        <div class="prop-section">
          <div class="section-title">Bulk Color</div>
          <input
            type="color"
            class="prop-color"
            value="#60a5fa"
            @input="(e) => {
              const color = (e.target as HTMLInputElement).value
              selectedSymbolIds.forEach(id => store.updatePidSymbolWithUndo(id, { color }))
              selectedPipeIds.forEach(id => store.updatePidPipeWithUndo(id, { color }))
            }"
          />
        </div>
      </template>

      <!-- No Selection -->
      <template v-else>
        <div class="prop-section">
          <div class="section-title">Canvas</div>
          <div class="prop-type">No selection</div>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="store.pidGridSnapEnabled"
              @change="store.togglePidGridSnap()" />
            Grid Snap
          </label>
          <div v-if="store.pidGridSnapEnabled" class="prop-sub">
            <div class="section-title">Grid Size</div>
            <select class="prop-select"
              :value="store.pidGridSize"
              @change="store.setPidGridSize(Number(($event.target as HTMLSelectElement).value))">
              <option :value="5">5px</option>
              <option :value="10">10px</option>
              <option :value="15">15px</option>
              <option :value="20">20px</option>
              <option :value="25">25px</option>
              <option :value="30">30px</option>
              <option :value="40">40px</option>
              <option :value="50">50px</option>
            </select>
          </div>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="store.pidShowGrid"
              @change="store.pidShowGrid = !store.pidShowGrid" />
            Show Grid
          </label>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="store.pidColorScheme === 'isa101'"
              @change="store.togglePidColorScheme()" />
            ISA-101 Mode
          </label>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.pid-properties-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: 240px;
  height: 100%;
  background: #0f0f1a;
  border-left: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 50;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #2a2a4a;
  background: #1a1a2e;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn-close-panel {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.btn-close-panel:hover {
  color: #fff;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.panel-body::-webkit-scrollbar {
  width: 6px;
}

.panel-body::-webkit-scrollbar-thumb {
  background: #2a2a4a;
  border-radius: 3px;
}

.prop-section {
  margin-bottom: 10px;
}

.section-title {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 4px;
}

.prop-type {
  font-size: 12px;
  color: #cbd5e1;
  padding: 4px 0;
}

.prop-input,
.prop-select {
  width: 100%;
  padding: 5px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  outline: none;
  box-sizing: border-box;
}

.prop-input:focus,
.prop-select:focus {
  border-color: #3b82f6;
}

.prop-hint {
  font-size: 10px;
  color: #666;
  font-style: italic;
  margin-top: 3px;
}

.prop-input::placeholder {
  color: #555;
}

.prop-input-sm {
  width: 100%;
  padding: 3px 6px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 3px;
  color: #fff;
  font-size: 11px;
  outline: none;
  box-sizing: border-box;
}

.prop-input-sm:focus {
  border-color: #3b82f6;
}

.prop-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prop-color {
  width: 28px;
  height: 28px;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  cursor: pointer;
  padding: 0;
  background: transparent;
}

.color-hex {
  font-size: 11px;
  color: #888;
  font-family: monospace;
}

.prop-grid-4 {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr;
  gap: 4px;
  align-items: center;
}

.mini-label {
  font-size: 10px;
  color: #666;
  font-weight: 600;
  text-align: right;
  padding-right: 2px;
}

.prop-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #cbd5e1;
  cursor: pointer;
  padding: 3px 0;
}

.prop-checkbox input[type="checkbox"] {
  accent-color: #3b82f6;
}

.prop-sub {
  margin-top: 6px;
  padding-left: 12px;
  border-left: 2px solid #2a2a4a;
}

.hmi-states-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hmi-state-row {
  display: flex;
  gap: 3px;
  align-items: center;
}

.prop-input-xs {
  width: 46px;
  padding: 3px 4px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 3px;
  color: #fff;
  font-size: 11px;
}

.prop-color-sm {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid #2a2a4a;
  border-radius: 3px;
  cursor: pointer;
  background: transparent;
}

.btn-remove-xs {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  line-height: 1;
}

.btn-remove-xs:hover {
  color: #ef4444;
}

.btn-add-xs {
  background: transparent;
  border: 1px dashed #2a2a4a;
  border-radius: 3px;
  color: #888;
  cursor: pointer;
  font-size: 11px;
  padding: 3px 8px;
  margin-top: 2px;
}

.btn-add-xs:hover {
  border-color: #3b82f6;
  color: #3b82f6;
}
.prop-btn {
  width: 100%;
  padding: 5px 10px;
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  text-align: center;
}

.prop-btn:hover {
  background: #334155;
}
</style>
