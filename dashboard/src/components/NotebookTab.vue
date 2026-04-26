<script setup lang="ts">
import { ref, computed } from 'vue'
import { useNotebook } from '../composables/useNotebook'
import type { NotebookEntry, NotebookTemplate } from '../types/notebook'

const notebook = useNotebook()

// UI State
const showNewEntry = ref(false)
const showNewExperiment = ref(false)
const expandedEntryId = ref<string | null>(null)
const showExportMenu = ref(false)

// New entry form
const newEntry = ref({
  type: 'note' as NotebookEntry['type'],
  title: '',
  content: '',
  tags: ''
})

// New experiment form
const newExperiment = ref({
  name: '',
  description: ''
})

// Entry type options
const entryTypes: { value: NotebookEntry['type']; label: string; icon: string }[] = [
  { value: 'note', label: 'Note', icon: '📝' },
  { value: 'observation', label: 'Observation', icon: '👁' },
  { value: 'procedure', label: 'Procedure', icon: '📋' },
  { value: 'result', label: 'Result', icon: '📊' },
  { value: 'issue', label: 'Issue', icon: '⚠️' }
]

// Filter type label for display
function getFilterLabel(type: string): string {
  if (type === 'all') return 'All Types'
  return entryTypes.find(t => t.value === type)?.label || type
}

function getTypeIcon(type: NotebookEntry['type']): string {
  return entryTypes.find(t => t.value === type)?.icon || '📝'
}

// Entries for current experiment
const currentEntries = computed(() => {
  const expId = notebook.activeExperimentId.value || 'unassigned'
  let entries = notebook.entries.value.filter(e =>
    (e.experimentId || 'unassigned') === expId
  )

  // Apply search filter
  if (notebook.searchQuery.value) {
    const q = notebook.searchQuery.value.toLowerCase()
    entries = entries.filter(e =>
      (e.title && e.title.toLowerCase().includes(q)) ||
      (e.content && e.content.toLowerCase().includes(q))
    )
  }

  // Apply type filter
  if (notebook.filterType.value !== 'all') {
    entries = entries.filter(e => e.type === notebook.filterType.value)
  }

  return entries.sort((a, b) =>
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )
})

// Unassigned entries count
const unassignedCount = computed(() =>
  notebook.entries.value.filter(e => !e.experimentId).length
)

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Actions
function openNewEntry(template?: NotebookTemplate) {
  if (template) {
    newEntry.value = {
      type: template.type,
      title: template.titleTemplate,
      content: template.contentTemplate,
      tags: template.defaultTags.join(', ')
    }
  } else {
    newEntry.value = { type: 'note', title: '', content: '', tags: '' }
  }
  showNewEntry.value = true
}

function saveEntry() {
  if (!newEntry.value.title.trim()) return

  notebook.addEntry({
    type: newEntry.value.type,
    title: newEntry.value.title.trim(),
    content: newEntry.value.content,
    tags: newEntry.value.tags.split(',').map(t => t.trim()).filter(Boolean),
    dataSnapshot: notebook.captureDataSnapshot()
  })

  showNewEntry.value = false
  newEntry.value = { type: 'note', title: '', content: '', tags: '' }
}

function startExperiment() {
  if (!newExperiment.value.name.trim()) return

  notebook.startExperiment(
    newExperiment.value.name.trim(),
    newExperiment.value.description
  )

  showNewExperiment.value = false
  newExperiment.value = { name: '', description: '' }
}

function endActiveExperiment() {
  if (!notebook.activeExperiment.value) return
  if (confirm(`End experiment "${notebook.activeExperiment.value.name}"?`)) {
    notebook.endExperiment(notebook.activeExperiment.value.id)
  }
}

function selectExperiment(id: string | null) {
  notebook.setActiveExperiment(id)
}

function toggleEntry(id: string) {
  expandedEntryId.value = expandedEntryId.value === id ? null : id
}

// Quick note
const quickNote = ref('')

function addQuickNote() {
  if (!quickNote.value.trim()) return
  notebook.addQuickNote(quickNote.value.trim())
  quickNote.value = ''
}

// Export functions
function exportMarkdown() {
  notebook.exportToMarkdown(notebook.activeExperimentId.value)
  showExportMenu.value = false
}

function exportText() {
  notebook.exportToText(notebook.activeExperimentId.value)
  showExportMenu.value = false
}

function exportPdf() {
  notebook.exportToPdf()
  showExportMenu.value = false
}

// Delete confirms in two steps: confirm dialog + reason prompt. The reason
// becomes part of the audit-trail amendment so the deleted record retains
// its provenance (ALCOA+ compliance).
function deleteEntry(id: string, title: string) {
  if (!confirm(`Delete entry "${title}"?\n\nThe entry will be archived for audit retrieval but removed from the active list.`)) return
  const reason = window.prompt('Reason for deletion (required for audit trail):') || ''
  if (!reason.trim()) {
    alert('A reason is required to delete an entry.')
    return
  }
  notebook.deleteEntry(id, reason.trim())
  if (expandedEntryId.value === id) expandedEntryId.value = null
}

function deleteExperiment(id: string, name: string) {
  if (!confirm(`Delete experiment "${name}"?\n\nAll associated entries remain. The experiment record is archived for audit retrieval.`)) return
  const reason = window.prompt('Reason for deletion (required for audit trail):') || ''
  if (!reason.trim()) {
    alert('A reason is required to delete an experiment.')
    return
  }
  notebook.deleteExperiment(id, reason.trim())
}

function dismissSaveError() {
  notebook.lastSaveError.value = null
}
</script>

<template>
  <div class="notebook-tab">
    <!-- Left Sidebar: Experiments -->
    <aside class="experiments-sidebar">
      <div class="sidebar-header">
        <span>Experiments</span>
        <button class="add-exp-btn" @click="showNewExperiment = true" title="New Experiment">+</button>
      </div>

      <div class="experiment-list">
        <!-- All Notes (unassigned) -->
        <button
          class="exp-tab"
          :class="{ active: !notebook.activeExperimentId.value }"
          @click="selectExperiment(null)"
        >
          <span class="exp-icon">📓</span>
          <span class="exp-name">All Notes</span>
          <span v-if="unassignedCount" class="exp-count">{{ unassignedCount }}</span>
        </button>

        <!-- Active experiments -->
        <div v-if="notebook.experiments.value.filter(e => e.status === 'active').length" class="exp-section">
          <div class="exp-section-label">Active</div>
          <button
            v-for="exp in notebook.experiments.value.filter(e => e.status === 'active')"
            :key="exp.id"
            class="exp-tab"
            :class="{ active: notebook.activeExperimentId.value === exp.id }"
            @click="selectExperiment(exp.id)"
          >
            <span class="exp-icon">🔬</span>
            <span class="exp-name">{{ exp.name }}</span>
          </button>
        </div>

        <!-- Completed experiments -->
        <div v-if="notebook.experiments.value.filter(e => e.status === 'completed').length" class="exp-section">
          <div class="exp-section-label">Completed</div>
          <div
            v-for="exp in notebook.experiments.value.filter(e => e.status === 'completed')"
            :key="exp.id"
            class="exp-tab-row"
          >
            <button
              class="exp-tab"
              :class="{ active: notebook.activeExperimentId.value === exp.id }"
              @click="selectExperiment(exp.id)"
            >
              <span class="exp-icon">✓</span>
              <span class="exp-name">{{ exp.name }}</span>
            </button>
            <button
              class="exp-delete-btn"
              @click.stop="deleteExperiment(exp.id, exp.name)"
              title="Delete experiment (archived for audit)"
              aria-label="Delete experiment"
            >🗑</button>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="notebook-main">
      <!-- Header Bar -->
      <div class="main-header">
        <div class="header-left">
          <h2>{{ notebook.activeExperiment.value?.name || 'All Notes' }}</h2>
          <button
            v-if="notebook.activeExperiment.value?.status === 'active'"
            class="end-exp-btn"
            @click="endActiveExperiment"
          >
            End Experiment
          </button>
        </div>

        <div class="header-right">
          <select
            class="filter-type-select"
            :value="notebook.filterType.value"
            @change="notebook.filterType.value = ($event.target as HTMLSelectElement).value as any"
          >
            <option value="all">All Types</option>
            <option v-for="t in entryTypes" :key="t.value" :value="t.value">{{ t.icon }} {{ t.label }}</option>
          </select>
          <input
            type="text"
            placeholder="Search..."
            :value="notebook.searchQuery.value"
            @input="notebook.setSearchQuery(($event.target as HTMLInputElement).value)"
            class="search-input"
          />
          <div class="export-menu">
            <button class="export-btn" @click="showExportMenu = !showExportMenu">Export</button>
            <div v-if="showExportMenu" class="export-dropdown">
              <button @click="exportMarkdown">Markdown (.md)</button>
              <button @click="exportText">Text (.txt)</button>
              <button @click="exportPdf">Print / PDF</button>
            </div>
          </div>
          <button class="new-entry-btn" @click="openNewEntry()">+ Entry</button>
        </div>
      </div>

      <!-- Save status / error banner -->
      <div v-if="notebook.lastSaveError.value" class="save-status-banner error" role="alert">
        <span class="save-icon" aria-hidden="true">⚠</span>
        <span class="save-text">{{ notebook.lastSaveError.value }}</span>
        <button class="save-dismiss" @click="dismissSaveError" aria-label="Dismiss">×</button>
      </div>
      <div v-else-if="notebook.savePending.value" class="save-status-banner pending">
        <span class="save-icon" aria-hidden="true">⟳</span>
        <span class="save-text">Saving…</span>
      </div>
      <div v-else-if="notebook.lastSavedAt.value" class="save-status-banner ok">
        <span class="save-icon" aria-hidden="true">✓</span>
        <span class="save-text">Saved {{ formatTime(notebook.lastSavedAt.value) }}</span>
      </div>

      <!-- Quick Note -->
      <div class="quick-note">
        <input
          v-model="quickNote"
          type="text"
          placeholder="Quick note... (Enter to add)"
          @keyup.enter="addQuickNote"
        />
      </div>

      <!-- Entries List -->
      <div class="entries-list">
        <div v-if="currentEntries.length === 0" class="empty-state">
          <p>No entries yet</p>
          <div class="quick-templates">
            <button
              v-for="t in notebook.templates.value"
              :key="t.id"
              @click="openNewEntry(t)"
            >
              {{ t.name }}
            </button>
          </div>
        </div>

        <article
          v-for="entry in currentEntries"
          :key="entry.id"
          class="entry"
          :class="{ expanded: expandedEntryId === entry.id }"
        >
          <div class="entry-header" @click="toggleEntry(entry.id)">
            <span class="entry-icon">{{ getTypeIcon(entry.type) }}</span>
            <div class="entry-info">
              <span class="entry-title">{{ entry.title }}</span>
              <span class="entry-time">{{ formatTime(entry.timestamp) }}</span>
            </div>
            <span v-if="entry.dataSnapshot" class="has-data" title="Has data snapshot">📊</span>
            <button
              class="entry-delete-btn"
              @click.stop="deleteEntry(entry.id, entry.title)"
              :title="'Delete entry (archived for audit)'"
              aria-label="Delete entry"
            >🗑</button>
            <span class="expand-icon">{{ expandedEntryId === entry.id ? '▼' : '▶' }}</span>
          </div>

          <div v-if="expandedEntryId === entry.id" class="entry-body">
            <div v-if="entry.operator" class="entry-operator">By: {{ entry.operator }}</div>

            <pre v-if="entry.content" class="entry-content">{{ entry.content }}</pre>

            <div v-if="entry.tags.length" class="entry-tags">
              <span v-for="tag in entry.tags" :key="tag" class="tag">{{ tag }}</span>
            </div>

            <div v-if="entry.dataSnapshot" class="data-snapshot">
              <div class="snapshot-header">Data Snapshot ({{ formatTime(entry.dataSnapshot.capturedAt) }})</div>
              <div class="snapshot-grid">
                <div v-for="(val, ch) in entry.dataSnapshot.channels" :key="ch" class="snapshot-item">
                  <span class="ch-name">{{ ch }}</span>
                  <span class="ch-value">{{ val.value.toFixed(2) }} {{ val.unit }}</span>
                </div>
              </div>
            </div>

            <div v-if="entry.amendments && entry.amendments.length" class="amendments-section">
              <div class="amendments-header">Edit History ({{ entry.amendments.length }})</div>
              <div v-for="(a, i) in entry.amendments" :key="i" class="amendment-item">
                <span class="amendment-time">{{ formatTime(a.timestamp) }}</span>
                <span class="amendment-field">{{ a.field }}</span>
                <span v-if="a.reason" class="amendment-reason">{{ a.reason }}</span>
              </div>
            </div>
          </div>
        </article>
      </div>
    </main>

    <!-- New Entry Modal -->
    <div v-if="showNewEntry" class="modal-overlay" @click.self="showNewEntry = false">
      <div class="modal">
        <div class="modal-header">
          <h3>New Entry</h3>
          <button class="close-btn" @click="showNewEntry = false">×</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Type</label>
            <div class="type-btns">
              <button
                v-for="t in entryTypes"
                :key="t.value"
                :class="{ active: newEntry.type === t.value }"
                @click="newEntry.type = t.value"
              >
                {{ t.icon }}
              </button>
            </div>
          </div>

          <div class="form-row">
            <label>Title</label>
            <input v-model="newEntry.title" type="text" placeholder="Entry title" />
          </div>

          <div class="form-row">
            <label>Content</label>
            <textarea v-model="newEntry.content" rows="6" placeholder="Notes..."></textarea>
          </div>

          <div class="form-row">
            <label>Tags</label>
            <input v-model="newEntry.tags" type="text" placeholder="tag1, tag2" />
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="showNewEntry = false">Cancel</button>
          <button class="btn-save" @click="saveEntry" :disabled="!newEntry.title.trim()">Save</button>
        </div>
      </div>
    </div>

    <!-- New Experiment Modal -->
    <div v-if="showNewExperiment" class="modal-overlay" @click.self="showNewExperiment = false">
      <div class="modal modal-sm">
        <div class="modal-header">
          <h3>New Experiment</h3>
          <button class="close-btn" @click="showNewExperiment = false">×</button>
        </div>

        <div class="modal-body">
          <div class="form-row">
            <label>Name</label>
            <input v-model="newExperiment.name" type="text" placeholder="Experiment name" />
          </div>
          <div class="form-row">
            <label>Description</label>
            <textarea v-model="newExperiment.description" rows="2" placeholder="Optional"></textarea>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="showNewExperiment = false">Cancel</button>
          <button class="btn-save" @click="startExperiment" :disabled="!newExperiment.name.trim()">Start</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.notebook-tab {
  display: flex;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-bright);
}

/* Sidebar */
.experiments-sidebar {
  width: 200px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  font-weight: 600;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--border-color);
}

.add-exp-btn {
  width: 24px;
  height: 24px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 1rem;
  cursor: pointer;
}

.experiment-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.exp-section {
  margin-top: 12px;
}

.exp-section-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  text-transform: uppercase;
  padding: 4px 8px;
}

.exp-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
}

.exp-tab:hover {
  background: var(--bg-widget);
}

.exp-tab.active {
  background: var(--bg-active);
  color: var(--text-primary);
}

.exp-icon {
  font-size: 0.9rem;
}

.exp-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exp-count {
  font-size: 0.7rem;
  background: var(--border-color);
  padding: 2px 6px;
  border-radius: 8px;
}

/* Main */
.notebook-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.main-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.main-header h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.end-exp-btn {
  padding: 4px 10px;
  background: transparent;
  border: 1px solid var(--color-error);
  color: var(--color-error);
  border-radius: 4px;
  font-size: 0.7rem;
  cursor: pointer;
}

.header-right {
  display: flex;
  gap: 8px;
}

.search-input {
  width: 180px;
  padding: 6px 10px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.8rem;
}

.new-entry-btn {
  padding: 6px 12px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
}

/* Export Menu */
.export-menu {
  position: relative;
}

.export-btn {
  padding: 6px 12px;
  background: var(--border-color);
  border: none;
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.8rem;
  cursor: pointer;
}

.export-btn:hover {
  background: var(--border-light);
}

.export-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: var(--bg-widget);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  overflow: hidden;
  z-index: 100;
  min-width: 140px;
}

.export-dropdown button {
  display: block;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: var(--text-bright);
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
}

.export-dropdown button:hover {
  background: var(--border-color);
}

/* Quick Note */
.quick-note {
  padding: 8px 16px;
  border-bottom: 1px solid var(--bg-widget);
}

.quick-note input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
}

/* Entries */
.entries-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 16px;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}

.quick-templates {
  display: flex;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
}

.quick-templates button {
  padding: 6px 12px;
  background: var(--bg-widget);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.75rem;
  cursor: pointer;
}

.entry {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;
}

.entry-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
}

.entry-header:hover {
  background: var(--bg-hover);
}

.entry-icon {
  font-size: 1rem;
}

.entry-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.entry-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-time {
  font-size: 0.7rem;
  color: var(--text-muted);
  flex-shrink: 0;
}

.has-data {
  font-size: 0.8rem;
}

.expand-icon {
  font-size: 0.6rem;
  color: var(--text-muted);
}

.entry-body {
  padding: 0 12px 12px;
  border-top: 1px solid var(--border-color);
}

.entry-content {
  margin: 12px 0;
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-bright);
}

.entry-tags {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.tag {
  padding: 2px 8px;
  background: var(--border-color);
  border-radius: 10px;
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.data-snapshot {
  background: var(--bg-secondary);
  border-radius: 4px;
  padding: 10px;
}

.snapshot-header {
  font-size: 0.7rem;
  color: var(--color-accent-light);
  margin-bottom: 8px;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 6px;
}

.snapshot-item {
  display: flex;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--bg-widget);
  border-radius: 3px;
  font-size: 0.75rem;
}

.ch-name {
  color: var(--text-secondary);
}

.ch-value {
  font-family: 'JetBrains Mono', monospace;
  color: var(--color-success);
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  width: 90%;
  max-width: 500px;
  background: var(--bg-widget);
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.modal.modal-sm {
  max-width: 360px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  font-size: 1rem;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 1.25rem;
  cursor: pointer;
}

.modal-body {
  padding: 16px;
}

.form-row {
  margin-bottom: 12px;
}

.form-row label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.form-row input,
.form-row textarea {
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  color: var(--text-bright);
  font-size: 0.85rem;
  resize: vertical;
}

.type-btns {
  display: flex;
  gap: 6px;
}

.type-btns button {
  padding: 6px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
}

.type-btns button.active {
  background: var(--color-accent);
  border-color: var(--color-accent);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.btn-cancel {
  padding: 8px 16px;
  background: var(--border-color);
  border: none;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}

.btn-save {
  padding: 8px 16px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  color: white;
  font-weight: 500;
  cursor: pointer;
}

.btn-save:disabled {
  background: var(--border-color);
  color: var(--text-muted);
  cursor: not-allowed;
}

/* Filter type select */
.filter-type-select {
  padding: 6px 10px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.8rem;
  cursor: pointer;
}

.filter-type-select option {
  background: var(--bg-widget);
  color: var(--text-bright);
}

/* Operator display */
.entry-operator {
  font-size: 0.7rem;
  color: var(--color-accent-light);
  padding: 8px 0 0;
}

/* Amendment history */
.amendments-section {
  margin-top: 12px;
  border-top: 1px solid var(--border-color);
  padding-top: 8px;
}

.amendments-header {
  font-size: 0.7rem;
  color: var(--text-secondary);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.amendment-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 3px 0;
  font-size: 0.75rem;
}

.amendment-time {
  color: var(--text-muted);
  flex-shrink: 0;
}

.amendment-field {
  color: var(--color-warning-dark);
}

.amendment-reason {
  color: var(--text-secondary);
  font-style: italic;
}

/* Save status banner — surfaces persistence failures so they aren't silent */
.save-status-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  margin: 6px 16px;
  border-radius: 4px;
  font-size: 0.78rem;
  border: 1px solid transparent;
}
.save-status-banner.error {
  background: var(--color-error-bg, #2d1418);
  color: var(--color-error, #f85149);
  border-color: var(--color-error, #f85149);
}
.save-status-banner.pending {
  background: var(--bg-widget);
  color: var(--text-secondary);
  border-color: var(--border-color);
}
.save-status-banner.ok {
  background: var(--color-success-bg, #14241b);
  color: var(--color-success, #56d364);
  border-color: var(--color-success, #56d364);
}
.save-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.save-dismiss {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 4px;
}

/* Delete affordances */
.entry-delete-btn,
.exp-delete-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 2px 6px;
  border-radius: 3px;
  opacity: 0.5;
  transition: opacity 0.15s, color 0.15s, background 0.15s;
}
.entry-delete-btn:hover,
.exp-delete-btn:hover {
  opacity: 1;
  color: var(--color-error, #f85149);
  background: var(--bg-hover);
}

.exp-tab-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.exp-tab-row .exp-tab {
  flex: 1;
}
</style>
