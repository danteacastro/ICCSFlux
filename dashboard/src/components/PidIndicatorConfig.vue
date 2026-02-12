<script setup lang="ts">
/**
 * PidIndicatorConfig - Properties form for a selected indicator in the block editor.
 *
 * Allows configuring type, channel/interlock binding, ISA labels, shape, signal line,
 * and ISA 5.1 signal line type.
 */

import { computed, ref } from 'vue'
import type { PidIndicator, PidIndicatorType, PidIndicatorShape, PidSignalLineType } from '../types'
import type { Interlock } from '../types'

const props = defineProps<{
  indicator: PidIndicator
  channelNames: string[]
  interlocks: Interlock[]
}>()

const emit = defineEmits<{
  (e: 'update', updates: Partial<PidIndicator>): void
  (e: 'delete'): void
}>()

const indicatorTypes: { value: PidIndicatorType; label: string }[] = [
  { value: 'channel_value', label: 'Channel Value' },
  { value: 'interlock', label: 'Interlock' },
  { value: 'alarm_annotation', label: 'Alarm Annotation' },
  { value: 'control_output', label: 'Control Output' },
]

const shapes: { value: PidIndicatorShape; label: string }[] = [
  { value: 'circle', label: 'Circle — Field (ISA)' },
  { value: 'circleBar', label: 'Circle+Bar — Panel (ISA)' },
  { value: 'dashedCircle', label: 'Dashed — Behind Panel (ISA)' },
  { value: 'circleInSquare', label: 'Circle/Square — Local Panel (ISA)' },
  { value: 'square', label: 'Square — DCS/Computer (ISA)' },
  { value: 'diamond', label: 'Diamond — PLC/Interlock (ISA)' },
  { value: 'hexagon', label: 'Hexagon — Shared Display (ISA)' },
  { value: 'flag', label: 'Flag — Alarm' },
]

const signalLineTypes: { value: PidSignalLineType; label: string; pattern: string }[] = [
  { value: 'undefined', label: 'Solid (Process Connection)', pattern: '' },
  { value: 'pneumatic', label: 'Pneumatic (ISA)', pattern: '--- ---' },
  { value: 'electrical', label: 'Electrical (ISA)', pattern: '· · · ·' },
  { value: 'capillary', label: 'Capillary (ISA)', pattern: '-·-·-·' },
  { value: 'hydraulic', label: 'Hydraulic (ISA)', pattern: '-··-··' },
  { value: 'electromagnetic', label: 'Electromagnetic (ISA)', pattern: '···---' },
  { value: 'software', label: 'Software/Data Link', pattern: '═══' },
]

// --- ISA 5.1 Function Letter Reference ---
// First letter = measured/initiating variable, subsequent = function/modifier
const ISA_FIRST_LETTERS: { code: string; variable: string }[] = [
  { code: 'A', variable: 'Analysis (composition, pH, O2, etc.)' },
  { code: 'B', variable: 'Burner/Combustion' },
  { code: 'C', variable: 'Conductivity' },
  { code: 'D', variable: 'Density/Specific Gravity' },
  { code: 'E', variable: 'Voltage (EMF)' },
  { code: 'F', variable: 'Flow Rate' },
  { code: 'G', variable: 'Gauging/Position/Length' },
  { code: 'H', variable: 'Hand (manual)' },
  { code: 'I', variable: 'Current (electrical)' },
  { code: 'J', variable: 'Power' },
  { code: 'K', variable: 'Time/Schedule' },
  { code: 'L', variable: 'Level' },
  { code: 'M', variable: 'Moisture/Humidity' },
  { code: 'N', variable: 'User Choice' },
  { code: 'O', variable: 'User Choice' },
  { code: 'P', variable: 'Pressure/Vacuum' },
  { code: 'Q', variable: 'Quantity/Event' },
  { code: 'R', variable: 'Radiation' },
  { code: 'S', variable: 'Speed/Frequency' },
  { code: 'T', variable: 'Temperature' },
  { code: 'U', variable: 'Multivariable' },
  { code: 'V', variable: 'Vibration' },
  { code: 'W', variable: 'Weight/Force' },
  { code: 'X', variable: 'Unclassified' },
  { code: 'Y', variable: 'Event/State/Presence' },
  { code: 'Z', variable: 'Position/Dimension' },
]

const ISA_FUNCTION_LETTERS: { code: string; func: string }[] = [
  { code: 'A', func: 'Alarm' },
  { code: 'C', func: 'Controller' },
  { code: 'D', func: 'Differential' },
  { code: 'E', func: 'Primary Element/Sensor' },
  { code: 'G', func: 'Glass/Gauge/Viewing' },
  { code: 'H', func: 'High' },
  { code: 'I', func: 'Indicator' },
  { code: 'J', func: 'Scan' },
  { code: 'K', func: 'Control Station' },
  { code: 'L', func: 'Low / Light' },
  { code: 'N', func: 'User Choice' },
  { code: 'O', func: 'Orifice/Restriction' },
  { code: 'Q', func: 'Integrate/Totalize' },
  { code: 'R', func: 'Recorder' },
  { code: 'S', func: 'Switch' },
  { code: 'T', func: 'Transmitter' },
  { code: 'V', func: 'Valve/Damper/Louver' },
  { code: 'W', func: 'Well/Probe' },
  { code: 'X', func: 'Unclassified' },
  { code: 'Y', func: 'Relay/Compute/Convert' },
  { code: 'Z', func: 'Driver/Actuator/Final Element' },
]

// Common ISA letter combinations for quick-pick
const ISA_COMMON_COMBOS = [
  'TE', 'TI', 'TT', 'TIC', 'TAH', 'TAL', 'TSH', 'TSL', 'TR',
  'PT', 'PI', 'PIC', 'PAH', 'PAL', 'PSH', 'PSL', 'PDT',
  'FT', 'FI', 'FIC', 'FAH', 'FAL', 'FE', 'FV', 'FQ',
  'LT', 'LI', 'LIC', 'LAH', 'LAL', 'LSH', 'LSL', 'LG',
  'AT', 'AI', 'AIC', 'AE',
  'HV', 'HS', 'HC',
  'XV', 'XS', 'ZSH', 'ZSL',
] as const

const isaInputFocused = ref(false)
const isaFilterText = ref('')

const filteredIsaCombos = computed(() => {
  const q = (isaFilterText.value || props.indicator.isaLetters || '').toUpperCase()
  if (!q) return ISA_COMMON_COMBOS.slice(0, 15)
  return ISA_COMMON_COMBOS.filter(c => c.startsWith(q))
})

const isaHint = computed(() => {
  const letters = (props.indicator.isaLetters || '').toUpperCase()
  if (!letters) return ''
  const first = ISA_FIRST_LETTERS.find(l => l.code === letters[0])
  if (!first) return ''
  const parts = [first.variable]
  for (let i = 1; i < letters.length; i++) {
    const fn = ISA_FUNCTION_LETTERS.find(l => l.code === letters[i])
    if (fn) parts.push(fn.func)
  }
  return parts.join(' + ')
})

function selectIsaCombo(combo: string) {
  emit('update', { isaLetters: combo })
  isaInputFocused.value = false
}

function onIsaInput(value: string) {
  isaFilterText.value = value
  emit('update', { isaLetters: value.toUpperCase() || undefined })
}

function onIsaBlur() {
  window.setTimeout(() => { isaInputFocused.value = false }, 200)
}

const showChannelBinding = computed(() =>
  props.indicator.type === 'channel_value' ||
  props.indicator.type === 'alarm_annotation' ||
  props.indicator.type === 'control_output'
)

const showInterlockBinding = computed(() =>
  props.indicator.type === 'interlock'
)

function onTypeChange(type: PidIndicatorType) {
  const shapeMap: Record<PidIndicatorType, PidIndicatorShape> = {
    channel_value: 'circle',
    interlock: 'diamond',
    alarm_annotation: 'flag',
    control_output: 'square',
  }
  emit('update', { type, shape: shapeMap[type] })
}
</script>

<template>
  <div class="indicator-config">
    <h4 class="config-title">Indicator Properties</h4>

    <!-- Type -->
    <div class="form-group">
      <label>Type</label>
      <select
        :value="indicator.type"
        @change="onTypeChange(($event.target as HTMLSelectElement).value as PidIndicatorType)"
        class="form-select"
      >
        <option v-for="t in indicatorTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
      </select>
    </div>

    <!-- Channel binding -->
    <div v-if="showChannelBinding" class="form-group">
      <label>Channel</label>
      <select
        :value="indicator.channel || ''"
        @change="emit('update', { channel: ($event.target as HTMLSelectElement).value || undefined })"
        class="form-select"
      >
        <option value="">— None —</option>
        <option v-for="ch in channelNames" :key="ch" :value="ch">{{ ch }}</option>
      </select>
    </div>

    <!-- Interlock binding -->
    <div v-if="showInterlockBinding" class="form-group">
      <label>Interlock</label>
      <select
        :value="indicator.interlockId || ''"
        @change="emit('update', { interlockId: ($event.target as HTMLSelectElement).value || undefined })"
        class="form-select"
      >
        <option value="">— None —</option>
        <option v-for="il in interlocks" :key="il.id" :value="il.id">{{ il.name }}</option>
      </select>
    </div>

    <!-- Label -->
    <div class="form-group">
      <label>Label</label>
      <input
        type="text"
        :value="indicator.label || ''"
        @input="emit('update', { label: ($event.target as HTMLInputElement).value || undefined })"
        class="form-input"
        placeholder="e.g. TE-305"
      />
    </div>

    <!-- ISA Letters (with autocomplete) -->
    <div class="form-group isa-letters-group">
      <label>ISA Letters</label>
      <div class="isa-input-wrapper">
        <input
          type="text"
          :value="indicator.isaLetters || ''"
          @input="onIsaInput(($event.target as HTMLInputElement).value)"
          @focus="isaInputFocused = true"
          @blur="onIsaBlur"
          class="form-input"
          placeholder="e.g. TE, FIC, LSH"
          autocomplete="off"
        />
        <div v-if="isaInputFocused && filteredIsaCombos.length > 0" class="isa-dropdown">
          <button
            v-for="combo in filteredIsaCombos"
            :key="combo"
            class="isa-option"
            @mousedown.prevent="selectIsaCombo(combo)"
          >{{ combo }}</button>
        </div>
      </div>
      <span v-if="isaHint" class="isa-hint">{{ isaHint }}</span>
    </div>

    <!-- Tag Number -->
    <div class="form-group">
      <label>Tag Number</label>
      <input
        type="text"
        :value="indicator.tagNumber || ''"
        @input="emit('update', { tagNumber: ($event.target as HTMLInputElement).value || undefined })"
        class="form-input"
        placeholder="e.g. 305, 3381"
      />
    </div>

    <!-- Shape -->
    <div class="form-group">
      <label>Shape</label>
      <select
        :value="indicator.shape"
        @change="emit('update', { shape: ($event.target as HTMLSelectElement).value as PidIndicatorShape })"
        class="form-select"
      >
        <option v-for="s in shapes" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
    </div>

    <!-- Show Value + Decimals (for channel-bound indicators) -->
    <div v-if="showChannelBinding" class="form-group form-row">
      <label class="checkbox-label">
        <input
          type="checkbox"
          :checked="indicator.showValue"
          @change="emit('update', { showValue: ($event.target as HTMLInputElement).checked })"
        />
        Show Value
      </label>
      <div v-if="indicator.showValue" class="decimals-input">
        <label>Dec</label>
        <input
          type="number"
          :value="indicator.decimals ?? 1"
          min="0"
          max="6"
          @input="emit('update', { decimals: parseInt(($event.target as HTMLInputElement).value) || 0 })"
          class="form-input narrow"
        />
      </div>
    </div>

    <!-- Signal Line Length -->
    <div class="form-group">
      <label>Signal Line Length</label>
      <div class="slider-row">
        <input
          type="range"
          :value="indicator.signalLineLength ?? 30"
          min="10"
          max="80"
          step="2"
          @input="emit('update', { signalLineLength: parseInt(($event.target as HTMLInputElement).value) })"
        />
        <span class="slider-value">{{ indicator.signalLineLength ?? 30 }}px</span>
      </div>
    </div>

    <!-- ISA Signal Line Type -->
    <div class="form-group">
      <label>Signal Line Type (ISA 5.1)</label>
      <select
        :value="indicator.signalType || 'pneumatic'"
        @change="emit('update', { signalType: ($event.target as HTMLSelectElement).value as PidSignalLineType })"
        class="form-select"
      >
        <option v-for="s in signalLineTypes" :key="s.value" :value="s.value">
          {{ s.label }}{{ s.pattern ? ` [${s.pattern}]` : '' }}
        </option>
      </select>
    </div>

    <!-- Position info -->
    <div class="form-group position-info">
      <span class="edge-badge">{{ indicator.edge }}</span>
      <span class="offset-text">{{ (indicator.edgeOffset * 100).toFixed(0) }}% along edge</span>
    </div>

    <!-- Delete -->
    <button class="delete-btn" @click="emit('delete')">Delete Indicator</button>
  </div>
</template>

<style scoped>
.indicator-config {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.config-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 4px;
  padding-bottom: 6px;
  border-bottom: 1px solid #334155;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.form-group > label {
  font-size: 0.7rem;
  color: #94a3b8;
  font-weight: 500;
}

.form-row {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.form-select,
.form-input {
  background: #1e293b;
  border: 1px solid #334155;
  color: #e2e8f0;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 0.75rem;
}

.form-input.narrow {
  width: 48px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #cbd5e1;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  accent-color: #3b82f6;
}

.decimals-input {
  display: flex;
  align-items: center;
  gap: 4px;
}

.decimals-input label {
  font-size: 0.7rem;
  color: #94a3b8;
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.slider-row input[type="range"] {
  flex: 1;
  accent-color: #3b82f6;
}

.slider-value {
  font-size: 0.7rem;
  color: #94a3b8;
  min-width: 36px;
  text-align: right;
}

.position-info {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  padding-top: 4px;
  border-top: 1px solid #334155;
}

.edge-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  background: #334155;
  color: #94a3b8;
  padding: 1px 6px;
  border-radius: 3px;
}

.offset-text {
  font-size: 0.7rem;
  color: #64748b;
}

.delete-btn {
  margin-top: 8px;
  padding: 6px 12px;
  border: 1px solid #dc2626;
  background: transparent;
  color: #dc2626;
  border-radius: 4px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: background 0.15s;
}

.delete-btn:hover {
  background: #dc26261a;
}

/* ISA Letters autocomplete */
.isa-letters-group {
  position: relative;
}

.isa-input-wrapper {
  position: relative;
}

.isa-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 4px;
  max-height: 160px;
  overflow-y: auto;
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 4px;
}

.isa-option {
  background: #334155;
  border: 1px solid #475569;
  color: #e2e8f0;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-family: monospace;
  cursor: pointer;
  transition: background 0.1s;
}

.isa-option:hover {
  background: #3b82f6;
  border-color: #3b82f6;
}

.isa-hint {
  font-size: 0.65rem;
  color: #64748b;
  font-style: italic;
  margin-top: 1px;
}
</style>
