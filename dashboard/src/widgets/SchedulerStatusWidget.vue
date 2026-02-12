<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import { useMqtt } from '../composables/useMqtt'

const props = defineProps<{
  showToggle?: boolean
  maxItems?: number
}>()

const store = useDashboardStore()
const scripts = useScripts()
const mqtt = useMqtt('nisystem')

const isSchedulerEnabled = computed(() => store.isSchedulerEnabled)
const schedules = computed(() => scripts.schedules.value)

// Get enabled schedules sorted by next run
const activeSchedules = computed(() => {
  return schedules.value
    .filter(s => s.enabled)
    .sort((a, b) => {
      if (!a.nextRun) return 1
      if (!b.nextRun) return -1
      return new Date(a.nextRun).getTime() - new Date(b.nextRun).getTime()
    })
    .slice(0, props.maxItems ?? 3)
})

const nextSchedule = computed(() => {
  if (activeSchedules.value.length === 0) return null
  return activeSchedules.value[0]
})

const nextRunTime = computed(() => {
  if (!nextSchedule.value?.nextRun) return null
  const date = new Date(nextSchedule.value.nextRun)
  const now = new Date()
  const diffMs = date.getTime() - now.getTime()

  if (diffMs < 0) return 'Overdue'

  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const mins = diffMins % 60

  if (diffHours > 24) {
    return date.toLocaleDateString('en-US', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  }
  if (diffHours > 0) {
    return `${diffHours}h ${mins}m`
  }
  return `${mins}m`
})

function formatTime(timeStr: string): string {
  const parts = timeStr.split(':')
  const hours = parts[0] || '0'
  const mins = parts[1] || '00'
  const h = parseInt(hours, 10)
  const ampm = h >= 12 ? 'PM' : 'AM'
  const h12 = h % 12 || 12
  return `${h12}:${mins} ${ampm}`
}

function toggleScheduler() {
  if (isSchedulerEnabled.value) {
    mqtt.disableScheduler()
  } else {
    mqtt.enableScheduler()
  }
}
</script>

<template>
  <div class="scheduler-status-widget" :class="{ enabled: isSchedulerEnabled }">
    <div class="header">
      <span class="title">Scheduler</span>
      <button
        v-if="showToggle !== false"
        class="toggle-btn"
        :class="{ active: isSchedulerEnabled }"
        @click="toggleScheduler"
      >
        {{ isSchedulerEnabled ? 'ON' : 'OFF' }}
      </button>
    </div>

    <div v-if="!isSchedulerEnabled" class="disabled-state">
      <span class="status-text">Disabled</span>
    </div>

    <template v-else>
      <div v-if="activeSchedules.length === 0" class="no-schedules">
        No active schedules
      </div>

      <div v-else class="schedule-list">
        <div v-if="nextSchedule" class="next-run">
          <span class="next-label">Next:</span>
          <span class="next-time">{{ nextRunTime }}</span>
        </div>

        <div
          v-for="schedule in activeSchedules"
          :key="schedule.id"
          class="schedule-item"
          :class="{ running: schedule.isRunning }"
        >
          <span class="schedule-name">{{ schedule.name }}</span>
          <span class="schedule-time">{{ formatTime(schedule.startTime) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.scheduler-status-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
}

.toggle-btn {
  padding: 2px 8px;
  border: none;
  border-radius: 3px;
  font-size: 0.6rem;
  font-weight: 700;
  cursor: pointer;
  background: #374151;
  color: #9ca3af;
}

.toggle-btn.active {
  background: #22c55e;
  color: #fff;
}

.toggle-btn:hover {
  filter: brightness(1.1);
}

.disabled-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-text {
  font-size: 0.8rem;
  color: #666;
}

.no-schedules {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  color: #666;
}

.schedule-list {
  flex: 1;
  overflow-y: auto;
}

.next-run {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: rgba(59, 130, 246, 0.2);
  border-radius: 4px;
  margin-bottom: 6px;
}

.next-label {
  font-size: 0.65rem;
  color: #60a5fa;
  font-weight: 600;
}

.next-time {
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', monospace;
  color: #3b82f6;
  font-weight: 600;
}

.schedule-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid #1f1f35;
}

.schedule-item:last-child {
  border-bottom: none;
}

.schedule-item.running {
  background: rgba(34, 197, 94, 0.1);
  padding: 4px 6px;
  margin: 0 -6px;
  border-radius: 3px;
}

.schedule-name {
  font-size: 0.7rem;
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}

.schedule-time {
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  color: #888;
}

.enabled {
  border-color: #22c55e40;
}
</style>
