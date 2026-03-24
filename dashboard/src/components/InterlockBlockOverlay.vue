<script setup lang="ts">
import { computed } from 'vue'
import type { InterlockStatus } from '../types'

const props = defineProps<{
  blockedBy: InterlockStatus[]
}>()

const primaryInterlock = computed(() => props.blockedBy[0])

const tooltipText = computed(() => {
  return props.blockedBy.map(il => {
    const reasons = il.failedConditions.map(fc => fc.reason).join(', ')
    return `${il.name}: ${reasons}`
  }).join('\n')
})
</script>

<template>
  <div class="interlock-overlay" :title="tooltipText">
    <div class="overlay-content">
      <svg class="lock-icon" viewBox="0 0 24 24" fill="currentColor">
        <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1s3.1 1.39 3.1 3.1v2z"/>
      </svg>
      <span v-if="primaryInterlock" class="interlock-name">{{ primaryInterlock.name }}</span>
    </div>
  </div>
</template>

<style scoped>
.interlock-overlay {
  position: absolute;
  inset: 0;
  background: var(--color-error-bg);
  border-radius: inherit;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 5;
}

.overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  color: var(--color-error);
}

.lock-icon {
  width: 16px;
  height: 16px;
  opacity: 0.9;
}

.interlock-name {
  font-size: 0.55rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 90%;
  text-align: center;
}
</style>
