<script setup lang="ts">
import { computed } from 'vue'
import type { NodeState } from '../types'
import NodeCard from './NodeCard.vue'

const props = defineProps<{
  nodes: NodeState[]
  selectedId: string | null
}>()

const emit = defineEmits<{ select: [nodeId: string] }>()

// Sort: errors first → warnings → healthy → unknown
const sortedNodes = computed(() =>
  [...props.nodes].sort((a, b) => {
    const order: Record<string, number> = { error: 0, warning: 1, healthy: 2, unknown: 3 }
    return (order[a.health] ?? 4) - (order[b.health] ?? 4)
  })
)
</script>

<template>
  <aside class="node-list">
    <div class="list-header">
      <span class="list-title">Nodes</span>
      <span class="list-count">{{ nodes.length }}</span>
    </div>

    <div class="list-scroll">
      <NodeCard
        v-for="ns in sortedNodes"
        :key="ns.node.id"
        :node-state="ns"
        :selected="selectedId === ns.node.id"
        @click="emit('select', ns.node.id)"
      />
      <div v-if="nodes.length === 0" class="empty-list">
        <p>No nodes configured</p>
        <p class="hint">Open Settings to add nodes</p>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.node-list {
  width: 300px;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-color);
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
}

.list-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-bright);
}

.list-count {
  font-size: 0.75rem;
  padding: 0.125rem 0.375rem;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border-radius: 4px;
}

.list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
}

.empty-list {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.875rem;
}

.empty-list p { margin: 0.25rem 0; }
.hint { font-size: 0.8rem; color: var(--text-dim); }
</style>
