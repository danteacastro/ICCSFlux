<script setup lang="ts">
import type { SafetyStatus } from '../types'

const props = defineProps<{ safety: SafetyStatus | null }>()
</script>

<template>
  <section v-if="safety" class="section">
    <h3 class="section-title">Safety / Interlocks</h3>
    <div class="latch-row">
      <span class="label">Latch State</span>
      <span class="latch-badge" :class="safety.latchState.toLowerCase()">
        {{ safety.latchState }}
      </span>
      <span v-if="safety.isTripped" class="tripped-badge">TRIPPED</span>
    </div>

    <div v-if="safety.interlockStatuses.length > 0" class="interlocks">
      <div
        v-for="il in safety.interlockStatuses"
        :key="il.id"
        class="interlock-row"
        :class="{ failed: !il.satisfied && il.enabled, bypassed: il.bypassed }"
      >
        <span class="il-dot" :class="il.satisfied ? 'ok' : (il.enabled ? 'fail' : 'off')"></span>
        <span class="il-name">{{ il.name }}</span>
        <span v-if="il.bypassed" class="il-tag bypass">BYPASS</span>
        <span v-if="!il.enabled" class="il-tag disabled">DISABLED</span>
        <span v-if="il.hasOfflineChannels" class="il-tag offline">OFFLINE CH</span>
        <span v-if="il.failedConditions?.length" class="il-fails">
          {{ il.failedConditions.join(', ') }}
        </span>
      </div>
    </div>
    <div v-else class="no-data">No interlocks configured</div>
  </section>
</template>

<style scoped>
.section {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 1rem;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 0.75rem;
}

.latch-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-bottom: 0.75rem;
}

.label {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.latch-badge {
  padding: 0.2rem 0.625rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 700;
}

.latch-badge.safe { background: var(--indicator-success-bg); color: var(--indicator-success-text); }
.latch-badge.armed { background: var(--indicator-warning-bg); color: var(--indicator-warning-text); }
.latch-badge.tripped { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); }

.tripped-badge {
  padding: 0.2rem 0.625rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 700;
  background: var(--indicator-danger-bg);
  color: var(--indicator-danger-text);
  animation: pulse 1s infinite;
}

.interlocks {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.interlock-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.5rem;
  border-radius: 4px;
  background: var(--bg-panel-row);
  font-size: 0.8rem;
}

.interlock-row.failed {
  background: var(--color-error-bg);
}

.il-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.il-dot.ok { background: var(--color-success); }
.il-dot.fail { background: var(--color-error); }
.il-dot.off { background: var(--text-muted); }

.il-name {
  color: var(--text-primary);
  flex: 1;
}

.il-tag {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.il-tag.bypass { background: var(--indicator-warning-bg); color: var(--indicator-warning-text); }
.il-tag.disabled { background: var(--bg-status-pill); color: var(--text-muted); }
.il-tag.offline { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); }

.il-fails {
  font-size: 0.7rem;
  color: var(--text-dim);
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.no-data {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-style: italic;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
