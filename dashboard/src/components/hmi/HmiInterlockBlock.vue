<script setup lang="ts">
/**
 * HmiInterlockBlock — ISA-84 / IEC 61511 Safety Instrumented Function (SIF) Block
 *
 * Renders an interlock logic block on the P&ID canvas showing:
 *   - Compact: interlock name, status, SIL badge, demand count
 *   - Expanded: condition list with live values, control list, bypass button
 *
 * Binds to an interlock definition via symbol.interlockId → useSafety().interlocks
 */
import { ref, computed } from 'vue'
import { useSafety } from '../../composables/useSafety'
import { useAuth } from '../../composables/useAuth'
import type { PidSymbol, InterlockCondition, InterlockControl } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const safety = useSafety()
const auth = useAuth()

const expanded = ref(false)

const interlock = computed(() => {
  if (!props.symbol.interlockId) return null
  return safety.interlocks.value.find(i => i.id === props.symbol.interlockId) || null
})

const interlockStatus = computed(() => {
  if (!props.symbol.interlockId) return null
  return safety.interlockStatuses.value.find(s => s.id === props.symbol.interlockId) || null
})

const borderState = computed<'satisfied' | 'failed' | 'bypassed' | 'disabled' | 'unbound'>(() => {
  if (!interlock.value || !interlockStatus.value) return 'unbound'
  if (!interlockStatus.value.enabled) return 'disabled'
  if (interlockStatus.value.bypassed) return 'bypassed'
  if (interlockStatus.value.satisfied) return 'satisfied'
  return 'failed'
})

const statusText = computed(() => {
  switch (borderState.value) {
    case 'satisfied': return 'OK'
    case 'failed': return 'TRIPPED'
    case 'bypassed': return 'BYPASSED'
    case 'disabled': return 'DISABLED'
    default: return 'NOT BOUND'
  }
})

const silRating = computed(() => interlock.value?.silRating || null)
const demandCount = computed(() => interlock.value?.demandCount || 0)

const canBypass = computed(() => {
  if (!interlock.value) return false
  return interlock.value.bypassAllowed && auth.isSupervisor.value
})

const conditionResults = computed(() => {
  if (!interlock.value || !interlockStatus.value) return []
  return interlock.value.conditions.map(condition => {
    const failed = interlockStatus.value!.failedConditions.find(
      f => f.condition.id === condition.id
    )
    return {
      condition,
      satisfied: !failed,
      currentValue: failed?.currentValue,
      reason: failed?.reason || 'OK'
    }
  })
})

function formatCondition(c: InterlockCondition): string {
  switch (c.type) {
    case 'channel_value':
      return `${c.channel || '?'} ${c.operator || '>'} ${c.value ?? '?'}`
    case 'digital_input':
      return `${c.channel || '?'} = ${c.invert ? 'LOW' : 'HIGH'}`
    case 'alarm_active':
      return `Alarm ${c.alarmId || '?'} active`
    case 'alarm_state':
      return `Alarm ${c.alarmId || '?'} ${c.alarmState || '?'}`
    case 'no_active_alarms':
      return 'No active alarms'
    case 'no_latched_alarms':
      return 'No latched alarms'
    case 'mqtt_connected':
      return 'MQTT connected'
    case 'daq_connected':
      return 'DAQ connected'
    case 'acquiring':
      return 'Acquisition running'
    case 'not_recording':
      return 'Not recording'
    case 'expression':
      return c.expression || 'Expression'
    case 'variable_value':
      return `Var ${c.variableId || '?'} ${c.operator || '='} ${c.value ?? '?'}`
    default:
      return c.description || c.type
  }
}

function formatControl(ctrl: InterlockControl): string {
  switch (ctrl.type) {
    case 'digital_output': return `Block DO: ${ctrl.channel || '?'}`
    case 'analog_output': return `Block AO: ${ctrl.channel || '?'}`
    case 'set_digital_output': return `Force DO: ${ctrl.channel || '?'} → ${ctrl.setValue}`
    case 'set_analog_output': return `Force AO: ${ctrl.channel || '?'} → ${ctrl.setValue}`
    case 'stop_session': return 'Stop session'
    case 'stop_acquisition': return 'Stop acquisition'
    case 'recording_start': return 'Block recording'
    case 'acquisition_start': return 'Block acquisition'
    case 'session_start': return 'Block session start'
    case 'schedule_enable': return 'Block scheduler'
    case 'script_start': return 'Block scripts'
    case 'button_action': return `Block button: ${ctrl.buttonId || '?'}`
    default: return ctrl.type
  }
}

function toggleExpanded() {
  if (props.editMode) return
  expanded.value = !expanded.value
}

function toggleBypass() {
  if (!interlock.value || !canBypass.value) return
  if (interlock.value.bypassed) {
    safety.bypassInterlock(interlock.value.id, false, 'dashboard', 'Bypass removed from P&ID')
  } else {
    safety.bypassInterlock(interlock.value.id, true, 'dashboard', 'Manual bypass from P&ID')
  }
}
</script>

<template>
  <div class="hmi-interlock" :class="[borderState, { expanded }]" @click.stop="toggleExpanded">
    <!-- Compact header: always visible -->
    <div class="il-header">
      <div class="il-name-row">
        <svg class="il-shield" width="12" height="14" viewBox="0 0 14 16" fill="currentColor">
          <path d="M7 0L0 3v5c0 3.87 2.99 7.49 7 8 4.01-.51 7-4.13 7-8V3L7 0z"/>
        </svg>
        <span class="il-name">{{ interlock?.name || symbol.label || 'INTERLOCK' }}</span>
      </div>
      <div class="il-badges">
        <span v-if="silRating" class="sil-badge">{{ silRating }}</span>
        <span v-if="demandCount > 0" class="demand-badge" :title="`${demandCount} demand(s) recorded`">D:{{ demandCount }}</span>
      </div>
    </div>
    <div class="il-status" :class="borderState">{{ statusText }}</div>

    <!-- Expanded: conditions + controls + bypass -->
    <template v-if="expanded && interlock && interlockStatus">
      <div class="il-details">
        <!-- Conditions -->
        <div class="il-section">
          <div class="il-section-label">CONDITIONS</div>
          <div v-for="cr in conditionResults" :key="cr.condition.id" class="il-condition-row">
            <svg v-if="cr.satisfied" class="il-icon ok" width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
              <path d="M6.5 12.5L2 8l1.4-1.4 3.1 3.1 5.1-5.1L13 6l-6.5 6.5z"/>
            </svg>
            <svg v-else class="il-icon fail" width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
              <path d="M12 4.7L11.3 4 8 7.3 4.7 4 4 4.7 7.3 8 4 11.3l.7.7L8 8.7l3.3 3.3.7-.7L8.7 8z"/>
            </svg>
            <span class="il-cond-text">{{ cr.condition.description || formatCondition(cr.condition) }}</span>
            <span v-if="!cr.satisfied && cr.currentValue !== undefined" class="il-cond-val">{{ cr.currentValue }}</span>
          </div>
          <div v-if="conditionResults.length === 0" class="il-empty">No conditions</div>
        </div>

        <!-- Controls -->
        <div class="il-section">
          <div class="il-section-label">CONTROLS</div>
          <div v-for="(ctrl, idx) in interlock.controls" :key="idx" class="il-control-row">
            <span class="il-ctrl-text">{{ formatControl(ctrl) }}</span>
          </div>
          <div v-if="interlock.controls.length === 0" class="il-empty">No controls</div>
        </div>

        <!-- Bypass -->
        <button
          v-if="canBypass"
          class="il-bypass-btn"
          :class="{ active: interlock.bypassed }"
          @click.stop="toggleBypass"
        >
          {{ interlock.bypassed ? 'REMOVE BYPASS' : 'BYPASS' }}
        </button>
      </div>
    </template>

    <!-- Edit mode: unbound hint -->
    <div v-if="editMode && !interlock" class="il-unbound">
      Bind to interlock in Properties
    </div>
  </div>
</template>

<style scoped>
.hmi-interlock {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--hmi-panel-bg, #D4D4D4);
  border: 2px solid var(--hmi-led-off, #808080);
  border-radius: 3px;
  border-left-width: 4px;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
  cursor: pointer;
  overflow: hidden;
}

.hmi-interlock.satisfied { border-color: var(--hmi-il-satisfied, #22c55e); }
.hmi-interlock.failed { border-color: var(--hmi-il-failed, #dc2626); }
.hmi-interlock.bypassed { border-color: var(--hmi-il-bypassed, #d97706); }
.hmi-interlock.disabled { border-color: var(--hmi-led-off, #808080); }
.hmi-interlock.unbound { border-color: var(--hmi-panel-border, #A0A0A4); border-style: dashed; }

.hmi-interlock.expanded {
  overflow-y: auto;
}

/* Header */
.il-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 2px;
  gap: 4px;
  min-height: 20px;
}

.il-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.il-shield {
  flex-shrink: 0;
}

.hmi-interlock.satisfied .il-shield { color: var(--hmi-il-satisfied, #22c55e); }
.hmi-interlock.failed .il-shield { color: var(--hmi-il-failed, #dc2626); }
.hmi-interlock.bypassed .il-shield { color: var(--hmi-il-bypassed, #d97706); }
.hmi-interlock.disabled .il-shield { color: var(--hmi-led-off, #808080); }
.hmi-interlock.unbound .il-shield { color: var(--hmi-panel-border, #A0A0A4); }

.il-name {
  font-size: clamp(8px, 28%, 12px);
  font-weight: 600;
  color: var(--hmi-label-text, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.il-badges {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
}

.sil-badge {
  font-size: 7px;
  font-weight: 700;
  padding: 1px 3px;
  border-radius: 2px;
  background: var(--hmi-value-text, #1E3A8A);
  color: var(--hmi-on-text, white);
  letter-spacing: 0.3px;
}

.demand-badge {
  font-size: 7px;
  font-weight: 600;
  padding: 1px 3px;
  border-radius: 2px;
  background: var(--hmi-demand-badge-bg, #6b7280);
  color: var(--hmi-on-text, white);
}

/* Status text */
.il-status {
  font-size: clamp(7px, 24%, 10px);
  font-weight: 700;
  text-transform: uppercase;
  text-align: center;
  padding: 1px 6px 3px;
  letter-spacing: 0.5px;
  color: var(--hmi-subtle-text, #555);
}

.il-status.satisfied { color: var(--hmi-il-satisfied-text, #15803d); }
.il-status.failed { color: var(--hmi-il-failed, #dc2626); }
.il-status.bypassed { color: var(--hmi-il-bypassed, #d97706); }
.il-status.disabled { color: var(--hmi-led-off, #808080); }

/* Expanded details */
.il-details {
  border-top: 1px solid var(--hmi-details-border, #bbb);
  padding: 4px 6px;
  background: var(--hmi-details-bg, #e8e8e8);
  flex: 1;
}

.il-section {
  margin-bottom: 4px;
}

.il-section-label {
  font-size: 7px;
  font-weight: 700;
  color: var(--hmi-muted-text, #888);
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}

.il-condition-row,
.il-control-row {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 1px 0;
  font-size: 9px;
}

.il-icon {
  flex-shrink: 0;
}

.il-icon.ok { color: var(--hmi-il-satisfied, #22c55e); }
.il-icon.fail { color: var(--hmi-il-failed, #dc2626); }

.il-cond-text,
.il-ctrl-text {
  color: var(--hmi-body-text, #444);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.il-cond-val {
  font-family: 'Segoe UI', monospace;
  font-weight: 600;
  color: var(--hmi-il-failed, #dc2626);
  flex-shrink: 0;
}

.il-empty {
  font-size: 8px;
  color: var(--hmi-hint-text, #999);
  font-style: italic;
  padding: 1px 0;
}

/* Bypass button */
.il-bypass-btn {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 3px 6px;
  font-size: 8px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: 1px solid var(--hmi-il-bypassed, #d97706);
  border-radius: 2px;
  background: transparent;
  color: var(--hmi-il-bypassed, #d97706);
  cursor: pointer;
}

.il-bypass-btn:hover {
  background: var(--hmi-il-bypass-hover, rgba(217, 119, 6, 0.1));
}

.il-bypass-btn.active {
  background: var(--hmi-il-bypassed, #d97706);
  color: var(--hmi-on-text, #fff);
}

/* Edit mode unbound hint */
.il-unbound {
  font-size: 8px;
  color: var(--hmi-hint-text, #999);
  text-align: center;
  padding: 2px 4px;
  font-style: italic;
}
</style>
