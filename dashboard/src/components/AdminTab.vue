<template>
  <div class="admin-tab">
    <!-- Access Denied for non-admins -->
    <div v-if="!isAdmin" class="access-denied">
      <div class="denied-icon">🔒</div>
      <h2>Access Restricted</h2>
      <p>Administrator privileges are required to access this section.</p>
      <p class="current-role" v-if="currentUser">
        Your current role: <strong>{{ currentUser.role }}</strong>
      </p>
    </div>

    <!-- Admin Panel -->
    <div v-else class="admin-content">
      <!-- Section Navigation -->
      <div class="section-nav">
        <button
          v-for="section in sections"
          :key="section.id"
          :class="['section-btn', { active: activeSection === section.id }]"
          @click="activeSection = section.id"
        >
          <span class="section-icon">{{ section.icon }}</span>
          {{ section.label }}
        </button>
      </div>

      <!-- User Management Section -->
      <div v-if="activeSection === 'users'" class="section-panel">
        <div class="panel-header">
          <h3>User Management</h3>
          <button class="btn-primary" @click="showCreateUserDialog = true">
            + Add User
          </button>
        </div>

        <div class="users-table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Display Name</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoadingUsers">
                <td colspan="6" class="loading-row">
                  <span class="spinner-small"></span> Loading users...
                </td>
              </tr>
              <tr v-else-if="users.length === 0">
                <td colspan="6" class="empty-row">No users found</td>
              </tr>
              <tr v-for="user in users" :key="user.username">
                <td class="username-cell">
                  <span class="user-avatar">{{ user.username.charAt(0).toUpperCase() }}</span>
                  {{ user.username }}
                </td>
                <td>{{ user.display_name || '-' }}</td>
                <td>
                  <span :class="['role-badge', `role-${user.role}`]">
                    {{ user.role }}
                  </span>
                </td>
                <td>
                  <span :class="['status-badge', user.enabled ? 'enabled' : 'disabled']">
                    {{ user.enabled ? 'Active' : 'Disabled' }}
                  </span>
                </td>
                <td>{{ formatDate(user.last_login) }}</td>
                <td class="actions-cell">
                  <button class="btn-icon" @click="editUser(user)" title="Edit">✏️</button>
                  <button
                    class="btn-icon btn-danger"
                    @click="confirmDeleteUser(user)"
                    title="Delete"
                    :disabled="user.username === currentUser?.username"
                  >🗑️</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Audit Trail Section -->
      <div v-if="activeSection === 'audit'" class="section-panel">
        <div class="panel-header">
          <h3>Audit Trail</h3>
          <div class="header-actions">
            <button class="btn-secondary" @click="refreshAuditEvents">
              🔄 Refresh
            </button>
            <button class="btn-secondary" @click="exportAudit">
              📥 Export
            </button>
          </div>
        </div>

        <!-- Audit Filters -->
        <div class="audit-filters">
          <div class="filter-group">
            <label>Event Type</label>
            <select v-model="auditFilters.eventType">
              <option value="">All Events</option>
              <option value="login">Login</option>
              <option value="logout">Logout</option>
              <option value="config_change">Config Change</option>
              <option value="recording_start">Recording Start</option>
              <option value="recording_stop">Recording Stop</option>
              <option value="alarm">Alarm</option>
              <option value="user_create">User Created</option>
              <option value="user_update">User Updated</option>
              <option value="user_delete">User Deleted</option>
            </select>
          </div>
          <div class="filter-group">
            <label>Username</label>
            <input v-model="auditFilters.username" placeholder="Filter by user..." />
          </div>
          <div class="filter-group">
            <label>From</label>
            <input type="datetime-local" v-model="auditFilters.startTime" />
          </div>
          <div class="filter-group">
            <label>To</label>
            <input type="datetime-local" v-model="auditFilters.endTime" />
          </div>
          <button class="btn-primary" @click="applyAuditFilters">Apply</button>
        </div>

        <div class="audit-table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Event Type</th>
                <th>User</th>
                <th>Details</th>
                <th>Checksum</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoadingAudit">
                <td colspan="5" class="loading-row">
                  <span class="spinner-small"></span> Loading audit events...
                </td>
              </tr>
              <tr v-else-if="auditEvents.length === 0">
                <td colspan="5" class="empty-row">No audit events found</td>
              </tr>
              <tr v-for="event in auditEvents" :key="event.event_id">
                <td class="timestamp-cell">{{ formatTimestamp(event.timestamp) }}</td>
                <td>
                  <span :class="['event-badge', `event-${event.event_type}`]">
                    {{ formatEventType(event.event_type) }}
                  </span>
                </td>
                <td>{{ event.username || 'System' }}</td>
                <td class="details-cell">
                  <span class="details-preview" @click="showEventDetails(event)">
                    {{ formatDetails(event.details) }}
                  </span>
                </td>
                <td class="checksum-cell">
                  <code>{{ event.checksum.substring(0, 8) }}...</code>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Archive Management Section -->
      <div v-if="activeSection === 'archives'" class="section-panel">
        <div class="panel-header">
          <h3>Data Archives</h3>
          <div class="header-actions">
            <button class="btn-secondary" @click="refreshArchives">
              🔄 Refresh
            </button>
          </div>
        </div>

        <div class="archive-info">
          <div class="info-card">
            <span class="info-icon">📦</span>
            <div class="info-content">
              <span class="info-value">{{ archives.length }}</span>
              <span class="info-label">Total Archives</span>
            </div>
          </div>
          <div class="info-card">
            <span class="info-icon">💾</span>
            <div class="info-content">
              <span class="info-value">{{ formatTotalSize() }}</span>
              <span class="info-label">Total Size</span>
            </div>
          </div>
          <div class="info-card">
            <span class="info-icon">📅</span>
            <div class="info-content">
              <span class="info-value">10 Years</span>
              <span class="info-label">Retention Period</span>
            </div>
          </div>
        </div>

        <div class="archives-table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Archive ID</th>
                <th>Original File</th>
                <th>Type</th>
                <th>Size</th>
                <th>Archived</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoadingArchives">
                <td colspan="6" class="loading-row">
                  <span class="spinner-small"></span> Loading archives...
                </td>
              </tr>
              <tr v-else-if="archives.length === 0">
                <td colspan="6" class="empty-row">No archives found</td>
              </tr>
              <tr v-for="archive in archives" :key="archive.archive_id">
                <td class="id-cell">
                  <code>{{ archive.archive_id.substring(0, 8) }}...</code>
                </td>
                <td>{{ archive.original_filename }}</td>
                <td>
                  <span class="type-badge">{{ archive.content_type }}</span>
                </td>
                <td>{{ formatBytes(archive.size_bytes) }}</td>
                <td>{{ formatDate(archive.archived_at) }}</td>
                <td class="actions-cell">
                  <button class="btn-icon" @click="verifyArchiveIntegrity(archive)" title="Verify">✅</button>
                  <button class="btn-icon" @click="downloadArchive(archive)" title="Download">📥</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Create/Edit User Dialog -->
    <Teleport to="body">
      <div v-if="showCreateUserDialog || editingUser" class="modal-overlay" @click.self="closeUserDialog">
        <div class="modal-dialog">
          <div class="modal-header">
            <h3>{{ editingUser ? 'Edit User' : 'Create New User' }}</h3>
            <button class="btn-close" @click="closeUserDialog">&times;</button>
          </div>
          <form @submit.prevent="saveUser" class="modal-body">
            <div class="form-group">
              <label>Username *</label>
              <input
                v-model="userForm.username"
                type="text"
                :disabled="!!editingUser"
                placeholder="Enter username"
                required
              />
            </div>
            <div class="form-group">
              <label>{{ editingUser ? 'New Password (leave blank to keep)' : 'Password *' }}</label>
              <input
                v-model="userForm.password"
                type="password"
                :placeholder="editingUser ? 'Leave blank to keep current' : 'Enter password'"
                :required="!editingUser"
              />
            </div>
            <div class="form-group">
              <label>Display Name</label>
              <input
                v-model="userForm.display_name"
                type="text"
                placeholder="Enter display name"
              />
            </div>
            <div class="form-group">
              <label>Email</label>
              <input
                v-model="userForm.email"
                type="email"
                placeholder="Enter email address"
              />
            </div>
            <div class="form-group">
              <label>Role *</label>
              <select v-model="userForm.role" required>
                <option value="viewer">Viewer - Read-only monitoring access</option>
                <option value="operator">Operator - Day-to-day operations, alarm acknowledgment</option>
                <option value="engineer">Engineer - Configure channels, alarms, safety, projects</option>
                <option value="admin">Admin - Full system access, user management</option>
              </select>
            </div>
            <div v-if="editingUser" class="form-group checkbox-group">
              <label>
                <input type="checkbox" v-model="userForm.enabled" />
                Account Enabled
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn-cancel" @click="closeUserDialog">Cancel</button>
              <button type="submit" class="btn-primary">
                {{ editingUser ? 'Update User' : 'Create User' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- Event Details Dialog -->
    <Teleport to="body">
      <div v-if="selectedEvent" class="modal-overlay" @click.self="selectedEvent = null">
        <div class="modal-dialog">
          <div class="modal-header">
            <h3>Event Details</h3>
            <button class="btn-close" @click="selectedEvent = null">&times;</button>
          </div>
          <div class="modal-body event-details">
            <div class="detail-row">
              <span class="detail-label">Event ID:</span>
              <code>{{ selectedEvent.event_id }}</code>
            </div>
            <div class="detail-row">
              <span class="detail-label">Timestamp:</span>
              <span>{{ formatTimestamp(selectedEvent.timestamp) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Event Type:</span>
              <span :class="['event-badge', `event-${selectedEvent.event_type}`]">
                {{ formatEventType(selectedEvent.event_type) }}
              </span>
            </div>
            <div class="detail-row">
              <span class="detail-label">User:</span>
              <span>{{ selectedEvent.username || 'System' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Checksum:</span>
              <code class="full-checksum">{{ selectedEvent.checksum }}</code>
            </div>
            <div class="detail-section">
              <span class="detail-label">Details:</span>
              <pre class="details-json">{{ JSON.stringify(selectedEvent.details, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Confirmation Dialog -->
    <Teleport to="body">
      <div v-if="userToDelete" class="modal-overlay" @click.self="userToDelete = null">
        <div class="modal-dialog modal-confirm">
          <div class="modal-header">
            <h3>Confirm Delete</h3>
          </div>
          <div class="modal-body">
            <p class="confirm-message">
              Are you sure you want to delete user <strong>{{ userToDelete.username }}</strong>?
            </p>
            <p class="confirm-warning">This action cannot be undone.</p>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="userToDelete = null">Cancel</button>
            <button class="btn-danger" @click="performDeleteUser">Delete User</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAuth, type User, type AuditEvent, type ArchiveEntry } from '../composables/useAuth'

const {
  currentUser,
  isAdmin,
  users,
  isLoadingUsers,
  auditEvents,
  isLoadingAudit,
  archives,
  isLoadingArchives,
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  queryAuditEvents,
  exportAuditEvents,
  listArchives,
  verifyArchive,
  retrieveArchive
} = useAuth()

// Section navigation
const sections = [
  { id: 'users', icon: '👥', label: 'Users' },
  { id: 'audit', icon: '📋', label: 'Audit Trail' },
  { id: 'archives', icon: '📦', label: 'Archives' }
]
const activeSection = ref('users')

// User management state
const showCreateUserDialog = ref(false)
const editingUser = ref<User | null>(null)
const userToDelete = ref<User | null>(null)
const userForm = ref({
  username: '',
  password: '',
  display_name: '',
  email: '',
  role: 'operator',
  enabled: true
})

// Audit filters
const auditFilters = ref({
  eventType: '',
  username: '',
  startTime: '',
  endTime: ''
})

// Selected event for details view
const selectedEvent = ref<AuditEvent | null>(null)

// ============================================================================
// LIFECYCLE
// ============================================================================

onMounted(() => {
  if (isAdmin.value) {
    listUsers()
    queryAuditEvents({ limit: 100 })
    listArchives()
  }
})

// ============================================================================
// USER MANAGEMENT
// ============================================================================

function editUser(user: User) {
  editingUser.value = user
  userForm.value = {
    username: user.username,
    password: '',
    display_name: user.display_name || '',
    email: user.email || '',
    role: user.role,
    enabled: user.enabled
  }
}

function confirmDeleteUser(user: User) {
  userToDelete.value = user
}

function performDeleteUser() {
  if (userToDelete.value) {
    deleteUser(userToDelete.value.username)
    userToDelete.value = null
  }
}

function closeUserDialog() {
  showCreateUserDialog.value = false
  editingUser.value = null
  userForm.value = {
    username: '',
    password: '',
    display_name: '',
    email: '',
    role: 'operator',
    enabled: true
  }
}

function saveUser() {
  if (editingUser.value) {
    // Update existing user
    const updates: Record<string, any> = {
      role: userForm.value.role,
      display_name: userForm.value.display_name || undefined,
      email: userForm.value.email || undefined,
      enabled: userForm.value.enabled
    }
    if (userForm.value.password) {
      updates.password = userForm.value.password
    }
    updateUser(editingUser.value.username, updates)
  } else {
    // Create new user
    createUser({
      username: userForm.value.username,
      password: userForm.value.password,
      role: userForm.value.role,
      display_name: userForm.value.display_name || undefined,
      email: userForm.value.email || undefined
    })
  }
  closeUserDialog()
}

// ============================================================================
// AUDIT TRAIL
// ============================================================================

function refreshAuditEvents() {
  queryAuditEvents({ limit: 100 })
}

function applyAuditFilters() {
  const options: Record<string, any> = { limit: 100 }
  if (auditFilters.value.eventType) {
    options.event_types = [auditFilters.value.eventType]
  }
  if (auditFilters.value.username) {
    options.username = auditFilters.value.username
  }
  if (auditFilters.value.startTime) {
    options.start_time = new Date(auditFilters.value.startTime).toISOString()
  }
  if (auditFilters.value.endTime) {
    options.end_time = new Date(auditFilters.value.endTime).toISOString()
  }
  queryAuditEvents(options)
}

function exportAudit() {
  exportAuditEvents({ format: 'csv' })
}

function showEventDetails(event: AuditEvent) {
  selectedEvent.value = event
}

// ============================================================================
// ARCHIVES
// ============================================================================

function refreshArchives() {
  listArchives()
}

function verifyArchiveIntegrity(archive: ArchiveEntry) {
  verifyArchive(archive.archive_id)
}

function downloadArchive(archive: ArchiveEntry) {
  retrieveArchive(archive.archive_id)
}

function formatTotalSize(): string {
  const total = archives.value.reduce((sum, a) => sum + a.size_bytes, 0)
  return formatBytes(total)
}

// ============================================================================
// FORMATTERS
// ============================================================================

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  const date = new Date(dateStr)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleString()
}

function formatEventType(type: string): string {
  return type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function formatDetails(details: Record<string, any>): string {
  const keys = Object.keys(details)
  if (keys.length === 0) return '-'
  if (keys.length <= 2) {
    return keys.map(k => `${k}: ${details[k]}`).join(', ')
  }
  return `${keys.length} fields - click to view`
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}
</script>

<style scoped>
.admin-tab {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* Access Denied */
.access-denied {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--color-text-muted, #888);
}

.denied-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.access-denied h2 {
  margin: 0 0 0.5rem;
  color: var(--color-text, #fff);
}

.current-role {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: var(--color-background-soft, #2a2a2a);
  border-radius: 4px;
}

/* Admin Content */
.admin-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Section Navigation */
.section-nav {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  background: var(--color-background-soft, #2a2a2a);
  border-bottom: 1px solid var(--color-border, #3e3e3e);
}

.section-btn {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--color-text-muted, #888);
  font-size: 0.875rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}

.section-btn:hover {
  background: var(--color-background, #1e1e1e);
  color: var(--color-text, #fff);
}

.section-btn.active {
  background: var(--color-primary, #007acc);
  color: white;
  border-color: var(--color-primary, #007acc);
}

.section-icon {
  font-size: 1rem;
}

/* Section Panel */
.section-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h3 {
  margin: 0;
  font-size: 1.25rem;
}

.header-actions {
  display: flex;
  gap: 8px;
}

/* Buttons */
.btn-primary {
  padding: 8px 16px;
  background: var(--color-primary, #007acc);
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: var(--color-primary-hover, #0098ff);
}

.btn-secondary {
  padding: 8px 16px;
  background: var(--color-background-soft, #2a2a2a);
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 6px;
  color: var(--color-text, #fff);
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: var(--color-background, #333);
  border-color: var(--color-text-muted, #666);
}

.btn-icon {
  padding: 4px 8px;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.2s;
}

.btn-icon:hover {
  opacity: 1;
}

.btn-icon:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.btn-danger {
  background: #dc3545;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-danger:hover {
  background: #c82333;
}

.btn-cancel {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 6px;
  color: var(--color-text-muted, #888);
  cursor: pointer;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: var(--color-text-muted, #888);
  cursor: pointer;
  line-height: 1;
}

/* Data Tables */
.users-table-wrapper,
.audit-table-wrapper,
.archives-table-wrapper {
  flex: 1;
  overflow: auto;
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 8px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.data-table th {
  position: sticky;
  top: 0;
  background: var(--color-background-soft, #2a2a2a);
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-muted, #888);
  border-bottom: 1px solid var(--color-border, #3e3e3e);
}

.data-table td {
  padding: 12px;
  border-bottom: 1px solid var(--color-border, #3e3e3e);
  color: var(--color-text, #fff);
}

.data-table tr:last-child td {
  border-bottom: none;
}

.data-table tr:hover td {
  background: var(--color-background-soft, #2a2a2a);
}

.loading-row,
.empty-row {
  text-align: center;
  color: var(--color-text-muted, #888);
  font-style: italic;
}

.spinner-small {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-border, #3e3e3e);
  border-top-color: var(--color-primary, #007acc);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 8px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* User Table Specific */
.username-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary, #007acc);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
}

.role-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: capitalize;
}

.role-admin { background: rgba(220, 53, 69, 0.2); color: #ff6b6b; }
.role-engineer { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.role-operator { background: rgba(0, 122, 204, 0.2); color: #6cb8ff; }
.role-viewer { background: rgba(108, 117, 125, 0.2); color: #adb5bd; }

.status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
}

.status-badge.enabled { background: rgba(40, 167, 69, 0.2); color: #4cd964; }
.status-badge.disabled { background: rgba(220, 53, 69, 0.2); color: #ff6b6b; }

/* Audit Filters */
.audit-filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.filter-group label {
  font-size: 0.75rem;
  color: var(--color-text-muted, #888);
}

.filter-group input,
.filter-group select {
  padding: 8px;
  background: var(--color-background-soft, #2a2a2a);
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 4px;
  color: var(--color-text, #fff);
  font-size: 0.875rem;
}

.event-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  white-space: nowrap;
}

.event-login { background: rgba(40, 167, 69, 0.2); color: #4cd964; }
.event-logout { background: rgba(108, 117, 125, 0.2); color: #adb5bd; }
.event-config_change { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.event-recording_start { background: rgba(0, 122, 204, 0.2); color: #6cb8ff; }
.event-recording_stop { background: rgba(0, 122, 204, 0.2); color: #6cb8ff; }
.event-alarm { background: rgba(220, 53, 69, 0.2); color: #ff6b6b; }
.event-user_create,
.event-user_update,
.event-user_delete { background: rgba(128, 0, 128, 0.2); color: #da70d6; }

.details-cell {
  max-width: 200px;
}

.details-preview {
  cursor: pointer;
  color: var(--color-primary, #007acc);
}

.details-preview:hover {
  text-decoration: underline;
}

.checksum-cell code,
.id-cell code {
  font-size: 0.75rem;
  background: var(--color-background-soft, #2a2a2a);
  padding: 2px 6px;
  border-radius: 4px;
}

/* Archive Info Cards */
.archive-info {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.info-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--color-background-soft, #2a2a2a);
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 8px;
  flex: 1;
}

.info-icon {
  font-size: 2rem;
}

.info-content {
  display: flex;
  flex-direction: column;
}

.info-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--color-text, #fff);
}

.info-label {
  font-size: 0.75rem;
  color: var(--color-text-muted, #888);
}

.type-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: rgba(0, 122, 204, 0.2);
  color: #6cb8ff;
}

/* Modal Dialogs */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  backdrop-filter: blur(4px);
}

.modal-dialog {
  background: var(--color-background, #1e1e1e);
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 12px;
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  overflow: auto;
}

.modal-confirm {
  max-width: 400px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border, #3e3e3e);
}

.modal-header h3 {
  margin: 0;
  font-size: 1.125rem;
}

.modal-body {
  padding: 20px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--color-border, #3e3e3e);
}

/* Form Groups */
.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text, #fff);
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 12px;
  background: var(--color-background-soft, #2a2a2a);
  border: 1px solid var(--color-border, #3e3e3e);
  border-radius: 6px;
  color: var(--color-text, #fff);
  font-size: 0.875rem;
  box-sizing: border-box;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--color-primary, #007acc);
}

.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-group input[type="checkbox"] {
  width: auto;
}

/* Event Details */
.event-details {
  font-size: 0.875rem;
}

.detail-row {
  display: flex;
  margin-bottom: 12px;
  align-items: flex-start;
}

.detail-label {
  width: 100px;
  flex-shrink: 0;
  color: var(--color-text-muted, #888);
}

.detail-section {
  margin-top: 16px;
}

.detail-section .detail-label {
  display: block;
  margin-bottom: 8px;
}

.full-checksum {
  font-size: 0.7rem;
  word-break: break-all;
}

.details-json {
  background: var(--color-background-soft, #2a2a2a);
  padding: 12px;
  border-radius: 6px;
  overflow: auto;
  max-height: 200px;
  font-size: 0.75rem;
  margin: 0;
}

/* Confirm Dialog */
.confirm-message {
  margin: 0 0 8px;
}

.confirm-warning {
  margin: 0;
  color: #ff6b6b;
  font-size: 0.875rem;
}
</style>
