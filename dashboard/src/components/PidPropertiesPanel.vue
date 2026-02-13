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

import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import { useBackendScripts } from '../composables/useBackendScripts'
import type { PidSymbol, PidPipe, PidTextAnnotation, ButtonAction, ButtonActionType, SystemCommandType } from '../types'
import { AUXILIARY_CHANNEL_PRESETS } from '../types'
import { isHmiControl, HMI_CONTROL_CATALOG } from '../constants/hmiControls'
import { SYMBOL_INFO, OFF_PAGE_CONNECTOR_TYPES, getVariantGroup } from '../assets/symbols'
import { isValveSymbol, isTankSymbol } from '../composables/usePidRendering'
import { useResizablePanel } from '../composables/useResizablePanel'
import { useSafety } from '../composables/useSafety'

const store = useDashboardStore()
const scriptsComposable = useScripts()
const backendScriptsComposable = useBackendScripts()
const safety = useSafety()

const availableInterlocks = computed(() => safety.interlocks.value)

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

const selectedTextAnnotation = computed<PidTextAnnotation | null>(() => {
  const ids = store.pidSelectedIds.textAnnotationIds
  if (ids.length !== 1 || selectedSymbolIds.value.length > 0 || selectedPipeIds.value.length > 0) return null
  return store.pidLayer.textAnnotations?.find(t => t.id === ids[0]) || null
})

const selectionCount = computed(() =>
  selectedSymbolIds.value.length + selectedPipeIds.value.length +
  store.pidSelectedIds.textAnnotationIds.length
)

const channelNames = computed(() => Object.keys(store.channels).sort())

// Grouped channel list with type/device metadata for smarter dropdowns
const groupedChannels = computed(() => {
  const groups: Record<string, Array<{ name: string; type: string; unit: string; device: string }>> = {}
  for (const [name, cfg] of Object.entries(store.channels)) {
    if (cfg.visible === false) continue
    const device = cfg.physical_channel?.split('/')[0] || cfg.group || 'Other'
    if (!groups[device]) groups[device] = []
    groups[device].push({
      name,
      type: cfg.channel_type || '',
      unit: cfg.unit || '',
      device,
    })
  }
  // Sort channels within each group
  for (const key of Object.keys(groups)) {
    groups[key]!.sort((a, b) => a.name.localeCompare(b.name))
  }
  return groups
})

// Auto-compose pipe line number from structured attributes
const computedLineNumber = computed<string>(() => {
  const p = selectedPipe.value
  if (!p) return ''
  const parts: string[] = []
  if (p.nominalSize) parts.push(p.nominalSize)
  if (p.fluidCode) parts.push(p.fluidCode)
  if (p.pressureRating) parts.push(p.pressureRating)
  if (p.material) parts.push(p.material)
  return parts.length >= 2 ? parts.join('-') : ''
})

// Loop number duplicate detection (checks all pages)
const loopNumberConflict = computed<string | null>(() => {
  const sym = selectedSymbol.value
  if (!sym?.loopNumber) return null
  const loop = sym.loopNumber.trim()
  if (!loop) return null
  for (const page of store.pages) {
    const pidLayer = page.pidLayer
    if (!pidLayer) continue
    for (const s of pidLayer.symbols) {
      if (s.id === sym.id) continue
      if (s.loopNumber?.trim() === loop) {
        return `${s.label || s.type} (${page.name})`
      }
    }
  }
  return null
})

const autoMatchResult = ref<{ matched: number; total: number } | null>(null)

function runAutoMatch() {
  autoMatchResult.value = store.pidAutoMatchChannels(selectedSymbolIds.value)
  globalThis.setTimeout(() => { autoMatchResult.value = null }, 4000)
}

// Alarm config summary for the selected symbol's channel
const symbolAlarmConfig = computed(() => {
  const ch = selectedSymbol.value?.channel
  if (!ch) return null
  return safety.getAlarmConfig(ch) || null
})

// Interlock status for the selected symbol's bound interlock
const symbolInterlockStatus = computed(() => {
  const ilId = selectedSymbol.value?.interlockId
  if (!ilId) return null
  return safety.interlockStatuses.value.find(s => s.id === ilId) || null
})

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

// Variant group for current symbol (for type switching)
const symbolVariants = computed(() => {
  if (!selectedSymbol.value) return []
  return getVariantGroup(selectedSymbol.value.type)
})

// Symbol property updates
function updateSymbol(updates: Partial<PidSymbol>) {
  if (!selectedSymbol.value) return
  store.updatePidSymbolWithUndo(selectedSymbol.value.id, updates)
}

// Text annotation property updates
function updateTextAnnotation(updates: Partial<PidTextAnnotation>) {
  if (!selectedTextAnnotation.value) return
  store.updatePidTextAnnotation(selectedTextAnnotation.value.id, updates)
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

// Auxiliary channel helpers
function addAuxiliaryChannel() {
  if (!selectedSymbol.value) return
  const channels = [...(selectedSymbol.value.auxiliaryChannels || [])]
  channels.push({ role: '', channel: '', label: 'New Channel' })
  updateSymbol({ auxiliaryChannels: channels })
}

function updateAuxiliaryChannel(index: number, field: string, value: string | number | boolean | undefined) {
  if (!selectedSymbol.value) return
  const channels = [...(selectedSymbol.value.auxiliaryChannels || [])]
  if (channels[index]) {
    channels[index] = { ...channels[index], [field]: value }
    updateSymbol({ auxiliaryChannels: channels })
  }
}

function removeAuxiliaryChannel(index: number) {
  if (!selectedSymbol.value) return
  const channels = [...(selectedSymbol.value.auxiliaryChannels || [])]
  channels.splice(index, 1)
  updateSymbol({ auxiliaryChannels: channels.length > 0 ? channels : undefined })
}

function applyAuxiliaryPreset(presetKey: string) {
  if (!selectedSymbol.value) return
  const preset = AUXILIARY_CHANNEL_PRESETS[presetKey]
  if (!preset) return
  const channels = preset.map(p => ({
    ...p,
    channel: '', // user fills in the channel
  }))
  updateSymbol({ auxiliaryChannels: channels })
}

const availablePresets = computed(() =>
  Object.entries(AUXILIARY_CHANNEL_PRESETS).map(([key, slots]) => ({
    key,
    label: key.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase()).trim(),
    slotCount: slots.length,
  }))
)

function closePanel() {
  store.pidPropertiesPanelOpen = false
}

function toggleCollapse() {
  store.pidPropertiesPanelCollapsed = !store.pidPropertiesPanelCollapsed
}

// Resizable panel
const { isResizing, onMouseDown: onResizeStart } = useResizablePanel({
  side: 'right',
  minWidth: 160,
  maxWidth: 400,
  getWidth: () => store.pidPropertiesPanelWidth,
  setWidth: (w) => { store.pidPropertiesPanelWidth = w },
})
</script>

<template>
  <!-- Collapse/expand tab — vertically centered on panel edge -->
  <div
    class="panel-tab panel-tab-right"
    :style="{ right: store.pidPropertiesPanelCollapsed ? '0px' : (store.pidPropertiesPanelWidth - 1) + 'px' }"
    @click="toggleCollapse"
    :title="store.pidPropertiesPanelCollapsed ? 'Expand Properties (])' : 'Collapse Properties (])'"
  >
    <svg width="10" height="18" viewBox="0 0 10 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline v-if="store.pidPropertiesPanelCollapsed" points="7 2 2 9 7 16" />
      <polyline v-else points="3 2 8 9 3 16" />
    </svg>
  </div>

  <!-- Full panel -->
  <div
    v-if="!store.pidPropertiesPanelCollapsed"
    class="pid-properties-panel"
    :style="{ width: store.pidPropertiesPanelWidth + 'px' }"
  >
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
          <select
            v-if="symbolVariants.length > 1"
            class="prop-select variant-select"
            :value="selectedSymbol!.type"
            @change="updateSymbol({ type: ($event.target as HTMLSelectElement).value as any })"
          >
            <option v-for="v in symbolVariants" :key="v.type" :value="v.type">{{ v.label }}</option>
          </select>
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

        <!-- Loop Number (ISA 5.1) -->
        <div class="prop-section">
          <div class="section-title">Loop Number</div>
          <input
            type="text"
            class="prop-input"
            :value="selectedSymbol.loopNumber || ''"
            @change="updateSymbol({ loopNumber: ($event.target as HTMLInputElement).value || undefined })"
            placeholder="e.g. 100, 200A"
          />
          <div v-if="loopNumberConflict" class="prop-info-badge info-warn">
            <span class="info-icon">&#x26A0;</span>
            <span class="info-text">Duplicate: also on {{ loopNumberConflict }}</span>
          </div>
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
            <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="device">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">
                {{ ch.name }}{{ ch.unit ? ` (${ch.unit})` : '' }}{{ ch.type ? ` [${ch.type}]` : '' }}
              </option>
            </optgroup>
          </select>
          <!-- Alarm config summary from SafetyTab -->
          <div v-if="symbolAlarmConfig" class="prop-info-badge">
            <span class="info-icon">&#x26A0;</span>
            <span class="info-text">
              Alarm thresholds:
              <template v-if="symbolAlarmConfig.high_high != null"> HiHi={{ symbolAlarmConfig.high_high }}</template>
              <template v-if="symbolAlarmConfig.high != null"> Hi={{ symbolAlarmConfig.high }}</template>
              <template v-if="symbolAlarmConfig.low != null"> Lo={{ symbolAlarmConfig.low }}</template>
              <template v-if="symbolAlarmConfig.low_low != null"> LoLo={{ symbolAlarmConfig.low_low }}</template>
            </span>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Interlock</div>
          <select class="prop-select"
            :value="selectedSymbol.interlockId || ''"
            @change="updateSymbol({ interlockId: ($event.target as HTMLSelectElement).value || undefined })"
          >
            <option value="">None</option>
            <option v-for="il in availableInterlocks" :key="il.id" :value="il.id">
              {{ il.name }}{{ il.silRating ? ` (${il.silRating})` : '' }}
            </option>
          </select>
          <!-- Interlock status preview -->
          <div v-if="symbolInterlockStatus" class="prop-info-badge" :class="{
            'info-ok': symbolInterlockStatus.satisfied && !symbolInterlockStatus.bypassed,
            'info-warn': symbolInterlockStatus.bypassed,
            'info-fail': !symbolInterlockStatus.satisfied && !symbolInterlockStatus.bypassed,
          }">
            <span class="info-icon">{{ symbolInterlockStatus.bypassed ? '&#x23ED;' : symbolInterlockStatus.satisfied ? '&#x2705;' : '&#x1F6D1;' }}</span>
            <span class="info-text">
              {{ symbolInterlockStatus.bypassed ? 'Bypassed' : symbolInterlockStatus.satisfied ? 'Satisfied' : 'TRIPPED' }}
            </span>
          </div>
        </div>

        <!-- Auxiliary Channels (multi-register equipment: heaters, VFDs, PID loops) -->
        <div class="prop-section">
          <div class="section-title">
            Auxiliary Channels
            <button class="btn-add-inline" @click="addAuxiliaryChannel" title="Add channel binding">+</button>
          </div>
          <!-- Preset selector -->
          <div v-if="!selectedSymbol.auxiliaryChannels?.length" class="prop-row">
            <select class="prop-select" @change="applyAuxiliaryPreset(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
              <option value="">Load preset...</option>
              <option v-for="p in availablePresets" :key="p.key" :value="p.key">
                {{ p.label }} ({{ p.slotCount }} channels)
              </option>
            </select>
          </div>
          <!-- Existing bindings -->
          <div v-for="(aux, idx) in (selectedSymbol.auxiliaryChannels || [])" :key="idx" class="aux-channel-row">
            <div class="aux-header">
              <input
                type="text"
                class="prop-input-sm aux-label"
                :value="aux.label"
                @change="updateAuxiliaryChannel(idx, 'label', ($event.target as HTMLInputElement).value)"
                placeholder="Label"
              />
              <button class="btn-remove-inline" @click="removeAuxiliaryChannel(idx)" title="Remove">x</button>
            </div>
            <select
              class="prop-select"
              :value="aux.channel"
              @change="updateAuxiliaryChannel(idx, 'channel', ($event.target as HTMLSelectElement).value)"
            >
              <option value="">Select channel...</option>
              <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
            </select>
          </div>
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
          <div class="section-title">State Colors</div>
          <div class="prop-row">
            <label class="mini-label">Channel</label>
            <select
              class="prop-select"
              :value="selectedSymbol.stateChannel || ''"
              @change="updateSymbol({ stateChannel: ($event.target as HTMLSelectElement).value || undefined })"
            >
              <option value="">None</option>
              <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
            </select>
          </div>
          <template v-if="selectedSymbol.stateChannel">
            <div class="prop-row prop-color-row">
              <label class="mini-label">On</label>
              <input
                type="color"
                class="prop-color"
                :value="selectedSymbol.onColor || '#22c55e'"
                @input="updateSymbol({ onColor: ($event.target as HTMLInputElement).value })"
              />
              <label class="mini-label">Off</label>
              <input
                type="color"
                class="prop-color"
                :value="selectedSymbol.offColor || '#6b7280'"
                @input="updateSymbol({ offColor: ($event.target as HTMLInputElement).value })"
              />
              <label class="mini-label">Fault</label>
              <input
                type="color"
                class="prop-color"
                :value="selectedSymbol.faultColor || '#ef4444'"
                @input="updateSymbol({ faultColor: ($event.target as HTMLInputElement).value })"
              />
            </div>
            <div class="prop-row">
              <label class="mini-label">Threshold</label>
              <input
                type="number"
                class="prop-input-sm"
                step="0.1"
                :value="selectedSymbol.stateThreshold ?? 0.5"
                @change="updateSymbol({ stateThreshold: Number(($event.target as HTMLInputElement).value) })"
              />
            </div>
          </template>
        </div>

        <!-- Valve position channel (only for valve types) -->
        <div v-if="isValveSymbol(selectedSymbol)" class="prop-section">
          <div class="section-title">Valve Position</div>
          <div class="prop-row">
            <label class="mini-label">Channel (0-100%)</label>
            <select
              class="prop-select"
              :value="selectedSymbol.positionChannel || ''"
              @change="updateSymbol({ positionChannel: ($event.target as HTMLSelectElement).value || undefined })"
            >
              <option value="">None</option>
              <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
            </select>
          </div>
        </div>

        <!-- Tank fill level (only for tank types) -->
        <div v-if="isTankSymbol(selectedSymbol)" class="prop-section">
          <div class="section-title">Tank Fill</div>
          <div class="prop-row">
            <label class="mini-label">Channel (0-100%)</label>
            <select
              class="prop-select"
              :value="selectedSymbol.fillChannel || ''"
              @change="updateSymbol({ fillChannel: ($event.target as HTMLSelectElement).value || undefined })"
            >
              <option value="">None (use static)</option>
              <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
            </select>
          </div>
          <div v-if="!selectedSymbol.fillChannel" class="prop-row">
            <label class="mini-label">Static Level</label>
            <input
              type="range"
              class="prop-range"
              min="0" max="100" step="1"
              :value="selectedSymbol.fillLevel ?? 50"
              @input="updateSymbol({ fillLevel: Number(($event.target as HTMLInputElement).value) })"
            />
            <span class="range-value">{{ selectedSymbol.fillLevel ?? 50 }}%</span>
          </div>
          <div class="prop-row">
            <label class="mini-label">Fill Color</label>
            <input
              type="color"
              class="prop-color"
              :value="selectedSymbol.fillColor || '#3b82f6'"
              @input="updateSymbol({ fillColor: ($event.target as HTMLInputElement).value })"
            />
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
          <div class="section-title">Flip</div>
          <div class="prop-row" style="gap: 4px">
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedSymbol.flipX }"
              @click="updateSymbol({ flipX: !selectedSymbol.flipX })"
              title="Flip Horizontal (H)"
            >&#8596;</button>
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedSymbol.flipY }"
              @click="updateSymbol({ flipY: !selectedSymbol.flipY })"
              title="Flip Vertical (V)"
            >&#8597;</button>
          </div>
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

        <!-- Block Editor hint (indicators + ports) -->
        <div class="prop-section block-editor-hint">
          <div class="section-title">Block Editor</div>
          <div class="hint-counts">
            <span v-if="selectedSymbol.indicators?.length">{{ selectedSymbol.indicators.length }} indicator{{ selectedSymbol.indicators.length !== 1 ? 's' : '' }}</span>
            <span v-if="selectedSymbol.customPorts?.length">{{ selectedSymbol.customPorts.length }} custom port{{ selectedSymbol.customPorts.length !== 1 ? 's' : '' }}</span>
            <span v-if="!selectedSymbol.indicators?.length && !selectedSymbol.customPorts?.length" class="hint-empty">No indicators or custom ports</span>
          </div>
          <div class="hint-text">Double-click symbol to edit</div>
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
                <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
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
            <span style="font-size: 11px; color: var(--text-secondary); width: 32px; text-align: right;">
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

        <!-- Structured Pipe Attributes (ISA standard) -->
        <div class="prop-section">
          <div class="section-title">Pipe Identification</div>
          <div class="prop-grid-4">
            <label class="mini-label">Size</label>
            <input type="text" class="prop-input-sm"
              :value="selectedPipe.nominalSize || ''"
              @change="updatePipe({ nominalSize: ($event.target as HTMLInputElement).value || undefined })"
              placeholder='4"' />
            <label class="mini-label">Rating</label>
            <input type="text" class="prop-input-sm"
              :value="selectedPipe.pressureRating || ''"
              @change="updatePipe({ pressureRating: ($event.target as HTMLInputElement).value || undefined })"
              placeholder="150#" />
            <label class="mini-label">Material</label>
            <input type="text" class="prop-input-sm"
              :value="selectedPipe.material || ''"
              @change="updatePipe({ material: ($event.target as HTMLInputElement).value || undefined })"
              placeholder="CS" />
            <label class="mini-label">Fluid</label>
            <input type="text" class="prop-input-sm"
              :value="selectedPipe.fluidCode || ''"
              @change="updatePipe({ fluidCode: ($event.target as HTMLInputElement).value || undefined })"
              placeholder="S" />
          </div>
          <div class="prop-sub">
            <label class="mini-label">Line Number</label>
            <input type="text" class="prop-input"
              :value="selectedPipe.lineNumber || ''"
              @change="updatePipe({ lineNumber: ($event.target as HTMLInputElement).value || undefined })"
              :placeholder="computedLineNumber || '4&quot;-S-150#-CS-101'" />
          </div>
          <div v-if="computedLineNumber && !selectedPipe.lineNumber" class="prop-hint">
            Auto: {{ computedLineNumber }}
          </div>
        </div>

        <!-- ISA Signal Line Type (for signal/instrument pipes) -->
        <div v-if="selectedPipe.medium === 'signal'" class="prop-section">
          <div class="section-title">Signal Line Type (ISA 5.1)</div>
          <select
            class="prop-select"
            :value="selectedPipe.lineCode || 'undefined'"
            @change="updatePipe({ lineCode: ($event.target as HTMLSelectElement).value as any })"
          >
            <option value="undefined">Solid (Process)</option>
            <option value="pneumatic">Pneumatic (--- ---)</option>
            <option value="electrical">Electrical (. . . .)</option>
            <option value="capillary">Capillary (-.-.-)</option>
            <option value="hydraulic">Hydraulic (-..-..)</option>
            <option value="electromagnetic">Electromagnetic (...---)</option>
            <option value="software">Software/Data Link</option>
          </select>
        </div>

        <div class="prop-section">
          <div class="section-title">Heat Trace</div>
          <select
            class="prop-select"
            :value="selectedPipe.heatTrace || 'none'"
            @change="updatePipe({ heatTrace: ($event.target as HTMLSelectElement).value as any })"
          >
            <option value="none">None</option>
            <option value="electric">Electric Trace (ET)</option>
            <option value="steam">Steam Trace (ST)</option>
            <option value="hot-water">Hot Water Trace (HWT)</option>
          </select>
          <template v-if="selectedPipe.heatTrace && selectedPipe.heatTrace !== 'none'">
            <div class="prop-row">
              <label class="mini-label">Control Channel</label>
              <select
                class="prop-select"
                :value="selectedPipe.heatTraceChannel || ''"
                @change="updatePipe({ heatTraceChannel: ($event.target as HTMLSelectElement).value || undefined })"
              >
                <option value="">Always on</option>
                <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
              </select>
            </div>
            <div v-if="selectedPipe.heatTraceChannel" class="prop-row">
              <label class="mini-label">Threshold</label>
              <input
                type="number"
                class="prop-input-sm"
                step="0.1"
                :value="selectedPipe.heatTraceThreshold ?? 0.5"
                @change="updatePipe({ heatTraceThreshold: Number(($event.target as HTMLInputElement).value) })"
              />
            </div>
          </template>
        </div>

        <div v-if="store.pidLayer.systems && store.pidLayer.systems.length > 0" class="prop-section">
          <div class="section-title">System</div>
          <select
            class="prop-select"
            :value="selectedPipe.system || ''"
            @change="updatePipe({ system: ($event.target as HTMLSelectElement).value || undefined })"
          >
            <option value="">None</option>
            <option v-for="sys in store.pidLayer.systems" :key="sys.id" :value="sys.id">{{ sys.name }}</option>
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
              <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
            </select>
            <label class="prop-checkbox" style="margin-top: 4px">
              <input type="checkbox" :checked="selectedPipe.flowParticles || false"
                @change="updatePipe({ flowParticles: ($event.target as HTMLInputElement).checked })" />
              Flow Particles
            </label>
            <div v-if="selectedPipe.flowParticles" class="prop-row">
              <label class="mini-label">Count</label>
              <input type="number" class="prop-input-sm" min="1" max="12" step="1"
                :value="selectedPipe.particleCount || 4"
                @change="updatePipe({ particleCount: Number(($event.target as HTMLInputElement).value) })" />
            </div>
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

      <!-- Single Text Annotation Selected (#3.2) -->
      <template v-else-if="selectedTextAnnotation">
        <div class="prop-section">
          <div class="section-title">Text Annotation</div>
        </div>

        <div class="prop-section">
          <div class="section-title">Font Size</div>
          <input
            type="range"
            class="prop-range"
            min="8" max="72" step="1"
            :value="selectedTextAnnotation.fontSize"
            @input="updateTextAnnotation({ fontSize: Number(($event.target as HTMLInputElement).value) })"
            :title="`${selectedTextAnnotation.fontSize}px`"
          />
          <span class="range-value">{{ selectedTextAnnotation.fontSize }}px</span>
        </div>

        <div class="prop-section">
          <div class="section-title">Style</div>
          <div class="prop-row" style="gap: 4px">
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedTextAnnotation.fontWeight === 'bold' }"
              @click="updateTextAnnotation({ fontWeight: selectedTextAnnotation!.fontWeight === 'bold' ? 'normal' : 'bold' })"
              title="Bold"
            ><strong>B</strong></button>
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedTextAnnotation.fontStyle === 'italic' }"
              @click="updateTextAnnotation({ fontStyle: selectedTextAnnotation!.fontStyle === 'italic' ? 'normal' : 'italic' })"
              title="Italic"
            ><em>I</em></button>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Alignment</div>
          <div class="prop-row" style="gap: 4px">
            <button
              class="prop-toggle-btn"
              :class="{ active: (selectedTextAnnotation.textAlign || 'left') === 'left' }"
              @click="updateTextAnnotation({ textAlign: 'left' })"
              title="Align Left"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>
              </svg>
            </button>
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedTextAnnotation.textAlign === 'center' }"
              @click="updateTextAnnotation({ textAlign: 'center' })"
              title="Align Center"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>
              </svg>
            </button>
            <button
              class="prop-toggle-btn"
              :class="{ active: selectedTextAnnotation.textAlign === 'right' }"
              @click="updateTextAnnotation({ textAlign: 'right' })"
              title="Align Right"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="6" y1="18" x2="21" y2="18"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="prop-section">
          <div class="section-title">Colors</div>
          <div class="prop-row prop-color-row">
            <label class="mini-label">Text</label>
            <input
              type="color"
              class="prop-color"
              :value="selectedTextAnnotation.color || '#e2e8f0'"
              @input="updateTextAnnotation({ color: ($event.target as HTMLInputElement).value })"
            />
            <label class="mini-label">BG</label>
            <input
              type="color"
              class="prop-color"
              :value="selectedTextAnnotation.backgroundColor || '#1a1a2e'"
              @input="updateTextAnnotation({ backgroundColor: ($event.target as HTMLInputElement).value })"
            />
          </div>
        </div>

        <div class="prop-section">
          <label class="prop-checkbox">
            <input type="checkbox" :checked="selectedTextAnnotation.border || false"
              @change="updateTextAnnotation({ border: ($event.target as HTMLInputElement).checked })" />
            Border
          </label>
          <div v-if="selectedTextAnnotation.border" class="prop-sub">
            <input
              type="color"
              class="prop-color"
              :value="selectedTextAnnotation.borderColor || '#475569'"
              @input="updateTextAnnotation({ borderColor: ($event.target as HTMLInputElement).value })"
            />
          </div>
        </div>
      </template>

      <!-- Multi Selection (#3.7 — enhanced) -->
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
        <div v-if="selectedSymbolIds.length > 0" class="prop-section">
          <div class="section-title">Bulk Rotation</div>
          <select
            class="prop-select"
            value=""
            @change="(e) => {
              const rotation = Number((e.target as HTMLSelectElement).value)
              selectedSymbolIds.forEach(id => store.updatePidSymbolWithUndo(id, { rotation }))
            }"
          >
            <option value="" disabled>Set rotation...</option>
            <option :value="0">0°</option>
            <option :value="90">90°</option>
            <option :value="180">180°</option>
            <option :value="270">270°</option>
          </select>
        </div>
        <div v-if="selectedSymbolIds.length > 0" class="prop-section">
          <div class="section-title">Bulk Flip</div>
          <div class="prop-row" style="gap: 4px">
            <button class="prop-toggle-btn"
              @click="selectedSymbolIds.forEach(id => {
                const s = store.pidLayer.symbols.find(s => s.id === id)
                if (s) store.updatePidSymbolWithUndo(id, { flipX: !s.flipX })
              })"
              title="Flip Horizontal"
            >&#8596;</button>
            <button class="prop-toggle-btn"
              @click="selectedSymbolIds.forEach(id => {
                const s = store.pidLayer.symbols.find(s => s.id === id)
                if (s) store.updatePidSymbolWithUndo(id, { flipY: !s.flipY })
              })"
              title="Flip Vertical"
            >&#8597;</button>
          </div>
        </div>
        <div v-if="selectedSymbolIds.length > 0" class="prop-section">
          <div class="section-title">Bulk Channel</div>
          <select
            class="prop-select"
            value=""
            @change="(e) => {
              const channel = (e.target as HTMLSelectElement).value || undefined
              selectedSymbolIds.forEach(id => store.updatePidSymbolWithUndo(id, { channel }))
            }"
          >
            <option value="" disabled>Set channel...</option>
            <option value="">None</option>
            <optgroup v-for="(chList, device) in groupedChannels" :key="device" :label="String(device)">
              <option v-for="ch in chList" :key="ch.name" :value="ch.name">{{ ch.name }}</option>
            </optgroup>
          </select>
        </div>
        <div v-if="selectedSymbolIds.length > 1" class="prop-section">
          <div class="section-title">Auto-Match</div>
          <button
            class="btn-auto-match"
            @click="runAutoMatch"
            title="Match symbol labels to channel names automatically"
          >
            Auto-Match Labels → Channels
          </button>
          <div v-if="autoMatchResult" class="auto-match-result" :class="{ success: autoMatchResult.matched > 0 }">
            Matched {{ autoMatchResult.matched }} of {{ autoMatchResult.total }} symbols
          </div>
          <div class="prop-hint">Matches symbol labels to channel names (exact, prefix, substring)</div>
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

    <!-- Resize handle -->
    <div
      class="resize-handle resize-handle-left"
      :class="{ active: isResizing }"
      @mousedown="onResizeStart"
    />
  </div>
</template>

<style scoped>
/* Collapse/expand tab handle */
.panel-tab {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 64px;
  background: var(--bg-widget);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 56;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
  box-shadow: -2px 0 6px rgba(0, 0, 0, 0.3);
}

.panel-tab:hover {
  background: var(--bg-gradient-elevated);
  color: var(--color-accent-light);
}

.panel-tab-right {
  border: 1px solid var(--border-color);
  border-right: none;
  border-radius: 6px 0 0 6px;
}

/* Full panel */
.pid-properties-panel {
  position: absolute;
  top: 0;
  right: 0;
  height: 100%;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  z-index: 55;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-widget);
  flex-shrink: 0;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn-close-panel {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
}

.btn-close-panel:hover {
  color: var(--text-primary);
}

/* Resize handle */
.resize-handle {
  position: absolute;
  top: 0;
  width: 4px;
  height: 100%;
  cursor: col-resize;
  z-index: 51;
}

.resize-handle:hover,
.resize-handle.active {
  background: var(--color-accent-glow);
}

.resize-handle-left {
  left: 0;
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
  background: var(--border-color);
  border-radius: 3px;
}

.prop-section {
  margin-bottom: 10px;
}

.section-title {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 4px;
}

.prop-type {
  font-size: 12px;
  color: #cbd5e1;
  padding: 4px 0;
}

.variant-select {
  margin-top: 4px;
  font-size: 11px;
}

.prop-input,
.prop-select {
  width: 100%;
  padding: 5px 8px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  box-sizing: border-box;
}

.prop-input:focus,
.prop-select:focus {
  border-color: var(--color-accent);
}

.prop-hint {
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
  margin-top: 3px;
}

.prop-input::placeholder {
  color: var(--text-dim);
}

.prop-input-sm {
  width: 100%;
  padding: 3px 6px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: var(--text-primary);
  font-size: 11px;
  outline: none;
  box-sizing: border-box;
}

.prop-input-sm:focus {
  border-color: var(--color-accent);
}

.prop-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prop-color {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  padding: 0;
  background: transparent;
}

.color-hex {
  font-size: 11px;
  color: var(--text-secondary);
  font-family: monospace;
}

.prop-color-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.prop-grid-4 {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr;
  gap: 4px;
  align-items: center;
}

.mini-label {
  font-size: 10px;
  color: var(--text-muted);
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
  accent-color: var(--color-accent);
}

.prop-sub {
  margin-top: 6px;
  padding-left: 12px;
  border-left: 2px solid var(--border-color);
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
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: var(--text-primary);
  font-size: 11px;
}

.prop-color-sm {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: 3px;
  cursor: pointer;
  background: transparent;
}

.btn-remove-xs {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  line-height: 1;
}

.btn-remove-xs:hover {
  color: var(--color-error);
}

.btn-add-xs {
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 3px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  padding: 3px 8px;
  margin-top: 2px;
}

.btn-add-xs:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.prop-btn {
  width: 100%;
  padding: 5px 10px;
  background: var(--bg-surface);
  color: var(--text-bright);
  border: 1px solid var(--border-heavy);
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  text-align: center;
}

.prop-btn:hover {
  background: var(--bg-hover);
}

.prop-toggle-btn {
  padding: 3px 8px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-heavy);
  border-radius: 3px;
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 26px;
}

.prop-toggle-btn:hover {
  background: var(--bg-hover);
  color: var(--text-bright);
}

.prop-toggle-btn.active {
  background: var(--color-accent);
  color: var(--text-primary);
  border-color: var(--color-accent);
}

.prop-range {
  width: 100%;
  margin: 4px 0;
}

.range-value {
  font-size: 10px;
  color: var(--text-dim);
}

/* Integration info badges (alarm config, interlock status) */
.prop-info-badge {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin-top: 4px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.3;
  background: rgba(250, 204, 21, 0.12);
  border: 1px solid rgba(250, 204, 21, 0.3);
  color: #a16207;
}
.prop-info-badge.info-ok {
  background: rgba(34, 197, 94, 0.1);
  border-color: rgba(34, 197, 94, 0.3);
  color: #15803d;
}
.prop-info-badge.info-warn {
  background: rgba(251, 146, 60, 0.12);
  border-color: rgba(251, 146, 60, 0.3);
  color: #c2410c;
}
.prop-info-badge.info-fail {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.3);
  color: var(--color-error-dark);
}
.info-icon {
  flex-shrink: 0;
  font-size: 11px;
}
.info-text {
  word-break: break-word;
}

.prop-range {
  width: 100%;
  margin: 4px 0;
}

/* Auxiliary channel bindings */
.btn-add-inline {
  float: right;
  background: rgba(96, 165, 250, 0.15);
  border: 1px solid rgba(96, 165, 250, 0.3);
  color: var(--color-accent-light);
  border-radius: 3px;
  width: 18px;
  height: 18px;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
.btn-add-inline:hover { background: rgba(96, 165, 250, 0.3); }

.btn-auto-match {
  width: 100%;
  padding: 5px 8px;
  background: rgba(52, 211, 153, 0.12);
  border: 1px solid rgba(52, 211, 153, 0.3);
  border-radius: 4px;
  color: #34d399;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-auto-match:hover { background: rgba(52, 211, 153, 0.25); }

.auto-match-result {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 3px;
}
.auto-match-result.success { color: #34d399; }

.aux-channel-row {
  padding: 4px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.aux-channel-row:last-child { border-bottom: none; }

.aux-header {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
}
.aux-label {
  flex: 1;
  font-weight: 500;
}
.btn-remove-inline {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: var(--color-error);
  border-radius: 3px;
  width: 18px;
  height: 18px;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
.btn-remove-inline:hover { background: rgba(239, 68, 68, 0.25); }

/* Block editor hint */
.block-editor-hint {
  padding: 8px;
  background: rgba(59, 130, 246, 0.06);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 4px;
}
.hint-counts {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.hint-empty {
  color: var(--text-dim);
  font-style: italic;
}
.hint-text {
  font-size: 10px;
  color: var(--text-dim);
  font-style: italic;
}
</style>
