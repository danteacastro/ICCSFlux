import { ref, computed, readonly } from 'vue'
import { useMqtt } from './useMqtt'

// ============================================================================
// TYPES
// ============================================================================

export interface AuthUser {
  username: string
  role: string
  displayName: string | null
  permissions: string[]
}

export interface AuthStatus {
  authenticated: boolean
  username: string | null
  role: string | null
  permissions: string[]
  displayName: string | null
  error?: string
  timestamp: string
}

export interface User {
  username: string
  display_name: string
  email: string
  role: string
  enabled: boolean
  created_at: string
  last_login: string
}

export interface AuditEvent {
  event_id: string
  event_type: string
  timestamp: string
  username: string | null
  details: Record<string, any>
  checksum: string
}

export interface ArchiveEntry {
  archive_id: string
  original_filename: string
  content_type: string
  archived_at: string
  size_bytes: number
  compressed: boolean
  checksum: string
}

// ============================================================================
// SINGLETON STATE - Shared across all useAuth() calls
// ============================================================================

const authenticated = ref(false)
const currentUser = ref<AuthUser | null>(null)
const authError = ref<string | null>(null)
const isLoggingIn = ref(false)

// User management state
const users = ref<User[]>([])
const isLoadingUsers = ref(false)

// Audit trail state
const auditEvents = ref<AuditEvent[]>([])
const isLoadingAudit = ref(false)

// Archive state
const archives = ref<ArchiveEntry[]>([])
const isLoadingArchives = ref(false)

// Callbacks
const authCallbacks: ((status: AuthStatus) => void)[] = []
let handlersInitialized = false

// ============================================================================
// PERMISSION HELPERS
// ============================================================================

const hasPermission = (permission: string): boolean => {
  if (!currentUser.value) return false
  return currentUser.value.permissions.includes(permission)
}

const isAdmin = computed(() => currentUser.value?.role === 'admin')
const isSupervisor = computed(() => ['admin', 'supervisor'].includes(currentUser.value?.role || ''))
const isOperator = computed(() => ['admin', 'supervisor', 'operator'].includes(currentUser.value?.role || ''))

// ============================================================================
// COMPOSABLE
// ============================================================================

export function useAuth() {
  const mqtt = useMqtt()

  // Initialize MQTT handlers once
  if (!handlersInitialized && mqtt.client.value) {
    initializeHandlers()
  }

  function initializeHandlers() {
    if (handlersInitialized) return
    handlersInitialized = true

    const client = mqtt.client.value
    if (!client) return

    const prefix = 'nisystem'

    // Subscribe to auth topics
    client.subscribe(`${prefix}/auth/status`)
    client.subscribe(`${prefix}/users/+/response`)
    client.subscribe(`${prefix}/audit/+/response`)
    client.subscribe(`${prefix}/archive/+/response`)

    // Handle auth status updates
    client.on('message', (topic: string, payload: Buffer) => {
      try {
        const data = JSON.parse(payload.toString())

        if (topic === `${prefix}/auth/status`) {
          handleAuthStatus(data)
        } else if (topic === `${prefix}/users/list/response`) {
          handleUsersListResponse(data)
        } else if (topic === `${prefix}/users/create/response` ||
                   topic === `${prefix}/users/update/response` ||
                   topic === `${prefix}/users/delete/response`) {
          handleUserMutationResponse(data)
        } else if (topic === `${prefix}/audit/query/response`) {
          handleAuditQueryResponse(data)
        } else if (topic === `${prefix}/archive/list/response`) {
          handleArchiveListResponse(data)
        } else if (topic === `${prefix}/archive/verify/response`) {
          handleArchiveVerifyResponse(data)
        }
      } catch (e) {
        console.error('Error parsing auth message:', e)
      }
    })
  }

  function handleAuthStatus(data: AuthStatus) {
    authenticated.value = data.authenticated
    authError.value = data.error || null
    isLoggingIn.value = false

    if (data.authenticated && data.username) {
      currentUser.value = {
        username: data.username,
        role: data.role || 'viewer',
        displayName: data.displayName,
        permissions: data.permissions || []
      }
    } else {
      currentUser.value = null
    }

    // Notify callbacks
    authCallbacks.forEach(cb => cb(data))
  }

  function handleUsersListResponse(data: { success: boolean; users?: User[]; error?: string }) {
    isLoadingUsers.value = false
    if (data.success && data.users) {
      users.value = data.users
    }
  }

  function handleUserMutationResponse(data: { success: boolean; message?: string; error?: string }) {
    // Refresh user list after mutation
    if (data.success) {
      listUsers()
    }
  }

  function handleAuditQueryResponse(data: { success: boolean; events?: AuditEvent[]; error?: string }) {
    isLoadingAudit.value = false
    if (data.success && data.events) {
      auditEvents.value = data.events
    }
  }

  function handleArchiveListResponse(data: { success: boolean; archives?: ArchiveEntry[]; error?: string }) {
    isLoadingArchives.value = false
    if (data.success && data.archives) {
      archives.value = data.archives
    }
  }

  function handleArchiveVerifyResponse(data: { success: boolean; archive_id?: string; is_valid?: boolean; message?: string }) {
    // Could emit an event or update specific archive entry
    console.log('Archive verify result:', data)
  }

  // ============================================================================
  // AUTH ACTIONS
  // ============================================================================

  async function login(username: string, password: string): Promise<boolean> {
    const client = mqtt.client.value
    if (!client || !mqtt.connected.value) {
      authError.value = 'Not connected to server'
      return false
    }

    isLoggingIn.value = true
    authError.value = null

    client.publish('nisystem/auth/login', JSON.stringify({
      username,
      password,
      source_ip: 'dashboard'
    }))

    // Wait for response (with timeout)
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        isLoggingIn.value = false
        authError.value = 'Login timeout'
        resolve(false)
      }, 10000)

      const unsubscribe = onAuthChange((status) => {
        clearTimeout(timeout)
        unsubscribe()
        resolve(status.authenticated)
      })
    })
  }

  function logout() {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/auth/logout', JSON.stringify({}))
    authenticated.value = false
    currentUser.value = null
  }

  function requestAuthStatus() {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/auth/status/request', JSON.stringify({}))
  }

  // ============================================================================
  // USER MANAGEMENT ACTIONS
  // ============================================================================

  function listUsers() {
    const client = mqtt.client.value
    if (!client) return

    isLoadingUsers.value = true
    client.publish('nisystem/users/list', JSON.stringify({}))
  }

  function createUser(user: { username: string; password: string; role: string; display_name?: string; email?: string }) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/users/create', JSON.stringify(user))
  }

  function updateUser(username: string, updates: { password?: string; role?: string; display_name?: string; email?: string; enabled?: boolean }) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/users/update', JSON.stringify({ username, ...updates }))
  }

  function deleteUser(username: string) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/users/delete', JSON.stringify({ username }))
  }

  // ============================================================================
  // AUDIT TRAIL ACTIONS
  // ============================================================================

  function queryAuditEvents(options: {
    start_time?: string
    end_time?: string
    event_types?: string[]
    username?: string
    limit?: number
  } = {}) {
    const client = mqtt.client.value
    if (!client) return

    isLoadingAudit.value = true
    client.publish('nisystem/audit/query', JSON.stringify(options))
  }

  function exportAuditEvents(options: {
    format?: 'json' | 'csv'
    start_time?: string
    end_time?: string
  } = {}) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/audit/export', JSON.stringify(options))
  }

  // ============================================================================
  // ARCHIVE ACTIONS
  // ============================================================================

  function listArchives(options: {
    content_type?: string
    start_date?: string
    end_date?: string
    limit?: number
  } = {}) {
    const client = mqtt.client.value
    if (!client) return

    isLoadingArchives.value = true
    client.publish('nisystem/archive/list', JSON.stringify(options))
  }

  function verifyArchive(archiveId: string) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/archive/verify', JSON.stringify({ archive_id: archiveId }))
  }

  function retrieveArchive(archiveId: string) {
    const client = mqtt.client.value
    if (!client) return

    client.publish('nisystem/archive/retrieve', JSON.stringify({ archive_id: archiveId }))
  }

  // ============================================================================
  // CALLBACKS
  // ============================================================================

  function onAuthChange(callback: (status: AuthStatus) => void): () => void {
    authCallbacks.push(callback)
    return () => {
      const index = authCallbacks.indexOf(callback)
      if (index > -1) authCallbacks.splice(index, 1)
    }
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  // Re-initialize handlers when MQTT connects
  if (mqtt.connected.value && !handlersInitialized) {
    initializeHandlers()
  }

  return {
    // State (readonly)
    authenticated: readonly(authenticated),
    currentUser: readonly(currentUser),
    authError: readonly(authError),
    isLoggingIn: readonly(isLoggingIn),

    // User management
    users: readonly(users),
    isLoadingUsers: readonly(isLoadingUsers),

    // Audit trail
    auditEvents: readonly(auditEvents),
    isLoadingAudit: readonly(isLoadingAudit),

    // Archives
    archives: readonly(archives),
    isLoadingArchives: readonly(isLoadingArchives),

    // Computed permissions
    isAdmin,
    isSupervisor,
    isOperator,
    hasPermission,

    // Auth actions
    login,
    logout,
    requestAuthStatus,
    onAuthChange,

    // User management actions
    listUsers,
    createUser,
    updateUser,
    deleteUser,

    // Audit actions
    queryAuditEvents,
    exportAuditEvents,

    // Archive actions
    listArchives,
    verifyArchive,
    retrieveArchive
  }
}
