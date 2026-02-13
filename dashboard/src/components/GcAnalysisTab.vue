<script setup lang="ts">
/**
 * GcAnalysisTab — Container for GC Analysis features.
 *
 * Hosts the method editor, report viewer, and chromatogram display
 * in a tabbed sub-layout. Only shown when GC nodes are present.
 */

import { ref, defineAsyncComponent } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const GcMethodEditor = defineAsyncComponent(() => import('./GcMethodEditor.vue'))
const GcReportView = defineAsyncComponent(() => import('./GcReportView.vue'))

const mqtt = useMqtt('nisystem')

// Sub-tabs within the GC Analysis tab
type GcSubTab = 'methods' | 'reports'
const activeSubTab = ref<GcSubTab>('methods')

// Report data — populated when user clicks "View Report" from method editor or chromatogram widget
const reportChromatogram = ref<any>(null)
const reportResult = ref<any>(null)
const reportMeta = ref<{
  labName?: string
  instrumentName?: string
  operatorName?: string
  methodName?: string
  sampleId?: string
  notes?: string
}>({})

function viewReport(data: { chromatogram: any; result: any; meta?: any }) {
  reportChromatogram.value = data.chromatogram
  reportResult.value = data.result
  if (data.meta) reportMeta.value = data.meta
  activeSubTab.value = 'reports'
}
</script>

<template>
  <div class="gc-analysis-tab">
    <!-- Sub-tab navigation -->
    <div class="gc-subtabs">
      <button
        class="gc-subtab"
        :class="{ active: activeSubTab === 'methods' }"
        @click="activeSubTab = 'methods'"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Methods
      </button>
      <button
        class="gc-subtab"
        :class="{ active: activeSubTab === 'reports' }"
        @click="activeSubTab = 'reports'"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
          <polyline points="14,2 14,8 20,8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10,9 9,9 8,9"/>
        </svg>
        Reports
      </button>
    </div>

    <!-- Sub-tab content -->
    <div class="gc-subtab-content">
      <GcMethodEditor v-if="activeSubTab === 'methods'" @view-report="viewReport" />
      <GcReportView
        v-else-if="activeSubTab === 'reports'"
        :chromatogram="reportChromatogram"
        :result="reportResult"
        v-bind="reportMeta"
      />
    </div>
  </div>
</template>

<style scoped>
.gc-analysis-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.gc-subtabs {
  display: flex;
  gap: 2px;
  padding: 6px 12px 0;
  background: var(--bg-secondary, #0f0f1a);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  flex-shrink: 0;
}

.gc-subtab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 4px 4px 0 0;
  background: transparent;
  color: var(--text-muted, #666680);
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.gc-subtab:hover {
  color: var(--text-secondary, #a0a0b0);
  background: rgba(59, 130, 246, 0.05);
}

.gc-subtab.active {
  color: var(--color-accent, #3b82f6);
  border-bottom-color: var(--color-accent, #3b82f6);
  background: var(--bg-widget, #1a1a2e);
}

.gc-subtab svg {
  opacity: 0.7;
}

.gc-subtab.active svg {
  opacity: 1;
}

.gc-subtab-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

:root.light .gc-subtabs {
  background: #f8fafc;
  border-bottom-color: #e2e8f0;
}

:root.light .gc-subtab {
  color: #94a3b8;
}

:root.light .gc-subtab:hover {
  color: #64748b;
}

:root.light .gc-subtab.active {
  color: #3b82f6;
  background: #ffffff;
}
</style>
