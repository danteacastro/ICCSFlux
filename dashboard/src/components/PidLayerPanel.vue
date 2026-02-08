<script setup lang="ts">
/**
 * PidLayerPanel - Floating layer management panel for P&ID editor
 *
 * Shows named layers with show/hide, lock, and opacity controls.
 * Layers filter which P&ID elements are visible and editable.
 */
import { ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const store = useDashboardStore()

const renamingId = ref<string | null>(null)
const renameValue = ref('')

function layers() {
  const infos = store.pidLayer.layerInfos
  if (!infos || infos.length === 0) {
    return [{ id: 'main', name: 'Main', visible: true, locked: false, opacity: 1, order: 0 }]
  }
  return [...infos].sort((a, b) => a.order - b.order)
}

function addLayer() {
  const name = `Layer ${layers().length + 1}`
  store.pidAddLayer(name)
}

function startRename(layerId: string, currentName: string) {
  renamingId.value = layerId
  renameValue.value = currentName
}

function commitRename(layerId: string) {
  if (renameValue.value.trim()) {
    store.pidRenameLayer(layerId, renameValue.value.trim())
  }
  renamingId.value = null
}

function removeLayer(layerId: string) {
  if (layers().length <= 1) return
  if (confirm('Delete this layer? Elements will be moved to Main.')) {
    store.pidRemoveLayer(layerId)
  }
}
</script>

<template>
  <div class="layer-panel">
    <div class="layer-header">
      <span class="layer-title">Layers</span>
      <button class="layer-add-btn" @click="addLayer" title="Add Layer">+</button>
    </div>
    <div class="layer-list">
      <div
        v-for="layer in layers()"
        :key="layer.id"
        class="layer-item"
        :class="{ active: store.pidActiveLayerId === layer.id }"
        @click="store.pidActiveLayerId = layer.id"
      >
        <!-- Visibility toggle -->
        <button
          class="layer-icon-btn"
          :class="{ off: !layer.visible }"
          @click.stop="store.pidToggleLayerVisibility(layer.id)"
          :title="layer.visible ? 'Hide layer' : 'Show layer'"
        >
          <svg v-if="layer.visible" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        </button>

        <!-- Lock toggle -->
        <button
          class="layer-icon-btn"
          :class="{ off: !layer.locked }"
          @click.stop="store.pidToggleLayerLock(layer.id)"
          :title="layer.locked ? 'Unlock layer' : 'Lock layer'"
        >
          <svg v-if="layer.locked" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 9.9-1" />
          </svg>
        </button>

        <!-- Name -->
        <div class="layer-name" @dblclick.stop="startRename(layer.id, layer.name)">
          <input
            v-if="renamingId === layer.id"
            v-model="renameValue"
            class="layer-rename-input"
            @blur="commitRename(layer.id)"
            @keydown.enter="commitRename(layer.id)"
            @keydown.escape="renamingId = null"
            @click.stop
          />
          <span v-else>{{ layer.name }}</span>
        </div>

        <!-- Delete -->
        <button
          v-if="layers().length > 1"
          class="layer-icon-btn delete"
          @click.stop="removeLayer(layer.id)"
          title="Delete layer"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>
    <!-- Move to layer -->
    <div v-if="store.hasPidSelection && layers().length > 1" class="layer-move">
      <select
        class="layer-move-select"
        @change="store.pidMoveToLayer(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''"
      >
        <option value="" disabled selected>Move selection to...</option>
        <option v-for="layer in layers()" :key="layer.id" :value="layer.id">{{ layer.name }}</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.layer-panel {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  min-width: 180px;
  font-size: 12px;
  overflow: hidden;
}

.layer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: #0f0f23;
  border-bottom: 1px solid #2a2a4a;
}

.layer-title {
  color: #94a3b8;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.layer-add-btn {
  background: #10b981;
  color: #fff;
  border: none;
  border-radius: 3px;
  width: 20px;
  height: 20px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.layer-add-btn:hover {
  background: #059669;
}

.layer-list {
  max-height: 200px;
  overflow-y: auto;
}

.layer-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  cursor: pointer;
  border-left: 3px solid transparent;
}

.layer-item:hover {
  background: rgba(96, 165, 250, 0.08);
}

.layer-item.active {
  background: rgba(96, 165, 250, 0.12);
  border-left-color: #60a5fa;
}

.layer-icon-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  border-radius: 2px;
}

.layer-icon-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.layer-icon-btn.off {
  color: #475569;
  opacity: 0.5;
}

.layer-icon-btn.delete {
  color: #ef4444;
  opacity: 0.5;
  margin-left: auto;
}

.layer-icon-btn.delete:hover {
  opacity: 1;
}

.layer-name {
  flex: 1;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.layer-rename-input {
  width: 100%;
  background: #0f0f23;
  color: #e2e8f0;
  border: 1px solid #3b82f6;
  border-radius: 2px;
  padding: 1px 4px;
  font-size: 12px;
  outline: none;
}

.layer-move {
  padding: 4px 6px;
  border-top: 1px solid #2a2a4a;
}

.layer-move-select {
  width: 100%;
  background: #0f0f23;
  color: #94a3b8;
  border: 1px solid #2a2a4a;
  border-radius: 3px;
  padding: 3px 6px;
  font-size: 11px;
  cursor: pointer;
}
</style>
