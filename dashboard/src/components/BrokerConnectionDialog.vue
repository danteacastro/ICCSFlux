<script setup lang="ts">
import { ref, watch } from 'vue'
import { useBrokerConfig } from '../composables/useBrokerConfig'
import mqtt from 'mqtt'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  reconnect: []
}>()

const brokerConfig = useBrokerConfig()

const urlInput = ref(brokerConfig.brokerUrl.value)
const usernameInput = ref(brokerConfig.brokerUsername.value)
const passwordInput = ref(brokerConfig.brokerPassword.value)
const testStatus = ref<'idle' | 'testing' | 'success' | 'error'>('idle')
const testMessage = ref('')

// Sync inputs when dialog opens
watch(() => props.modelValue, (open) => {
  if (open) {
    urlInput.value = brokerConfig.brokerUrl.value
    usernameInput.value = brokerConfig.brokerUsername.value
    passwordInput.value = brokerConfig.brokerPassword.value
    testStatus.value = 'idle'
    testMessage.value = ''
  }
})

function isRemoteUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname
    return host !== 'localhost' && host !== '127.0.0.1' && host !== '::1'
  } catch {
    return false
  }
}

async function testConnection() {
  testStatus.value = 'testing'
  testMessage.value = 'Connecting...'

  const options: mqtt.IClientOptions = {
    clientId: `nisystem-test-${Math.random().toString(16).slice(2, 8)}`,
    clean: true,
    connectTimeout: 5000,
    reconnectPeriod: 0, // Don't auto-reconnect for test
  }

  if (usernameInput.value && passwordInput.value) {
    options.username = usernameInput.value
    options.password = passwordInput.value
  }

  try {
    const client = mqtt.connect(urlInput.value, options)

    const result = await new Promise<boolean>((resolve) => {
      const timeout = setTimeout(() => {
        client.end(true)
        resolve(false)
      }, 5000)

      client.on('connect', () => {
        clearTimeout(timeout)
        client.end()
        resolve(true)
      })

      client.on('error', () => {
        clearTimeout(timeout)
        client.end(true)
        resolve(false)
      })
    })

    if (result) {
      testStatus.value = 'success'
      testMessage.value = 'Connection successful'
    } else {
      testStatus.value = 'error'
      testMessage.value = 'Connection failed — check URL and credentials'
    }
  } catch {
    testStatus.value = 'error'
    testMessage.value = 'Connection failed — invalid URL'
  }
}

function applyAndConnect() {
  brokerConfig.setBrokerUrl(urlInput.value)
  if (isRemoteUrl(urlInput.value)) {
    brokerConfig.setBrokerCredentials(usernameInput.value, passwordInput.value)
  } else {
    brokerConfig.setBrokerCredentials('', '')
  }
  emit('update:modelValue', false)
  emit('reconnect')
}

function resetToLocal() {
  brokerConfig.resetToLocal()
  urlInput.value = brokerConfig.DEFAULT_URL
  usernameInput.value = ''
  passwordInput.value = ''
  emit('update:modelValue', false)
  emit('reconnect')
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="broker-dialog-overlay" @click.self="close">
      <div class="broker-dialog">
        <div class="dialog-header">
          <h3>Broker Connection</h3>
          <button class="btn-close" @click="close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="dialog-body">
          <div class="field">
            <label>Broker URL</label>
            <input
              v-model="urlInput"
              type="text"
              placeholder="ws://localhost:9002"
              spellcheck="false"
            />
            <span class="field-hint">
              Local: ws://localhost:9002 | Remote: ws://192.168.1.x:9003
            </span>
          </div>

          <template v-if="isRemoteUrl(urlInput)">
            <div class="field">
              <label>Username</label>
              <input
                v-model="usernameInput"
                type="text"
                placeholder="dashboard"
                autocomplete="username"
              />
            </div>
            <div class="field">
              <label>Password</label>
              <input
                v-model="passwordInput"
                type="password"
                placeholder="From mqtt_credentials.json on target PC"
                autocomplete="current-password"
              />
            </div>
            <div class="remote-notice">
              Remote connections use port 9003 (authenticated WebSocket).
              Get credentials from the target PC's config/mqtt_credentials.json.
            </div>
          </template>

          <div v-if="testMessage" class="test-result" :class="testStatus">
            {{ testMessage }}
          </div>
        </div>

        <div class="dialog-footer">
          <button class="btn-secondary" @click="resetToLocal">Reset to Local</button>
          <div class="footer-right">
            <button
              class="btn-secondary"
              @click="testConnection"
              :disabled="testStatus === 'testing'"
            >
              {{ testStatus === 'testing' ? 'Testing...' : 'Test Connection' }}
            </button>
            <button class="btn-primary" @click="applyAndConnect">Connect</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.broker-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.broker-dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 8px;
  width: 440px;
  max-width: 90vw;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-primary);
}

.dialog-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.btn-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.btn-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.dialog-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.field input {
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
}

.field input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.field-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

.remote-notice {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 4px;
  padding: 10px 12px;
  line-height: 1.5;
}

.test-result {
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 4px;
}

.test-result.testing {
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

.test-result.success {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.test-result.error {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-top: 1px solid var(--border-primary);
}

.footer-right {
  display: flex;
  gap: 8px;
}

.btn-primary,
.btn-secondary {
  padding: 7px 14px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
}

.btn-primary {
  background: var(--accent-primary);
  color: #fff;
  border-color: var(--accent-primary);
}

.btn-primary:hover {
  filter: brightness(1.1);
}

.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-primary);
}

.btn-secondary:hover {
  background: var(--bg-hover);
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
