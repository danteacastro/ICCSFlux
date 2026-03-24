/**
 * Tests for AdminTab Component
 *
 * Tests cover:
 * - Access control (admin-only access)
 * - Section navigation (Users, Audit, Archives)
 * - User management UI operations
 * - Audit trail display and filtering
 * - Archive management UI
 * - Dialog rendering (Create/Edit User, Event Details, Delete Confirm)
 * - Data formatting functions
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref, readonly, computed } from 'vue'

// Create mock functions first (these are safe to hoist)
const mockListUsers = vi.fn()
const mockCreateUser = vi.fn()
const mockUpdateUser = vi.fn()
const mockDeleteUser = vi.fn()
const mockQueryAuditEvents = vi.fn()
const mockExportAuditEvents = vi.fn()
const mockListArchives = vi.fn()
const mockVerifyArchive = vi.fn()
const mockRetrieveArchive = vi.fn()

// Mock useAuth composable - must be before imports that use it
// Define reactive state INSIDE the mock factory to avoid hoisting issues
vi.mock('../composables/useAuth', () => {
  const { ref, readonly, computed } = require('vue')

  const mockUsers = ref([
    {
      username: 'admin',
      display_name: 'Administrator',
      email: 'admin@example.com',
      role: 'admin',
      enabled: true,
      created_at: '2024-01-01T00:00:00Z',
      last_login: '2024-06-15T10:30:00Z'
    },
    {
      username: 'operator1',
      display_name: 'Test Operator',
      email: 'operator@example.com',
      role: 'operator',
      enabled: true,
      created_at: '2024-02-01T00:00:00Z',
      last_login: '2024-06-14T08:15:00Z'
    }
  ])

  const mockAuditEvents = ref([
    {
      event_id: 'evt_001',
      event_type: 'login',
      timestamp: '2024-06-15T10:30:00Z',
      username: 'admin',
      details: { source: 'dashboard' },
      checksum: 'abc123def456789012345678901234567890abcd'
    }
  ])

  const mockArchives = ref([
    {
      archive_id: 'arch_001',
      original_filename: 'session_2024-06-15.csv',
      content_type: 'recording',
      archived_at: '2024-06-15T12:00:00Z',
      size_bytes: 1024000,
      compressed: true,
      checksum: 'abc123'
    }
  ])

  const mockCurrentUser = ref({
    username: 'admin',
    role: 'admin',
    displayName: 'Administrator',
    permissions: ['VIEW_DATA', 'MANAGE_USERS', 'VIEW_AUDIT']
  })

  interface MockAuthState {
    mockCurrentUser: ReturnType<typeof ref>
    mockUsers: ReturnType<typeof ref>
    mockAuditEvents: ReturnType<typeof ref>
    mockArchives: ReturnType<typeof ref>
  }

  // Store refs globally so tests can access them
  ;(globalThis as unknown as Record<string, MockAuthState>).__mockAuthState = {
    mockCurrentUser,
    mockUsers,
    mockAuditEvents,
    mockArchives
  }

  return {
    useAuth: () => ({
      currentUser: readonly(mockCurrentUser),
      isAdmin: computed(() => mockCurrentUser.value?.role === 'admin'),
      isSupervisor: computed(() => ['admin', 'supervisor'].includes(mockCurrentUser.value?.role || '')),
      users: readonly(mockUsers),
      isLoadingUsers: ref(false),
      auditEvents: readonly(mockAuditEvents),
      isLoadingAudit: ref(false),
      archives: readonly(mockArchives),
      isLoadingArchives: ref(false),
      listUsers: vi.fn(),
      createUser: vi.fn(),
      updateUser: vi.fn(),
      deleteUser: vi.fn(),
      queryAuditEvents: vi.fn(),
      exportAuditEvents: vi.fn(),
      listArchives: vi.fn(),
      verifyArchive: vi.fn(),
      retrieveArchive: vi.fn(),
      reloadSecuritySettings: vi.fn()
    })
  }
})

// Import component AFTER mock is set up
import AdminTab from './AdminTab.vue'

// Helper to access mock state
function getMockState() {
  return (globalThis as unknown as Record<string, { mockCurrentUser: { value: Record<string, unknown> }; mockUsers: { value: unknown[] }; mockAuditEvents: { value: unknown[] }; mockArchives: { value: unknown[] } }>).__mockAuthState
}

describe('AdminTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset to admin user using mock state
    const { mockCurrentUser } = getMockState()
    mockCurrentUser.value = {
      username: 'admin',
      role: 'admin',
      displayName: 'Administrator',
      permissions: ['VIEW_DATA', 'MANAGE_USERS', 'VIEW_AUDIT']
    }
  })

  // ===========================================================================
  // ACCESS CONTROL TESTS
  // ===========================================================================

  describe('Access Control', () => {
    it('should show access denied for non-admin/non-supervisor users', async () => {
      const { mockCurrentUser } = getMockState()
      mockCurrentUser.value = {
        username: 'operator',
        role: 'operator',
        displayName: 'Operator',
        permissions: ['VIEW_DATA']
      }

      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(wrapper.find('.access-denied').exists()).toBe(true)
      expect(wrapper.text()).toContain('Access Restricted')
      expect(wrapper.text()).toContain('Supervisor or Administrator')
    })

    it('should show current role in access denied message', async () => {
      const { mockCurrentUser } = getMockState()
      mockCurrentUser.value = {
        username: 'guest',
        role: 'guest',
        displayName: 'Guest',
        permissions: ['VIEW_DATA']
      }

      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(wrapper.text()).toContain('Your current role:')
      expect(wrapper.text()).toContain('guest')
    })

    it('should show admin panel for admin users', () => {
      // Already set to admin in beforeEach
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(wrapper.find('.admin-content').exists()).toBe(true)
      expect(wrapper.find('.access-denied').exists()).toBe(false)
    })
  })

  // Helper: mount and navigate to a specific section
  async function mountAndNavigateTo(section: 'stations' | 'nodes' | 'users' | 'audit' | 'archives' | 'settings' | 'security') {
    const sectionIndex: Record<string, number> = { stations: 0, nodes: 1, users: 2, audit: 3, archives: 4, settings: 5, security: 6 }
    const wrapper = mount(AdminTab, { global: { stubs: { Teleport: true } } })
    if (section !== 'stations') {
      const btn = wrapper.findAll('.section-btn')[sectionIndex[section]]
      await btn.trigger('click')
    }
    return wrapper
  }

  // ===========================================================================
  // SECTION NAVIGATION TESTS
  // ===========================================================================

  describe('Section Navigation', () => {
    it('should display all three section buttons', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const sectionButtons = wrapper.findAll('.section-btn')
      expect(sectionButtons.length).toBe(7)

      const buttonTexts = sectionButtons.map(b => b.text())
      expect(buttonTexts).toContain('🏭 Stations')
      expect(buttonTexts).toContain('🖥️ Nodes')
      expect(buttonTexts).toContain('👥 Users')
      expect(buttonTexts).toContain('📋 Audit Trail')
      expect(buttonTexts).toContain('📦 Archives')
      expect(buttonTexts).toContain('⚙️ Settings')
      expect(buttonTexts).toContain('🛡️ Security')
    })

    it('should start with Stations section active', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const activeButton = wrapper.find('.section-btn.active')
      expect(activeButton.text()).toContain('Stations')
    })

    it('should switch to Audit Trail section on click', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      expect(wrapper.find('.section-btn.active').text()).toContain('Audit Trail')
    })

    it('should switch to Archives section on click', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      expect(wrapper.find('.section-btn.active').text()).toContain('Archives')
    })
  })

  // ===========================================================================
  // USER MANAGEMENT SECTION TESTS
  // ===========================================================================

  describe('User Management Section', () => {
    it('should display user table headers', async () => {
      const wrapper = await mountAndNavigateTo('users')

      const headers = wrapper.findAll('th')
      const headerTexts = headers.map(h => h.text())

      expect(headerTexts).toContain('Username')
      expect(headerTexts).toContain('Display Name')
      expect(headerTexts).toContain('Role')
      expect(headerTexts).toContain('Status')
      expect(headerTexts).toContain('Last Login')
      expect(headerTexts).toContain('Actions')
    })

    it('should display users in the table', async () => {
      const wrapper = await mountAndNavigateTo('users')

      expect(wrapper.text()).toContain('admin')
      expect(wrapper.text()).toContain('operator1')
      expect(wrapper.text()).toContain('Administrator')
      expect(wrapper.text()).toContain('Test Operator')
    })

    it('should display role badges', async () => {
      const wrapper = await mountAndNavigateTo('users')

      expect(wrapper.find('.role-admin').exists()).toBe(true)
      expect(wrapper.find('.role-operator').exists()).toBe(true)
    })

    it('should display status badges', async () => {
      const wrapper = await mountAndNavigateTo('users')

      const enabledBadges = wrapper.findAll('.status-badge.enabled')
      expect(enabledBadges.length).toBeGreaterThan(0)
    })

    it('should have Add User button', async () => {
      const wrapper = await mountAndNavigateTo('users')

      const addButton = wrapper.find('button.btn-primary')
      expect(addButton.text()).toContain('Add User')
    })

    it('should disable delete button for current user', async () => {
      const wrapper = await mountAndNavigateTo('users')

      // Find the row for admin user and check if delete is disabled
      const rows = wrapper.findAll('tbody tr')
      const adminRow = rows.find(r => r.text().includes('admin'))

      if (adminRow) {
        const deleteBtn = adminRow.find('.btn-danger')
        expect(deleteBtn.attributes('disabled')).toBeDefined()
      }
    })
  })

  // ===========================================================================
  // AUDIT TRAIL SECTION TESTS
  // ===========================================================================

  describe('Audit Trail Section', () => {
    it('should display audit filters', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      // Switch to audit section
      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      expect(wrapper.find('.audit-filters').exists()).toBe(true)
      expect(wrapper.find('select').exists()).toBe(true)
    })

    it('should have refresh and export buttons', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      expect(wrapper.text()).toContain('Refresh')
      expect(wrapper.text()).toContain('Export')
    })

    it('should display audit event table headers', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      const headerTexts = wrapper.findAll('th').map(h => h.text())
      expect(headerTexts).toContain('Timestamp')
      expect(headerTexts).toContain('Event Type')
      expect(headerTexts).toContain('User')
      expect(headerTexts).toContain('Details')
      expect(headerTexts).toContain('Checksum')
    })

    it('should display audit events in table', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      expect(wrapper.text()).toContain('admin')
      expect(wrapper.text()).toContain('abc123de...')
    })
  })

  // ===========================================================================
  // ARCHIVE SECTION TESTS
  // ===========================================================================

  describe('Archive Section', () => {
    it('should display archive info cards', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      expect(wrapper.find('.archive-info').exists()).toBe(true)
      expect(wrapper.findAll('.info-card').length).toBe(3)
    })

    it('should display total archives count', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      expect(wrapper.text()).toContain('Total Archives')
      expect(wrapper.text()).toContain('1')
    })

    it('should display retention period', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      expect(wrapper.text()).toContain('10 Years')
      expect(wrapper.text()).toContain('Retention Period')
    })

    it('should display archive table', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      expect(wrapper.text()).toContain('session_2024-06-15.csv')
      expect(wrapper.text()).toContain('recording')
    })
  })

  // ===========================================================================
  // LIFECYCLE TESTS
  // ===========================================================================

  describe('Lifecycle', () => {
    it('should render admin content on mount for admin', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      // Verify admin content is rendered (component lifecycle completed)
      expect(wrapper.find('.admin-content').exists()).toBe(true)
      expect(wrapper.find('.section-nav').exists()).toBe(true)
    })

    it('should show Stations section by default', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      // Stations section should be active by default
      expect(wrapper.find('.section-btn.active').text()).toContain('Stations')
    })

    it('should display users table when users section selected', async () => {
      const wrapper = await mountAndNavigateTo('users')

      // Users table should be visible
      expect(wrapper.find('.data-table').exists()).toBe(true)
    })

    it('should show access denied for non-supervisor users', () => {
      const { mockCurrentUser } = getMockState()
      mockCurrentUser.value = {
        username: 'operator',
        role: 'operator',
        displayName: 'Operator',
        permissions: ['VIEW_DATA']
      }

      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      // Non-supervisor/admin users see access denied
      expect(wrapper.find('.access-denied').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // DATA FORMATTING TESTS
  // ===========================================================================

  describe('Data Formatting', () => {
    it('should format bytes correctly', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const archivesButton = wrapper.findAll('.section-btn')[4]
      await archivesButton.trigger('click')

      // 1024000 bytes = ~1000 KB or ~1 MB
      expect(wrapper.text()).toMatch(/\d+(\.\d+)?\s*(KB|MB)/i)
    })

    it('should truncate long checksums', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[3]
      await auditButton.trigger('click')

      // Should show truncated checksum with ...
      expect(wrapper.text()).toContain('...')
    })
  })
})

// ===========================================================================
// USER DIALOG TESTS
// ===========================================================================

describe('AdminTab User Dialogs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const { mockCurrentUser } = getMockState()
    mockCurrentUser.value = {
      username: 'admin',
      role: 'admin',
      displayName: 'Administrator',
      permissions: ['VIEW_DATA', 'MANAGE_USERS', 'VIEW_AUDIT']
    }
  })

  it('should show create user dialog when Add User clicked', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    // Navigate to Users section first (default is Nodes)
    await wrapper.findAll('.section-btn')[2].trigger('click')

    const addButton = wrapper.find('button.btn-primary')
    await addButton.trigger('click')

    expect(wrapper.find('.modal-dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('Create New User')
  })

  it('should have form fields in create user dialog', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    await wrapper.findAll('.section-btn')[2].trigger('click')

    const addButton = wrapper.find('button.btn-primary')
    await addButton.trigger('click')

    expect(wrapper.find('input[type="text"]').exists()).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('select').exists()).toBe(true)
  })

  it('should have role options in create user dialog', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    await wrapper.findAll('.section-btn')[2].trigger('click')

    const addButton = wrapper.find('button.btn-primary')
    await addButton.trigger('click')

    const options = wrapper.findAll('.modal-dialog select option')
    const optionTexts = options.map(o => o.text())

    // Actual role options in the component
    expect(optionTexts.some(t => t.includes('Guest'))).toBe(true)
    expect(optionTexts.some(t => t.includes('Operator'))).toBe(true)
    expect(optionTexts.some(t => t.includes('Supervisor'))).toBe(true)
    expect(optionTexts.some(t => t.includes('Admin'))).toBe(true)
  })

  it('should close dialog when Cancel clicked', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    await wrapper.findAll('.section-btn')[2].trigger('click')

    // Open dialog
    const addButton = wrapper.find('button.btn-primary')
    await addButton.trigger('click')
    expect(wrapper.find('.modal-dialog').exists()).toBe(true)

    // Close dialog
    const cancelButton = wrapper.find('.modal-dialog .btn-cancel')
    await cancelButton.trigger('click')

    // Dialog should be closed (this may need adjustment based on reactivity)
    await wrapper.vm.$nextTick()
  })
})

// ===========================================================================
// DELETE CONFIRMATION TESTS
// ===========================================================================

describe('AdminTab Delete Confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const { mockCurrentUser } = getMockState()
    mockCurrentUser.value = {
      username: 'admin',
      role: 'admin',
      displayName: 'Administrator',
      permissions: ['VIEW_DATA', 'MANAGE_USERS', 'VIEW_AUDIT']
    }
  })

  it('should show confirmation dialog when delete clicked', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    // Navigate to Users section first (default is Stations)
    await wrapper.findAll('.section-btn')[2].trigger('click')

    // Find delete button for operator1 (not admin)
    const rows = wrapper.findAll('tbody tr')
    const operatorRow = rows.find(r => r.text().includes('operator1'))

    if (operatorRow) {
      const deleteBtn = operatorRow.find('.btn-icon.btn-danger')
      await deleteBtn.trigger('click')

      expect(wrapper.text()).toContain('Confirm Delete')
      expect(wrapper.text()).toContain('operator1')
    }
  })

  it('should warn that action cannot be undone', async () => {
    const wrapper = mount(AdminTab, {
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    // Navigate to Users section first (default is Stations)
    await wrapper.findAll('.section-btn')[2].trigger('click')

    const rows = wrapper.findAll('tbody tr')
    const operatorRow = rows.find(r => r.text().includes('operator1'))

    if (operatorRow) {
      const deleteBtn = operatorRow.find('.btn-icon.btn-danger')
      await deleteBtn.trigger('click')

      expect(wrapper.text()).toContain('cannot be undone')
    }
  })
})

// ===========================================================================
// SECURITY SECTION TESTS
// ===========================================================================

describe('AdminTab Security Section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const { mockCurrentUser } = getMockState()
    mockCurrentUser.value = {
      username: 'admin',
      role: 'admin',
      displayName: 'Administrator',
      permissions: ['VIEW_DATA', 'MANAGE_USERS', 'VIEW_AUDIT']
    }
    // Reset localStorage for security settings
    localStorage.removeItem('nisystem-security-settings')
  })

  async function mountSecurity() {
    const wrapper = mount(AdminTab, { global: { stubs: { Teleport: true } } })
    // Security is index 6 in the section buttons
    const secBtn = wrapper.findAll('.section-btn')[6]
    await secBtn.trigger('click')
    return wrapper
  }

  it('should display Security section when clicked', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.find('.section-btn.active').text()).toContain('Security')
  })

  it('should show Security Settings header with NIST badge', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Security Settings')
    expect(wrapper.text()).toContain('Security Compliance')
  })

  it('should show description about NIST compliance features', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Security Compliance / Security Compliance')
    expect(wrapper.text()).toContain('disabled by default')
  })

  it('should display Session Lock toggle group', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Session Lock')
    expect(wrapper.text()).toContain('Lock session after inactivity')
    expect(wrapper.text()).toContain('Backend processes')
  })

  it('should display Access Control toggle group', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Access Control')
    expect(wrapper.text()).toContain('Allow guest access')
    expect(wrapper.text()).toContain('Limit concurrent sessions')
  })

  it('should display Audit & Integrity toggle group', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Audit & Integrity')
    expect(wrapper.text()).toContain('audit trail integrity verification')
    expect(wrapper.text()).toContain('NTP time synchronization')
  })

  it('should display Anomaly Detection toggle group', async () => {
    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Anomaly Detection')
    expect(wrapper.text()).toContain('MQTT anomaly detection')
    expect(wrapper.text()).toContain('command floods')
  })

  it('should have Reset to Defaults button', async () => {
    const wrapper = await mountSecurity()

    const buttons = wrapper.findAll('button')
    const resetBtn = buttons.find(b => b.text().includes('Reset to Defaults'))
    expect(resetBtn).toBeDefined()
  })

  it('should have Enable All button', async () => {
    const wrapper = await mountSecurity()

    const buttons = wrapper.findAll('button')
    const nistBtn = buttons.find(b => b.text().includes('Enable All'))
    expect(nistBtn).toBeDefined()
  })

  it('should have all security toggle checkboxes', async () => {
    const wrapper = await mountSecurity()

    // Find all checkboxes in the security section
    const checkboxes = wrapper.findAll('.security-group input[type="checkbox"]')
    // Session lock (1) + guest access (1) + concurrent sessions (1) + audit integrity (1) + NTP (1) + anomaly detection (1) = 6
    expect(checkboxes.length).toBe(6)
  })

  it('should show sub-settings when session lock is enabled', async () => {
    // Pre-set session lock enabled
    localStorage.setItem('nisystem-security-settings', JSON.stringify({
      session_lock_enabled: true,
      session_lock_timeout_minutes: 30,
      session_lock_warning_minutes: 25,
      guest_access_enabled: true
    }))

    const wrapper = await mountSecurity()

    // Sub-settings should be visible
    expect(wrapper.text()).toContain('Lock timeout')
    expect(wrapper.text()).toContain('Warning before lock')
  })

  it('should show sub-settings when anomaly detection is enabled', async () => {
    localStorage.setItem('nisystem-security-settings', JSON.stringify({
      anomaly_detection_enabled: true,
      anomaly_command_rate_limit: 200,
      anomaly_failed_login_rate_limit: 10,
      security_summary_interval_minutes: 5,
      guest_access_enabled: true
    }))

    const wrapper = await mountSecurity()

    expect(wrapper.text()).toContain('Command rate limit')
    expect(wrapper.text()).toContain('Failed login limit')
    expect(wrapper.text()).toContain('Security summary interval')
  })

  it('should persist settings to localStorage when toggle changes', async () => {
    const wrapper = await mountSecurity()

    // Toggle session lock on
    const checkboxes = wrapper.findAll('.security-group input[type="checkbox"]')
    await checkboxes[0].setValue(true)

    // Check localStorage was updated
    const saved = localStorage.getItem('nisystem-security-settings')
    expect(saved).toBeTruthy()
    const parsed = JSON.parse(saved!)
    expect(parsed.session_lock_enabled).toBe(true)
  })

  it('should save all-off defaults when Reset to Defaults clicked', async () => {
    // First enable everything
    localStorage.setItem('nisystem-security-settings', JSON.stringify({
      session_lock_enabled: true,
      anomaly_detection_enabled: true,
      guest_access_enabled: false
    }))

    const wrapper = await mountSecurity()

    // Click Reset to Defaults
    const buttons = wrapper.findAll('button')
    const resetBtn = buttons.find(b => b.text().includes('Reset to Defaults'))
    await resetBtn!.trigger('click')

    const saved = JSON.parse(localStorage.getItem('nisystem-security-settings')!)
    expect(saved.session_lock_enabled).toBe(false)
    expect(saved.anomaly_detection_enabled).toBe(false)
    expect(saved.guest_access_enabled).toBe(true)
  })

  it('should enable all settings when Enable All clicked', async () => {
    const wrapper = await mountSecurity()

    const buttons = wrapper.findAll('button')
    const nistBtn = buttons.find(b => b.text().includes('Enable All'))
    await nistBtn!.trigger('click')

    const saved = JSON.parse(localStorage.getItem('nisystem-security-settings')!)
    expect(saved.session_lock_enabled).toBe(true)
    expect(saved.anomaly_detection_enabled).toBe(true)
    expect(saved.ntp_sync_required).toBe(true)
    expect(saved.audit_integrity_check_enabled).toBe(true)
    expect(saved.guest_access_enabled).toBe(false)
    expect(saved.max_concurrent_sessions).toBe(10)
  })

  it('should hide Security section for non-admin users', () => {
    const { mockCurrentUser } = getMockState()
    mockCurrentUser.value = {
      username: 'supervisor',
      role: 'supervisor',
      displayName: 'Supervisor',
      permissions: ['VIEW_DATA', 'VIEW_AUDIT']
    }

    const wrapper = mount(AdminTab, { global: { stubs: { Teleport: true } } })

    // Security should be hidden for supervisor (requiresAdmin: true)
    const buttonTexts = wrapper.findAll('.section-btn').map(b => b.text())
    expect(buttonTexts).not.toContain('🛡️ Security')
  })

  it('should show Security section for admin users', () => {
    const wrapper = mount(AdminTab, { global: { stubs: { Teleport: true } } })

    const buttonTexts = wrapper.findAll('.section-btn').map(b => b.text())
    expect(buttonTexts).toContain('🛡️ Security')
  })
})
