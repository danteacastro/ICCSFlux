<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const store = useDashboardStore()

const isRecording = computed(() => store.status?.recording ?? false)

const recordingDuration = computed(() => {
  if (!store.status?.recording_duration) return '00:00:00'
  return store.status.recording_duration
})

const recordingFilename = computed(() => {
  if (!store.status?.recording_filename) return '--'
  // Truncate long filenames
  const name = store.status.recording_filename
  if (name.length > 25) {
    return '...' + name.slice(-22)
  }
  return name
})

const recordingSamples = computed(() => {
  if (!store.status?.recording_samples) return '--'
  const samples = store.status.recording_samples
  if (samples >= 1000000) {
    return (samples / 1000000).toFixed(1) + 'M'
  }
  if (samples >= 1000) {
    return (samples / 1000).toFixed(1) + 'K'
  }
  return samples.toString()
})

const recordingSize = computed(() => {
  if (!store.status?.recording_bytes) return '--'
  const bytes = store.status.recording_bytes
  if (bytes >= 1024 * 1024 * 1024) {
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
  }
  if (bytes >= 1024 * 1024) {
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }
  if (bytes >= 1024) {
    return (bytes / 1024).toFixed(0) + ' KB'
  }
  return bytes + ' B'
})

const recordingMode = computed(() => {
  return store.status?.recording_mode || 'manual'
})
</script>

<template>
  <div class="recording-status-widget" :class="{ recording: isRecording }">
    <!-- Recording indicator -->
    <div class="recording-header">
      <div class="indicator" :class="{ active: isRecording }">
        <span class="dot"></span>
        <span class="text">{{ isRecording ? 'REC' : 'IDLE' }}</span>
      </div>
      <span v-if="isRecording" class="duration">{{ recordingDuration }}</span>
    </div>

    <!-- Recording details (when recording) -->
    <template v-if="isRecording">
      <div class="filename" :title="store.status?.recording_filename">
        {{ recordingFilename }}
      </div>

      <div class="stats">
        <div class="stat">
          <span class="value">{{ recordingSamples }}</span>
          <span class="label">samples</span>
        </div>
        <div class="stat">
          <span class="value">{{ recordingSize }}</span>
          <span class="label">size</span>
        </div>
        <div class="stat mode">
          <span class="value">{{ recordingMode }}</span>
        </div>
      </div>
    </template>

    <!-- Idle state -->
    <template v-else>
      <div class="idle-message">
        Not recording
      </div>
    </template>
  </div>
</template>

<style scoped>
.recording-status-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
  gap: 6px;
}

.recording-status-widget.recording {
  border-color: #dc2626;
}

.recording-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.indicator {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4b5563;
}

.indicator.active .dot {
  background: #ef4444;
  animation: pulse-dot 1s infinite;
}

.indicator .text {
  font-size: 0.7rem;
  font-weight: 700;
  color: #6b7280;
  text-transform: uppercase;
}

.indicator.active .text {
  color: #ef4444;
}

.duration {
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.filename {
  font-size: 0.65rem;
  color: #9ca3af;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 4px 6px;
  background: #0f0f1a;
  border-radius: 3px;
}

.stats {
  display: flex;
  gap: 8px;
  justify-content: space-around;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

.stat .value {
  font-size: 0.8rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  color: #fff;
}

.stat .label {
  font-size: 0.55rem;
  color: #6b7280;
  text-transform: uppercase;
}

.stat.mode .value {
  font-size: 0.6rem;
  padding: 2px 6px;
  background: #374151;
  border-radius: 3px;
  text-transform: uppercase;
}

.idle-message {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4b5563;
  font-size: 0.75rem;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
