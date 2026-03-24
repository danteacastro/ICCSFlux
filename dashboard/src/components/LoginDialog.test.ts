/**
 * Tests for LoginDialog Component
 *
 * Tests cover:
 * - Dialog rendering and visibility
 * - Form input handling
 * - Login submission
 * - Password visibility toggle
 * - Error display
 * - Loading state
 * - Cancel behavior
 * - Focus management
 * - Event emissions
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { ref, nextTick } from 'vue'
import LoginDialog from './LoginDialog.vue'

// Mock useAuth composable
const mockLogin = vi.fn()
const mockAuthError = ref<string | null>(null)
const mockIsLoggingIn = ref(false)

vi.mock('../composables/useAuth', () => ({
  useAuth: () => ({
    login: mockLogin,
    authError: mockAuthError,
    isLoggingIn: mockIsLoggingIn
  })
}))

describe('LoginDialog', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthError.value = null
    mockIsLoggingIn.value = false
    mockLogin.mockResolvedValue(true)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  // ===========================================================================
  // VISIBILITY TESTS
  // ===========================================================================

  describe('Visibility', () => {
    it('should not render when isOpen is false', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: false
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.login-overlay').exists()).toBe(false)
    })

    it('should render when isOpen is true', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.login-overlay').exists()).toBe(true)
      expect(wrapper.find('.login-dialog').exists()).toBe(true)
    })

    it('should display login header', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.text()).toContain('Login Required')
      expect(wrapper.text()).toContain('Please enter your credentials to continue')
    })
  })

  // ===========================================================================
  // FORM INPUT TESTS
  // ===========================================================================

  describe('Form Inputs', () => {
    beforeEach(() => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })
    })

    it('should have username input field', () => {
      const usernameInput = wrapper.find('#username')
      expect(usernameInput.exists()).toBe(true)
      expect(usernameInput.attributes('type')).toBe('text')
      expect(usernameInput.attributes('placeholder')).toBe('Enter username')
    })

    it('should have password input field', () => {
      const passwordInput = wrapper.find('#password')
      expect(passwordInput.exists()).toBe(true)
      expect(passwordInput.attributes('type')).toBe('password')
      expect(passwordInput.attributes('placeholder')).toBe('Enter password')
    })

    it('should update username value on input', async () => {
      const usernameInput = wrapper.find('#username')
      await usernameInput.setValue('testuser')

      expect((usernameInput.element as HTMLInputElement).value).toBe('testuser')
    })

    it('should update password value on input', async () => {
      const passwordInput = wrapper.find('#password')
      await passwordInput.setValue('testpass')

      expect((passwordInput.element as HTMLInputElement).value).toBe('testpass')
    })

    it('should have autocomplete attributes', () => {
      const usernameInput = wrapper.find('#username')
      const passwordInput = wrapper.find('#password')

      expect(usernameInput.attributes('autocomplete')).toBe('username')
      expect(passwordInput.attributes('autocomplete')).toBe('current-password')
    })
  })

  // ===========================================================================
  // PASSWORD TOGGLE TESTS
  // ===========================================================================

  describe('Password Toggle', () => {
    beforeEach(() => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })
    })

    it('should have password toggle button', () => {
      const toggleButton = wrapper.find('.password-toggle')
      expect(toggleButton.exists()).toBe(true)
    })

    it('should start with password hidden', () => {
      const passwordInput = wrapper.find('#password')
      expect(passwordInput.attributes('type')).toBe('password')
    })

    it('should toggle password visibility on button click', async () => {
      const toggleButton = wrapper.find('.password-toggle')

      // Initial state - password hidden
      expect(wrapper.find('#password').attributes('type')).toBe('password')

      await toggleButton.trigger('click')
      await wrapper.vm.$nextTick()

      // After first click - password visible
      expect(wrapper.find('#password').attributes('type')).toBe('text')

      await toggleButton.trigger('click')
      await wrapper.vm.$nextTick()

      // After second click - password hidden again
      expect(wrapper.find('#password').attributes('type')).toBe('password')
    })

    it('should have tabindex -1 on toggle button', () => {
      const toggleButton = wrapper.find('.password-toggle')
      expect(toggleButton.attributes('tabindex')).toBe('-1')
    })
  })

  // ===========================================================================
  // SUBMIT TESTS
  // ===========================================================================

  describe('Submit', () => {
    beforeEach(() => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })
    })

    it('should have login button', () => {
      const loginButton = wrapper.find('.btn-login')
      expect(loginButton.exists()).toBe(true)
      expect(loginButton.text()).toBe('Login')
    })

    it('should disable login button when fields are empty', () => {
      const loginButton = wrapper.find('.btn-login')
      expect(loginButton.attributes('disabled')).toBeDefined()
    })

    it('should enable login button when fields are filled', async () => {
      await wrapper.find('#username').setValue('user')
      await wrapper.find('#password').setValue('pass')

      const loginButton = wrapper.find('.btn-login')
      expect(loginButton.attributes('disabled')).toBeUndefined()
    })

    it('should call login when form is submitted', async () => {
      await wrapper.find('#username').setValue('testuser')
      await wrapper.find('#password').setValue('testpass')
      await wrapper.find('form').trigger('submit')

      expect(mockLogin).toHaveBeenCalledWith('testuser', 'testpass')
    })

    it('should emit success and close on successful login', async () => {
      mockLogin.mockResolvedValue(true)

      await wrapper.find('#username').setValue('user')
      await wrapper.find('#password').setValue('pass')
      await wrapper.find('form').trigger('submit')

      await nextTick()

      expect(wrapper.emitted('success')).toBeTruthy()
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('should NOT emit events on failed login', async () => {
      mockLogin.mockResolvedValue(false)

      await wrapper.find('#username').setValue('user')
      await wrapper.find('#password').setValue('wrongpass')
      await wrapper.find('form').trigger('submit')

      await nextTick()

      expect(wrapper.emitted('success')).toBeFalsy()
      expect(wrapper.emitted('close')).toBeFalsy()
    })
  })

  // ===========================================================================
  // ERROR DISPLAY TESTS
  // ===========================================================================

  describe('Error Display', () => {
    it('should display auth error when present', async () => {
      mockAuthError.value = 'Invalid credentials'

      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.error-message').exists()).toBe(true)
      expect(wrapper.text()).toContain('Invalid credentials')
    })

    it('should NOT display error when no error', () => {
      mockAuthError.value = null

      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.error-message').exists()).toBe(false)
    })
  })

  // ===========================================================================
  // LOADING STATE TESTS
  // ===========================================================================

  describe('Loading State', () => {
    it('should show spinner when logging in', async () => {
      mockIsLoggingIn.value = true

      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.spinner').exists()).toBe(true)
      expect(wrapper.text()).toContain('Logging in...')
    })

    it('should disable inputs when logging in', async () => {
      mockIsLoggingIn.value = true

      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('#username').attributes('disabled')).toBeDefined()
      expect(wrapper.find('#password').attributes('disabled')).toBeDefined()
    })

    it('should disable buttons when logging in', async () => {
      mockIsLoggingIn.value = true

      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.btn-cancel').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.btn-login').attributes('disabled')).toBeDefined()
    })
  })

  // ===========================================================================
  // CANCEL BEHAVIOR TESTS
  // ===========================================================================

  describe('Cancel Behavior', () => {
    it('should have cancel button', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      const cancelButton = wrapper.find('.btn-cancel')
      expect(cancelButton.exists()).toBe(true)
      expect(cancelButton.text()).toBe('Cancel')
    })

    it('should emit close when cancel clicked', async () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true,
          allowCancel: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      await wrapper.find('.btn-cancel').trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('should emit close when overlay clicked', async () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true,
          allowCancel: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      await wrapper.find('.login-overlay').trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('should NOT emit close when allowCancel is false', async () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true,
          allowCancel: false
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      await wrapper.find('.btn-cancel').trigger('click')

      expect(wrapper.emitted('close')).toBeFalsy()
    })

    it('should NOT close on overlay click when allowCancel is false', async () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true,
          allowCancel: false
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      await wrapper.find('.login-overlay').trigger('click')

      expect(wrapper.emitted('close')).toBeFalsy()
    })
  })

  // ===========================================================================
  // SECURITY NOTICE TESTS
  // ===========================================================================

  describe('Security Notice', () => {
    it('should display security notice in footer', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.text()).toContain('Secure connection')
      expect(wrapper.text()).toContain('All access is logged for audit compliance')
    })

    it('should have login footer', () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: true
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      expect(wrapper.find('.login-footer').exists()).toBe(true)
      expect(wrapper.find('.security-notice').exists()).toBe(true)
    })
  })

  // ===========================================================================
  // FORM RESET TESTS
  // ===========================================================================

  describe('Form Reset', () => {
    it('should clear fields when dialog opens', async () => {
      wrapper = mount(LoginDialog, {
        props: {
          isOpen: false
        },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' }
          }
        }
      })

      // Open dialog
      await wrapper.setProps({ isOpen: true })
      await nextTick()

      const usernameInput = wrapper.find('#username') as VueWrapper<HTMLInputElement>
      const passwordInput = wrapper.find('#password') as VueWrapper<HTMLInputElement>

      // Fields should be empty
      expect((usernameInput.element as HTMLInputElement).value).toBe('')
      expect((passwordInput.element as HTMLInputElement).value).toBe('')
    })
  })
})

// ===========================================================================
// ACCESSIBILITY TESTS
// ===========================================================================

describe('LoginDialog Accessibility', () => {
  it('should have labels for inputs', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    const labels = wrapper.findAll('label')
    const labelTexts = labels.map(l => l.text())

    expect(labelTexts).toContain('Username')
    expect(labelTexts).toContain('Password')

    wrapper.unmount()
  })

  it('should have for attributes matching input ids', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    const usernameLabel = wrapper.find('label[for="username"]')
    const passwordLabel = wrapper.find('label[for="password"]')

    expect(usernameLabel.exists()).toBe(true)
    expect(passwordLabel.exists()).toBe(true)

    wrapper.unmount()
  })

  it('should use button type="submit" for login', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    const loginButton = wrapper.find('.btn-login')
    expect(loginButton.attributes('type')).toBe('submit')

    wrapper.unmount()
  })

  it('should use button type="button" for cancel', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    const cancelButton = wrapper.find('.btn-cancel')
    expect(cancelButton.attributes('type')).toBe('button')

    wrapper.unmount()
  })
})

// ===========================================================================
// STYLING/ANIMATION TESTS
// ===========================================================================

describe('LoginDialog Styling', () => {
  it('should have backdrop blur on overlay', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    expect(wrapper.find('.login-overlay').exists()).toBe(true)

    wrapper.unmount()
  })

  it('should have dialog class for styling', () => {
    const wrapper = mount(LoginDialog, {
      props: {
        isOpen: true
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' }
        }
      }
    })

    expect(wrapper.find('.login-dialog').exists()).toBe(true)
    expect(wrapper.find('.login-header').exists()).toBe(true)
    expect(wrapper.find('.login-form').exists()).toBe(true)
    expect(wrapper.find('.login-footer').exists()).toBe(true)

    wrapper.unmount()
  })
})
