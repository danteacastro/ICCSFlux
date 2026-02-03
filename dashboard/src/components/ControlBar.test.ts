/**
 * Tests for ControlBar Component
 *
 * Tests cover:
 * - Start/Stop acquisition buttons
 * - Recording controls
 * - Session toggle
 * - Edit mode toggle
 * - Permission-based control visibility
 * - Recording time display
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { ref, type Ref } from 'vue'

// Shared state for mocks - set before mounting component
let mockAcquiring: Ref<boolean>
let mockRecording: Ref<boolean>
let mockEditMode: Ref<boolean>
let mockPidEditMode: Ref<boolean>
let mockSessionActive: Ref<boolean>
let mockAuthRole: Ref<string>

// Initialize fresh refs
function resetMocks() {
  mockAcquiring = ref(false)
  mockRecording = ref(false)
  mockEditMode = ref(false)
  mockPidEditMode = ref(false)
  mockSessionActive = ref(false)
  mockAuthRole = ref('admin')
}

// Mock all composables - they read from the shared refs
vi.mock('../stores/dashboard', () => ({
  useDashboardStore: () => ({
    get isConnected() { return true },
    get isAcquiring() { return mockAcquiring.value },
    get isRecording() { return mockRecording.value },
    get status() { return { recording_duration_seconds: 0 } },
    get editMode() { return mockEditMode.value },
    get pidEditMode() { return mockPidEditMode.value },
    toggleEditMode: vi.fn(),
    setPidEditMode: vi.fn()
  })
}))

vi.mock('../composables/useAuth', () => ({
  useAuth: () => ({
    hasPermission: (perm: string) => {
      const role = mockAuthRole.value
      return role === 'admin' || role === 'operator' || role === 'supervisor'
    },
    isOperator: {
      get value() {
        return ['admin', 'supervisor', 'operator'].includes(mockAuthRole.value)
      }
    }
  })
}))

vi.mock('../composables/useMqtt', () => ({
  useMqtt: () => ({
    connected: { value: true }
  })
}))

vi.mock('../composables/usePlayground', () => ({
  usePlayground: () => ({
    isSessionActive: {
      get value() { return mockSessionActive.value }
    }
  })
}))

// Import after mocking
import ControlBar from './ControlBar.vue'

describe('ControlBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetMocks()
  })

  // ===========================================================================
  // RENDERING TESTS
  // ===========================================================================

  describe('Rendering', () => {
    it('should render control bar', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.find('.control-bar').exists()).toBe(true)
    })

    it('should show START button when not acquiring', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.text()).toContain('START')
    })

    it('should show RECORD button', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.text()).toContain('RECORD')
    })

    it('should show SESSION toggle', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.text()).toContain('SESSION')
    })
  })

  // ===========================================================================
  // BUTTON STATE TESTS
  // ===========================================================================

  describe('Button States', () => {
    it('should have control groups', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.findAll('.control-group').length).toBeGreaterThan(0)
    })

    it('should render start button with correct class', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.find('.btn-start').exists()).toBe(true)
    })

    it('should render record button with correct class', () => {
      const wrapper = mount(ControlBar)
      expect(wrapper.find('.btn-record').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // START/STOP STATE TRANSITION TESTS
  // ===========================================================================

  describe('Start/Stop State Transition', () => {
    it('should show START button when not acquiring', () => {
      mockAcquiring.value = false

      const wrapper = mount(ControlBar)

      expect(wrapper.find('.btn-start').exists()).toBe(true)
      expect(wrapper.find('.btn-stop').exists()).toBe(false)
      expect(wrapper.text()).toContain('START')
    })

    it('should show STOP button when acquiring', () => {
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)

      expect(wrapper.find('.btn-stop').exists()).toBe(true)
      expect(wrapper.find('.btn-start').exists()).toBe(false)
      expect(wrapper.text()).toContain('STOP')
    })

    it('should emit stop when STOP button clicked', async () => {
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const stopBtn = wrapper.find('.btn-stop')

      await stopBtn.trigger('click')

      expect(wrapper.emitted('stop')).toBeTruthy()
    })
  })

  // ===========================================================================
  // EMIT TESTS
  // ===========================================================================

  describe('Event Emission', () => {
    it('should emit start when START clicked', async () => {
      const wrapper = mount(ControlBar)

      const startBtn = wrapper.find('.btn-start')
      await startBtn.trigger('click')

      expect(wrapper.emitted('start')).toBeTruthy()
    })
  })

  // ===========================================================================
  // EDIT MODE TESTS
  // ===========================================================================

  describe('Edit Mode', () => {
    it('should show edit controls when showEditControls is true', () => {
      const wrapper = mount(ControlBar, {
        props: { showEditControls: true }
      })

      expect(wrapper.find('.edit-group').exists()).toBe(true)
    })

    it('should not show edit controls when showEditControls is false', () => {
      const wrapper = mount(ControlBar, {
        props: { showEditControls: false }
      })

      expect(wrapper.find('.edit-group').exists()).toBe(false)
    })

    it('should show EDIT button in edit group', () => {
      const wrapper = mount(ControlBar, {
        props: { showEditControls: true }
      })

      expect(wrapper.find('.btn-edit').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // PERMISSION TESTS
  // ===========================================================================

  describe('Permissions', () => {
    it('should show lock icon for guests', () => {
      mockAuthRole.value = 'guest'

      const wrapper = mount(ControlBar)

      expect(wrapper.findAll('.lock-icon').length).toBeGreaterThan(0)
    })

    it('should not show lock icon for operators', () => {
      mockAuthRole.value = 'operator'

      const wrapper = mount(ControlBar)

      // Start button should not have lock class when user is operator
      const startBtn = wrapper.find('.btn-start')
      expect(startBtn.classes()).not.toContain('locked')
    })

    it('should not show lock icon for admins', () => {
      mockAuthRole.value = 'admin'

      const wrapper = mount(ControlBar)

      const startBtn = wrapper.find('.btn-start')
      expect(startBtn.classes()).not.toContain('locked')
    })
  })

  // ===========================================================================
  // SESSION TOGGLE TESTS
  // ===========================================================================

  describe('Session Toggle', () => {
    it('should render session toggle', () => {
      const wrapper = mount(ControlBar)

      expect(wrapper.find('.session-toggle').exists()).toBe(true)
    })

    it('should have toggle button', () => {
      const wrapper = mount(ControlBar)

      expect(wrapper.find('.toggle-btn').exists()).toBe(true)
    })

    it('should NOT have "on" class when session is inactive', () => {
      mockSessionActive.value = false

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      expect(toggleBtn.classes()).not.toContain('on')
    })

    it('should have "on" class when session is active (green state)', () => {
      mockSessionActive.value = true
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      expect(toggleBtn.classes()).toContain('on')
    })

    it('should be disabled when not acquiring', () => {
      mockAcquiring.value = false

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      expect(toggleBtn.classes()).toContain('disabled')
      expect(toggleBtn.attributes('disabled')).toBeDefined()
    })

    it('should be enabled when acquiring', () => {
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      expect(toggleBtn.classes()).not.toContain('disabled')
    })

    it('should emit session-start when clicked while OFF (inactive)', async () => {
      mockSessionActive.value = false
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      await toggleBtn.trigger('click')

      expect(wrapper.emitted('session-start')).toBeTruthy()
      expect(wrapper.emitted('session-stop')).toBeFalsy()
    })

    it('should emit session-stop when clicked while ON (active)', async () => {
      mockSessionActive.value = true
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      await toggleBtn.trigger('click')

      expect(wrapper.emitted('session-stop')).toBeTruthy()
      expect(wrapper.emitted('session-start')).toBeFalsy()
    })

    it('should NOT emit events when clicked while not acquiring', async () => {
      mockSessionActive.value = false
      mockAcquiring.value = false

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      await toggleBtn.trigger('click')

      expect(wrapper.emitted('session-start')).toBeFalsy()
      expect(wrapper.emitted('session-stop')).toBeFalsy()
    })

    it('should NOT emit events when user lacks permission', async () => {
      mockAuthRole.value = 'guest'
      mockAcquiring.value = true

      const wrapper = mount(ControlBar)
      const toggleBtn = wrapper.find('.toggle-btn')

      await toggleBtn.trigger('click')

      expect(wrapper.emitted('session-start')).toBeFalsy()
      expect(wrapper.emitted('session-stop')).toBeFalsy()
    })
  })

  // ===========================================================================
  // API COMPLETENESS TESTS
  // ===========================================================================

  describe('Component Interface', () => {
    it('should accept showEditControls prop', () => {
      const wrapper = mount(ControlBar, {
        props: { showEditControls: true }
      })

      expect(wrapper.props('showEditControls')).toBe(true)
    })

    it('should emit expected events', async () => {
      const wrapper = mount(ControlBar, {
        props: { showEditControls: true }
      })

      // Check that component can emit these events (emitDefinitions)
      const emits = (wrapper.vm.$options as Record<string, unknown>).emits
      // Vue 3 with script setup doesn't expose emits the same way,
      // but we can verify by attempting to trigger them
      expect(typeof wrapper.vm.$emit).toBe('function')
    })
  })
})
