<script setup lang="ts">
import { useScripts } from '../composables/useScripts'

const scripts = useScripts()

function getIcon(type: string): string {
  switch (type) {
    case 'error': return '!'
    case 'warning': return '!'
    case 'success': return '✓'
    default: return 'i'
  }
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <Teleport to="body">
    <div class="notification-container">
      <TransitionGroup name="notification">
        <div
          v-for="notification in scripts.notifications.value"
          :key="notification.id"
          class="notification"
          :class="[notification.type, { acknowledged: notification.acknowledged }]"
        >
          <div class="notification-icon" :class="notification.type">
            {{ getIcon(notification.type) }}
          </div>
          <div class="notification-content">
            <div class="notification-header">
              <span class="notification-title">{{ notification.title }}</span>
              <span class="notification-time">{{ formatTime(notification.timestamp) }}</span>
            </div>
            <p class="notification-message">{{ notification.message }}</p>
          </div>
          <div class="notification-actions">
            <button
              v-if="(notification.type === 'warning' || notification.type === 'error') && !notification.acknowledged"
              class="ack-btn"
              @click="scripts.acknowledgeNotification(notification.id)"
              title="Acknowledge"
            >
              ACK
            </button>
            <button
              class="dismiss-btn"
              @click="scripts.dismissNotification(notification.id)"
              title="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      </TransitionGroup>

      <!-- Clear all button when there are multiple notifications -->
      <button
        v-if="scripts.notifications.value.length > 2"
        class="clear-all-btn"
        @click="scripts.clearAllNotifications()"
      >
        Clear All ({{ scripts.notifications.value.length }})
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.notification-container {
  position: fixed;
  top: 60px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
  pointer-events: none;
}

.notification-container > * {
  pointer-events: auto;
}

.notification {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  min-width: 320px;
  max-width: 420px;
}

.notification.info {
  border-left: 4px solid #3b82f6;
}

.notification.success {
  border-left: 4px solid #22c55e;
}

.notification.warning {
  border-left: 4px solid #f59e0b;
  background: #1a1a2e;
}

.notification.error {
  border-left: 4px solid #ef4444;
  background: #1f1a1a;
}

.notification.acknowledged {
  opacity: 0.7;
}

.notification-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  flex-shrink: 0;
}

.notification-icon.info {
  background: #1e3a5f;
  color: #60a5fa;
}

.notification-icon.success {
  background: #14532d;
  color: #22c55e;
}

.notification-icon.warning {
  background: #78350f;
  color: #fbbf24;
}

.notification-icon.error {
  background: #7f1d1d;
  color: #ef4444;
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.notification-title {
  font-weight: 600;
  font-size: 0.9rem;
  color: #fff;
}

.notification-time {
  font-size: 0.7rem;
  color: #666;
  white-space: nowrap;
}

.notification-message {
  margin: 0;
  font-size: 0.8rem;
  color: #999;
  line-height: 1.4;
  word-wrap: break-word;
}

.notification-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-left: auto;
}

.dismiss-btn {
  width: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  border: none;
  color: #666;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s;
}

.dismiss-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.ack-btn {
  padding: 2px 6px;
  background: #374151;
  border: none;
  color: #fff;
  font-size: 0.65rem;
  font-weight: 600;
  cursor: pointer;
  border-radius: 3px;
  transition: all 0.2s;
}

.ack-btn:hover {
  background: #4b5563;
}

.clear-all-btn {
  align-self: flex-end;
  padding: 6px 12px;
  background: #374151;
  border: none;
  color: #fff;
  font-size: 0.75rem;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s;
}

.clear-all-btn:hover {
  background: #4b5563;
}

/* Transitions */
.notification-enter-active {
  animation: slideIn 0.3s ease-out;
}

.notification-leave-active {
  animation: slideOut 0.2s ease-in;
}

.notification-move {
  transition: transform 0.3s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(100%);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideOut {
  from {
    opacity: 1;
    transform: translateX(0);
  }
  to {
    opacity: 0;
    transform: translateX(100%);
  }
}
</style>
