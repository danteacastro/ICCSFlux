<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useProjectFiles, type ProjectFile } from '../composables/useProjectFiles'

const emit = defineEmits<{
  (e: 'project-loaded'): void
  (e: 'project-saved'): void
  (e: 'feedback', type: 'success' | 'error', message: string): void
}>()

const projectFiles = useProjectFiles()

// Modal states
const showNewModal = ref(false)
const showOpenModal = ref(false)
const showSaveAsModal = ref(false)
const showConfirmModal = ref(false)

const confirmAction = ref<(() => void) | null>(null)
const confirmMessage = ref('')

const newProjectName = ref('')
const saveAsName = ref('')

onMounted(() => {
  projectFiles.listProjects()
  projectFiles.listConfigs()
})

// Actions
async function handleNew() {
  if (projectFiles.hasUnsavedChanges()) {
    confirmMessage.value = 'You have unsaved changes. Create new project anyway?'
    confirmAction.value = () => {
      showNewModal.value = true
    }
    showConfirmModal.value = true
  } else {
    showNewModal.value = true
  }
}

function handleOpen() {
  projectFiles.listProjects()
  showOpenModal.value = true
}

async function handleSave() {
  if (!projectFiles.currentProject.value) {
    showSaveAsModal.value = true
  } else {
    const success = await projectFiles.saveProject(projectFiles.currentProject.value)
    if (success) {
      emit('feedback', 'success', 'Project saved')
      emit('project-saved')
    } else {
      emit('feedback', 'error', projectFiles.error.value || 'Save failed')
    }
  }
}

function handleSaveAs() {
  saveAsName.value = projectFiles.currentProject.value?.replace('.json', '') || ''
  showSaveAsModal.value = true
}

// Modal handlers
async function createNewProject() {
  if (!newProjectName.value.trim()) return

  projectFiles.newProject()
  const success = await projectFiles.saveProject(newProjectName.value.trim(), newProjectName.value.trim())

  if (success) {
    emit('feedback', 'success', `Created project: ${newProjectName.value}`)
    emit('project-saved')
  } else {
    emit('feedback', 'error', projectFiles.error.value || 'Failed to create project')
  }

  newProjectName.value = ''
  showNewModal.value = false
}

async function openProject(project: ProjectFile) {
  if (projectFiles.hasUnsavedChanges()) {
    confirmMessage.value = 'You have unsaved changes. Open project anyway?'
    confirmAction.value = async () => {
      await doOpenProject(project)
    }
    showConfirmModal.value = true
  } else {
    await doOpenProject(project)
  }
}

async function doOpenProject(project: ProjectFile) {
  const success = await projectFiles.loadProject(project.filename)
  if (success) {
    emit('feedback', 'success', `Loaded project: ${project.name}`)
    emit('project-loaded')
  } else {
    emit('feedback', 'error', projectFiles.error.value || 'Failed to load project')
  }
  showOpenModal.value = false
}

async function deleteProject(project: ProjectFile) {
  if (!confirm(`Delete project "${project.name}"? This cannot be undone.`)) return

  const success = await projectFiles.deleteProject(project.filename)
  if (success) {
    emit('feedback', 'success', `Deleted project: ${project.name}`)
  } else {
    emit('feedback', 'error', projectFiles.error.value || 'Failed to delete project')
  }
}

async function saveProjectAs() {
  if (!saveAsName.value.trim()) return

  const success = await projectFiles.saveProject(saveAsName.value.trim(), saveAsName.value.trim())
  if (success) {
    emit('feedback', 'success', `Saved as: ${saveAsName.value}`)
    emit('project-saved')
  } else {
    emit('feedback', 'error', projectFiles.error.value || 'Save failed')
  }

  saveAsName.value = ''
  showSaveAsModal.value = false
}

function confirmYes() {
  if (confirmAction.value) {
    confirmAction.value()
  }
  showConfirmModal.value = false
  confirmAction.value = null
}

function confirmNo() {
  showConfirmModal.value = false
  confirmAction.value = null
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const hasChanges = computed(() => projectFiles.hasUnsavedChanges())
</script>

<template>
  <div class="project-manager">
    <!-- Project toolbar -->
    <div class="project-toolbar">
      <div class="toolbar-section">
        <span class="section-label">PROJECT</span>
        <button class="action-btn" @click="handleNew" title="New Project">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <line x1="12" y1="11" x2="12" y2="17"/>
            <line x1="9" y1="14" x2="15" y2="14"/>
          </svg>
          New
        </button>
        <button class="action-btn" @click="handleOpen" title="Open Project">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
          </svg>
          Open
        </button>
        <button
          class="action-btn"
          :class="{ dirty: hasChanges }"
          @click="handleSave"
          title="Save Project"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/>
            <polyline points="17,21 17,13 7,13 7,21"/>
            <polyline points="7,3 7,8 15,8"/>
          </svg>
          Save
          <span v-if="hasChanges" class="dirty-dot"></span>
        </button>
        <button class="action-btn" @click="handleSaveAs" title="Save Project As">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/>
            <polyline points="17,21 17,13 7,13 7,21"/>
            <line x1="12" y1="11" x2="12" y2="17"/>
            <line x1="9" y1="14" x2="15" y2="14"/>
          </svg>
          Save As
        </button>
      </div>

      <!-- Current project info -->
      <div class="current-project-info" v-if="projectFiles.currentProject.value">
        <span class="project-name">{{ projectFiles.currentProject.value }}</span>
        <span v-if="projectFiles.currentProjectData.value?.config" class="config-badge">
          {{ projectFiles.currentProjectData.value.config }}
        </span>
      </div>
      <div class="current-project-info no-project" v-else>
        <span class="project-name">No project loaded</span>
      </div>
    </div>

    <!-- New Project Modal -->
    <Teleport to="body">
      <div v-if="showNewModal" class="modal-overlay" @click.self="showNewModal = false">
        <div class="modal">
          <h3>New Project</h3>
          <p class="modal-desc">Create a new project. This will use the current hardware configuration.</p>
          <input
            v-model="newProjectName"
            type="text"
            placeholder="Project name..."
            @keyup.enter="createNewProject"
            autofocus
          />
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showNewModal = false">Cancel</button>
            <button class="btn btn-primary" @click="createNewProject" :disabled="!newProjectName.trim()">Create</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Open Project Modal -->
    <Teleport to="body">
      <div v-if="showOpenModal" class="modal-overlay" @click.self="showOpenModal = false">
        <div class="modal open-modal">
          <h3>Open Project</h3>

          <div v-if="projectFiles.isLoading.value" class="loading">
            Loading projects...
          </div>

          <div v-else-if="projectFiles.projects.value.length === 0" class="empty">
            No projects found. Create a new project to get started.
          </div>

          <div v-else class="project-list">
            <div
              v-for="project in projectFiles.projects.value"
              :key="project.filename"
              class="project-item"
              :class="{ active: project.filename === projectFiles.currentProject.value }"
              @click="openProject(project)"
            >
              <div class="project-info">
                <span class="project-name">{{ project.name }}</span>
                <span class="project-meta">
                  <span class="date">{{ formatDate(project.modified) }}</span>
                  <span v-if="project.config" class="config-ref">{{ project.config }}</span>
                </span>
              </div>
              <button class="delete-btn" @click.stop="deleteProject(project)" title="Delete project">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3,6 5,6 21,6"/>
                  <path d="M19 6l-2 14H7L5 6"/>
                  <path d="M10 11v6"/>
                  <path d="M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
              </button>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showOpenModal = false">Close</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Save As Modal -->
    <Teleport to="body">
      <div v-if="showSaveAsModal" class="modal-overlay" @click.self="showSaveAsModal = false">
        <div class="modal">
          <h3>Save Project As</h3>
          <input
            v-model="saveAsName"
            type="text"
            placeholder="Project name..."
            @keyup.enter="saveProjectAs"
            autofocus
          />
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="showSaveAsModal = false">Cancel</button>
            <button class="btn btn-primary" @click="saveProjectAs" :disabled="!saveAsName.trim()">Save</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Confirm Modal -->
    <Teleport to="body">
      <div v-if="showConfirmModal" class="modal-overlay">
        <div class="modal confirm-modal">
          <h3>Unsaved Changes</h3>
          <p>{{ confirmMessage }}</p>
          <div class="modal-actions">
            <button class="btn btn-secondary" @click="confirmNo">Cancel</button>
            <button class="btn btn-warning" @click="confirmYes">Discard & Continue</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.project-manager {
  margin-bottom: 16px;
}

.project-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.toolbar-section {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-muted);
  margin-right: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-muted);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn:hover {
  background: var(--border-color);
  color: var(--text-primary);
  border-color: var(--border-light);
}

.action-btn.dirty {
  border-color: var(--color-warning);
}

.dirty-dot {
  width: 6px;
  height: 6px;
  background: var(--color-warning);
  border-radius: 50%;
  margin-left: 2px;
}

.current-project-info {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.current-project-info .project-name {
  font-size: 0.85rem;
  color: var(--color-accent-light);
  font-weight: 500;
}

.current-project-info.no-project .project-name {
  color: var(--text-muted);
  font-style: italic;
}

.config-badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: var(--color-accent-bg);
  border-radius: 3px;
  color: var(--color-accent-light);
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.modal {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  min-width: 360px;
  max-width: 500px;
}

.modal h3 {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 1.1rem;
}

.modal-desc {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin: 0 0 16px;
}

.modal p {
  color: var(--text-muted);
  margin: 0 0 16px;
  font-size: 0.9rem;
}

.modal input {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.9rem;
  margin-bottom: 16px;
}

.modal input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--btn-secondary-bg);
  color: var(--text-primary);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--btn-secondary-hover);
}

.btn-primary {
  background: var(--color-accent);
  color: var(--text-primary);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-accent-dark);
}

.btn-warning {
  background: var(--color-warning-dark);
  color: var(--text-primary);
}

.btn-warning:hover:not(:disabled) {
  background: var(--color-warning-dark);
}

/* Open modal */
.open-modal {
  min-width: 450px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
}

.loading, .empty {
  padding: 32px;
  text-align: center;
  color: var(--text-muted);
}

.project-list {
  max-height: 320px;
  overflow-y: auto;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.project-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: background 0.15s;
}

.project-item:last-child {
  border-bottom: none;
}

.project-item:hover {
  background: var(--border-color);
}

.project-item.active {
  background: var(--color-accent-bg);
}

.project-info {
  flex: 1;
  min-width: 0;
}

.project-info .project-name {
  display: block;
  color: var(--text-primary);
  font-weight: 500;
  margin-bottom: 4px;
}

.project-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.75rem;
}

.project-meta .date {
  color: var(--text-muted);
}

.config-ref {
  background: var(--bg-input);
  padding: 2px 6px;
  border-radius: 2px;
  color: var(--text-secondary);
}

.delete-btn {
  padding: 6px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}

.delete-btn:hover {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.confirm-modal {
  max-width: 400px;
}
</style>
