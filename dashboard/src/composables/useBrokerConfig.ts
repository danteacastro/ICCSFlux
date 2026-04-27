import { ref, computed } from 'vue'

const STORAGE_KEY = 'nisystem-broker-url'
const DEFAULT_URL = 'ws://localhost:9002'
const MAX_URL_LENGTH = 1024

// Validate a broker URL: WebSocket scheme, parseable, hostname present.
// A malformed value in localStorage previously could throw on first parse
// later in the boot path, leaving the dashboard in a half-initialized state.
function isValidBrokerUrl(s: string | null): s is string {
  if (!s || typeof s !== 'string') return false
  if (s.length > MAX_URL_LENGTH) return false
  try {
    const u = new URL(s)
    if (u.protocol !== 'ws:' && u.protocol !== 'wss:') return false
    if (!u.hostname) return false
    return true
  } catch {
    return false
  }
}

// Initial load with validation. If the stored URL is malformed (or absent),
// fall through to the default rather than letting an exception bubble up.
function loadInitialBrokerUrl(): string {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (isValidBrokerUrl(stored)) return stored
  if (stored) {
    console.warn(`[BROKER CONFIG] Stored broker URL is invalid, falling back to default: ${stored}`)
    try { localStorage.removeItem(STORAGE_KEY) } catch { /* private mode */ }
  }
  return DEFAULT_URL
}

// Singleton state (shared across all components that call useBrokerConfig)
const brokerUrl = ref(loadInitialBrokerUrl())
const brokerUsername = ref('')
const brokerPassword = ref('')

export function useBrokerConfig() {
  function setBrokerUrl(url: string) {
    if (!isValidBrokerUrl(url)) {
      console.warn(`[BROKER CONFIG] Refusing to set invalid broker URL: ${url}`)
      return
    }
    brokerUrl.value = url
    localStorage.setItem(STORAGE_KEY, url)
  }

  function setBrokerCredentials(username: string, password: string) {
    brokerUsername.value = username
    brokerPassword.value = password
  }

  function resetToLocal() {
    brokerUrl.value = DEFAULT_URL
    brokerUsername.value = ''
    brokerPassword.value = ''
    localStorage.removeItem(STORAGE_KEY)
  }

  const isRemoteBroker = computed(() => {
    try {
      const url = new URL(brokerUrl.value)
      const host = url.hostname
      return host !== 'localhost' && host !== '127.0.0.1' && host !== '::1'
    } catch {
      return false
    }
  })

  return {
    brokerUrl,
    brokerUsername,
    brokerPassword,
    isRemoteBroker,
    setBrokerUrl,
    setBrokerCredentials,
    resetToLocal,
    DEFAULT_URL,
  }
}
