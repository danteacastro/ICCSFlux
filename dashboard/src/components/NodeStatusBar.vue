<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMqtt } from '../composables/useMqtt'
import { useNodeContext } from '../composables/useNodeContext'
import type { NodeInfo } from '../types'

const mqtt = useMqtt()
const nodeContext = useNodeContext()

const nodes = computed(() => Array.from(mqtt.knownNodes.value.values()))

const hoveredNodeId = ref<string | null>(null)
let hoverTimeout: ReturnType<typeof setTimeout> | null = null

function getNodeIcon(node: NodeInfo): string {
  switch (node.nodeType) {
    case 'crio': return 'C'  // Controller
    case 'opto22': return 'O' // Opto22
    case 'gc': return 'G'    // GC
    default: return 'D'       // DAQ
  }
}

function getNodeTypeLabel(node: NodeInfo): string {
  switch (node.nodeType) {
    case 'crio': return 'cRIO Controller'
    case 'opto22': return 'Opto22 EPIC/RIO'
    case 'gc': return 'GC Analysis'
    default: return 'DAQ Service'
  }
}

function getModeDescription(node: NodeInfo): string {
  if (node.nodeType === 'crio') return 'cRIO is PLC — runs safety independently'
  if (node.nodeType === 'opto22') return 'Opto22 is PLC — runs safety independently'
  if (node.nodeType === 'gc') return 'Gas chromatograph analysis node'
  if (node.projectMode === 'crio') return 'PC is HMI — cRIO runs safety'
  if (node.projectMode === 'opto22') return 'PC is HMI — Opto22 runs safety'
  return 'PC is PLC — reads hardware, runs safety'
}

function getTimeSince(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}

function isActive(nodeId: string): boolean {
  return mqtt.activeNodeId.value === nodeId
}

async function toggleNode(nodeId: string) {
  if (mqtt.activeNodeId.value === nodeId) {
    await nodeContext.switchToNode(null) // Deselect = default node
  } else {
    await nodeContext.switchToNode(nodeId)
  }
}

function onMouseEnter(nodeId: string) {
  if (hoverTimeout) clearTimeout(hoverTimeout)
  hoveredNodeId.value = nodeId
}

function onMouseLeave() {
  hoverTimeout = setTimeout(() => {
    hoveredNodeId.value = null
  }, 200)
}
</script>

<template>
  <!-- Only show when multiple nodes are detected — single-node operation looks unchanged -->
  <div v-if="nodes.length > 1" class="node-status-bar">
    <div
      v-for="node in nodes"
      :key="node.nodeId"
      class="node-pill"
      :class="{
        active: isActive(node.nodeId),
        online: node.status === 'online',
        offline: node.status === 'offline',
        switching: nodeContext.isSwitching.value,
      }"
      @click="toggleNode(node.nodeId)"
      @mouseenter="onMouseEnter(node.nodeId)"
      @mouseleave="onMouseLeave"
    >
      <span class="node-icon">{{ getNodeIcon(node) }}</span>
      <span class="node-name">{{ node.nodeName || node.nodeId }}</span>
      <span class="status-dot" :class="node.status"></span>

      <!-- Hover dropdown -->
      <Transition name="dropdown">
        <div
          v-if="hoveredNodeId === node.nodeId"
          class="node-dropdown"
          @mouseenter="onMouseEnter(node.nodeId)"
          @mouseleave="onMouseLeave"
        >
          <div class="dropdown-header">
            <span class="dropdown-name">{{ node.nodeName || node.nodeId }}</span>
            <span class="dropdown-type">{{ getNodeTypeLabel(node) }}</span>
          </div>
          <div class="dropdown-body">
            <div class="dropdown-row">
              <span class="row-label">ID</span>
              <span class="row-value mono">{{ node.nodeId }}</span>
            </div>
            <div class="dropdown-row">
              <span class="row-label">Status</span>
              <span class="row-value" :class="'status-' + node.status">{{ node.status }}</span>
            </div>
            <div class="dropdown-row">
              <span class="row-label">Mode</span>
              <span class="row-value">{{ getModeDescription(node) }}</span>
            </div>
            <div v-if="node.channelCount != null" class="dropdown-row">
              <span class="row-label">Channels</span>
              <span class="row-value">{{ node.channelCount }}</span>
            </div>
            <div v-if="node.acquiring != null" class="dropdown-row">
              <span class="row-label">Acquiring</span>
              <span class="row-value" :class="node.acquiring ? 'status-online' : ''">
                {{ node.acquiring ? 'Yes' : 'No' }}
              </span>
            </div>
            <div v-if="node.recording != null" class="dropdown-row">
              <span class="row-label">Recording</span>
              <span class="row-value" :class="node.recording ? 'status-recording' : ''">
                {{ node.recording ? 'Yes' : 'No' }}
              </span>
            </div>
            <div v-if="node.safetyState && node.safetyState !== 'normal'" class="dropdown-row">
              <span class="row-label">Safety</span>
              <span class="row-value" :class="'safety-' + node.safetyState">
                {{ node.safetyState }}
              </span>
            </div>
            <div class="dropdown-row">
              <span class="row-label">Last seen</span>
              <span class="row-value">{{ getTimeSince(node.lastSeen) }}</span>
            </div>
            <div v-if="node.configSynced === false" class="dropdown-row">
              <span class="row-label">Config</span>
              <span class="row-value status-warning">Out of sync</span>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.node-status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.node-pill {
  position: relative;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  cursor: pointer;
  font-size: 11px;
  color: var(--text-secondary);
  transition: all 0.15s;
  white-space: nowrap;
}

.node-pill:hover {
  background: var(--bg-hover);
  border-color: var(--border-light);
  color: var(--text-primary);
}

.node-pill.active {
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 1px var(--accent-primary);
  color: var(--text-primary);
}

.node-pill.offline {
  opacity: 0.6;
}

.node-pill.switching {
  pointer-events: none;
  opacity: 0.7;
}

.node-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 3px;
  background: var(--bg-tertiary, var(--bg-hover));
  font-size: 9px;
  font-weight: 700;
  color: var(--text-secondary);
}

.node-name {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.online {
  background: #22c55e;
}

.status-dot.offline {
  background: #ef4444;
}

.status-dot.unknown {
  background: #eab308;
}

/* Hover dropdown */
.node-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  min-width: 240px;
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}

.dropdown-header {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-primary);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dropdown-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.dropdown-type {
  font-size: 11px;
  color: var(--text-tertiary);
}

.dropdown-body {
  padding: 8px 0;
}

.dropdown-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  font-size: 12px;
}

.row-label {
  color: var(--text-tertiary);
}

.row-value {
  color: var(--text-primary);
}

.row-value.mono {
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  font-size: 11px;
}

.status-online { color: #22c55e; }
.status-offline { color: #ef4444; }
.status-warning { color: #eab308; }
.status-recording { color: #3b82f6; }
.safety-warning { color: #eab308; }
.safety-tripped { color: #ef4444; font-weight: 600; }
.safety-emergency { color: #ef4444; font-weight: 700; }

/* Transitions */
.dropdown-enter-active { transition: opacity 0.15s, transform 0.15s; }
.dropdown-leave-active { transition: opacity 0.1s, transform 0.1s; }
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-4px);
}
</style>
