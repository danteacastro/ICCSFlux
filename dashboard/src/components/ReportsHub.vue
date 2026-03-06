<script setup lang="ts">
import { ref } from 'vue'
import LogViewerTab from './LogViewerTab.vue'
import OperationalReportTab from './OperationalReportTab.vue'
import NotebookTab from './NotebookTab.vue'

const activeSubTab = ref<'logs' | 'reports' | 'notes'>('logs')
</script>

<template>
  <div class="reports-hub">
    <div class="sub-tab-bar">
      <button
        class="sub-tab-btn"
        :class="{ active: activeSubTab === 'logs' }"
        @click="activeSubTab = 'logs'"
      >Logs</button>
      <button
        class="sub-tab-btn"
        :class="{ active: activeSubTab === 'reports' }"
        @click="activeSubTab = 'reports'"
      >Reports</button>
      <button
        class="sub-tab-btn"
        :class="{ active: activeSubTab === 'notes' }"
        @click="activeSubTab = 'notes'"
      >Notes</button>
    </div>

    <div class="sub-tab-content">
      <LogViewerTab v-if="activeSubTab === 'logs'" />
      <OperationalReportTab v-if="activeSubTab === 'reports'" />
      <NotebookTab v-if="activeSubTab === 'notes'" />
    </div>
  </div>
</template>

<style scoped>
.reports-hub {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.sub-tab-bar {
  display: flex;
  gap: 2px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.sub-tab-btn {
  padding: 5px 14px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}

.sub-tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.sub-tab-btn.active {
  background: var(--accent-primary);
  color: #fff;
}

.sub-tab-content {
  flex: 1;
  overflow: hidden;
}
</style>
