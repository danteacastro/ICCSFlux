<script setup lang="ts">
import type { NodeConnectionState } from '../types'
import { formatRelativeTime, formatTimestamp } from '../utils/formatters'

const props = defineProps<{
  connection: NodeConnectionState
  lastMessageTime: number
}>()

const emit = defineEmits<{ reconnect: [] }>()
</script>

<template>
  <section class="section">
    <h3 class="section-title">Connection</h3>
    <div class="grid">
      <div class="field">
        <span class="label">MQTT</span>
        <span class="value" :class="connection.connected ? 'ok' : 'err'">
          {{ connection.connected ? 'Connected' : (connection.connecting ? 'Connecting...' : 'Disconnected') }}
        </span>
      </div>
      <div class="field">
        <span class="label">Last Message</span>
        <span class="value">{{ lastMessageTime > 0 ? formatRelativeTime(lastMessageTime) : 'Never' }}</span>
      </div>
      <div v-if="connection.lastConnectTime" class="field">
        <span class="label">Connected At</span>
        <span class="value">{{ formatTimestamp(new Date(connection.lastConnectTime).toISOString()) }}</span>
      </div>
      <div v-if="connection.reconnectAttempts > 0" class="field">
        <span class="label">Reconnect Attempts</span>
        <span class="value mono warn">{{ connection.reconnectAttempts }}</span>
      </div>
      <div v-if="connection.error" class="field full">
        <span class="label">Error</span>
        <span class="value err">{{ connection.error }}</span>
      </div>
    </div>

    <button class="reconnect-btn" @click="emit('reconnect')">
      Reconnect
    </button>
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

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.625rem;
  margin-bottom: 0.75rem;
}

.field { display: flex; flex-direction: column; gap: 0.125rem; }
.field.full { grid-column: 1 / -1; }
.label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.value { font-size: 0.875rem; color: var(--text-primary); }
.value.ok { color: var(--color-success); }
.value.warn { color: var(--color-warning); }
.value.err { color: var(--color-error); font-size: 0.8rem; word-break: break-all; }

.reconnect-btn {
  padding: 0.375rem 0.75rem;
  background: var(--btn-bg);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.8rem;
  transition: all 0.15s;
}

.reconnect-btn:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}
</style>
