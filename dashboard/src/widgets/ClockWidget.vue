<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetStyle } from '../types'

const props = defineProps<{
  label?: string
  showDate?: boolean
  showElapsed?: boolean
  format24h?: boolean
  style?: WidgetStyle
}>()

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.style?.backgroundColor && props.style.backgroundColor !== 'transparent') {
    s.backgroundColor = props.style.backgroundColor
  }
  return s
})

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
  <div class="clock-widget" :style="containerStyle">
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
  padding: 2px 4px;
  background: var(--bg-widget);
  border-radius: 4px;
  border: 1px solid var(--border-color);
  overflow: hidden;
  container-type: size;
}

.label {
  font-size: clamp(0.5rem, 2cqh, 0.65rem);
  color: var(--text-secondary);
  text-transform: uppercase;
  line-height: 1;
}

.time {
  font-size: clamp(1rem, 45cqh, 4rem);
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #4ade80;
  letter-spacing: 1px;
  line-height: 1;
  white-space: nowrap;
}

.date {
  font-size: clamp(0.5rem, 15cqh, 1rem);
  color: var(--text-secondary);
  line-height: 1;
}

.elapsed {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.2);
  border-radius: 3px;
}

.elapsed-label {
  font-size: clamp(0.45rem, 8cqh, 0.55rem);
  font-weight: 700;
  color: #3b82f6;
  letter-spacing: 0.5px;
  line-height: 1;
}

.elapsed-time {
  font-size: clamp(0.55rem, 10cqh, 0.75rem);
  font-family: 'JetBrains Mono', monospace;
  color: #60a5fa;
  line-height: 1;
}
</style>
