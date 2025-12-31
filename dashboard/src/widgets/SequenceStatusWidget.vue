<script setup lang="ts">
import { computed } from 'vue'
import { useScripts } from '../composables/useScripts'

const props = defineProps<{
  showControls?: boolean
}>()

const scripts = useScripts()

const runningSequence = computed(() => scripts.runningSequence.value)
const sequences = computed(() => scripts.sequences.value)

const isRunning = computed(() => !!runningSequence.value)
const isPaused = computed(() => runningSequence.value?.state === 'paused')

// Calculate progress
const progress = computed(() => {
  if (!runningSequence.value) return 0
  const total = runningSequence.value.steps.length
  if (total === 0) return 0
  return Math.round((runningSequence.value.currentStepIndex / total) * 100)
})

// Current step info
const currentStep = computed(() => {
  if (!runningSequence.value) return null
  const idx = runningSequence.value.currentStepIndex
  return runningSequence.value.steps[idx] || null
})

const currentStepLabel = computed(() => {
  if (!currentStep.value) return 'Idle'
  const step = currentStep.value
  if (step.label) return step.label
  return `Step ${(runningSequence.value?.currentStepIndex ?? 0) + 1}: ${step.type}`
})

// Elapsed time
const elapsedTime = computed(() => {
  if (!runningSequence.value?.startTime) return '--'
  const elapsed = Math.floor((Date.now() - runningSequence.value.startTime) / 1000)
  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
})

// Available sequences for quick start
const availableSequences = computed(() =>
  sequences.value.filter(s => s.enabled && s.state !== 'running')
)

function pauseSequence() {
  if (runningSequence.value) {
    scripts.pauseSequence(runningSequence.value.id)
  }
}

function resumeSequence() {
  if (runningSequence.value) {
    scripts.resumeSequence(runningSequence.value.id)
  }
}

function abortSequence() {
  if (runningSequence.value) {
    scripts.abortSequence(runningSequence.value.id)
  }
}

function startSequence(id: string) {
  scripts.startSequence(id)
}
</script>

<template>
  <div class="sequence-status-widget" :class="{ running: isRunning, paused: isPaused }">
    <div class="header">
      <span class="title">Sequence</span>
      <span v-if="isRunning" class="status-badge" :class="{ paused: isPaused }">
        {{ isPaused ? 'PAUSED' : 'RUNNING' }}
      </span>
    </div>

    <!-- Running sequence display -->
    <template v-if="isRunning">
      <div class="sequence-name">{{ runningSequence?.name }}</div>

      <div class="progress-section">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }" />
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <div class="step-info">
        <span class="step-label">{{ currentStepLabel }}</span>
        <span class="elapsed">{{ elapsedTime }}</span>
      </div>

      <div v-if="showControls !== false" class="controls">
        <button
          v-if="!isPaused"
          class="control-btn pause"
          @click="pauseSequence"
          title="Pause"
        >
          ⏸
        </button>
        <button
          v-else
          class="control-btn resume"
          @click="resumeSequence"
          title="Resume"
        >
          ▶
        </button>
        <button
          class="control-btn abort"
          @click="abortSequence"
          title="Abort"
        >
          ⏹
        </button>
      </div>
    </template>

    <!-- Idle state -->
    <template v-else>
      <div class="idle-state">
        <span class="idle-text">No sequence running</span>

        <div v-if="availableSequences.length > 0 && showControls !== false" class="quick-start">
          <select class="sequence-select" @change="(e) => { if ((e.target as HTMLSelectElement).value) startSequence((e.target as HTMLSelectElement).value); (e.target as HTMLSelectElement).value = '' }">
            <option value="">Quick Start...</option>
            <option v-for="seq in availableSequences" :key="seq.id" :value="seq.id">
              {{ seq.name }}
            </option>
          </select>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sequence-status-widget {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  background: var(--widget-bg, #1a1a2e);
  border-radius: 4px;
  border: 1px solid var(--border-color, #2a2a4a);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
}

.status-badge {
  font-size: 0.55rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  background: #22c55e;
  color: #fff;
  animation: pulse-running 2s infinite;
}

.status-badge.paused {
  background: #f59e0b;
  animation: none;
}

@keyframes pulse-running {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.sequence-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 6px;
}

.progress-section {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: #0f0f1a;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 3px;
  transition: width 0.3s ease-out;
}

.progress-text {
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  color: #888;
  min-width: 30px;
  text-align: right;
}

.step-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.step-label {
  font-size: 0.7rem;
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70%;
}

.elapsed {
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  color: #60a5fa;
}

.controls {
  display: flex;
  gap: 6px;
  justify-content: center;
}

.control-btn {
  width: 32px;
  height: 24px;
  border: none;
  border-radius: 4px;
  font-size: 0.8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.control-btn.pause {
  background: #f59e0b;
  color: #fff;
}

.control-btn.resume {
  background: #22c55e;
  color: #fff;
}

.control-btn.abort {
  background: #ef4444;
  color: #fff;
}

.control-btn:hover {
  filter: brightness(1.1);
}

.idle-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.idle-text {
  font-size: 0.75rem;
  color: #666;
}

.quick-start {
  width: 100%;
}

.sequence-select {
  width: 100%;
  padding: 6px 8px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #ccc;
  font-size: 0.7rem;
  cursor: pointer;
}

.sequence-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.running {
  border-color: #3b82f640;
}

.paused {
  border-color: #f59e0b40;
}
</style>
