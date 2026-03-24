/**
 * useLogViewer - Composable for the real-time Log Viewer tab
 *
 * Provides reactive state for viewing service logs streamed over MQTT:
 * - Receives log entries from backend MqttLogHandler
 * - Level and text filtering
 * - Level badge counts
 * - Initial query on first use
 *
 * Singleton pattern: module-level refs shared across all callers.
 */

import { ref, computed, onUnmounted } from 'vue'
import { useMqtt } from './useMqtt'
import type { LogEntry } from '../types'

// ── Singleton state ──────────────────────────────────────────

const logEntries = ref<LogEntry[]>([])
const levelFilter = ref<string | null>(null)  // null = all levels
const searchFilter = ref('')
const MAX_ENTRIES = 2000

let handlersInitialized = false
let cleanupStream: (() => void) | null = null
let cleanupQuery: (() => void) | null = null

// ── Computed ─────────────────────────────────────────────────

const LEVEL_ORDER: Record<string, number> = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3,
  CRITICAL: 4,
}

const filteredEntries = computed(() => {
  let entries = logEntries.value

  // Level filter
  if (levelFilter.value) {
    const minLevel = LEVEL_ORDER[levelFilter.value] ?? 0
    entries = entries.filter(e => (LEVEL_ORDER[e.level] ?? 0) >= minLevel)
  }

  // Text search filter
  if (searchFilter.value) {
    const search = searchFilter.value.toLowerCase()
    entries = entries.filter(e =>
      e.message.toLowerCase().includes(search) ||
      e.logger.toLowerCase().includes(search)
    )
  }

  return entries
})

const levelCounts = computed(() => {
  const counts: Record<string, number> = {
    DEBUG: 0,
    INFO: 0,
    WARNING: 0,
    ERROR: 0,
    CRITICAL: 0,
  }
  for (const entry of logEntries.value) {
    if (entry.level in counts && counts[entry.level] !== undefined) {
      counts[entry.level] = (counts[entry.level] ?? 0) + 1
    }
  }
  return counts
})

// ── Setup ────────────────────────────────────────────────────

function initHandlers() {
  if (handlersInitialized) return
  handlersInitialized = true

  const mqtt = useMqtt()

  // Handle streaming log entries (periodic drain from backend)
  cleanupStream = mqtt.onLogStream((entries: LogEntry[]) => {
    const current = logEntries.value
    const combined = [...current, ...entries]
    // Cap at MAX_ENTRIES, keeping newest
    if (combined.length > MAX_ENTRIES) {
      logEntries.value = combined.slice(combined.length - MAX_ENTRIES)
    } else {
      logEntries.value = combined
    }
  })

  // Handle query response (initial load)
  cleanupQuery = mqtt.onLogQuery((result) => {
    if (result.success && result.entries) {
      const current = logEntries.value
      // Merge: query results are historical, append any new entries after
      const combined = [...result.entries, ...current]
      if (combined.length > MAX_ENTRIES) {
        logEntries.value = combined.slice(combined.length - MAX_ENTRIES)
      } else {
        logEntries.value = combined
      }
    }
  })

  // Request recent logs on first connect
  mqtt.queryLogs(200)
}

// ── Public API ───────────────────────────────────────────────

export function useLogViewer() {
  initHandlers()

  function clearLogs() {
    logEntries.value = []
  }

  function setLevelFilter(level: string | null) {
    levelFilter.value = level
  }

  function setSearchFilter(text: string) {
    searchFilter.value = text
  }

  function refreshLogs() {
    const mqtt = useMqtt()
    mqtt.queryLogs(500)
  }

  return {
    logEntries,
    filteredEntries,
    levelFilter,
    searchFilter,
    levelCounts,
    clearLogs,
    setLevelFilter,
    setSearchFilter,
    refreshLogs,
  }
}
