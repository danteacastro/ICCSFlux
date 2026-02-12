<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label?: string
  orientation?: 'horizontal' | 'vertical'
  style?: {
    lineColor?: string
    lineStyle?: 'solid' | 'dashed' | 'dotted'
  }
}>()

const isVertical = computed(() => props.orientation === 'vertical')
const lineColor = computed(() => props.style?.lineColor || '#3b82f6')
const lineStyle = computed(() => props.style?.lineStyle || 'solid')
</script>

<template>
  <div class="divider-widget" :class="{ vertical: isVertical }">
    <div
      v-if="!isVertical"
      class="divider-line horizontal"
      :style="{ borderTopColor: lineColor, borderTopStyle: lineStyle }"
    >
      <span v-if="label" class="divider-label" :style="{ color: lineColor }">
        {{ label }}
      </span>
    </div>
    <div
      v-else
      class="divider-line vertical"
      :style="{ borderLeftColor: lineColor, borderLeftStyle: lineStyle }"
    />
  </div>
</template>

<style scoped>
.divider-widget {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 4px;
}

.divider-line.horizontal {
  flex: 1;
  display: flex;
  align-items: center;
  border-top-width: 2px;
  position: relative;
}

.divider-line.vertical {
  height: 100%;
  border-left-width: 2px;
}

.divider-label {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-widget);
  padding: 0 8px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  white-space: nowrap;
}

.vertical .divider-widget {
  flex-direction: column;
}
</style>
