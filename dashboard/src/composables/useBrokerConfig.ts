import { ref, computed } from 'vue'

const STORAGE_KEY = 'nisystem-broker-url'
const DEFAULT_URL = 'ws://localhost:9002'

// Singleton state (shared across all components that call useBrokerConfig)
const brokerUrl = ref(localStorage.getItem(STORAGE_KEY) || DEFAULT_URL)
const brokerUsername = ref('')
const brokerPassword = ref('')

export function useBrokerConfig() {
  function setBrokerUrl(url: string) {
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
