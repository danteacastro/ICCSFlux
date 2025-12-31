<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const props = defineProps<{
  label?: string
  showDate?: boolean
  showElapsed?: boolean
  format24h?: boolean
}>()

const store = useDashboardStore()

const now = ref(new Date())
let intervalId: number | null = null

onMounted(() => {
  intervalId = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})

const displayLabel = computed(() => props.label || '')

const timeString = computed(() => {
  const date = now.value
  if (props.format24h !== false) {
    return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
})

const dateString = computed(() => {
  return now.value.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric'
  })
})

// Track acquisition start time
const acquisitionStartTime = ref<number | null>(null)

// Watch for acquisition state changes
const isAcquiring = computed(() => store.isAcquiring)

// Update start time when acquisition starts
const checkAcquisition = () => {
  if (isAcquiring.value && !acquisitionStartTime.value) {
    acquisitionStartTime.value = Date.now()
  } else if (!isAcquiring.value) {
    acquisitionStartTime.value = null
  }
}

// Check on each tick
const elapsedTime = computed(() => {
  checkAcquisition()
  if (!acquisitionStartTime.value || !isAcquiring.value) return null

  const elapsed = Math.floor((now.value.getTime() - acquisitionStartTime.value) / 1000)
  const hours = Math.floor(elapsed / 3600)
  const minutes = Math.floor((elapsed % 3600) / 60)
  const seconds = elapsed % 60

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
  }
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
})
</script>

<template>
  <div class="clock-widget">
    <div v-if="displayLabel" class="label">{{ displayLabel }}</div>

    <div class="time">{{ timeString }}</div>

    <div v-if="showDate !== false" class="date">{{ dateString }}</div>

    <div v-if="showElapsed && isAcquiring && elapsedTime" class="elapsed">
      <span class="elapsed-label">RUN</span>
      <span class="elapsed-time">{{ elapsedTime }}</span>
    </div>
  </div>
</template>

<style scoped>
.clock-widget {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.label {
  font-size: 0.65rem;
  color: #888;
  text-transform: uppercase;
  margin-bottom: 2px;
}

.time {
  font-size: 1.4rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
  letter-spacing: 1px;
}

.date {
  font-size: 0.7rem;
  color: #888;
  margin-top: 2px;
}

.elapsed {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 3px 8px;
  background: rgba(59, 130, 246, 0.2);
  border-radius: 3px;
}

.elapsed-label {
  font-size: 0.55rem;
  font-weight: 700;
  color: #3b82f6;
  letter-spacing: 0.5px;
}

.elapsed-time {
  font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
  color: #60a5fa;
}
</style>
