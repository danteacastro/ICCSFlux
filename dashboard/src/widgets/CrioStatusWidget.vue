<script setup lang="ts">
import { computed } from 'vue'
import { useCrio } from '../composables/useCrio'

const crio = useCrio()

// State classes
const stateClass = computed(() => {
  switch (crio.safetyState.value) {
    case 'emergency': return 'emergency'
    case 'tripped': return 'tripped'
    case 'warning': return 'warning'
    case 'normal': return 'normal'
    default: return 'unknown'
  }
})

const stateLabel = computed(() => {
  switch (crio.safetyState.value) {
    case 'emergency': return 'EMERGENCY'
    case 'tripped': return 'TRIPPED'
    case 'warning': return 'WARNING'
    case 'normal': return 'NORMAL'
    default: return 'OFFLINE'
  }
})

const inputCount = computed(() => Object.keys(crio.inputStates.value).length)
const outputCount = computed(() => Object.keys(crio.outputStates.value).length)
const trippedCount = computed(() => crio.trippedInputs.value.length)

function handleReset() {
  if (confirm('Reset cRIO safety system?')) {
    crio.resetSafety()
  }
}
</script>

<template>
  <div class="crio-status-widget">
    <!-- Header with connection status -->
    <div class="header">
      <div class="title">
        <span class="icon">&#x26A1;</span>
        <span>cRIO</span>
      </div>
      <div class="connection" :class="{ online: crio.isOnline.value }">
        <span class="dot"></span>
        <span class="label">{{ crio.isOnline.value ? 'Online' : 'Offline' }}</span>
      </div>
    </div>

    <!-- Safety State Banner -->
    <div class="state-banner" :class="stateClass">
      <span class="state-icon">
        <template v-if="stateClass === 'emergency'">&#x26A0;</template>
        <template v-else-if="stateClass === 'tripped'">&#x26D4;</template>
        <template v-else-if="stateClass === 'warning'">&#x26A0;</template>
        <template v-else-if="stateClass === 'normal'">&#x2713;</template>
        <template v-else>?</template>
      </span>
      <span class="state-label">{{ stateLabel }}</span>
    </div>

    <!-- I/O Summary -->
    <div class="io-summary" v-if="crio.isOnline.value">
      <div class="io-item">
        <span class="io-value">{{ inputCount }}</span>
        <span class="io-label">DI</span>
      </div>
      <div class="io-item">
        <span class="io-value">{{ outputCount }}</span>
        <span class="io-label">DO</span>
      </div>
      <div class="io-item" :class="{ alert: trippedCount > 0 }">
        <span class="io-value">{{ trippedCount }}</span>
        <span class="io-label">TRIP</span>
      </div>
    </div>

    <!-- Tripped Inputs List -->
    <div class="tripped-list" v-if="trippedCount > 0">
      <div class="tripped-header">Tripped Inputs:</div>
      <div
        v-for="input in crio.trippedInputs.value"
        :key="input"
        class="tripped-item"
      >
        {{ input }}
      </div>
    </div>

    <!-- Reset Button -->
    <button
      v-if="crio.requiresReset.value"
      class="reset-btn"
      @click="handleReset"
    >
      RESET SAFETY
    </button>

    <!-- Uptime -->
    <div class="footer" v-if="crio.isOnline.value">
      <span class="uptime">Up: {{ crio.uptime.value }}</span>
      <span
        v-if="crio.status.value?.simulation_mode"
        class="sim-badge"
      >SIM</span>
    </div>
  </div>
</template>

<style scoped>
.crio-status-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 8px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: #fff;
  font-size: 0.8rem;
}

.title .icon {
  font-size: 1rem;
}

.connection {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 3px;
  background: #1f1f2e;
}

.connection .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444;
}

.connection.online .dot {
  background: #22c55e;
  box-shadow: 0 0 4px #22c55e;
}

.connection .label {
  font-size: 0.6rem;
  color: #9ca3af;
  text-transform: uppercase;
}

.connection.online .label {
  color: #86efac;
}

/* State Banner */
.state-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 0.75rem;
}

.state-banner.normal {
  background: #14532d;
  color: #86efac;
}

.state-banner.warning {
  background: #78350f;
  color: #fbbf24;
}

.state-banner.tripped {
  background: #7f1d1d;
  color: #fca5a5;
  animation: pulse-tripped 1s infinite;
}

.state-banner.emergency {
  background: #7f1d1d;
  color: #fff;
  animation: pulse-emergency 0.5s infinite;
}

.state-banner.unknown {
  background: #1f1f2e;
  color: #6b7280;
}

.state-icon {
  font-size: 1rem;
}

@keyframes pulse-tripped {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

@keyframes pulse-emergency {
  0%, 100% {
    opacity: 1;
    background: #7f1d1d;
  }
  50% {
    opacity: 0.8;
    background: #991b1b;
  }
}

/* I/O Summary */
.io-summary {
  display: flex;
  justify-content: space-around;
  gap: 8px;
}

.io-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4px 12px;
  background: #0f0f1a;
  border-radius: 4px;
}

.io-item.alert {
  background: #7f1d1d;
}

.io-value {
  font-size: 1rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.io-item.alert .io-value {
  color: #fca5a5;
}

.io-label {
  font-size: 0.55rem;
  color: #6b7280;
  text-transform: uppercase;
}

/* Tripped List */
.tripped-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 80px;
  overflow-y: auto;
}

.tripped-header {
  font-size: 0.6rem;
  color: #fca5a5;
  font-weight: 600;
  text-transform: uppercase;
}

.tripped-item {
  font-size: 0.65rem;
  padding: 2px 6px;
  background: #450a0a;
  color: #fca5a5;
  border-radius: 2px;
  font-family: 'JetBrains Mono', monospace;
}

/* Reset Button */
.reset-btn {
  margin-top: auto;
  padding: 8px;
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-weight: 700;
  font-size: 0.7rem;
  cursor: pointer;
  transition: background 0.2s;
}

.reset-btn:hover {
  background: #b91c1c;
}

.reset-btn:active {
  background: #991b1b;
}

/* Footer */
.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 4px;
  border-top: 1px solid #2a2a4a;
  font-size: 0.6rem;
  color: #6b7280;
}

.uptime {
  font-family: 'JetBrains Mono', monospace;
}

.sim-badge {
  padding: 1px 4px;
  background: #7c3aed;
  color: #fff;
  border-radius: 2px;
  font-weight: 700;
  font-size: 0.5rem;
}
</style>
