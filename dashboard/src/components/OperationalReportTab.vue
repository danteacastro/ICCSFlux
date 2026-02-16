<script setup lang="ts">
/**
 * OperationalReportTab.vue — Unified operational event viewer.
 *
 * Merges data from two sources:
 * - Backend audit trail (logins, config changes, recording, sessions, system events)
 * - Client-side alarm/interlock history (triggers, acks, trips, bypasses)
 *
 * Time-range filterable, category filterable, searchable.
 * Audit trail requires Supervisor+; alarm/interlock history available to all roles.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useAuth, type AuditEvent } from '../composables/useAuth'
import { useSafety } from '../composables/useSafety'
import type { AlarmHistoryEntry, InterlockHistoryEntry } from '../types'

const auth = useAuth()
const safety = useSafety()

// ============================================================================
// Types
// ============================================================================

type Category = 'auth' | 'config' | 'alarm' | 'interlock' | 'recording' | 'session' | 'system'

interface ReportEvent {
  id: string
  timestamp: string
  category: Category
  eventType: string
  eventLabel: string
  user: string
  description: string
  details: Record<string, any>
  severity?: string
  channel?: string
}

// ============================================================================
// Filter state
// ============================================================================

const categoryFilter = ref<Category | null>(null)
const searchFilter = ref('')
const timePreset = ref<string>('24h')
const customStart = ref('')
const customEnd = ref('')
const expandedRow = ref<string | null>(null)
const isLoading = ref(false)

const presets = [
  { label: '1h', value: '1h', hours: 1 },
  { label: '6h', value: '6h', hours: 6 },
  { label: '24h', value: '24h', hours: 24 },
  { label: '7d', value: '7d', hours: 168 },
  { label: '30d', value: '30d', hours: 720 },
  { label: 'Custom', value: 'custom', hours: 0 },
]

const categoryMeta: Record<Category, { label: string; color: string; bg: string }> = {
  auth:       { label: 'Auth',       color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)' },
  config:     { label: 'Config',     color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' },
  alarm:      { label: 'Alarms',     color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)' },
  interlock:  { label: 'Interlocks', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.12)' },
  recording:  { label: 'Recording',  color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)' },
  session:    { label: 'Sessions',   color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.12)' },
  system:     { label: 'System',     color: '#6b7280', bg: 'rgba(107, 114, 128, 0.12)' },
}

// ============================================================================
// Time range
// ============================================================================

function getTimeRange(): { start: string; end: string } {
  const now = new Date()
  const end = now.toISOString()

  if (timePreset.value === 'custom') {
    return {
      start: customStart.value ? new Date(customStart.value).toISOString() : new Date(now.getTime() - 86400000).toISOString(),
      end: customEnd.value ? new Date(customEnd.value).toISOString() : end,
    }
  }

  const preset = presets.find(p => p.value === timePreset.value)
  const hours = preset?.hours || 24
  const start = new Date(now.getTime() - hours * 3600000).toISOString()
  return { start, end }
}

// ============================================================================
// Normalization
// ============================================================================

function categorizeEventType(eventType: string): Category {
  if (eventType.startsWith('user.') || eventType.startsWith('electronic.')) return 'auth'
  if (eventType.startsWith('config.')) return 'config'
  if (eventType.startsWith('alarm.')) return 'alarm'
  if (eventType.startsWith('safety.') || eventType === 'emergency.stop') return 'interlock'
  if (eventType.startsWith('recording.')) return 'recording'
  if (eventType.startsWith('test.session.') || eventType.startsWith('acquisition.')) return 'session'
  return 'system'
}

function formatEventLabel(eventType: string): string {
  return eventType
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

function normalizeAuditEvent(event: AuditEvent): ReportEvent {
  const raw = event as any
  return {
    id: `audit-${raw.event_id || raw.sequence || Math.random()}`,
    timestamp: event.timestamp,
    category: categorizeEventType(event.event_type),
    eventType: event.event_type,
    eventLabel: formatEventLabel(event.event_type),
    user: event.username || raw.user || 'system',
    description: raw.description || event.event_type,
    details: event.details || {},
    severity: raw.details?.severity,
  }
}

function normalizeAlarmHistory(entry: Readonly<AlarmHistoryEntry>): ReportEvent {
  return {
    id: `alarm-${entry.id}`,
    timestamp: entry.triggered_at,
    category: 'alarm',
    eventType: `alarm.${entry.event_type}`,
    eventLabel: `Alarm ${entry.event_type.charAt(0).toUpperCase() + entry.event_type.slice(1)}`,
    user: entry.acknowledged_by || entry.user || '',
    description: entry.message || `${entry.channel} ${entry.event_type}`,
    details: {
      channel: entry.channel,
      severity: entry.severity,
      value: entry.value,
      threshold: entry.threshold,
      duration_seconds: entry.duration_seconds,
      cleared_at: entry.cleared_at,
    },
    severity: String(entry.severity),
    channel: entry.channel,
  }
}

// Accept any to handle Vue's DeepReadonly wrapper on nested arrays
function normalizeInterlockHistory(entry: any): ReportEvent {
  return {
    id: `interlock-${entry.id}`,
    timestamp: entry.timestamp,
    category: 'interlock',
    eventType: `interlock.${entry.event}`,
    eventLabel: `Interlock ${String(entry.event).replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}`,
    user: entry.user || '',
    description: `${entry.interlockName}: ${String(entry.event).replace(/_/g, ' ')}`,
    details: {
      interlockId: entry.interlockId,
      interlockName: entry.interlockName,
      reason: entry.reason,
      ...(entry.details || {}),
    },
  }
}

// ============================================================================
// Merged event list
// ============================================================================

const allEvents = computed<ReportEvent[]>(() => {
  const events: ReportEvent[] = []
  const { start, end } = getTimeRange()
  const startMs = new Date(start).getTime()
  const endMs = new Date(end).getTime()

  // Source A: Audit trail (Supervisor+ only — controlled by backend)
  if (auth.auditEvents.value) {
    for (const event of auth.auditEvents.value) {
      const ts = new Date(event.timestamp).getTime()
      if (ts >= startMs && ts <= endMs) {
        events.push(normalizeAuditEvent(event))
      }
    }
  }

  // Source B: Client-side alarm history
  for (const entry of safety.alarmHistory.value) {
    const ts = new Date(entry.triggered_at).getTime()
    if (ts >= startMs && ts <= endMs) {
      events.push(normalizeAlarmHistory(entry))
    }
  }

  // Source C: Client-side interlock history
  for (const entry of safety.interlockHistory.value) {
    const ts = new Date(entry.timestamp).getTime()
    if (ts >= startMs && ts <= endMs) {
      events.push(normalizeInterlockHistory(entry))
    }
  }

  // Sort newest-first
  events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  return events
})

const filteredEvents = computed(() => {
  let events = allEvents.value

  if (categoryFilter.value) {
    events = events.filter(e => e.category === categoryFilter.value)
  }

  if (searchFilter.value) {
    const q = searchFilter.value.toLowerCase()
    events = events.filter(e =>
      e.user.toLowerCase().includes(q) ||
      e.description.toLowerCase().includes(q) ||
      e.eventType.toLowerCase().includes(q) ||
      e.eventLabel.toLowerCase().includes(q) ||
      (e.channel && e.channel.toLowerCase().includes(q))
    )
  }

  return events
})

// ============================================================================
// Summary counts
// ============================================================================

const categoryCounts = computed(() => {
  const counts: Record<Category, number> = {
    auth: 0, config: 0, alarm: 0, interlock: 0, recording: 0, session: 0, system: 0,
  }
  for (const event of allEvents.value) {
    counts[event.category]++
  }
  return counts
})

const categoryButtons = computed(() => {
  const categories: Category[] = ['auth', 'config', 'alarm', 'interlock', 'recording', 'session']
  return categories.map(cat => ({
    category: cat,
    ...categoryMeta[cat],
    count: categoryCounts.value[cat],
    active: categoryFilter.value === cat,
  }))
})

// ============================================================================
// Actions
// ============================================================================

function refresh() {
  const { start, end } = getTimeRange()
  isLoading.value = true

  // Query audit trail if Supervisor+
  if (auth.isSupervisor.value) {
    auth.queryAuditEvents({ start_time: start, end_time: end, limit: 1000 })
  }

  // Alarm/interlock history is reactive — no query needed
  // Wait a moment for audit response
  setTimeout(() => { isLoading.value = false }, 1500)
}

function exportCsv() {
  if (!auth.isSupervisor.value) return
  const { start, end } = getTimeRange()
  auth.exportAuditEvents({ format: 'csv', start_time: start, end_time: end })
}

function toggleCategory(cat: Category) {
  categoryFilter.value = categoryFilter.value === cat ? null : cat
}

function toggleRow(id: string) {
  expandedRow.value = expandedRow.value === id ? null : id
}

function setPreset(value: string) {
  timePreset.value = value
  if (value !== 'custom') {
    refresh()
  }
}

// ============================================================================
// Formatting
// ============================================================================

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return ts
  }
}

function formatDetails(details: Record<string, any>): string {
  if (!details || Object.keys(details).length === 0) return ''
  return Object.entries(details)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join('\n')
}

function formatTimeRange(): string {
  if (timePreset.value === 'custom') {
    const s = customStart.value ? new Date(customStart.value).toLocaleDateString() : '?'
    const e = customEnd.value ? new Date(customEnd.value).toLocaleDateString() : 'now'
    return `${s} – ${e}`
  }
  const p = presets.find(p => p.value === timePreset.value)
  return `Last ${p?.label || '24h'}`
}

// ============================================================================
// Lifecycle
// ============================================================================

onMounted(() => {
  refresh()
})

// Re-query when custom time range changes
watch([customStart, customEnd], () => {
  if (timePreset.value === 'custom' && customStart.value && customEnd.value) {
    refresh()
  }
})
</script>

<template>
  <div class="report-tab">
    <!-- Toolbar -->
    <div class="report-toolbar">
      <div class="toolbar-left">
        <!-- Time range presets -->
        <div class="time-presets">
          <button
            v-for="p in presets"
            :key="p.value"
            class="preset-btn"
            :class="{ active: timePreset === p.value }"
            @click="setPreset(p.value)"
          >{{ p.label }}</button>
        </div>

        <!-- Custom range inputs -->
        <div v-if="timePreset === 'custom'" class="custom-range">
          <input type="datetime-local" v-model="customStart" class="datetime-input" />
          <span class="range-sep">to</span>
          <input type="datetime-local" v-model="customEnd" class="datetime-input" />
        </div>

        <div class="separator" />

        <!-- Category filter buttons -->
        <div class="category-filters">
          <button
            v-for="btn in categoryButtons"
            :key="btn.category"
            class="cat-btn"
            :class="{ active: btn.active }"
            :style="{ '--cat-color': btn.color }"
            @click="toggleCategory(btn.category)"
          >
            {{ btn.label }}
            <span class="badge" v-if="btn.count > 0" :style="{ background: btn.color }">
              {{ btn.count > 999 ? '999+' : btn.count }}
            </span>
          </button>
        </div>
      </div>

      <div class="toolbar-right">
        <!-- Search -->
        <div class="search-box">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            v-model="searchFilter"
            placeholder="Search events..."
            class="search-input"
          />
        </div>

        <!-- Actions -->
        <button class="tool-btn" @click="refresh()" :disabled="isLoading" title="Refresh">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: isLoading }">
            <polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </button>
        <button
          class="tool-btn"
          @click="exportCsv()"
          :disabled="!auth.isSupervisor.value"
          :title="auth.isSupervisor.value ? 'Export audit trail as CSV' : 'Requires Supervisor role'"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Permission banner -->
    <div v-if="!auth.isSupervisor.value" class="permission-banner">
      Showing alarm and interlock history only. Log in as Supervisor to see full audit trail (logins, config changes, recording events).
    </div>

    <!-- Summary cards -->
    <div class="summary-cards">
      <div
        v-for="btn in categoryButtons"
        :key="btn.category"
        class="summary-card"
        :class="{ active: categoryFilter === btn.category }"
        :style="{ borderColor: btn.count > 0 ? btn.color : 'transparent' }"
        @click="toggleCategory(btn.category)"
      >
        <div class="card-count" :style="{ color: btn.color }">{{ btn.count }}</div>
        <div class="card-label">{{ btn.label }}</div>
      </div>
    </div>

    <!-- Event table -->
    <div class="event-list">
      <div v-if="filteredEvents.length === 0" class="empty-state">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <line x1="7" y1="8" x2="17" y2="8"/><line x1="7" y1="12" x2="17" y2="12"/>
          <line x1="7" y1="16" x2="13" y2="16"/>
        </svg>
        <span>No events in this time range</span>
        <span class="empty-hint" v-if="!auth.isSupervisor.value">
          Alarm and interlock events appear here during operation
        </span>
      </div>

      <div
        v-for="event in filteredEvents"
        :key="event.id"
        class="event-row"
        :class="{ expanded: expandedRow === event.id }"
        @click="toggleRow(event.id)"
      >
        <div class="event-main">
          <span class="event-time">{{ formatTimestamp(event.timestamp) }}</span>
          <span
            class="event-badge"
            :style="{
              color: categoryMeta[event.category].color,
              background: categoryMeta[event.category].bg,
            }"
          >{{ categoryMeta[event.category].label }}</span>
          <span class="event-label">{{ event.eventLabel }}</span>
          <span class="event-user" v-if="event.user">{{ event.user }}</span>
          <span class="event-desc">{{ event.description }}</span>
          <span class="event-channel" v-if="event.channel">{{ event.channel }}</span>
        </div>

        <!-- Expanded details -->
        <div v-if="expandedRow === event.id && Object.keys(event.details).length > 0" class="event-details">
          <pre>{{ formatDetails(event.details) }}</pre>
        </div>
      </div>
    </div>

    <!-- Status bar -->
    <div class="report-status-bar">
      <span>{{ filteredEvents.length }} events</span>
      <span v-if="categoryFilter" class="filter-active">
        Category: {{ categoryMeta[categoryFilter].label }}
      </span>
      <span v-if="searchFilter" class="filter-active">
        Search: "{{ searchFilter }}"
      </span>
      <span class="time-range-label">{{ formatTimeRange() }}</span>
    </div>
  </div>
</template>

<style scoped>
.report-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #1a1a2e);
  color: var(--text-primary, #e0e0e0);
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

/* Toolbar */
.report-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-secondary, #16213e);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  gap: 12px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.separator {
  width: 1px;
  height: 20px;
  background: var(--border-color, #2a2a4a);
}

/* Time presets */
.time-presets {
  display: flex;
  gap: 2px;
}

.preset-btn {
  padding: 3px 8px;
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  background: var(--bg-tertiary, #1a1a3e);
  color: var(--text-secondary, #a0a0b8);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.preset-btn:hover {
  background: var(--bg-hover, #2a2a4a);
  color: var(--text-primary, #e0e0e0);
}

.preset-btn.active {
  color: #3b82f6;
  border-color: #3b82f640;
  background: rgba(59, 130, 246, 0.1);
}

/* Custom range */
.custom-range {
  display: flex;
  align-items: center;
  gap: 6px;
}

.datetime-input {
  background: var(--bg-tertiary, #1a1a3e);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  color: var(--text-primary, #e0e0e0);
  font-size: 11px;
  padding: 3px 6px;
  font-family: inherit;
}

.range-sep {
  color: var(--text-tertiary, #666);
  font-size: 11px;
}

/* Category filter buttons */
.category-filters {
  display: flex;
  gap: 4px;
}

.cat-btn {
  padding: 3px 8px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: var(--bg-tertiary, #1a1a3e);
  color: var(--text-secondary, #a0a0b8);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
  font-family: inherit;
}

.cat-btn:hover {
  background: var(--bg-hover, #2a2a4a);
  color: var(--cat-color);
}

.cat-btn.active {
  color: var(--cat-color);
  border-color: var(--cat-color);
  background: color-mix(in srgb, var(--cat-color) 15%, transparent);
}

.badge {
  color: #fff;
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 8px;
  min-width: 14px;
  text-align: center;
}

/* Search */
.search-box {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-tertiary, #1a1a3e);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  padding: 2px 8px;
  color: var(--text-tertiary, #888);
}

.search-input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary, #e0e0e0);
  font-size: 12px;
  width: 150px;
  font-family: inherit;
}

.search-input::placeholder {
  color: var(--text-tertiary, #666);
}

.tool-btn {
  padding: 4px 6px;
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  background: var(--bg-tertiary, #1a1a3e);
  color: var(--text-secondary, #a0a0b8);
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: all 0.15s ease;
}

.tool-btn:hover:not(:disabled) {
  background: var(--bg-hover, #2a2a4a);
  color: var(--text-primary, #e0e0e0);
}

.tool-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spinning {
  animation: spin 1s linear infinite;
}

/* Permission banner */
.permission-banner {
  padding: 6px 12px;
  background: rgba(59, 130, 246, 0.1);
  border-bottom: 1px solid rgba(59, 130, 246, 0.2);
  color: #93c5fd;
  font-size: 11px;
  flex-shrink: 0;
}

/* Summary cards */
.summary-cards {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
}

.summary-card {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-secondary, #16213e);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 6px;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s ease;
  border-left: 3px solid transparent;
}

.summary-card:hover {
  background: var(--bg-hover, #2a2a4a);
}

.summary-card.active {
  background: var(--bg-hover, #2a2a4a);
}

.card-count {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.card-label {
  font-size: 10px;
  color: var(--text-tertiary, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Event list */
.event-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: var(--text-tertiary, #666);
  font-size: 13px;
}

.empty-hint {
  font-size: 11px;
  opacity: 0.6;
}

.event-row {
  border-bottom: 1px solid var(--border-color, #2a2a4a10);
  cursor: pointer;
  transition: background 0.1s ease;
}

.event-row:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.03));
}

.event-main {
  display: flex;
  align-items: center;
  padding: 5px 12px;
  gap: 10px;
  font-size: 12px;
}

.event-time {
  color: var(--text-tertiary, #666);
  font-size: 11px;
  flex-shrink: 0;
  min-width: 130px;
}

.event-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  min-width: 70px;
  text-align: center;
}

.event-label {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
  flex-shrink: 0;
  min-width: 160px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-user {
  color: #3b82f6;
  font-size: 11px;
  flex-shrink: 0;
  min-width: 80px;
}

.event-desc {
  color: var(--text-secondary, #a0a0b8);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
}

.event-channel {
  color: #f59e0b;
  font-size: 11px;
  flex-shrink: 0;
}

/* Expanded details */
.event-details {
  padding: 4px 12px 8px 152px;
  border-top: 1px solid var(--border-color, #2a2a4a20);
}

.event-details pre {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary, #a0a0b8);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

/* Status bar */
.report-status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 4px 12px;
  background: var(--bg-secondary, #16213e);
  border-top: 1px solid var(--border-color, #2a2a4a);
  font-size: 11px;
  color: var(--text-tertiary, #888);
  flex-shrink: 0;
}

.filter-active {
  color: #f59e0b;
}

.time-range-label {
  margin-left: auto;
  color: var(--text-secondary, #a0a0b8);
}

/* Scrollbar styling */
.event-list::-webkit-scrollbar {
  width: 6px;
}

.event-list::-webkit-scrollbar-track {
  background: transparent;
}

.event-list::-webkit-scrollbar-thumb {
  background: var(--border-color, #2a2a4a);
  border-radius: 3px;
}

.event-list::-webkit-scrollbar-thumb:hover {
  background: var(--text-tertiary, #666);
}
</style>
