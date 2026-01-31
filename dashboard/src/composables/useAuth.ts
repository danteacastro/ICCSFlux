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

// Default guest user - available without login (read-only)
const DEFAULT_GUEST: AuthUser = {
  username: 'guest',
  role: 'guest',
  displayName: 'Guest',
  permissions: ['view.data', 'view.alarms']
}

const AUTH_STORAGE_KEY = 'nisystem-auth-session'

// Try to restore persisted session from localStorage
function loadPersistedSession(): AuthUser | null {
  try {
    const saved = localStorage.getItem(AUTH_STORAGE_KEY)
    if (saved) {
      const session = JSON.parse(saved)
      // Restore any authenticated session (not guest)
      if (session.role && session.role !== 'guest') {
        console.log('[AUTH] Restored persisted session:', session.username, session.role)
        return session
      }
    }
  } catch (e) {
    console.warn('[AUTH] Failed to load persisted session:', e)
  }
  return null
}

function saveSession(user: AuthUser | null) {
  try {
    if (user && user.role !== 'guest') {
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user))
      console.log('[AUTH] Persisted session:', user.username, user.role)
    } else {
      localStorage.removeItem(AUTH_STORAGE_KEY)
    }
  } catch (e) {
    console.warn('[AUTH] Failed to save session:', e)
  }
}

// Initialize with persisted session or default guest
const persistedSession = loadPersistedSession()
const authenticated = ref(persistedSession !== null)
const currentUser = ref<AuthUser | null>(persistedSession || DEFAULT_GUEST)
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

/**
 * Check if current user has a specific permission.
 *
 * WARNING: This is a FUNCTION, not a computed ref. Calling it inside a Vue
 * computed() will NOT create a reactive dependency! Vue cannot track that
 * this function reads currentUser.value internally.
 *
 * For reactive permission checks in computed properties, use the role-based
 * computed refs instead: isAdmin, isSupervisor, isOperator, isGuest
 *
 * Example:
 *   BAD:  computed(() => auth.hasPermission('foo') || auth.isOperator.value)
 *   GOOD: computed(() => auth.isOperator.value)
 */
const hasPermission = (permission: string): boolean => {
  if (!currentUser.value) return false
  // Admin role has all permissions (bypass explicit permission check)
  if (currentUser.value.role === 'admin') return true
  return currentUser.value.permissions.includes(permission)
}

// Role hierarchy: admin > supervisor > operator > guest
// USE THESE in computed() for proper reactivity!
const isAdmin = computed(() => currentUser.value?.role === 'admin')
const isSupervisor = computed(() => ['admin', 'supervisor'].includes(currentUser.value?.role || ''))
const isOperator = computed(() => ['admin', 'supervisor', 'operator'].includes(currentUser.value?.role || ''))
const isGuest = computed(() => currentUser.value?.role === 'guest')

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

    // Request current auth status from backend on boot
    // This restores session state if user was previously logged in
    setTimeout(() => {
      if (mqtt.connected.value) {
        mqtt.sendLocalCommand('auth/status/request', {})
        console.log('[AUTH] Requested auth status on boot')
      }
    }, 500)  // Small delay to ensure subscriptions are ready
  }

  function handleAuthStatus(data: AuthStatus) {
    authenticated.value = data.authenticated
    authError.value = data.error || null
    isLoggingIn.value = false

    if (data.authenticated && data.username) {
      const user: AuthUser = {
        username: data.username,
        role: data.role || 'guest',
        displayName: data.displayName,
        permissions: data.permissions || []
      }
      currentUser.value = user
      // Persist authenticated sessions
      saveSession(user)
    } else {
      // Login failed or logout - reset to guest
      currentUser.value = DEFAULT_GUEST
      saveSession(null)
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

    // Auth is always handled by the local DAQ service (node-001), not remote cRIO nodes
    mqtt.sendLocalCommand('auth/login', {
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

    mqtt.sendLocalCommand('auth/logout', {})
    authenticated.value = false
    currentUser.value = DEFAULT_GUEST
    saveSession(null)  // Clear persisted session
  }

  function requestAuthStatus() {
    if (!mqtt.connected.value) return

    mqtt.sendLocalCommand('auth/status/request', {})
  }

  // ============================================================================
  // USER MANAGEMENT ACTIONS
  // ============================================================================

  function listUsers() {
    if (!mqtt.connected.value) return

    isLoadingUsers.value = true
    mqtt.sendLocalCommand('users/list', {})
  }

  function createUser(user: { username: string; password: string; role: string; display_name?: string; email?: string }) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/create', user, 'node-001')
  }

  function updateUser(username: string, updates: { password?: string; role?: string; display_name?: string; email?: string; enabled?: boolean }) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/update', { username, ...updates }, 'node-001')
  }

  function deleteUser(username: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('users/delete', { username }, 'node-001')
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
    mqtt.sendNodeCommand('audit/query', options, 'node-001')
  }

  function exportAuditEvents(options: {
    format?: 'json' | 'csv'
    start_time?: string
    end_time?: string
  } = {}) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('audit/export', options, 'node-001')
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
    mqtt.sendNodeCommand('archive/list', options, 'node-001')
  }

  function verifyArchive(archiveId: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('archive/verify', { archive_id: archiveId }, 'node-001')
  }

  function retrieveArchive(archiveId: string) {
    if (!mqtt.connected.value) return

    mqtt.sendNodeCommand('archive/retrieve', { archive_id: archiveId }, 'node-001')
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

    // Computed role checks (hierarchical)
    isAdmin,
    isSupervisor,
    isOperator,
    isGuest,
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
