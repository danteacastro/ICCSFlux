<script setup lang="ts">
/**
 * PidContextMenu - Right-click context menu for P&ID elements
 *
 * Shows different menus for:
 * - Symbol: Configure, Cut/Copy/Duplicate/Delete, Bring to Front/Send to Back, Rotate
 * - Pipe: Delete, Toggle Dashed, Toggle Animation
 * - Canvas: Paste, Select All, Toggle Grid, Reset Zoom
 */

import { ref, onMounted, onUnmounted, nextTick } from 'vue'

export type MenuTarget =
  | { type: 'symbol'; id: string }
  | { type: 'pipe'; id: string }
  | { type: 'canvas' }

const props = defineProps<{
  x: number
  y: number
  target: MenuTarget
  hasStyleClipboard?: boolean
}>()

const emit = defineEmits<{
  (e: 'action', action: string): void
  (e: 'close'): void
}>()

const menuRef = ref<HTMLElement | null>(null)

function handleAction(action: string) {
  emit('action', action)
  emit('close')
}

function handleClickOutside(event: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(event.target as Node)) {
    emit('close')
  }
}

onMounted(() => {
  setTimeout(() => {
    window.addEventListener('mousedown', handleClickOutside)
  }, 0)
  // Adjust position if menu overflows viewport
  nextTick(() => {
    if (!menuRef.value) return
    const rect = menuRef.value.getBoundingClientRect()
    const el = menuRef.value
    if (rect.right > window.innerWidth) {
      el.style.left = `${Math.max(0, window.innerWidth - rect.width - 4)}px`
    }
    if (rect.bottom > window.innerHeight) {
      el.style.top = `${Math.max(0, window.innerHeight - rect.height - 4)}px`
    }
  })
})

onUnmounted(() => {
  window.removeEventListener('mousedown', handleClickOutside)
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="menuRef"
      class="pid-context-menu"
      :style="{ left: `${x}px`, top: `${y}px` }"
    >
      <!-- Symbol Menu -->
      <template v-if="target.type === 'symbol'">
        <button class="menu-item" @click="handleAction('configure')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          Configure...
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('cut')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" />
            <line x1="20" y1="4" x2="8.12" y2="15.88" /><line x1="14.47" y1="14.48" x2="20" y2="20" />
            <line x1="8.12" y1="8.12" x2="12" y2="12" />
          </svg>
          Cut
          <span class="shortcut">Ctrl+X</span>
        </button>
        <button class="menu-item" @click="handleAction('copy')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          Copy
          <span class="shortcut">Ctrl+C</span>
        </button>
        <button class="menu-item" @click="handleAction('duplicate')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="8" y="8" width="12" height="12" rx="2" />
            <path d="M4 16V4h12" />
          </svg>
          Duplicate
          <span class="shortcut">Ctrl+D</span>
        </button>
        <button class="menu-item danger" @click="handleAction('delete')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
          Delete
          <span class="shortcut">Del</span>
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('bringToFront')">
          Bring to Front
        </button>
        <button class="menu-item" @click="handleAction('sendToBack')">
          Send to Back
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('rotateCW')">
          Rotate 90\u00B0 CW
        </button>
        <button class="menu-item" @click="handleAction('rotateCCW')">
          Rotate 90\u00B0 CCW
        </button>
      </template>

      <!-- Pipe Menu -->
      <template v-else-if="target.type === 'pipe'">
        <button class="menu-item" @click="handleAction('toggleDashed')">
          Toggle Dashed
        </button>
        <button class="menu-item" @click="handleAction('toggleAnimation')">
          Toggle Flow Animation
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('reversePipe')">
          Reverse Direction
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('copyStyle')">
          Copy Style
        </button>
        <button class="menu-item" :class="{ disabled: !hasStyleClipboard }" :disabled="!hasStyleClipboard" @click="handleAction('pasteStyle')">
          Paste Style
        </button>
        <div class="menu-divider" />
        <button class="menu-item danger" @click="handleAction('delete')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
          Delete Pipe
          <span class="shortcut">Del</span>
        </button>
      </template>

      <!-- Canvas Menu -->
      <template v-else>
        <button class="menu-item" @click="handleAction('paste')">
          Paste
          <span class="shortcut">Ctrl+V</span>
        </button>
        <button class="menu-item" @click="handleAction('selectAll')">
          Select All
          <span class="shortcut">Ctrl+A</span>
        </button>
        <div class="menu-divider" />
        <button class="menu-item" @click="handleAction('toggleGrid')">
          Toggle Grid
          <span class="shortcut">G</span>
        </button>
        <button class="menu-item" @click="handleAction('resetZoom')">
          Reset Zoom
          <span class="shortcut">Ctrl+0</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.pid-context-menu {
  position: fixed;
  min-width: 180px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 4px 0;
  z-index: 99999;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 12px;
  background: transparent;
  border: none;
  color: #e2e8f0;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}

.menu-item:hover {
  background: #334155;
}

.menu-item.disabled {
  color: #475569;
  cursor: default;
}

.menu-item.disabled:hover {
  background: transparent;
}

.menu-item.danger {
  color: #f87171;
}

.menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.15);
}

.shortcut {
  margin-left: auto;
  font-size: 11px;
  color: #64748b;
}

.menu-divider {
  height: 1px;
  background: #334155;
  margin: 4px 0;
}
</style>
