<script setup lang="ts">
/**
 * InterlockStatusWidget — IEC 61511 / ISA-84 Interlock Status Dashboard
 *
 * Comprehensive interlock status display with:
 *   - Summary counts (satisfied/blocked/bypassed)
 *   - Per-interlock expandable detail rows showing:
 *     - Failed conditions with live values and thresholds
 *     - Controlled outputs (what it blocks/forces)
 *     - SIL rating, demand count, last demand time
 *     - Bypass status (who, when, reason, time remaining)
 *     - Proof test status (last test, overdue indicator)
 *     - Condition delay timers
 *   - Bypass/remove controls (supervisor-only)
 */
import { ref, computed } from 'vue'
import { useSafety } from '../composables/useSafety'
import { useAuth } from '../composables/useAuth'
import type { InterlockCondition, InterlockControl } from '../types'

defineProps<{
  title?: string
  compact?: boolean
  showBypassButtons?: boolean
}>()

const safety = useSafety()
const auth = useAuth()

const expandedIds = ref<Set<string>>(new Set())

const interlockStatuses = computed(() => safety.interlockStatuses.value)
const hasInterlocks = computed(() => interlockStatuses.value.length > 0)

const satisfiedCount = computed(() =>
  interlockStatuses.value.filter(s => s.satisfied && s.enabled && !s.bypassed).length
)
const blockedCount = computed(() =>
  interlockStatuses.value.filter(s => !s.satisfied && s.enabled && !s.bypassed).length
)
const bypassedCount = computed(() =>
  interlockStatuses.value.filter(s => s.bypassed && s.enabled).length
)
const disabledCount = computed(() =>
  interlockStatuses.value.filter(s => !s.enabled).length
)

const allSatisfied = computed(() => blockedCount.value === 0 && bypassedCount.value === 0)

function getInterlock(id: string) {
  return safety.interlocks.value.find(i => i.id === id)
}

function toggleExpand(id: string) {
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
}

function toggleBypass(id: string) {
  const interlock = getInterlock(id)
  if (interlock && interlock.bypassAllowed) {
    safety.bypassInterlock(id, !interlock.bypassed, 'dashboard', interlock.bypassed ? 'Bypass removed' : 'Manual bypass')
  }
}

function formatCondition(c: InterlockCondition): string {
  switch (c.type) {
    case 'channel_value':
      return `${c.channel || '?'} ${c.operator || '>'} ${c.value ?? '?'}`
    case 'digital_input':
      return `${c.channel || '?'} = ${c.invert ? 'LOW' : 'HIGH'}`
    case 'alarm_active':
      return `Alarm "${c.alarmId || '?'}" active`
    case 'alarm_state':
      return `Alarm "${c.alarmId || '?'}" ${c.alarmState || '?'}`
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
    case 'set_digital_output': return `Force DO: ${ctrl.channel || '?'} \u2192 ${ctrl.setValue}`
    case 'set_analog_output': return `Force AO: ${ctrl.channel || '?'} \u2192 ${ctrl.setValue}`
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

function formatTime(iso: string | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatBypassRemaining(interlock: ReturnType<typeof getInterlock>): string | null {
  if (!interlock?.bypassed || !interlock.bypassedAt || !interlock.maxBypassDuration) return null
  const elapsed = (Date.now() - new Date(interlock.bypassedAt).getTime()) / 1000
  const remaining = interlock.maxBypassDuration - elapsed
  if (remaining <= 0) return 'Expired'
  if (remaining < 60) return `${Math.ceil(remaining)}s left`
  if (remaining < 3600) return `${Math.ceil(remaining / 60)}m left`
  return `${Math.round(remaining / 3600)}h left`
}

function isProofTestOverdue(interlock: ReturnType<typeof getInterlock>): boolean {
  if (!interlock?.proofTestInterval || !interlock.lastProofTest) return false
  const daysSince = (Date.now() - new Date(interlock.lastProofTest).getTime()) / (1000 * 86400)
  return daysSince > interlock.proofTestInterval
}
</script>

<template>
  <div class="interlock-status-widget" :class="{ compact, 'has-blocked': blockedCount > 0 }">
    <!-- Widget title -->
    <div v-if="title" class="widget-title">{{ title }}</div>

    <!-- No interlocks configured -->
    <div v-if="!hasInterlocks" class="no-interlocks">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <span>No interlocks configured</span>
    </div>

    <!-- Summary header -->
    <template v-else>
      <div class="summary-row">
        <div class="stat ok" :class="{ active: satisfiedCount > 0 }">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
          </svg>
          <span class="count">{{ satisfiedCount }}</span>
        </div>
        <div class="stat blocked" :class="{ active: blockedCount > 0 }">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/>
          </svg>
          <span class="count">{{ blockedCount }}</span>
        </div>
        <div v-if="bypassedCount > 0" class="stat bypassed active">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
          </svg>
          <span class="count">{{ bypassedCount }}</span>
          <span class="label">BYP</span>
        </div>
        <div v-if="disabledCount > 0" class="stat disabled-stat active">
          <span class="count">{{ disabledCount }}</span>
          <span class="label">OFF</span>
        </div>
      </div>

      <!-- All clear indicator -->
      <div v-if="allSatisfied" class="all-clear">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>All Interlocks Satisfied</span>
      </div>

      <!-- Interlock list -->
      <div class="interlock-list" v-if="!allSatisfied || !compact">
        <div
          v-for="status in (compact ? interlockStatuses.filter(s => !s.satisfied && s.enabled && !s.bypassed) : interlockStatuses)"
          :key="status.id"
          class="interlock-card"
          :class="{
            satisfied: status.satisfied && !status.bypassed,
            blocked: !status.satisfied && !status.bypassed && status.enabled,
            bypassed: status.bypassed,
            disabled: !status.enabled,
            expanded: expandedIds.has(status.id)
          }"
        >
          <!-- Header row (click to expand) -->
          <div class="card-header" @click="toggleExpand(status.id)">
            <span class="status-dot" :class="{
              'dot-ok': status.satisfied && !status.bypassed && status.enabled,
              'dot-fail': !status.satisfied && !status.bypassed && status.enabled,
              'dot-bypass': status.bypassed,
              'dot-disabled': !status.enabled
            }"></span>
            <span class="card-name">{{ status.name }}</span>
            <!-- Badges -->
            <span v-if="status.priority && status.priority !== 'medium'" class="priority-badge" :class="`priority-${status.priority}`">
              {{ status.priority.toUpperCase() }}
            </span>
            <span v-if="getInterlock(status.id)?.silRating" class="sil-badge">
              {{ getInterlock(status.id)!.silRating }}
            </span>
            <span v-if="status.bypassed" class="bypass-badge">BYP</span>
            <span v-if="!status.enabled" class="disabled-badge">OFF</span>
            <!-- State -->
            <span class="card-state" :class="{
              'state-ok': status.satisfied && !status.bypassed && status.enabled,
              'state-fail': !status.satisfied && !status.bypassed && status.enabled,
              'state-bypass': status.bypassed,
              'state-disabled': !status.enabled,
            }">
              {{ !status.enabled ? 'DISABLED' : status.bypassed ? 'BYPASSED' : status.satisfied ? 'OK' : 'TRIPPED' }}
            </span>
            <!-- Expand chevron -->
            <svg class="expand-chevron" :class="{ rotated: expandedIds.has(status.id) }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
              <path d="M7 10l5 5 5-5z"/>
            </svg>
          </div>

          <!-- Failed conditions (always shown for blocked interlocks, even when collapsed) -->
          <div v-if="!status.satisfied && !status.bypassed && status.failedConditions?.length > 0 && !expandedIds.has(status.id)" class="failed-summary">
            <div v-for="(fc, idx) in (status.failedConditions || []).slice(0, 2)" :key="idx" class="failed-line">
              <svg width="8" height="8" viewBox="0 0 16 16" fill="currentColor" class="fail-icon">
                <path d="M12 4.7L11.3 4 8 7.3 4.7 4 4 4.7 7.3 8 4 11.3l.7.7L8 8.7l3.3 3.3.7-.7L8.7 8z"/>
              </svg>
              <span class="failed-reason">{{ fc.reason }}</span>
              <span v-if="fc.currentValue !== undefined" class="failed-val">{{ typeof fc.currentValue === 'number' ? fc.currentValue.toFixed(2) : fc.currentValue }}</span>
            </div>
            <div v-if="(status.failedConditions?.length || 0) > 2" class="failed-more">
              +{{ status.failedConditions.length - 2 }} more...
            </div>
          </div>

          <!-- Expanded details -->
          <div v-if="expandedIds.has(status.id)" class="card-details">
            <!-- Description -->
            <div v-if="getInterlock(status.id)?.description" class="detail-description">
              {{ getInterlock(status.id)!.description }}
            </div>

            <!-- Conditions section -->
            <div class="detail-section">
              <div class="section-label">CONDITIONS
                <span v-if="getInterlock(status.id)?.conditionLogic" class="logic-badge">{{ getInterlock(status.id)!.conditionLogic }}</span>
              </div>
              <div v-for="cond in (getInterlock(status.id)?.conditions || [])" :key="cond.id" class="condition-row">
                <svg v-if="!(status.failedConditions || []).find(f => f.condition.id === cond.id)" class="cond-icon ok" width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M6.5 12.5L2 8l1.4-1.4 3.1 3.1 5.1-5.1L13 6l-6.5 6.5z"/>
                </svg>
                <svg v-else class="cond-icon fail" width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M12 4.7L11.3 4 8 7.3 4.7 4 4 4.7 7.3 8 4 11.3l.7.7L8 8.7l3.3 3.3.7-.7L8.7 8z"/>
                </svg>
                <span class="cond-text">{{ cond.description || formatCondition(cond) }}</span>
                <template v-if="(status.failedConditions || []).find(f => f.condition.id === cond.id)">
                  <span class="cond-current">{{
                    (() => { const v = (status.failedConditions || []).find(f => f.condition.id === cond.id)?.currentValue; return v !== undefined ? (typeof v === 'number' ? v.toFixed(2) : v) : '' })()
                  }}</span>
                </template>
                <!-- Delay timer -->
                <template v-if="(status.conditionsWithDelay || []).find(d => d.conditionId === cond.id)">
                  <span class="delay-timer" :class="{ met: (status.conditionsWithDelay || []).find(d => d.conditionId === cond.id)!.delayMet }">
                    {{ Math.ceil((status.conditionsWithDelay || []).find(d => d.conditionId === cond.id)!.delayElapsed) }}s / {{ (status.conditionsWithDelay || []).find(d => d.conditionId === cond.id)!.delayTotal }}s
                  </span>
                </template>
              </div>
              <div v-if="!(getInterlock(status.id)?.conditions?.length)" class="detail-empty">No conditions defined</div>
            </div>

            <!-- Controls section -->
            <div class="detail-section">
              <div class="section-label">CONTROLS</div>
              <div v-for="(ctrl, idx) in (status.controls || [])" :key="idx" class="control-row">
                <span class="ctrl-text">{{ formatControl(ctrl) }}</span>
              </div>
              <div v-if="!(status.controls?.length)" class="detail-empty">No controls defined</div>
            </div>

            <!-- Metadata row -->
            <div class="meta-grid">
              <template v-if="getInterlock(status.id)?.silRating">
                <span class="meta-label">SIL</span>
                <span class="meta-value sil">{{ getInterlock(status.id)!.silRating }}</span>
              </template>
              <template v-if="(getInterlock(status.id)?.demandCount ?? 0) > 0">
                <span class="meta-label">Demands</span>
                <span class="meta-value">{{ getInterlock(status.id)!.demandCount }}</span>
              </template>
              <template v-if="getInterlock(status.id)?.lastDemandTime">
                <span class="meta-label">Last demand</span>
                <span class="meta-value">{{ formatTime(getInterlock(status.id)!.lastDemandTime) }}</span>
              </template>
              <template v-if="getInterlock(status.id)?.lastProofTest">
                <span class="meta-label">Proof test</span>
                <span class="meta-value" :class="{ overdue: isProofTestOverdue(getInterlock(status.id)) }">
                  {{ formatTime(getInterlock(status.id)!.lastProofTest) }}
                  <span v-if="isProofTestOverdue(getInterlock(status.id))" class="overdue-tag">OVERDUE</span>
                </span>
              </template>
            </div>

            <!-- Bypass details (if bypassed) -->
            <div v-if="status.bypassed && getInterlock(status.id)" class="bypass-details">
              <div class="section-label">BYPASS ACTIVE</div>
              <div class="bypass-info">
                <span v-if="getInterlock(status.id)!.bypassedBy">By: {{ getInterlock(status.id)!.bypassedBy }}</span>
                <span v-if="getInterlock(status.id)!.bypassedAt">At: {{ formatTime(getInterlock(status.id)!.bypassedAt) }}</span>
                <span v-if="getInterlock(status.id)!.bypassReason">Reason: {{ getInterlock(status.id)!.bypassReason }}</span>
                <span v-if="formatBypassRemaining(getInterlock(status.id))" class="bypass-timer">
                  {{ formatBypassRemaining(getInterlock(status.id)) }}
                </span>
              </div>
            </div>

            <!-- Trip acknowledgment section -->
            <div v-if="status.requiresAcknowledgment && !status.satisfied && !status.bypassed" class="trip-ack-section">
              <div class="section-label">TRIP ACKNOWLEDGMENT</div>
              <div v-if="status.tripAcknowledged" class="ack-info">
                <span class="ack-status acknowledged">Acknowledged</span>
                <span v-if="status.tripAcknowledgedBy">by {{ status.tripAcknowledgedBy }}</span>
                <span v-if="status.tripAcknowledgedAt">at {{ formatTime(status.tripAcknowledgedAt) }}</span>
              </div>
              <button
                v-if="!status.tripAcknowledged && auth.isSupervisor.value"
                class="ack-trip-btn"
                @click.stop="safety.acknowledgeTrip(status.id)"
              >
                Acknowledge Trip
              </button>
              <div v-if="!status.tripAcknowledged && !auth.isSupervisor.value" class="ack-pending">
                Awaiting operator acknowledgment
              </div>
            </div>

            <!-- Bypass button -->
            <button
              v-if="showBypassButtons && getInterlock(status.id)?.bypassAllowed && auth.isSupervisor.value"
              class="bypass-btn"
              :class="{ active: status.bypassed }"
              @click.stop="toggleBypass(status.id)"
            >
              {{ status.bypassed ? 'Remove Bypass' : 'Bypass Interlock' }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.interlock-status-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 6px;
}

.widget-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color);
}

.interlock-status-widget.has-blocked {
  border-color: #7f1d1d;
}

.no-interlocks {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 100%;
  color: #666;
  font-size: 0.75rem;
}

/* Summary row */
.summary-row {
  display: flex;
  gap: 6px;
  justify-content: center;
  flex-wrap: wrap;
}

.stat {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  opacity: 0.5;
}

.stat.active { opacity: 1; }
.stat.ok.active { background: #14532d; color: #86efac; }
.stat.blocked.active { background: #7f1d1d; color: #fca5a5; animation: pulse 1s infinite; }
.stat.bypassed.active { background: #78350f; color: #fbbf24; }
.stat.disabled-stat.active { background: #1f2937; color: #9ca3af; }

.stat .count {
  font-size: 0.9rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}

.stat .label {
  font-size: 0.55rem;
  text-transform: uppercase;
}

/* All clear */
.all-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px;
  background: #14532d;
  color: #86efac;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Interlock list */
.interlock-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Card */
.interlock-card {
  background: var(--bg-secondary);
  border-radius: 4px;
  border-left: 3px solid var(--btn-secondary-bg);
  overflow: hidden;
}

.interlock-card.satisfied { border-left-color: var(--color-success); }
.interlock-card.blocked { border-left-color: var(--color-error); }
.interlock-card.bypassed { border-left-color: #f59e0b; }
.interlock-card.disabled { border-left-color: #4b5563; opacity: 0.6; }

/* Card header */
.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  cursor: pointer;
  user-select: none;
}

.card-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-ok { background: var(--color-success); }
.dot-fail { background: var(--color-error); animation: dot-pulse 1.2s ease-in-out infinite; }
.dot-bypass { background: #f59e0b; }
.dot-disabled { background: #4b5563; }

.card-name {
  flex: 1;
  font-size: 0.72rem;
  font-weight: 500;
  color: #ddd;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sil-badge {
  font-size: 0.5rem;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 2px;
  background: #1e3a8a;
  color: #93c5fd;
  letter-spacing: 0.3px;
  flex-shrink: 0;
}

.bypass-badge {
  font-size: 0.48rem;
  padding: 1px 4px;
  background: #f59e0b;
  color: #000;
  border-radius: 2px;
  font-weight: 700;
  flex-shrink: 0;
}

.disabled-badge {
  font-size: 0.48rem;
  padding: 1px 4px;
  background: var(--btn-secondary-bg);
  color: #9ca3af;
  border-radius: 2px;
  font-weight: 600;
  flex-shrink: 0;
}

.card-state {
  font-size: 0.58rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  flex-shrink: 0;
}

.state-ok { color: var(--color-success); }
.state-fail { color: var(--color-error); }
.state-bypass { color: #f59e0b; }
.state-disabled { color: #6b7280; }

.expand-chevron {
  flex-shrink: 0;
  color: #666;
  transition: transform 0.15s;
}

.expand-chevron.rotated {
  transform: rotate(180deg);
}

/* Failed conditions summary (collapsed, blocked only) */
.failed-summary {
  padding: 0 8px 4px 22px;
}

.failed-line {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.62rem;
  color: #fca5a5;
  padding: 1px 0;
}

.fail-icon { flex-shrink: 0; color: var(--color-error); }

.failed-reason {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.failed-val {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: var(--color-error);
  flex-shrink: 0;
}

.failed-more {
  font-size: 0.58rem;
  color: #888;
  font-style: italic;
}

/* Expanded details */
.card-details {
  padding: 4px 8px 8px;
  border-top: 1px solid #1a1a3a;
}

.detail-description {
  font-size: 0.65rem;
  color: #9ca3af;
  padding: 4px 0 6px;
  font-style: italic;
  line-height: 1.3;
}

.detail-section {
  margin-bottom: 6px;
}

.section-label {
  font-size: 0.52rem;
  font-weight: 700;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 3px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.logic-badge {
  font-size: 0.48rem;
  padding: 0 3px;
  background: var(--btn-secondary-bg);
  border-radius: 2px;
  color: #9ca3af;
}

/* Condition rows */
.condition-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
  font-size: 0.65rem;
}

.cond-icon { flex-shrink: 0; }
.cond-icon.ok { color: var(--color-success); }
.cond-icon.fail { color: var(--color-error); }

.cond-text {
  flex: 1;
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cond-current {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--color-error);
  flex-shrink: 0;
}

.delay-timer {
  font-size: 0.55rem;
  font-family: 'JetBrains Mono', monospace;
  padding: 0 3px;
  border-radius: 2px;
  background: var(--bg-surface);
  color: #94a3b8;
  flex-shrink: 0;
}

.delay-timer.met {
  background: #14532d;
  color: #86efac;
}

/* Control rows */
.control-row {
  padding: 2px 0;
  font-size: 0.62rem;
}

.ctrl-text {
  color: #9ca3af;
}

.detail-empty {
  font-size: 0.6rem;
  color: #555;
  font-style: italic;
}

/* Metadata grid */
.meta-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 8px;
  padding: 4px 0;
  border-top: 1px solid #1a1a3a;
  margin-top: 4px;
}

.meta-label {
  font-size: 0.55rem;
  color: #666;
  text-transform: uppercase;
}

.meta-value {
  font-size: 0.6rem;
  color: #aaa;
  font-family: 'JetBrains Mono', monospace;
}

.meta-value.sil {
  color: #93c5fd;
  font-weight: 600;
}

.meta-value.overdue {
  color: var(--color-error);
}

.overdue-tag {
  font-size: 0.45rem;
  padding: 0 3px;
  background: #7f1d1d;
  color: #fca5a5;
  border-radius: 2px;
  font-weight: 700;
  margin-left: 4px;
  vertical-align: middle;
}

/* Bypass details */
.bypass-details {
  padding: 4px 0;
  border-top: 1px solid #1a1a3a;
  margin-top: 4px;
}

.bypass-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.58rem;
  color: #fbbf24;
}

.bypass-timer {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}

/* Bypass button */
.bypass-btn {
  width: 100%;
  margin-top: 6px;
  padding: 4px 8px;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: 1px solid #f59e0b;
  border-radius: 3px;
  background: transparent;
  color: #f59e0b;
  cursor: pointer;
}

.bypass-btn:hover {
  background: rgba(245, 158, 11, 0.1);
}

.bypass-btn.active {
  background: #f59e0b;
  color: #000;
}

/* Compact mode */
.compact .interlock-list {
  max-height: none;
}

.compact .card-header {
  padding: 3px 6px;
}

.compact .card-name {
  font-size: 0.65rem;
}

/* Priority badge */
.priority-badge {
  font-size: 0.45rem;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.priority-critical {
  background: #7f1d1d;
  color: #fca5a5;
}

.priority-high {
  background: #7c2d12;
  color: #fdba74;
}

.priority-low {
  background: #1e3a5f;
  color: #93c5fd;
}

/* Trip acknowledgment */
.trip-ack-section {
  padding: 4px 0;
  border-top: 1px solid #1a1a3a;
  margin-top: 4px;
}

.ack-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.58rem;
  color: #86efac;
}

.ack-status.acknowledged {
  font-weight: 600;
  color: #86efac;
}

.ack-pending {
  font-size: 0.58rem;
  color: #fbbf24;
  font-style: italic;
}

.ack-trip-btn {
  width: 100%;
  margin-top: 4px;
  padding: 4px 8px;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: 1px solid var(--color-error);
  border-radius: 3px;
  background: transparent;
  color: var(--color-error);
  cursor: pointer;
}

.ack-trip-btn:hover {
  background: rgba(239, 68, 68, 0.1);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
