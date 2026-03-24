<script setup lang="ts">
import type { FleetSummary } from '../types'

defineProps<{ summary: FleetSummary }>()
const emit = defineEmits<{ toggleTheme: []; openSettings: [] }>()
</script>

<template>
  <header class="header">
    <div class="header-left">
      <h1 class="title">ICCSFlux Fleet Monitor</h1>
      <div class="summary">
        <span class="chip">
          <span class="dot connected"></span>{{ summary.connected }}/{{ summary.total }}
        </span>
        <span v-if="summary.healthy > 0" class="chip ok">
          <span class="dot green"></span>{{ summary.healthy }}
        </span>
        <span v-if="summary.warning > 0" class="chip warn">
          <span class="dot yellow"></span>{{ summary.warning }}
        </span>
        <span v-if="summary.error > 0" class="chip err">
          <span class="dot red"></span>{{ summary.error }}
        </span>
        <span v-if="summary.totalAlarms > 0" class="chip alarm">
          {{ summary.totalAlarms }} alarm{{ summary.totalAlarms > 1 ? 's' : '' }}
        </span>
      </div>
    </div>

    <div class="header-right">
      <button class="icon-btn" @click="emit('toggleTheme')" title="Toggle theme">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
      </button>
      <button class="icon-btn" @click="emit('openSettings')" title="Settings">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0;
  white-space: nowrap;
}

.summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
  background: var(--bg-status-pill);
  color: var(--text-secondary);
}

.chip.ok { background: var(--indicator-success-bg); color: var(--indicator-success-text); }
.chip.warn { background: var(--indicator-warning-bg); color: var(--indicator-warning-text); }
.chip.err { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); }
.chip.alarm { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); font-weight: 600; }

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.connected { background: var(--color-accent); }
.dot.green { background: var(--color-success); }
.dot.yellow { background: var(--color-warning); }
.dot.red { background: var(--color-error); }

.header-right {
  display: flex;
  gap: 0.375rem;
}

.icon-btn {
  width: 2rem;
  height: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--btn-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  transition: all 0.15s;
}

.icon-btn:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}
</style>
