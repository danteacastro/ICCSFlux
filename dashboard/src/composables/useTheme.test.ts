/**
 * Tests for Theme Composable
 *
 * Tests cover:
 * - Default theme (dark)
 * - Theme persistence to localStorage
 * - Theme toggling
 * - Theme setting
 * - isDark/isLight helpers
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// We need to reset the module between tests since useTheme uses singleton state
describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset document attribute
    document.documentElement.removeAttribute('data-theme')
    // Reset module to clear singleton state
    vi.resetModules()
  })

  // ===========================================================================
  // DEFAULT STATE TESTS
  // ===========================================================================

  describe('Default State', () => {
    it('should default to dark theme', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme.value).toBe('dark')
    })

    it('should apply dark theme to document', async () => {
      const { useTheme } = await import('./useTheme')
      useTheme()

      expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    })

    it('should save default theme to localStorage', async () => {
      const { useTheme } = await import('./useTheme')
      useTheme()

      expect(localStorage.getItem('nisystem-theme')).toBe('dark')
    })
  })

  // ===========================================================================
  // PERSISTENCE TESTS
  // ===========================================================================

  describe('Persistence', () => {
    it('should restore saved theme from localStorage', async () => {
      localStorage.setItem('nisystem-theme', 'light')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme.value).toBe('light')
    })

    it('should ignore invalid saved theme', async () => {
      localStorage.setItem('nisystem-theme', 'invalid')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme.value).toBe('dark')
    })
  })

  // ===========================================================================
  // THEME SETTING TESTS
  // ===========================================================================

  describe('Theme Setting', () => {
    it('should set theme to light', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      theme.setTheme('light')

      expect(theme.theme.value).toBe('light')
      expect(document.documentElement.getAttribute('data-theme')).toBe('light')
      expect(localStorage.getItem('nisystem-theme')).toBe('light')
    })

    it('should set theme to dark', async () => {
      localStorage.setItem('nisystem-theme', 'light')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      theme.setTheme('dark')

      expect(theme.theme.value).toBe('dark')
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    })
  })

  // ===========================================================================
  // TOGGLE TESTS
  // ===========================================================================

  describe('Theme Toggle', () => {
    it('should toggle from dark to light', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme.value).toBe('dark')
      theme.toggleTheme()
      expect(theme.theme.value).toBe('light')
    })

    it('should toggle from light to dark', async () => {
      localStorage.setItem('nisystem-theme', 'light')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme.value).toBe('light')
      theme.toggleTheme()
      expect(theme.theme.value).toBe('dark')
    })

    it('should persist toggled theme', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      theme.toggleTheme()

      expect(localStorage.getItem('nisystem-theme')).toBe('light')
    })
  })

  // ===========================================================================
  // HELPER FUNCTION TESTS
  // ===========================================================================

  describe('Helper Functions', () => {
    it('isDark should return true for dark theme', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.isDark()).toBe(true)
    })

    it('isDark should return false for light theme', async () => {
      localStorage.setItem('nisystem-theme', 'light')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.isDark()).toBe(false)
    })

    it('isLight should return true for light theme', async () => {
      localStorage.setItem('nisystem-theme', 'light')

      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.isLight()).toBe(true)
    })

    it('isLight should return false for dark theme', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.isLight()).toBe(false)
    })
  })

  // ===========================================================================
  // SINGLETON PATTERN TESTS
  // ===========================================================================

  describe('Singleton Pattern', () => {
    it('should share state across multiple calls', async () => {
      const { useTheme } = await import('./useTheme')

      const theme1 = useTheme()
      const theme2 = useTheme()

      theme1.setTheme('light')

      expect(theme2.theme.value).toBe('light')
    })
  })

  // ===========================================================================
  // API COMPLETENESS TESTS
  // ===========================================================================

  describe('API Completeness', () => {
    it('should export all expected properties', async () => {
      const { useTheme } = await import('./useTheme')
      const theme = useTheme()

      expect(theme.theme).toBeDefined()
      expect(typeof theme.setTheme).toBe('function')
      expect(typeof theme.toggleTheme).toBe('function')
      expect(typeof theme.isDark).toBe('function')
      expect(typeof theme.isLight).toBe('function')
    })
  })
})
