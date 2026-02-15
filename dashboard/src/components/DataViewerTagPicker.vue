<script setup lang="ts">
/**
 * DataViewerTagPicker.vue — Inline dropdown for per-panel channel selection.
 *
 * Searchable, grouped by prefix (Hardware, Scripts, System, User Vars, Formulas).
 * Checkboxes with color indicators. "Select All in Group" per group header.
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import type { HistorianTag } from '../types'

const props = defineProps<{
  tags: HistorianTag[]
  selected: string[]
  colors: string[]
}>()

const emit = defineEmits<{
  (e: 'update', channels: string[]): void
}>()

const isOpen = ref(false)
const search = ref('')
const searchRef = ref<HTMLInputElement | null>(null)
const dropdownRef = ref<HTMLDivElement | null>(null)

// Grouped and filtered tags
const filteredGroups = computed(() => {
  const groups: Record<string, HistorianTag[]> = {
    'Hardware': [],
    'Scripts': [],
    'System': [],
    'User Vars': [],
    'Formulas': [],
    'Other': []
  }

  const q = search.value.toLowerCase().trim()

  for (const tag of props.tags) {
    if (q && !tag.name.toLowerCase().includes(q)) continue

    if (tag.name.startsWith('py.')) groups['Scripts']!.push(tag)
    else if (tag.name.startsWith('sys.')) groups['System']!.push(tag)
    else if (tag.name.startsWith('uv.')) groups['User Vars']!.push(tag)
    else if (tag.name.startsWith('fx.')) groups['Formulas']!.push(tag)
    else groups['Hardware']!.push(tag)
  }

  // Remove empty groups
  const result: Record<string, HistorianTag[]> = {}
  for (const [key, tags] of Object.entries(groups)) {
    if (tags.length > 0) result[key] = tags
  }
  return result
})

const selectedSet = computed(() => new Set(props.selected))

function toggle(tagName: string) {
  const current = new Set(props.selected)
  if (current.has(tagName)) {
    current.delete(tagName)
  } else {
    current.add(tagName)
  }
  emit('update', Array.from(current))
}

function selectAllInGroup(group: HistorianTag[]) {
  const current = new Set(props.selected)
  const allSelected = group.every(t => current.has(t.name))
  if (allSelected) {
    // Deselect all in group
    for (const t of group) current.delete(t.name)
  } else {
    // Select all in group
    for (const t of group) current.add(t.name)
  }
  emit('update', Array.from(current))
}

function open() {
  isOpen.value = true
  nextTick(() => searchRef.value?.focus())
}

function close() {
  isOpen.value = false
  search.value = ''
}

// Close on outside click
function handleClickOutside(e: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    close()
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})

function getColor(tagName: string): string {
  const idx = props.selected.indexOf(tagName)
  if (idx >= 0 && props.colors[idx]) return props.colors[idx]!
  return '#666'
}

function formatCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`
  return String(count)
}
</script>

<template>
  <div class="tag-picker" ref="dropdownRef">
    <button class="picker-trigger" @click="isOpen ? close() : open()">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/>
        <line x1="7" y1="7" x2="7.01" y2="7"/>
      </svg>
      <span v-if="selected.length > 0">{{ selected.length }} tag{{ selected.length !== 1 ? 's' : '' }}</span>
      <span v-else>Select Tags...</span>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="chevron" :class="{ open: isOpen }">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </button>

    <div v-if="isOpen" class="picker-dropdown">
      <div class="picker-search">
        <input
          ref="searchRef"
          v-model="search"
          type="text"
          placeholder="Search tags..."
          class="search-input"
          @keydown.escape="close"
        />
      </div>

      <div class="picker-list">
        <template v-for="(tags, groupName) in filteredGroups" :key="groupName">
          <div class="group-header" @click="selectAllInGroup(tags)">
            <span class="group-name">{{ groupName }}</span>
            <span class="group-count">{{ tags.length }}</span>
            <span class="group-toggle">{{ tags.every(t => selectedSet.has(t.name)) ? 'Deselect All' : 'Select All' }}</span>
          </div>
          <label
            v-for="tag in tags"
            :key="tag.name"
            class="tag-item"
            :class="{ selected: selectedSet.has(tag.name) }"
          >
            <input
              type="checkbox"
              :checked="selectedSet.has(tag.name)"
              @change="toggle(tag.name)"
              class="tag-checkbox"
            />
            <span class="tag-color" :style="{ background: selectedSet.has(tag.name) ? getColor(tag.name) : '#444' }"></span>
            <span class="tag-name">{{ tag.name }}</span>
            <span class="tag-unit" v-if="tag.unit">{{ tag.unit }}</span>
            <span class="tag-points" v-if="tag.point_count">{{ formatCount(tag.point_count) }} pts</span>
          </label>
        </template>

        <div v-if="Object.keys(filteredGroups).length === 0" class="no-results">
          No tags match "{{ search }}"
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tag-picker {
  position: relative;
}

.picker-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.picker-trigger:hover {
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.chevron {
  transition: transform 0.2s;
}

.chevron.open {
  transform: rotate(180deg);
}

.picker-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  width: 300px;
  max-height: 350px;
  background: var(--bg-widget);
  border: 1px solid var(--color-accent);
  border-radius: 6px;
  z-index: 500;
  box-shadow: var(--shadow-md, 0 8px 32px rgba(0, 0, 0, 0.5));
  display: flex;
  flex-direction: column;
  margin-top: 4px;
}

.picker-search {
  padding: 8px;
  border-bottom: 1px solid var(--border-color);
}

.search-input {
  width: 100%;
  padding: 6px 8px;
  background: var(--bg-input, var(--bg-secondary));
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.75rem;
  outline: none;
}

.search-input:focus {
  border-color: var(--color-accent);
}

.search-input::placeholder {
  color: var(--text-muted);
}

.picker-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.group-header:hover {
  background: var(--bg-hover);
}

.group-name {
  flex: 1;
}

.group-count {
  background: var(--bg-hover);
  padding: 1px 5px;
  border-radius: 8px;
  font-size: 0.6rem;
}

.group-toggle {
  font-size: 0.55rem;
  color: var(--color-accent);
  font-weight: 400;
}

.tag-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 16px;
  cursor: pointer;
  border-radius: 3px;
  transition: background 0.1s;
  font-size: 0.7rem;
}

.tag-item:hover {
  background: var(--bg-hover);
}

.tag-item.selected {
  background: rgba(59, 130, 246, 0.08);
}

.tag-checkbox {
  width: 12px;
  height: 12px;
  accent-color: var(--color-accent);
  flex-shrink: 0;
}

.tag-color {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}

.tag-name {
  flex: 1;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-unit {
  color: var(--text-muted);
  font-size: 0.6rem;
}

.tag-points {
  color: var(--text-muted);
  font-size: 0.55rem;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
}

.no-results {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.75rem;
}
</style>
