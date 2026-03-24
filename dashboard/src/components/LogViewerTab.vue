<script setup lang="ts">
/**
 * LogViewerTab.vue — Real-time service log viewer.
 *
 * Shows backend service logs streamed over MQTT with:
 * - Level filter buttons (DEBUG/INFO/WARNING/ERROR) with counts
 * - Text search filter
 * - Auto-scroll with pause on scroll-up
 * - Color-coded level badges
 * - Clear and refresh controls
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useLogViewer } from '../composables/useLogViewer'
import type { LogEntry } from '../types'

const logViewer = useLogViewer()

const logContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const showDebug = ref(false)

// Level colors matching ISA/industrial standards
const levelColors: Record<string, string> = {
  DEBUG: '#6b7280',
  INFO: '#3b82f6',
  WARNING: '#f59e0b',
  ERROR: '#ef4444',
  CRITICAL: '#dc2626',
}

const levelBgColors: Record<string, string> = {
  DEBUG: 'rgba(107, 114, 128, 0.15)',
  INFO: 'rgba(59, 130, 246, 0.15)',
  WARNING: 'rgba(245, 158, 11, 0.15)',
  ERROR: 'rgba(239, 68, 68, 0.15)',
  CRITICAL: 'rgba(220, 38, 38, 0.25)',
}

const levelButtons = computed(() => {
  const levels = showDebug.value
    ? ['DEBUG', 'INFO', 'WARNING', 'ERROR']
    : ['INFO', 'WARNING', 'ERROR']
  return levels.map(level => ({
    level,
    count: logViewer.levelCounts.value[level] || 0,
    active: logViewer.levelFilter.value === level,
    color: levelColors[level],
  }))
})

function toggleLevel(level: string) {
  if (logViewer.levelFilter.value === level) {
    logViewer.setLevelFilter(null) // Clear filter
  } else {
    logViewer.setLevelFilter(level)
  }
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts)
    const time = d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    const ms = String(d.getMilliseconds()).padStart(3, '0')
    return `${time}.${ms}`
  } catch {
    return ts
  }
}

function handleScroll() {
  if (!logContainer.value) return
  const el = logContainer.value
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  autoScroll.value = atBottom
}

function scrollToBottom() {
  if (!logContainer.value) return
  autoScroll.value = true
  logContainer.value.scrollTop = logContainer.value.scrollHeight
}

// Auto-scroll when new entries arrive
watch(() => logViewer.filteredEntries.value.length, () => {
  if (autoScroll.value) {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
})

onMounted(() => {
  // Scroll to bottom on mount
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
})
</script>

<template>
  <div class="log-viewer-tab">
    <!-- Toolbar -->
    <div class="log-toolbar">
      <div class="toolbar-left">
        <!-- Level filter buttons -->
        <div class="level-filters">
          <button
            v-for="btn in levelButtons"
            :key="btn.level"
            class="level-btn"
            :class="{ active: btn.active }"
            :style="{
              '--level-color': btn.color,
              borderColor: btn.active ? btn.color : 'transparent',
            }"
            @click="toggleLevel(btn.level)"
            :title="`Filter by ${btn.level} and above`"
          >
            {{ btn.level }}
            <span class="badge" v-if="btn.count > 0">{{ btn.count > 999 ? '999+' : btn.count }}</span>
          </button>
        </div>

        <!-- Debug toggle -->
        <label class="debug-toggle" title="Show DEBUG level logs">
          <input type="checkbox" v-model="showDebug" />
          <span>Debug</span>
        </label>
      </div>

      <div class="toolbar-right">
        <!-- Search -->
        <div class="search-box">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            :value="logViewer.searchFilter.value"
            @input="logViewer.setSearchFilter(($event.target as HTMLInputElement).value)"
            placeholder="Search logs..."
            class="search-input"
          />
        </div>

        <!-- Actions -->
        <button class="tool-btn" @click="logViewer.refreshLogs()" title="Refresh logs from backend">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </button>
        <button class="tool-btn" @click="logViewer.clearLogs()" title="Clear all logs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3,6 5,6 21,6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
        <button
          class="tool-btn"
          :class="{ active: autoScroll }"
          @click="scrollToBottom()"
          title="Scroll to bottom / Auto-scroll"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19,12 12,19 5,12"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Log entries -->
    <div
      ref="logContainer"
      class="log-entries"
      @scroll="handleScroll"
    >
      <div
        v-if="logViewer.filteredEntries.value.length === 0"
        class="empty-state"
      >
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/>
        </svg>
        <span>No log entries{{ logViewer.levelFilter.value ? ` at ${logViewer.levelFilter.value} level` : '' }}</span>
        <span class="empty-hint">Logs stream from the backend service while it is running</span>
      </div>

      <div
        v-for="(entry, i) in logViewer.filteredEntries.value"
        :key="i"
        class="log-entry"
        :style="{ backgroundColor: levelBgColors[entry.level] || 'transparent' }"
      >
        <span class="log-time">{{ formatTimestamp(entry.timestamp) }}</span>
        <span
          class="log-level"
          :style="{ color: levelColors[entry.level] || '#888' }"
        >{{ entry.level.padEnd(8) }}</span>
        <span class="log-logger">{{ entry.logger }}</span>
        <span class="log-message">{{ entry.message }}</span>
      </div>
    </div>

    <!-- Status bar -->
    <div class="log-status-bar">
      <span>{{ logViewer.filteredEntries.value.length }} entries</span>
      <span v-if="logViewer.levelFilter.value" class="filter-active">
        Filtering: {{ logViewer.levelFilter.value }}+
      </span>
      <span v-if="logViewer.searchFilter.value" class="filter-active">
        Search: "{{ logViewer.searchFilter.value }}"
      </span>
      <span class="auto-scroll-indicator" :class="{ active: autoScroll }">
        {{ autoScroll ? 'Auto-scroll ON' : 'Auto-scroll paused' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.log-viewer-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #1a1a2e);
  color: var(--text-primary, #e0e0e0);
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

.log-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-secondary, #16213e);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  gap: 12px;
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.level-filters {
  display: flex;
  gap: 4px;
}

.level-btn {
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
}

.level-btn:hover {
  background: var(--bg-hover, #2a2a4a);
  color: var(--level-color);
}

.level-btn.active {
  color: var(--level-color);
  background: color-mix(in srgb, var(--level-color) 15%, transparent);
}

.badge {
  background: var(--level-color, #666);
  color: #fff;
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 8px;
  min-width: 14px;
  text-align: center;
}

.debug-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-tertiary, #888);
  cursor: pointer;
}

.debug-toggle input {
  width: 12px;
  height: 12px;
}

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

.tool-btn:hover {
  background: var(--bg-hover, #2a2a4a);
  color: var(--text-primary, #e0e0e0);
}

.tool-btn.active {
  color: #22c55e;
  border-color: #22c55e40;
}

.log-entries {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 0;
  font-size: 12px;
  line-height: 1.6;
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

.log-entry {
  display: flex;
  padding: 1px 12px;
  border-bottom: 1px solid var(--border-color, #2a2a4a10);
  white-space: nowrap;
  gap: 0;
}

.log-entry:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.03)) !important;
}

.log-time {
  color: var(--text-tertiary, #666);
  margin-right: 10px;
  flex-shrink: 0;
  font-size: 11px;
}

.log-level {
  font-weight: 700;
  margin-right: 10px;
  flex-shrink: 0;
  font-size: 11px;
  min-width: 70px;
}

.log-logger {
  color: var(--text-secondary, #a0a0b8);
  margin-right: 10px;
  flex-shrink: 0;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
}

.log-message {
  color: var(--text-primary, #e0e0e0);
  white-space: pre-wrap;
  word-break: break-word;
  flex: 1;
  min-width: 0;
  font-size: 11.5px;
}

.log-status-bar {
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

.auto-scroll-indicator {
  margin-left: auto;
}

.auto-scroll-indicator.active {
  color: #22c55e;
}

/* Scrollbar styling */
.log-entries::-webkit-scrollbar {
  width: 6px;
}

.log-entries::-webkit-scrollbar-track {
  background: transparent;
}

.log-entries::-webkit-scrollbar-thumb {
  background: var(--border-color, #2a2a4a);
  border-radius: 3px;
}

.log-entries::-webkit-scrollbar-thumb:hover {
  background: var(--text-tertiary, #666);
}
</style>
