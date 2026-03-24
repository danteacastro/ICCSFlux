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
  session_state?: 'active' | 'locked'
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

const AUTH_STORAGE_KEY = 'nisystem-auth-session'

// Maximum age for persisted sessions (24 hours)
const SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000

// Idle timeout DISABLED — users must explicitly log out.
// Sessions persist across browser reloads (24h expiry).

interface PersistedSession extends AuthUser {
  _persistedAt: number
}

// Local credential cache — enables login when MQTT is unreachable
const CREDENTIAL_CACHE_KEY = 'nisystem-auth-credentials'

interface CachedCredential {
  username: string
  passwordHash: string  // SHA-256 hex
  user: AuthUser
  cachedAt: number
}

async function hashPassword(password: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(password)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

function saveCachedCredentials(username: string, passwordHash: string, user: AuthUser) {
  try {
    const existing = loadAllCachedCredentials()
    existing[username] = { username, passwordHash, user, cachedAt: Date.now() }
    localStorage.setItem(CREDENTIAL_CACHE_KEY, JSON.stringify(existing))
  } catch (e) {
    console.warn('[AUTH] Failed to cache credentials:', e)
  }
}

function loadAllCachedCredentials(): Record<string, CachedCredential> {
  try {
    const saved = localStorage.getItem(CREDENTIAL_CACHE_KEY)
    if (saved) return JSON.parse(saved)
  } catch (e) {
    console.warn('[AUTH] Failed to load cached credentials:', e)
  }
  return {}
}

// Try to restore persisted session from localStorage
function loadPersistedSession(): AuthUser | null {
  try {
    const saved = localStorage.getItem(AUTH_STORAGE_KEY)
    if (saved) {
      const session: PersistedSession = JSON.parse(saved)
      // Restore any authenticated session (not guest)
      if (session.role && session.role !== 'guest') {
        // Check if the session has expired
        if (session._persistedAt && (Date.now() - session._persistedAt) > SESSION_MAX_AGE_MS) {
          console.warn('[AUTH] Persisted session expired, discarding')
          localStorage.removeItem(AUTH_STORAGE_KEY)
          return null
        }
        console.log('[AUTH] Restored persisted session:', session.username, session.role)
        // Return without the internal _persistedAt field
        const { _persistedAt, ...user } = session
        return user
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
      const persisted: PersistedSession = { ...user, _persistedAt: Date.now() }
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(persisted))
      console.log('[AUTH] Persisted session:', user.username, user.role)
    } else {
      localStorage.removeItem(AUTH_STORAGE_KEY)
    }
  } catch (e) {
    console.warn('[AUTH] Failed to save session:', e)
  }
}

// Runtime window.ICCSFLUX_DEMO_MODE is NOT checked — prevents console bypass in production.
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'
const DEMO_ADMIN: AuthUser = {
  username: 'demo',
  role: 'admin',
  displayName: 'Demo',
  permissions: [],
}

// Default guest user — used when guest_access_enabled is true and no one is logged in
const DEFAULT_GUEST: AuthUser = {
  username: 'guest',
  role: 'guest',
  displayName: 'Guest',
  permissions: [],
}

// Security settings — read from localStorage (written by AdminTab Security section)
const SECURITY_SETTINGS_KEY = 'nisystem-security-settings'

function loadSecuritySetting<T>(key: string, defaultValue: T): T {
  try {
    const saved = localStorage.getItem(SECURITY_SETTINGS_KEY)
    if (saved) {
      const settings = JSON.parse(saved)
      if (key in settings) return settings[key] as T
    }
  } catch { /* ignore */ }
  return defaultValue
}

// Guest access: OFF by default — users must log in (NIST AC.L2-3.1.22)
const guestAccessEnabled = ref(loadSecuritySetting('guest_access_enabled', false))

// Session lock: OFF by default
// When ON (NIST AC.L2-3.1.10), UI locks after inactivity timeout
const sessionLockEnabled = ref(loadSecuritySetting('session_lock_enabled', false))

// Session lock state
// LOCKED = UI commands disabled, data still streams. User must re-enter password.
// Backend processes (acquisition, recording, scripts, safety) are NEVER affected.
const sessionState = ref<'active' | 'locked'>('active')
const sessionLockWarning = ref(false)  // True when warning threshold reached

// Idle tracking — reset on any user interaction
let sessionLockTimeoutMs = loadSecuritySetting('session_lock_timeout_minutes', 30) * 60 * 1000
let sessionLockWarningMs = loadSecuritySetting('session_lock_warning_minutes', 25) * 60 * 1000
let lastActivityTime = Date.now()
let idleCheckInterval: ReturnType<typeof setInterval> | null = null

function resetIdleTimer() {
  lastActivityTime = Date.now()
  sessionLockWarning.value = false
}

/** Reload security settings from localStorage (called when AdminTab saves changes) */
function reloadSecuritySettings() {
  guestAccessEnabled.value = loadSecuritySetting('guest_access_enabled', false)
  sessionLockEnabled.value = loadSecuritySetting('session_lock_enabled', false)
  sessionLockTimeoutMs = loadSecuritySetting('session_lock_timeout_minutes', 30) * 60 * 1000
  sessionLockWarningMs = loadSecuritySetting('session_lock_warning_minutes', 25) * 60 * 1000

  // If guest access was just enabled and no one is logged in, restore guest
  if (guestAccessEnabled.value && !currentUser.value) {
    currentUser.value = DEFAULT_GUEST
    authenticated.value = true
  }
  // If guest access was just disabled and current user is guest, force login
  if (!guestAccessEnabled.value && currentUser.value?.role === 'guest') {
    currentUser.value = null
    authenticated.value = false
  }
}

// Initialize: demo mode → admin, persisted session → restored, guest enabled → guest, else null
function resolveInitialUser(): AuthUser | null {
  if (DEMO_MODE) return DEMO_ADMIN
  const persisted = loadPersistedSession()
  if (persisted) return persisted
  if (guestAccessEnabled.value) return DEFAULT_GUEST
  return null
}

const initialUser = resolveInitialUser()
const authenticated = ref(initialUser !== null)
const currentUser = ref<AuthUser | null>(initialUser)
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
 * Reads currentUser.value internally, so IS reactive inside computed() / templates.
 * For role-based checks, prefer the computed refs: isAdmin, isSupervisor, isOperator.
 */
const hasPermission = (permission: string): boolean => {
  if (!currentUser.value) return false
  if (currentUser.value.role === 'admin') return true
  return currentUser.value.permissions.includes(permission)
}

/**
 * Reactive computed wrapper for permission checks.
 * Returns a ComputedRef<boolean> that auto-updates when user/role changes.
 *
 * Usage: const canEdit = auth.canDo('edit.config')  // canEdit.value is reactive
 */
const canDo = (permission: string) => computed(() => hasPermission(permission))

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

    // Track session lock state from backend
    if (data.session_state) {
      sessionState.value = data.session_state
      if (data.session_state === 'active') {
        sessionLockWarning.value = false
        resetIdleTimer()
      }
    }

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
      // Login failed or logout — fall back to guest if enabled, otherwise no access
      if (guestAccessEnabled.value) {
        currentUser.value = DEFAULT_GUEST
        authenticated.value = true
      } else {
        currentUser.value = null
      }
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
    isLoggingIn.value = true
    authError.value = null

    // If MQTT is available, authenticate via backend (primary path)
    if (mqtt.connected.value) {
      mqtt.sendLocalCommand('auth/login', {
        username,
        password,
        source_ip: 'dashboard'
      })

      // Wait for response (with timeout)
      const pwHash = await hashPassword(password)
      return new Promise((resolve) => {
        const unsubscribe = onAuthChange((status) => {
          clearTimeout(timeout)
          unsubscribe()
          isLoggingIn.value = false
          if (status.authenticated && currentUser.value) {
            // Cache credentials for offline login
            saveCachedCredentials(username, pwHash, currentUser.value)
          }
          resolve(status.authenticated)
        })

        const timeout = setTimeout(() => {
          unsubscribe()
          isLoggingIn.value = false
          authError.value = 'Login timed out — server may be unreachable'
          resolve(false)
        }, 10000)
      })
    }

    // MQTT unavailable — fall back to cached credentials (offline login)
    const pwHash = await hashPassword(password)
    const cached = loadAllCachedCredentials()
    const entry = cached[username]

    if (entry && entry.passwordHash === pwHash) {
      console.log('[AUTH] Offline login via cached credentials:', username)
      authenticated.value = true
      currentUser.value = entry.user
      saveSession(entry.user)
      isLoggingIn.value = false
      return true
    }

    isLoggingIn.value = false
    if (entry) {
      authError.value = 'Incorrect password (offline mode)'
    } else {
      authError.value = 'Server unreachable — no cached credentials for this user. Connect to server for first login.'
    }
    return false
  }

  function logout() {
    // Notify backend if connected (best-effort)
    if (mqtt.connected.value) {
      mqtt.sendLocalCommand('auth/logout', {})
    }
    sessionState.value = 'active'
    sessionLockWarning.value = false
    saveSession(null)  // Clear persisted session

    // Fall back to guest if enabled, otherwise no access
    if (guestAccessEnabled.value) {
      currentUser.value = DEFAULT_GUEST
      authenticated.value = true
    } else {
      currentUser.value = null
      authenticated.value = false
    }
  }

  /**
   * Unlock a locked session by re-entering password.
   * Same session preserved — no backend process interruption.
   */
  async function unlockSession(password: string): Promise<boolean> {
    if (!mqtt.connected.value) {
      authError.value = 'Cannot unlock — server unreachable'
      return false
    }

    authError.value = null
    mqtt.sendLocalCommand('auth/unlock', { password })

    return new Promise((resolve) => {
      const unsubscribe = onAuthChange((status) => {
        clearTimeout(timeout)
        unsubscribe()
        if (status.session_state === 'active' && status.authenticated) {
          sessionState.value = 'active'
          resetIdleTimer()
          resolve(true)
        } else {
          resolve(false)
        }
      })

      const timeout = setTimeout(() => {
        unsubscribe()
        authError.value = 'Unlock timed out'
        resolve(false)
      }, 10000)
    })
  }

  // Sync auth state to useMqtt (gates permission-sensitive commands like safe-state)
  watch(authenticated, (isAuth) => {
    mqtt.setUserAuthenticated(isAuth)
  }, { immediate: true })

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

  // Idle activity tracking — reset timer on user interaction
  // Only tracks locally for the warning toast; actual lock is server-side.
  if (typeof window !== 'undefined' && !idleCheckInterval) {
    const activityEvents = ['mousedown', 'keydown', 'touchstart', 'scroll']
    for (const evt of activityEvents) {
      window.addEventListener(evt, resetIdleTimer, { passive: true })
    }

    // Check idle state every 30 seconds (only when session lock is enabled)
    idleCheckInterval = setInterval(() => {
      if (!sessionLockEnabled.value) return
      if (!authenticated.value || currentUser.value?.role === 'guest') return

      const idle = Date.now() - lastActivityTime
      if (idle >= sessionLockWarningMs && idle < sessionLockTimeoutMs) {
        sessionLockWarning.value = true
      }
    }, 30000)
  }

  const isSessionLocked = computed(() => sessionState.value === 'locked')

  return {
    // State (readonly)
    authenticated: readonly(authenticated),
    currentUser: readonly(currentUser),
    authError: readonly(authError),
    isLoggingIn: readonly(isLoggingIn),

    sessionState: readonly(sessionState),
    isSessionLocked,
    sessionLockWarning: readonly(sessionLockWarning),

    // Security settings
    guestAccessEnabled: readonly(guestAccessEnabled),
    sessionLockEnabled: readonly(sessionLockEnabled),
    reloadSecuritySettings,

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
    canDo,

    // Auth actions
    login,
    logout,
    unlockSession,
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
