<template>
  <Teleport to="body">
    <div v-if="isOpen" class="login-overlay" @click.self="handleOverlayClick">
      <div class="login-dialog">
        <div class="login-header">
          <h2>Login Required</h2>
          <p class="login-subtitle">Please enter your credentials to continue</p>
        </div>

        <form @submit.prevent="handleLogin" class="login-form">
          <div class="form-group">
            <label for="username">Username</label>
            <input
              id="username"
              v-model="username"
              type="text"
              placeholder="Enter username"
              :disabled="isLoggingIn"
              autocomplete="username"
              ref="usernameInput"
            />
          </div>

          <div class="form-group">
            <label for="password">Password</label>
            <div class="password-wrapper">
              <input
                id="password"
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="Enter password"
                :disabled="isLoggingIn"
                autocomplete="current-password"
              />
              <button
                type="button"
                class="password-toggle"
                @click="showPassword = !showPassword"
                tabindex="-1"
              >
                {{ showPassword ? '👁' : '👁‍🗨' }}
              </button>
            </div>
          </div>

          <div v-if="authError" class="error-message">
            {{ authError }}
          </div>

          <div class="form-actions">
            <button
              type="button"
              class="btn-cancel"
              @click="handleCancel"
              :disabled="isLoggingIn"
            >
              Cancel
            </button>
            <button
              type="submit"
              class="btn-login"
              :disabled="isLoggingIn || !username || !password"
            >
              <span v-if="isLoggingIn" class="spinner"></span>
              {{ isLoggingIn ? 'Logging in...' : 'Login' }}
            </button>
          </div>
        </form>

        <div class="login-footer">
          <p class="security-notice">
            🔒 Secure connection • All access is logged for audit compliance
          </p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useAuth } from '../composables/useAuth'

const props = defineProps<{
  isOpen: boolean
  allowCancel?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success'): void
}>()

const { login, authError, isLoggingIn } = useAuth()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const usernameInput = ref<HTMLInputElement | null>(null)

// Focus username input when dialog opens
watch(() => props.isOpen, async (isOpen) => {
  if (isOpen) {
    username.value = ''
    password.value = ''
    await nextTick()
    usernameInput.value?.focus()
  }
})

async function handleLogin() {
  if (!username.value || !password.value) return

  const success = await login(username.value, password.value)

  if (success) {
    emit('success')
    emit('close')
  }
}

function handleCancel() {
  if (props.allowCancel !== false) {
    emit('close')
  }
}

function handleOverlayClick() {
  if (props.allowCancel !== false) {
    emit('close')
  }
}
</script>

<style scoped>
.login-overlay {
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

.login-dialog {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  width: 100%;
  max-width: 400px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  animation: slideIn 0.2s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-20px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.login-header {
  padding: 24px 24px 16px;
  text-align: center;
  border-bottom: 1px solid var(--border-color);
}

.login-header h2 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.login-subtitle {
  margin: 8px 0 0;
  font-size: 0.875rem;
  color: var(--text-muted);
}

.login-form {
  padding: 24px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.form-group input {
  width: 100%;
  padding: 10px 12px;
  font-size: 1rem;
  background: var(--bg-hover);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  transition: border-color 0.2s, box-shadow 0.2s;
  box-sizing: border-box;
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(0, 122, 204, 0.2);
}

.form-group input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-group input::placeholder {
  color: var(--text-muted);
}

.password-wrapper {
  position: relative;
}

.password-wrapper input {
  padding-right: 40px;
}

.password-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 1rem;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.password-toggle:hover {
  opacity: 1;
}

.error-message {
  background: rgba(220, 53, 69, 0.15);
  border: 1px solid rgba(220, 53, 69, 0.3);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 16px;
  color: #ff6b6b;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-message::before {
  content: '⚠️';
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.form-actions button {
  flex: 1;
  padding: 12px 16px;
  font-size: 1rem;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-cancel {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-muted);
}

.btn-cancel:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--text-muted);
}

.btn-login {
  background: var(--color-accent);
  border: none;
  color: white;
}

.btn-login:hover:not(:disabled) {
  background: var(--color-accent-light);
}

.btn-login:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.login-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border-color);
  text-align: center;
}

.security-notice {
  margin: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}
</style>
