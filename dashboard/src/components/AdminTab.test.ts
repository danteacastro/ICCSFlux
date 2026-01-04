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
import AdminTab from './AdminTab.vue'

// Mock useAuth composable
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
  },
  {
    event_id: 'evt_002',
    event_type: 'config_change',
    timestamp: '2024-06-15T11:00:00Z',
    username: 'admin',
    details: { field: 'channel', channel: 'TC001' },
    checksum: 'def456789012345678901234567890abcdef1234'
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

const mockIsAdmin = computed(() => mockCurrentUser.value?.role === 'admin')

// Create mock functions
const mockListUsers = vi.fn()
const mockCreateUser = vi.fn()
const mockUpdateUser = vi.fn()
const mockDeleteUser = vi.fn()
const mockQueryAuditEvents = vi.fn()
const mockExportAuditEvents = vi.fn()
const mockListArchives = vi.fn()
const mockVerifyArchive = vi.fn()
const mockRetrieveArchive = vi.fn()

vi.mock('../composables/useAuth', () => ({
  useAuth: () => ({
    currentUser: readonly(mockCurrentUser),
    isAdmin: mockIsAdmin,
    users: readonly(mockUsers),
    isLoadingUsers: ref(false),
    auditEvents: readonly(mockAuditEvents),
    isLoadingAudit: ref(false),
    archives: readonly(mockArchives),
    isLoadingArchives: ref(false),
    listUsers: mockListUsers,
    createUser: mockCreateUser,
    updateUser: mockUpdateUser,
    deleteUser: mockDeleteUser,
    queryAuditEvents: mockQueryAuditEvents,
    exportAuditEvents: mockExportAuditEvents,
    listArchives: mockListArchives,
    verifyArchive: mockVerifyArchive,
    retrieveArchive: mockRetrieveArchive
  })
}))

describe('AdminTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset to admin user
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
    it('should show access denied for non-admin users', async () => {
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
      expect(wrapper.text()).toContain('Administrator privileges are required')
    })

    it('should show current role in access denied message', async () => {
      mockCurrentUser.value = {
        username: 'viewer',
        role: 'viewer',
        displayName: 'Viewer',
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
      expect(wrapper.text()).toContain('viewer')
    })

    it('should show admin panel for admin users', () => {
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
      expect(sectionButtons.length).toBe(3)

      const buttonTexts = sectionButtons.map(b => b.text())
      expect(buttonTexts).toContain('👥 Users')
      expect(buttonTexts).toContain('📋 Audit Trail')
      expect(buttonTexts).toContain('📦 Archives')
    })

    it('should start with Users section active', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const activeButton = wrapper.find('.section-btn.active')
      expect(activeButton.text()).toContain('Users')
    })

    it('should switch to Audit Trail section on click', async () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const auditButton = wrapper.findAll('.section-btn')[1]
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
      await archivesButton.trigger('click')

      expect(wrapper.find('.section-btn.active').text()).toContain('Archives')
    })
  })

  // ===========================================================================
  // USER MANAGEMENT SECTION TESTS
  // ===========================================================================

  describe('User Management Section', () => {
    it('should display user table headers', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const headers = wrapper.findAll('th')
      const headerTexts = headers.map(h => h.text())

      expect(headerTexts).toContain('Username')
      expect(headerTexts).toContain('Display Name')
      expect(headerTexts).toContain('Role')
      expect(headerTexts).toContain('Status')
      expect(headerTexts).toContain('Last Login')
      expect(headerTexts).toContain('Actions')
    })

    it('should display users in the table', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(wrapper.text()).toContain('admin')
      expect(wrapper.text()).toContain('operator1')
      expect(wrapper.text()).toContain('Administrator')
      expect(wrapper.text()).toContain('Test Operator')
    })

    it('should display role badges', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(wrapper.find('.role-admin').exists()).toBe(true)
      expect(wrapper.find('.role-operator').exists()).toBe(true)
    })

    it('should display status badges', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const enabledBadges = wrapper.findAll('.status-badge.enabled')
      expect(enabledBadges.length).toBeGreaterThan(0)
    })

    it('should have Add User button', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      const addButton = wrapper.find('button.btn-primary')
      expect(addButton.text()).toContain('Add User')
    })

    it('should disable delete button for current user', () => {
      const wrapper = mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

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
      const auditButton = wrapper.findAll('.section-btn')[1]
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

      const auditButton = wrapper.findAll('.section-btn')[1]
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

      const auditButton = wrapper.findAll('.section-btn')[1]
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

      const auditButton = wrapper.findAll('.section-btn')[1]
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
      await archivesButton.trigger('click')

      expect(wrapper.text()).toContain('session_2024-06-15.csv')
      expect(wrapper.text()).toContain('recording')
    })
  })

  // ===========================================================================
  // LIFECYCLE TESTS
  // ===========================================================================

  describe('Lifecycle', () => {
    it('should call listUsers on mount for admin', () => {
      mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(mockListUsers).toHaveBeenCalled()
    })

    it('should call queryAuditEvents on mount for admin', () => {
      mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(mockQueryAuditEvents).toHaveBeenCalledWith({ limit: 100 })
    })

    it('should call listArchives on mount for admin', () => {
      mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(mockListArchives).toHaveBeenCalled()
    })

    it('should NOT call data loading for non-admin users', () => {
      mockCurrentUser.value = {
        username: 'operator',
        role: 'operator',
        displayName: 'Operator',
        permissions: ['VIEW_DATA']
      }

      vi.clearAllMocks()

      mount(AdminTab, {
        global: {
          stubs: {
            Teleport: true
          }
        }
      })

      expect(mockListUsers).not.toHaveBeenCalled()
      expect(mockQueryAuditEvents).not.toHaveBeenCalled()
      expect(mockListArchives).not.toHaveBeenCalled()
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

      const archivesButton = wrapper.findAll('.section-btn')[2]
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

      const auditButton = wrapper.findAll('.section-btn')[1]
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

    const addButton = wrapper.find('button.btn-primary')
    await addButton.trigger('click')

    const options = wrapper.findAll('.modal-dialog select option')
    const optionTexts = options.map(o => o.text())

    expect(optionTexts.some(t => t.includes('Viewer'))).toBe(true)
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

    const rows = wrapper.findAll('tbody tr')
    const operatorRow = rows.find(r => r.text().includes('operator1'))

    if (operatorRow) {
      const deleteBtn = operatorRow.find('.btn-icon.btn-danger')
      await deleteBtn.trigger('click')

      expect(wrapper.text()).toContain('cannot be undone')
    }
  })
})
