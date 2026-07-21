<script setup lang="ts">
/**
 * Theme toggle + user/sign-out controls.
 *
 * Shared between the main app header and the P&ID toolbar (full mode only) so
 * the two stay in sync. Emits `login` so the host can open its login dialog.
 */
import { useTheme } from '../composables/useTheme'
import { useAuth } from '../composables/useAuth'

defineEmits<{ (e: 'login'): void }>()

const { theme, toggleTheme } = useTheme()
const auth = useAuth()
</script>

<template>
  <!-- Single root so the internal spacing is identical wherever this is placed
       (main header vs. P&ID toolbar), independent of the container's own gap. -->
  <div class="header-user-controls">
  <!-- Theme Toggle -->
  <button
    class="theme-toggle"
    @click="toggleTheme"
    :title="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
  >
    <svg v-if="theme === 'dark'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
    <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
    </svg>
  </button>

  <!-- User Auth Section -->
  <div class="user-section">
    <template v-if="auth.authenticated.value && auth.currentUser.value">
      <span class="user-info">
        <span class="user-avatar">{{ auth.currentUser.value.username.charAt(0).toUpperCase() }}</span>
        <span class="user-name">{{ auth.currentUser.value.displayName || auth.currentUser.value.username }}</span>
        <span class="user-role">{{ auth.currentUser.value.role }}</span>
      </span>
      <button class="btn-logout" @click="auth.logout()" title="Logout">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
          <polyline points="16,17 21,12 16,7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
      </button>
    </template>
    <template v-else>
      <button class="btn-login" @click="$emit('login')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
          <polyline points="10,17 15,12 10,7"/>
          <line x1="15" y1="12" x2="3" y2="12"/>
        </svg>
        Login
      </button>
    </template>
  </div>
  </div>
</template>

<style scoped>
.header-user-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.theme-toggle:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-light);
}

.user-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-left: 16px;
  border-left: 1px solid var(--border-color);
  margin-left: 8px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-accent);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

.user-name {
  font-size: 0.85rem;
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
}

.user-role {
  font-size: 0.7rem;
  color: var(--text-secondary);
  text-transform: capitalize;
  background: var(--bg-widget);
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.btn-login,
.btn-logout {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  color: var(--color-accent-light);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-login:hover,
.btn-logout:hover {
  background: var(--color-accent-bg);
}

.btn-logout {
  padding: 6px;
  border-color: var(--border-heavy);
  color: var(--text-secondary);
}

.btn-logout:hover {
  border-color: var(--color-error);
  color: var(--color-error);
  background: var(--color-error-bg);
}
</style>
