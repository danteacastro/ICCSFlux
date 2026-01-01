<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  text?: string
  label?: string  // Fallback to label if text not set
  fontSize?: 'small' | 'medium' | 'large' | 'xlarge'
  textAlign?: 'left' | 'center' | 'right'
  textColor?: string
}>()

const displayText = computed(() => props.text || props.label || 'Text Label')

const fontSizeClass = computed(() => props.fontSize || 'medium')

const textStyle = computed(() => ({
  color: props.textColor || '#ffffff',
  textAlign: props.textAlign || 'center'
}))
</script>

<template>
  <div class="text-label-widget" :class="fontSizeClass" :style="textStyle">
    {{ displayText }}
  </div>
</template>

<style scoped>
.text-label-widget {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  width: 100%;
  padding: 4px 8px;
  font-weight: 500;
  line-height: 1.2;
  word-break: break-word;
  overflow: hidden;
}

/* Text alignment */
.text-label-widget[style*="text-align: left"] {
  justify-content: flex-start;
}

.text-label-widget[style*="text-align: right"] {
  justify-content: flex-end;
}

/* Font sizes */
.small {
  font-size: 0.75rem;
}

.medium {
  font-size: 1rem;
}

.large {
  font-size: 1.5rem;
}

.xlarge {
  font-size: 2rem;
  font-weight: 600;
}
</style>
