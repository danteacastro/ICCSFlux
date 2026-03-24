<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useFleetStore } from './stores/fleet'
import { useFleetMqtt } from './composables/useFleetMqtt'
import { useTheme } from './composables/useTheme'
import HeaderBar from './components/HeaderBar.vue'
import NodeList from './components/NodeList.vue'
import NodeDetail from './components/NodeDetail.vue'
import SettingsView from './components/SettingsView.vue'

const store = useFleetStore()
const mqtt = useFleetMqtt()
const { toggleTheme } = useTheme()

const showSettings = ref(false)

onMounted(() => {
  mqtt.init()
  // Open settings on first launch if no nodes configured
  if (store.nodes.length === 0) showSettings.value = true
})

onUnmounted(() => {
  mqtt.disconnectAll()
})
</script>

<template>
  <div class="app">
    <HeaderBar
      :summary="store.summary"
      @toggle-theme="toggleTheme"
      @open-settings="showSettings = true"
    />

    <div class="main-container">
      <NodeList
        :nodes="store.nodeStatesList"
        :selected-id="store.selectedNodeId"
        @select="store.selectNode($event)"
      />

      <div class="detail-panel">
        <SettingsView
          v-if="showSettings"
          @close="showSettings = false"
        />
        <NodeDetail
          v-else-if="store.selectedNode"
          :node-state="store.selectedNode"
          @reconnect="mqtt.reconnectNode(store.selectedNode!.node.id)"
        />
        <div v-else class="empty-state">
          <div class="empty-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
          </div>
          <h2>ICCSFlux Fleet Monitor</h2>
          <p>Select a node from the list to view its status</p>
          <button v-if="store.nodes.length === 0" class="add-btn" @click="showSettings = true">
            Add Your First Node
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.main-container {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.detail-panel {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-secondary);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 1.5rem;
  opacity: 0.3;
}

.empty-state h2 {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0 0 0.5rem;
}

.empty-state p {
  color: var(--text-secondary);
  margin: 0 0 1.5rem;
}

.add-btn {
  padding: 0.625rem 1.25rem;
  background: var(--color-accent);
  color: #fff;
  border-radius: 6px;
  font-weight: 500;
  font-size: 0.875rem;
  transition: background 0.15s;
}

.add-btn:hover {
  background: var(--color-accent-dark);
}
</style>
