<script setup lang="ts">
import { ref } from 'vue'
import { useMqtt } from '../composables/useMqtt'

const mqtt = useMqtt()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Form state
const connectionType = ref<'tcp' | 'rtu'>('tcp')
const isLoading = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref<'success' | 'error' | 'warning'>('success')

// TCP settings
const ipAddress = ref('192.168.1.100')
const port = ref(502)

// RTU settings
const serialPort = ref('COM3')
const baudrate = ref(9600)
const parity = ref('N')
const stopbits = ref(1)
const bytesize = ref(8)

// Modbus settings
const currentSlaveId = ref(1)
const registerAddress = ref<number | null>(null)
const newSlaveId = ref(2)

function showFeedback(type: 'success' | 'error' | 'warning', message: string) {
  feedbackType.value = type
  feedbackMessage.value = message
}

async function writeAddress() {
  // Validate inputs
  if (registerAddress.value === null || registerAddress.value < 0) {
    showFeedback('error', 'Please enter a valid register address')
    return
  }

  if (newSlaveId.value < 1 || newSlaveId.value > 247) {
    showFeedback('error', 'Slave ID must be between 1 and 247')
    return
  }

  if (connectionType.value === 'tcp' && !ipAddress.value) {
    showFeedback('error', 'Please enter an IP address')
    return
  }

  if (connectionType.value === 'rtu' && !serialPort.value) {
    showFeedback('error', 'Please enter a serial port')
    return
  }

  isLoading.value = true
  showFeedback('warning', 'Writing to device...')

  try {
    const payload: Record<string, any> = {
      connection_type: connectionType.value,
      slave_id: currentSlaveId.value,
      register_address: registerAddress.value,
      value: newSlaveId.value
    }

    if (connectionType.value === 'tcp') {
      payload.ip_address = ipAddress.value
      payload.port = port.value
    } else {
      payload.serial_port = serialPort.value
      payload.baudrate = baudrate.value
      payload.parity = parity.value
      payload.stopbits = stopbits.value
      payload.bytesize = bytesize.value
    }

    const result = await mqtt.sendCommandWithAck('modbus/write_register', payload, 10000)

    if (result.success) {
      showFeedback('success', (result as any).message || 'Address changed successfully. Device may need power cycle.')
    } else {
      showFeedback('error', (result as any).message || result.error || 'Failed to write register')
    }
  } catch (e: any) {
    showFeedback('error', e.message || 'Command timed out')
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal address-changer">
      <div class="modal-header">
        <h3>Modbus Address Changer</h3>
        <button class="close-btn" @click="emit('close')">&times;</button>
      </div>

      <div class="modal-body">
        <div class="warning-box">
          <strong>Note:</strong> This tool writes a value to a Modbus register. To change a device's
          slave address, you need to know which register holds the address (check your device manual).
          The device may require a power cycle after changing the address.
        </div>

        <!-- Feedback message -->
        <div v-if="feedbackMessage" :class="['feedback', feedbackType]">
          {{ feedbackMessage }}
        </div>

        <!-- Connection Type -->
        <div class="form-row">
          <label>Connection Type</label>
          <select v-model="connectionType">
            <option value="tcp">Modbus TCP (Ethernet)</option>
            <option value="rtu">Modbus RTU (Serial)</option>
          </select>
        </div>

        <!-- TCP Settings -->
        <div v-if="connectionType === 'tcp'" class="form-group">
          <h4>TCP Connection</h4>
          <div class="form-row">
            <label>IP Address</label>
            <input v-model="ipAddress" type="text" placeholder="192.168.1.100" />
          </div>
          <div class="form-row">
            <label>Port</label>
            <input v-model.number="port" type="number" min="1" max="65535" />
          </div>
        </div>

        <!-- RTU Settings -->
        <div v-else class="form-group">
          <h4>Serial Connection</h4>
          <div class="form-row">
            <label>Serial Port</label>
            <input v-model="serialPort" type="text" placeholder="COM3 or /dev/ttyUSB0" />
          </div>
          <div class="form-row-group">
            <div class="form-row half">
              <label>Baud Rate</label>
              <select v-model.number="baudrate">
                <option :value="9600">9600</option>
                <option :value="19200">19200</option>
                <option :value="38400">38400</option>
                <option :value="57600">57600</option>
                <option :value="115200">115200</option>
              </select>
            </div>
            <div class="form-row half">
              <label>Parity</label>
              <select v-model="parity">
                <option value="N">None</option>
                <option value="E">Even</option>
                <option value="O">Odd</option>
              </select>
            </div>
          </div>
          <div class="form-row-group">
            <div class="form-row half">
              <label>Data Bits</label>
              <select v-model.number="bytesize">
                <option :value="7">7</option>
                <option :value="8">8</option>
              </select>
            </div>
            <div class="form-row half">
              <label>Stop Bits</label>
              <select v-model.number="stopbits">
                <option :value="1">1</option>
                <option :value="2">2</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Modbus Settings -->
        <div class="form-group">
          <h4>Address Change</h4>
          <div class="form-row">
            <label>Current Slave ID</label>
            <input v-model.number="currentSlaveId" type="number" min="1" max="247" />
            <span class="hint">The device's current address (1-247)</span>
          </div>
          <div class="form-row">
            <label>Address Register</label>
            <input
              v-model.number="registerAddress"
              type="number"
              min="0"
              max="65535"
              placeholder="e.g., 0, 100, 9999"
            />
            <span class="hint">Holding register that stores the slave address (from device manual)</span>
          </div>
          <div class="form-row">
            <label>New Slave ID</label>
            <input v-model.number="newSlaveId" type="number" min="1" max="247" />
            <span class="hint">The new address to assign (1-247)</span>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn secondary" @click="emit('close')">Cancel</button>
        <button
          class="btn primary"
          @click="writeAddress"
          :disabled="isLoading || registerAddress === null"
        >
          {{ isLoading ? 'Writing...' : 'Write Address' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal.address-changer {
  background: var(--bg-secondary, #1e1e1e);
  border-radius: 8px;
  width: 90%;
  max-width: 480px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid var(--border-color, #333);
}

.modal-header h3 {
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 1.5rem;
  cursor: pointer;
}

.close-btn:hover {
  color: white;
}

.modal-body {
  padding: 1rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 1rem;
  border-top: 1px solid var(--border-color, #333);
}

.warning-box {
  background: #78350f;
  border: 1px solid #f59e0b;
  color: #fef3c7;
  padding: 0.75rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
  line-height: 1.4;
}

.feedback {
  padding: 0.5rem 1rem;
  border-radius: 4px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.feedback.success {
  background: #14532d;
  color: #86efac;
}

.feedback.error {
  background: #7f1d1d;
  color: #fca5a5;
}

.feedback.warning {
  background: #78350f;
  color: #fef3c7;
}

.form-group {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--bg-tertiary, #252525);
  border-radius: 6px;
}

.form-group h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.9rem;
  color: #888;
}

.form-row {
  margin-bottom: 0.75rem;
}

.form-row label {
  display: block;
  font-size: 0.85rem;
  color: #ccc;
  margin-bottom: 0.25rem;
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 0.5rem;
  background: var(--bg-primary, #121212);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  color: white;
}

.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: #3b82f6;
}

.form-row .hint {
  display: block;
  font-size: 0.75rem;
  color: #666;
  margin-top: 0.25rem;
}

.form-row-group {
  display: flex;
  gap: 1rem;
}

.form-row.half {
  flex: 1;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn.primary {
  background: #3b82f6;
  color: white;
}

.btn.primary:hover {
  background: #2563eb;
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.secondary {
  background: #374151;
  color: white;
}

.btn.secondary:hover {
  background: #4b5563;
}
</style>
