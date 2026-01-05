import { ref, computed, readonly, watch } from 'vue'
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
const isEngineer = computed(() => ['admin', 'engineer'].includes(currentUser.value?.role || ''))
const isOperator = computed(() => ['admin', 'engineer', 'operator'].includes(currentUser.value?.role || ''))

// ============================================================================
// COMPOSABLE
// ============================================================================

export function useAuth() {
  const mqtt = useMqtt()

  // Initialize MQTT handlers once when connected
  if (!handlersInitialized && mqtt.connected.value) {
    initializeHandlers()
  }

  // Watch for MQTT connection to initialize handlers if not already done
  watch(() => mqtt.connected.value, (connected) => {
    if (connected && !handlersInitialized) {
      initializeHandlers()
    }
  }, { immediate: true })

  function initializeHandlers() {
    if (handlersInitialized) return
    handlersInitialized = true

    // NOTE: Backend uses node-prefixed topics: nisystem/nodes/{node_id}/auth/...
    // We use wildcard (+) to receive from any node
    const nodePrefix = 'nisystem/nodes/+'

    // Subscribe to auth topics using the public subscribe API
    mqtt.subscribe(`${nodePrefix}/auth/status`, handleAuthStatus)
    mqtt.subscribe(`${nodePrefix}/users/list/response`, handleUsersListResponse)
    mqtt.subscribe(`${nodePrefix}/users/create/response`, handleUserMutationResponse)
    mqtt.subscribe(`${nodePrefix}/users/update/response`, handleUserMutationResponse)
    mqtt.subscribe(`${nodePrefix}/users/delete/response`, handleUserMutationResponse)
    mqtt.subscribe(`${nodePrefix}/audit/query/response`, handleAuditQueryResponse)
    mqtt.subscribe(`${nodePrefix}/archive/list/response`, handleArchiveListResponse)
    mqtt.subscribe(`${nodePrefix}/archive/verify/response`, handleArchiveVerifyResponse)
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
    if (!mqtt.connected.value) {
      authError.value = 'Not connected to server'
      return false
    }

    isLoggingIn.value = true
    authError.value = null

    mqtt.sendNodeCommand('auth/login', {
      username,
      password,
      source_ip: 'dashboard'
    })

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
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('auth/logout', {})
    authenticated.value = false
    currentUser.value = null
  }

  function requestAuthStatus() {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('auth/status/request', {})
  }

  // ============================================================================
  // USER MANAGEMENT ACTIONS
  // ============================================================================

  function listUsers() {
    if (!mqtt.connected.value) return

    isLoadingUsers.value = true
    mqtt.sendNodeCommand('users/list', {})
  }

  function createUser(user: { username: string; password: string; role: string; display_name?: string; email?: string }) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/create', user)
  }

  function updateUser(username: string, updates: { password?: string; role?: string; display_name?: string; email?: string; enabled?: boolean }) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/update', { username, ...updates })
  }

  function deleteUser(username: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/delete', { username })
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
    if (!mqtt.connected.value) return

    isLoadingAudit.value = true
    mqtt.sendNodeCommand('audit/query', options)
  }

  function exportAuditEvents(options: {
    format?: 'json' | 'csv'
    start_time?: string
    end_time?: string
  } = {}) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('audit/export', options)
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
    if (!mqtt.connected.value) return

    isLoadingArchives.value = true
    mqtt.sendNodeCommand('archive/list', options)
  }

  function verifyArchive(archiveId: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('archive/verify', { archive_id: archiveId })
  }

  function retrieveArchive(archiveId: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('archive/retrieve', { archive_id: archiveId })
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
    isEngineer,
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
