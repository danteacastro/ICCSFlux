<script setup lang="ts">
/**
 * ImageWidget - Static image/logo display
 *
 * Displays an image from URL with configurable fit mode.
 * Useful for company logos, equipment photos, diagrams.
 */
defineProps<{
  imageUrl?: string
  imageFit?: 'contain' | 'cover' | 'fill' | 'none'
  title?: string
}>()
</script>

<template>
  <div class="image-widget">
    <img
      v-if="imageUrl"
      :src="imageUrl"
      :alt="title || 'Image'"
      :style="{ objectFit: imageFit || 'contain' }"
      class="widget-image"
    />
    <div v-else class="placeholder">
      <span class="placeholder-icon">&#128247;</span>
      <span class="placeholder-text">No image URL set</span>
    </div>
  </div>
</template>

<style scoped>
.image-widget {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.widget-image {
  width: 100%;
  height: 100%;
}
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: #64748b;
  font-size: 12px;
}
.placeholder-icon { font-size: 24px; }
</style>
