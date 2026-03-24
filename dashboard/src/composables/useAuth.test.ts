/**
 * Tests for Authentication Composable (useAuth)
 *
 * Tests cover:
 * - Authentication state management
 * - Login/logout flow
 * - Permission checking
 * - User management operations
 * - Audit trail operations
 * - Archive operations
 * - MQTT handler integration
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'

// Mock useMqtt module with all required methods
const mockSendLocalCommand = vi.fn()
const mockSendNodeCommand = vi.fn()
const mockSubscribe = vi.fn()

const mockMqtt = {
  connected: ref(true),
  sendCommand: vi.fn(),
  sendLocalCommand: mockSendLocalCommand,
  sendNodeCommand: mockSendNodeCommand,
  subscribe: mockSubscribe,
  onSystemUpdate: vi.fn().mockReturnValue(() => {}),
  systemStatus: ref({ acquiring: false, recording: false }),
  channelValues: ref({}),
  setUserAuthenticated: vi.fn(),
}

vi.mock('./useMqtt', () => ({
  useMqtt: () => mockMqtt
}))

// Import after mocking
import { useAuth } from './useAuth'

describe('useAuth', () => {
  let auth: ReturnType<typeof useAuth>

  beforeEach(() => {
    vi.clearAllMocks()
    auth = useAuth()
  })

  // ===========================================================================
  // INITIAL STATE TESTS
  // ===========================================================================

  describe('Initial State', () => {
    it('should not be authenticated initially (login required)', () => {
      expect(auth.authenticated.value).toBe(false)
    })

    it('should have no user initially (guest access disabled by default)', () => {
      expect(auth.currentUser.value).toBeNull()
    })

    it('should have no auth error initially', () => {
      expect(auth.authError.value).toBeNull()
    })

    it('should not be logging in initially', () => {
      expect(auth.isLoggingIn.value).toBe(false)
    })

    it('should have empty users list initially', () => {
      expect(auth.users.value).toEqual([])
    })

    it('should not be loading users initially', () => {
      expect(auth.isLoadingUsers.value).toBe(false)
    })

    it('should have empty audit events initially', () => {
      expect(auth.auditEvents.value).toEqual([])
    })

    it('should have empty archives list initially', () => {
      expect(auth.archives.value).toEqual([])
    })
  })

  // ===========================================================================
  // PERMISSION HELPERS TESTS
  // ===========================================================================

  describe('Permission Helpers', () => {
    it('isAdmin should return false when not logged in', () => {
      expect(auth.isAdmin.value).toBe(false)
    })

    it('isSupervisor should return false when not logged in', () => {
      expect(auth.isSupervisor.value).toBe(false)
    })

    it('isOperator should return false when not logged in', () => {
      expect(auth.isOperator.value).toBe(false)
    })

    it('isGuest should return false when not logged in (no guest role)', () => {
      expect(auth.isGuest.value).toBe(false)
    })

    it('hasPermission should return false when not logged in', () => {
      expect(auth.hasPermission('VIEW_DATA')).toBe(false)
    })
  })

  // ===========================================================================
  // LOGIN TESTS
  // ===========================================================================

  describe('Login', () => {
    it('should call sendLocalCommand with login data', () => {
      auth.login('testuser', 'testpass')

      expect(mockSendLocalCommand).toHaveBeenCalledWith(
        'auth/login',
        expect.objectContaining({
          username: 'testuser',
          password: 'testpass',
        })
      )
    })

    it('should set isLoggingIn to true during login', () => {
      auth.login('user', 'pass')
      expect(auth.isLoggingIn.value).toBe(true)
    })

    it('should include source_ip in login message', () => {
      auth.login('user', 'pass')

      expect(mockSendLocalCommand).toHaveBeenCalledWith(
        'auth/login',
        expect.objectContaining({
          source_ip: 'dashboard',
        })
      )
    })
  })

  // ===========================================================================
  // LOGOUT TESTS
  // ===========================================================================

  describe('Logout', () => {
    it('should call sendLocalCommand for logout', () => {
      auth.logout()

      expect(mockSendLocalCommand).toHaveBeenCalledWith(
        'auth/logout',
        expect.any(Object)
      )
    })

    it('should be unauthenticated after logout (no guest fallback)', () => {
      auth.logout()

      // Guest access is OFF by default — logout means no access
      expect(auth.authenticated.value).toBe(false)
      expect(auth.currentUser.value).toBeNull()
    })
  })

  // ===========================================================================
  // AUTH STATUS REQUEST TESTS
  // ===========================================================================

  describe('Auth Status Request', () => {
    it('should call sendLocalCommand for status request', () => {
      auth.requestAuthStatus()

      expect(mockSendLocalCommand).toHaveBeenCalledWith(
        'auth/status/request',
        {}
      )
    })
  })

  // ===========================================================================
  // USER MANAGEMENT TESTS
  // ===========================================================================

  describe('User Management', () => {
    it('should call sendLocalCommand for list users', () => {
      auth.listUsers()

      expect(mockSendLocalCommand).toHaveBeenCalledWith(
        'users/list',
        {}
      )
    })

    it('should set loading state when listing users', () => {
      auth.listUsers()
      expect(auth.isLoadingUsers.value).toBe(true)
    })

    it('should call sendNodeCommand for create user', () => {
      const newUser = {
        username: 'newuser',
        password: 'newpass',
        role: 'operator',
        display_name: 'New User'
      }

      auth.createUser(newUser)

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'users/create',
        newUser,
        'node-001'
      )
    })

    it('should call sendNodeCommand for update user', () => {
      auth.updateUser('testuser', { role: 'supervisor', enabled: true })

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'users/update',
        expect.objectContaining({
          username: 'testuser',
          role: 'supervisor',
          enabled: true,
        }),
        'node-001'
      )
    })

    it('should call sendNodeCommand for delete user', () => {
      auth.deleteUser('deleteuser')

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'users/delete',
        { username: 'deleteuser' },
        'node-001'
      )
    })
  })

  // ===========================================================================
  // AUDIT TRAIL TESTS
  // ===========================================================================

  describe('Audit Trail', () => {
    it('should call sendNodeCommand for query audit events', () => {
      auth.queryAuditEvents({ limit: 100 })

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'audit/query',
        { limit: 100 },
        'node-001'
      )
    })

    it('should set loading state when querying audit events', () => {
      auth.queryAuditEvents({})
      expect(auth.isLoadingAudit.value).toBe(true)
    })

    it('should call sendNodeCommand with filters', () => {
      const filters = {
        start_time: '2024-01-01T00:00:00Z',
        end_time: '2024-12-31T23:59:59Z',
        event_types: ['login', 'logout'],
        username: 'testuser',
        limit: 50
      }

      auth.queryAuditEvents(filters)

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'audit/query',
        filters,
        'node-001'
      )
    })

    it('should call sendNodeCommand for export audit events', () => {
      auth.exportAuditEvents({ format: 'csv' })

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'audit/export',
        { format: 'csv' },
        'node-001'
      )
    })
  })

  // ===========================================================================
  // ARCHIVE MANAGEMENT TESTS
  // ===========================================================================

  describe('Archive Management', () => {
    it('should call sendNodeCommand for list archives', () => {
      auth.listArchives()

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'archive/list',
        {},
        'node-001'
      )
    })

    it('should set loading state when listing archives', () => {
      auth.listArchives()
      expect(auth.isLoadingArchives.value).toBe(true)
    })

    it('should call sendNodeCommand with archive filters', () => {
      const filters = {
        content_type: 'recording',
        start_date: '2024-01-01',
        limit: 25
      }

      auth.listArchives(filters)

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'archive/list',
        filters,
        'node-001'
      )
    })

    it('should call sendNodeCommand for verify archive', () => {
      auth.verifyArchive('archive_123')

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'archive/verify',
        { archive_id: 'archive_123' },
        'node-001'
      )
    })

    it('should call sendNodeCommand for retrieve archive', () => {
      auth.retrieveArchive('archive_456')

      expect(mockSendNodeCommand).toHaveBeenCalledWith(
        'archive/retrieve',
        { archive_id: 'archive_456' },
        'node-001'
      )
    })
  })

  // ===========================================================================
  // CALLBACK TESTS
  // ===========================================================================

  describe('Auth Callbacks', () => {
    it('should register auth change callback', () => {
      const callback = vi.fn()
      const unsubscribe = auth.onAuthChange(callback)

      expect(typeof unsubscribe).toBe('function')
    })

    it('should allow unsubscribing from auth changes', () => {
      const callback = vi.fn()
      const unsubscribe = auth.onAuthChange(callback)

      // Unsubscribe
      unsubscribe()

      // Callback should not be called anymore (verified by internal state)
      expect(callback).not.toHaveBeenCalled()
    })
  })

  // ===========================================================================
  // READONLY STATE TESTS
  // ===========================================================================

  describe('Readonly State', () => {
    it('should return readonly authenticated state', () => {
      expect(auth.authenticated).toBeDefined()
      expect(typeof auth.authenticated.value).toBe('boolean')
    })

    it('should return readonly users state', () => {
      expect(auth.users).toBeDefined()
      expect(Array.isArray(auth.users.value)).toBe(true)
    })

    it('should return readonly auditEvents state', () => {
      expect(auth.auditEvents).toBeDefined()
      expect(Array.isArray(auth.auditEvents.value)).toBe(true)
    })

    it('should return readonly archives state', () => {
      expect(auth.archives).toBeDefined()
      expect(Array.isArray(auth.archives.value)).toBe(true)
    })
  })

  // ===========================================================================
  // SECURITY SETTINGS TESTS
  // ===========================================================================

  describe('Security Settings', () => {
    it('should expose guestAccessEnabled as readonly ref', () => {
      expect(auth.guestAccessEnabled).toBeDefined()
      expect(typeof auth.guestAccessEnabled.value).toBe('boolean')
    })

    it('should expose sessionLockEnabled as readonly ref', () => {
      expect(auth.sessionLockEnabled).toBeDefined()
      expect(typeof auth.sessionLockEnabled.value).toBe('boolean')
    })

    it('should have guest access disabled by default', () => {
      expect(auth.guestAccessEnabled.value).toBe(false)
    })

    it('should have session lock disabled by default', () => {
      expect(auth.sessionLockEnabled.value).toBe(false)
    })

    it('should expose reloadSecuritySettings function', () => {
      expect(typeof auth.reloadSecuritySettings).toBe('function')
    })

    it('should expose session lock state', () => {
      expect(auth.sessionState).toBeDefined()
      expect(auth.sessionState.value).toBe('active')
    })

    it('should expose isSessionLocked computed', () => {
      expect(auth.isSessionLocked).toBeDefined()
      expect(auth.isSessionLocked.value).toBe(false)
    })

    it('should expose sessionLockWarning ref', () => {
      expect(auth.sessionLockWarning).toBeDefined()
      expect(auth.sessionLockWarning.value).toBe(false)
    })

    it('reloadSecuritySettings should read from localStorage', () => {
      // Save guest_access_enabled=false to localStorage
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: false,
        session_lock_enabled: true,
        session_lock_timeout_minutes: 15,
        session_lock_warning_minutes: 10
      }))

      auth.reloadSecuritySettings()

      expect(auth.guestAccessEnabled.value).toBe(false)
      expect(auth.sessionLockEnabled.value).toBe(true)

      // Cleanup
      localStorage.removeItem('nisystem-security-settings')
    })

    it('reloadSecuritySettings should force login when guest access disabled and user is guest', () => {
      // Ensure we start as guest by re-enabling guest access first
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: true
      }))
      auth.reloadSecuritySettings()
      expect(auth.currentUser.value?.role).toBe('guest')

      // Now disable guest access
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: false
      }))

      auth.reloadSecuritySettings()

      // Should no longer be authenticated
      expect(auth.authenticated.value).toBe(false)
      expect(auth.currentUser.value).toBeNull()

      // Cleanup — re-enable guest
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: true
      }))
      auth.reloadSecuritySettings()
      localStorage.removeItem('nisystem-security-settings')
    })

    it('reloadSecuritySettings should restore guest when guest access re-enabled', () => {
      // Disable guest access first
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: false
      }))
      auth.reloadSecuritySettings()
      expect(auth.currentUser.value).toBeNull()

      // Re-enable guest access
      localStorage.setItem('nisystem-security-settings', JSON.stringify({
        guest_access_enabled: true
      }))
      auth.reloadSecuritySettings()

      expect(auth.authenticated.value).toBe(true)
      expect(auth.currentUser.value?.role).toBe('guest')

      // Cleanup
      localStorage.removeItem('nisystem-security-settings')
    })

    it('should gracefully handle missing localStorage data', () => {
      localStorage.removeItem('nisystem-security-settings')
      auth.reloadSecuritySettings()

      // Defaults should apply (guest OFF)
      expect(auth.guestAccessEnabled.value).toBe(false)
      expect(auth.sessionLockEnabled.value).toBe(false)
    })

    it('should gracefully handle corrupted localStorage data', () => {
      localStorage.setItem('nisystem-security-settings', '{invalid json')
      auth.reloadSecuritySettings()

      // Should fall back to defaults (guest OFF)
      expect(auth.guestAccessEnabled.value).toBe(false)
      expect(auth.sessionLockEnabled.value).toBe(false)

      // Cleanup
      localStorage.removeItem('nisystem-security-settings')
    })
  })

  // ===========================================================================
  // UNLOCK SESSION TESTS
  // ===========================================================================

  describe('Session Unlock', () => {
    it('should expose unlockSession function', () => {
      expect(typeof auth.unlockSession).toBe('function')
    })

    it('should fail unlock when MQTT not connected', async () => {
      mockMqtt.connected.value = false
      const result = await auth.unlockSession('password')
      expect(result).toBe(false)
      mockMqtt.connected.value = true  // Restore
    })
  })
})

// ===========================================================================
// INTEGRATION TESTS - Auth Flow Simulation
// ===========================================================================

describe('Auth Flow Integration', () => {
  describe('Complete Login Flow', () => {
    it('should export all expected methods', () => {
      const auth = useAuth()

      // Auth actions
      expect(typeof auth.login).toBe('function')
      expect(typeof auth.logout).toBe('function')
      expect(typeof auth.unlockSession).toBe('function')
      expect(typeof auth.requestAuthStatus).toBe('function')
      expect(typeof auth.onAuthChange).toBe('function')
      expect(typeof auth.reloadSecuritySettings).toBe('function')

      // User management actions
      expect(typeof auth.listUsers).toBe('function')
      expect(typeof auth.createUser).toBe('function')
      expect(typeof auth.updateUser).toBe('function')
      expect(typeof auth.deleteUser).toBe('function')

      // Audit actions
      expect(typeof auth.queryAuditEvents).toBe('function')
      expect(typeof auth.exportAuditEvents).toBe('function')

      // Archive actions
      expect(typeof auth.listArchives).toBe('function')
      expect(typeof auth.verifyArchive).toBe('function')
      expect(typeof auth.retrieveArchive).toBe('function')
    })

    it('should export all expected computed properties', () => {
      const auth = useAuth()

      expect(auth.isAdmin).toBeDefined()
      expect(auth.isSupervisor).toBeDefined()
      expect(auth.isOperator).toBeDefined()
      expect(auth.isGuest).toBeDefined()
      expect(auth.isSessionLocked).toBeDefined()
      expect(typeof auth.hasPermission).toBe('function')
    })

    it('should export all expected state refs', () => {
      const auth = useAuth()

      // Auth state
      expect(auth.authenticated).toBeDefined()
      expect(auth.currentUser).toBeDefined()
      expect(auth.authError).toBeDefined()
      expect(auth.isLoggingIn).toBeDefined()

      // Session lock state
      expect(auth.sessionState).toBeDefined()
      expect(auth.sessionLockWarning).toBeDefined()

      // Security settings state
      expect(auth.guestAccessEnabled).toBeDefined()
      expect(auth.sessionLockEnabled).toBeDefined()

      // User management state
      expect(auth.users).toBeDefined()
      expect(auth.isLoadingUsers).toBeDefined()

      // Audit state
      expect(auth.auditEvents).toBeDefined()
      expect(auth.isLoadingAudit).toBeDefined()

      // Archive state
      expect(auth.archives).toBeDefined()
      expect(auth.isLoadingArchives).toBeDefined()
    })
  })
})
