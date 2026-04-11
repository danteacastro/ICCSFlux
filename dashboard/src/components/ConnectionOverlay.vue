<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'

// Demo mode: gated behind build-time flag only (NIST 800-171 AC.L2-3.1.22)
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'

const props = defineProps<{
  connected: boolean
  reconnectAttempts: number
  dataIsStale: boolean
  lastHeartbeatTime: number
  isAcquiring: boolean
}>()

const emit = defineEmits<{
  retryNow: []
}>()

// Reconnect countdown
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000
const GRACE_PERIOD_MS = 4000

const nextRetryDelay = computed(() => {
  if (props.connected) return 0
  return Math.min(RECONNECT_BASE_DELAY_MS * Math.pow(2, props.reconnectAttempts), RECONNECT_MAX_DELAY_MS)
})

const countdownSeconds = ref(0)
let countdownInterval: ReturnType<typeof setInterval> | null = null

watch(() => props.reconnectAttempts, () => {
  if (!props.connected) {
    countdownSeconds.value = Math.ceil(nextRetryDelay.value / 1000)
    if (countdownInterval) clearInterval(countdownInterval)
    countdownInterval = setInterval(() => {
      if (countdownSeconds.value > 0) countdownSeconds.value--
    }, 1000)
  }
}, { immediate: true })

watch(() => props.connected, (isConnected) => {
  if (isConnected && countdownInterval) {
    clearInterval(countdownInterval)
    countdownInterval = null
    countdownSeconds.value = 0
  }
})

const inGracePeriod = ref(false)
let graceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.connected, (isConnected, wasConnected) => {
  if (!isConnected && wasConnected) {
    inGracePeriod.value = true
    if (graceTimer) clearTimeout(graceTimer)
    graceTimer = setTimeout(() => { inGracePeriod.value = false; graceTimer = null }, GRACE_PERIOD_MS)
  }
  if (isConnected) {
    inGracePeriod.value = false
    if (graceTimer) { clearTimeout(graceTimer); graceTimer = null }
  }
})

function onVisibilityChange() {
  if (document.visibilityState === 'visible' && !props.connected) {
    inGracePeriod.value = true
    if (graceTimer) clearTimeout(graceTimer)
    graceTimer = setTimeout(() => { inGracePeriod.value = false; graceTimer = null }, GRACE_PERIOD_MS)
  }
}

onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
onUnmounted(() => {
  if (countdownInterval) clearInterval(countdownInterval)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

const showOverlay = computed(() => {
  if (DEMO_MODE) return false
  if (inGracePeriod.value) return false
  return !props.connected || (props.isAcquiring && props.dataIsStale && props.lastHeartbeatTime > 0)
})

const overlayMessage = computed(() => !props.connected ? 'Connection Lost' : 'Service Not Responding')

const overlaySubMessage = computed(() => {
  if (!props.connected) {
    if (props.reconnectAttempts === 0) return 'Connecting to MQTT broker...'
    return `Reconnecting... (attempt ${props.reconnectAttempts})`
  }
  const staleFor = Math.round((Date.now() - props.lastHeartbeatTime) / 1000)
  return `No heartbeat received for ${staleFor} seconds`
})

const showRetryButton = computed(() => !props.connected && props.reconnectAttempts >= 3)
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

          <button v-if="showRetryButton" class="retry-button" @click="emit('retryNow')">
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
  top: 0; left: 0; right: 0; bottom: 0;
  background: var(--bg-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.overlay-content {
  text-align: center;
  color: var(--text-primary);
  max-width: 400px;
  padding: 2rem;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid var(--border-light);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1.5rem;
}

@keyframes spin { to { transform: rotate(360deg); } }

h2 {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
  color: var(--color-error-light);
}

.sub-message {
  color: var(--text-secondary);
  margin: 0 0 1rem;
  font-size: 0.95rem;
}

.countdown {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.hint {
  color: var(--text-disabled);
  font-size: 0.8rem;
  margin-top: 1rem;
}

.retry-button {
  background: var(--color-accent);
  color: var(--text-primary);
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 6px;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 1rem;
}

.retry-button:hover { background: var(--color-accent-dark); }

.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
