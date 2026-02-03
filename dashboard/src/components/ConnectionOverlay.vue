<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  connected: boolean
  reconnectAttempts: number
  dataIsStale: boolean
  lastHeartbeatTime: number
}>()

const emit = defineEmits<{
  retryNow: []
}>()

// Calculate next retry delay based on exponential backoff
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000
const GRACE_PERIOD_MS = 4000 // Suppress overlay briefly to allow silent reconnect

const nextRetryDelay = computed(() => {
  if (props.connected) return 0
  return Math.min(
    RECONNECT_BASE_DELAY_MS * Math.pow(2, props.reconnectAttempts),
    RECONNECT_MAX_DELAY_MS
  )
})

// Countdown timer
const countdownSeconds = ref(0)
let countdownInterval: ReturnType<typeof setInterval> | null = null

watch(() => props.reconnectAttempts, () => {
  if (!props.connected) {
    countdownSeconds.value = Math.ceil(nextRetryDelay.value / 1000)
    if (countdownInterval) clearInterval(countdownInterval)
    countdownInterval = setInterval(() => {
      if (countdownSeconds.value > 0) {
        countdownSeconds.value--
      }
    }, 1000)
  }
}, { immediate: true })

watch(() => props.connected, (isConnected) => {
  if (isConnected && countdownInterval) {
    clearInterval(countdownInterval)
    countdownInterval = null
  }
})

onUnmounted(() => {
  if (countdownInterval) clearInterval(countdownInterval)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

// Grace period: suppress overlay for a few seconds after disconnect
// to give auto-reconnect a chance to succeed silently
const inGracePeriod = ref(false)
let graceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.connected, (isConnected, wasConnected) => {
  if (!isConnected && wasConnected) {
    // Just disconnected — start grace period
    inGracePeriod.value = true
    if (graceTimer) clearTimeout(graceTimer)
    graceTimer = setTimeout(() => {
      inGracePeriod.value = false
      graceTimer = null
    }, GRACE_PERIOD_MS)
  }
  if (isConnected) {
    // Reconnected during grace — clear it
    inGracePeriod.value = false
    if (graceTimer) { clearTimeout(graceTimer); graceTimer = null }
  }
})

// Tab visibility: when returning from background, extend grace period
// since browser throttles WebSocket activity in background tabs
function onVisibilityChange() {
  if (document.visibilityState === 'visible' && !props.connected) {
    inGracePeriod.value = true
    if (graceTimer) clearTimeout(graceTimer)
    graceTimer = setTimeout(() => {
      inGracePeriod.value = false
      graceTimer = null
    }, GRACE_PERIOD_MS)
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
})

// Show overlay when disconnected or data is stale (respecting grace period)
const showOverlay = computed(() => {
  if (inGracePeriod.value) return false
  return !props.connected || (props.dataIsStale && props.lastHeartbeatTime > 0)
})

const overlayMessage = computed(() => {
  if (!props.connected) {
    return 'Connection Lost'
  }
  if (props.dataIsStale) {
    return 'Service Not Responding'
  }
  return ''
})

const overlaySubMessage = computed(() => {
  if (!props.connected) {
    if (props.reconnectAttempts === 0) {
      return 'Connecting to MQTT broker...'
    }
    return `Reconnecting... (attempt ${props.reconnectAttempts})`
  }
  if (props.dataIsStale) {
    const staleFor = Math.round((Date.now() - props.lastHeartbeatTime) / 1000)
    return `No heartbeat received for ${staleFor} seconds`
  }
  return ''
})

const showRetryButton = computed(() => {
  return !props.connected && props.reconnectAttempts >= 3
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showOverlay" class="connection-overlay">
        <div class="overlay-content">
          <div class="spinner"></div>
          <h2>{{ overlayMessage }}</h2>
          <p class="sub-message">{{ overlaySubMessage }}</p>

          <div v-if="!connected && countdownSeconds > 0" class="countdown">
            Next retry in {{ countdownSeconds }}s
          </div>

          <button
            v-if="showRetryButton"
            class="retry-button"
            @click="emit('retryNow')"
          >
            Retry Now
          </button>

          <div class="hint">
            <span v-if="!connected">Check that the DAQ service is running</span>
            <span v-else-if="dataIsStale">The DAQ service may have stopped responding</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.connection-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.overlay-content {
  text-align: center;
  color: white;
  max-width: 400px;
  padding: 2rem;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1.5rem;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

h2 {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
  color: #f87171;
}

.sub-message {
  color: rgba(255, 255, 255, 0.8);
  margin: 0 0 1rem;
  font-size: 0.95rem;
}

.countdown {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.retry-button {
  background: #3b82f6;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 6px;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 1rem;
}

.retry-button:hover {
  background: #2563eb;
}

.hint {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.8rem;
  margin-top: 1rem;
}

/* Fade transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
