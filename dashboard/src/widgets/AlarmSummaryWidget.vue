<script setup lang="ts">
import { computed } from 'vue'
import { useSafety } from '../composables/useSafety'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  title?: string
  showAckButton?: boolean
  compact?: boolean
  style?: WidgetStyle
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

const safety = useSafety()

const hasIssues = computed(() =>
  safety.hasActiveAlarms.value ||
  safety.hasActiveWarnings.value ||
  safety.hasLatchedAlarms.value
)

const blockedCount = computed(() =>
  safety.interlockStatuses.value.filter(s => !s.satisfied && s.enabled && !s.bypassed).length
)
</script>

<template>
  <div class="alarm-summary-widget" :class="{ compact: props.compact, 'has-issues': hasIssues }" :style="containerStyle">
    <!-- Widget title -->
    <div v-if="title" class="widget-title">{{ title }}</div>

    <!-- All Clear State -->
    <div v-if="!hasIssues && blockedCount === 0" class="all-clear">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <span>All Clear</span>
    </div>

    <!-- Issues Present -->
    <template v-else>
      <div class="summary-row">
        <!-- Alarms -->
        <div class="stat alarm" :class="{ active: safety.alarmCounts.value.active > 0 }">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
          </svg>
          <span class="count">{{ safety.alarmCounts.value.active }}</span>
          <span class="label">Alarms</span>
        </div>

        <!-- Warnings -->
        <div class="stat warning" :class="{ active: (safety.alarmCounts.value.warnings ?? 0) > 0 }">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
          </svg>
          <span class="count">{{ safety.alarmCounts.value.warnings ?? 0 }}</span>
          <span class="label">Warnings</span>
        </div>

        <!-- Acknowledged -->
        <div class="stat acknowledged" :class="{ active: safety.alarmCounts.value.acknowledged > 0 }">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
          </svg>
          <span class="count">{{ safety.alarmCounts.value.acknowledged }}</span>
          <span class="label">Ack'd</span>
        </div>
      </div>

      <!-- Latched indicator -->
      <div v-if="safety.hasLatchedAlarms.value" class="latched-row" @click="safety.resetAllLatched()">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 17a2 2 0 002-2V9a2 2 0 00-4 0v6a2 2 0 002 2zm6-9v6a6 6 0 11-12 0V8h2v6a4 4 0 008 0V8h2z"/>
        </svg>
        <span>{{ safety.latchedAlarmCount.value }} Latched</span>
        <span class="reset-hint">Click to reset</span>
      </div>

      <!-- Blocked interlocks -->
      <div v-if="blockedCount > 0" class="blocked-row">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>{{ blockedCount }} Blocked</span>
      </div>

      <!-- Acknowledge All Button -->
      <button
        v-if="showAckButton !== false && safety.alarmCounts.value.active > 0"
        class="ack-btn"
        @click="safety.acknowledgeAll()"
      >
        ACK ALL
      </button>
    </template>
  </div>
</template>

<style scoped>
.alarm-summary-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 6px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 3px;
  overflow: hidden;
  min-height: 0;
}

.widget-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding-bottom: 3px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.alarm-summary-widget.has-issues {
  border-color: #7f1d1d;
}

.all-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex: 1;
  min-height: 0;
  color: #4ade80;
  font-size: 0.85rem;
  font-weight: 600;
}

.summary-row {
  display: flex;
  gap: 4px;
  justify-content: space-around;
  flex-shrink: 1;
  min-height: 0;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 3px 6px;
  border-radius: 4px;
  background: var(--bg-secondary);
  opacity: 0.5;
  min-width: 44px;
  min-height: 0;
}

.stat.active {
  opacity: 1;
}

.stat.alarm.active {
  background: #7f1d1d;
  color: #fca5a5;
  animation: pulse 1s infinite;
}

.stat.warning.active {
  background: #78350f;
  color: #fbbf24;
}

.stat.acknowledged.active {
  background: #1e3a5f;
  color: #60a5fa;
}

.stat .count {
  font-size: 1rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  line-height: 1.1;
}

.stat .label {
  font-size: 0.55rem;
  text-transform: uppercase;
  color: inherit;
  opacity: 0.8;
  line-height: 1;
}

.latched-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 3px 6px;
  background: #7f1d1d;
  color: #fca5a5;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
  cursor: pointer;
  animation: pulse 1s infinite;
  flex-shrink: 0;
}

.latched-row:hover {
  background: #991b1b;
}

.reset-hint {
  font-size: 0.55rem;
  opacity: 0.7;
  font-weight: 400;
}

.blocked-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 3px 6px;
  background: #78350f;
  color: #fbbf24;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
  flex-shrink: 0;
}

.ack-btn {
  padding: 4px 10px;
  background: var(--btn-secondary-bg);
  border: 1px solid var(--btn-secondary-hover);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.65rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.ack-btn:hover {
  background: var(--btn-secondary-hover);
}

/* Compact mode */
.compact .summary-row {
  flex-direction: row;
}

.compact .stat {
  flex-direction: row;
  gap: 4px;
  padding: 2px 5px;
}

.compact .stat .count {
  font-size: 0.85rem;
}

.compact .stat .label {
  display: none;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
