import { ref, watch } from 'vue'

export type Theme = 'dark' | 'light'

// Singleton state
const theme = ref<Theme>('dark')
let initialized = false

export function useTheme() {
  // Initialize from localStorage on first use
  if (!initialized) {
    initialized = true
    const saved = localStorage.getItem('nisystem-theme') as Theme | null
    if (saved && (saved === 'dark' || saved === 'light')) {
      theme.value = saved
    }
    // Apply immediately
    applyTheme(theme.value)
  }

  function applyTheme(newTheme: Theme) {
    document.documentElement.setAttribute('data-theme', newTheme)
    localStorage.setItem('nisystem-theme', newTheme)
  }

  function setTheme(newTheme: Theme) {
    theme.value = newTheme
    applyTheme(newTheme)
  }

  function toggleTheme() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  // Watch for changes
  watch(theme, (newTheme) => {
    applyTheme(newTheme)
  })

  return {
    theme,
    setTheme,
    toggleTheme,
    isDark: () => theme.value === 'dark',
    isLight: () => theme.value === 'light'
  }
}
