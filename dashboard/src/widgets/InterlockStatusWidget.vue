<script setup lang="ts">
import { computed } from 'vue'
import { useSafety } from '../composables/useSafety'

defineProps<{
  compact?: boolean
  showBypassButtons?: boolean
}>()

const safety = useSafety()

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

const allSatisfied = computed(() => blockedCount.value === 0 && bypassedCount.value === 0)

function toggleBypass(id: string) {
  const interlock = safety.interlocks.value.find(i => i.id === id)
  if (interlock && interlock.bypassAllowed) {
    safety.bypassInterlock(id, !interlock.bypassed)
  }
}
</script>

<template>
  <div class="interlock-status-widget" :class="{ compact, 'has-blocked': blockedCount > 0 }">
    <!-- No interlocks configured -->
    <div v-if="!hasInterlocks" class="no-interlocks">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <span>No interlocks</span>
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
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
          <span class="count">{{ bypassedCount }}</span>
          <span class="label">BYP</span>
        </div>
      </div>

      <!-- All clear indicator -->
      <div v-if="allSatisfied" class="all-clear">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>All Clear</span>
      </div>

      <!-- Interlock list (compact shows only blocked) -->
      <div class="interlock-list" v-if="!allSatisfied || !compact">
        <div
          v-for="status in (compact ? interlockStatuses.filter(s => !s.satisfied && s.enabled && !s.bypassed) : interlockStatuses)"
          :key="status.id"
          class="interlock-item"
          :class="{
            satisfied: status.satisfied && !status.bypassed,
            blocked: !status.satisfied && !status.bypassed,
            bypassed: status.bypassed,
            disabled: !status.enabled
          }"
        >
          <span class="status-icon">
            <svg v-if="status.satisfied || status.bypassed" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            <svg v-else width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </span>
          <span class="name">{{ status.name }}</span>
          <span v-if="status.bypassed" class="bypass-badge">BYP</span>
          <button
            v-if="showBypassButtons && safety.interlocks.value.find(i => i.id === status.id)?.bypassAllowed && !status.satisfied"
            class="bypass-btn"
            @click="toggleBypass(status.id)"
          >
            {{ status.bypassed ? 'X' : 'BYP' }}
          </button>
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
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 6px;
}

.interlock-status-widget.has-blocked {
  border-color: #78350f;
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

.summary-row {
  display: flex;
  gap: 8px;
  justify-content: center;
}

.stat {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #0f0f1a;
  border-radius: 4px;
  opacity: 0.5;
}

.stat.active {
  opacity: 1;
}

.stat.ok.active {
  background: #14532d;
  color: #86efac;
}

.stat.blocked.active {
  background: #7f1d1d;
  color: #fca5a5;
  animation: pulse 1s infinite;
}

.stat.bypassed.active {
  background: #78350f;
  color: #fbbf24;
}

.stat .count {
  font-size: 0.9rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}

.stat .label {
  font-size: 0.55rem;
  text-transform: uppercase;
}

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

.interlock-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.interlock-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  background: #0f0f1a;
  border-radius: 3px;
  font-size: 0.7rem;
}

.interlock-item.satisfied {
  color: #86efac;
}

.interlock-item.blocked {
  color: #fca5a5;
  background: linear-gradient(90deg, #3f1515 0%, #0f0f1a 50%);
}

.interlock-item.bypassed {
  color: #fbbf24;
}

.interlock-item.disabled {
  opacity: 0.4;
}

.status-icon {
  flex-shrink: 0;
  width: 12px;
  height: 12px;
}

.name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bypass-badge {
  font-size: 0.5rem;
  padding: 1px 4px;
  background: #fbbf24;
  color: #000;
  border-radius: 2px;
  font-weight: 700;
}

.bypass-btn {
  font-size: 0.5rem;
  padding: 2px 4px;
  background: #374151;
  border: none;
  border-radius: 2px;
  color: #fff;
  cursor: pointer;
}

.bypass-btn:hover {
  background: #4b5563;
}

/* Compact mode */
.compact .interlock-list {
  max-height: 60px;
}

.compact .interlock-item {
  padding: 2px 4px;
  font-size: 0.65rem;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
