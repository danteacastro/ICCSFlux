<script setup lang="ts">
import { ref, watch } from 'vue'
import type { MonitorNode } from '../types'

const props = defineProps<{
  node: MonitorNode | null  // null = add mode, object = edit mode
}>()

const emit = defineEmits<{
  save: [node: MonitorNode]
  cancel: []
}>()

const form = ref({
  name: '',
  host: '',
  port: 9003,
  username: '',
  password: '',
  enabled: true,
})

// Populate form when editing
watch(() => props.node, (n) => {
  if (n) {
    form.value = { name: n.name, host: n.host, port: n.port, username: n.username, password: n.password, enabled: n.enabled }
  } else {
    form.value = { name: '', host: '', port: 9003, username: '', password: '', enabled: true }
  }
}, { immediate: true })

function submit() {
  if (!form.value.name.trim() || !form.value.host.trim()) return
  emit('save', {
    id: props.node?.id ?? crypto.randomUUID(),
    name: form.value.name.trim(),
    host: form.value.host.trim(),
    port: form.value.port,
    username: form.value.username,
    password: form.value.password,
    enabled: form.value.enabled,
  })
}
</script>

<template>
  <div class="overlay" @click.self="emit('cancel')">
    <div class="modal">
      <h3 class="modal-title">{{ node ? 'Edit Node' : 'Add Node' }}</h3>

      <form @submit.prevent="submit">
        <div class="form-row">
          <label>Display Name</label>
          <input v-model="form.name" type="text" placeholder="e.g. Lab PC #1" required />
        </div>
        <div class="form-row">
          <label>Host / IP</label>
          <input v-model="form.host" type="text" placeholder="e.g. 192.168.1.100" required />
        </div>
        <div class="form-row">
          <label>WebSocket Port</label>
          <input v-model.number="form.port" type="number" min="1" max="65535" />
        </div>
        <div class="form-row">
          <label>MQTT Username</label>
          <input v-model="form.username" type="text" placeholder="from mqtt_credentials.json" />
        </div>
        <div class="form-row">
          <label>MQTT Password</label>
          <input v-model="form.password" type="password" placeholder="from mqtt_credentials.json" />
        </div>
        <div class="form-row checkbox-row">
          <label>
            <input v-model="form.enabled" type="checkbox" />
            Enabled (auto-connect)
          </label>
        </div>

        <div class="actions">
          <button type="button" class="btn-secondary" @click="emit('cancel')">Cancel</button>
          <button type="submit" class="btn-primary">{{ node ? 'Save' : 'Add Node' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.5rem;
  width: 420px;
  max-width: 90vw;
  box-shadow: var(--shadow-xl);
}

.modal-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-bright);
  margin: 0 0 1.25rem;
}

.form-row {
  margin-bottom: 0.875rem;
}

.form-row label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.form-row input[type="text"],
.form-row input[type="password"],
.form-row input[type="number"] {
  width: 100%;
  padding: 0.5rem 0.625rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.875rem;
  font-family: 'JetBrains Mono', monospace;
}

.form-row input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text-primary);
}

.checkbox-row input[type="checkbox"] {
  accent-color: var(--color-accent);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.25rem;
}

.btn-secondary {
  padding: 0.5rem 1rem;
  background: var(--btn-bg);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.85rem;
  transition: all 0.15s;
}

.btn-secondary:hover {
  background: var(--btn-hover);
  color: var(--text-primary);
}

.btn-primary {
  padding: 0.5rem 1rem;
  background: var(--color-accent);
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 500;
  transition: background 0.15s;
}

.btn-primary:hover {
  background: var(--color-accent-dark);
}
</style>
