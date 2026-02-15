<script setup lang="ts">
import type { NodeState } from '../types'
import StatusSection from './StatusSection.vue'
import ResourceSection from './ResourceSection.vue'
import HardwareSection from './HardwareSection.vue'
import AlarmSection from './AlarmSection.vue'
import SafetySection from './SafetySection.vue'
import WatchdogSection from './WatchdogSection.vue'
import ConnectionSection from './ConnectionSection.vue'

const props = defineProps<{ nodeState: NodeState }>()
const emit = defineEmits<{ reconnect: [] }>()
</script>

<template>
  <div class="detail">
    <!-- Header -->
    <div class="detail-header">
      <div class="detail-title-row">
        <span class="dot" :class="nodeState.health"></span>
        <h2 class="detail-name">{{ nodeState.node.name }}</h2>
        <span class="detail-host mono">{{ nodeState.node.host }}:{{ nodeState.node.port }}</span>
      </div>
      <div class="health-reasons">
        <span v-for="r in nodeState.healthReasons" :key="r" class="reason" :class="nodeState.health">
          {{ r }}
        </span>
      </div>
    </div>

    <!-- Sections -->
    <div class="sections">
      <StatusSection :status="nodeState.status" :heartbeat="nodeState.heartbeat" />
      <ResourceSection :status="nodeState.status" />
      <HardwareSection :health="nodeState.status?.hardware_health ?? null" />
      <AlarmSection :alarms="nodeState.alarms" />
      <SafetySection :safety="nodeState.safety" />
      <WatchdogSection :watchdog="nodeState.watchdog" />
      <ConnectionSection
        :connection="nodeState.connection"
        :last-message-time="nodeState.lastMessageTime"
        @reconnect="emit('reconnect')"
      />
    </div>
  </div>
</template>

<style scoped>
.detail {
  padding: 1.25rem;
  max-width: 900px;
}

.detail-header {
  margin-bottom: 1.25rem;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-bottom: 0.5rem;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.healthy { background: var(--color-success); box-shadow: 0 0 8px var(--color-success); }
.dot.warning { background: var(--color-warning); box-shadow: 0 0 8px var(--color-warning); }
.dot.error { background: var(--color-error); box-shadow: 0 0 8px var(--color-error); }
.dot.unknown { background: var(--text-muted); }

.detail-name {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0;
}

.detail-host {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.health-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.reason {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  background: var(--bg-status-pill);
  color: var(--text-secondary);
}

.reason.error { background: var(--indicator-danger-bg); color: var(--indicator-danger-text); }
.reason.warning { background: var(--indicator-warning-bg); color: var(--indicator-warning-text); }
.reason.healthy { background: var(--indicator-success-bg); color: var(--indicator-success-text); }

.sections {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
</style>
